"""Tests for oracle_ab_live — the growing live Oracle A/B from the bot decision log.

Load-bearing: action→arm mapping (act→ON, decline→REJECTED) must be exact, and
enrichment must NEVER fabricate an outcome — a None from the candle provider counts
as pending and is excluded, so the A/B only ever uses real closed-window returns.

Run: uv run pytest scripts/calibration/test_oracle_ab_live.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import oracle_ab_live as live


def test_to_entry_maps_action_to_verdict():
    assert (
        live._to_entry({"instrument": "WIF", "action": "act", "ts": "t"}, 1.5)["verdict"] == "act"
    )
    assert (
        live._to_entry({"instrument": "JTO", "action": "decline", "ts": "t"}, -0.3)["verdict"]
        == "defer"
    )


def test_enrich_excludes_pending_never_fabricates():
    decs = [
        {"instrument": "WIF", "action": "act", "ts": "t1"},
        {"instrument": "JTO", "action": "decline", "ts": "t2"},
        {"instrument": "PYTH", "action": "act", "ts": "t3"},
    ]
    # provider has an outcome for WIF + PYTH, but JTO's window is still open (None)
    outcomes = {"WIF": 2.0, "PYTH": -1.0, "JTO": None}

    def provider(sym, ts, hold_h):
        return outcomes[sym]

    entries, pending = live.enrich(decs, provider)
    assert pending == 1  # JTO excluded, not faked
    assert len(entries) == 2
    assert {e["sym"] for e in entries} == {"WIF", "PYTH"}
    assert all("pnl_real" in e for e in entries)


def test_null_provider_yields_all_pending():
    decs = [{"instrument": "WIF", "action": "act", "ts": "t1"}]
    entries, pending = live.enrich(decs, live.null_candle_provider)
    assert entries == [] and pending == 1


def test_entry_index_picks_closed_bar_no_lookahead():
    ts = [100.0, 200.0, 300.0, 400.0]  # ascending
    assert live.entry_index(ts, 250.0) == 1  # bar at/just-before the decision
    assert live.entry_index(ts, 300.0) == 2  # exact match -> that bar
    assert live.entry_index(ts, 400.0) == 3  # last bar
    assert live.entry_index(ts, 99.0) == -1  # decision predates the series
    assert live.entry_index(ts, 500.0) == 3  # after last -> last bar


def test_iso_to_ms_parses_utc():
    ms = live.iso_to_ms("2026-05-25T00:00:00+00:00")
    assert ms is not None and abs(ms - 1779667200000.0) < 1.0
    assert live.iso_to_ms(None) is None
    assert live.iso_to_ms("not-a-date") is None
