"""The SendAI-style pre-trade firewall consumer (the MISSING surface).

``docs/architecture/firewall-e2e.md`` §5.3: "the SendAI firewall-consumer surface
does not exist" — the in-repo ``exec_adapters/sendai.py`` is *execution* only. This
module is its missing counterpart: the gate an agent consults **before** it acts.

Two pieces:

  * :func:`pretrade_check` — calls ``/safety`` (via an injected reader), maps the
    gate to ``{proceed, gate, reasons}``:
        - ``block``                  → ``proceed=False``
        - ``caution``                → ``proceed=True`` WITH ``flagged=True``
        - ``ok`` / ``unknown``       → ``proceed=True``
  * :class:`FirewallGate` — wraps :func:`pretrade_check` behind the SAME
    ``submit(*, mint, side, size_usd)`` signature as
    :class:`gecko_core.trade_agent.exec_adapters.sendai.SendAIExecAdapter`, so it
    reads as "the firewall gate the SendAI adapter consults before executing." The
    execution itself stays stubbed — this surface only DECIDES; it never sends.

The ``/safety`` reader is injected (a ``SafetyReader`` callable) so the SAME code
runs against either a real HTTP call to ``gecko-api`` OR an in-process
``safety_fast.serve_safety`` bound to a shared store (the dev entrypoint chooses).
That keeps stub and live on identical code paths (the payments principle, applied
to the firewall gate).
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# A reader returns the ``/safety`` response dict for a mint (the shape
# ``PrecomputedSafety.to_response`` / ``serve_safety`` produce).
SafetyReader = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class PretradeDecision:
    """The pre-trade gate decision an agent acts on."""

    mint: str
    proceed: bool
    gate: str
    reasons: list[str]
    flagged: bool = False  # caution → proceed-with-flag

    def to_dict(self) -> dict[str, Any]:
        return {
            "mint": self.mint,
            "proceed": self.proceed,
            "gate": self.gate,
            "reasons": self.reasons,
            "flagged": self.flagged,
        }


def _reasons_from_safety(safety: dict[str, Any]) -> list[str]:
    """Collect the fired signal codes (wash + snipe) as the decision reasons."""
    reasons: list[str] = []
    snipe = safety.get("snipe") or {}
    wash = safety.get("wash_risk") or {}
    if snipe.get("label"):
        reasons.append(f"snipe={snipe['label']}")
    reasons.extend(snipe.get("fired_signals") or [])
    if wash.get("label"):
        reasons.append(f"wash={wash['label']}")
    reasons.extend(wash.get("fired_signals") or [])
    # Static contract flags, if any rode along on the cold path.
    reasons.extend(safety.get("rug_flags") or [])
    return reasons


def decide(mint: str, safety: dict[str, Any]) -> PretradeDecision:
    """Pure mapping from a ``/safety`` response to a :class:`PretradeDecision`."""
    gate = str(safety.get("gate", "unknown"))
    proceed = gate != "block"
    flagged = gate == "caution"
    return PretradeDecision(
        mint=mint,
        proceed=proceed,
        gate=gate,
        reasons=_reasons_from_safety(safety),
        flagged=flagged,
    )


async def pretrade_check(mint: str, reader: SafetyReader) -> PretradeDecision:
    """Consult ``/safety`` for ``mint`` and return the pre-trade decision.

    ``reader`` is the injected ``/safety`` accessor (HTTP or in-process). Any
    error from the reader is surfaced verbatim (we do not swallow firewall
    failures); a caller that wants fail-OPEN can catch it and treat ``unknown``
    as proceed — but the default here is to let the failure propagate.
    """
    safety = await reader(mint)
    decision = decide(mint, safety)
    logger.info(
        "firewall.pretrade mint=%s gate=%s proceed=%s flagged=%s",
        mint,
        decision.gate,
        decision.proceed,
        decision.flagged,
    )
    return decision


@dataclass
class FirewallGate:
    """The firewall gate the SendAI adapter consults before executing.

    Mirrors :class:`SendAIExecAdapter.submit` so it slots in as the pre-execution
    check: same ``submit(*, mint, side, size_usd)`` shape. But where the exec
    adapter *sends*, this gate *decides* — it returns ``{proceed, gate, reasons}``
    and an ``executed`` flag that is always ``False`` here (execution stays
    stubbed). A real integration would call the exec adapter only when
    ``proceed`` is true.
    """

    reader: SafetyReader
    name: str = "firewall_gate"
    record: Callable[..., Awaitable[Any]] | None = None  # optional ledger writer
    source: str = "fork"
    _last_sink: list[str] = field(default_factory=list, repr=False)

    async def submit(self, *, mint: str, side: str, size_usd: float) -> dict[str, Any]:
        """Consult the firewall, optionally record the verdict, return the gate.

        The return shape intentionally echoes the exec adapter's
        ``{"mode", "ok", "intent"}`` so a caller swapping the firewall gate in
        front of the SendAI adapter sees a familiar envelope, with the firewall
        decision attached. ``ok`` here means "cleared to execute" (``proceed``),
        NOT "executed".
        """
        safety = await self.reader(mint)
        decision = decide(mint, safety)

        sink: str | None = None
        if self.record is not None:
            snipe = safety.get("snipe") or {}
            wash = safety.get("wash_risk") or {}
            _row, sink = await self.record(
                mint=mint,
                gate=decision.gate,
                snipe_label=snipe.get("label"),
                snipe_fired=list(snipe.get("fired_signals") or []),
                wash_label=wash.get("label"),
                wash_fired=list(wash.get("fired_signals") or []),
                source=self.source,
            )
            if sink is not None:
                self._last_sink.append(sink)

        intent = {"rail": "firewall_gate->sendai", "mint": mint, "side": side, "size_usd": size_usd}
        logger.info(
            "firewall.gate.submit mint=%s side=%s size_usd=%s -> proceed=%s gate=%s",
            mint,
            side,
            size_usd,
            decision.proceed,
            decision.gate,
        )
        return {
            "mode": "gate",
            "ok": decision.proceed,  # cleared to execute (not executed)
            "executed": False,  # execution stays stubbed in this slice
            "decision": decision.to_dict(),
            "ledger_sink": sink,
            "intent": intent,
        }


__all__ = [
    "FirewallGate",
    "PretradeDecision",
    "SafetyReader",
    "decide",
    "pretrade_check",
]
