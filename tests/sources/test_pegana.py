"""Recorded-fixture contract tests for the Pegana peg-risk client (Pattern C).

Fixtures in ``fixtures/`` are real captures from ``api.pegana.xyz`` (2026-06-10):
  - INF  — PEGGED at a -1.36% discount (a healthy LST; must NOT be risk-off)
  - sUSD — DRIFT at +2.29% (a real depeg; must be risk-off)

No network in CI: requests are served by an ``httpx.MockTransport``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from gecko_core.sources.pegana import (
    PeganaClient,
    PeganaPegState,
    _risk_from_state,
)

_FIX = Path(__file__).parent / "fixtures"


def _load(name: str) -> object:
    return json.loads((_FIX / name).read_text())


def _handler(request: httpx.Request) -> httpx.Response:
    routes = {
        "/v1/assets": "pegana_assets.json",
        "/v1/assets/INF/state": "pegana_state_inf.json",
        "/v1/assets/sUSD/state": "pegana_state_drift.json",
        "/v1/stats": "pegana_stats.json",
    }
    name = routes.get(request.url.path)
    if name is None:
        return httpx.Response(404)
    return httpx.Response(200, json=_load(name))


def _client() -> PeganaClient:
    transport = httpx.MockTransport(_handler)
    return PeganaClient(client=httpx.AsyncClient(transport=transport))


def test_list_assets_parses() -> None:
    assets = asyncio.run(_client().list_assets())
    assert len(assets) == 21
    by_symbol = {a.symbol: a for a in assets}
    inf = by_symbol["INF"]
    assert inf.asset_class == "lst"  # parsed from the reserved-word "class" field
    assert inf.mint  # mint present for gate-side by-mint lookups


def test_pegged_lst_is_not_risk_off() -> None:
    """INF: PEGGED but -1.36% raw discount. Trust Pegana's class-aware state."""
    risk = asyncio.run(_client().depeg_risk("INF"))
    assert risk.state == "PEGGED"
    assert risk.is_pegged is True
    assert risk.discount_abs > 0.01  # the raw discount really is >1%
    assert risk.risk_off is False  # ...but Pegana says PEGGED, so NOT risk-off


def test_drift_is_risk_off() -> None:
    """sUSD: DRIFT. Must flag risk-off regardless of discount size."""
    risk = asyncio.run(_client().depeg_risk("sUSD"))
    assert risk.state == "DRIFT"
    assert risk.is_pegged is False
    assert risk.risk_off is True


def test_opt_in_discount_threshold_overrides_pegged() -> None:
    """A caller may opt into a stricter cut; then INF's -1.36% trips risk-off."""
    inf_state = PeganaPegState.model_validate(_load("pegana_state_inf.json"))
    default = _risk_from_state(inf_state)
    strict = _risk_from_state(inf_state, discount_threshold=0.005)
    assert default.risk_off is False
    assert strict.risk_off is True


def test_stats_parses() -> None:
    stats = asyncio.run(_client().stats())
    assert stats.assets_tracked == 21
    assert stats.assets_in_drift == stats.by_state.get("DRIFT", 0)
