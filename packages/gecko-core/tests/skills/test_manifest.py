"""pay.sh v1.0 manifest shape invariants (S20-B1)."""

from __future__ import annotations

from gecko_core.skills.manifest import build_manifest

_REQUIRED_TOP_KEYS = {"version", "name", "description", "skills"}
_REQUIRED_SKILL_KEYS = {
    "name",
    "title",
    "description",
    "url",
    "pricing",
    "category",
    "gecko_knowledge_category",
}
_REQUIRED_PRICING_KEYS = {
    "flat_usd",
    "bundled_output_tokens",
    "overage_per_1m_output_usd",
    "currency",
}


def test_manifest_top_level_shape() -> None:
    m = build_manifest()
    assert m.keys() >= _REQUIRED_TOP_KEYS
    assert m["version"] == "1.0"
    assert m["name"] == "Gecko"
    assert isinstance(m["description"], str) and m["description"]
    assert len(m["skills"]) == 12


def test_every_skill_entry_has_required_fields() -> None:
    m = build_manifest()
    for entry in m["skills"]:
        assert entry.keys() >= _REQUIRED_SKILL_KEYS
        assert entry["url"].startswith("https://app.geckovision.tech/skills/")
        pricing = entry["pricing"]
        assert pricing.keys() >= _REQUIRED_PRICING_KEYS
        assert pricing["currency"] == "USD"


def test_pricing_floors_match_bb_pricing() -> None:
    by_name = {entry["name"]: entry for entry in build_manifest()["skills"]}
    assert by_name["research-market"]["pricing"]["flat_usd"] == 0.10
    assert by_name["research-full"]["pricing"]["flat_usd"] == 0.50
    for retrieve_name in (
        "retrieve-market-intelligence",
        "retrieve-business-financial",
        "retrieve-investment-signals",
        "retrieve-product",
        "retrieve-technical-engineering",
        "retrieve-ai-ml",
        "retrieve-design-ux",
    ):
        assert by_name[retrieve_name]["pricing"]["flat_usd"] == 0.01


def test_credit_pack_has_null_overage_in_manifest() -> None:
    by_name = {entry["name"]: entry for entry in build_manifest()["skills"]}
    pack = by_name["credit-pack"]
    assert pack["pricing"]["overage_per_1m_output_usd"] is None
    assert pack["pricing"]["bundled_output_tokens"] == 1_500_000
    assert pack["gecko_knowledge_category"] is None
