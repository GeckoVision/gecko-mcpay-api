"""Synthesizer system-prompt loader for the scaffold stage.

Mirrors the Pro tier's prompts.py contract: bundled JSON beside this module,
overridable via `GECKO_SCAFFOLD_PROMPTS_PATH` for production-tuned variants.
We keep this trivially simple — only one prompt (`system`) and one default
version (v1). The bundled file is the source of truth; we never inline the
prompt in code so prompt iteration is a JSON-only diff.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent
_BUNDLED_VERSIONS: dict[str, Path] = {
    "v1": _PROMPTS_DIR / "_default_scaffold_prompt.json",
}
_DEFAULT_VERSION = "v1"


class ScaffoldPromptError(ValueError):
    """Raised when the scaffold prompt file is missing or malformed."""


@lru_cache(maxsize=1)
def load_system_prompt() -> str:
    """Resolve and return the synthesizer system prompt string.

    Resolution order (matches `pro/prompts.py`):
      1. ``GECKO_SCAFFOLD_PROMPTS_PATH`` — full path override.
      2. ``GECKO_SCAFFOLD_PROMPTS_VERSION`` — bundled version selector.
      3. Bundled default (``v1``).
    """
    override = os.environ.get("GECKO_SCAFFOLD_PROMPTS_PATH")
    if override:
        path = Path(override).expanduser()
    else:
        version = os.environ.get("GECKO_SCAFFOLD_PROMPTS_VERSION", _DEFAULT_VERSION).strip()
        if version not in _BUNDLED_VERSIONS:
            raise ScaffoldPromptError(
                f"GECKO_SCAFFOLD_PROMPTS_VERSION={version!r} is not a known bundled version "
                f"(known: {sorted(_BUNDLED_VERSIONS)})"
            )
        path = _BUNDLED_VERSIONS[version]

    if not path.is_file():
        raise ScaffoldPromptError(f"scaffold prompt file is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScaffoldPromptError(f"scaffold prompt JSON at {path} is not valid: {exc}") from exc
    system = data.get("system")
    if not isinstance(system, str) or not system.strip():
        raise ScaffoldPromptError("scaffold prompt JSON missing non-empty 'system' key")
    return system.strip()


__all__ = ["ScaffoldPromptError", "load_system_prompt"]
