"""Tests for decline-side decision recording (honesty-sprint fix 6b).

Before fix 6b, only `coordinator.action == "act"` decisions reached the
recorder — typically <40% of polls. Panel-decline and oracle-pass-decline
short-circuited at `open_position` without producing a `DecisionDoc`, so
the vector substrate could never answer "how often did the panel decline
a setup like this before?".

The fix wires `_record_decline_decision` into both decline branches.
This suite asserts the contract:

  1. panel-decline produces a `DecisionDoc` with `coordinator.action == "decline"`
     and `coordinator.rule` carrying the panel's reason / coordinator rule.
  2. the decline DecisionDoc goes through the fix-6 embedder hook —
     a patch row with `embedding` / `embedding_model` / `embedding_summary`
     lands in the same JSONL.
  3. oracle-pass-decline produces `coordinator.rule == "oracle_pass"`
     and the oracle block is populated (the oracle IS what's vetoing).
  4. the decline DecisionDoc has `outcome=None` — `close_position` only
     runs after an act-path entry, so declines are forever outcome-less.
  5. the trading loop survives a recorder exception in the decline path —
     mock `_RECORDER.record` to raise, assert `_record_decline_decision`
     returns silently.

Pattern lifted from `test_decision_store_embedding.py` — same fixture
style, same `_FakeColl`, same synchronous-embedder pattern so assertions
are race-free.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# Sprint 24-U (2026-05-31) — wiring landed. `_record_decline_decision`,
# `_voices_for_record`, and `_oracle_for_record` are now on the bot module
# (added immediately above the existing `_init_decision_store()` call site).
# Tests run live.

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

import decision_store.embedder as embedder_module  # noqa: E402
from decision_store.models import SimulationDoc  # noqa: E402
from decision_store.recorder import SimulationRegistry  # noqa: E402

# ── shared fixtures ────────────────────────────────────────────────────


class _FakeColl:
    def __init__(self):
        self.docs: dict[str, dict] = {}

    def update_one(self, flt, update, upsert=False):
        key = flt.get("decision_id") or flt.get("run_id")
        self.docs.setdefault(key, {}).update(update["$set"])


def _fake_embed_factory(vector: list[float], used_model: str = "voyage-finance-2"):
    """Drop-in replacement for `submit_embedding_job` that fires the
    callback synchronously — eliminates the background-thread race in
    the JSONL-shape assertions."""

    def _submit(text, on_done, *, model=None):
        on_done(vector, model or used_model)

    return _submit


def _mk_registry(tmp_path, decs_coll=None):
    sims = _FakeColl()
    decs = decs_coll if decs_coll is not None else _FakeColl()
    reg = SimulationRegistry(root=tmp_path, sims_coll=sims, decs_coll=decs)
    reg.start(
        SimulationDoc(
            run_id="",
            strategy_id="jto",
            agent_group="default",
            symbol_universe=["JTO"],
            universe_label="majors",
            config={},
            mode="paper",
            code_commit="abc",
        )
    )
    return reg, decs


def _fake_local_decision(
    *,
    action: str = "decline",
    reason: str = "chop_high_conviction_floor",
    rule: str | None = "chop_high_conviction",
):
    """Mint a duck-typed stand-in for `LocalDecision`. The recorder only
    reads `.voice_opinions`, `.action`, `.coordinator_rule_fired`,
    `.reason` — duck typing avoids dragging the Pydantic stack into the
    test surface."""
    voice_opinions = [
        SimpleNamespace(
            voice_name="chart_analyst",
            verdict="bearish",
            confidence=0.62,
            reasoning="multi-timeframe chop; momentum exhausted",
        ),
        SimpleNamespace(
            voice_name="regime_analyst",
            verdict="bearish",
            confidence=0.58,
            reasoning="1h CHOP, 5m drifting lower",
        ),
        SimpleNamespace(
            voice_name="risk_voice",
            verdict="neutral",
            confidence=0.50,
            reasoning="operational headroom ok",
        ),
    ]
    return SimpleNamespace(
        action=action,
        reason=reason,
        coordinator_rule_fired=rule,
        voice_opinions=voice_opinions,
        decision_id="local-fake-1",
        total_elapsed_ms=120,
        total_cost_usd=0.0,
    )


def _fake_fund_verdict(
    *,
    verdict: str = "pass",
    confidence: float = 0.78,
    citations_count: int = 6,
):
    return SimpleNamespace(
        verdict=verdict,
        confidence=confidence,
        citations_count=citations_count,
    )


def _market_state_with_range(range_pct: float = 2.4) -> dict:
    return {
        "instrument": "JTO",
        "spot_price": 1.0,
        "range_24h_pct": range_pct,
        "regime_1h": "CHOP",
    }


@pytest.fixture
def bot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """Import the bot module with the local panel disabled, then arm a
    fresh recorder pointing at `tmp_path`. Mirrors the fixture style in
    `test_volume_spike_and_btc_overlay.py` — heavy import once, then
    point the global recorder at a clean run dir per test."""
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("GECKO_DECISION_EMBED", "1")
    if "jto_breakout_gecko_gated_contest_bot" in sys.modules:
        del sys.modules["jto_breakout_gecko_gated_contest_bot"]
    import jto_breakout_gecko_gated_contest_bot as m

    # Arm a clean recorder per test — the module-level `_init_decision_store`
    # call at import time may have created a stale recorder pointed at the
    # real decision_runs/ directory. Swap it for one rooted in tmp_path so
    # the JSONL writes here are observable and isolated.
    reg, decs = _mk_registry(tmp_path)
    monkeypatch.setattr(m, "_RECORDER", reg.recorder())
    monkeypatch.setattr(m, "_RUN_ID", reg._run_dir.name)
    # Synchronous embedder so the patch-row assertion is race-free.
    monkeypatch.setattr(
        embedder_module, "submit_embedding_job", _fake_embed_factory([0.1] * 1024)
    )
    # Seed _LAST_INDEX so the snapshot has something to read (the bot's
    # poll_instruments path normally populates this).
    m._LAST_INDEX["JTO"] = {
        "adx": 22.5,
        "plus_di": 18.1,
        "minus_di": 24.3,
        "rsi": 48.7,
        "mfi": 51.2,
        "chop": 62.0,
        "bb_width": 0.04,
        "ema_stack": "bear",
        "regime": "CHOP",
        "regime_1h": "CHOP",
    }
    return m, reg, decs


# ── 1. panel-decline produces a decline DecisionDoc ────────────────────


def test_panel_decline_produces_decline_decision_doc(bot):
    """When the panel returns `action=decline`, the recorder writes a
    `DecisionDoc` with `coordinator.action=='decline'` and the rule
    carrying the panel's coordinator rule (or reason fallback)."""
    m, reg, decs = bot
    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout+volume", "instrument": "JTO"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        local_decision=_fake_local_decision(
            action="decline",
            reason="chop_high_conviction_floor",
            rule="chop_high_conviction",
        ),
        fund_verdict=None,
        rule="chop_high_conviction",
    )

    lines = (reg._run_dir / "decisions.jsonl").read_text().splitlines()
    decision_row = json.loads(lines[0])
    assert decision_row["coordinator"]["action"] == "decline"
    assert decision_row["coordinator"]["rule"] == "chop_high_conviction"
    assert decision_row["symbol"] == "JTO"
    assert decision_row["outcome"] is None
    # Voices block carries the panel's actual votes (not synthesised).
    voice_names = {v["name"] for v in decision_row["voices"]}
    assert voice_names == {"chart_analyst", "regime_analyst", "risk_voice"}
    # Indicators come from the snapshot helper — all 14 slots present.
    assert decision_row["indicators"]["regime_1h"] == "CHOP"
    assert decision_row["indicators"]["adx"] == 22.5
    # Mongo doc mirrors JSONL via the best-effort upsert.
    assert decs.docs[decision_row["decision_id"]]["coordinator"]["action"] == "decline"


# ── 2. decline-side embedder hook runs ─────────────────────────────────


def test_panel_decline_routes_through_embedder_hook(bot):
    """The decline DecisionDoc must go through the same fix-6 embedder
    as the act-path: a patch row with `embedding`, `embedding_model`,
    `embedding_summary` lands in the JSONL right after the decision row."""
    m, reg, _decs = bot
    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        local_decision=_fake_local_decision(),
        fund_verdict=None,
        rule="panel_decline",
    )

    lines = (reg._run_dir / "decisions.jsonl").read_text().splitlines()
    assert len(lines) == 2, f"expected decision + embedding patch, got {len(lines)} rows"
    patch_row = json.loads(lines[1])
    assert set(patch_row.keys()) == {
        "decision_id",
        "embedding",
        "embedding_model",
        "embedding_summary",
    }
    assert patch_row["embedding"] == [0.1] * 1024
    assert patch_row["embedding_model"] == "voyage-finance-2"
    # Summary text proves the decline-coordinator round-tripped through
    # `decision_summary_text` — query-CLI similarity scoring depends on it.
    assert "Coordinator: action=decline" in patch_row["embedding_summary"]
    assert "rule=panel_decline" in patch_row["embedding_summary"]


# ── 3. oracle-pass-decline has its own rule + populated oracle block ───


def test_oracle_pass_decline_uses_distinct_rule_and_populates_oracle(bot):
    """When the panel said act but the grounded oracle vetoed, the
    DecisionDoc must (a) carry `coordinator.rule == "oracle_pass"` so
    the gating-delta query can stratify, and (b) carry a populated
    `oracle` block — the oracle IS what's declining, so the disagreement
    between voices and oracle is the load-bearing signal."""
    m, reg, _decs = bot
    fund = _fake_fund_verdict(verdict="pass", confidence=0.81, citations_count=7)
    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        # Panel votes were act-leaning here — the oracle is the veto.
        local_decision=_fake_local_decision(
            action="act",
            reason="all_voices_aligned",
            rule="all_voices_aligned",
        ),
        fund_verdict=fund,
        rule="oracle_pass",
    )

    decision_row = json.loads((reg._run_dir / "decisions.jsonl").read_text().splitlines()[0])
    assert decision_row["coordinator"] == {"action": "decline", "rule": "oracle_pass"}
    assert decision_row["oracle"] == {
        "verdict": "pass",
        "confidence": 0.81,
        "citations": 7,
        "grounded": True,
    }


# ── 4. decline DecisionDoc has no outcome attached ─────────────────────


def test_decline_decision_doc_has_no_outcome(bot):
    """`close_position` only runs after an act-path entry; a decline
    never opens a position, so `outcome` is None forever. The query CLI
    relies on `outcome is None` to surface declines as "pending /
    intentionally outcome-less" rather than "still open trade"."""
    m, reg, _decs = bot
    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        local_decision=_fake_local_decision(),
        fund_verdict=None,
        rule="panel_decline",
    )

    decision_row = json.loads((reg._run_dir / "decisions.jsonl").read_text().splitlines()[0])
    assert decision_row["outcome"] is None
    # And there's no later outcome patch row — only the decision + the
    # embedding patch should exist.
    lines = (reg._run_dir / "decisions.jsonl").read_text().splitlines()
    for line in lines:
        row = json.loads(line)
        assert "outcome" not in row or row.get("outcome") is None


# ── 5. trading loop survives a recorder exception in the decline path ──


def test_decline_path_swallows_recorder_exception(bot, monkeypatch: pytest.MonkeyPatch):
    """The recorder must NEVER crash the trading loop. The helper wraps
    every step; a raise from `.record(...)` is logged and absorbed."""
    m, _reg, _decs = bot

    def _boom(*_args, **_kwargs):
        raise RuntimeError("mongo + jsonl both blew up")

    # Replace the recorder with one whose `.record` raises.
    monkeypatch.setattr(m._RECORDER, "record", _boom)

    # Must NOT raise. If `_record_decline_decision` ever lets an
    # exception escape, the bot loop dies; this assertion is the guard.
    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        local_decision=_fake_local_decision(),
        fund_verdict=None,
        rule="panel_decline",
    )


# ── 6. recorder-disabled is a no-op (not a crash) ──────────────────────


def test_decline_path_is_noop_when_recorder_unarmed(bot, monkeypatch: pytest.MonkeyPatch):
    """The recorder is None under pytest / on init failure. The helper
    must short-circuit cleanly — no JSONL writes, no exceptions."""
    m, reg, _decs = bot
    monkeypatch.setattr(m, "_RECORDER", None)
    monkeypatch.setattr(m, "_RUN_ID", None)

    m._record_decline_decision(
        instrument="JTO",
        symbol_str="JTO-USDC",
        signal_data={"primitive": "breakout"},
        market_state=_market_state_with_range(2.4),
        ms_candles=[],
        local_decision=_fake_local_decision(),
        fund_verdict=None,
        rule="panel_decline",
    )
    # JSONL file may or may not exist (the registry create touched the dir);
    # what matters is that no decision row was appended.
    path = reg._run_dir / "decisions.jsonl"
    if path.exists():
        assert path.read_text() == ""
