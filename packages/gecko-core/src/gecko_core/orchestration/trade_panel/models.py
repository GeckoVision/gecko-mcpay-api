"""Pydantic schemas for the 7-agent trade-research panel.

The contract surface — Phase 8b's MCP tool + REST endpoint serialize these.
Field semantics are stable; adding optional fields is non-breaking, renaming
existing fields is. Keep the Literal sets aligned with the closing-line
patterns in :mod:`gecko_core.orchestration.trade_panel.personas`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.orchestration.trade_panel.backtest.models import BacktestReport
from gecko_core.sources.types import FreshnessTier, ProviderKind
from gecko_core.types import SettlementMode

# Final-verdict tokens. Mirrors the coordinator's closing-line regex.
TradeVerdictLiteral = Literal["act", "pass", "defer"]

# S36-#111 — canonical citation-snippet length cap. Pattern A: single source
# of truth. The panel driver (__init__.py) imports this to derive its
# truncation limit `_CITATION_SNIPPET_LIMIT`, so the truncation window and the
# Pydantic `max_length` validator can never drift. S36-WS2 raised the cap
# 240 -> 320 (validated by #107's truncation investigation) so number-first
# chunk figures survive into the judge's view.
CITATION_SNIPPET_MAX_LEN = 320


class TradePanelTurn(BaseModel):
    """A single agent's turn in the panel.

    ``parsed_verdict`` is the structured extraction from the closing line
    (e.g. ``{"trend_verdict": "bullish"}``). ``None`` means the agent did
    not emit a parseable closing line — surface as a soft failure rather
    than coercing a default, so callers can flag the run as degraded.
    """

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(..., description="Persona name (matches REQUIRED_AGENTS).")
    content: str = Field(..., description="Full turn text the agent produced.")
    parsed_verdict: dict[str, Any] | None = Field(
        default=None,
        description="Structured extraction from the closing line, or None if unparsed.",
    )


class Citation(BaseModel):
    """A single retrieved-chunk citation surfaced on the verdict envelope.

    Issue #15: previously, citations were exposed only as inline ``[N]``
    markers inside ``turns[].content``. Skill authors and demo UIs had to
    regex-extract from prose to render or audit. This model is the
    structured wire surface — the ``id`` field links each entry to the
    inline marker (1-indexed, matches ``_format_chunks`` in the panel
    driver). Additive only; the inline markers keep working.

    ``provider_kind`` and ``freshness_tier`` re-export the canonical
    Literals from :mod:`gecko_core.sources.types` (Pattern A — single
    source of truth). When a chunk is missing either column, defaults
    fall through to ``"web"`` / ``"static"`` so the wire shape never
    breaks on partial Mongo rows.

    S35-#99 — this item shape is shared by BOTH top-level verdict lists:
    ``evidence_citations`` (protocol/market data — "the data") and
    ``framework_context`` (investor-canon — "the lens"). The split lives
    on :class:`TradePanelVerdict`, not on this model: a Citation is
    provider-kind-agnostic; which list it lands in is decided at panel
    assembly by ``partition_emitted_citations``.
    """

    model_config = ConfigDict(extra="forbid")

    id: int = Field(..., ge=1, description="1-indexed marker that matches inline [N] in turns.")
    source: str = Field(..., description="Catalog name (e.g. 'paysh', 'bazaar', 'tavily').")
    url: str = Field(..., description="Full URL when available, else hash-of-chunk_id fallback.")
    chunk_id: str = Field(..., description="Mongo _id (or empty string when ephemeral).")
    provider_kind: ProviderKind = Field(
        default="web",
        description="Canonical chunks.provider_kind — gecko_core.sources.types.ProviderKind.",
    )
    freshness_tier: FreshnessTier = Field(
        default="static",
        description="Canonical chunks.freshness_tier — gecko_core.sources.types.FreshnessTier.",
    )
    snippet: str = Field(
        default="",
        max_length=CITATION_SNIPPET_MAX_LEN,
        description="Cited chunk content, truncated to CITATION_SNIPPET_MAX_LEN chars.",
    )


class DissentEntry(BaseModel):
    """Sprint 18 — a single voice's surviving dissent against the verdict.

    The verdict envelope used to expose only ``dissent_count: int``. Callers
    (the bot's gate, dashboards, downstream skills) could not tell WHICH
    voice dissented or WHAT they said — only that someone did. This entry
    surfaces both, mirroring the pro-tier ``surviving_dissent`` shape into
    basic-tier so the wedge ("grounded dissent that survived debate") is
    visible at the cheapest tier too.

    Pattern: ``voice`` matches the persona name from REQUIRED_AGENTS;
    ``verbatim`` is the dissenting voice's closing-line token in their own
    words (the structured ``parsed_verdict`` value, never paraphrased);
    ``on_topic`` is a 1-phrase summary of what the dissent concerns.

    Empty list is the honest default when no voice opposed the verdict;
    do not synthesize entries to fill the surface. The eval harness
    treats `dissent: []` on a high-confidence verdict as a quality SIGNAL
    (consensus is real), not a quality FAILURE.
    """

    model_config = ConfigDict(extra="forbid")

    voice: str = Field(
        ...,
        description="Persona name (technical_analyst, sentiment_analyst, ...).",
    )
    stance: Literal["oppose", "abstain"] = Field(
        ...,
        description=(
            "'oppose' = closing-line directional verdict against the coordinator's call. "
            "'abstain' = the voice explicitly punted (mixed/stable with data-gap)."
        ),
    )
    verbatim: str = Field(
        ...,
        max_length=300,
        description=(
            "The dissenting voice's closing-line token, verbatim — never paraphrased. "
            "Trimmed at 300 chars to keep the envelope small but preserve evidence."
        ),
    )
    on_topic: str = Field(
        default="",
        max_length=80,
        description="1-phrase summary of what the dissent concerns (e.g. 'trend read', 'risk band').",
    )


InformationMEVLabel = Literal["clean", "elevated", "manipulated"]


class InformationMEVBlock(BaseModel):
    """Named Information-MEV read — manipulation severity of a token's *visible signal*.

    W1 (MEV-decision-provider sprint). PR #136 computed the raw manipulation
    flags (``thin_liquidity_vs_mcap`` / ``fake_market_cap`` /
    ``high_holder_concentration``) but left them as loose strings on
    ``SafetyBlock.rug_flags``. This block is the product surface: a single
    0–1 ``score``, a one-glance ``label``, and human-readable ``reasons`` — so a
    consumer (the gate, the app, the deck) can read *"is this decision being
    made on a manipulated price?"* without re-deriving it.

    *Information-MEV* = value extracted by manipulating the information a
    decision rests on (bot-inflated price, fake market cap, single-wallet
    float) — the decision-layer analogue of transaction-MEV. The score measures
    how manipulable the *visible market signal* is; it is NOT contract-rug risk
    (that stays on the mint/freeze/honeypot fields).

    Fail-OPEN: the whole block is ``None`` when there were no inputs to assess
    (market source unreachable AND no holder read) — never a fabricated
    ``"clean"``. When signals exist but are benign, a real ``"clean"`` block is
    emitted (a positive read is information too).
    """

    model_config = ConfigDict(extra="forbid")

    score: float = Field(
        ..., ge=0.0, le=1.0, description="Manipulation severity in [0,1]; 0 = clean."
    )
    label: InformationMEVLabel = Field(
        ..., description="One-glance band: clean / elevated / manipulated."
    )
    reasons: list[str] = Field(
        default_factory=list,
        description="Human-readable signals behind the score; carries the 'clean' note when benign.",
    )


class SafetyBlock(BaseModel):
    """First-class contract-safety read attached to the verdict envelope.

    feat/verdict-contract-safety — Pattern E: we owned the QuickNode raw-chain
    rug/honeypot client (``gecko_core.sources.quicknode``) but the signal never
    reached the sold verdict. This block is the canonical wire shape so the
    oracle can truthfully say "our safety layer checked the contract" instead
    of borrowing it from a venue (OKX).

    Fail-OPEN + explicit: when the check could not run (target is not an SPL
    mint, source unavailable, or the RPC errored) every measured field is
    ``None`` and ``rug_flags`` carries an explicit marker
    (``"not_a_token_mint"`` / ``"safety_check_unavailable"``). The envelope
    ALWAYS shows whether the check ran — never silently omit. ``checked`` is the
    one-glance boolean the coordinator / gate reads first.

    Field semantics:
      - ``honeypot``        — True when the contract structurally cannot be
        sold safely. v0.1 derives this from un-renounced mint/freeze authority
        (the dev can mint-dilute or freeze your position); refined when a
        sell-simulation source lands.
      - ``mint_mutable``    — True when mint authority is NOT renounced.
      - ``freeze_mutable``  — True when freeze authority is NOT renounced.
      - ``tax_rate``        — transfer-tax fraction in [0,1] when a source
        exposes it; ``None`` until a tax source is wired (SPL token-2022
        transfer-fee extension is the v0.2 target).
      - ``top_holder_pct``  — largest single holder's share of supply in
        [0,1]; concentration proxy for rug risk.
      - ``market_cap_usd``  — token market cap in USD from the market-data
        source (CoinGecko on-chain). ``None`` until a source resolves it.
      - ``liquidity_usd``   — on-chain DEX liquidity (total reserve across
        pools) in USD. ``None`` until a source resolves it.
      - ``liquidity_to_mcap_pct`` — ``liquidity_usd / market_cap_usd * 100``
        when both are known. A LOW ratio is the manipulation signal a venue
        "Normal" rating misses: a $26M mcap backed by $22K of liquidity
        (0.085%) is a fake-market-cap / thin-float setup. ``None`` when
        either input is missing.
      - ``rug_flags``       — explicit string flags (e.g. ``"mint_not_renounced"``,
        ``"freeze_not_renounced"``, ``"high_holder_concentration"``,
        ``"thin_liquidity_vs_mcap"``, ``"fake_market_cap"``,
        ``"safety_check_unavailable"``).
      - ``source``          — provenance of the read (``"quicknode"`` /
        ``"quicknode+coingecko"`` / ``"unavailable"``); never a secret/URL.
    """

    model_config = ConfigDict(extra="forbid")

    checked: bool = Field(
        ...,
        description="True when a contract-safety source actually ran for this target.",
    )
    honeypot: bool | None = Field(
        default=None,
        description="True = contract structurally unsafe to sell; None = not measured.",
    )
    mint_mutable: bool | None = Field(
        default=None,
        description="True when mint authority is NOT renounced (dev can dilute).",
    )
    freeze_mutable: bool | None = Field(
        default=None,
        description="True when freeze authority is NOT renounced (dev can freeze).",
    )
    tax_rate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Transfer-tax fraction in [0,1]; None until a tax source is wired.",
    )
    top_holder_pct: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Largest single holder share of supply in [0,1]; None if unmeasured.",
    )
    market_cap_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="Token market cap in USD (CoinGecko on-chain); None if unmeasured.",
    )
    liquidity_usd: float | None = Field(
        default=None,
        ge=0.0,
        description="On-chain DEX liquidity (total reserve) in USD; None if unmeasured.",
    )
    liquidity_to_mcap_pct: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "liquidity_usd / market_cap_usd * 100. The manipulation signal: a "
            "low ratio (<1%) flags thin liquidity vs mcap; <0.2% flags a fake "
            "market cap. None when either input is missing."
        ),
    )
    rug_flags: list[str] = Field(
        default_factory=list,
        description="Explicit rug/honeypot/availability flags; never empty-silent on failure.",
    )
    information_mev: InformationMEVBlock | None = Field(
        default=None,
        description=(
            "W1 — named Information-MEV read: manipulation severity of the "
            "visible market signal, derived from the liquidity/mcap ratio + "
            "holder concentration already on this block. None when there were "
            "no inputs to assess (fail-OPEN)."
        ),
    )
    depeg_risk: float | None = Field(
        default=None,
        ge=0.0,
        description=(
            "Phase 3.3 — absolute peg deviation (discount) from the Pegana "
            "peg-risk oracle, in [0,1+] (0 = on-peg). For LSTs/stablecoins a "
            "material deviation is a decision-integrity risk the contract-rug "
            "read alone misses. None when no peg data (non-peg token, Pegana "
            "down, or any error — fail-OPEN)."
        ),
    )
    peg_status: str | None = Field(
        default=None,
        description=(
            "Phase 3.3 — Pegana peg state for the asset (e.g. 'PEGGED', "
            "'DEPEGGED', 'DRIFTING'). None when no peg data (fail-OPEN). A "
            "non-PEGGED or stale state adds the 'depeg_risk' rug flag."
        ),
    )
    source: str = Field(
        default="unavailable",
        description="Read provenance ('quicknode' / 'unavailable'); never a secret.",
    )

    @classmethod
    def unavailable(cls, *, source: str = "unavailable", reason: str | None = None) -> SafetyBlock:
        """Fail-OPEN constructor — the check could not run, and we say so.

        Use when the RPC is unconfigured/errored or the target is not an SPL
        mint. Always emits a flag so the envelope shows the check did not run.
        """
        flag = reason or "safety_check_unavailable"
        return cls(checked=False, source=source, rug_flags=[flag])


class TradePanelVerdict(BaseModel):
    """Final aggregated verdict from the coordinator + per-turn audit trail."""

    model_config = ConfigDict(extra="forbid")

    verdict: TradeVerdictLiteral = Field(..., description="Final coordinator decision.")
    confidence: float = Field(
        ..., ge=0.0, le=1.0, description="Coordinator-reported confidence in [0,1]."
    )
    key_drivers: list[str] = Field(
        default_factory=list,
        description="Short bullet drivers behind the verdict.",
    )
    dissent_count: int = Field(
        default=0,
        ge=0,
        description=(
            "Count of voices pointing the OTHER way from the coordinator's verdict. "
            "Computed from parsed_verdict on each non-coordinator turn."
        ),
    )
    dissent: list[DissentEntry] = Field(
        default_factory=list,
        max_length=5,
        description=(
            "Sprint 18 — structured surviving dissent. Each entry names a voice + "
            "their closing-line verbatim + what the dissent is about. "
            "Empty when the verdict is unanimous (which is itself a real signal — "
            "do not synthesize entries). Cap of 5 keeps the envelope bounded."
        ),
    )
    blocker_questions: list[str] = Field(
        default_factory=list,
        description="Open questions that would change the verdict if answered.",
    )
    turns: list[TradePanelTurn] = Field(
        default_factory=list,
        description="Full transcript in canonical agent order.",
    )
    evidence_citations: list[Citation] = Field(
        default_factory=list,
        description=(
            "S35-#99 — 'the data'. Protocol/market-data chunks a panel turn "
            "actually referenced via its inline [N] marker (provider_kind in "
            "protocol_native / market_data / paysh_live / bazaar_live). "
            "Relevance-trimmed: only chunks a turn drew on land here, so the "
            "rubric's citation_relevance dimension is judged over a tight, "
            "protocol-specific set. Empty when the panel ran without retrieval."
        ),
    )
    framework_context: list[Citation] = Field(
        default_factory=list,
        description=(
            "S35-#99 — 'the lens'. Investor-canon chunks (provider_kind "
            "canon_*) the panel reasoned over. NOT relevance-trimmed: canon "
            "framework prose is cross-cutting by design, so trimming it for "
            "protocol specificity is a category error. Split out of the old "
            "single citations[] so canon no longer drags citation_relevance."
        ),
    )
    safety: SafetyBlock | None = Field(
        default=None,
        description=(
            "feat/verdict-contract-safety — first-class contract-safety read. "
            "Populated for SPL-mint targets from the raw-chain rug/honeypot "
            "client (gecko_core.sources.quicknode). None ONLY on the legacy "
            "path that did not run the check at all (e.g. a unit-constructed "
            "verdict); the retrieval entry point always attaches a block — a "
            "fail-OPEN `SafetyBlock.unavailable()` when the check could not run "
            "— so the envelope shows whether the contract was checked."
        ),
    )
    backtest: BacktestReport | None = Field(
        default=None,
        description=(
            "Realized-history replay of the Strategist intent. None when "
            "enable_backtest=False (default) or when the panel is rerun "
            "by a caller that doesn't surface backtests."
        ),
    )
    # S24 WS-E — paid-call receipt. Populated by the gecko-api handler from
    # the x402 settle event (request.state.payment_payload). Always emitted
    # on the wire even in stub mode (so consumers can rely on the keys
    # existing); ``tx_signature`` + ``solscan_url`` are null in stub mode.
    # Build through :func:`gecko_core.payments.receipts.build_receipt` —
    # never construct these by hand at the call site.
    tx_signature: str | None = Field(
        default=None,
        description="Solana on-chain x402 settlement signature; null in stub mode.",
    )
    solscan_url: str | None = Field(
        default=None,
        description="Solscan deep link for tx_signature; null in stub mode.",
    )
    settlement_mode: SettlementMode = Field(
        default="stub",
        description=(
            "Whether real money moved on chain. 'stub' = no settlement (free / "
            "stub-mode runs); 'live' = on-chain x402 settle. Canonical literal "
            "lives in gecko_core.types (Pattern A)."
        ),
    )


__all__ = [
    "BacktestReport",
    "Citation",
    "InformationMEVBlock",
    "InformationMEVLabel",
    "SafetyBlock",
    "TradePanelTurn",
    "TradePanelVerdict",
    "TradeVerdictLiteral",
]
