"""Sprint 23 — tests for the grader → Oracle one-click handoff.

These tests pin the contract that drives Marina's "what do I do with
this grade?" moment:

  1. A-grade traders surface a 'basic' tier handoff
  2. B-grade traders surface a 'pro' tier handoff (borderline → pay 3x
     for richer envelope)
  3. C/D-grade traders surface NO handoff (the grader's call is the
     answer; don't burn $0.25 on a Pre-confirmed reject)
  4. The MCP args dict is ready to pass — keys present, types correct
  5. The idea string bakes in grade + metric signature
  6. render_handoffs gracefully handles empty / all-C-grade batches
  7. Malformed trader dicts (missing nickname/grade) skip silently
  8. max_handoffs cap is enforced (default 3, dashboard-fit)

Light fakes only — no MCP calls, no Oracle invocations. The whole
point of the handoff is that it's text the user reads + chooses to
invoke; we never auto-fire from grader output.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the skill importable.
_SKILL_DIR = Path(__file__).resolve().parents[1]
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from handoff import (  # noqa: E402
    OracleHandoff,
    build_oracle_handoff,
    render_handoffs,
)


def _graded(
    grade: str = "A",
    *,
    nickname: str = "jiumao",
    sharpe_def: float = 0.62,
    stability: float = 0.45,
    cat_rate: float = 2.0,
    true_dd: float = -8.5,
    okx_pnl_ratio: float = 0.42,
    aum: float = 85_000,
) -> dict:
    """Build a graded-trader dict matching grader.grade_okx_trader_from_payload."""
    return {
        "nickname": nickname,
        "authorId": "abc123",
        "grade": grade,
        "aum": aum,
        "okx_pnl_ratio": okx_pnl_ratio,
        "sharpe_deflated": sharpe_def,
        "stability_ratio": stability,
        "catastrophic_rate_pct": cat_rate,
        "true_max_dd_pct": true_dd,
    }


# ── build_oracle_handoff per-grade behavior ────────────────────────────


def test_a_grade_yields_basic_tier_handoff() -> None:
    """A-grade trader → basic tier ($0.25), clean handoff."""
    handoff = build_oracle_handoff(_graded(grade="A"))
    assert handoff is not None
    assert isinstance(handoff, OracleHandoff)
    assert handoff.trader_grade == "A"
    assert handoff.tier == "basic"
    assert handoff.tool == "mcp__gecko__gecko_trade_research"


def test_b_grade_yields_pro_tier_handoff() -> None:
    """B-grade (borderline) → pro tier ($0.75) for richer envelope."""
    handoff = build_oracle_handoff(_graded(grade="B"))
    assert handoff is not None
    assert handoff.trader_grade == "B"
    assert handoff.tier == "pro"


def test_c_grade_yields_no_handoff() -> None:
    """C-grade → no handoff. Grader's call IS the answer; no $0.25 needed."""
    assert build_oracle_handoff(_graded(grade="C")) is None


def test_d_grade_yields_no_handoff() -> None:
    """D-grade (gambling) → no handoff."""
    assert build_oracle_handoff(_graded(grade="D")) is None


def test_unknown_grade_yields_no_handoff() -> None:
    """'?' or unknown grade → no handoff."""
    assert build_oracle_handoff(_graded(grade="?")) is None


def test_lowercase_grade_normalized() -> None:
    """grade 'a' → handoff at tier basic (case-insensitive)."""
    handoff = build_oracle_handoff(_graded(grade="a"))
    assert handoff is not None
    assert handoff.trader_grade == "A"
    assert handoff.tier == "basic"


# ── defensive parsing ─────────────────────────────────────────────────


def test_missing_nickname_yields_no_handoff() -> None:
    """Malformed payload (no nickname) → None, no crash."""
    bad = _graded(grade="A")
    del bad["nickname"]
    assert build_oracle_handoff(bad) is None


def test_missing_grade_yields_no_handoff() -> None:
    """Missing grade key → None, no crash."""
    bad = _graded(grade="A")
    del bad["grade"]
    assert build_oracle_handoff(bad) is None


def test_non_string_grade_yields_no_handoff() -> None:
    """grade=None or int → None, no crash."""
    bad = _graded(grade="A")
    bad["grade"] = None
    assert build_oracle_handoff(bad) is None


# ── mcp_args contract ─────────────────────────────────────────────────


def test_mcp_args_has_required_keys() -> None:
    """The kwargs dict is ready to pass to mcp__gecko__gecko_trade_research."""
    handoff = build_oracle_handoff(_graded(grade="A"))
    assert handoff is not None
    args = handoff.mcp_args
    assert set(args.keys()) == {"idea", "protocol", "vertical", "tier"}
    assert args["protocol"] == "okx-copytrading"
    assert args["vertical"] == "dex"
    assert args["tier"] == "basic"


def test_mcp_args_idea_bakes_grade_and_metrics() -> None:
    """idea string carries enough context for the panel to reason."""
    handoff = build_oracle_handoff(_graded(grade="B", nickname="alpha_seeker", sharpe_def=0.42))
    assert handoff is not None
    idea = handoff.idea
    assert "alpha_seeker" in idea
    assert "B" in idea  # grade
    assert "0.42" in idea  # sharpe_deflated
    assert "Default-REJECT" in idea  # the posture instruction
    assert "dissent" in idea  # the panel-wedge ask
    assert len(idea) <= 2000  # fits the model's max_length


def test_mcp_args_idea_includes_period() -> None:
    """The period string surfaces in the question so the panel scopes its read."""
    handoff = build_oracle_handoff(_graded(grade="A"), period="90d")
    assert handoff is not None
    assert "90d" in handoff.idea


# ── render_handoffs behavior ──────────────────────────────────────────


def test_render_with_no_traders_emits_empty_state_note() -> None:
    """Empty batch → explicit note, NOT silence."""
    out = render_handoffs([])
    assert "no A/B-graded" in out


def test_render_with_only_cd_traders_emits_empty_state_note() -> None:
    """All-C/D batch → empty-state note (the grader's call IS the answer)."""
    out = render_handoffs([_graded(grade="C"), _graded(grade="D", nickname="degen")])
    assert "no A/B-graded" in out


def test_render_with_ab_traders_emits_invocation_lines() -> None:
    """A/B traders → 'Invoke: mcp__gecko__gecko_trade_research(...)' lines."""
    out = render_handoffs(
        [
            _graded(grade="A", nickname="solid_alpha"),
            _graded(grade="B", nickname="borderline_b"),
            _graded(grade="C", nickname="should_skip"),
        ]
    )
    assert "solid_alpha" in out
    assert "borderline_b" in out
    assert "should_skip" not in out  # C-grade filtered
    assert "mcp__gecko__gecko_trade_research" in out
    assert "$0.25" in out  # basic-tier price label
    assert "$0.75" in out  # pro-tier price label


def test_render_caps_handoffs_at_max() -> None:
    """max_handoffs cap prevents the dashboard close from ballooning."""
    traders = [_graded(grade="A", nickname=f"t{i}") for i in range(10)]
    out = render_handoffs(traders, max_handoffs=2)
    # First two should appear; rest should not.
    assert "t0" in out
    assert "t1" in out
    assert "t5" not in out


def test_render_caps_default_to_three() -> None:
    """Default cap is 3 (dashboard-fit)."""
    traders = [_graded(grade="A", nickname=f"t{i}") for i in range(10)]
    out = render_handoffs(traders)
    assert "t0" in out
    assert "t1" in out
    assert "t2" in out
    assert "t3" not in out


def test_render_includes_x402_no_signup_framing() -> None:
    """The pricing-and-onboarding hedge surfaces — no surprise to the user."""
    out = render_handoffs([_graded(grade="A")])
    assert "x402" in out
    assert "no signup" in out or "no invoice" in out
