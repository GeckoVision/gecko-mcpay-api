"""The adaptive switcher — a PURE router (regime -> strategy).

Reads the live regime, applies safety overlays first, then picks ONE active
strategy. Pure: same inputs -> same choice, so it is backtestable + verifiable.
No I/O, no state mutation — the caller threads `hysteresis_state` and
`open_position` in and gets a decision out.

Overlay precedence (STRICT, safety always wins):
    1. market_temp risk_off   -> FLAT_YIELD (route idle USDC to Kamino lend)
    2. pegana depeg flag       -> FLAT
    3. safety_gate blocked     -> FLAT
    4. regime router (TREND-UP / CHOP / TREND-DOWN)
    5. vol-target sizing overlay (applied by the caller to the chosen strategy)

Hysteresis (anti-whipsaw): the new regime label must hold for >=N consecutive
1h reads before the router switches strategies. And NEVER flip strategy with an
open position — the caller drains/closes under the active strategy's own exit
first, then re-routes.

Every FLAT decision carries the gate name that fired (the verification artifact:
"we correctly stood down" vs "we sat out lazily").
"""

from __future__ import annotations

from dataclasses import dataclass, field

# decision tokens
TREND = "trend_breakout_regime"
RANGE = "range_fade"
FLAT = "FLAT"
FLAT_YIELD = "FLAT_YIELD"  # route idle USDC -> Kamino lend (active capital pres.)


@dataclass
class SwitchDecision:
    active: str  # one of {TREND, RANGE, FLAT, FLAT_YIELD}
    reason: str  # the gate / regime that produced it (artifact log)
    held: bool = False  # True if hysteresis blocked an otherwise-pending switch


@dataclass
class HysteresisState:
    """Per-symbol regime-confirmation state, threaded by the caller across reads.
    `pending_label` is the candidate new regime; `pending_count` how many
    consecutive reads it has held; `confirmed_label` the regime currently in
    force for routing."""

    confirmed_label: str = "CHOP"
    pending_label: str | None = None
    pending_count: int = 0


@dataclass
class SwitchConfig:
    """Switcher knobs. These COUNT in the DSR n_trials (quant-gate review §1.3)
    unless declared frozen-from-prior in the pre-registration."""

    hysteresis_reads: int = 2  # consecutive 1h reads to confirm a regime switch
    risk_off_temp: float = -0.25  # market_temp <= this -> FLAT_YIELD
    chop_temp_floor: float = -0.08  # range_fade needs market_temp > this


def _norm(label: object) -> str:
    return str(label or "").upper().replace("_", "-")


def confirm_regime(
    state: HysteresisState, observed_label: str, cfg: SwitchConfig | None = None
) -> tuple[HysteresisState, bool]:
    """Advance the hysteresis state with a new observed 1h regime label.

    Returns (new_state, switched) where `switched` is True iff the confirmed
    label changed on this read. Pure: returns a NEW state, does not mutate.
    """
    cfg = cfg or SwitchConfig()
    obs = _norm(observed_label)
    if obs == state.confirmed_label:
        # back to the confirmed regime — clear any pending switch
        return HysteresisState(confirmed_label=obs, pending_label=None, pending_count=0), False
    # a different label than confirmed
    count = state.pending_count + 1 if state.pending_label == obs else 1
    if count >= cfg.hysteresis_reads:
        return HysteresisState(confirmed_label=obs, pending_label=None, pending_count=0), True
    return (
        HysteresisState(
            confirmed_label=state.confirmed_label, pending_label=obs, pending_count=count
        ),
        False,
    )


def select_strategy(
    *,
    market_temp: float | None,
    risk_off: bool,
    pegana_depeg: bool,
    safety_blocked: bool,
    confirmed_regime: str,
    btc_regime: str,
    has_open_position: bool,
    current_active: str | None,
    cfg: SwitchConfig | None = None,
) -> SwitchDecision:
    """The router. Returns the strategy that SHOULD be active given the live read.

    `confirmed_regime` is the hysteresis-confirmed instrument 1h regime (use
    `confirm_regime` to produce it). `btc_regime` is the BTC 1h regime overlay.
    The caller passes `has_open_position` so we never flip mid-position.
    """
    cfg = cfg or SwitchConfig()

    # ── 1-3. SAFETY OVERLAY FIRST (safety always wins, even over an open pos) ──
    if risk_off or (market_temp is not None and market_temp <= cfg.risk_off_temp):
        return SwitchDecision(FLAT_YIELD, "safety:risk_off -> yield-park")
    if pegana_depeg:
        return SwitchDecision(FLAT, "safety:pegana_depeg")
    if safety_blocked:
        return SwitchDecision(FLAT, "safety:safety_gate")

    # ── never flip strategy with an open position (drain under its own exit) ──
    if has_open_position and current_active:
        return SwitchDecision(
            current_active, f"hold:open_position keeps {current_active}", held=True
        )

    # ── 2. REGIME ROUTER (switch-don't-sit-out core) ──
    reg = _norm(confirmed_regime)
    btc = _norm(btc_regime)
    mt = market_temp if market_temp is not None else 0.0

    if btc == "TREND-DOWN" or reg == "TREND-DOWN":
        return SwitchDecision(FLAT_YIELD, "regime:TREND-DOWN -> hedge-by-absence + yield")
    if reg == "TREND-UP":
        return SwitchDecision(TREND, "regime:TREND-UP -> trend_breakout_regime")
    if reg == "CHOP":
        if mt > cfg.chop_temp_floor:
            return SwitchDecision(RANGE, "regime:CHOP -> range_fade (fee-width gate inside)")
        return SwitchDecision(FLAT, f"regime:CHOP but market_temp {mt:+.2f}<=floor -> flat")
    # transitional / unknown
    return SwitchDecision(FLAT, f"regime:{reg or 'unknown'} -> flat")


@dataclass
class SwitcherRun:
    """Convenience container if a caller wants to keep both states together."""

    hyst: dict[str, HysteresisState] = field(default_factory=dict)
    active: dict[str, str | None] = field(default_factory=dict)
