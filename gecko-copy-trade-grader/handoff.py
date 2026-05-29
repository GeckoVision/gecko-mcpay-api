"""Grader → Oracle one-click handoff.

Sprint 23 (2026-05-28). Per the PM journey doc Wednesday deliverable:
Marina runs the grader, sees a trader graded A or B, wants to dig
deeper. Without this module, she has to manually craft a
``gecko_trade_research`` invocation with the right context. With this
module, the grader emits the exact MCP call she (or Claude) can fire
verbatim — copy/paste or one-tool-use.

Falsifier (per PM doc): ≥2 of the next 5 grader installs click through
to an Oracle call in the same session. If <2, the handoff framing is
wrong; revisit copy + placement.

DESIGN

The grader produces a per-trader dict (see ``grader.py``
``grade_okx_trader_from_payload``). This module takes that dict and
produces an ``OracleHandoff`` envelope carrying:

  - ``idea``: pre-formatted question for the Oracle, with the trader's
    grade + key metrics baked in so the panel reads the right context
  - ``tool``: the literal MCP tool name (``mcp__gecko__gecko_trade_research``)
  - ``mcp_args``: ready-to-pass kwargs dict
  - ``tier``: ``basic`` ($0.25) for clean A graders, ``pro`` ($0.75)
    for borderline cases where the extra-cite envelope earns its 3x

Only A and B graders surface a handoff — C/D graders are explicitly
filtered out (the answer there is "don't copy this trader" without
needing the panel's $0.25). The skill prints "no handoff: trader
graded C/D — the grader's call is the answer" for those.

NOT EXECUTED BY THE GRADER. The handoff envelope is a STRING the user
or Claude reads + chooses to invoke. We never auto-fire a paid Oracle
call from grader output — that would be a billable side effect of a
free local skill, which is the wrong UX.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_HANDOFF_GRADES = frozenset({"A", "B"})
_PRO_TIER_GRADES = frozenset({"B"})  # borderline → pay 3x for richer envelope


class OracleHandoff(BaseModel):
    """One pre-built Oracle invocation for a graded trader.

    ``idea`` is the load-bearing string the Oracle's panel reads. It
    bakes in the grade + the metric signature so the panel doesn't
    have to re-derive context. ``mcp_args`` is the ready-to-pass dict
    for ``mcp__gecko__gecko_trade_research``.
    """

    model_config = ConfigDict(extra="forbid")

    trader_nickname: str
    trader_grade: str
    tool: Literal["mcp__gecko__gecko_trade_research"] = "mcp__gecko__gecko_trade_research"
    tier: Literal["basic", "pro"]
    idea: str = Field(..., max_length=2000)
    protocol: str = "okx-copytrading"
    vertical: str = "dex"

    @property
    def mcp_args(self) -> dict[str, Any]:
        """The ready-to-pass kwargs dict for the MCP tool call."""
        return {
            "idea": self.idea,
            "protocol": self.protocol,
            "vertical": self.vertical,
            "tier": self.tier,
        }


def build_oracle_handoff(
    graded_trader: dict[str, Any],
    *,
    period: str = "30d",
) -> OracleHandoff | None:
    """Build a per-trader Oracle handoff envelope.

    Returns None when the trader is graded C or D (or missing a grade)
    — the grader's own verdict is the answer for those, and burning
    $0.25 on a "should I copy a degrading/gambling trader" question is
    answered by the grader for free.

    Returns None when the trader's payload is malformed (missing
    nickname or grade) — defensive, never crash the grader on bad data.
    """
    grade = graded_trader.get("grade")
    nickname = graded_trader.get("nickname")
    if not nickname or not isinstance(grade, str):
        return None
    grade_upper = grade.upper()
    if grade_upper not in _HANDOFF_GRADES:
        return None

    tier: Literal["basic", "pro"] = "pro" if grade_upper in _PRO_TIER_GRADES else "basic"

    idea = _build_idea(graded_trader, period=period, grade=grade_upper)

    return OracleHandoff(
        trader_nickname=str(nickname),
        trader_grade=grade_upper,
        tier=tier,
        idea=idea,
    )


def _build_idea(graded_trader: dict[str, Any], *, period: str, grade: str) -> str:
    """Build the Oracle's ``idea`` string with grade + metric signature baked in.

    The panel will read this verbatim. The phrasing follows the
    'single-shot judgment question' pattern from the moat doc — direct
    ask, no preamble. The panel sees enough context to reason without
    re-deriving the trader's profile.
    """
    aum = graded_trader.get("aum", 0)
    okx_pnl_ratio = graded_trader.get("okx_pnl_ratio", 0.0)
    sharpe_def = graded_trader.get("sharpe_deflated", 0.0)
    stability = graded_trader.get("stability_ratio", 0.0)
    cat_rate = graded_trader.get("catastrophic_rate_pct", 0.0)
    true_dd = graded_trader.get("true_max_dd_pct", 0.0)

    aum_str = f"${aum / 1000:.0f}K" if aum else "AUM n/a"
    pnl_str = f"{okx_pnl_ratio * 100:+.1f}%" if okx_pnl_ratio else "PnL n/a"

    return (
        f"Should I copy the strategy of OKX trader '{graded_trader['nickname']}' "
        f"(period: {period})? The gecko-copy-trade-grader graded them {grade} on "
        f"the rigor scorecard: Deflated Sharpe {sharpe_def:+.2f}, second/first-half "
        f"stability {stability:+.2f}, catastrophic-trade rate {cat_rate:.0f}%, "
        f"true max drawdown {true_dd:.1f}%, OKX-reported {period} PnL {pnl_str}, "
        f"AUM {aum_str}. Default-REJECT the call unless the panel can name "
        f"a specific reason this trader's edge is structural, not noise — "
        f"surface the strongest bear case in the dissent."
    )


def render_handoffs(
    graded_traders: list[dict[str, Any]],
    *,
    period: str = "30d",
    max_handoffs: int = 3,
) -> str:
    """Render the 'next step' block printed at the end of a grader run.

    Filters to A/B graders, caps at ``max_handoffs`` (default 3 — the
    dashboard fits 3 lines cleanly; more clutters the close). When no
    A/B graders exist, renders an explicit empty-state note instead
    of silence.
    """
    handoffs = []
    for t in graded_traders:
        ho = build_oracle_handoff(t, period=period)
        if ho is not None:
            handoffs.append(ho)
        if len(handoffs) >= max_handoffs:
            break

    if not handoffs:
        return (
            "\nNext step: no A/B-graded traders in this batch — the grader's call "
            "is the answer. (C/D = don't copy; no Oracle call needed.)\n"
        )

    lines: list[str] = [
        "\n" + "─" * 80,
        f"Next step — dig deeper on the top {len(handoffs)} trader(s) with the Gecko Oracle:",
        "─" * 80,
    ]
    for ho in handoffs:
        lines.append("")
        lines.append(
            f"  • {ho.trader_nickname} (graded {ho.trader_grade}) "
            f"— Oracle tier: {ho.tier} ({_tier_price(ho.tier)})"
        )
        lines.append(f"    Invoke: {ho.tool}({_format_mcp_args(ho.mcp_args)})")
    lines.append("")
    lines.append(
        "Each call is settled on-chain via x402 — no signup, no invoice, "
        "no committed monthly fee. The Oracle defaults to REJECT; pay only "
        "for verdicts that survive its dissent panel."
    )
    lines.append("")
    return "\n".join(lines)


def _tier_price(tier: str) -> str:
    return {"basic": "$0.25", "pro": "$0.75"}.get(tier, "?")


def _format_mcp_args(args: dict[str, Any]) -> str:
    """Format the kwargs dict as a copy-paste-ready Python literal.

    The user (or Claude) reads this and either pastes into a notebook
    or hands it to a tool-use call. Multi-line for readability — the
    idea string is long.
    """
    parts: list[str] = []
    for key, value in args.items():
        if isinstance(value, str):
            # JSON-encode to handle quotes/newlines/etc safely
            parts.append(f"{key}={json.dumps(value)}")
        else:
            parts.append(f"{key}={value!r}")
    return ", ".join(parts)


__all__ = [
    "OracleHandoff",
    "build_oracle_handoff",
    "render_handoffs",
]
