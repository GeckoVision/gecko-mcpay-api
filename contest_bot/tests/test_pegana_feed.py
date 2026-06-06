"""S48 — Pegana peg-risk feed. Pure + injected-client; NO real network."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pegana_feed as pf  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class _StubClient:
    """Minimal httpx.Client stand-in. `routes` maps a path suffix → payload (or an
    Exception instance to raise). `calls` records every path hit (dedup assertions)."""

    def __init__(self, routes, *, raise_all=False):
        self.routes = routes
        self.raise_all = raise_all
        self.calls: list[str] = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        if self.raise_all:
            raise RuntimeError("network down")
        for suffix, payload in self.routes.items():
            if url.endswith(suffix):
                if isinstance(payload, Exception):
                    raise payload
                return _Resp(payload)
        raise RuntimeError(f"no route for {url}")


_ASSETS = [
    {"symbol": "USDC", "state": "PEGGED", "discount": -0.0001, "confidence": 0.99},
    {"symbol": "jitoSOL", "state": "DRIFT", "discount": -0.018, "confidence": 0.95},
    {"symbol": "INF", "state": "CRITICAL", "discount": -0.052, "confidence": 0.97},
]


def _client(**kw):
    return pf.PeganaClient(http_client=_StubClient({"/assets": _ASSETS}), **kw)


# ── happy path ──────────────────────────────────────────────────────────────
def test_peg_states_one_call_filters_all():
    stub = _StubClient({"/assets": _ASSETS})
    cli = pf.PeganaClient(http_client=stub)
    out = cli.peg_states(["USDC", "jitoSOL", "INF"])
    assert out["USDC"]["state"] == "PEGGED"
    assert out["jitoSOL"]["state"] == "DRIFT" and out["jitoSOL"]["discount"] == -0.018
    assert out["INF"]["state"] == "CRITICAL"
    # ONE /assets call covered all three (no per-asset fallback needed)
    assert sum("/assets/" in c for c in stub.calls) == 0
    assert sum(c.endswith("/assets") for c in stub.calls) == 1


def test_peg_states_case_insensitive():
    out = _client().peg_states(["jitosol"])  # lower-case request matches jitoSOL
    assert out["jitosol"]["state"] == "DRIFT"


def test_peg_states_cached_within_ttl():
    stub = _StubClient({"/assets": _ASSETS})
    cli = pf.PeganaClient(http_client=stub, cache_ttl=30.0)
    cli.peg_states(["USDC"], now=1000.0)
    cli.peg_states(["jitoSOL"], now=1010.0)  # within TTL → no second fetch
    assert sum(c.endswith("/assets") for c in stub.calls) == 1


def test_peg_states_refetches_after_ttl():
    stub = _StubClient({"/assets": _ASSETS})
    cli = pf.PeganaClient(http_client=stub, cache_ttl=30.0)
    cli.peg_states(["USDC"], now=1000.0)
    cli.peg_states(["USDC"], now=1040.0)  # past TTL → refetch
    assert sum(c.endswith("/assets") for c in stub.calls) == 2


# ── per-asset fallback ──────────────────────────────────────────────────────
def test_peg_states_per_asset_fallback_for_missing_symbol():
    # /assets lacks "MEW"; client falls back to /assets/MEW/state
    stub = _StubClient(
        {"/assets": _ASSETS, "/assets/MEW/state": {"asset": "MEW", "state": "DEPEG", "discount": -0.04}}
    )
    cli = pf.PeganaClient(http_client=stub)
    out = cli.peg_states(["MEW"])
    assert out["MEW"]["state"] == "DEPEG"


# ── fail-open ───────────────────────────────────────────────────────────────
def test_peg_states_network_error_returns_empty():
    cli = pf.PeganaClient(http_client=_StubClient({}, raise_all=True))
    assert cli.peg_states(["USDC", "jitoSOL"]) == {}  # fail-open


def test_peg_states_empty_symbols():
    assert _client().peg_states([]) == {}


def test_peg_states_garbage_payload_is_unknown():
    stub = _StubClient({"/assets": [{"symbol": "USDC"}]})  # no state field
    out = pf.PeganaClient(http_client=stub).peg_states(["USDC"])
    assert out["USDC"]["state"] == "UNKNOWN"  # coerced, never raises


def test_peg_states_non_list_payload_fails_open():
    stub = _StubClient({"/assets": {"oops": "object not array"}})
    assert pf.PeganaClient(http_client=stub).peg_states(["USDC"]) == {}


# ── asset map ───────────────────────────────────────────────────────────────
def test_asset_map():
    assert pf.pegana_symbol_for("stable_spread") == "USDC"
    assert pf.pegana_symbol_for("lst_staking") == "jitoSOL"
    assert pf.pegana_symbol_for("jlp_fees") == "USDC"
    assert pf.pegana_symbol_for("rwa_credit") is None
    assert pf.pegana_symbol_for("equity") is None


def test_peg_states_for_sources_keys_by_yield_source():
    stub = _StubClient({"/assets": _ASSETS})
    cli = pf.PeganaClient(http_client=stub)
    out = pf.peg_states_for_sources(["lst_staking", "stable_spread", "rwa_credit"], client=cli)
    assert out["lst_staking"]["state"] == "DRIFT"
    assert out["stable_spread"]["state"] == "PEGGED"
    assert "rwa_credit" not in out  # untracked leg absent


def test_peg_states_for_sources_failopen():
    cli = pf.PeganaClient(http_client=_StubClient({}, raise_all=True))
    assert pf.peg_states_for_sources(["lst_staking"], client=cli) == {}
