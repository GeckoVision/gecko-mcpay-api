"""Bento pre-flight — the fail-CLOSED execution-layer enforcement veto.

This is the *enforcement* half of the safety stack. Its complement is the
fail-OPEN ``SafetyBlock`` judgment signal
(:mod:`gecko_core.orchestration.trade_panel.safety_check`). The boundary is
spelled out in ``private/strategy/2026-06-13-bento-layering-architecture.md``:

  * SIGNAL  — judges *the thing you want to do* (a mint), at research time.
    Advisory, fail-OPEN, never blocks. 8% mint-substitution bypass on its own.
  * GUARDRAIL — inspects *the transaction you are about to send*, at broadcast
    time. Fail-CLOSED. A vetoed tx never reaches the chain. Closes the 8%→0%.

Per Pattern C (CLAUDE.md "Recurring patterns"), the FIRST deliverable for any
wire-protocol integration is a free local simulation + a recorded-fixture
contract test — never a live mainnet debug loop. We have no Bento creds yet, so
:class:`StubBentoClient` is the only conformer that ships; the live client is a
deliberate later step gated on the contract test passing against the real
Bento scan endpoint.

The gate that *calls* this lives in the execution adapter's ``place_order``,
between "build unsigned tx" and "broadcast" — NOT in the pure ``check_order``
policy gate. See ``contest_bot/trade_safety.py`` (``JupiterSwapExecutionAdapter``).
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)

# Env toggle — mirrors the X402_MODE / *_EXEC_MODE stub/live shape. Default OFF.
# OFF is a no-op pass-through: the gate must NEVER block when disabled.
PREFLIGHT_ENV = "BENTO_PREFLIGHT"
_ON_VALUES = frozenset({"on", "1", "true", "yes"})
_OFF_VALUES = frozenset({"off", "0", "false", "no", ""})


def is_preflight_enabled(env: dict[str, str] | None = None) -> bool:
    """True iff ``BENTO_PREFLIGHT`` is explicitly on. Default (unset) = off.

    Any value other than the known on/off tokens raises — a typo'd flag on a
    fail-closed gate must fail loud, not silently disable enforcement.
    """
    src = env if env is not None else os.environ
    raw = src.get(PREFLIGHT_ENV, "").strip().lower()
    if raw in _ON_VALUES:
        return True
    if raw in _OFF_VALUES:
        return False
    raise ValueError(f"invalid {PREFLIGHT_ENV}={raw!r}; must be one of on/off (or 1/0, true/false)")


@dataclass(frozen=True)
class BentoPreflightContext:
    """Advisory hint Gecko passes INTO Bento's pre-flight (layering doc §3a).

    The ``intended_mint`` is the equality anchor — Gecko researched and judged
    THIS mint; Bento extracts the mint the realized tx actually buys and asserts
    they are equal. That equality check is the literal 8%→0% mint-substitution
    mechanism.

    **The hint is advisory, NEVER an authority.** A clean Gecko signal may let
    Bento run a faster path; it may NEVER disarm the fail-closed veto. If the
    hint is absent or ``gecko_safety_checked=False``, Bento ignores it and runs
    full depth. Feeding a fail-OPEN signal must not weaken a fail-CLOSED gate.
    """

    intended_mint: str | None = None
    gecko_rug_flags: list[str] = field(default_factory=list)
    gecko_top_holder_pct: float | None = None
    gecko_safety_checked: bool = False


@dataclass(frozen=True)
class BentoPreflightResult:
    """Bento's allow/veto decision over a realized unsigned tx.

    ``allowed=True`` → the adapter may broadcast. ``allowed=False`` → the
    adapter MUST raise before any broadcast. ``ran=False`` means the pre-flight
    could not execute; on a fail-closed gate that is treated as a veto.
    """

    allowed: bool
    ran: bool
    reasons: list[str] = field(default_factory=list)
    tx_hash: str | None = None
    source: str = "bento"


@runtime_checkable
class BentoClient(Protocol):
    """Wallet/provider-neutral Bento pre-flight scan client.

    One method: scan a built (unsigned) tx + the advisory context, return an
    allow/veto. The client NEVER signs, NEVER broadcasts, NEVER holds a key — it
    is a read/simulate call. The veto primitive is "refuse to allow", which the
    adapter turns into "refuse to dispatch". Non-custodial by construction.
    """

    name: str
    mode: str  # "stub" | "live"

    def scan(
        self,
        *,
        unsigned_tx_b64: str | None,
        mint: str,
        context: BentoPreflightContext,
    ) -> BentoPreflightResult: ...


@dataclass
class StubBentoClient:
    """Free, deterministic, no-network Bento client (Pattern C: stub-first).

    Models the EXPECTED shape of the real Bento scan endpoint (allow/deny +
    reason) so the gate, the contract test, and the EnforcementBlock can all be
    exercised without creds. The decision logic mirrors the contract the live
    client must honor:

      * **Mint-equality cross-check.** If the advisory ``intended_mint`` is
        present AND the scanned ``mint`` differs, that is the mint-substitution
        attack class — VETO (``mint_substitution``). This is the modeled
        8%→0% mechanism. The hint, when present, makes the catch a direct
        equality check rather than Bento re-deriving intent.
      * **Hint NEVER disarms the veto.** ``gecko_rug_flags`` only ever *adds*
        veto reasons (e.g. an un-renounced mint escalates). A "clean" signal
        (no flags, ``gecko_safety_checked=True``, mints equal) yields allow —
        but absence of a hint does NOT yield allow on a substitution.
      * **Deterministic default.** With a matching/absent intended_mint and no
        adverse flags, the stub allows. The live client replaces this body with
        a real simulation; the allow/veto wire shape is identical.

    A ``deny_mints`` set lets tests force a veto for a known-bad mint without
    needing a substitution — exercises the deny path directly.
    """

    name: str = "bento"
    mode: str = "stub"
    deny_mints: frozenset[str] = field(default_factory=frozenset)
    # Rug flags that, if present in the advisory hint, escalate to a veto in the
    # stub. The live client would re-derive these from its own simulation; here
    # they let the contract test prove "flagged → veto" without a real scan.
    veto_on_flags: frozenset[str] = field(
        default_factory=lambda: frozenset({"mint_not_renounced", "freeze_not_renounced"})
    )

    def scan(
        self,
        *,
        unsigned_tx_b64: str | None,
        mint: str,
        context: BentoPreflightContext,
    ) -> BentoPreflightResult:
        reasons: list[str] = []

        # 1. Mint-equality cross-check — the substitution catch (8%→0%).
        intended = context.intended_mint
        if intended is not None and intended != mint:
            reasons.append("mint_substitution")

        # 2. Hint may ADD reasons, never remove them. A flagged mint escalates.
        if context.gecko_safety_checked:
            for flag in context.gecko_rug_flags:
                if flag in self.veto_on_flags:
                    reasons.append(f"hint:{flag}")

        # 3. Explicit deny list (test/operator force-veto for a known-bad mint).
        if mint in self.deny_mints:
            reasons.append("deny_listed")

        allowed = not reasons
        logger.info(
            "bento.preflight.stub mint=%s allowed=%s reasons=%s tx=%s",
            mint,
            allowed,
            reasons,
            "present" if unsigned_tx_b64 else "absent",
        )
        # tx_hash is None in stub: the stub never sees a real chain tx.
        return BentoPreflightResult(allowed=allowed, ran=True, reasons=reasons, tx_hash=None)


def default_bento_client(mode: str | None = None) -> BentoClient:
    """Return a Bento client for ``mode`` (resolves from env when None).

    Only the stub conformer ships today (no Bento creds). A ``mode='live'``
    request raises — the live client is gated on its recorded-fixture contract
    test passing against the real Bento scan endpoint (Pattern C), which is a
    separate, deliberate step. This mirrors ``get_adapter``'s stub-default.
    """
    resolved = (mode or os.environ.get("BENTO_MODE", "stub")).lower()
    if resolved == "stub":
        return StubBentoClient()
    raise NotImplementedError(
        f"BENTO_MODE={resolved!r}: only 'stub' ships. The live Bento client is "
        "gated on its recorded-fixture contract test (Pattern C) + real creds."
    )


__all__ = [
    "PREFLIGHT_ENV",
    "BentoClient",
    "BentoPreflightContext",
    "BentoPreflightResult",
    "StubBentoClient",
    "default_bento_client",
    "is_preflight_enabled",
]
