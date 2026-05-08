"""JSON-shape contract tests for the trade-panel system prompts.

Light: no LLM calls, no AG2 import. Just validates the bundled JSON
matches REQUIRED_AGENTS and that every prompt carries enough structure
for the closing-line parser to do its job.
"""

from __future__ import annotations

import re

import pytest
from gecko_core.orchestration.trade_panel.personas import (
    CLOSING_LINE_PATTERNS,
    REQUIRED_AGENTS,
    ROLE_TASKS,
)
from gecko_core.orchestration.trade_panel.prompts import (
    TradePanelPromptsConfigError,
    load_prompts,
)


def test_all_seven_personas_present() -> None:
    prompts = load_prompts()
    assert set(prompts.keys()) == set(REQUIRED_AGENTS)
    assert len(REQUIRED_AGENTS) == 7


def test_every_prompt_is_substantial() -> None:
    prompts = load_prompts()
    for name in REQUIRED_AGENTS:
        body = prompts[name]
        assert isinstance(body, str)
        # 80-150 lines expected per ticket; the JSON is a single string with
        # \n separators so we count newlines instead. Floor of 600 chars
        # catches any accidental stub without coupling to exact length.
        assert len(body) > 600, f"prompt for {name} too short: {len(body)} chars"
        # Each persona must mention its own name in the role one-liner.
        assert name in body, f"prompt for {name} doesn't mention its own name"


def test_every_prompt_advertises_its_closing_line_pattern() -> None:
    """Each prompt body must contain the literal closing-line label.

    We don't try to match the full regex against the prompt (the prompt
    contains the *template*, not a real closing line). Instead we verify
    the load-bearing prefix appears verbatim — that's what tells the
    model what to emit.
    """
    prompts = load_prompts()
    expected_prefixes = {
        "technical_analyst": "Trend verdict:",
        "sentiment_analyst": "Sentiment band:",
        "fundamental_analyst": "Protocol health:",
        "risk_manager": "Risk band:",
        "strategist": "Strategic intent:",
        "bull_bear_debater": "Decisive question:",
        "coordinator": "Final verdict:",
    }
    for name, prefix in expected_prefixes.items():
        assert prefix in prompts[name], f"prompt for {name} missing closing-line prefix '{prefix}'"


def test_closing_line_patterns_are_compilable_regexes() -> None:
    for name in REQUIRED_AGENTS:
        pat = CLOSING_LINE_PATTERNS[name]
        # Will raise if invalid.
        re.compile(pat)


def test_role_tasks_cover_all_personas() -> None:
    assert set(ROLE_TASKS.keys()) == set(REQUIRED_AGENTS)
    for name, summary in ROLE_TASKS.items():
        assert isinstance(summary, str) and summary.strip(), name


def test_load_prompts_raises_on_missing_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bad override path must fail loud at load time, not mid-debate."""
    load_prompts.cache_clear()
    monkeypatch.setenv("GECKO_TRADE_PANEL_PROMPTS_PATH", "/no/such/path/prompts.json")
    with pytest.raises(TradePanelPromptsConfigError):
        load_prompts()
    load_prompts.cache_clear()
