"""Direct protocol-native API ingest — Kamino, Drift, Jupiter, Jito, Sanctum.

S26 #14. The trade-panel rubric eval (2026-05-12) surfaced that the
``paysh_live`` Kamino chunks in Mongo were literally ``{"data":[]}`` ×
7 — empty API responses from pay.sh-cataloged providers. The retrieval
was correct (S25 #13 boosts surface protocol-tagged chunks ahead of
canon) but the content was unusable, so citation_relevance stayed at
0.35 / 0.7 threshold.

This module defines free, public, protocol-native API endpoints to seed
the corpus with substantive vault-params / market-config / fee
manifests. Distinct from ``paysh_live``:

  - ``paysh_live`` = per-request paid x402 retrieval against pay.sh
    catalog providers. Chunks land in Mongo with a USDC ledger entry.
  - ``protocol_native`` (this module) = free, public protocol API
    content ingested ONCE into the corpus from a one-shot script. No
    payment; persisted with ``freshness_tier='daily'``; refreshable on
    a manual cadence.

Why a new ProviderKind (not "reuse paysh_live"):

  Per Pattern A (CLAUDE.md), the chunks-table ProviderKind is the
  single source of truth that gates retrieval admittance + the boost
  class. Mixing free protocol-API content under the ``paysh_live``
  label would (a) corrupt the spend ledger semantics, (b) make the
  empty pay.sh chunks indistinguishable from the new substantive
  ones at debugging time, and (c) violate the rule that one literal
  carries one concept. Adding ``protocol_native`` is a single-file
  edit per the Pattern A workflow.

Retrieval admittance: protocol_native is in the PROVIDER_SPECIFIC_KINDS
set used by ``_apply_retrieval_boosts`` — same +0.10 boost as
``paysh_live`` when the chunk's protocol tag matches the request.

Endpoint catalog (all public, free, no API key):

  Kamino:    https://api.kamino.finance/kamino-market/markets
             https://api.kamino.finance/v2/markets/{market}/reserves
  Drift:     https://dlob.drift.trade/markets
  Jupiter:   https://stats.jup.ag/  (HTML scrape for stats; falls back
             to https://quote-api.jup.ag/v6/tokens for catalog)
  Jito:      https://kobe.mainnet.jito.network/api/v1/recent_blocks
             https://www.jito.wtf/api/v1/...
  Sanctum:   https://sanctum-extra-api.ngrok.dev/v1/sol-value/current

This module exports the per-protocol URL catalogs + the rendering
helpers. The ingest is driven by
``scripts/protocol_native/ingest_protocol_native.py``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class ProtocolEndpoint:
    """One protocol-native endpoint to fetch + chunk + embed."""

    protocol: str
    slug: str
    url: str
    description: str
    content_kind: str = "mechanism"  # mechanism|governance|quote


# --- Kamino ----------------------------------------------------------------
# Kamino exposes a public API (no key) — markets + reserves + vault params.
# These endpoints return substantive JSON that grounds vault-mechanism
# answers (audit status, liquidation params, vault types, reserve mints).

KAMINO_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    ProtocolEndpoint(
        protocol="kamino",
        slug="kamino-markets",
        url="https://api.kamino.finance/v2/kamino-market",
        description=(
            "Kamino market catalog: main, JLP, Altcoin, JitoSOL etc. "
            "Each entry carries lendingMarket pubkey, description, and "
            "primary/curated/isolated flags. Substantive ground truth for "
            "vault-market mapping in Kamino-related verdicts."
        ),
        content_kind="mechanism",
    ),
    ProtocolEndpoint(
        protocol="kamino",
        slug="kamino-vaults",
        url="https://api.kamino.finance/kvaults/vaults",
        description=(
            "Kamino K-Vaults catalog — vault adminAuthority, tokenMint, "
            "tokenVault, vault state config. Includes Multiply / Leverage "
            "/ Yield vault types with their per-vault parameters."
        ),
        content_kind="mechanism",
    ),
    ProtocolEndpoint(
        protocol="kamino",
        slug="kamino-strategies",
        url="https://api.kamino.finance/strategies",
        description=(
            "Kamino concentrated-liquidity strategies catalog: each entry "
            "carries strategy address, type (PEGGED/NON_PEGGED), shareMint, "
            "tokenAMint, tokenBMint, status (LIVE/IGNORED/etc)."
        ),
        content_kind="mechanism",
    ),
    ProtocolEndpoint(
        protocol="kamino",
        slug="kamino-staking-yields",
        url="https://api.kamino.finance/v2/staking-yields",
        description=(
            "Kamino-tracked LST staking-yield snapshots — JitoSOL, mSOL, "
            "bSOL, INF current APY + 7d trailing. Quote-kind, refreshable."
        ),
        content_kind="quote",
    ),
)


# --- Drift -----------------------------------------------------------------
# S28 #26 depth pass — expand from 1 URL (3 chunks) to 12 URLs targeting
# perp markets, funding rate math, liquidation engine, oracle staleness,
# insurance fund, JIT auctions, prediction markets, market config.

def _drift(slug: str, path: str, desc: str, kind: str = "mechanism") -> ProtocolEndpoint:
    return ProtocolEndpoint(
        protocol="drift",
        slug=slug,
        url=f"https://docs.drift.trade/{path}" if not path.startswith("http") else path,
        description=desc,
        content_kind=kind,
    )


DRIFT_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    _drift("drift-docs-root", "", "Drift Protocol docs landing — index across all docs sections."),
    _drift(
        "drift-perps-trading",
        "protocol/trading/perpetuals-trading/perpetuals-trading",
        "Drift perpetuals overview — perp market mechanics, position lifecycle, "
        "leverage caps, margin requirements.",
    ),
    _drift(
        "drift-funding-rates",
        "protocol/trading/perpetuals-trading/funding-rates",
        "Drift funding rate mechanics — long-short equilibrium, premium/discount, "
        "payment frequency, oracle-derived mark price.",
    ),
    _drift(
        "drift-auction-parameters",
        "protocol/trading/perpetuals-trading/auction-parameters",
        "Drift perpetuals auction parameters — start price, end price, "
        "auction duration, slot increments.",
    ),
    _drift(
        "drift-liquidations",
        "protocol/trading/liquidations",
        "Drift liquidations overview — when accounts are eligible, sequence of "
        "actions, insurance-fund interaction.",
    ),
    _drift(
        "drift-liquidation-engine",
        "protocol/trading/liquidations/liquidation-engine",
        "Drift liquidation engine — maintenance margin thresholds, cascade "
        "dynamics, position priority, partial liquidations.",
    ),
    _drift(
        "drift-liquidators",
        "protocol/trading/liquidations/liquidators",
        "Drift liquidator role — incentives, bot architecture, eligibility, "
        "competition dynamics.",
    ),
    _drift(
        "drift-oracles",
        "protocol/trading/oracles",
        "Drift oracle design — Pyth + Switchboard sourcing, staleness tolerance, "
        "twap windows, mark price reconciliation.",
    ),
    _drift(
        "drift-risk-parameters",
        "protocol/risk-and-safety/risk-parameters",
        "Drift risk parameters — initial/maintenance margin, max leverage, "
        "per-market caps, asset weights.",
    ),
    _drift(
        "drift-risks",
        "protocol/risk-and-safety/risks",
        "Drift protocol risks — smart contract, oracle, liquidity, governance, "
        "insurance fund coverage.",
    ),
    _drift(
        "drift-safety-module",
        "protocol/risk-and-safety/drift-safety-module",
        "Drift safety module — circuit breakers, paused-market state, "
        "emergency procedures, governance triggers.",
    ),
    _drift(
        "drift-insurance-fund-staking",
        "protocol/insurance-fund/insurance-fund-staking",
        "Drift insurance fund staking — IF stake mechanics, revenue share, "
        "bad-debt absorption, withdrawal cooldown.",
    ),
    _drift(
        "drift-margin",
        "protocol/trading/margin",
        "Drift margin system — cross-margin model, asset weights, collateral "
        "types, account-health math.",
    ),
    _drift(
        "drift-margin-account-health",
        "protocol/trading/margin/account-health",
        "Drift account health — total collateral, free collateral, margin "
        "ratio, liquidation threshold derivation.",
    ),
    _drift(
        "drift-margin-per-market-leverage",
        "protocol/trading/margin/per-market-leverage",
        "Drift per-market leverage caps — overrides, scaling with size, "
        "tier-based limits.",
    ),
    _drift(
        "drift-jit-auctions-mm",
        "developers/market-makers/jit-auctions",
        "Drift JIT (Just-In-Time) auctions — MM bidding process, taker fill "
        "mechanics, auction duration, taker-vs-LP pricing.",
    ),
    _drift(
        "drift-amm",
        "protocol/about-v3/drift-amm",
        "Drift AMM (vAMM) — peg adjustment, fee allocation, k-curve, LP risk, "
        "spread mechanics.",
    ),
    _drift(
        "drift-matching-engine",
        "protocol/about-v3/matching-engine",
        "Drift matching engine — DLOB priority, order-types, fill semantics, "
        "AMM-vs-orderbook fallback.",
    ),
    _drift(
        "drift-decentralized-orderbook",
        "protocol/about-v3/decentralized-orderbook",
        "Drift DLOB — off-chain orderbook, on-chain settlement, keeper role "
        "in cranking matches.",
    ),
    _drift(
        "drift-borrow-lend-faq",
        "protocol/borrow-lend/borrow-lend-faq",
        "Drift borrow-lend FAQ — collateral types, interest accrual, "
        "isolated vs cross, withdrawal limits.",
    ),
    _drift(
        "drift-borrow-interest-rate",
        "protocol/borrow-lend/borrow-interest-rate",
        "Drift borrow interest rate model — utilization curve, optimal "
        "utilization point, slope1/slope2 segments.",
    ),
    _drift(
        "drift-isolated-pools",
        "protocol/borrow-lend/isolated-pools",
        "Drift isolated lending pools — risk isolation, asset-tier "
        "configuration, exit constraints.",
    ),
    _drift(
        "drift-amplify-risk",
        "protocol/borrow-lend/amplify/risk",
        "Drift Amplify risk — leveraged-yield mechanics, liquidation risk, "
        "loop-position unwind path.",
    ),
    _drift(
        "drift-market-specs",
        "protocol/trading/market-specs",
        "Drift market specs — per-market base asset, oracle, fees, "
        "leverage tiers.",
    ),
    _drift(
        "drift-trading-fees",
        "protocol/trading/trading-fees",
        "Drift trading fees — maker/taker schedule, tiers, rebates, "
        "discount mechanisms.",
    ),
    _drift(
        "drift-profit-loss",
        "protocol/trading/profit-loss",
        "Drift profit-and-loss — unsettled vs settled PnL, PnL pool, "
        "accounting model.",
    ),
    _drift(
        "drift-profit-loss-pool",
        "protocol/trading/profit-loss/profit-loss-pool",
        "Drift PnL pool — depositor mechanics, payout cap, role in covering "
        "winning trader PnL.",
    ),
    _drift(
        "drift-revenue-pool",
        "protocol/about-v3/revenue-pool",
        "Drift revenue pool — fee accrual, distribution to IF stakers, "
        "treasury policy.",
    ),
    _drift("drift-glossary", "protocol/glossary", "Drift glossary — protocol terminology canonical definitions."),
    _drift("drift-account-model", "developers/concepts/account-model",
           "Drift account model — UserAccount, subaccounts, MarketAccount, "
           "PerpMarket, SpotMarket data shape.",
           kind="mechanism"),
    _drift(
        "drift-dlob-markets",
        "https://dlob.drift.trade/markets",
        "Drift DLOB live market config — per-market index, oracle source, "
        "funding-rate snapshot, open interest.",
        kind="quote",
    ),
    _drift(
        "drift-github-readme",
        "https://raw.githubusercontent.com/drift-labs/protocol-v2/master/README.md",
        "Drift protocol-v2 GitHub README — program architecture, instruction "
        "surface, risk parameters.",
    ),
)


# --- Jupiter ---------------------------------------------------------------
# S28 #26 depth pass — expand from 2 URLs (4 chunks) to 12 URLs covering
# aggregator routing, JLP composition + risk + yield, LST routing, perp
# exchange mechanics, swap fee math.

def _jup(slug: str, path: str, desc: str, kind: str = "mechanism") -> ProtocolEndpoint:
    return ProtocolEndpoint(
        protocol="jupiter",
        slug=slug,
        url=path if path.startswith("http") else f"https://dev.jup.ag/docs/{path}",
        description=desc,
        content_kind=kind,
    )


JUPITER_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    _jup("jupiter-docs-root", "", "Jupiter Developer docs root — Swap, Perpetuals, Lend, Token, Price API mechanics."),
    _jup("jupiter-swap-root", "swap", "Jupiter Swap overview — aggregator design, route discovery, market coverage."),
    _jup("jupiter-swap-order-execute", "swap/order-and-execute",
         "Jupiter Order + Execute swap flow — building, signing, submitting an aggregated route trade."),
    _jup("jupiter-swap-slippage", "swap/advanced/slippage",
         "Jupiter swap slippage handling — auto-slippage, dynamic computation, settings for volatile assets."),
    _jup("jupiter-swap-reduce-latency", "swap/advanced/reduce-latency",
         "Jupiter swap latency reduction — RPC selection, priority fees, transaction sizing."),
    _jup("jupiter-swap-compute-units", "swap/advanced/compute-units",
         "Jupiter swap compute units — CU budget for aggregated routes, optimization strategies."),
    _jup("jupiter-swap-routing-dex-integration", "swap/routing/dex-integration",
         "Jupiter DEX integration for routing — eligibility, AMM types supported (CLMM, CPMM, stable pools)."),
    _jup("jupiter-swap-routing-market-listing", "swap/routing/market-listing",
         "Jupiter market listing for routing — pool inclusion criteria, liquidity thresholds, eligibility."),
    _jup("jupiter-swap-routing-rfq", "swap/routing/rfq-integration",
         "Jupiter RFQ routing — request-for-quote market-maker integration, when RFQ wins vs AMM routing."),
    _jup("jupiter-perps-root", "perps", "Jupiter Perpetuals overview — JLP pool, position model, custody accounts."),
    _jup("jupiter-perps-pool-account", "perps/pool-account",
         "Jupiter JLP pool account structure — composition (SOL, ETH, BTC, USDC, USDT), AUM, target weights."),
    _jup("jupiter-perps-custody-account", "perps/custody-account",
         "Jupiter perps custody accounts — per-asset custody state, owned amounts, locked amounts, funding."),
    _jup("jupiter-perps-position-account", "perps/position-account",
         "Jupiter perps position account — open size, collateral, side, entry price, realized PnL."),
    _jup("jupiter-perps-position-request", "perps/position-request-account",
         "Jupiter perps position request — open/close/decrease/increase request lifecycle, keeper execution."),
    _jup("jupiter-tokens-root", "tokens",
         "Jupiter Token API overview — token universe, metadata, tag taxonomy (verified, lst, stablecoin, community)."),
    _jup("jupiter-tokens-verification", "tokens/verification",
         "Jupiter token verification criteria — what qualifies a mint for the verified tag, abuse mitigations."),
    _jup("jupiter-tokens-token-information", "tokens/token-information",
         "Jupiter token information fields — metadata, dailyVolume, freezeAuthority, mintAuthority, ts pricing."),
    _jup("jupiter-price-doc", "price",
         "Jupiter Price API overview — derived price discovery via aggregator routes, depth-aware pricing."),
    _jup("jupiter-lend-architecture", "lend/architecture",
         "Jupiter Lend architecture — earn vs borrow surfaces, vault structure, oracle integration."),
    _jup("jupiter-lend-oracles", "lend/oracles",
         "Jupiter Lend oracles — Pyth integration, staleness checks, price-fetch fallbacks."),
    _jup("jupiter-lend-liquidation", "lend/borrow/liquidation",
         "Jupiter Lend liquidation — LTV thresholds, liquidator incentives, partial vs full liquidation."),
    _jup("jupiter-lend-advanced-multiply", "lend/advanced/multiply",
         "Jupiter Lend multiply (leveraged-yield) — loop construction, max LTV, unwind path on liquidation risk."),
    _jup("jupiter-lend-advanced-unwind", "lend/advanced/unwind",
         "Jupiter Lend unwind — closing a leveraged position, swap costs, residual collateral."),
    _jup("jupiter-trigger-best-practices", "trigger/best-practices",
         "Jupiter Trigger orders — limit-order semantics, partial fills, cancellation, gas considerations."),
    _jup("jupiter-recurring-best-practices", "recurring/best-practices",
         "Jupiter Recurring orders — DCA mechanics, schedule, execution priority, slippage protection."),
    _jup("jupiter-portal-rate-limits", "portal/rate-limits",
         "Jupiter Portal rate limits — request/sec, tier plans, error handling, exponential backoff guidance."),
    _jup("jupiter-resources-audits", "resources/audits", "Jupiter audits — auditor list, scope, dates, findings."),
    _jup("jupiter-sol-price",
         "https://lite-api.jup.ag/price/v3?ids=So11111111111111111111111111111111111111112",
         "Jupiter Lite-API SOL price + 24h liquidity + priceChange24h. Quote-kind.",
         kind="quote"),
    _jup("jupiter-lst-prices",
         "https://lite-api.jup.ag/price/v3?ids="
         "J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn,"
         "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So,"
         "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1,"
         "5oVNBeEEQvYi1cX3ir8Dx5n1P7pdxydbGF2X4TxVusJm",
         "Jupiter Lite-API LST snapshot — JitoSOL, mSOL, bSOL, INF prices for LST rotation analysis.",
         kind="quote"),
    _jup("jupiter-tokens-verified-list",
         "https://lite-api.jup.ag/tokens/v2/tag?query=verified",
         "Jupiter verified-token list — canonical Solana mints curated for routing.",
         kind="mechanism"),
    _jup("jupiter-tokens-lst-list",
         "https://lite-api.jup.ag/tokens/v2/tag?query=lst",
         "Jupiter LST-tagged tokens — JitoSOL, mSOL, bSOL, INF, hSOL et al with metadata.",
         kind="mechanism"),
)


# --- Jito ------------------------------------------------------------------
# S28 #26 depth pass — expand from 2 URLs (3 chunks, worst citRel 0.15) to
# 14 URLs across JitoSOL mechanics, MEV bundle landing, tip distribution,
# restaking, block-engine, validator selection.

def _jito(slug: str, url: str, desc: str, kind: str = "mechanism") -> ProtocolEndpoint:
    return ProtocolEndpoint(protocol="jito", slug=slug, url=url, description=desc, content_kind=kind)


JITO_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    # --- Live quote endpoints ---
    _jito(
        "jito-tip-floor",
        "https://bundles.jito.wtf/api/v1/bundles/tip_floor",
        "Jito tip-floor percentiles (P25/P50/P75/P95/P99) for bundle landing — "
        "current snapshot. Grounds tip-band decisions in real lamport figures.",
        kind="quote",
    ),
    _jito(
        "jito-mev-rewards",
        "https://kobe.mainnet.jito.network/api/v1/mev_rewards",
        "Jito MEV rewards — recent-epoch MEV totals, distribution snapshot.",
        kind="quote",
    ),
    _jito(
        "jito-validators",
        "https://kobe.mainnet.jito.network/api/v1/validators",
        "Jito validator set telemetry — MEV share, commission, stake size, "
        "performance scores.",
        kind="quote",
    ),
    _jito(
        "jito-recent-blocks",
        "https://kobe.mainnet.jito.network/api/v1/recent_blocks",
        "Jito recent blocks — block engine production telemetry: slot, leader, "
        "bundle count, tip totals.",
        kind="quote",
    ),
    # --- docs.jito.wtf (the two big pages, sphinx) ---
    _jito(
        "jito-docs-root",
        "https://docs.jito.wtf/",
        "Jito Labs docs landing — index across MEV protocol architecture.",
    ),
    _jito(
        "jito-docs-low-latency-txn-send",
        "https://docs.jito.wtf/lowlatencytxnsend/",
        "Jito low-latency transaction send — block engine, bundle submission "
        "API (sendBundle, getBundleStatuses, getInflightBundleStatuses, tip "
        "accounts), atomicity guarantees, MEV protection model, JSON-RPC "
        "authentication, tip percentiles, regional endpoints. ~90KB.",
    ),
    _jito(
        "jito-docs-low-latency-txn-feed",
        "https://docs.jito.wtf/lowlatencytxnfeed/",
        "Jito low-latency transaction feed — ShredStream proxy mechanics, "
        "shred receive flow, latency vs reliability tradeoff, integration "
        "patterns for searchers. ~40KB.",
    ),
    # --- jito.wtf product landing pages ---
    _jito(
        "jito-wtf-searchers",
        "https://www.jito.wtf/searchers/",
        "Jito Searchers product page — MEV searcher value proposition, bundle "
        "mechanics, tip economics, integration paths.",
    ),
    _jito(
        "jito-wtf-stakers",
        "https://www.jito.wtf/stakers/",
        "Jito Stakers product page — JitoSOL liquid staking, MEV-boosted "
        "yield, redemption, validator selection.",
    ),
    _jito(
        "jito-wtf-validators",
        "https://www.jito.wtf/validators/",
        "Jito Validators product page — running the jito-solana client, "
        "MEV-share economics, validator onboarding.",
    ),
    _jito(
        "jito-wtf-blog-index",
        "https://www.jito.wtf/blog/",
        "Jito blog index — recent posts on protocol changes, ecosystem "
        "milestones, MEV research.",
    ),
    # --- Jito GitHub READMEs (mechanism documentation in markdown) ---
    _jito(
        "jito-stakenet-readme",
        "https://raw.githubusercontent.com/jito-foundation/stakenet/master/README.md",
        "Jito Stakenet README — Steward program overview, validator scoring, "
        "automated delegation rebalancing for JitoSOL stake pool.",
    ),
    _jito(
        "jito-stakenet-keeper-quickstart",
        "https://raw.githubusercontent.com/jito-foundation/stakenet/master/keeper-bot-quick-start.md",
        "Jito Stakenet keeper-bot quickstart — Steward operator runbook, "
        "cycle steps, validator score thresholds, delegation rebalance flow.",
    ),
    _jito(
        "jito-stakenet-docs-index",
        "https://raw.githubusercontent.com/jito-foundation/stakenet/master/docs/index.md",
        "Jito Stakenet docs index — pointer to Steward program component map.",
    ),
    _jito(
        "jito-restaking-readme",
        "https://raw.githubusercontent.com/jito-foundation/restaking/master/README.md",
        "Jito Restaking README — protocol overview, NCN (Node Consensus "
        "Network) model, VRT (Vault Receipt Token) mechanics, slashing design.",
    ),
    _jito(
        "jito-restaking-docs-index",
        "https://raw.githubusercontent.com/jito-foundation/restaking/master/docs/index.md",
        "Jito Restaking docs index — restaking + vault program component map.",
    ),
    _jito(
        "jito-solana-readme",
        "https://raw.githubusercontent.com/jito-labs/jito-solana/master/README.md",
        "jito-solana validator README — fork of Solana Labs validator with "
        "Jito-specific block-engine integration, MEV bundle inclusion.",
    ),
    _jito(
        "jito-solana-security",
        "https://raw.githubusercontent.com/jito-labs/jito-solana/master/SECURITY.md",
        "jito-solana security policy — disclosure process, scope, "
        "responsible-disclosure timing.",
    ),
    _jito(
        "jito-mev-protos-readme",
        "https://raw.githubusercontent.com/jito-labs/mev-protos/master/README.md",
        "Jito MEV protos README — gRPC protobuf schemas for block-engine, "
        "searcher, relayer, auction service.",
    ),
    _jito(
        "jito-js-rpc-readme",
        "https://raw.githubusercontent.com/jito-labs/jito-js-rpc/master/README.md",
        "Jito JS RPC client README — bundle submission patterns, tip account "
        "configuration, regional endpoint selection from TypeScript.",
    ),
    _jito(
        "jito-py-rpc-readme",
        "https://raw.githubusercontent.com/jito-labs/jito-py-rpc/master/README.md",
        "Jito Python RPC client README — bundle submission patterns, tip "
        "accounts, regional endpoint selection from Python.",
    ),
    _jito(
        "jito-go-rpc-readme",
        "https://raw.githubusercontent.com/jito-labs/jito-go-rpc/master/README.md",
        "Jito Go RPC client README — bundle submission patterns from Go.",
    ),
    _jito(
        "jito-rust-rpc-readme",
        "https://raw.githubusercontent.com/jito-labs/jito-rust-rpc/master/README.md",
        "Jito Rust RPC client README — bundle submission patterns from Rust.",
    ),
)


# --- Sanctum ---------------------------------------------------------------
# S28 #26 depth pass — expand from 1 URL (2 chunks) to 12 URLs covering
# Infinity pool mechanics, INF behavior, peg dynamics, LST router math,
# yield rebalancing, sol-value snapshots.

def _sanc(slug: str, url: str, desc: str, kind: str = "mechanism") -> ProtocolEndpoint:
    return ProtocolEndpoint(protocol="sanctum", slug=slug, url=url, description=desc, content_kind=kind)


SANCTUM_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    _sanc(
        "sanctum-docs-root",
        "https://learn.sanctum.so/docs",
        "Sanctum learn docs landing — index across the Sanctum surface.",
    ),
    _sanc(
        "sanctum-mission",
        "https://learn.sanctum.so/docs/introduction-to-sanctum/the-sanctum-mission",
        "Sanctum mission — unify Solana LSTs into a single liquid layer; "
        "router + infinity pool design rationale.",
    ),
    _sanc(
        "sanctum-pow-pos",
        "https://learn.sanctum.so/docs/introduction-to-lsts/pow-and-pos-blockchains",
        "Sanctum LST intro — PoW vs PoS distinction, why staking exists, "
        "validator role, slashing risk vs reward.",
    ),
    _sanc(
        "sanctum-from-native-to-liquid",
        "https://learn.sanctum.so/docs/introduction-to-lsts/from-native-to-liquid-staking",
        "Sanctum — from native staking to liquid staking: cooldown problem, "
        "LST mechanic as fix, exchange-rate dynamics.",
    ),
    _sanc(
        "sanctum-optimal-lst-state",
        "https://learn.sanctum.so/docs/introduction-to-lsts/making-the-state-of-liquid-staking-optimal",
        "Sanctum on optimal LST state — fragmentation problem, unified "
        "liquidity argument, infrastructure layer.",
    ),
    _sanc(
        "sanctum-router-technical",
        "https://learn.sanctum.so/docs/technical-documentation/router",
        "Sanctum Router — technical doc: instant LST↔LST and LST→SOL "
        "conversion, spread computation, pool depth math, fee tier.",
    ),
    _sanc(
        "sanctum-infinity-technical",
        "https://learn.sanctum.so/docs/technical-documentation/infinity",
        "Sanctum Infinity pool — technical doc: INF as basket LST, "
        "underlying LST composition, weight bands, rebalance trigger, "
        "peg maintenance, LP fee accrual.",
    ),
    _sanc(
        "sanctum-infinity-non-technical",
        "https://learn.sanctum.so/docs/technical-documentation/infinity-non-technical",
        "Sanctum Infinity (non-technical) — INF user-facing explanation, "
        "what INF returns, when to use vs router.",
    ),
    _sanc(
        "sanctum-reserve-technical",
        "https://learn.sanctum.so/docs/technical-documentation/reserve",
        "Sanctum Reserve — SOL backing reserves for instant unstakes, "
        "fee accrual model, depositor mechanics.",
    ),
    _sanc(
        "sanctum-lsts-technical",
        "https://learn.sanctum.so/docs/technical-documentation/sanctum-lsts",
        "Sanctum LSTs technical — stake-pool model, validator selection "
        "delegation, branding, creator economics, the lst-program standard.",
    ),
    _sanc(
        "sanctum-gateway-technical",
        "https://learn.sanctum.so/docs/technical-documentation/gateway",
        "Sanctum Gateway — composability layer for LST issuers and "
        "downstream protocols, integration patterns.",
    ),
    _sanc(
        "sanctum-creating-lst-understanding",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/understanding-sanctum-lsts",
        "Sanctum — understanding-sanctum-lsts: design philosophy, "
        "what makes a Sanctum LST distinct from a stake-pool LST.",
    ),
    _sanc(
        "sanctum-creating-lst-package",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/the-sanctum-package",
        "Sanctum LST creation package — what new issuers receive: "
        "router integration, infinity inclusion eligibility, branding kit.",
    ),
    _sanc(
        "sanctum-creating-lst-setup",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/the-setup-process-launching-your-lst",
        "Sanctum LST launch setup process — steps from token mint to "
        "router listing.",
    ),
    _sanc(
        "sanctum-creating-lst-mint",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/the-setup-process-launching-your-lst/creating-the-token-mint",
        "Sanctum LST creation — creating-the-token-mint: SPL mint flow, "
        "authorities, supply controls.",
    ),
    _sanc(
        "sanctum-creating-lst-things-to-know",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/the-setup-process-launching-your-lst/a-few-things-you-should-know-about",
        "Sanctum LST creation — operational considerations, validator "
        "delegation rules, MEV pass-through model.",
    ),
    _sanc(
        "sanctum-creating-lst-post-deployment",
        "https://learn.sanctum.so/docs/creating-your-own-lst-with-sanctum/post-deployment-additional-information",
        "Sanctum LST post-deployment — monitoring, validator changes, "
        "branding updates, holder communications.",
    ),
    _sanc(
        "sanctum-developers-deployed-programs",
        "https://learn.sanctum.so/docs/for-developers/deployed-programs",
        "Sanctum deployed programs — on-chain program addresses for router, "
        "infinity, reserve, stake-pool program.",
    ),
    _sanc(
        "sanctum-developers-sanctum-api",
        "https://learn.sanctum.so/docs/for-developers/sanctum-api",
        "Sanctum API for developers — sol-value, APY, router quote, INF "
        "redemption-quote endpoints.",
    ),
    # Quote endpoints (live snapshots; refreshable)
    _sanc(
        "sanctum-sol-value-inf",
        "https://sanctum-extra-api.ngrok.dev/v1/sol-value/current?lst=INF",
        "Sanctum INF current sol-value — INF expressed in SOL.",
        kind="quote",
    ),
    _sanc(
        "sanctum-sol-value-jitosol",
        "https://sanctum-extra-api.ngrok.dev/v1/sol-value/current?lst=jitoSOL",
        "Sanctum JitoSOL current sol-value snapshot.",
        kind="quote",
    ),
    _sanc(
        "sanctum-apy-inf",
        "https://sanctum-extra-api.ngrok.dev/v1/apy/latest?lst=INF",
        "Sanctum INF latest APY snapshot.",
        kind="quote",
    ),
    _sanc(
        "sanctum-apy-jitosol",
        "https://sanctum-extra-api.ngrok.dev/v1/apy/latest?lst=jitoSOL",
        "Sanctum JitoSOL latest APY snapshot.",
        kind="quote",
    ),
    _sanc(
        "sanctum-apy-msol",
        "https://sanctum-extra-api.ngrok.dev/v1/apy/latest?lst=mSOL",
        "Sanctum mSOL latest APY snapshot.",
        kind="quote",
    ),
    _sanc(
        "sanctum-apy-bsol",
        "https://sanctum-extra-api.ngrok.dev/v1/apy/latest?lst=bSOL",
        "Sanctum bSOL latest APY snapshot.",
        kind="quote",
    ),
)


ALL_PROTOCOL_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    *KAMINO_ENDPOINTS,
    *DRIFT_ENDPOINTS,
    *JUPITER_ENDPOINTS,
    *JITO_ENDPOINTS,
    *SANCTUM_ENDPOINTS,
)


def endpoints_for_protocol(protocol: str) -> tuple[ProtocolEndpoint, ...]:
    """Return the endpoints catalog for a given protocol slug."""
    catalog: dict[str, tuple[ProtocolEndpoint, ...]] = {
        "kamino": KAMINO_ENDPOINTS,
        "drift": DRIFT_ENDPOINTS,
        "jupiter": JUPITER_ENDPOINTS,
        "jito": JITO_ENDPOINTS,
        "sanctum": SANCTUM_ENDPOINTS,
    }
    return catalog.get(protocol.lower(), ())


def render_chunk(ep: ProtocolEndpoint, body_text: str, as_of_iso: str) -> str:
    """Render a fetched body as a substantive prose chunk.

    The chunk includes ``description`` (what this content represents),
    the as-of timestamp, the source URL, and the body. Keeps citation
    rendering well-formed downstream — voices know what the content
    means without re-reading the URL.
    """
    return (
        f"Protocol-native API: {ep.protocol} / {ep.slug} (as of {as_of_iso}).\n"
        f"Endpoint description: {ep.description}\n"
        f"Source URL: {ep.url}\n"
        f"Content kind: {ep.content_kind}\n"
        f"----- body -----\n"
        f"{body_text}\n"
        f"----- end body -----\n"
        f"Provider: protocol_native."
    )


__all__ = [
    "ALL_PROTOCOL_ENDPOINTS",
    "DRIFT_ENDPOINTS",
    "JITO_ENDPOINTS",
    "JUPITER_ENDPOINTS",
    "KAMINO_ENDPOINTS",
    "SANCTUM_ENDPOINTS",
    "ProtocolEndpoint",
    "endpoints_for_protocol",
    "render_chunk",
]
