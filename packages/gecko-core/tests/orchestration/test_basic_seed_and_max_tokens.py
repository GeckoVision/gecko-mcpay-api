"""LLM-hygiene Commit C regression test.

Asserts the orchestration layer forwards ``seed=42`` and ``max_tokens`` on
JSON-mode chat completions so eval reproducibility + budget caps don't
silently regress. The basic-tier ``_call_llm`` is the canonical site;
covering it here protects the per-call hygiene contract without
re-exercising every other call site.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock


def _build_fake_client(content: str = '{"foo": "bar"}') -> tuple[Any, list[dict[str, Any]]]:
    """Build a fake AsyncOpenAI whose ``chat.completions.with_raw_response.create``
    captures every kwarg it's called with. Returns ``(client, captured)``.
    """
    captured: list[dict[str, Any]] = []

    fake_resp = MagicMock()
    fake_resp.choices = [MagicMock()]
    fake_resp.choices[0].message.content = content
    fake_resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)

    fake_raw = MagicMock()
    fake_raw.parse.return_value = fake_resp
    fake_raw.headers = {}

    async def _create(**kwargs: Any) -> Any:
        captured.append(kwargs)
        return fake_raw

    client = MagicMock()
    client.chat.completions.with_raw_response.create = AsyncMock(side_effect=_create)
    return client, captured


async def test_call_llm_forwards_seed_42_for_reproducibility() -> None:
    """``_call_llm`` must forward ``seed=42`` on every JSON-mode call.

    This guards against accidental drift (e.g. a refactor that drops the
    kwarg). Determinism is best-effort — OpenRouter passes seed per-provider
    and not all providers honor it — but the kwarg must reach the API.
    """
    from gecko_core.orchestration.basic import _call_llm

    client, captured = _build_fake_client()

    await _call_llm(
        client=client,
        model="gpt-4o-mini",
        system="sys",
        user="u",
        temperature=0.3,
    )

    assert len(captured) == 1, "expected exactly one create call"
    kw = captured[0]
    assert kw.get("seed") == 42, f"seed=42 missing or wrong: got {kw.get('seed')!r}"
    # Sanity: response_format is still json_object (didn't regress).
    assert kw.get("response_format") == {"type": "json_object"}


async def test_call_llm_forwards_max_tokens_when_supplied() -> None:
    """``max_tokens`` is opt-in — passes through when callers thread it."""
    from gecko_core.orchestration.basic import _call_llm

    client, captured = _build_fake_client()

    await _call_llm(
        client=client,
        model="gpt-4o-mini",
        system="sys",
        user="u",
        temperature=0.3,
        max_tokens=6000,
    )

    assert captured[0].get("max_tokens") == 6000


async def test_call_llm_omits_max_tokens_when_not_supplied() -> None:
    """When ``max_tokens`` is None, the kwarg is omitted entirely (provider default)."""
    from gecko_core.orchestration.basic import _call_llm

    client, captured = _build_fake_client()

    await _call_llm(
        client=client,
        model="gpt-4o-mini",
        system="sys",
        user="u",
        temperature=0.3,
    )

    assert "max_tokens" not in captured[0], (
        "max_tokens should be omitted when not threaded; provider default applies"
    )


def test_orchestration_settings_exposes_per_role_max_tokens() -> None:
    """Settings expose seven independently tunable per-role caps (C2)."""
    from gecko_core.orchestration.settings import OrchestrationSettings

    s = OrchestrationSettings()  # type: ignore[call-arg]
    # Each role's cap is independently tunable; defaults are non-zero ints.
    for attr in (
        "max_tokens_research_basic",
        "max_tokens_post_processor",
        "max_tokens_refiner",
        "max_tokens_judge_synth",
        "max_tokens_ask",
        "max_tokens_ag2",
        "max_tokens_advisor",
    ):
        v = getattr(s, attr)
        assert isinstance(v, int) and v > 0, f"{attr} default invalid: {v!r}"
