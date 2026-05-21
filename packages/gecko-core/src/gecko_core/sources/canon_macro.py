"""Macro working papers (Fed / BIS / IMF) — investor-canon source.

Public-domain content distributed freely by the Federal Reserve System,
the Bank for International Settlements, and the International Monetary
Fund. All PDFs are hosted on the institutions' own domains; none paywalled.

Chunks land with ``provider_kind="canon_macro"`` — grounds rate-environment,
liquidity, stablecoin-regulatory, and capital-flow reasoning. Complements
the firm/security-level investor sources (Marks, Mauboussin, Damodaran,
Berkshire).

URL confidence: BIS (bis.org/publ/...) HIGH. NY Fed + Fed Board FEDS
MEDIUM-HIGH (real path conventions; confirm slugs on dry-run). IMF MEDIUM
(the -print-pdf vs -source-pdf suffix varies); the 2026 IMF WP/26/74 is
forward-dated — verify it exists. Run ``--dry-run`` first.

    uv run python scripts/canon/ingest_macro.py --dry-run
"""

from __future__ import annotations

from typing import Final, NamedTuple


class CanonSource(NamedTuple):
    """One curated macro working-paper PDF — URL + citation metadata."""

    url: str
    title: str
    year: int
    author: str
    venue: str


MACRO_SOURCES: Final[tuple[CanonSource, ...]] = (
    # ---------- Federal Reserve ----------
    CanonSource(
        url="https://www.newyorkfed.org/medialibrary/media/research/epr/2024/EPR_2024_digital-assets_azar.pdf",
        title="The Financial Stability Implications of Digital Assets",
        year=2024,
        author="Pablo D. Azar et al.",
        venue="Federal Reserve Bank of New York Economic Policy Review",
    ),
    CanonSource(
        url="https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1073.pdf",
        title="Runs and Flights to Safety: Are Stablecoins the New Money Market Funds?",
        year=2023,
        author="Kenechukwu Anadu et al.",
        venue="Federal Reserve Bank of New York Staff Reports No. 1073",
    ),
    CanonSource(
        url="https://www.federalreserve.gov/econres/feds/files/2024011r1pap.pdf",
        title="Monetary Policy Shocks: Data or Methods?",
        year=2024,
        author="Connor M. Brennan et al.",
        venue="Federal Reserve FEDS Working Paper 2024-011",
    ),
    CanonSource(
        url="https://www.federalreserve.gov/econres/feds/files/2024050pap.pdf",
        title="(Re-)Connecting Inflation and the Labor Market: A Tale of Two Curves",
        year=2024,
        author="Federal Reserve Board staff",
        venue="Federal Reserve FEDS Working Paper 2024-050",
    ),
    CanonSource(
        url="https://www.federalreserve.gov/econres/feds/files/2025071pap.pdf",
        title="Pandemic and War Inflation: Lessons from the International Experience",
        year=2025,
        author="Federal Reserve Board staff",
        venue="Federal Reserve FEDS Working Paper 2025-071",
    ),
    # ---------- BIS ----------
    CanonSource(
        url="https://www.bis.org/publ/work1270.pdf",
        title="Stablecoins and Safe Asset Prices",
        year=2024,
        author="Rashad Ahmed, Iñaki Aldasoro",
        venue="BIS Working Papers No. 1270",
    ),
    CanonSource(
        url="https://www.bis.org/publ/work1164.pdf",
        title="Public Information and Stablecoin Runs",
        year=2024,
        author="Yu Zhu et al.",
        venue="BIS Working Papers No. 1164",
    ),
    CanonSource(
        url="https://www.bis.org/publ/bisbull108.pdf",
        title="Stablecoin Growth — Policy Challenges and Approaches",
        year=2024,
        author="Iñaki Aldasoro et al.",
        venue="BIS Bulletin No. 108",
    ),
    CanonSource(
        url="https://www.bis.org/publ/qtrpdf/r_qt2412.pdf",
        title="BIS Quarterly Review, December 2024",
        year=2024,
        author="BIS Monetary and Economic Department",
        venue="BIS Quarterly Review",
    ),
    # ---------- IMF ----------
    CanonSource(
        url="https://www.imf.org/-/media/files/publications/wp/2024/english/wpiea2024133-print-pdf.pdf",
        title="Crypto as a Marketplace for Capital Flight",
        year=2024,
        author="Marcello Estevão et al.",
        venue="IMF Working Paper WP/24/133",
    ),
    CanonSource(
        url="https://www.imf.org/-/media/files/publications/wp/2025/english/wpiea2025141-source-pdf.pdf",
        title="Decrypting Crypto: How to Estimate International Stablecoin Flows",
        year=2025,
        author="IMF Statistics Department staff",
        venue="IMF Working Paper WP/25/141",
    ),
    CanonSource(
        url="https://www.imf.org/-/media/files/publications/dp/2025/english/usea.pdf",
        title="Understanding Stablecoins",
        year=2025,
        author="IMF Monetary and Capital Markets Department",
        venue="IMF Departmental / Discussion Paper",
    ),
    CanonSource(
        url="https://www.imf.org/-/media/files/publications/wp/2026/english/wpiea2026074-source-pdf.pdf",
        title="Making Stablecoins Stable",
        year=2026,
        author="IMF Monetary and Capital Markets Department",
        venue="IMF Working Paper WP/26/74",
    ),
)
"""13 curated macro PDFs. Anchors: NY Fed EPR digital-assets (2024),
BIS WP 1270 stablecoins/safe-assets (2024), IMF WP 24/133 capital-flight (2024)."""
