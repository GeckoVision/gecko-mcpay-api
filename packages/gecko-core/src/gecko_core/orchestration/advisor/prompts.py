"""Advisor Panel system-prompt loader (S4-ADVISOR-01).

Mirrors ``orchestration/pro/prompts.py``: bundled JSON sidecars beside this
module, overridable via ``GECKO_ADVISOR_PROMPTS_PATH`` for production-tuned
variants and selectable across bundled versions via
``GECKO_ADVISOR_PROMPTS_VERSION``.

File schema::

    {
      "version": "v1",
      "agents": {
        "ceo":              "...",
        "cto":              "...",
        "business_manager": "...",
        "product_manager":  "...",
        "staff_manager":    "..."
      }
    }

Schema is enforced at load time — missing keys, empty strings, or wrong
types raise loudly so a bad override fails fast at boot rather than
mid-panel.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REQUIRED_VOICES = ("ceo", "cto", "business_manager", "product_manager", "staff_manager")

_PROMPTS_DIR = Path(__file__).parent
_BUNDLED_VERSIONS: dict[str, Path] = {
    "v1": _PROMPTS_DIR / "_default_advisor_prompts.json",
}
_DEFAULT_VERSION = "v1"


class AdvisorPromptsConfigError(ValueError):
    """Raised when the advisor prompts JSON is missing keys, empty, or malformed."""


def _validate(data: dict[str, object]) -> dict[str, str]:
    agents = data.get("agents")
    if not isinstance(agents, dict):
        raise AdvisorPromptsConfigError(
            "advisor prompts JSON must have a top-level 'agents' object"
        )
    out: dict[str, str] = {}
    for name in REQUIRED_VOICES:
        val = agents.get(name)
        if not isinstance(val, str) or not val.strip():
            raise AdvisorPromptsConfigError(
                f"advisor prompts JSON is missing or empty for required voice '{name}'"
            )
        out[name] = val.strip()
    return out


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, str]:
    """Resolve and validate the 5 advisor system prompts.

    Resolution order:
      1. ``GECKO_ADVISOR_PROMPTS_PATH`` (full path override) — wins when set.
      2. ``GECKO_ADVISOR_PROMPTS_VERSION`` — selects bundled version.
      3. Bundled default (``v1``).
    """
    override = os.environ.get("GECKO_ADVISOR_PROMPTS_PATH")
    if override:
        path = Path(override).expanduser()
    else:
        version = os.environ.get("GECKO_ADVISOR_PROMPTS_VERSION", _DEFAULT_VERSION).strip()
        if version not in _BUNDLED_VERSIONS:
            raise AdvisorPromptsConfigError(
                f"GECKO_ADVISOR_PROMPTS_VERSION={version!r} is not a known bundled version "
                f"(known: {sorted(_BUNDLED_VERSIONS)})"
            )
        path = _BUNDLED_VERSIONS[version]

    if not path.is_file():
        if override:
            raise AdvisorPromptsConfigError(
                f"GECKO_ADVISOR_PROMPTS_PATH={override} does not point to a readable file"
            )
        raise AdvisorPromptsConfigError(f"bundled advisor prompts file is missing: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdvisorPromptsConfigError(
            f"advisor prompts JSON at {path} is not valid JSON: {exc}"
        ) from exc

    return _validate(data)


__all__ = ["REQUIRED_VOICES", "AdvisorPromptsConfigError", "load_prompts"]
