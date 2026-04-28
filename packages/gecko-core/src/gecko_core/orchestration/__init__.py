"""Orchestration — the LLM tier(s) that turn indexed chunks into documents.

`basic` is a single GPT-4o-mini call. `pro` (AutoGen GroupChat) ships in
Phase 6.
"""

from gecko_core.orchestration.basic import OrchestrationError
from gecko_core.orchestration.basic import generate as basic_generate

__all__ = ["OrchestrationError", "basic_generate"]
