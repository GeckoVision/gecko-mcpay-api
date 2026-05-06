"""Registry invariants for the 12-skill agent-skills manifest (S20-B1)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from gecko_core.knowledge.taxonomy import CATEGORIES
from gecko_core.skills.registry import SKILLS, Skill, get_skill

_EXPECTED_NAMES = frozenset(
    {
        # 7 retrieval
        "retrieve-market-intelligence",
        "retrieve-business-financial",
        "retrieve-investment-signals",
        "retrieve-product",
        "retrieve-technical-engineering",
        "retrieve-ai-ml",
        "retrieve-design-ux",
        # 3 team-debate
        "research-market",
        "build-product",
        "strategy-architecture",
        # 1 full pipeline
        "research-full",
        # 1 bulk credit
        "credit-pack",
    }
)


def test_all_twelve_skills_present() -> None:
    assert len(SKILLS) == 12
    assert {s.name for s in SKILLS} == _EXPECTED_NAMES


def test_skill_names_appear_in_source_file() -> None:
    """Schema-drift guard: source must literally contain every name."""
    src = Path(__file__).resolve().parents[2] / "src" / "gecko_core" / "skills" / "registry.py"
    text = src.read_text(encoding="utf-8")
    for name in _EXPECTED_NAMES:
        assert name in text, f"Skill {name!r} missing from registry.py source"


def test_get_skill_hit_and_miss() -> None:
    skill = get_skill("retrieve-market-intelligence")
    assert isinstance(skill, Skill)
    assert skill.name == "retrieve-market-intelligence"
    assert skill.gecko_knowledge_category == "market_intelligence"

    with pytest.raises(KeyError):
        get_skill("not-a-real-skill")


def test_retrieval_skills_share_invariants() -> None:
    retrieval = [s for s in SKILLS if s.name.startswith("retrieve-")]
    assert len(retrieval) == 7
    for s in retrieval:
        assert s.dispatch_kind == "retrieve"
        assert s.price_usd == Decimal("0.01")
        assert s.bundled_output_tokens == 50_000
        assert s.overage_per_1m_output_usd == Decimal("0.50")
        assert s.gecko_knowledge_category in CATEGORIES


def test_credit_pack_shape() -> None:
    pack = get_skill("credit-pack")
    assert pack.gecko_knowledge_category is None
    assert pack.overage_per_1m_output_usd is None
    assert pack.bundled_output_tokens == 1_500_000
    assert pack.price_usd == Decimal("10.00")
    assert pack.dispatch_kind == "credit"


def test_skill_dataclass_is_frozen() -> None:
    s = get_skill("research-market")
    with pytest.raises(Exception):  # FrozenInstanceError subclasses AttributeError/Exception
        s.price_usd = Decimal("9.99")  # type: ignore[misc]
