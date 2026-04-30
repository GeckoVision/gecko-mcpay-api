"""Per-voice LLM call for the Advisor Panel (S4-ADVISOR-02).

Each voice runs as ONE chat completion. Voices are independent — the
caller (orchestration shell in ``__init__.py``) gathers them with
``asyncio.gather``. We do NOT use AG2 GroupChat: the panel is parallel
non-conversational advice, not adversarial debate.

Per-voice model selection comes from ``routing.catalog.lookup_model``:
each role's primary task profile (set in ``_ROLE_TO_TASK_MATRIX``) plus
the user's tier preset → curated model. So at ``Tier.balanced`` you get
five different models (Kimi for CEO/CTO planning+coding, DeepSeek V4
Pro for business_manager math, Kimi for product_manager creative,
GPT-4.1 Nano for staff_manager classification).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from openai import AsyncOpenAI

from gecko_core.orchestration.advisor.models import AdvisorVoice
from gecko_core.routing.catalog import (
    AgentRole,
    Tier,
    lookup_model,
    task_for_role,
)

logger = logging.getLogger(__name__)

# Closing-line patterns per role. Each voice prompt enforces a specific
# trailing line; we extract it here so callers can render a one-line
# summary. Anchors are anchored to a line start so prose mentioning
# "strategic priority:" mid-paragraph doesn't false-positive.
_CLOSING_PATTERNS: dict[AgentRole, re.Pattern[str]] = {
    AgentRole.ceo: re.compile(r"(?im)^\s*Strategic priority:\s*(.+?)\s*$"),
    AgentRole.cto: re.compile(r"(?im)^\s*Critical path:\s*(.+?)\s*$"),
    AgentRole.business_manager: re.compile(r"(?im)^\s*Lever this sprint:\s*(.+?)\s*$"),
    AgentRole.product_manager: re.compile(r"(?im)^\s*Top backlog item:\s*(.+?)\s*$"),
    AgentRole.staff_manager: re.compile(r"(?im)^\s*Sprint plan:\s*(.+?)\s*$"),
}


@dataclass(frozen=True)
class VoiceCallResult:
    """Internal: what one ``run_voice`` call returns to the orchestration shell."""

    voice: AdvisorVoice


_ROLE_PREFIX: dict[AgentRole, str] = {
    AgentRole.ceo: "Strategic priority:",
    AgentRole.cto: "Critical path:",
    AgentRole.business_manager: "Lever this sprint:",
    AgentRole.product_manager: "Top backlog item:",
    AgentRole.staff_manager: "Sprint plan:",
}


# S9-ADVISOR-01: strict suffix appended to system prompt on retry. Lists
# every accepted prefix so the model can't claim ambiguity.
_RETRY_SYSTEM_SUFFIX = (
    "\n\nYour previous response did not end with a structured closing line.\n"
    "You MUST end your response with a line starting with EXACTLY one of:\n"
    '- "## Strategic priority:"\n'
    '- "## Critical path:"\n'
    '- "Lever this sprint:"\n'
    '- "## Top backlog item:"\n'
    '- "## Sprint plan:"\n'
    "Output ONLY the final response. The closing line must be the LAST line."
)


def match_closing_line(role: AgentRole, output_md: str) -> str | None:
    """Strict regex match for the role's closing line.

    Returns the prefix-included rendered form, or ``None`` if no compliant
    line is found. This is the primitive used by the detect/retry layer in
    ``run_voice`` (S9-ADVISOR-01) — distinct from ``extract_closing_line``
    which still applies a graceful fallback for legacy callers.
    """
    pat = _CLOSING_PATTERNS[role]
    last: re.Match[str] | None = None
    for m in pat.finditer(output_md):
        last = m
    if last is None:
        return None
    return f"{_ROLE_PREFIX[role]} {last.group(1).strip()}"


def extract_closing_line(role: AgentRole, output_md: str) -> str:
    """Extract the role-specific closing line. Returns the prompt's prefix +
    captured group, or a graceful fallback if the model didn't comply.

    We return the prefix-included form (e.g. 'Strategic priority: ship X')
    rather than just the captured tail because callers typically render
    the line as-is alongside the role label.
    """
    matched = match_closing_line(role, output_md)
    if matched is not None:
        return matched
    # Fallback: last non-empty line. Better than empty string for the UI.
    nonempty = [ln.strip() for ln in output_md.splitlines() if ln.strip()]
    return nonempty[-1] if nonempty else "(voice produced no closing line)"


def _gpt4o_estimate(prompt_tokens: int, completion_tokens: int) -> float:
    """Fallback cost estimate when ClawRouter doesn't surface a header.

    We don't have per-model rate tables here (those live in the catalog),
    and the catalog's ``ModelPricing`` is in USD/1M tokens. A precise
    estimate would walk the catalog; for now a conservative gpt-4o-mini
    rate keeps the surfaced number believable without overstating cost.
    """
    # gpt-4o-mini pricing (USD per 1M tokens) — a reasonable lower bound
    # across the balanced tier. The router header overrides this when present.
    input_rate = 0.15
    output_rate = 0.60
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000


@dataclass(frozen=True)
class _CallOutcome:
    """Internal: one LLM attempt's parsed result + accounting."""

    content: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None


async def _call_once(
    *,
    client: AsyncOpenAI,
    model_id: str,
    system_prompt: str,
    user_prompt: str,
    temperature: float,
) -> _CallOutcome:
    """Single chat-completion call returning parsed accounting.

    Network/upstream exceptions propagate to the caller — ``run_voice``
    catches them at the outer boundary so one bad voice doesn't sink the
    panel.
    """
    raw = await client.chat.completions.with_raw_response.create(
        model=model_id,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=temperature,
    )
    resp = raw.parse()
    content = resp.choices[0].message.content or ""
    prompt_tokens = int(getattr(resp.usage, "prompt_tokens", 0) or 0) if resp.usage else 0
    completion_tokens = int(getattr(resp.usage, "completion_tokens", 0) or 0) if resp.usage else 0

    cost_usd: float | None = None
    header = raw.headers.get("x-clawrouter-cost-usd") if hasattr(raw, "headers") else None
    if header:
        try:
            cost_usd = float(header)
        except ValueError:
            cost_usd = None
    if cost_usd is None:
        cost_usd = _gpt4o_estimate(prompt_tokens, completion_tokens)

    return _CallOutcome(
        content=content,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        cost_usd=cost_usd,
    )


async def run_voice(
    *,
    role: AgentRole,
    system_prompt: str,
    user_prompt: str,
    tier_preset: Tier,
    client: AsyncOpenAI,
) -> AdvisorVoice:
    """Call one advisor voice. Returns a fully-populated AdvisorVoice.

    S9-ADVISOR-01 — three-layer reliability:

    1. **Detect**: after the regex match against ``_CLOSING_PATTERNS``, an
       explicit miss (no match) on non-empty content is treated as a
       structural failure rather than silently emitting the last-line
       fallback.
    2. **Retry once**: re-issue the same prompt with a strict suffix
       (``_RETRY_SYSTEM_SUFFIX``) at lower temperature (0.2) to encourage
       compliance.
    3. **Surface**: if retry also misses, set ``error_kind='no_closing_line'``
       and use a structured closing line so dogfood / monitoring can detect
       quality drift via ``AdvisorPanel.voices_no_closing_line``.

    Network/upstream errors are caught and surfaced as an AdvisorVoice
    with empty output — one voice failing should not blow up the whole
    panel.
    """
    task = task_for_role(role)
    model_entry = lookup_model(task, tier_preset)

    try:
        first = await _call_once(
            client=client,
            model_id=model_entry.id,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.4,
        )
    except Exception as exc:  # pragma: no cover — defensive, network/upstream only
        logger.warning("advisor voice %s failed: %s", role.value, exc)
        return AdvisorVoice(
            role=role,
            model_used=model_entry.id,
            output_md="",
            closing_line=f"(voice {role.value} failed: {exc})",
            tokens_in=0,
            tokens_out=0,
            cost_usd=None,
        )

    matched = match_closing_line(role, first.content)
    if matched is not None:
        return AdvisorVoice(
            role=role,
            model_used=model_entry.id,
            output_md=first.content,
            closing_line=matched,
            tokens_in=first.prompt_tokens,
            tokens_out=first.completion_tokens,
            cost_usd=first.cost_usd,
        )

    # Detect: first call returned no compliant closing line. Retry once
    # with a stricter system suffix at lower temperature.
    logger.info(
        "advisor voice %s: no closing line on first attempt, retrying with strict suffix",
        role.value,
    )
    retry_system_prompt = system_prompt + _RETRY_SYSTEM_SUFFIX
    try:
        second = await _call_once(
            client=client,
            model_id=model_entry.id,
            system_prompt=retry_system_prompt,
            user_prompt=user_prompt,
            temperature=0.2,
        )
    except Exception as exc:  # pragma: no cover — defensive, network/upstream only
        logger.warning("advisor voice %s retry failed: %s", role.value, exc)
        # Treat the retry network failure as a structural no_closing_line
        # rather than a separate kind — caller monitoring is the same.
        return AdvisorVoice(
            role=role,
            model_used=model_entry.id,
            output_md=first.content,
            closing_line="(voice failed: no_closing_line after 2 attempts)",
            tokens_in=first.prompt_tokens,
            tokens_out=first.completion_tokens,
            cost_usd=first.cost_usd,
            error_kind="no_closing_line",
        )

    combined_in = first.prompt_tokens + second.prompt_tokens
    combined_out = first.completion_tokens + second.completion_tokens
    combined_cost: float | None
    if first.cost_usd is None and second.cost_usd is None:
        combined_cost = None
    else:
        combined_cost = (first.cost_usd or 0.0) + (second.cost_usd or 0.0)

    matched_retry = match_closing_line(role, second.content)
    if matched_retry is not None:
        return AdvisorVoice(
            role=role,
            model_used=model_entry.id,
            output_md=second.content,
            closing_line=matched_retry,
            tokens_in=combined_in,
            tokens_out=combined_out,
            cost_usd=combined_cost,
        )

    # Surface: both attempts produced no compliant closing line.
    logger.warning(
        "advisor voice %s: no_closing_line after 2 attempts (model=%s)",
        role.value,
        model_entry.id,
    )
    return AdvisorVoice(
        role=role,
        model_used=model_entry.id,
        output_md=second.content,
        closing_line="(voice failed: no_closing_line after 2 attempts)",
        tokens_in=combined_in,
        tokens_out=combined_out,
        cost_usd=combined_cost,
        error_kind="no_closing_line",
    )


__all__ = ["extract_closing_line", "match_closing_line", "run_voice"]
