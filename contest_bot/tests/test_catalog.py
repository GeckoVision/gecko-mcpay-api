import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino.catalog import CURATED_FALLBACK, load_catalog, normalize_market  # noqa: E402
from kamino.multiply import LeverageStrategy  # noqa: E402

# Real Kamino reserve-metrics row shape (keys confirmed against the live endpoint).
RAW = {
    "liquidityToken": "JitoSOL",
    "supplyApy": 0.07,
    "borrowApy": 0.06,
    "maxLtv": 0.90,
}


def test_normalize_market_to_leverage_strategy():
    s = normalize_market(RAW, leverage=4.0, correlated=True, yield_source="lst_staking")
    assert isinstance(s, LeverageStrategy)
    assert abs(s.collateral_yield - 0.07) < 1e-9
    assert abs(s.borrow_rate - 0.06) < 1e-9
    assert abs(s.max_ltv - 0.90) < 1e-9
    # liquidation threshold derived from maxLtv (feed doesn't expose it)
    assert s.liquidation_ltv > s.max_ltv and s.liquidation_ltv <= 0.98


def test_load_catalog_falls_back_when_fetch_fails():
    def boom():
        raise RuntimeError("api down")

    cat = load_catalog(fetch=boom)
    assert cat == CURATED_FALLBACK and len(cat) >= 3


def test_load_catalog_normalizes_injected_rows():
    rows = [
        {"liquidityToken": "USDC", "supplyApy": 0.037, "borrowApy": 0.057, "maxLtv": 0.8},
        {"liquidityToken": "JitoSOL", "supplyApy": 0.08, "borrowApy": 0.10, "maxLtv": 0.74},
        {"bad": "row"},  # skipped, not fatal
    ]
    cat = load_catalog(fetch=lambda: rows)
    assert [s.name for s in cat] == ["USDC", "JitoSOL"]
    assert cat[0].yield_source == "stable_spread"
    assert cat[1].yield_source == "lst_staking"
