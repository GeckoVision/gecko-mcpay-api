"""`jto_breakout` legacy wrapper — preserves the memecoin bot bit-for-bit.

The live monolith's legacy path keeps its OWN gate chain (evaluate_breakout +
volume_spike OR + safety + net_flow + BTC overlay + panel + MFI hard-gate). When
`GECKO_STRATEGY` is unset/`jto_breakout`, the monolith does NOT consult this
object and does NOT override its exit constants — so behavior is unchanged. This
class exists only so `load_strategy("jto_breakout")` returns a valid Strategy and
so the legacy rule is expressible in the same contract for tests.

`should_enter` fires iff the caller has already found a breakout candidate
(`features["legacy_breakout"]` truthy) — i.e. it delegates the decision to the
existing pipeline rather than re-deriving it.
"""

from __future__ import annotations

from .base import ExitPolicy, Signal
from .spec import StrategySpec


def default_spec() -> StrategySpec:
    # mirrors the memecoin live constants; NOT applied by the monolith (legacy path
    # keeps its module-level exit globals) — present for completeness/tests only.
    return StrategySpec(
        strategy_id="jto_breakout",
        version="legacy",
        universe=["PYTH", "WIF"],
        timeframe="5m",
        venue="onchainos",
        entry_gates={"delegated": True},
        exit={"tp_pct": 4.0, "sl_pct": 3.0, "time_stop_min": 720},
    )


class JtoBreakoutLegacy:
    def __init__(self, spec: StrategySpec | None = None) -> None:
        self.spec = spec or default_spec()

    def should_enter(self, features: dict[str, object]) -> Signal | None:
        if not features.get("legacy_breakout"):
            return None
        return Signal(side="long", reason="jto_breakout (delegated)", features=dict(features))

    def exit_policy(self) -> ExitPolicy:
        e = self.spec.exit
        return ExitPolicy(tp_pct=e["tp_pct"], sl_pct=e["sl_pct"], time_stop_min=e["time_stop_min"])
