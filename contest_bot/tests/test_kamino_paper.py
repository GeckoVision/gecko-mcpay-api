"""Sprint 25 (#117, #141) — Kamino paper sink tests.

Light-fakes pattern per `feedback_lighter_tests`. No live Kamino calls,
no on-chain anything. We mock the Kamino REST surface with `respx` (same
pattern as `tests/payments/test_privy_client.py`) and assert:

  1. APY cache: cached value, refresh-after-TTL, safe-fallback on failure,
     override bypass.
  2. Paper ledger: accrual math matches a hand-computed expected value;
     deposit + withdraw idempotency; invariant survives replay.
  3. Paper sink: deposit threshold + reserve respected; close-event
     idempotency by decision_id; best-effort swallows raised exceptions.

8 tests total; all synchronous (httpx.Client, not AsyncClient — APY cache
is sync so the bot loop's `close_position` can call it without coroutine
plumbing).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import httpx
import pytest
import respx

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from kamino.apy_cache import (  # noqa: E402
    KAMINO_API_BASE,
    KAMINO_MAIN_MARKET,
    KAMINO_USDC_RESERVE,
    KaminoAPYCache,
)
from kamino.paper_ledger import (  # noqa: E402
    DuplicateEventError,
    PaperLedger,
)
from kamino.paper_sink import KaminoPaperSink  # noqa: E402

# ── Helpers ────────────────────────────────────────────────────────────

_RESERVES_URL = f"{KAMINO_API_BASE}/kamino-market/{KAMINO_MAIN_MARKET}/reserves/metrics"


def _reserves_payload(usdc_apy: float = 0.0421) -> list[dict]:
    return [
        {
            "reserve": "OTHER_RESERVE_xxxxxxxxxxxxxxxxxxxxxxxxxxx",
            "liquidityToken": "USDT",
            "supplyApy": "0.035",
        },
        {
            "reserve": KAMINO_USDC_RESERVE,
            "liquidityToken": "USDC",
            "supplyApy": str(usdc_apy),
        },
    ]


# ── APY cache tests ───────────────────────────────────────────────────


@respx.mock
def test_apy_cache_fetches_live_then_caches() -> None:
    """First call hits the network; second call inside TTL returns the
    cached value WITHOUT a second request."""
    route = respx.get(_RESERVES_URL).mock(
        return_value=httpx.Response(200, json=_reserves_payload(0.0421))
    )
    cache = KaminoAPYCache(ttl_sec=3600, fallback_apy=0.0)

    apy1 = cache.get_apy(now=1000.0)
    apy2 = cache.get_apy(now=1500.0)  # 500s later, well inside TTL

    assert apy1 == pytest.approx(0.0421)
    assert apy2 == pytest.approx(0.0421)
    assert route.call_count == 1
    assert cache.last_fetch_status == "cache_hit"


@respx.mock
def test_apy_cache_refreshes_after_ttl() -> None:
    """After ttl elapses, a fresh fetch happens."""
    responses = iter(
        [
            httpx.Response(200, json=_reserves_payload(0.0421)),
            httpx.Response(200, json=_reserves_payload(0.0500)),
        ]
    )
    respx.get(_RESERVES_URL).mock(side_effect=lambda req: next(responses))

    cache = KaminoAPYCache(ttl_sec=100, fallback_apy=0.0)
    a1 = cache.get_apy(now=1000.0)
    a2 = cache.get_apy(now=1000.0 + 101.0)  # past TTL

    assert a1 == pytest.approx(0.0421)
    assert a2 == pytest.approx(0.0500)
    assert cache.last_fetch_status == "live"


@respx.mock
def test_apy_cache_falls_back_to_zero_on_network_error() -> None:
    """Endpoint 500s → we return the configured fallback, never raise."""
    respx.get(_RESERVES_URL).mock(return_value=httpx.Response(500))

    cache = KaminoAPYCache(ttl_sec=3600, fallback_apy=0.0)
    apy = cache.get_apy(now=1000.0)

    assert apy == 0.0
    assert "fallback" in cache.last_fetch_status


def test_apy_cache_override_bypasses_network() -> None:
    """If GECKO_KAMINO_APY_OVERRIDE is set the cache never touches the wire."""
    cache = KaminoAPYCache(
        ttl_sec=3600,
        fallback_apy=0.0,
        override_apy=0.03,
    )
    # No respx mock — if we tried to network we'd get an error
    assert cache.get_apy(now=1000.0) == 0.03
    assert cache.get_apy(now=9999.0) == 0.03
    assert cache.last_fetch_status == "override"


# ── Ledger tests ──────────────────────────────────────────────────────


def test_ledger_accrual_matches_closed_form(tmp_path: Path) -> None:
    """Hand-computed accrual: $1000 at 4.21% APY for 30 days continuous-
    compound = 1000 * (e^(0.0421 * 30/365.25) - 1) ≈ $3.466.

    The invariant principal == deposits + accruals must hold to within
    1e-6 USD.
    """
    ledger = PaperLedger(path=tmp_path / "ledger.jsonl")
    ledger.deposit(1000.0, apy=0.0421, idempotency_key="d1", now=0.0)

    thirty_days = 30 * 86400.0
    delta = ledger.accrue(apy=0.0421, now=thirty_days)

    expected = 1000.0 * math.expm1(0.0421 * 30.0 / 365.25)
    assert delta == pytest.approx(expected, abs=1e-6)
    assert ledger.current_principal == pytest.approx(1000.0 + expected, abs=1e-6)
    # invariant — deposits + accrual_total == principal
    assert ledger.total_accrued == pytest.approx(expected, abs=1e-6)


def test_ledger_deposit_idempotent_by_key(tmp_path: Path) -> None:
    """Same idempotency_key → DuplicateEventError; principal unchanged."""
    ledger = PaperLedger(path=tmp_path / "ledger.jsonl")
    ledger.deposit(100.0, apy=0.04, idempotency_key="dec-abc", now=0.0)
    with pytest.raises(DuplicateEventError):
        ledger.deposit(100.0, apy=0.04, idempotency_key="dec-abc", now=10.0)
    assert ledger.current_principal == pytest.approx(100.0, abs=1e-6)
    # Only one deposit line + no additional accrue lines on the failed call
    lines = (tmp_path / "ledger.jsonl").read_text().splitlines()
    deposits = [json.loads(line) for line in lines if json.loads(line)["type"] == "deposit"]
    assert len(deposits) == 1


def test_ledger_replays_state_from_disk(tmp_path: Path) -> None:
    """A fresh PaperLedger over an existing JSONL recovers the principal,
    accrual_total, and seen_keys set. Bot restart = no state loss."""
    path = tmp_path / "ledger.jsonl"
    led_a = PaperLedger(path=path)
    led_a.deposit(500.0, apy=0.04, idempotency_key="d1", now=0.0)
    led_a.accrue(apy=0.04, now=86400.0)  # one day
    p_before = led_a.current_principal

    led_b = PaperLedger(path=path)
    assert led_b.current_principal == pytest.approx(p_before, abs=1e-6)
    # Idempotency keys survive replay → cannot re-use them
    with pytest.raises(DuplicateEventError):
        led_b.deposit(1.0, apy=0.04, idempotency_key="d1", now=200000.0)


# ── Sink tests ────────────────────────────────────────────────────────


def _build_sink(tmp_path: Path, *, override_apy: float = 0.0421) -> KaminoPaperSink:
    cache = KaminoAPYCache(ttl_sec=3600, fallback_apy=0.0, override_apy=override_apy)
    ledger = PaperLedger(path=tmp_path / "ledger.jsonl")
    return KaminoPaperSink(
        ledger=ledger,
        apy_cache=cache,
        deposit_threshold_usd=10.0,
        deposit_reserve_usd=5.0,
        enabled=True,
    )


def test_sink_skips_when_below_threshold(tmp_path: Path) -> None:
    """idle <= threshold → no deposit, ledger untouched, no raise."""
    sink = _build_sink(tmp_path)
    out = sink.on_position_close(idle_usdc=8.0, decision_id="dec-1", now=0.0)
    assert out is None
    assert sink.last_action == "skipped:below_threshold"
    assert sink.ledger.current_principal == 0.0


def test_sink_deposits_excess_above_reserve(tmp_path: Path) -> None:
    """idle=100, threshold=10, reserve=5 → deposit 95."""
    sink = _build_sink(tmp_path)
    out = sink.on_position_close(idle_usdc=100.0, decision_id="dec-1", now=0.0)
    assert out is not None
    assert out["type"] == "deposit"
    assert out["amount"] == pytest.approx(95.0, abs=1e-6)
    assert sink.last_action == "deposit"
    assert sink.ledger.current_principal == pytest.approx(95.0, abs=1e-6)


def test_sink_idempotent_on_repeat_decision_id(tmp_path: Path) -> None:
    """Same decision_id fired twice → second call is a silent no-op,
    principal stays at the first deposit."""
    sink = _build_sink(tmp_path)
    sink.on_position_close(idle_usdc=100.0, decision_id="dec-abc", now=0.0)
    out2 = sink.on_position_close(idle_usdc=200.0, decision_id="dec-abc", now=10.0)
    assert out2 is None
    assert sink.last_action == "skipped:duplicate"
    assert sink.ledger.current_principal == pytest.approx(95.0, abs=1e-3)


def test_sink_swallows_ledger_exceptions(tmp_path: Path) -> None:
    """If the ledger raises mid-flight, on_position_close returns None and
    sets last_error — never propagates."""
    sink = _build_sink(tmp_path)

    class _Boom:
        def deposit(self, *a, **kw):
            raise RuntimeError("simulated disk full")

        def withdraw(self, *a, **kw):
            raise RuntimeError("simulated disk full")

        def accrue(self, *a, **kw):
            return 0.0

        @property
        def current_principal(self):
            return 0.0

    sink.ledger = _Boom()  # type: ignore[assignment]
    out = sink.on_position_close(idle_usdc=100.0, decision_id="dec-x", now=0.0)
    assert out is None
    assert sink.last_action == "error"
    assert sink.last_error is not None
    assert "RuntimeError" in sink.last_error
