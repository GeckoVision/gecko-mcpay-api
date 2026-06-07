import math
import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from kamino.multiply import (  # noqa: E402
    LeverageStrategy,
    min_hold_period,
    net_apy_after_cost,
    round_trip_cost,
)
from kamino.vault_orchestrator import PROFILE_BASKETS, normalize_profile  # noqa: E402


def _lst(lev=4.0):
    return LeverageStrategy("JitoSOL/SOL", 0.07, 0.06, lev, 0.90, 0.93, True, "lst_staking")


def test_round_trip_cost_sums_legs():
    # 10 bps entry swap + 5 bps flash + 10 bps exit swap + 2 bps gas = 0.0027
    c = round_trip_cost(entry_swap_bps=10, flash_fee_bps=5, exit_swap_bps=10, gas_bps=2)
    assert abs(c - 0.0027) < 1e-9


def test_min_hold_period_positive_yield():
    s = _lst(4.0)  # net_apy = 0.07 + 0.01*3 = 0.10
    cost = 0.0027
    t = min_hold_period(s, principal=1000.0, cost=cost)
    assert t is not None and abs(t - (math.log(1 + cost) / math.log(1.10))) < 1e-6


def test_min_hold_period_none_when_no_yield():
    s = LeverageStrategy("bleeder", 0.04, 0.06, 4.0, 0.90, 0.93, True, "lst_staking")  # net<0
    assert min_hold_period(s, 1000.0, 0.0027) is None


def test_net_apy_after_cost_amortizes():
    s = _lst(4.0)  # net 0.10
    assert abs(net_apy_after_cost(s, cost=0.0027, horizon_years=0.5) - (0.10 - 0.0027 / 0.5)) < 1e-9


def test_balanced_is_canonical_moderate_is_alias():
    assert "Balanced" in PROFILE_BASKETS
    assert "moderate" not in PROFILE_BASKETS  # old key gone from the dict
    assert normalize_profile("moderate") == "Balanced"  # back-compat alias
    assert normalize_profile("Balanced") == "Balanced"
    assert normalize_profile("conservative") == "conservative"
