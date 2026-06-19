"""Attack catalog — the canonical taxonomy of how a Solana token's market gets
manufactured, and how Gecko detects + mitigates each pattern.

This is the knowledge backbone of the Launch Firewall. The product's moat is
*depth of harm-detection* (Pattern D: orchestration is table stakes; knowing
every manufacture-the-market attack better than anyone is the wedge). Encoding
that knowledge once, machine-readably, lets it drive three things from a single
source of truth:

* the **firewall** maps its fired signal codes → the attack(s) they imply
  (:func:`patterns_for_signals`) so a verdict can name the attack, not just a flag;
* the **classifier** (trained on the MELT dataset) labels to these pattern ids;
* the **report / skill** explains a block in terms of a named, documented attack
  + its real-world example + the mitigation.

Pure data + lookups: ``pydantic`` + stdlib only, no I/O. Detection coverage is
stated honestly per pattern (``coverage``) — some patterns need data paths we
have not built yet (signer-level parsed tx, account-age, Jito-bundle tagging);
those are marked ``planned`` / ``external`` rather than overclaimed.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# How soon the pattern can be detected relative to the event.
LatencyTier = Literal["realtime", "batch", "static", "external"]
# How much of this attack Gecko's engine covers today.
Coverage = Literal["live", "partial", "planned", "out_of_scope"]


class AttackPattern(BaseModel):
    """One way a token's market is manufactured (or the agent is harmed)."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable machine id, e.g. 'thin_pool_buy_loop'.")
    name: str
    category: str = Field(
        ..., description="market_data | execution_mev | contract_rug | custody | agent_logic"
    )
    description: str = Field(..., description="What the attacker does + how it harms.")
    on_chain_signature: str = Field(..., description="The observable on-chain footprint.")
    signals: list[str] = Field(
        default_factory=list,
        description="Gecko signal codes that fire on this pattern ([] = not yet detected).",
    )
    latency_tier: LatencyTier
    coverage: Coverage
    melt_feature_group: str | None = Field(
        default=None,
        description="The MELT-dataset feature group that trains a classifier for this.",
    )
    mitigations_issuer: list[str] = Field(default_factory=list)
    mitigations_agent: list[str] = Field(default_factory=list)
    example: str | None = Field(default=None, description="A real-world instance.")


# --------------------------------------------------------------------------- #
# The catalog                                                                  #
# --------------------------------------------------------------------------- #

CATALOG: tuple[AttackPattern, ...] = (
    # ---- market-data integrity (Plane C — Gecko's wedge) ------------------ #
    AttackPattern(
        id="thin_pool_buy_loop",
        name="Thin-pool buy-loop (inflate-then-drain)",
        category="market_data",
        description=(
            "Bots fire many tiny, uniform, one-sided buys into a thin pool so the "
            "price climbs on near-zero real notional; retail/agents chase the fake "
            "demand and the operator dumps."
        ),
        on_chain_signature="buys≫sells over a short window, tiny uniform sizes, price rising, few makers",
        signals=["thin_pool_buy_loop"],
        latency_tier="realtime",
        coverage="live",
        melt_feature_group="market_activity",
        mitigations_issuer=["publish launch-integrity report", "delay aggregator listing 2-3 min"],
        mitigations_agent=["abstain", "require N clean slots before entry"],
        example="BrCA — climbing chart on ~$6.5K liquidity",
    ),
    AttackPattern(
        id="multi_pool_price_bait",
        name="Multi-pool price bait",
        category="market_data",
        description=(
            "The token is quoted far above its liquidity-weighted index price in "
            "thin, dead satellite pools so a naive price read is inflated."
        ),
        on_chain_signature="max_pool_price / index_price > ~1.5 with the high-priced pools dead (≈0 trades, tiny TVL)",
        signals=["multi_pool_price_bait"],
        latency_tier="realtime",
        coverage="live",
        melt_feature_group="market_activity",
        mitigations_agent=["price off the liquidity-weighted index, never max-pool", "abstain"],
        example="BrCA — $5.8 / $6.9 / $10.2 across satellite pools",
    ),
    AttackPattern(
        id="wash_self_trade",
        name="Wash / self-trade",
        category="market_data",
        description=(
            "A wallet (or small ring) trades both sides in balance with no net "
            "fresh capital — manufacturing volume with no price discovery."
        ),
        on_chain_signature="per-wallet buy≈sell volume, ≥4 round-trips, net external inflow ≈ 0",
        signals=["wash_self_trade"],
        latency_tier="batch",
        coverage="partial",  # scorer fires; awaits per-wallet parsed-tx ingest
        melt_feature_group="bundle_statistics",
        mitigations_agent=["discount manufactured volume", "abstain"],
        example="VanEck: 41% of Solana memecoin volume is wash-traded",
    ),
    AttackPattern(
        id="common_funder_sybil",
        name="Common-funder sybil cluster",
        category="market_data",
        description=(
            "The 'many buyers' were funded by a few fresh wallets just before "
            "launch — coordinated demand masquerading as organic."
        ),
        on_chain_signature="≥60% of buyers share ≤3 fresh funders, funded <24h pre-launch, near-identical amounts",
        signals=["common_funder_sybil"],
        latency_tier="batch",
        coverage="partial",  # scorer fires; awaits funder-graph (getSignaturesForAddress per buyer)
        melt_feature_group="bundle_statistics",
        mitigations_issuer=["blocklist the cluster (own frontend/launchpad only)"],
        mitigations_agent=["abstain"],
        example="MELT: 21% of pre-migration txns are wash/coordinated",
    ),
    AttackPattern(
        id="fake_market_cap",
        name="Fake market cap (thin liquidity vs mcap)",
        category="market_data",
        description="A large headline market cap unsupportable by on-chain liquidity — the price is air.",
        on_chain_signature="liquidity_to_mcap < ~0.2% AND liquidity small in absolute terms",
        signals=["fake_market_cap", "thin_liquidity_vs_mcap"],
        latency_tier="static",
        coverage="live",
        melt_feature_group="market_activity",
        mitigations_agent=["block — price cannot be realized"],
        example="BrCA — $5.73M mcap on $6.5K liquidity (0.11%)",
    ),
    AttackPattern(
        id="single_wallet_float",
        name="Single-wallet float / holder concentration",
        category="market_data",
        description="One wallet holds enough supply to dump the chart at will.",
        on_chain_signature="top holder ≥ ~35% of supply",
        signals=["high_holder_concentration"],
        latency_tier="static",
        coverage="live",
        melt_feature_group="holding_concentration",
        mitigations_agent=["size-down or abstain"],
        example="BrCA — top holder 72%",
    ),
    AttackPattern(
        id="oracle_manipulation",
        name="Oracle manipulation (information-MEV)",
        category="market_data",
        description=(
            "Attacker mints a token, seeds tiny liquidity, wash-trades a short "
            "price history, an oracle ingests it, and a downstream protocol "
            "(lending/perps) is drained on the fake price."
        ),
        on_chain_signature="brand-new token + thin liquidity + wash-built price history feeding an oracle",
        signals=["fake_market_cap", "thin_pool_buy_loop"],
        latency_tier="realtime",
        coverage="partial",
        mitigations_agent=["never use a thin/new token's pool price as an oracle input"],
        example="Drift −$285M (Apr 2026) — fake CVT token, ~12-min wash history",
    ),
    # ---- snipe / execution (real-time tells; need parsed-tx data) --------- #
    AttackPattern(
        id="jito_bundle_snipe",
        name="Jito-bundle snipe",
        category="execution_mev",
        description=(
            "A buy submitted inside a Jito bundle — categorically automated; the "
            "single highest-precision 'this is a bot, not a human' tell."
        ),
        on_chain_signature="tx transfers to one of the 8 Jito tip accounts (hotpath.jito.is_jito_bundle_tx)",
        signals=[],
        latency_tier="realtime",
        coverage="planned",  # detection encoded (jito.py); needs the parsed-tx account-key path
        mitigations_issuer=["choose a launchpad with anti-snipe fee mechanics (Meteora)"],
        mitigations_agent=["abstain on bundle-snipe-dominated launches"],
    ),
    AttackPattern(
        id="same_slot_co_buy",
        name="Same-slot co-buy cluster (snipe)",
        category="execution_mev",
        description=(
            ">N distinct wallets buy the same thin pool in the same ~400ms slot — "
            "coordinated sniping no organic crowd produces."
        ),
        on_chain_signature="≥3 distinct makers on one low-liq pool within a single slot, similar size",
        signals=[],
        latency_tier="realtime",
        coverage="planned",  # needs signer-level attribution per swap
        melt_feature_group="bundle_statistics",
        mitigations_agent=["require N clean slots before entry"],
    ),
    AttackPattern(
        id="fresh_wallet_swarm",
        name="Fresh-wallet swarm",
        category="execution_mev",
        description="The early buyers are wallets created <24-48h before the launch — bot-spun, not real holders.",
        on_chain_signature="majority of first-buyers' accounts created <48h before first interaction",
        signals=[],
        latency_tier="batch",
        coverage="planned",  # needs account-age lookup (getAsset/creation slot)
        melt_feature_group="contextual_info",
        mitigations_agent=["weight fresh-wallet-dominated demand as fake"],
    ),
    AttackPattern(
        id="sandwich_mev",
        name="Sandwich / front-run",
        category="execution_mev",
        description=(
            "A searcher detects the victim's pending swap and brackets it in a Jito "
            "bundle [frontrun, victim, backrun]: buys before (pushing price up), the "
            "victim fills worse, then sells after — pocketing the spread. Harms "
            "execution, not market data. (Solana has no public mempool — txs are "
            "forwarded to the leader + expire ~150 blocks — so the surface is "
            "narrower than Ethereum, and atomic arbitrage is benign; sandwiches are "
            "the harmful kind.)"
        ),
        on_chain_signature="same searcher buy@index_i-1, sell@index_i+1 around a third-party swap in one bundle",
        signals=[],
        latency_tier="realtime",
        coverage="out_of_scope",  # we don't sit in the block; this is a SEND-SIDE mitigation
        mitigations_agent=[
            "add a read-only account whose pubkey starts with 'jitodontfront' to the "
            "swap — Jito's block engine then forces your tx to bundle index 0, so no "
            "front-run can precede it (Jito dontfront)",
            "send via a Jito-protected / MEV-protected RPC",
            "set a tight slippage cap so a sandwich is unprofitable",
        ],
        example="Jito dontfront — solana.com/developers/guides/advanced/mev-protection",
    ),
    # ---- contract-level rug (we surface flags; auditor goes deeper) ------- #
    AttackPattern(
        id="honeypot",
        name="Honeypot (can't sell)",
        category="contract_rug",
        description="Un-renounced freeze authority or sell-blocking logic — you can buy but not exit.",
        on_chain_signature="freeze authority live / sell simulation fails",
        signals=["honeypot", "freeze_not_renounced"],
        latency_tier="static",
        coverage="partial",
        mitigations_agent=["block"],
    ),
    AttackPattern(
        id="mint_dilution",
        name="Mint authority live (dilution)",
        category="contract_rug",
        description="Dev can mint more supply and dilute holders.",
        on_chain_signature="mint authority not renounced",
        signals=["mint_not_renounced"],
        latency_tier="static",
        coverage="partial",
        mitigations_agent=["caution / size-down"],
    ),
    AttackPattern(
        id="rug_pull_lp_remove",
        name="Rug pull (LP removal)",
        category="contract_rug",
        description="Dev yanks the liquidity, collapsing the price to zero.",
        on_chain_signature="large liquidity-remove vs add ratio; sudden reserve drain by the creator",
        signals=[],
        latency_tier="realtime",
        coverage="planned",
        melt_feature_group="market_activity",
        mitigations_agent=["abstain on un-locked LP"],
        example="Solidus: 93% of Raydium pools show soft-rug characteristics",
    ),
    AttackPattern(
        id="depeg",
        name="Peg-asset depeg",
        category="market_data",
        description="An LST/stablecoin used as collateral or quote drifts off peg.",
        on_chain_signature="material deviation from peg per a peg oracle",
        signals=["depeg_risk"],
        latency_tier="external",
        coverage="live",
        mitigations_agent=["block on material depeg"],
    ),
)

_BY_ID: dict[str, AttackPattern] = {p.id: p for p in CATALOG}
_BY_SIGNAL: dict[str, list[AttackPattern]] = {}
for _p in CATALOG:
    for _s in _p.signals:
        _BY_SIGNAL.setdefault(_s, []).append(_p)


def get_pattern(pattern_id: str) -> AttackPattern | None:
    """Look up one pattern by id."""
    return _BY_ID.get(pattern_id)


def patterns_for_signals(fired_signals: list[str]) -> list[AttackPattern]:
    """The attack patterns implied by a set of fired Gecko signal codes.

    Lets a verdict say *"thin-pool buy-loop + fake market cap"* instead of a bare
    flag list. De-duplicated, catalog order preserved.
    """
    fired = set(fired_signals)
    return [p for p in CATALOG if fired & set(p.signals)]


def patterns_by_coverage(coverage: Coverage) -> list[AttackPattern]:
    """All patterns at a given coverage level (e.g. 'planned' = the build roadmap)."""
    return [p for p in CATALOG if p.coverage == coverage]


__all__ = [
    "CATALOG",
    "AttackPattern",
    "Coverage",
    "LatencyTier",
    "get_pattern",
    "patterns_by_coverage",
    "patterns_for_signals",
]
