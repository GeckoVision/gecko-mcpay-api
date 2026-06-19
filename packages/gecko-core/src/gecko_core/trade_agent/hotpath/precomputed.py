"""Pre-computed safety verdict + the shared gate kernel for the Launch Firewall.

Step 2 of the Launch Firewall build order. Two things live here:

1. :func:`safety_gate` — the ONE canonical pre-trade gate kernel (Pattern A).
   It was born inline in ``gecko_api.main._safety_gate``; moving it here lets the
   continuous monitor and the FastAPI endpoint score with the *identical*
   function instead of two drifting copies. It is **duck-typed** (reads attrs via
   ``getattr``) so it stays hotpath-clean — it does NOT import ``SafetyBlock``
   from ``orchestration`` (that would drag db-adjacent code into the latency
   island). The endpoint keeps a thin ``_safety_gate`` that delegates here.

2. :class:`PrecomputedSafety` — what the monitor writes to the fast store and the
   serve path reads. The gate is pre-computed at WRITE time, so a warm read is a
   dict lookup + freshness check (single-digit ms), never a network call.

Hotpath isolation: ``pydantic`` + stdlib only. The ``safety`` payload is carried
as a plain ``dict`` (the ``SafetyBlock.model_dump(mode="json")`` the endpoint
already produces) rather than the typed model, so this module never imports
``orchestration``. The serve layer maps dict <-> model at the boundary.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.trade_agent.hotpath.wash_signals import WashRiskBlock

# --------------------------------------------------------------------------- #
# The shared gate kernel (Pattern A — one canonical scorer)                    #
# --------------------------------------------------------------------------- #

_BLOCK_FLAGS = frozenset({"fake_market_cap", "depeg_risk"})
_CAUTION_FLAGS = frozenset(
    {
        "thin_liquidity_vs_mcap",
        "high_holder_concentration",
        "mint_not_renounced",
        "freeze_not_renounced",
    }
)


def safety_gate(block: Any, *, wash: WashRiskBlock | None = None) -> str:
    """One-glance pre-trade gate derived from the deterministic safety read.

    Duck-typed over a ``SafetyBlock``-shaped object (``checked`` / ``rug_flags``
    / ``honeypot`` / ``information_mev``). Optionally folds in the Launch-Firewall
    :class:`WashRiskBlock` flow read — a ``manipulated`` wash verdict is a hard
    ``block``, an ``elevated`` one is at least ``caution``.

    - ``block``   — honeypot, fake market cap, material depeg, a ``manipulated``
      Information-MEV read, OR a ``manipulated`` wash read.
    - ``caution`` — elevated manipulation / thin liquidity / holder concentration
      / un-renounced mint or freeze authority / ``elevated`` wash read.
    - ``ok``      — checked and clean.
    - ``unknown`` — the check could not run (fail-OPEN; never trust as safe).
    """
    if not getattr(block, "checked", False):
        # Static read didn't run — but a wash read alone can still be decisive.
        if wash is not None and wash.label == "manipulated":
            return "block"
        if wash is not None and wash.label == "elevated":
            return "caution"
        return "unknown"

    flags = set(getattr(block, "rug_flags", None) or [])
    if getattr(block, "honeypot", False) or (flags & _BLOCK_FLAGS):
        return "block"

    imev = getattr(block, "information_mev", None)
    imev_label = getattr(imev, "label", None) if imev is not None else None
    if imev_label == "manipulated" or (wash is not None and wash.label == "manipulated"):
        return "block"

    wash_elevated = wash is not None and wash.label == "elevated"
    if imev_label == "elevated" or wash_elevated or (flags & _CAUTION_FLAGS):
        return "caution"
    return "ok"


# --------------------------------------------------------------------------- #
# The pre-computed verdict the monitor writes + the serve path reads           #
# --------------------------------------------------------------------------- #


class PrecomputedSafety(BaseModel):
    """A cached, ready-to-serve safety verdict for one mint.

    ``gate`` is computed at write time so the serve path never re-scores. ``safety``
    is the JSON dict of the static ``SafetyBlock``; ``wash`` is the flow read.
    Freshness is measured against an epoch timestamp the writer stamps, so the
    model itself stays pure (no clock calls inside) and is trivially testable.
    """

    model_config = ConfigDict(extra="forbid")

    mint: str
    gate: str = Field(..., description="Pre-computed gate: block / caution / ok / unknown.")
    safety: dict[str, Any] = Field(
        default_factory=dict,
        description="SafetyBlock.model_dump(mode='json') — the static contract-safety read.",
    )
    wash: WashRiskBlock | None = Field(
        default=None, description="Launch-Firewall flow read; None when no flow was assessed."
    )
    computed_at_epoch: float = Field(
        ..., description="Unix epoch seconds when this verdict was computed (writer-stamped)."
    )
    source: str = Field(
        default="monitor",
        description="Provenance: 'monitor' (pre-computed) | 'ondemand' (cold-miss fallback).",
    )

    def age_seconds(self, now_epoch: float) -> float:
        """Seconds since this verdict was computed (clamped at 0)."""
        return max(0.0, now_epoch - self.computed_at_epoch)

    def is_fresh(self, now_epoch: float, max_age_s: float) -> bool:
        """True when the verdict is younger than ``max_age_s`` — the warm-hit test."""
        return self.age_seconds(now_epoch) <= max_age_s

    def to_response(self, now_epoch: float | None = None) -> dict[str, Any]:
        """The wire shape ``/safety`` returns: gate + the safety fields + wash.

        Mirrors the existing endpoint's ``{"gate": ..., **block.model_dump()}``
        shape, with the wash block and freshness metadata added so a consumer can
        see how stale the read is and whether it came warm or cold.
        """
        out: dict[str, Any] = {"gate": self.gate, **self.safety}
        out["wash_risk"] = self.wash.model_dump(mode="json") if self.wash is not None else None
        out["source"] = self.source
        if now_epoch is not None:
            out["staleness_s"] = round(self.age_seconds(now_epoch), 3)
        return out


@runtime_checkable
class SafetyStore(Protocol):
    """The fast-store contract: a Mongo-free key/value with TTL.

    Phase 1 is satisfied by :class:`gecko_core.trade_agent.hotpath.cache.HotpathCache`
    (in-process). Phase 2 swaps in a Redis-backed impl with the SAME interface —
    no caller changes (the Rust ingest service, when it lands, writes the same
    keys). Implementations must return ``None`` on a miss, never raise.
    """

    async def get(self, mint: str) -> PrecomputedSafety | None: ...

    async def set(self, mint: str, value: PrecomputedSafety, ttl_seconds: float) -> None: ...
