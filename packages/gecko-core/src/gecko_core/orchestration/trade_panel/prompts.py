"""Trade panel system-prompt loader.

Mirrors ``orchestration/pro/prompts.py`` — JSON-on-disk so prompts can be
tuned without code changes (and so the OSS surface ships working defaults).
Resolution order:

1. ``GECKO_TRADE_PANEL_PROMPTS_PATH`` env var → JSON file at that path.
2. The bundled ``_default_prompts.json`` next to this module.

File format::

    {
      "version": "v1",
      "agents": {
        "technical_analyst":   "...",
        "sentiment_analyst":   "...",
        "fundamental_analyst": "...",
        "risk_manager":        "...",
        "strategist":          "...",
        "bull_bear_debater":   "...",
        "coordinator":         "..."
      }
    }

Schema enforced at load — missing keys, empty values, or wrong types raise
:class:`TradePanelPromptsConfigError` so a bad override fails at boot rather
than mid-debate.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from gecko_core.orchestration.trade_panel.personas import REQUIRED_AGENTS

_PROMPTS_DIR = Path(__file__).parent
_DEFAULT_PROMPTS_PATH = _PROMPTS_DIR / "_default_prompts.json"


class TradePanelPromptsConfigError(ValueError):
    """Raised when prompts JSON is missing keys, empty, or malformed."""


def _validate(data: dict[str, object]) -> dict[str, str]:
    agents = data.get("agents")
    if not isinstance(agents, dict):
        raise TradePanelPromptsConfigError(
            "trade-panel prompts JSON must have a top-level 'agents' object"
        )
    out: dict[str, str] = {}
    for name in REQUIRED_AGENTS:
        val = agents.get(name)
        if not isinstance(val, str) or not val.strip():
            raise TradePanelPromptsConfigError(
                f"trade-panel prompts JSON is missing or empty for required agent '{name}'"
            )
        out[name] = val.strip()
    return out


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, str]:
    """Resolve and validate the 7 trade-panel system prompts.

    Returns ``{agent_name: system_message}`` containing exactly the 7
    required entries. Caches so re-imports don't re-parse the file.
    """
    override = os.environ.get("GECKO_TRADE_PANEL_PROMPTS_PATH")
    path = Path(override).expanduser() if override else _DEFAULT_PROMPTS_PATH
    if not path.is_file():
        if override:
            raise TradePanelPromptsConfigError(
                f"GECKO_TRADE_PANEL_PROMPTS_PATH={override} does not point to a readable file"
            )
        raise TradePanelPromptsConfigError(f"bundled trade-panel prompts file is missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TradePanelPromptsConfigError(
            f"trade-panel prompts JSON at {path} is not valid JSON: {exc}"
        ) from exc
    return _validate(data)


__all__ = [
    "TradePanelPromptsConfigError",
    "load_prompts",
]
