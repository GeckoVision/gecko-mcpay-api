"""S2X-04 — flywheel write hook.

Verifies the Pro write-path persists exactly one `gecko_precedent` row with
the right shape (summary, verdict, categories, comparables, embedding).
The supabase store, classifier, summarizer, and embedder are all mocked —
the test exercises the orchestration in `gecko_core.flywheel.write_precedent`
without burning network calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from gecko_core import flywheel


def _judge_turn(content: str) -> dict[str, Any]:
    return {
        "seq": 10,
        "agent": "judge",
        "content": content,
        "ts": 1.0,
        "tokens_in": 0,
        "tokens_out": 0,
    }


def _transcript(
    judge_content: str, extra_turns: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    turns: list[dict[str, Any]] = list(extra_turns or [])
    turns.append(_judge_turn(judge_content))
    return {
        "turns": turns,
        "total_tokens_in": 0,
        "total_tokens_out": 0,
        "budget_halt_reason": None,
    }


@pytest.mark.asyncio
async def test_write_precedent_writes_row_with_correct_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Pro session with a SHIP verdict writes one row matching the spec."""
    session_id = uuid4()

    # Mock classifier — returns a deterministic 2-category set.
    async def fake_classify(idea: str, **kwargs: Any) -> set[str]:
        assert "validator" in idea
        return {"crypto", "devtools"}

    monkeypatch.setattr(flywheel, "classify_idea", fake_classify)

    # Mock summarizer — must NOT contain the verbatim idea, by contract.
    async def fake_summarize(idea: str, cats: list[str], **kwargs: Any) -> str:
        return "Solana validator monitoring tool with slashing alerts"

    monkeypatch.setattr(flywheel, "summarize_idea_for_flywheel", fake_summarize)

    # Mock embedder — return a fixed 1024-dim vector.
    async def fake_embed(texts: list[str], **kwargs: Any) -> tuple[list[list[float]], int]:
        assert len(texts) == 1
        # Embed the SUMMARY, never the raw idea.
        assert texts[0] == "Solana validator monitoring tool with slashing alerts"
        return [[0.1] * 1024], 7

    monkeypatch.setattr(flywheel, "embed", fake_embed)

    # Mock store.append_gecko_precedent — capture call kwargs.
    captured: dict[str, Any] = {}

    async def fake_append(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return uuid4()

    store = MagicMock()
    store.append_gecko_precedent = AsyncMock(side_effect=fake_append)

    judge_content = (
        "TAM: 7\nWEDGE: 8\nV1_FEASIBILITY: 9\n\n"
        "Verdict: SHIP V1 to Solana validator operators running mainnet nodes. "
        "Helius DAS and Stripe-style billing are the obvious comparables."
    )
    transcript = _transcript(judge_content)

    precedent_id = await flywheel.write_precedent(
        session_id=session_id,
        idea="I want a Solana validator monitoring product with slashing alerts",
        transcript=transcript,
        user_id=None,
        store=store,
    )

    assert precedent_id is not None
    store.append_gecko_precedent.assert_awaited_once()
    assert captured["session_id"] == session_id
    assert captured["user_id"] is None
    assert captured["idea_summary"] == "Solana validator monitoring tool with slashing alerts"
    assert captured["verdict"] == "ship"
    assert captured["category_tags"] == ["crypto", "devtools"]  # sorted
    # Comparables extracted from the judge text — Helius is in the allowlist.
    assert any("Helius" in c for c in captured["key_comparables"])
    assert len(captured["embedding"]) == 1024
    # idea_hash is sha256 — opaque but deterministic.
    assert isinstance(captured["idea_hash"], str)
    assert len(captured["idea_hash"]) == 64


@pytest.mark.asyncio
async def test_write_precedent_skips_on_unknown_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the judge text doesn't yield a canonical verdict, skip the write."""
    store = MagicMock()
    store.append_gecko_precedent = AsyncMock()

    transcript = _transcript("the analyst raised some concerns and we deliberated")
    result = await flywheel.write_precedent(
        session_id=uuid4(),
        idea="ambiguous idea",
        transcript=transcript,
        user_id=None,
        store=store,
    )

    assert result is None
    store.append_gecko_precedent.assert_not_called()


@pytest.mark.asyncio
async def test_write_precedent_swallows_store_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Best-effort: a store-level exception must not propagate."""

    async def fake_classify(idea: str, **kwargs: Any) -> set[str]:
        return set()

    async def fake_summarize(idea: str, cats: list[str], **kwargs: Any) -> str:
        return "category summary"

    async def fake_embed(texts: list[str], **kwargs: Any) -> tuple[list[list[float]], int]:
        return [[0.0] * 1024], 1

    monkeypatch.setattr(flywheel, "classify_idea", fake_classify)
    monkeypatch.setattr(flywheel, "summarize_idea_for_flywheel", fake_summarize)
    monkeypatch.setattr(flywheel, "embed", fake_embed)

    store = MagicMock()
    store.append_gecko_precedent = AsyncMock(side_effect=RuntimeError("supabase boom"))

    transcript = _transcript("Verdict: KILL — saturated b2c market")
    # Must NOT raise.
    result = await flywheel.write_precedent(
        session_id=uuid4(),
        idea="another todo app",
        transcript=transcript,
        user_id=None,
        store=store,
    )
    assert result is None


def test_extract_comparables_pulls_named_products() -> None:
    transcript = {
        "turns": [
            {
                "agent": "analyst",
                "content": "The space is owned by Stripe and Plaid; small entrants like Ramp compete.",
            },
            {
                "agent": "architect",
                "content": "Helius DAS gives us NFT context. We can host on Vercel and store on Supabase.",
            },
        ]
    }
    out = flywheel.extract_comparables(transcript)
    # Allowlist single-tokens.
    assert "Stripe" in out
    assert "Plaid" in out
    assert any("Helius" in c for c in out)  # may surface as "Helius" or "Helius DAS"
    assert "Vercel" in out
    assert "Supabase" in out


def test_extract_comparables_empty_when_no_transcript() -> None:
    assert flywheel.extract_comparables(None) == []
    assert flywheel.extract_comparables({}) == []
    assert flywheel.extract_comparables({"turns": "not a list"}) == []
