"""S20-DISTRIBUTION-CRITIC-01 — distribution/GTM critic prompt fragment.

Mirrors the structure of ``test_feature_not_product_critic.py``: pure-function
trigger map + prompt-assembly checks, mocked-only (no LLM calls). The fragment
is triggered by a heuristic substring match on idea + ICP, so the test surface
is the keyword set + the agent_specs append.
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.pro.agents import _agent_specs
from gecko_core.orchestration.pro.prompts import (
    DISTRIBUTION_CRITIC_FRAGMENT,
    FEATURE_NOT_PRODUCT_FRAGMENT,
    distribution_critic_fragment_for,
)

# --- pure-function trigger ----------------------------------------------------


def test_b2b_keyword_triggers_fragment() -> None:
    """B2B keyword in the idea string fires the fragment."""
    out = distribution_critic_fragment_for(
        "self-serve API gateway for B2B onboarding", icp="ops teams at SMBs"
    )
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


def test_2sided_hint_triggers_fragment() -> None:
    """A marketplace idea fires via the 2-sided hint set."""
    out = distribution_critic_fragment_for(
        "marketplace for indie hardware sellers", icp="indie hardware buyers"
    )
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


def test_consumer_idea_does_not_trigger() -> None:
    """A purely consumer idea with no B2B / 2-sided language stays clean."""
    out = distribution_critic_fragment_for(
        "personal habit tracker for solo runners", icp="individual runners"
    )
    assert out is None


def test_stress_matrix_3_hotels() -> None:
    """The exact stress-matrix #3 idea — the canonical regression case."""
    out = distribution_critic_fragment_for(
        "a new app for hotels — generate local guides personally built for them",
        icp="boutique hotels in tourist cities",
    )
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


def test_icp_alone_can_trigger() -> None:
    """ICP-side B2B language alone is enough — the idea string may be vague."""
    out = distribution_critic_fragment_for("scheduling tool", icp="enterprise procurement teams")
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


def test_empty_inputs_do_not_trigger() -> None:
    """Empty strings + None inputs are safe — no trigger, no crash."""
    assert distribution_critic_fragment_for("", icp="") is None
    assert distribution_critic_fragment_for("", icp=None) is None
    assert distribution_critic_fragment_for("habit tracker") is None


@pytest.mark.parametrize(
    "phrase",
    [
        "buyer and seller",
        "creator and viewer",
        "host and guest",
        "driver and rider",
        "two-sided network for X",
        "two sided network for X",
    ],
)
def test_all_2sided_role_pairs_trigger(phrase: str) -> None:
    out = distribution_critic_fragment_for(phrase)
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


@pytest.mark.parametrize(
    "phrase",
    [
        "wholesale ordering portal",
        "distributor onboarding",
        "supplier risk scoring",
        "procurement automation",
        "channel sales enablement",
        "insurance claims triage",
        "law firms billing assistant",
        "hospitals scheduling",
    ],
)
def test_named_b2b_verticals_trigger(phrase: str) -> None:
    out = distribution_critic_fragment_for(phrase)
    assert out == DISTRIBUTION_CRITIC_FRAGMENT


@pytest.mark.parametrize(
    "phrase",
    [
        # Cuts from the draft list — these MUST NOT trigger to avoid
        # false-positive overfire on consumer ideas:
        "AI-powered SaaS notes app for students",  # 'saas' was cut
        "personal training API for runners",  # 'api' was cut
        "social platform for indie writers",  # bare 'platform' was cut
        "match the user's preferences with content",  # bare 'match' was cut
        "an agency-driven autonomous agent",  # 'agency' was cut
    ],
)
def test_cut_keywords_do_not_overfire(phrase: str) -> None:
    """The pruned keywords stay pruned — these consumer-ish ideas don't fire."""
    out = distribution_critic_fragment_for(phrase, icp="individual users")
    assert out is None


# --- agent_specs assembly ------------------------------------------------------


def test_agent_specs_appends_distribution_to_critic_only() -> None:
    """When the B2B trigger fires, only the critic gets the suffix."""
    specs = dict(
        _agent_specs(
            idea="marketplace for hotels",
            icp="boutique hotels",
        )
    )
    assert DISTRIBUTION_CRITIC_FRAGMENT in specs["critic"]
    for name in ("analyst", "architect", "scoper", "judge"):
        assert DISTRIBUTION_CRITIC_FRAGMENT not in specs[name], (
            f"distribution fragment leaked into {name}"
        )


def test_agent_specs_no_trigger_no_fragment() -> None:
    specs = dict(_agent_specs(idea="solo habit tracker", icp="runners"))
    for sys_msg in specs.values():
        assert DISTRIBUTION_CRITIC_FRAGMENT not in sys_msg


def test_agent_specs_default_call_omits_distribution() -> None:
    """Backwards-compat: callers that don't pass idea/icp see legacy prompts."""
    specs = dict(_agent_specs())
    for sys_msg in specs.values():
        assert DISTRIBUTION_CRITIC_FRAGMENT not in sys_msg


def test_both_fragments_compose() -> None:
    """When BOTH gates fire, the critic carries both fragments in stable order.

    Stable order is feature-not-product FIRST, distribution SECOND. Locked
    here so a future refactor that flips the order fails loudly.
    """
    specs = dict(
        _agent_specs(
            gap_classification="Partial:UX",
            idea="marketplace for boutique hotels",
            icp="hotel operations teams",
        )
    )
    critic = specs["critic"]
    assert FEATURE_NOT_PRODUCT_FRAGMENT in critic
    assert DISTRIBUTION_CRITIC_FRAGMENT in critic
    # Order check: feature-not-product first, distribution second.
    assert critic.index(FEATURE_NOT_PRODUCT_FRAGMENT) < critic.index(
        DISTRIBUTION_CRITIC_FRAGMENT
    ), "fragment order regressed — feature-not-product must come before distribution"
    # Other voices stay clean.
    for name in ("analyst", "architect", "scoper", "judge"):
        assert FEATURE_NOT_PRODUCT_FRAGMENT not in specs[name]
        assert DISTRIBUTION_CRITIC_FRAGMENT not in specs[name]


def test_agent_specs_deterministic_under_repeated_calls() -> None:
    """Same inputs → same output. Replay determinism."""
    a = _agent_specs(idea="hotels app", icp="boutique hotels")
    b = _agent_specs(idea="hotels app", icp="boutique hotels")
    assert a == b


def test_fragment_text_contains_required_markers() -> None:
    """Soft guardrail: the fragment names the GTM/distribution framing."""
    text = DISTRIBUTION_CRITIC_FRAGMENT.lower()
    assert "distribution" in text
    assert "gtm" in text or "go to market" in text or "moat" in text
    assert "refine" in text


# --- meta: V1 source-id consistency stays green --------------------------------


def test_v1_consistency_still_passes() -> None:
    """The fragments are pure prose with no V1 source-id references.

    Re-runs the canonical V1 source-id consistency tests so a regression in
    this ticket fails here loudly rather than weeks later in eval drift.
    """
    import importlib.util
    from pathlib import Path

    repo_root = Path(__file__).resolve().parents[2]
    consistency_path = (
        repo_root / "packages" / "gecko-core" / "tests" / "test_v1_source_ids_consistency.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_v1_source_ids_consistency_meta", consistency_path
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    mod.test_canonical_v1_source_ids_value()
    mod.test_v1_source_id_literal_matches_runtime_tuple()
    mod.test_v1_block_re_exports_canonical_symbols()
    mod.test_every_prompt_id_reference_is_canonical()
    mod.test_every_canonical_id_appears_in_at_least_one_prompt()
    mod.test_no_blocklisted_typo_in_any_prompt()
    mod.test_v1_block_imports_canonical_module()
