"""Aswath Damodaran / NYU Stern papers — investor-canon source.

Public domain (free academic distribution from Damodaran's NYU faculty
page). Papers span the canonical valuation toolkit: equity risk premium,
discount rates, country risk, distress, intangibles, multiples, beta,
growth, control, synergy, and probabilistic risk approaches.

Chunks land with ``provider_kind="canon_damodaran"`` — the trade-coach
can ground valuation-shape decisions in Damodaran's frameworks while
Marks grounds cycle/risk decisions and Buffett grounds capital-allocation.

Design notes:
  - URL list is curated from
    https://pages.stern.nyu.edu/~adamodar/New_Home_Page/papers.html
    snapshot 2026-05-11.
  - All entries are PDFs; the ingester uses ``gecko_core.sources.pdf.extract``.

How to invoke:
    uv run python scripts/canon/ingest_damodaran.py
"""

from __future__ import annotations

from dataclasses import dataclass

DAMODARAN_PAPERS: tuple[str, ...] = (
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/ERP2011.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/ERP2012.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/nothingisriskfree.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/unstableriskpremiums.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/liquiditynotnorm.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/ERP2009.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/commodity.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/younggrowth.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/NewDistress.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/emergmkts.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/intangibles.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/octopus.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/newlease.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/riskfreerate.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/ERPfull.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/equityclaims.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/growthorigins.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/returnmeasures.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/valuesurvey.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/probabilistic.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/VAR.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/hedging.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/strategicrisk.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/liquidity.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/cashvaluation.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/controlvalue.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/esops.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/synergy.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/riskvalue.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/CountryRisk.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/divtaxes.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/Transparency.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/distresspaper.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/HighGrow.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/realopt.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/pvtfirmval.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/acquisitions.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/multiples.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/beta.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/oplev.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/R&D.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/fininnov.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/beydiv.pdf",
    "https://www.stern.nyu.edu/~adamodar/pdfiles/papers/valcre.pdf",
)


@dataclass(frozen=True)
class DamodaranPaper:
    """One Damodaran paper — URL + slug."""

    url: str

    @property
    def slug(self) -> str:
        """Filename without extension — citation key for the chunk."""
        return self.url.rsplit("/", 1)[-1].replace(".pdf", "")


def paper_urls() -> list[DamodaranPaper]:
    """Return the full curated paper list, ready to fetch."""
    return [DamodaranPaper(url=u) for u in DAMODARAN_PAPERS]
