"""Canonical Skill dataclass + 12-skill registry (S20-B1).

The registry mirrors ``docs/strategy/2026-05-05-agent-skills-manifest-sketch.md``
and is the single source of truth for every paid Gecko endpoint:

* 7 categorized retrieval skills (one per :data:`Category`)
* 3 team-debate skills (market / build / strategy)
* 1 full-pipeline skill
* 1 bulk credit pack

Per Pattern A in CLAUDE.md, every consumer imports ``SKILLS`` from this
module — never redeclare the list. Adding or renaming a skill is a
single-line edit here; the schema-drift test in
``tests/skills/test_registry.py`` enforces the count + name invariant.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from gecko_core.knowledge.taxonomy import Category

SkillCategory = Literal["data", "finance", "ai_ml"]
"""pay.sh API-verb taxonomy bucket. NOT Gecko's knowledge taxonomy —
that is the orthogonal :data:`Skill.gecko_knowledge_category` field."""

DispatchKind = Literal["retrieve", "debate", "pipeline", "credit"]
"""Internal dispatch tag — selects the gecko-core entrypoint the x402
route invokes after a green facilitator verify."""


@dataclass(frozen=True, slots=True)
class Skill:
    """One paid Gecko endpoint as advertised on the manifest.

    ``price_usd`` and ``overage_per_1m_output_usd`` are :class:`Decimal`
    so we never round-trip money through float. Manifest serialization
    converts to JSON-safe primitives at the boundary.
    """

    name: str
    title: str
    description: str
    category: SkillCategory
    gecko_knowledge_category: Category | None
    dispatch_kind: DispatchKind
    price_usd: Decimal
    bundled_output_tokens: int | None
    overage_per_1m_output_usd: Decimal | None
    url_path: str


# ---------------------------------------------------------------------------
# Pricing constants — referenced from multiple skill rows; lifted to keep
# ``bb pricing`` floors and the manifest in lockstep.
# ---------------------------------------------------------------------------

_RETRIEVE_PRICE: Final = Decimal("0.01")
_RETRIEVE_BUNDLED: Final = 50_000
_RETRIEVE_OVERAGE: Final = Decimal("0.50")

_DEBATE_OVERAGE: Final = Decimal("1.00")


SKILLS: Final[tuple[Skill, ...]] = (
    # ---------- 7 categorized retrieval endpoints ----------
    Skill(
        name="retrieve-market-intelligence",
        title="Retrieve market_intelligence chunks",
        description=(
            "Vector search the categorized base for competitive signals, "
            "market sizing, timing, analogous companies."
        ),
        category="data",
        gecko_knowledge_category="market_intelligence",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-market-intelligence",
    ),
    Skill(
        name="retrieve-business-financial",
        title="Retrieve business_financial chunks",
        description="Unit economics, pricing models, GTM patterns, revenue signals.",
        category="finance",
        gecko_knowledge_category="business_financial",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-business-financial",
    ),
    Skill(
        name="retrieve-investment-signals",
        title="Retrieve investment_signals chunks",
        description="What investors look for, funding patterns, due-diligence signals.",
        category="finance",
        gecko_knowledge_category="investment_signals",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-investment-signals",
    ),
    Skill(
        name="retrieve-product",
        title="Retrieve product chunks",
        description="JTBD patterns, prioritization frameworks, PMF signals, user research.",
        category="data",
        gecko_knowledge_category="product",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-product",
    ),
    Skill(
        name="retrieve-technical-engineering",
        title="Retrieve technical_engineering chunks",
        description="Architecture patterns, stack decisions, implementation patterns.",
        category="data",
        gecko_knowledge_category="technical_engineering",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-technical-engineering",
    ),
    Skill(
        name="retrieve-ai-ml",
        title="Retrieve ai_ml chunks",
        description="Agent patterns, model selection, RAG design, eval frameworks.",
        category="ai_ml",
        gecko_knowledge_category="ai_ml",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-ai-ml",
    ),
    Skill(
        name="retrieve-design-ux",
        title="Retrieve design_ux chunks",
        description="Design patterns, UX research, brand positioning.",
        category="data",
        gecko_knowledge_category="design_ux",
        dispatch_kind="retrieve",
        price_usd=_RETRIEVE_PRICE,
        bundled_output_tokens=_RETRIEVE_BUNDLED,
        overage_per_1m_output_usd=_RETRIEVE_OVERAGE,
        url_path="/skills/retrieve-design-ux",
    ),
    # ---------- 3 team-debate endpoints ----------
    Skill(
        name="research-market",
        title="Run Market Research debate",
        description=(
            "Investor + Business Manager agents debate the market case for an idea. "
            "Returns KILL / REFINE / BUILD verdict with cited evidence."
        ),
        category="data",
        gecko_knowledge_category="market_intelligence",
        dispatch_kind="debate",
        price_usd=Decimal("0.10"),
        bundled_output_tokens=100_000,
        overage_per_1m_output_usd=_DEBATE_OVERAGE,
        url_path="/skills/research-market",
    ),
    Skill(
        name="build-product",
        title="Run Product Building debate",
        description=(
            "PM + Designer + Software Engineer + AI Engineer agents debate what to "
            "build, in what order, and how it should feel. Returns build plan + "
            "implementation signals."
        ),
        category="data",
        gecko_knowledge_category="product",
        dispatch_kind="debate",
        price_usd=Decimal("0.25"),
        bundled_output_tokens=200_000,
        overage_per_1m_output_usd=_DEBATE_OVERAGE,
        url_path="/skills/build-product",
    ),
    Skill(
        name="strategy-architecture",
        title="Run Architecture & Strategy debate",
        description=(
            "CTO + Staff Engineer agents debate whether this is the right system to "
            "build, and the right way to build it. Returns architecture verdict + "
            "6-month risk flags."
        ),
        category="data",
        gecko_knowledge_category="technical_engineering",
        dispatch_kind="debate",
        price_usd=Decimal("0.15"),
        bundled_output_tokens=100_000,
        overage_per_1m_output_usd=_DEBATE_OVERAGE,
        url_path="/skills/strategy-architecture",
    ),
    # ---------- 1 full-pipeline endpoint ----------
    Skill(
        name="research-full",
        title="Run all 3 teams (Market + Product + Architecture)",
        description=(
            "Full Gecko pipeline: classify, retrieve, three-team debate, "
            "synthesized verdict. Output enriches the base for the matched category."
        ),
        category="data",
        gecko_knowledge_category="market_intelligence",
        dispatch_kind="pipeline",
        price_usd=Decimal("0.50"),
        bundled_output_tokens=500_000,
        overage_per_1m_output_usd=Decimal("1.00"),
        url_path="/skills/research-full",
    ),
    # ---------- 1 bulk credit ----------
    Skill(
        name="credit-pack",
        title="Buy bulk Gecko credits ($10 = 1.5M output tokens)",
        description=(
            "Prepay credit pack consumable on any Gecko skill. Best blended margin "
            "for high-volume agent users."
        ),
        category="data",
        gecko_knowledge_category=None,
        dispatch_kind="credit",
        price_usd=Decimal("10.00"),
        bundled_output_tokens=1_500_000,
        overage_per_1m_output_usd=None,
        url_path="/skills/credit-pack",
    ),
)


_BY_NAME: Final[dict[str, Skill]] = {s.name: s for s in SKILLS}


def get_skill(name: str) -> Skill:
    """Return the :class:`Skill` registered under ``name``.

    Raises :class:`KeyError` on miss — callers that want a soft lookup
    should catch and fall back themselves.
    """
    try:
        return _BY_NAME[name]
    except KeyError as exc:
        raise KeyError(f"Unknown skill: {name!r}") from exc


__all__ = [
    "SKILLS",
    "DispatchKind",
    "Skill",
    "SkillCategory",
    "get_skill",
]
