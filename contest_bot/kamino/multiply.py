"""Kamino Multiply economics — pure, no network.

S42 profit-vault. Models a leveraged-looping position the way Kamino Multiply
actually behaves, so we can simulate 5x (and any leverage) and reason about
net APY, liquidation distance, and — crucially — whether the yield clears the
user's hurdle rate, WITHOUT touching mainnet.

The whole economics is one formula (verified against Kamino's own 8x JitoSOL
example: 7% yield, 6% borrow, 8x → 14% net):

    net_apy = collateral_yield + (collateral_yield - borrow_rate) * (leverage - 1)

i.e. you leverage the SPREAD, not the asset. A positive spread widens with
leverage; a NEGATIVE spread (borrow > yield) deepens with leverage — "there is
no floor." That asymmetry is the entire risk and the reason the monitor exists.

This module is the read-model; `monitor.py` is the decision layer on top.
Pattern B (CLAUDE.md): this local simulation is the FIRST deliverable, the
falsifier. Devnet/mainnet is the final verification, never the debug tool.
"""

from __future__ import annotations

from dataclasses import dataclass

# Where the yield comes from = what the risk actually is. The monitor keys off this.
YIELD_SOURCES = {
    "stable_spread",  # yield-bearing stable vs borrow stable — only spread/rate risk
    "lst_staking",  # SOL LST staking yield, SOL debt — depeg-protected, SOL-denominated
    "rwa_credit",  # Maple / mortgages / reinsurance — counterparty DEFAULT risk, slow exit
    "jlp_fees",  # Jupiter perps LP fees — JLP is ~65% volatile crypto, real liquidation
    "equity",  # tokenized stocks — directional, NO yield floor
}


@dataclass(frozen=True)
class LeverageStrategy:
    """A single Multiply (or un-leveraged, leverage=1.0) yield position.

    Rates are APY fractions (0.07 == 7%). `max_ltv` is the eMode/standard cap;
    `liquidation_ltv` is where the position is force-closed. `correlated=True`
    means both legs move together (LST/SOL, stable/stable) so there is no
    PRICE liquidation risk — only spread inversion. `correlated=False` (JLP,
    equities) carries genuine price-liquidation risk.
    """

    name: str
    collateral_yield: float
    borrow_rate: float
    leverage: float
    max_ltv: float
    liquidation_ltv: float
    correlated: bool
    yield_source: str

    def __post_init__(self) -> None:
        if self.leverage < 1.0:
            raise ValueError(f"leverage must be >= 1.0, got {self.leverage}")
        if self.yield_source not in YIELD_SOURCES:
            raise ValueError(f"unknown yield_source {self.yield_source!r}")

    @property
    def spread(self) -> float:
        """Collateral yield minus borrow cost. Negative = bleeding under leverage."""
        return self.collateral_yield - self.borrow_rate

    @property
    def spread_inverted(self) -> bool:
        """Borrow costs more than the collateral yields — leverage now multiplies a loss."""
        return self.spread < 0.0

    @property
    def net_apy(self) -> float:
        """Net APY on the user's EQUITY after borrow drag. The one number that matters."""
        return self.collateral_yield + self.spread * (self.leverage - 1.0)

    @property
    def operating_ltv(self) -> float:
        """debt/collateral at this leverage = (L-1)/L. 8x → 0.875, matches Kamino's example."""
        return (self.leverage - 1.0) / self.leverage if self.leverage > 0 else 0.0

    @property
    def ltv_headroom(self) -> float:
        """How far operating LTV sits below the liquidation threshold. <0 = already underwater."""
        return self.liquidation_ltv - self.operating_ltv

    @property
    def liquidation_drop_pct(self) -> float:
        """Adverse % move on the collateral leg that triggers liquidation — the
        founder's intuitive risk number. If collateral price drops by d, the new
        LTV = operating_ltv / (1 - d); liquidation hits when that == liquidation_ltv,
        so  d = 1 - operating_ltv / liquidation_ltv.

        Returns a FRACTION (0.10 == a 10% drop wipes you out). This is the buffer
        we compare the Oracle's predicted downside against.

        Worked: 10x with liq_ltv≈1.0 → operating 0.90 → d = 10% (founder's '1000x10
        dies on a 10% drop'). 5x → operating 0.80 → d = 20% (the '5x security margin').

        For CORRELATED pairs (LST/SOL, stable/stable) both legs move together, so a
        market-wide drop doesn't change the ratio — this number then represents the
        DEPEG tolerance of the collateral vs its debt, which is large and stake-pool
        protected. The monitor only treats it as price-liquidation risk when
        `correlated` is False.
        """
        if self.liquidation_ltv <= 0:
            return 1.0
        d = 1.0 - (self.operating_ltv / self.liquidation_ltv)
        return max(0.0, d)

    def with_rates(self, collateral_yield: float, borrow_rate: float) -> LeverageStrategy:
        """Clone with refreshed live rates (the monitor re-reads these on cadence)."""
        return LeverageStrategy(
            name=self.name,
            collateral_yield=collateral_yield,
            borrow_rate=borrow_rate,
            leverage=self.leverage,
            max_ltv=self.max_ltv,
            liquidation_ltv=self.liquidation_ltv,
            correlated=self.correlated,
            yield_source=self.yield_source,
        )

    def with_leverage(self, leverage: float) -> LeverageStrategy:
        """Clone at a different leverage (used to solve for the leverage that clears a hurdle)."""
        return LeverageStrategy(
            name=self.name,
            collateral_yield=self.collateral_yield,
            borrow_rate=self.borrow_rate,
            leverage=leverage,
            max_ltv=self.max_ltv,
            liquidation_ltv=self.liquidation_ltv,
            correlated=self.correlated,
            yield_source=self.yield_source,
        )


def leverage_to_clear(
    base: LeverageStrategy, target_net_apy: float, max_leverage: float | None = None
) -> float | None:
    """Solve for the leverage that makes net_apy == target, capped at max_leverage
    (defaults to the strategy's eMode ceiling derived from max_ltv: L_max = 1/(1-max_ltv)).

    Returns None if the spread is non-positive (no leverage can clear a hurdle when
    the spread doesn't pay) or if the required leverage exceeds the cap.

    From net = y + spread*(L-1) → L = 1 + (target - y)/spread.
    """
    if base.spread <= 0:
        return None  # a non-positive spread can't be levered into a real yield
    cap = max_leverage if max_leverage is not None else (1.0 / (1.0 - base.max_ltv))
    needed = 1.0 + (target_net_apy - base.collateral_yield) / base.spread
    if needed <= 1.0:
        return 1.0  # un-leveraged already clears it
    if needed > cap + 1e-9:
        return None  # can't get there within the safe leverage ceiling
    return round(needed, 4)


def project_balance(principal: float, net_apy: float, years: float) -> float:
    """Continuously-ish compounded balance projection (annual compounding)."""
    return principal * ((1.0 + net_apy) ** years)


def time_to_target(principal: float, net_apy: float, target_gain_usd: float) -> float | None:
    """Years to grow `principal` by `target_gain_usd` at `net_apy` (annual compounding).

    Returns None if net_apy <= 0 (never reaches a positive target). The founder's
    canonical question: '$1000 → +$100, how long?'
    """
    if net_apy <= 0 or principal <= 0 or target_gain_usd <= 0:
        return None
    import math

    ratio = (principal + target_gain_usd) / principal
    return math.log(ratio) / math.log(1.0 + net_apy)


# ── Round-trip cost + minimum-hold period (S48 profit-vault) ──────────────────
# The founder's question: "what's the minimum period to make a Multiply worth it,
# and don't liquidate before that." A leveraged loop has a real open+close cost
# (entry swap + flash-loan fee + exit swap + gas); the position only turns net
# positive once accrued yield clears that cost. `min_hold_period` is that
# break-even horizon; the monitor's min-hold lock keys off it.


def round_trip_cost(
    entry_swap_bps: float, flash_fee_bps: float, exit_swap_bps: float, gas_bps: float = 0.0
) -> float:
    """Total open+close cost as a FRACTION of equity. bps → fraction (/10_000)."""
    return (entry_swap_bps + flash_fee_bps + exit_swap_bps + gas_bps) / 10_000.0


def min_hold_period(strat: LeverageStrategy, principal: float, cost: float) -> float | None:
    """Years to hold before accrued net yield clears the round-trip `cost`
    (fraction of equity). The 'don't liquidate before this' number. None if the
    position never earns (net_apy <= 0). Reuses time_to_target."""
    return time_to_target(principal, strat.net_apy, cost * principal)


def net_apy_after_cost(strat: LeverageStrategy, cost: float, horizon_years: float) -> float:
    """net_apy with the round-trip cost amortized over `horizon_years` — the
    ranking metric. A high-APY position with a long break-even ranks below a
    modest one held past break-even."""
    if horizon_years <= 0:
        return strat.net_apy
    return strat.net_apy - (cost / horizon_years)
