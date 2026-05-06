"""Tests for `gecko_core.routing.classifier` (S20-C-CLASSIFIER-01).

We never call OpenAI. The ``AsyncOpenAI`` client is replaced with a
fake whose ``chat.completions.create`` returns canned JSON. Pattern C
(recorded-fixture contract): the gold-fixture test pins behaviour
against a stubbed model so prompt drift cannot regress the contract
silently.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gecko_core.knowledge.taxonomy import CATEGORIES, VERTICALS
from gecko_core.routing import classifier as classifier_mod
from gecko_core.routing.classifier import (
    ClassifierParseError,
    QueryClassification,
    classify_query,
)

GOLD_FIXTURE = Path(__file__).parent / "fixtures" / "classifier_gold.jsonl"


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens = prompt_tokens
        self.completion_tokens = completion_tokens


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str, t_in: int = 150, t_out: int = 50) -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(t_in, t_out)


class _FakeCompletions:
    def __init__(self, content: str, t_in: int = 150, t_out: int = 50) -> None:
        self._content = content
        self._t_in = t_in
        self._t_out = t_out
        self.last_kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _FakeCompletion:
        self.last_kwargs = kwargs
        return _FakeCompletion(self._content, self._t_in, self._t_out)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeClient:
    def __init__(self, content: str, t_in: int = 150, t_out: int = 50) -> None:
        self.completions = _FakeCompletions(content, t_in, t_out)
        self.chat = _FakeChat(self.completions)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_known_query_returns_high_confidence_neobank() -> None:
    payload = {
        "categories": ["business_financial", "technical_engineering"],
        "vertical": "neobank",
        "category_confidence": 0.92,
        "vertical_confidence": 0.95,
    }
    client = _FakeClient(json.dumps(payload))

    result = await classify_query(
        "I want to build a neobank in São Paulo with PIX rails",
        client=client,  # type: ignore[arg-type]
    )

    assert isinstance(result, QueryClassification)
    assert result.vertical == "neobank"
    assert "business_financial" in result.categories
    assert result.category_confidence >= 0.7
    assert result.vertical_confidence >= 0.7


async def test_low_vertical_confidence_forces_unknown() -> None:
    """Below threshold (0.6) → vertical replaced with ``unknown``."""
    payload = {
        "categories": ["ai_ml", "technical_engineering"],
        "vertical": "ai_agent_platform",
        "category_confidence": 0.9,
        "vertical_confidence": 0.4,  # below threshold
    }
    client = _FakeClient(json.dumps(payload))

    result = await classify_query(
        "tell me about token economics",
        client=client,  # type: ignore[arg-type]
    )
    assert result.vertical == "unknown"
    # Confidence value preserved — caller decides whether to surface candidates.
    assert result.vertical_confidence == pytest.approx(0.4)


async def test_high_confidence_keeps_predicted_vertical() -> None:
    """At/above threshold (0.6) → vertical is preserved."""
    payload = {
        "categories": ["ai_ml"],
        "vertical": "ai_agent_platform",
        "category_confidence": 0.8,
        "vertical_confidence": 0.6,  # exactly at threshold
    }
    client = _FakeClient(json.dumps(payload))
    result = await classify_query(
        "build an agent platform",
        client=client,  # type: ignore[arg-type]
    )
    assert result.vertical == "ai_agent_platform"


async def test_malformed_json_raises_parse_error() -> None:
    client = _FakeClient("not actually json {{{")
    with pytest.raises(ClassifierParseError) as exc_info:
        await classify_query("anything", client=client)  # type: ignore[arg-type]
    assert "{{{" in exc_info.value.raw_output


async def test_invalid_shape_raises_parse_error() -> None:
    """Valid JSON, wrong shape — pydantic ValidationError → ClassifierParseError."""
    bad = json.dumps({"categories": [], "vertical": "neobank"})  # missing fields, empty list
    client = _FakeClient(bad)
    with pytest.raises(ClassifierParseError):
        await classify_query("anything", client=client)  # type: ignore[arg-type]


async def test_empty_query_raises_before_llm_call() -> None:
    client = _FakeClient(json.dumps({}))
    with pytest.raises(ValueError, match="non-empty"):
        await classify_query("   ", client=client)  # type: ignore[arg-type]
    # Crucially: no spend.
    assert client.completions.last_kwargs is None


async def test_prompt_mentions_all_categories_and_verticals() -> None:
    """Schema-drift guard — every Category and Vertical must appear in the prompt."""
    payload = {
        "categories": ["product"],
        "vertical": "unknown",
        "category_confidence": 0.7,
        "vertical_confidence": 0.7,
    }
    client = _FakeClient(json.dumps(payload))
    await classify_query("hello world", client=client)  # type: ignore[arg-type]

    sent = client.completions.last_kwargs
    assert sent is not None
    user_msg = sent["messages"][0]["content"]
    for cat in CATEGORIES:
        assert cat in user_msg, f"Category {cat!r} missing from prompt"
    for vert in VERTICALS:
        assert vert in user_msg, f"Vertical {vert!r} missing from prompt"
    # Determinism + cost guards live in the call args.
    assert sent["model"] == "gpt-4o-mini"
    assert sent["temperature"] == 0.0
    assert sent["response_format"] == {"type": "json_object"}
    assert sent["max_tokens"] == 300


async def test_gold_fixture_contract() -> None:
    """Pin behaviour against the seed gold set (Pattern C)."""
    assert GOLD_FIXTURE.exists(), f"missing gold fixture: {GOLD_FIXTURE}"
    rows = [json.loads(line) for line in GOLD_FIXTURE.read_text().splitlines() if line.strip()]
    assert len(rows) >= 12

    for row in rows:
        canned = {
            "categories": row["expected_categories"],
            "vertical": row["expected_vertical"],
            "category_confidence": 0.9,
            # If the fixture's expected vertical is ``unknown``, the LLM
            # would return low confidence; mimic that to exercise the
            # threshold path end-to-end.
            "vertical_confidence": 0.3 if row["expected_vertical"] == "unknown" else 0.9,
        }
        client = _FakeClient(json.dumps(canned))
        result = await classify_query(row["query"], client=client)  # type: ignore[arg-type]
        assert result.vertical == row["expected_vertical"], row["query"]
        # Top-1 category preserved.
        assert result.categories[0] == row["expected_categories"][0], row["query"]


async def test_long_query_is_truncated() -> None:
    payload = {
        "categories": ["product"],
        "vertical": "unknown",
        "category_confidence": 0.8,
        "vertical_confidence": 0.7,
    }
    client = _FakeClient(json.dumps(payload))
    huge = "x" * 50_000
    await classify_query(huge, client=client)  # type: ignore[arg-type]
    sent = client.completions.last_kwargs
    assert sent is not None
    # The prompt embeds the truncated query — total prompt should fit
    # comfortably below the 50K input chars we sent in.
    assert len(sent["messages"][0]["content"]) < 10_000


async def test_budget_assert_flag_trips_on_overspend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "categories": ["product"],
        "vertical": "unknown",
        "category_confidence": 0.8,
        "vertical_confidence": 0.7,
    }
    client = _FakeClient(json.dumps(payload), t_in=900, t_out=200)
    monkeypatch.setattr(classifier_mod, "_DEBUG_BUDGET_ASSERT", True)
    with pytest.raises(AssertionError, match="budget exceeded"):
        await classify_query("x", client=client)  # type: ignore[arg-type]
