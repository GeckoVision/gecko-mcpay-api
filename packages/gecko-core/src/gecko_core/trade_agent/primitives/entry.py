"""Entry primitives — v0.1 stubs.

Each primitive returns an :class:`EntryCandidate` (the trade the agent
*would* take) or ``None`` (no opportunity). Real strategy logic lands in
AIML-2; this module ships the dispatch + canonical signatures so the
runtime and tests can wire end-to-end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gecko_core.trade_agent.spec import EntryBlock, EntryPrimitive


@dataclass
class EntryCandidate:
    """A trade the agent is considering — pre-risk, pre-oracle."""

    mint: str
    side: str = "long"
    nominal_size_usd: float = 0.0
    idea: str = ""
    rule_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


def evaluate_entry(
    spec_entry: EntryBlock,
    event: dict[str, Any],
) -> EntryCandidate | None:
    """Dispatch on ``spec_entry.primitive`` against a hot-path ``event``.

    Event shape (loose, since hot-path producers vary):

    * ``mint`` — the token mint the event refers to (required for v0.1)
    * ``price`` — current price snapshot
    * ``signal`` — primitive-specific payload (drawdown_pct for buy_dip,
      momentum score for momentum_follow, etc.)

    Returns ``None`` if the event doesn't match the primitive's trigger.
    """
    mint = event.get("mint")
    if not mint:
        return None

    primitive: EntryPrimitive = spec_entry.primitive
    params = spec_entry.params
    idea = f"{primitive}:{mint}"

    if primitive == "dca":
        # DCA always wants to enter at its cadence; the scheduler is the
        # trigger, not a hot-path event. Surface a candidate iff the
        # event is a ``dca_tick``.
        if event.get("kind") == "dca_tick":
            return EntryCandidate(
                mint=mint,
                nominal_size_usd=float(params.get("per_tick_usd", 0)),
                idea=idea,
                rule_id=spec_entry.rule_id,
                params=params,
            )
        return None

    if primitive == "buy_dip":
        drawdown_pct = float(event.get("drawdown_pct", 0))
        threshold = float(params.get("drawdown_pct", 5))
        if drawdown_pct >= threshold:
            return EntryCandidate(mint=mint, idea=idea, rule_id=spec_entry.rule_id, params=params)
        return None

    if primitive == "momentum_follow":
        score = float(event.get("momentum", 0))
        threshold = float(params.get("min_momentum", 0.5))
        if score >= threshold:
            return EntryCandidate(mint=mint, idea=idea, rule_id=spec_entry.rule_id, params=params)
        return None

    if primitive == "smart_money_copy":
        # Trigger is a smart-wallet account-sub event from Helius.
        if event.get("kind") == "smart_money_buy":
            return EntryCandidate(mint=mint, idea=idea, rule_id=spec_entry.rule_id, params=params)
        return None

    if primitive == "snipe_new":
        if event.get("kind") == "new_pool":
            return EntryCandidate(mint=mint, idea=idea, rule_id=spec_entry.rule_id, params=params)
        return None

    if primitive == "grid":
        # Grid is order-book shaped — v0.1 not wired; AIML-2 owns.
        return None

    return None


__all__ = ["EntryCandidate", "evaluate_entry"]
