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
from gecko_core.orchestration.trade_panel.models import (
    InformationMEVBlock,
    InformationMEVLabel,
    SafetyBlock,
)
from gecko_core.sources.coingecko import CoinGeckoClient, OnchainTokenMarket
from gecko_core.sources.quicknode import QuickNodeClient, TokenSafety

logger = logging.getLogger(__name__)

# Holder-concentration alarm threshold. A single wallet holding >35% of supply
# is a recognized rug/dump vector. Tunable; surfaced as an explicit flag rather
# than folded into ``honeypot`` so the coordinator can weigh it separately.
_HOLDER_CONCENTRATION_FLAG = 0.35

# Manipulation thresholds on liquidity-to-mcap ratio (expressed as a percent).
#   - Below 1%   => liquidity is thin relative to the quoted market cap; the
#     "price" is supportable only on tiny volume (`thin_liquidity_vs_mcap`).
#   - Below 0.2% => the market cap is effectively fictional — there is not
#     enough liquidity to realize anything close to it (`fake_market_cap`).
# BrCA live: $26.31M mcap / $22.4K liquidity = 0.085% => fake_market_cap, while
# venue ratings called it "Normal". These are the signals that catch that.
_THIN_LIQUIDITY_PCT = 1.0
_FAKE_MCAP_PCT = 0.2

# Absolute on-chain liquidity floor (USD). The liq/mcap RATIO alone is a
# false-positive magnet for large caps: a $585M token with $2.0M on-chain DEX
# liquidity is 0.34% but perfectly tradable — its real depth lives on CEXes that
# ``total_reserve_in_usd`` does not capture. A thin float is only a manipulation
# signal when liquidity is ALSO small in ABSOLUTE terms (a real-size order can't
# exit). Below this floor BrCA ($160K) flags; above it JUP/BONK (~$2M+) do not.
# CAVEAT: a genuinely large-cap token whose liquidity is almost entirely on CEX
# could in theory dip below the floor; that edge is accepted for v1. Tunable.
_MIN_LIQUIDITY_USD = 500_000.0

# FOLLOW-UP (not built here): holder-distribution VELOCITY — top holders selling
# down over time is a distinct rug signal from static concentration. It needs a
# holder time-series (Helius holder snapshots over a window), which is a new data
# dependency + storage. Deferred deliberately; `top_holder_pct` covers the static
# concentration read for now. Tracked for a follow-up sprint.

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


def compute_manipulation_signals(
    market: OnchainTokenMarket | None,
) -> tuple[float | None, float | None, float | None, list[str]]:
    """Derive (market_cap, liquidity, ratio_pct, flags) from a market read.

    Returns the raw mcap + liquidity figures, their ratio as a percent, and the
    triggered manipulation flags. Fail-OPEN: a missing source or unusable inputs
    yield ``(None, None, None, [])`` — the caller adds the explicit-unavailable
    flag, never this function (it stays a pure signal computation).
    """
    if market is None:
        return None, None, None, []
    mcap = market.effective_market_cap_usd
    liquidity = market.total_reserve_in_usd
    if mcap is None or mcap <= 0 or liquidity is None or liquidity < 0:
        # Surface whatever we DID resolve so the envelope isn't silent, but no
        # ratio and no manipulation flag without both inputs.
        return mcap, liquidity, None, []
    ratio_pct = liquidity / mcap * 100.0
    flags: list[str] = []
    # A low ratio is only a manipulation signal when liquidity is ALSO thin in
    # absolute terms — otherwise a deep-liquidity large cap (whose off-chain CEX
    # depth this source can't see) trips a false positive. Require both.
    thin_absolute = liquidity < _MIN_LIQUIDITY_USD
    if thin_absolute and ratio_pct < _FAKE_MCAP_PCT:
        # fake_market_cap is the stronger claim; it implies thin liquidity too,
        # so emit both so a consumer filtering on either flag still catches it.
        flags.append("thin_liquidity_vs_mcap")
        flags.append("fake_market_cap")
    elif thin_absolute and ratio_pct < _THIN_LIQUIDITY_PCT:
        flags.append("thin_liquidity_vs_mcap")
    return mcap, liquidity, ratio_pct, flags


# Information-MEV scoring weights (W1). Deterministic, derived from the
# manipulation flags PR #136 already computes — no new data dependency.
# fake_market_cap is the strongest single signal (the price is fictional); thin
# liquidity alone is milder; single-wallet concentration compounds either (one
# holder can dump the whole float). Tuned so BrCA ($26.3M mcap / $22.4K liq,
# 77% top holder) => ~0.95 'manipulated', a deep-liquidity major => 0.0 'clean'.
_IMEV_FAKE_MCAP = 0.7
_IMEV_THIN_LIQUIDITY = 0.4
_IMEV_CONCENTRATION = 0.25
_IMEV_MANIPULATED_AT = 0.6
_IMEV_ELEVATED_AT = 0.25


def _fmt_usd(v: float | None) -> str:
    if v is None:
        return "?"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return f"{v:.0f}"


def _fmt_pct(v: float | None) -> str:
    return "?" if v is None else f"{v:.3f}%"


def assess_information_mev(
    *,
    market_cap_usd: float | None,
    liquidity_usd: float | None,
    ratio_pct: float | None,
    manip_flags: list[str],
    top_holder_pct: float | None,
) -> InformationMEVBlock | None:
    """Package the raw manipulation signals into a named Information-MEV read.

    Returns ``None`` (fail-OPEN) only when there is nothing to assess — no
    liquidity/mcap ratio AND no holder-concentration read. Otherwise returns a
    scored block, including an honest ``"clean"`` verdict when signals are
    present but benign (a positive read is information too — never fabricated).
    """
    if ratio_pct is None and top_holder_pct is None:
        return None

    score = 0.0
    reasons: list[str] = []

    if "fake_market_cap" in manip_flags:
        score += _IMEV_FAKE_MCAP
        reasons.append(
            f"Market cap (~${_fmt_usd(market_cap_usd)}) is backed by only "
            f"~${_fmt_usd(liquidity_usd)} of on-chain liquidity "
            f"({_fmt_pct(ratio_pct)}) — the price is unsupportable on real "
            "volume; bot-inflation / fake-market-cap pattern."
        )
    elif "thin_liquidity_vs_mcap" in manip_flags:
        score += _IMEV_THIN_LIQUIDITY
        reasons.append(
            f"Liquidity is thin vs market cap ({_fmt_pct(ratio_pct)}) — the "
            "visible price is movable on small volume."
        )

    if top_holder_pct is not None and top_holder_pct >= _HOLDER_CONCENTRATION_FLAG:
        score += _IMEV_CONCENTRATION
        reasons.append(
            f"Top holder controls ~{top_holder_pct * 100:.0f}% of supply — "
            "single-wallet dump / float-control risk."
        )

    score = min(score, 1.0)
    label: InformationMEVLabel
    if score >= _IMEV_MANIPULATED_AT:
        label = "manipulated"
    elif score >= _IMEV_ELEVATED_AT:
        label = "elevated"
    else:
        label = "clean"

    if not reasons:
        note = f"No manipulation signals: liquidity {_fmt_pct(ratio_pct)} of market cap"
        if top_holder_pct is not None:
            note += f", top holder ~{top_holder_pct * 100:.0f}% of supply"
        reasons.append(note + ".")

    return InformationMEVBlock(score=round(score, 2), label=label, reasons=reasons)


def _block_from_token_safety(
    safety: TokenSafety,
    top_holder_pct: float | None,
    market: OnchainTokenMarket | None,
) -> SafetyBlock:
    """Map the raw-chain :class:`TokenSafety` + market read into the envelope."""
    flags: list[str] = []
    if not safety.mint_renounced:
        flags.append("mint_not_renounced")
    if not safety.freeze_renounced:
        flags.append("freeze_not_renounced")
    if top_holder_pct is not None and top_holder_pct >= _HOLDER_CONCENTRATION_FLAG:
        flags.append("high_holder_concentration")

    mcap, liquidity, ratio_pct, manip_flags = compute_manipulation_signals(market)
    flags.extend(manip_flags)
    if ratio_pct is None:
        # The chain read ran, but we could not compute a liquidity-to-mcap
        # ratio (market source unreachable, token unknown to it, or it gave
        # only one of the two inputs). Be explicit rather than silent — a
        # missing manipulation read is itself information for the gate.
        flags.append("manipulation_check_unavailable")

    # v0.1 honeypot proxy: un-renounced mint OR freeze authority means the dev
    # retains the power to dilute or freeze the position — structurally unsafe
    # to hold. Refined when a sell-simulation source lands.
    honeypot = safety.rug_risk

    source = "quicknode+coingecko" if market is not None else "quicknode"

    information_mev = assess_information_mev(
        market_cap_usd=mcap,
        liquidity_usd=liquidity,
        ratio_pct=ratio_pct,
        manip_flags=manip_flags,
        top_holder_pct=top_holder_pct,
    )

    return SafetyBlock(
        checked=True,
        honeypot=honeypot,
        mint_mutable=not safety.mint_renounced,
        freeze_mutable=not safety.freeze_renounced,
        tax_rate=None,  # no tax source wired in v0.1
        top_holder_pct=top_holder_pct,
        market_cap_usd=mcap,
        liquidity_usd=liquidity,
        liquidity_to_mcap_pct=ratio_pct,
        rug_flags=flags,
        information_mev=information_mev,
        source=source,
    )


def _resolve_mint(target: str, mint: str | None) -> str | None:
    """Return the mint to check, or None when no real SPL mint is available.

    Precedence: an explicit ``mint`` arg (the firing fix) wins — when the caller
    knows the mint, we never reject the request because the *protocol* string
    ("brca") isn't base58. The base58-in-protocol fallback is kept for
    back-compat so existing callers that crammed the mint into ``protocol``
    still fire.
    """
    if mint:
        m = mint.strip()
        if is_spl_mint(m):
            return m
        # An explicit-but-invalid mint is a caller error worth surfacing as a
        # distinct fail-OPEN reason rather than silently falling back.
        return None
    if is_spl_mint(target):
        return target.strip()
    return None


async def evaluate_contract_safety(
    target: str,
    *,
    mint: str | None = None,
    client: QuickNodeClient | None = None,
    market_client: CoinGeckoClient | None = None,
) -> SafetyBlock:
    """Build the verdict-envelope :class:`SafetyBlock` for a research target.

    ``target`` is the panel's ``protocol`` argument — either a known protocol
    name (``"kamino"``) or, for back-compat, an SPL mint crammed into the field.
    ``mint`` is the explicit, first-class mint address: when set and valid it
    fires the safety read directly, so a token query no longer has to abuse the
    ``protocol`` field. Precedence: ``mint`` > base58-in-``protocol``.

    ``client`` (raw-chain) and ``market_client`` (CoinGecko on-chain market /
    liquidity) are injectable for tests; in production they are built from
    ``QUICKNODE_RPC_URL`` and the default CoinGecko endpoints. When the RPC is
    absent the block is fail-OPEN (``safety_check_unavailable``). When the
    market source is absent/unreachable the chain read still returns and the
    manipulation signals are simply ``None`` (fail-OPEN, explicit).

    NEVER raises: any RPC/parse error degrades to a fail-OPEN block so the panel
    path can always attach a safety surface.
    """
    resolved = _resolve_mint(target, mint)
    if resolved is None:
        # Distinguish "not a mint at all" from "explicit mint was malformed" so
        # the envelope flag is honest about why the check didn't run.
        reason = "invalid_mint" if mint else "not_a_token_mint"
        return SafetyBlock.unavailable(reason=reason)

    if client is None:
        url = _rpc_url()
        if url is None:
            return SafetyBlock.unavailable(reason="safety_check_unavailable")
        client = QuickNodeClient(url)

    try:
        safety = await client.token_safety(resolved)
    except Exception as exc:  # pragma: no cover - defensive; never crash the panel
        # Redact: log the exception type only, never the RPC URL or full body.
        logger.warning(
            "trade_panel.safety_check.error target=%s err_type=%s", resolved, type(exc).__name__
        )
        return SafetyBlock.unavailable(reason="safety_check_unavailable")

    # Holder concentration is best-effort: a failure here must not drop the
    # already-good mint/freeze read, so it is guarded independently.
    top_pct: float | None = None
    try:
        largest = await client.token_largest_accounts(resolved)
        top_pct = _top_holder_pct(largest, safety.supply)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "trade_panel.safety_check.holders_error target=%s err_type=%s",
            resolved,
            type(exc).__name__,
        )

    # Manipulation signals (mcap / liquidity) are best-effort too — fail-OPEN to
    # None when CoinGecko is unreachable or doesn't know the token. The raw-chain
    # rug read above is never dropped because the market source failed.
    market = await _fetch_market(resolved, market_client)

    return _block_from_token_safety(safety, top_pct, market)


async def _fetch_market(
    mint: str,
    market_client: CoinGeckoClient | None,
) -> OnchainTokenMarket | None:
    """Resolve mcap + liquidity for ``mint``; None (fail-OPEN) on any failure.

    Uses CoinGecko's on-chain (GeckoTerminal) token-by-address endpoint, which
    works on a raw SPL mint and needs NO new API key (free tier). A default
    client is constructed only when one isn't injected.
    """
    client = market_client if market_client is not None else CoinGeckoClient()
    try:
        return await client.onchain_token_market(mint, network="solana")
    except Exception as exc:  # pragma: no cover - defensive; never crash the panel
        logger.warning(
            "trade_panel.safety_check.market_error target=%s err_type=%s",
            mint,
            type(exc).__name__,
        )
        return None


__all__ = [
    "assess_information_mev",
    "compute_manipulation_signals",
    "evaluate_contract_safety",
    "is_spl_mint",
]
