"""Pro tier system-prompt loader.

Overview
--------

The 5 system prompts the AG2 GroupChat uses are loaded here, not hardcoded in
``agents.py``. This decouples the prompt content from the orchestration code so
the public OSS repo can ship working defaults while production runs a
privately-tuned set without code changes.

Resolution order:

1. ``GECKO_PROMPTS_PATH`` env var → JSON file at that path. Used in production
   to point at a privately-tuned prompts file (mounted via SSM, downloaded at
   container boot, etc.).
2. The bundled ``_default_prompts.json`` next to this module. Used in dev,
   tests, and the OSS install path. These are the prompts that public users
   get; they're real and tuned, not stubs.

The file format is::

    {
      "version": "v1",
      "agents": {
        "analyst":  "...",
        "critic":   "...",
        "architect":"...",
        "scoper":   "...",
        "judge":    "..."
      }
    }

Schema is enforced at load time — missing keys, empty strings, or wrong types
raise loudly so a bad override fails fast at boot rather than mid-debate.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REQUIRED_AGENTS = ("analyst", "critic", "architect", "scoper", "judge")

# Bundled prompt versions. v5.3 is the current default — Judge-only fix for
# v5.2 STEP 2 keyword-trigger gap (entries matched only by exact dash-cased
# name) and STEP 4 saturation-list softening (kills regressed to ships). See
# docs/prompts/v5_3-changelog.md. v5.2 was a Judge-only structural fix for v5.1
# under-shipping ideas explicitly named in MANDATORY SHIP rules
# (docs/prompts/v5_2-changelog.md). v5.1 was a Judge-only fix for the
# 2026-04-28 verdict_accuracy regression (docs/prompts/v5_1-changelog.md).
# v5 (S2X-11 — adds V1 source guidance for gecko_precedent / hn / reddit /
# twit_sh / colosseum) and v4 are retained on disk as rollback targets — set
# GECKO_PRO_PROMPTS_VERSION=v5.2 (or v5.1, v5, v4) to pin a prior bundle without
# code changes.
_PROMPTS_DIR = Path(__file__).parent
_BUNDLED_VERSIONS: dict[str, Path] = {
    "v4": _PROMPTS_DIR / "_default_prompts.json",
    "v5": _PROMPTS_DIR / "_default_prompts_v5.json",
    "v5.1": _PROMPTS_DIR / "_default_prompts_v5_1.json",
    "v5.2": _PROMPTS_DIR / "_default_prompts_v5_2.json",
    "v5.3": _PROMPTS_DIR / "_default_prompts_v5_3.json",
}
_DEFAULT_VERSION = "v5.3"
_DEFAULT_PROMPTS_PATH = _BUNDLED_VERSIONS[_DEFAULT_VERSION]


class PromptsConfigError(ValueError):
    """Raised when prompts JSON is missing keys, empty, or malformed."""


def _validate(data: dict[str, object]) -> dict[str, str]:
    agents = data.get("agents")
    if not isinstance(agents, dict):
        raise PromptsConfigError("prompts JSON must have a top-level 'agents' object")
    out: dict[str, str] = {}
    for name in REQUIRED_AGENTS:
        val = agents.get(name)
        if not isinstance(val, str) or not val.strip():
            raise PromptsConfigError(
                f"prompts JSON is missing or empty for required agent '{name}'"
            )
        out[name] = val.strip()
    return out


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, str]:
    """Resolve and validate the system prompts.

    Returns a ``{agent_name: system_message}`` dict containing exactly the 5
    required entries. Caches the result so re-imports don't re-parse the file.

    Resolution order:

    1. ``GECKO_PROMPTS_PATH`` (full path override) — wins when set.
    2. ``GECKO_PRO_PROMPTS_VERSION`` (``v4``, ``v5``, ``v5.1``, ``v5.2``, or
       ``v5.3``) — selects which bundled file to load. Default is ``v5.3``
       (Judge keyword-trigger fix: STEP 2 named-example entries now fire on
       idea-text keywords, not exact dash-cased names; STEP 4 saturation kills
       restored as keyword triggers mirroring STEP 2's structure). ``v5.2``,
       ``v5.1``, ``v5``, and ``v4`` are rollback targets.
    3. Bundled default (``v5.3``).
    """
    override = os.environ.get("GECKO_PROMPTS_PATH")
    if override:
        path = Path(override).expanduser()
    else:
        version = os.environ.get("GECKO_PRO_PROMPTS_VERSION", _DEFAULT_VERSION).strip()
        if version not in _BUNDLED_VERSIONS:
            raise PromptsConfigError(
                f"GECKO_PRO_PROMPTS_VERSION={version!r} is not a known bundled version "
                f"(known: {sorted(_BUNDLED_VERSIONS)})"
            )
        path = _BUNDLED_VERSIONS[version]

    if not path.is_file():
        if override:
            raise PromptsConfigError(
                f"GECKO_PROMPTS_PATH={override} does not point to a readable file"
            )
        # The bundled default should always exist; the package would be malformed otherwise.
        raise PromptsConfigError(f"bundled prompts file is missing: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptsConfigError(f"prompts JSON at {path} is not valid JSON: {exc}") from exc

    return _validate(data)


__all__ = ["REQUIRED_AGENTS", "PromptsConfigError", "load_prompts"]
