"""Local-lab panel coordinator.

Fans out a list of voices concurrently, aggregates opinions, calls a
caller-supplied coordinator function for the final ``act / decline``
decision, and logs the result to :class:`local_memory.LocalMemory`.

Design rules locked here (and NOT in any prompt):

* **Voices run concurrently** via ``asyncio.gather(return_exceptions=True)``.
  A single voice raising or timing out cannot block the panel — its
  slot becomes an ``abstain`` opinion with ``confidence=0.0``. Per
  ``feedback-prompt-iteration-plateau`` we keep decision-rule logic
  in code, never in a prompt.
* **Coordinator is injected** as a plain callable. ai-ml-engineer
  ships the rules in ``contest_bot/voices/coordinator_rules.py``;
  this module knows nothing about the specific rules so swapping
  rule sets does not require touching panel plumbing.
* **One write per panel run.** The panel appends a single
  ``local_decision`` row carrying every voice opinion + the final
  action. Voices must never append (see ``MemoryReader`` Protocol in
  ``voices/base.py``).
* **Budget is wall-clock concurrent.** The 8s panel budget is
  enforced by the slowest voice's httpx timeout, not by an
  ``asyncio.wait_for`` here — wrapping ``gather`` in ``wait_for``
  would orphan voice tasks and leak HTTP sockets.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from typing import Any, Literal

from local_memory import LocalMemory
from pydantic import BaseModel, Field
from voices.base import LocalVoice, VoiceOpinion

logger = logging.getLogger(__name__)


LocalAction = Literal["act", "decline"]
# Type alias for the coordinator function. Returns (action, rule_fired)
# where rule_fired is a short identifier the artifact log uses to
# explain which rule produced the decision (e.g. "majority_bullish",
# "any_abstain_block"). ai-ml-engineer owns the rule names.
CoordinatorFn = Callable[[list[VoiceOpinion]], tuple[LocalAction, str | None]]


class LocalDecision(BaseModel):
    """The full output of one panel run."""

    action: LocalAction
    reason: str
    voice_opinions: list[VoiceOpinion]
    coordinator_rule_fired: str | None = None
    total_elapsed_ms: int
    total_cost_usd: float
    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)


class LocalPanel:
    """Concurrent voice runner + coordinator.

    Typical wire:

        panel = LocalPanel(
            voices=[chart_analyst, memory_voice, risk_voice],
            memory=LocalMemory(),
            coordinator=majority_vote,  # from voices/coordinator_rules.py
        )
        decision = await panel.run(market_state)
        if decision.action != "act":
            return  # bot declines

    The panel is stateless across runs — every call to :meth:`run`
    starts fresh. State (rolling PnL, prior decisions) lives in the
    voices via the injected ``LocalMemory``.
    """

    def __init__(
        self,
        voices: list[LocalVoice],
        memory: LocalMemory,
        coordinator: CoordinatorFn,
    ) -> None:
        if not voices:
            # A panel with zero voices would always decline (since the
            # coordinator sees an empty list) and would silently
            # neutralize the bot. Raise loudly at construction so the
            # operator sees the misconfig at startup, not on the first
            # trade signal.
            raise ValueError("LocalPanel requires at least one voice")
        self._voices = voices
        self._memory = memory
        self._coordinator = coordinator

    async def run(self, market_state: dict[str, Any]) -> LocalDecision:
        """Run all voices concurrently and aggregate."""
        started = time.monotonic()
        # Gather with return_exceptions so a single voice failure does
        # NOT collapse the whole panel. Failed voices become abstain
        # opinions below.
        results = await asyncio.gather(
            *(self._safe_grade(voice, market_state) for voice in self._voices),
            return_exceptions=True,
        )

        opinions: list[VoiceOpinion] = []
        for voice, result in zip(self._voices, results, strict=False):
            if isinstance(result, VoiceOpinion):
                opinions.append(result)
            else:
                # ``_safe_grade`` already converts known errors to
                # abstain opinions; anything that still leaks here is
                # an unexpected exception type. Belt-and-suspenders.
                exc_name = type(result).__name__ if result is not None else "Unknown"
                logger.warning(
                    "panel: voice %s raised unexpected %s; abstaining",
                    getattr(voice, "voice_name", "unknown"),
                    exc_name,
                )
                opinions.append(_abstain_for_exception(voice, exc_name, elapsed_ms=0))

        action, rule_fired = self._coordinator(opinions)
        total_elapsed_ms = int((time.monotonic() - started) * 1000)
        total_cost_usd = round(sum((o.cost_usd or 0.0) for o in opinions), 6)

        reason = _build_reason(action, opinions, rule_fired)
        decision = LocalDecision(
            action=action,
            reason=reason,
            voice_opinions=opinions,
            coordinator_rule_fired=rule_fired,
            total_elapsed_ms=total_elapsed_ms,
            total_cost_usd=total_cost_usd,
        )

        self._memory.append(
            "local_decision",
            payload={
                "action": action,
                "reason": reason,
                "coordinator_rule_fired": rule_fired,
                "total_elapsed_ms": total_elapsed_ms,
                "total_cost_usd": total_cost_usd,
                "voice_opinions": [o.model_dump() for o in opinions],
                "market_state": market_state,
            },
            decision_id=decision.decision_id,
        )
        return decision

    async def _safe_grade(self, voice: LocalVoice, market_state: dict[str, Any]) -> VoiceOpinion:
        """Run one voice and convert any exception to an abstain.

        This is what makes the panel resilient: even with
        ``return_exceptions=True``, ``asyncio.gather`` only catches
        exceptions raised inside the coroutine. By doing the same
        catch here we keep a uniform return type and avoid the
        ``isinstance(result, BaseException)`` dance in the caller.
        """
        voice_started = time.monotonic()
        try:
            opinion = await voice.grade(market_state, self._memory)
        except Exception as exc:
            voice_elapsed_ms = int((time.monotonic() - voice_started) * 1000)
            logger.warning(
                "panel: voice %s raised %s; producing abstain",
                getattr(voice, "voice_name", "unknown"),
                type(exc).__name__,
            )
            return _abstain_for_exception(voice, type(exc).__name__, voice_elapsed_ms)
        return opinion


def _abstain_for_exception(voice: LocalVoice, exc_name: str, elapsed_ms: int) -> VoiceOpinion:
    """Construct an abstain opinion for a voice that raised."""
    return VoiceOpinion(
        voice_name=getattr(voice, "voice_name", "unknown"),
        verdict="abstain",
        confidence=0.0,
        reasoning=f"exception: {exc_name}",
        observations=[],
        raw_response="",
        elapsed_ms=elapsed_ms,
        cost_usd=None,
    )


def _build_reason(
    action: LocalAction,
    opinions: list[VoiceOpinion],
    rule_fired: str | None,
) -> str:
    """One-line summary for the log feed."""
    bull = sum(1 for o in opinions if o.verdict == "bullish")
    bear = sum(1 for o in opinions if o.verdict == "bearish")
    neutral = sum(1 for o in opinions if o.verdict == "neutral")
    abst = sum(1 for o in opinions if o.verdict == "abstain")
    rule = rule_fired or "unspecified"
    return f"{action} via {rule}: {bull}B/{bear}S/{neutral}N/{abst}A ({len(opinions)} voices)"


__all__ = [
    "CoordinatorFn",
    "LocalAction",
    "LocalDecision",
    "LocalPanel",
]
