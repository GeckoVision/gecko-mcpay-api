"""Profile-filtered, cost-aware ranking of the Kamino catalog → a pick menu.

The V1 risk profiles (Conservative / Balanced / Aggressive, aligned to Kamino's
risk categories) act as a FILTER over the catalog: which yield sources are
allowed, the max leverage, and the minimum liquidation-headroom. Survivors are
ranked by net-APY-after-cost (so a high-headline-APY position with a long
break-even ranks below a modest one held past break-even), each row carrying its
minimum-hold period. The user picks one from the returned menu.
"""

from __future__ import annotations

from kamino.multiply import LeverageStrategy, min_hold_period, net_apy_after_cost
from kamino.vault_orchestrator import normalize_profile

# profile -> (allowed yield_sources, max_leverage, min_ltv_headroom)
PROFILE_RULES: dict[str, dict] = {
    "conservative": {
        "sources": {"stable_spread"},
        "max_leverage": 1.0,
        "min_headroom": 0.0,
    },
    "Balanced": {
        "sources": {"stable_spread", "lst_staking"},
        "max_leverage": 5.0,
        "min_headroom": 0.05,
    },
    "aggressive": {
        "sources": {"stable_spread", "lst_staking", "jlp_fees", "rwa_credit", "equity"},
        "max_leverage": 10.0,
        "min_headroom": 0.0,
    },
}


def _passes(s: LeverageStrategy, rule: dict) -> bool:
    return (
        s.yield_source in rule["sources"]
        and s.leverage <= rule["max_leverage"] + 1e-9
        and s.ltv_headroom >= rule["min_headroom"] - 1e-9
        and s.net_apy > 0
    )


def rank_catalog(
    catalog: list[LeverageStrategy],
    *,
    profile: str,
    principal: float,
    cost: float,
    horizon_years: float,
) -> list[dict]:
    """Filter by profile, rank by net-APY-after-cost, attach min-hold. The menu."""
    rule = PROFILE_RULES[normalize_profile(profile)]
    rows: list[dict] = []
    for s in catalog:
        if not _passes(s, rule):
            continue
        t = min_hold_period(s, principal, cost)
        rows.append(
            {
                "name": s.name,
                "net_apy": round(s.net_apy, 4),
                "net_apy_after_cost": round(net_apy_after_cost(s, cost, horizon_years), 4),
                "leverage": s.leverage,
                "liquidation_drop_pct": round(s.liquidation_drop_pct, 4),
                "min_hold_days": round(t * 365.0, 1) if t is not None else None,
                "_strategy": s,
            }
        )
    rows.sort(key=lambda r: r["net_apy_after_cost"], reverse=True)
    return rows
