"""Non-live readiness checks for the S2X-15 mainnet cutover eval gate.

These tests assert the gate machinery is wired correctly. They make NO
network calls, spend NO money, and do not import the live rubric SDK.

Purpose: fail loudly in CI if anyone breaks the gate's invariants
(suite shape, runner flags, env-var fallback, gate script wiring) so
that when Ernani actually runs the paid live gate, every precondition
is already true.

See: scripts/run_eval_gate.sh, docs/runbooks/eval-gate.md
"""

from __future__ import annotations

import inspect
import json
import os
import stat
from pathlib import Path

import pytest

from tests.eval import rubric as rubric_module
from tests.eval import runner as runner_module

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITES_DIR = REPO_ROOT / "tests" / "eval" / "suites"
GATE_SCRIPT = REPO_ROOT / "scripts" / "run_eval_gate.sh"

EXPECTED_BALANCE: dict[str, dict[str, int]] = {
    # (n_total, ship_count, kill_count) — matches the Wave 2 sub-suites.
    "general": {"n": 20, "ship": 10, "kill": 10},
    "crypto": {"n": 15, "ship": 7, "kill": 8},
    "saas": {"n": 15, "ship": 7, "kill": 8},
}

REQUIRED_FIELDS = ("expected_verdict", "expected_categories", "must_cite_sources")


@pytest.mark.parametrize("suite", list(EXPECTED_BALANCE.keys()))
def test_suite_file_exists_and_balanced(suite: str) -> None:
    path = SUITES_DIR / f"{suite}_suite.json"
    assert path.exists(), f"missing suite file: {path}"

    ideas = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(ideas, list), f"{suite}: root must be a JSON array"

    expected = EXPECTED_BALANCE[suite]
    assert len(ideas) == expected["n"], f"{suite}: expected {expected['n']} ideas, got {len(ideas)}"

    ship = sum(1 for i in ideas if i.get("expected_verdict") == "ship")
    kill = sum(1 for i in ideas if i.get("expected_verdict") == "kill")
    assert ship == expected["ship"], f"{suite}: ship count {ship} != {expected['ship']}"
    assert kill == expected["kill"], f"{suite}: kill count {kill} != {expected['kill']}"


@pytest.mark.parametrize("suite", list(EXPECTED_BALANCE.keys()))
def test_every_idea_has_required_fields(suite: str) -> None:
    path = SUITES_DIR / f"{suite}_suite.json"
    ideas = json.loads(path.read_text(encoding="utf-8"))
    for idea in ideas:
        for field in REQUIRED_FIELDS:
            assert field in idea, f"{suite}/{idea.get('id', '?')}: missing field '{field}'"
        # must_cite_sources must be a list (possibly empty), not None / dict / str.
        assert isinstance(idea["must_cite_sources"], list), (
            f"{suite}/{idea['id']}: must_cite_sources must be a list"
        )
        assert isinstance(idea["expected_categories"], list), (
            f"{suite}/{idea['id']}: expected_categories must be a list"
        )
        assert idea["expected_verdict"] in ("ship", "kill", "pivot"), (
            f"{suite}/{idea['id']}: unexpected verdict {idea['expected_verdict']!r}"
        )


def test_runner_has_live_flag() -> None:
    """argparse contract: --live, --suite, --save/--no-save must all be present."""
    parser = runner_module._build_parser()
    flags = {action.option_strings[0] for action in parser._actions if action.option_strings}
    assert "--live" in flags, "runner is missing --live flag"
    assert "--suite" in flags, "runner is missing --suite flag"
    # The gate script relies on default save behavior (no --no-save passed).
    assert "--no-save" in flags, "runner is missing --no-save flag"

    suite_action = next(a for a in parser._actions if a.option_strings == ["--suite"])
    assert suite_action.choices is not None
    for s in ("general", "crypto", "saas", "all"):
        assert s in suite_action.choices, f"--suite choices missing {s!r}"


def test_live_rubric_accepts_either_anthropic_or_claude_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The live rubric must read ANTHROPIC_API_KEY *and* CLAUDE_API_KEY as fallback.

    We don't actually call the API — we just verify that the source references
    both env names and that the missing-key path raises with both mentioned.
    """
    src = inspect.getsource(rubric_module.score_transcript_live)
    assert "ANTHROPIC_API_KEY" in src, "rubric must reference ANTHROPIC_API_KEY"
    assert "CLAUDE_API_KEY" in src, "rubric must reference CLAUDE_API_KEY as fallback"

    # With both env vars unset, calling the live rubric must raise before any
    # network I/O. We pass an empty transcript — it never gets used.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    with pytest.raises(RuntimeError) as exc_info:
        rubric_module.score_transcript_live({})
    msg = str(exc_info.value)
    assert "ANTHROPIC_API_KEY" in msg
    assert "CLAUDE_API_KEY" in msg


def test_gate_script_exists_executable_and_invokes_three_suites() -> None:
    assert GATE_SCRIPT.exists(), f"missing gate script: {GATE_SCRIPT}"

    mode = GATE_SCRIPT.stat().st_mode
    assert mode & stat.S_IXUSR, "gate script is not executable by owner"

    body = GATE_SCRIPT.read_text(encoding="utf-8")

    # All three suite invocations must be present, --live must be passed,
    # and the 0.85 threshold must be referenced.
    for suite in ("general", "crypto", "saas"):
        assert (
            '--suite "${suite}" --live' in body
            or f"--suite {suite} --live" in body
            or ("SUITES=(general crypto saas)" in body and '--suite "${suite}" --live' in body)
        ), f"gate script does not invoke runner for suite={suite}"
    assert "0.85" in body, "gate script does not reference 0.85 pass threshold"
    assert "SUITES=(general crypto saas)" in body, (
        "gate script SUITES array must list general, crypto, saas in order"
    )

    # Spend confirmation prompt must exist so it can't be run silently.
    assert "Proceed?" in body, "gate script must require interactive confirmation"

    # Must check for the rubric API key alternatives.
    assert "ANTHROPIC_API_KEY" in body
    assert "CLAUDE_API_KEY" in body
    assert "OPENAI_API_KEY" in body
    assert "GECKO_API_BASE" in body


def test_gate_script_has_no_network_calls_at_import_time() -> None:
    """Sanity: importing this test module must not have triggered any of the
    paid code paths. If `from anthropic import Anthropic` were at module top
    in rubric.py, this would still pass (the import is lazy inside the live
    function), but we assert the lazy structure explicitly here.
    """
    src = Path(rubric_module.__file__).read_text(encoding="utf-8")
    # The anthropic import must be inside score_transcript_live, not at module top.
    top_lines = src.splitlines()[:60]
    assert not any(
        line.strip().startswith("from anthropic") or line.strip().startswith("import anthropic")
        for line in top_lines
    ), "anthropic SDK must be imported lazily inside score_transcript_live"


def test_no_network_envvars_required_for_this_test_module() -> None:
    """Cheap guard: this test file should pass even with zero credentials."""
    # We don't strictly enforce the env is empty (CI may set it), but we
    # document intent: nothing in this module reads these.
    for var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        # Just access — never raise on presence/absence.
        _ = os.environ.get(var)
