"""S24-X (2026-05-31) — Per-voice model env-resolution helper.

Shared resolver so the bot can A/B different OpenRouter models per
voice without changing voice code. ALL voices default to
``openai/gpt-4o-mini`` (the value historically hard-coded in each
voice's ``DEFAULT_MODEL`` constant) unless an env override is set.

Precedence (most specific wins):
  1. ``GECKO_<VOICE_NAME>_MODEL`` — per-voice override.
     Example envs (canonical voice_name in upper-snake case):
       GECKO_CHART_ANALYST_MODEL=anthropic/claude-haiku-4-5
       GECKO_MEMORY_VOICE_MODEL=deepseek/deepseek-chat
       GECKO_RISK_VOICE_MODEL=openai/gpt-4o-mini
       GECKO_STRATEGIST_VOICE_MODEL=anthropic/claude-haiku-4-5
  2. ``GECKO_VOICE_MODEL`` — panel-wide override (all 4 LLM voices).
     Useful for cost-controlled A/B tests where you want all voices
     on a single alt model.
  3. ``fallback`` argument — what the caller passes (per-voice
     ``DEFAULT_MODEL``). Hard-codes ``openai/gpt-4o-mini`` today.

Caller-passed ``model=`` kwarg on the voice constructor SHORT-CIRCUITS
all env resolution (tests + advanced callers retain full control).
"""

from __future__ import annotations

import os
from typing import Final

#: Universal default. Mirrors the historical per-voice DEFAULT_MODEL.
#: Changing this here changes every voice's fallback in one place.
DEFAULT_MODEL: Final[str] = "openai/gpt-4o-mini"


def resolve_voice_model(voice_name: str, fallback: str = DEFAULT_MODEL) -> str:
    """Return the OpenRouter model for ``voice_name``.

    ``voice_name`` is the canonical name used by the voice's
    ``VoiceOpinion.voice_name`` field (e.g. ``"chart_analyst"``). The
    env-var name is derived: ``GECKO_<voice_name.upper()>_MODEL``.

    Returns the first non-empty value from the precedence chain above.
    Strips whitespace; treats empty-string env as unset.
    """
    if not voice_name:
        return fallback
    specific_env = f"GECKO_{voice_name.upper()}_MODEL"
    specific = (os.environ.get(specific_env) or "").strip()
    if specific:
        return specific
    panel_wide = (os.environ.get("GECKO_VOICE_MODEL") or "").strip()
    if panel_wide:
        return panel_wide
    return fallback


__all__ = ["DEFAULT_MODEL", "resolve_voice_model"]
