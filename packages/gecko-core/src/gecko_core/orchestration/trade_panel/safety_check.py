"""Contract-safety wiring for the trade-panel verdict envelope.

feat/verdict-contract-safety — Pattern E gap closure. The raw-chain rug/honeypot
client (:mod:`gecko_core.sources.quicknode`) existed but its signal never reached
the sold verdict. This module is the bridge: detect an SPL-mint target, call the
QuickNode client, and build a first-class :class:`SafetyBlock` for the envelope.

Design constraints:
  - **Fail-OPEN + explicit.** Any failure (no RPC configured, RPC error, target
    is not a mint) yields a ``SafetyBlock`` with ``checked=False`` and an
    explicit ``rug_flags`` marker — never a silently-omitted field. The
    envelope must always show whether the check ran.
  - **No secrets in errors.** The RPC URL is read from env and never logged or
    embedded in a flag/source string.
  - **Thin.** Mint detection + concentration math live here so the panel entry
    point (:func:`run_trade_panel_with_retrieval`) just awaits one coroutine.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from gecko_core.execution.yield_base.validation import b58decode
from gecko_core.orchestration.trade_panel.models import SafetyBlock
from gecko_core.sources.quicknode import QuickNodeClient, TokenSafety

logger = logging.getLogger(__name__)

# Holder-concentration alarm threshold. A single wallet holding >35% of supply
# is a recognized rug/dump vector. Tunable; surfaced as an explicit flag rather
# than folded into ``honeypot`` so the coordinator can weigh it separately.
_HOLDER_CONCENTRATION_FLAG = 0.35

# Known non-mint protocol names that arrive as the ``protocol`` argument. These
# are NOT SPL mints — they route to the lending/DeFi reasoning path, not a
# contract-safety read. Listed so the "not a token mint" decision is explicit
# rather than relying solely on base58 length.
_KNOWN_PROTOCOLS = frozenset(
    {"kamino", "jito", "jupiter", "drift", "marginfi", "raydium", "orca", "meteora", "sanctum"}
)


def is_spl_mint(candidate: str) -> bool:
    """True when ``candidate`` looks like a base58-encoded 32-byte SPL mint.

    Solana account addresses (mints included) are 32 raw bytes, base58-encoded
    to 32-44 chars. We validate by decoding and checking the byte length — a
    known protocol *name* (``"kamino"``) decodes to the wrong length and is
    rejected, so the safety read only fires for genuine on-chain mints.
    """
    s = candidate.strip()
    if not s or s.lower() in _KNOWN_PROTOCOLS:
        return False
    if not (32 <= len(s) <= 44):
        return False
    try:
        return len(b58decode(s)) == 32
    except (ValueError, KeyError):
        # Non-base58 char in the string -> not a mint.
        return False


def _rpc_url() -> str | None:
    """Read the Solana RPC endpoint from env. Never logged."""
    url = os.environ.get("QUICKNODE_RPC_URL", "").strip()
    return url or None


def _top_holder_pct(largest: list[dict[str, Any]], supply: str | None) -> float | None:
    """Largest single holder's share of supply in [0,1], or None if unknowable.

    Uses raw ``amount`` (integer minimal units) against mint ``supply`` so the
    ratio is decimals-agnostic. Guards against zero/None supply.
    """
    if not largest or not supply:
        return None
    try:
        total = int(supply)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    top_amount = 0
    for acct in largest:
        raw = acct.get("amount")
        if raw is None:
            continue
        try:
            top_amount = max(top_amount, int(raw))
        except (TypeError, ValueError):
            continue
    if top_amount <= 0:
        return None
    return min(top_amount / total, 1.0)


def _block_from_token_safety(
    safety: TokenSafety,
    top_holder_pct: float | None,
) -> SafetyBlock:
    """Map the raw-chain :class:`TokenSafety` read into the envelope block."""
    flags: list[str] = []
    if not safety.mint_renounced:
        flags.append("mint_not_renounced")
    if not safety.freeze_renounced:
        flags.append("freeze_not_renounced")
    if top_holder_pct is not None and top_holder_pct >= _HOLDER_CONCENTRATION_FLAG:
        flags.append("high_holder_concentration")

    # v0.1 honeypot proxy: un-renounced mint OR freeze authority means the dev
    # retains the power to dilute or freeze the position — structurally unsafe
    # to hold. Refined when a sell-simulation source lands.
    honeypot = safety.rug_risk

    return SafetyBlock(
        checked=True,
        honeypot=honeypot,
        mint_mutable=not safety.mint_renounced,
        freeze_mutable=not safety.freeze_renounced,
        tax_rate=None,  # no tax source wired in v0.1
        top_holder_pct=top_holder_pct,
        rug_flags=flags,
        source="quicknode",
    )


async def evaluate_contract_safety(
    target: str,
    *,
    client: QuickNodeClient | None = None,
) -> SafetyBlock:
    """Build the verdict-envelope :class:`SafetyBlock` for a research target.

    ``target`` is the panel's ``protocol`` argument — either a known protocol
    name (``"kamino"``) or an SPL mint address. Only mints get a raw-chain read;
    everything else returns an explicit fail-OPEN block (``not_a_token_mint``).

    ``client`` is injectable for tests (recorded-fixture transport); in
    production it is built from ``QUICKNODE_RPC_URL``. When that env var is
    absent the block is fail-OPEN (``safety_check_unavailable``) — we never
    fabricate a "safe" read.

    NEVER raises: any RPC/parse error degrades to a fail-OPEN block so the panel
    path can always attach a safety surface.
    """
    if not is_spl_mint(target):
        return SafetyBlock.unavailable(reason="not_a_token_mint")

    if client is None:
        url = _rpc_url()
        if url is None:
            return SafetyBlock.unavailable(reason="safety_check_unavailable")
        client = QuickNodeClient(url)

    try:
        safety = await client.token_safety(target)
    except Exception as exc:  # pragma: no cover - defensive; never crash the panel
        # Redact: log the exception type only, never the RPC URL or full body.
        logger.warning(
            "trade_panel.safety_check.error target=%s err_type=%s", target, type(exc).__name__
        )
        return SafetyBlock.unavailable(reason="safety_check_unavailable")

    # Holder concentration is best-effort: a failure here must not drop the
    # already-good mint/freeze read, so it is guarded independently.
    top_pct: float | None = None
    try:
        largest = await client.token_largest_accounts(target)
        top_pct = _top_holder_pct(largest, safety.supply)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "trade_panel.safety_check.holders_error target=%s err_type=%s",
            target,
            type(exc).__name__,
        )

    return _block_from_token_safety(safety, top_pct)


__all__ = ["evaluate_contract_safety", "is_spl_mint"]
