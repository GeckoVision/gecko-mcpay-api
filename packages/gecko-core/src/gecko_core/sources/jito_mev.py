"""S31-#50 — Jito MEV-tip-floor-specific source catalog.

The jito-2025Q2-mev-tip-band rubric fixture (citRel 0.15 in V1-FINAL)
asks about MEV tip-band data — P75 vs P90 floor for high-frequency arb
bundles. The corpus's existing Jito chunks (S28-#26) are dominated by
JitoSOL staking / validator-selection / restaking content, none of
which answers the MEV-tip question. This catalog is the MEV-only
slice: tip floor percentiles, bundle landing mechanics, searcher dev
docs, block-engine telemetry. Staking pages are intentionally
excluded — they live in ``protocol_native.py`` and stay there.

Every endpoint here is free + public, no API key. JSON endpoints
return live tip-floor or recent-block telemetry; HTML/docs endpoints
carry the mechanism prose searchers actually need to reason about
tip strategy.

Carries:
  - provider_kind="protocol_native"
  - protocol=("jito",)
  - metadata.subkind="mev_tip_data"

The subkind tag is the disambiguator at retrieval-debug time: it lets
us tell at a glance whether a Jito chunk is MEV-side (what we wrote
here) or staking-side (what S28-#26 wrote).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class JitoMevEndpoint:
    """One Jito MEV-specific endpoint to fetch + chunk + embed."""

    slug: str
    url: str
    description: str
    content_kind: str = "mechanism"  # mechanism | quote | governance


# --- Live tip-floor / bundle telemetry (quote-kind) -----------------------
# These are the lamport-grounded numbers a searcher needs to make a tip
# decision. content_kind="quote" so the panel knows they're snapshots.

_LIVE_ENDPOINTS: Final[tuple[JitoMevEndpoint, ...]] = (
    JitoMevEndpoint(
        slug="jito-mev-tip-floor-live",
        url="https://bundles.jito.wtf/api/v1/bundles/tip_floor",
        description=(
            "Jito tip-floor percentiles (P25/P50/P75/P95/P99) for bundle "
            "landing — current snapshot. Direct lamport figures that "
            "ground 'P75 vs P90' tip-strategy questions in real data."
        ),
        content_kind="quote",
    ),
    JitoMevEndpoint(
        slug="jito-mev-recent-blocks",
        url="https://kobe.mainnet.jito.network/api/v1/recent_blocks",
        description=(
            "Jito Block Engine recent-block telemetry — slot, leader, "
            "bundle count, total tips per block. Grounds bundle-landing-"
            "rate estimates over recent slots."
        ),
        content_kind="quote",
    ),
    JitoMevEndpoint(
        slug="jito-mev-rewards-snapshot",
        url="https://kobe.mainnet.jito.network/api/v1/mev_rewards",
        description=(
            "Jito MEV rewards summary — recent-epoch MEV totals + "
            "distribution to validators + JitoSOL. Caveat: epoch-level "
            "aggregate, not per-bundle. Use alongside tip_floor for "
            "magnitude calibration."
        ),
        content_kind="quote",
    ),
    JitoMevEndpoint(
        slug="jito-mev-validators-telemetry",
        url="https://kobe.mainnet.jito.network/api/v1/validators",
        description=(
            "Jito validator-set telemetry — per-validator MEV share, "
            "commission, stake size, performance scores. Useful for "
            "reasoning about leader-schedule coverage when sizing tips."
        ),
        content_kind="quote",
    ),
)


# --- MEV / bundle mechanics docs (mechanism-kind) -------------------------
# The docs.jito.wtf surface that explains HOW bundle landing, tip
# distribution, and atomic execution actually work. These pages are the
# substantive ground truth a searcher would cite when defending a tip
# strategy.

_DOCS_ENDPOINTS: Final[tuple[JitoMevEndpoint, ...]] = (
    JitoMevEndpoint(
        slug="jito-mev-docs-low-latency-txn-send",
        url="https://docs.jito.wtf/lowlatencytxnsend/",
        description=(
            "Jito low-latency transaction send — block engine, bundle "
            "submission API (sendBundle, getBundleStatuses, "
            "getInflightBundleStatuses, tip accounts), atomicity "
            "guarantees, MEV protection model, JSON-RPC authentication, "
            "tip percentiles, regional endpoints. The canonical MEV-"
            "bundle-mechanics reference."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-docs-low-latency-txn-feed",
        url="https://docs.jito.wtf/lowlatencytxnfeed/",
        description=(
            "Jito low-latency transaction feed — ShredStream proxy "
            "mechanics, shred receive flow, latency-vs-reliability "
            "tradeoff, integration patterns for MEV searchers."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-docs-root",
        url="https://docs.jito.wtf/",
        description=(
            "Jito Labs docs landing — index across MEV protocol "
            "architecture, block engine, searcher integration."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-searchers-product",
        url="https://www.jito.wtf/searchers/",
        description=(
            "Jito Searchers product page — MEV searcher value "
            "proposition, bundle mechanics, tip economics, integration "
            "paths. Marketing-grade summary of the searcher surface."
        ),
    ),
)


# --- MEV / bundle dev-client READMEs (mechanism-kind) ---------------------
# These are the per-language client READMEs — they document the bundle
# submission patterns and tip-account configuration that map directly to
# tip-strategy code. Excluded jito-solana validator README and Stakenet /
# Restaking READMEs (those are staking-side, already covered by S28-#26).

_CLIENT_ENDPOINTS: Final[tuple[JitoMevEndpoint, ...]] = (
    JitoMevEndpoint(
        slug="jito-mev-protos-readme",
        url="https://raw.githubusercontent.com/jito-labs/mev-protos/master/README.md",
        description=(
            "Jito MEV protos README — gRPC protobuf schemas for "
            "block-engine, searcher, relayer, auction service. The "
            "wire-protocol contract for bundle submission."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-js-rpc-readme",
        url="https://raw.githubusercontent.com/jito-labs/jito-js-rpc/master/README.md",
        description=(
            "Jito JS RPC client README — bundle submission patterns, "
            "tip account configuration, regional endpoint selection "
            "from TypeScript. Searcher-implementation reference."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-py-rpc-readme",
        url="https://raw.githubusercontent.com/jito-labs/jito-py-rpc/master/README.md",
        description=(
            "Jito Python RPC client README — bundle submission "
            "patterns, tip accounts, regional endpoint selection from "
            "Python. Searcher-implementation reference."
        ),
    ),
    JitoMevEndpoint(
        slug="jito-mev-rust-rpc-readme",
        url="https://raw.githubusercontent.com/jito-labs/jito-rust-rpc/master/README.md",
        description=("Jito Rust RPC client README — bundle submission patterns from Rust."),
    ),
    JitoMevEndpoint(
        slug="jito-mev-go-rpc-readme",
        url="https://raw.githubusercontent.com/jito-labs/jito-go-rpc/master/README.md",
        description=("Jito Go RPC client README — bundle submission patterns from Go."),
    ),
)


JITO_MEV_ENDPOINTS: Final[tuple[JitoMevEndpoint, ...]] = (
    *_LIVE_ENDPOINTS,
    *_DOCS_ENDPOINTS,
    *_CLIENT_ENDPOINTS,
)


def render_chunk(ep: JitoMevEndpoint, body_text: str, as_of_iso: str) -> str:
    """Render a fetched body as a substantive prose chunk.

    The chunk header tags the content as Jito MEV-tip data so the panel
    + voices know what bucket of evidence they're holding.
    """
    return (
        f"Protocol-native API: jito / {ep.slug} (subkind=mev_tip_data) "
        f"(as of {as_of_iso}).\n"
        f"Endpoint description: {ep.description}\n"
        f"Source URL: {ep.url}\n"
        f"Content kind: {ep.content_kind}\n"
        f"----- body -----\n"
        f"{body_text}\n"
        f"----- end body -----\n"
        f"Provider: protocol_native (Jito MEV-side, distinct from JitoSOL "
        f"staking content)."
    )


__all__ = [
    "JITO_MEV_ENDPOINTS",
    "JitoMevEndpoint",
    "render_chunk",
]
