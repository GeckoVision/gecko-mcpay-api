"""Canonical VoiceName Literal for the 5-agent pro debate.

Per CLAUDE.md Pattern A: every consumer of the voice-name vocabulary
imports from here. The schema-drift test in
``tests/test_voice_name_consistency.py`` asserts this set equals
``REQUIRED_AGENTS`` from ``orchestration.pro.prompts``.

Lives at ``gecko_core.voices`` (top-level) rather than under
``orchestration.pro`` so ``models.py`` can import it without triggering
the orchestration package __init__ — which depends on models — and
producing a circular import.
"""

from __future__ import annotations

from typing import Literal

VoiceName = Literal["analyst", "critic", "architect", "scoper", "judge"]

VoiceStatus = Literal["engaged", "deferred", "silent"]

DissentStatus = Literal["surviving", "no_surviving_dissent"]

__all__ = ["DissentStatus", "VoiceName", "VoiceStatus"]
