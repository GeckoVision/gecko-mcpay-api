"""Phase-0 Fix 0.2 — CVD net-flow against REAL onchainos ``token trades`` shape.

These tests exercise the parser against captured-live fixtures (no network):
  tests/fixtures/onchainos_trades_pyth.json  — PYTH, mixed SOL/USDC/JUP quotes
  tests/fixtures/onchainos_trades_wif.json   — WIF, all SOL-quoted
  tests/fixtures/onchainos_price_sol.json    — SOL token price-info

The pre-S44 parser probed flat usd_amount/usdAmount/amount keys that DO NOT
exist in this shape → always 0.0 → every trade skipped → CVD always neutral →
the wave-2b gate was a silent no-op. The regression test documents that bug;
the real-shape tests prove the changedTokenInfo-quote-leg reconstruction works
across BOTH quoting regimes (USDC-quoted ≈ 1, SOL-quoted = SOL/USD).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from net_flow import _parse_usd, _resolve_quote_prices, cache_clear, compute_net_flow

_FIX = Path(__file__).resolve().parent / "fixtures"
_PYTH_MINT = "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"
_WIF_MINT = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"


def _load(name: str) -> Any:
    return json.loads((_FIX / name).read_text())


def _trades(name: str) -> list[dict]:
    return _load(name)["data"]


@pytest.fixture(autouse=True)
def _clear_cache():
    cache_clear()
    yield
    cache_clear()


def _oc_for(trades_file: str) -> Any:
    """Fake onchainos that returns the captured trades + the captured SOL price
    for the WSOL mint (and a 1.0-ish dummy for any other looked-up mint)."""
    sol_resp = _load("onchainos_price_sol.json")
    fake = MagicMock()
    fake.get_token_trades.return_value = _trades(trades_file)

    def _price_info(addr: str) -> dict:
        if addr == "So11111111111111111111111111111111111111112":
            return sol_resp
        # JUP / others — return a plausible price so they are priceable.
        return {"data": [{"price": "0.5"}]}

    fake.get_price_info.side_effect = _price_info
    fake.get_signals.return_value = []
    return fake


# ── regression: the OLD key-probing returns 0 on the real shape ──────────


def test_old_flat_usd_keys_absent_in_real_shape() -> None:
    """Documents the bug: real trades carry NONE of the flat usd_* keys the
    pre-S44 parser probed — so that parser always returned 0.0 → silent no-op."""
    for trade in _trades("onchainos_trades_pyth.json") + _trades("onchainos_trades_wif.json"):
        for legacy_key in ("usd_amount", "usdAmount", "amount_usd", "amountUsd", "amount"):
            assert legacy_key not in trade, (
                f"unexpected flat key {legacy_key!r} in real trade — fixture drift"
            )
        # The data IS there, just under changedTokenInfo (the leg list).
        assert isinstance(trade.get("changedTokenInfo"), list)
        assert trade.get("type") in ("buy", "sell")


# ── real-shape reconstruction ────────────────────────────────────────────


def test_resolve_quote_prices_sol_only_wif() -> None:
    oc = _oc_for("onchainos_trades_wif.json")
    prices = _resolve_quote_prices(_trades("onchainos_trades_wif.json"), _WIF_MINT, oc)
    wsol = "so11111111111111111111111111111111111111112"
    assert wsol in prices
    assert prices[wsol] > 50  # SOL/USD is ~$85 in the fixture, not ~1


def test_resolve_quote_prices_multi_quote_pyth() -> None:
    """PYTH fixture has SOL, USDC, and JUP quote legs — all must price."""
    oc = _oc_for("onchainos_trades_pyth.json")
    prices = _resolve_quote_prices(_trades("onchainos_trades_pyth.json"), _PYTH_MINT, oc)
    usdc = "epjfwdd5aufqssqem2qn1xzybapc8g4weggkzwytdt1v"
    wsol = "so11111111111111111111111111111111111111112"
    assert prices[usdc] == 1.0  # stablecoin short-circuit, no network call
    assert prices[wsol] > 50


def test_parse_usd_reads_quote_leg_sol() -> None:
    """A SOL-quoted trade reconstructs to ~ quote_amount × SOL_USD."""
    trade = _trades("onchainos_trades_wif.json")[0]
    quote_prices = {"so11111111111111111111111111111111111111112": 84.96}
    usd = _parse_usd(trade, _WIF_MINT, quote_prices)
    # Cross-check against the response's own `volume` field (USD value).
    assert usd == pytest.approx(float(trade["volume"]), rel=0.02)
    assert usd > 0


def test_parse_usd_old_key_probe_would_return_zero() -> None:
    """Belt-and-suspenders: feeding an EMPTY quote_prices map (the moral
    equivalent of the old no-op) yields 0.0 on a real trade."""
    trade = _trades("onchainos_trades_wif.json")[0]
    assert _parse_usd(trade, _WIF_MINT, {}) == 0.0


def test_compute_net_flow_wif_non_neutral_and_signed() -> None:
    """End-to-end on the REAL WIF shape: heavy net selling in the fixture must
    yield a non-neutral verdict and a correctly-signed (negative) net flow."""
    oc = _oc_for("onchainos_trades_wif.json")
    result = compute_net_flow(_WIF_MINT, "WIF", oc)
    assert result is not None
    assert result.trade_count > 0, "every trade was skipped — parser no-op regressed"
    assert result.verdict != "neutral", "real distribution should not read as neutral"
    # The captured WIF window is net selling → distribution → negative net flow.
    assert result.verdict == "distribution"
    assert result.net_flow_usd < 0


def test_compute_net_flow_pyth_prices_all_quote_regimes() -> None:
    """End-to-end on the REAL PYTH shape (mixed SOL/USDC/JUP quotes): trades
    are actually counted (no silent no-op) and buy/sell USD are both non-zero."""
    oc = _oc_for("onchainos_trades_pyth.json")
    result = compute_net_flow(_PYTH_MINT, "PYTH", oc)
    assert result is not None
    assert result.trade_count > 0
    assert result.buy_usd > 0
    assert result.sell_usd > 0


def test_compute_net_flow_matches_volume_field_aggregate() -> None:
    """The reconstructed total USD must track the sum of each trade's own
    `volume` (USD) field to within live SOL-price drift (~2%)."""
    oc = _oc_for("onchainos_trades_wif.json")
    result = compute_net_flow(_WIF_MINT, "WIF", oc)
    assert result is not None
    expected_total = sum(float(t["volume"]) for t in _trades("onchainos_trades_wif.json"))
    assert (result.buy_usd + result.sell_usd) == pytest.approx(expected_total, rel=0.03)
