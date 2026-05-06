"""Canonical skill registry + pay.sh v1.0 manifest builder (S20-B1).

Public surface for the agent-skills manifest published at
``app.geckovision.tech/.well-known/agent-skills/index.json``. The
registry is the single source of truth consumed by the manifest
endpoint (B2), the per-skill x402 dispatcher (B3-B5), and the MCP
``serve`` tool registration.
"""

from __future__ import annotations

from gecko_core.skills.manifest import build_manifest
from gecko_core.skills.registry import SKILLS, Skill, get_skill

__all__ = ["SKILLS", "Skill", "build_manifest", "get_skill"]
