"""Phase-0 Fix 0.1 — forming-candle bug: get_candles drops the forming bar.

Fixture (captured live 2026-05-23, no network at test time):
  tests/fixtures/onchainos_kline_pyth_5m.json — 30 PYTH 5m bars, NEWEST-FIRST,
  the newest bar carrying confirm == "0" (still forming, high/close moving).

The bot evaluated breakouts on candles[-1]. After the ascending sort that is
the newest bar — which the CLI marks confirm=0 (forming) → premature breakout
fires that mean-revert. Fix: drop the trailing forming bar at the ingestion
boundary so every consumer reads the last CLOSED bar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

import onchainos as oc_mod
from onchainos import OnchainOS

_FIX = Path(__file__).resolve().parent / "fixtures"


def _kline_fixture() -> dict:
    return json.loads((_FIX / "onchainos_kline_pyth_5m.json").read_text())


@pytest.fixture
def patched_oc(monkeypatch: pytest.MonkeyPatch) -> OnchainOS:
    """OnchainOS whose _run_cli returns the captured kline fixture verbatim."""
    fixture = _kline_fixture()
    monkeypatch.setattr(oc_mod, "_run_cli", lambda *a, **k: fixture)
    return OnchainOS(chain="solana")


def test_real_fixture_has_forming_newest_bar() -> None:
    """Sanity: the captured fixture really is newest-first with a forming bar."""
    rows = _kline_fixture()["data"]
    assert rows[0]["confirm"] == "0", "expected newest bar to be forming (confirm=0)"
    assert int(rows[0]["ts"]) > int(rows[-1]["ts"]), "fixture should be newest-first"


def test_forming_bar_dropped_by_default(patched_oc: OnchainOS) -> None:
    """Fix 0.1: the newest (confirm==0) bar is dropped → candles[-1] is closed."""
    raw_n = len(_kline_fixture()["data"])
    candles = patched_oc.get_candles("PYTH_MINT", "5m", limit=30)
    assert len(candles) == raw_n - 1, "exactly the one forming bar should be dropped"
    assert candles[-1]["confirm"] == 1, "the evaluated newest bar must be CLOSED"


def test_evaluated_bar_is_prior_closed_bar(patched_oc: OnchainOS) -> None:
    """Fix 0.1: the bar a consumer reads as candles[-1] equals the prior CLOSED
    bar (the second-newest in the raw newest-first response)."""
    raw = _kline_fixture()["data"]
    # raw[0] is forming; raw[1] is the newest CLOSED bar.
    expected_closed_ts = float(raw[1]["ts"])
    candles = patched_oc.get_candles("PYTH_MINT", "5m", limit=30)
    assert candles[-1]["ts"] == expected_closed_ts


def test_drop_forming_false_keeps_forming_bar(patched_oc: OnchainOS) -> None:
    """Opt-out path keeps the live bar for real-time reads."""
    raw_n = len(_kline_fixture()["data"])
    candles = patched_oc.get_candles("PYTH_MINT", "5m", limit=30, drop_forming=False)
    assert len(candles) == raw_n
    assert candles[-1]["confirm"] == 0  # forming bar retained, still last (newest)
