"""Canonical persona definitions for the 7-agent trade research panel.

Mirrors ``orchestration/pro/`` conventions: ``REQUIRED_AGENTS`` is the single
source of truth for persona names + canonical order. Every other module in
this package iterates that tuple — JSON schema validation, AG2 agent build
order, transcript replay determinism all key off it.

Order rationale (Phase 8a):
  1. technical_analyst   — chart/price view, fastest signal
  2. sentiment_analyst   — narrative + social view, parallel-safe with #1
  3. fundamental_analyst — protocol mechanics, parallel-safe with #1/#2
  4. risk_manager        — veto-power; reads 1-3, names blocking risks
  5. strategist          — synthesizes 1-4 into a position thesis
  6. bull_bear_debater   — adversarial stress-test of #5
  7. coordinator         — aggregator, emits final verdict last

The first three are mutually independent (each reads the same retrieved
chunks; none reads the others' output). v1 stays sync round-robin per the
ticket spec — parallel dispatch is a v2 optimization.
"""

from __future__ import annotations

# Persona-name constants. Importing these (rather than spelling the strings
# inline) lets static analysis catch typos and gives IDE go-to-definition.
TECHNICAL_ANALYST = "technical_analyst"
SENTIMENT_ANALYST = "sentiment_analyst"
FUNDAMENTAL_ANALYST = "fundamental_analyst"
RISK_MANAGER = "risk_manager"
STRATEGIST = "strategist"
BULL_BEAR_DEBATER = "bull_bear_debater"
COORDINATOR = "coordinator"

REQUIRED_AGENTS: tuple[str, ...] = (
    TECHNICAL_ANALYST,
    SENTIMENT_ANALYST,
    FUNDAMENTAL_ANALYST,
    RISK_MANAGER,
    STRATEGIST,
    BULL_BEAR_DEBATER,
    COORDINATOR,
)

# Closing-line patterns each persona's reply must end with. The values are
# regex strings — parsing logic in ``__init__.py`` compiles + matches them
# against the last non-empty line of each turn to extract a structured
# verdict. Patterns are intentionally narrow so a freelancing model that
# omits the line surfaces as ``parsed_verdict=None`` rather than a silent
# parse-anything fallback.
CLOSING_LINE_PATTERNS: dict[str, str] = {
    TECHNICAL_ANALYST: r"^Trend verdict:\s*(bullish|bearish|mixed)\s*$",
    SENTIMENT_ANALYST: r"^Sentiment band:\s*(fear|neutral|greed)\s*$",
    FUNDAMENTAL_ANALYST: r"^Protocol health:\s*(degraded|stable|growing)\s*$",
    RISK_MANAGER: r"^Risk band:\s*(acceptable|elevated|unacceptable)\s*$",
    STRATEGIST: r"^Strategic intent:\s*(.+)$",
    BULL_BEAR_DEBATER: r"^Decisive question:\s*(.+)$",
    COORDINATOR: r"^Final verdict:\s*(act|pass|defer)\s*$",
}

# Role-to-task mapping — short prose summary used by tests + docs to assert
# every persona has a single coherent responsibility (no overlap, no gaps).
# The corresponding system prompt in ``_default_prompts.json`` is the
# load-bearing version; this dict is reference-only.
ROLE_TASKS: dict[str, str] = {
    TECHNICAL_ANALYST: "read price/volume/indicators; emit trend direction",
    SENTIMENT_ANALYST: "read news/social/governance; emit sentiment band",
    FUNDAMENTAL_ANALYST: "read protocol mechanics/TVL/audits; emit health band",
    RISK_MANAGER: "veto on oracle/slippage/contract/concentration risk",
    STRATEGIST: "synthesize 1-4 into position thesis (entry/size/stop/horizon)",
    BULL_BEAR_DEBATER: "single agent, dual perspective; stress-test strategist",
    COORDINATOR: "aggregate all turns; emit final verdict + JSON block",
}


__all__ = [
    "BULL_BEAR_DEBATER",
    "CLOSING_LINE_PATTERNS",
    "COORDINATOR",
    "FUNDAMENTAL_ANALYST",
    "REQUIRED_AGENTS",
    "RISK_MANAGER",
    "ROLE_TASKS",
    "SENTIMENT_ANALYST",
    "STRATEGIST",
    "TECHNICAL_ANALYST",
]
