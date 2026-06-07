import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino.multiply import LeverageStrategy  # noqa: E402
from kamino.selector import rank_catalog  # noqa: E402


def _cat():
    return [
        LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"),
        LeverageStrategy("JitoSOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
        LeverageStrategy("JLP 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees"),
    ]


def test_conservative_filters_out_leverage_and_uncorrelated():
    menu = rank_catalog(
        _cat(), profile="conservative", principal=1000.0, cost=0.0027, horizon_years=0.5
    )
    assert [m["name"] for m in menu] == ["USDC lend"]  # only no-liquidation-surface


def test_aggressive_includes_all_ranked_by_net_after_cost():
    menu = rank_catalog(
        _cat(), profile="aggressive", principal=1000.0, cost=0.0027, horizon_years=0.5
    )
    assert len(menu) == 3
    nets = [m["net_apy_after_cost"] for m in menu]
    assert nets == sorted(nets, reverse=True)
    assert all("min_hold_days" in m for m in menu)


def test_balanced_accepts_alias_moderate():
    a = rank_catalog(_cat(), profile="moderate", principal=1000.0, cost=0.0027, horizon_years=0.5)
    b = rank_catalog(_cat(), profile="Balanced", principal=1000.0, cost=0.0027, horizon_years=0.5)
    assert [m["name"] for m in a] == [m["name"] for m in b]
