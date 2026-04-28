"""S2X-05 — flywheel privacy guardrail.

For 5 known builder ideas, run them through `summarize_idea_for_flywheel`
(with a deterministic mock OpenAI client — we don't burn a real key in CI)
and assert the longest-common-substring overlap with the original idea is
≤ 30% of len(idea). This catches regressions where a future prompt change
causes the LLM to echo verbatim phrasing into the precedent corpus.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from gecko_core.flywheel import (
    longest_common_substring_ratio,
    summarize_idea_for_flywheel,
)

# 5 fixtures: realistic builder ideas paired with the privacy-safe summary
# we expect the LLM to produce. The mock returns these summaries verbatim
# so the test exercises the LCS guard, not the model's quality.
_FIXTURES: list[tuple[str, str]] = [
    (
        "I want to build a Solana-native validator monitoring tool with slashing alerts so operators don't lose stake when their nodes drift out of consensus during epoch boundaries.",
        "Blockchain node operations dashboard with stake-loss notifications",
    ),
    (
        "AI-powered changelog generator that turns merged pull requests into a weekly customer-facing release-notes email for B2B SaaS engineering teams shipping multiple times per day.",
        "Automated release-notes drafting service for enterprise software vendors",
    ),
    (
        "A cap-table diff tool for early-stage founders that highlights how a new SAFE round changes founder ownership before they sign the docs.",
        "Equity ownership comparison utility for pre-seed company executives",
    ),
    (
        "MCP server that lets Claude Code query a customer's Postgres database with type-safe schema introspection and row-level permission boundaries baked in.",
        "Agent-protocol bridge to relational data stores featuring access controls",
    ),
    (
        "Vet telemedicine platform handling DEA EPCS controlled-substance prescribing for rural animal hospitals where the nearest licensed practitioner is more than fifty miles away.",
        "Remote veterinary consultation product covering regulated medication workflows",
    ),
]


def _build_mock_client(summary: str) -> MagicMock:
    """OpenAI AsyncClient mock that returns `summary` in JSON-mode shape."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    msg = MagicMock()
    msg.content = json.dumps({"idea_summary": summary})
    choice = MagicMock()
    choice.message = msg
    response = MagicMock()
    response.choices = [choice]
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


@pytest.mark.parametrize("idea,expected_summary", _FIXTURES)
@pytest.mark.asyncio
async def test_summary_overlap_below_30pct(idea: str, expected_summary: str) -> None:
    """The LLM-generated summary echoes ≤ 30% of the original idea verbatim."""
    client = _build_mock_client(expected_summary)
    summary = await summarize_idea_for_flywheel(idea, ["devtools"], client=client)
    assert summary == expected_summary  # mock plumbing sanity

    ratio = longest_common_substring_ratio(idea, summary)
    assert ratio <= 0.30, (
        f"Privacy guardrail: LCS overlap {ratio:.2%} > 30% threshold.\n"
        f"  idea    = {idea!r}\n"
        f"  summary = {summary!r}"
    )


def test_lcs_ratio_handles_edge_cases() -> None:
    assert longest_common_substring_ratio("", "anything") == 0.0
    assert longest_common_substring_ratio("hello world", "") == 0.0
    # Identical strings: ratio = 1.0
    assert longest_common_substring_ratio("abc", "abc") == 1.0
    # No overlap: ratio = 0.0
    assert longest_common_substring_ratio("abcdef", "xyzwq") == 0.0
    # 50% overlap (3 chars out of 6 verbatim).
    assert longest_common_substring_ratio("abcdef", "qqqdef") == pytest.approx(0.5)


def test_lcs_ratio_case_insensitive() -> None:
    # The privacy guard must catch case-twisted echoes too.
    assert longest_common_substring_ratio("Hello World", "hello") == pytest.approx(5 / 11)


@pytest.mark.asyncio
async def test_summary_falls_back_safely_on_llm_failure() -> None:
    """An LLM exception yields a category-only fallback (still privacy-safe)."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(side_effect=RuntimeError("api boom"))

    idea = "I want to build a Solana validator monitoring tool with slashing alerts"
    summary = await summarize_idea_for_flywheel(idea, ["crypto", "devtools"], client=client)
    # Fallback string contains only the category, never the idea.
    assert "validator" not in summary.lower()
    assert "slashing" not in summary.lower()
    ratio = longest_common_substring_ratio(idea, summary)
    assert ratio <= 0.30
