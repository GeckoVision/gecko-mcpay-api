import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from kamino import catalog as cat  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402


def _client() -> TestClient:
    import agent_api

    return TestClient(agent_api.app)


_FAKE = [
    LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"),
    LeverageStrategy("JitoSOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
    LeverageStrategy("JLP 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees"),
]


@pytest.fixture(autouse=True)
def _stub_catalog(monkeypatch):
    monkeypatch.setattr(cat, "load_catalog", lambda *a, **k: _FAKE)


def test_conservative_menu_only_lend():
    j = _client().get("/vault/catalog?profile=conservative").json()
    assert j["profile"] == "conservative"
    assert [o["name"] for o in j["options"]] == ["USDC lend"]
    # field contract for the app's picker row
    for o in j["options"]:
        assert {"name", "net_apy", "net_apy_after_cost", "leverage", "min_hold_days"} <= set(o)
    assert "_strategy" not in j["options"][0]  # internal object never crosses the wire


def test_aggressive_menu_ranked_with_min_hold():
    j = _client().get("/vault/catalog?profile=aggressive").json()
    assert len(j["options"]) == 3
    nets = [o["net_apy_after_cost"] for o in j["options"]]
    assert nets == sorted(nets, reverse=True)
    assert all("min_hold_days" in o for o in j["options"])


def test_moderate_alias_normalizes_to_balanced():
    j = _client().get("/vault/catalog?profile=moderate").json()
    assert j["profile"] == "Balanced"


def test_unknown_profile_422():
    r = _client().get("/vault/catalog?profile=yolo")
    assert r.status_code == 422


def test_cost_params_change_min_hold():
    # both costs are non-zero (zero cost ⇒ min_hold is None — no break-even to clear)
    cheap = (
        _client()
        .get(
            "/vault/catalog?profile=aggressive&entry_swap_bps=2&flash_fee_bps=1&exit_swap_bps=2&gas_bps=0"
        )
        .json()
    )
    pricey = (
        _client()
        .get(
            "/vault/catalog?profile=aggressive&entry_swap_bps=50&flash_fee_bps=20&exit_swap_bps=50&gas_bps=10"
        )
        .json()
    )
    # higher round-trip cost ⇒ longer break-even hold for the same market
    c = {o["name"]: o["min_hold_days"] for o in cheap["options"]}
    p = {o["name"]: o["min_hold_days"] for o in pricey["options"]}
    common = [n for n in c if c[n] is not None and p.get(n) is not None]
    assert common and all(p[n] > c[n] for n in common)
