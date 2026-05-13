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

DRIFT_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    ProtocolEndpoint(
        protocol="drift",
        slug="drift-docs-root",
        url="https://docs.drift.trade/",
        description=(
            "Drift Protocol docs landing — funding mechanism, leverage "
            "caps, oracle config, liquidation parameters across perp + spot "
            "markets. HTML rendered to plain text at ingest."
        ),
        content_kind="mechanism",
    ),
)


# --- Jupiter ---------------------------------------------------------------

JUPITER_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    ProtocolEndpoint(
        protocol="jupiter",
        slug="jupiter-docs-root",
        url="https://dev.jup.ag/docs/",
        description=(
            "Jupiter Developer docs root — Swap API, Perpetuals (JLP), "
            "token-API, price API mechanics. Mechanism content for the "
            "Jupiter product surface. HTML rendered to plain text."
        ),
        content_kind="mechanism",
    ),
    ProtocolEndpoint(
        protocol="jupiter",
        slug="jupiter-sol-price",
        url=(
            "https://lite-api.jup.ag/price/v3"
            "?ids=So11111111111111111111111111111111111111112"
        ),
        description=(
            "Jupiter Lite-API SOL price + 24h liquidity + priceChange24h. "
            "Quote-kind, refreshable. Grounds Jupiter-context price "
            "discussions in real numbers."
        ),
        content_kind="quote",
    ),
)


# --- Jito ------------------------------------------------------------------

JITO_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    ProtocolEndpoint(
        protocol="jito",
        slug="jito-tip-floor",
        url="https://bundles.jito.wtf/api/v1/bundles/tip_floor",
        description=(
            "Jito tip-floor percentiles (P25/P50/P75/P95) for bundle "
            "landing — current snapshot. Quote-kind; grounds tip-band "
            "decisions in real numbers instead of hallucinated lamport "
            "figures."
        ),
        content_kind="quote",
    ),
    ProtocolEndpoint(
        protocol="jito",
        slug="jito-docs-root",
        url="https://docs.jito.wtf/",
        description=(
            "Jito Labs docs landing — JitoSOL LST mechanics, bundle "
            "landing, tip distribution, validator commission. HTML "
            "rendered to plain text."
        ),
        content_kind="mechanism",
    ),
)


# --- Sanctum ---------------------------------------------------------------

SANCTUM_ENDPOINTS: Final[tuple[ProtocolEndpoint, ...]] = (
    ProtocolEndpoint(
        protocol="sanctum",
        slug="sanctum-docs-learn",
        url="https://learn.sanctum.so/docs",
        description=(
            "Sanctum LSTs + router docs — INF token, router spread, "
            "unstaking mechanics, pool depth. HTML rendered to plain "
            "text at ingest."
        ),
        content_kind="mechanism",
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
