"""Michael Mauboussin / Counterpoint Global papers — investor-canon source.

Public-domain content distributed freely by Morgan Stanley Investment
Management's Counterpoint Global research arm (where Mauboussin is Head
of Consilient Research), plus stable third-party mirrors for the older
Legg Mason / Credit Suisse pieces.

Chunks land with ``provider_kind="canon_mauboussin"`` — grounds
expectation-shape, base-rate, capital-allocation, and skill-vs-luck
reasoning, complementing Marks (cycles), Damodaran (valuation), Berkshire
(capital-allocation cases), and the macro corpus.

URL confidence: the first two (trendfollowing, portfolioconstructionforum)
are HIGH. The morganstanley.com ``article_*.pdf`` slugs follow Counterpoint
Global's real naming convention but are MEDIUM — MS occasionally appends
region suffixes or reorganizes paths. Run ``--dry-run`` first; 404s log as
FAIL and need the slug re-confirmed against the live insights index.

    uv run python scripts/canon/ingest_mauboussin.py --dry-run
"""

from __future__ import annotations

from typing import Final, NamedTuple


class CanonSource(NamedTuple):
    """One curated investor-canon PDF — URL + citation metadata."""

    url: str
    title: str
    year: int
    author: str
    venue: str


_MS_HOST = "https://www.morganstanley.com/im/publication/insights/articles"


MAUBOUSSIN_SOURCES: Final[tuple[CanonSource, ...]] = (
    CanonSource(
        url="https://www.trendfollowing.com/pdfs/UntanglingSkillandLuck.pdf",
        title="Untangling Skill and Luck in Business, Sports, and Investing",
        year=2010,
        author="Michael Mauboussin",
        venue="Legg Mason Capital Management",
    ),
    CanonSource(
        url="https://obj.portfolioconstructionforum.edu.au/articles_perspectives/PortfolioConstruction-Forum_Credit-Suisse_30-years-reflections-on-10-attributes-of-great-investors.pdf",
        title="Thirty Years — Reflections on the Ten Attributes of Great Investors",
        year=2016,
        author="Michael Mauboussin",
        venue="Credit Suisse Global Financial Strategies",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_capitalallocation.pdf",
        title="Capital Allocation: Results, Analysis, and Assessment",
        year=2022,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_measuringthemoat.pdf",
        title="Measuring the Moat: Assessing the Magnitude and Sustainability of Value Creation",
        year=2016,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_returnoninvestedcapital.pdf",
        title="Return on Invested Capital: How to Calculate ROIC and Handle Common Issues",
        year=2022,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_roicandtheinvestmentprocess.pdf",
        title="ROIC and the Investment Process",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_roicandintangibleassets_us.pdf",
        title="ROIC and Intangible Assets",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_probabilitiesandpayoffs.pdf",
        title="Probabilities and Payoffs: The Practicalities and Psychology of Expected Value",
        year=2024,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_confidence.pdf",
        title="Confidence: How Much Should We Believe What We Believe?",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_birthdeathandwealthcreation.pdf",
        title="Birth, Death, and Wealth Creation",
        year=2022,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_totalshareholderreturns.pdf",
        title="Total Shareholder Return: Drivers, Volatility, and Aggregate Operating Profit",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_theimpactofintangiblesonbaserates.pdf",
        title="The Impact of Intangibles on Base Rates",
        year=2021,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_categorizingforclarity.pdf",
        title="Categorizing for Clarity: Cash Flow Statement Adjustments to Better Reflect Economic Reality",
        year=2022,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_tradingstagesinthecompanylifecycle.pdf",
        title="Trading Stages in the Company Life Cycle",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
    CanonSource(
        url=f"{_MS_HOST}/article_marketexpectedreturnoninvestment_en.pdf",
        title="Market-Expected Return on Investment",
        year=2023,
        author="Michael Mauboussin",
        venue="Morgan Stanley Counterpoint Global",
    ),
)
"""15 curated Mauboussin PDFs. Anchors: Untangling Skill and Luck (2010),
Thirty Years/Ten Attributes (2016), Capital Allocation (2022)."""
