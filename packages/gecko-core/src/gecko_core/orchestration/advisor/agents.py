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


def extract_closing_line(role: AgentRole, output_md: str) -> str:
    """Extract the role-specific closing line. Returns the prompt's prefix +
    captured group, or a graceful fallback if the model didn't comply.

    We return the prefix-included form (e.g. 'Strategic priority: ship X')
    rather than just the captured tail because callers typically render
    the line as-is alongside the role label.
    """
    pat = _CLOSING_PATTERNS[role]
    # Search the LAST match (model may have written the prefix once mid-doc
    # as a section header before the real closer). Iterate to keep last.
    last: re.Match[str] | None = None
    for m in pat.finditer(output_md):
        last = m
    if last is None:
        # Fallback: last non-empty line. Better than empty string for the UI.
        nonempty = [ln.strip() for ln in output_md.splitlines() if ln.strip()]
        return nonempty[-1] if nonempty else "(voice produced no closing line)"
    # Reconstruct prefix + captured tail for display continuity.
    prefix = {
        AgentRole.ceo: "Strategic priority:",
        AgentRole.cto: "Critical path:",
        AgentRole.business_manager: "Lever this sprint:",
        AgentRole.product_manager: "Top backlog item:",
        AgentRole.staff_manager: "Sprint plan:",
    }[role]
    return f"{prefix} {last.group(1).strip()}"


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


async def run_voice(
    *,
    role: AgentRole,
    system_prompt: str,
    user_prompt: str,
    tier_preset: Tier,
    client: AsyncOpenAI,
) -> AdvisorVoice:
    """Call one advisor voice. Returns a fully-populated AdvisorVoice.

    Errors are caught and surfaced as an AdvisorVoice with empty output
    and a note in ``closing_line`` — one voice failing should not blow up
    the whole panel (the staff_manager output is still useful even if the
    CEO 5xx'd). Caller can detect failure via empty ``output_md``.
    """
    task = task_for_role(role)
    model_entry = lookup_model(task, tier_preset)

    try:
        raw = await client.chat.completions.with_raw_response.create(
            model=model_entry.id,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
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

    resp = raw.parse()
    content = resp.choices[0].message.content or ""

    prompt_tokens = (
        int(getattr(resp.usage, "prompt_tokens", 0) or 0) if resp.usage else 0
    )
    completion_tokens = (
        int(getattr(resp.usage, "completion_tokens", 0) or 0) if resp.usage else 0
    )

    cost_usd: float | None = None
    header = raw.headers.get("x-clawrouter-cost-usd") if hasattr(raw, "headers") else None
    if header:
        try:
            cost_usd = float(header)
        except ValueError:
            cost_usd = None
    if cost_usd is None:
        cost_usd = _gpt4o_estimate(prompt_tokens, completion_tokens)

    return AdvisorVoice(
        role=role,
        model_used=model_entry.id,
        output_md=content,
        closing_line=extract_closing_line(role, content),
        tokens_in=prompt_tokens,
        tokens_out=completion_tokens,
        cost_usd=cost_usd,
    )


__all__ = ["extract_closing_line", "run_voice"]
