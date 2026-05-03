"""Pattern A drift guard — VoiceName Literal must equal REQUIRED_AGENTS.

Modeled on tests/test_payment_mode_consistency.py. Adding/removing a voice
requires touching exactly one Literal (orchestration.pro.voices) AND the
REQUIRED_AGENTS tuple in prompts.py — this test fails loudly if they drift.
"""

from __future__ import annotations

from typing import get_args

from gecko_core.orchestration.pro.prompts import REQUIRED_AGENTS
from gecko_core.orchestration.pro.transcript import AgentName
from gecko_core.voices import VoiceName


def test_voice_name_matches_required_agents() -> None:
    assert set(get_args(VoiceName)) == set(REQUIRED_AGENTS), (
        "VoiceName Literal drifted from REQUIRED_AGENTS. Update both together; "
        "voices.py is the canonical Literal per CLAUDE.md Pattern A."
    )


def test_agent_name_matches_voice_name() -> None:
    """transcript.AgentName predates voices.py; keep them in lockstep until
    AgentName is migrated to import from voices.py directly."""
    assert set(get_args(AgentName)) == set(get_args(VoiceName))
