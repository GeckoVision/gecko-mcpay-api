"""Phase-0 Fix 0.3 — capture volUsd + guard the candle ascending-sort.

Fixture (captured live 2026-05-23, no network at test time):
  tests/fixtures/onchainos_kline_pyth_5m.json — real PYTH 5m kline, each bar
  carrying a volUsd (USD volume) field that the pre-S44 parser discarded.

Fix 0.3a: capture volUsd onto each candle as vol_usd (for RVOL/VWAP later).
Fix 0.3b: the newest-first → ascending sort is load-bearing with no guard.
          Add an explicit assertion (KlineSortError) so a mis-ordered series
          fails loud instead of silently corrupting every indicator.
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
from onchainos import KlineSortError, OnchainOS, _assert_candles_ascending

_FIX = Path(__file__).resolve().parent / "fixtures"


def _kline_fixture() -> dict:
    return json.loads((_FIX / "onchainos_kline_pyth_5m.json").read_text())


@pytest.fixture
def patched_oc(monkeypatch: pytest.MonkeyPatch) -> OnchainOS:
    fixture = _kline_fixture()
    monkeypatch.setattr(oc_mod, "_run_cli", lambda *a, **k: fixture)
    return OnchainOS(chain="solana")


# ── Fix 0.3a: volUsd capture ──────────────────────────────────────────────


def test_real_fixture_carries_vol_usd() -> None:
    """Sanity: the real kline rows carry volUsd."""
    assert all("volUsd" in r for r in _kline_fixture()["data"])


def test_vol_usd_captured(patched_oc: OnchainOS) -> None:
    """volUsd is captured onto each candle as vol_usd (>0 in fixture)."""
    candles = patched_oc.get_candles("PYTH_MINT", "5m", limit=30)
    assert all("vol_usd" in c for c in candles)
    assert any(c["vol_usd"] > 0 for c in candles)
    # Cross-check one bar against the raw fixture (the newest CLOSED bar = raw[1]).
    raw_closed = _kline_fixture()["data"][1]
    assert candles[-1]["vol_usd"] == pytest.approx(float(raw_closed["volUsd"]))


# ── Fix 0.3b: ascending-sort guard ────────────────────────────────────────


def test_output_is_ascending(patched_oc: OnchainOS) -> None:
    """Output is strictly ascending by ts (the load-bearing invariant)."""
    candles = patched_oc.get_candles("PYTH_MINT", "5m", limit=30)
    ts = [c["ts"] for c in candles]
    assert ts == sorted(ts)
    assert all(ts[i] > ts[i - 1] for i in range(1, len(ts)))


def test_scrambled_input_sorted_correctly(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scrambled raw order still yields a correct ascending series out."""
    rows = list(_kline_fixture()["data"])
    scrambled = rows[5:] + rows[:5]  # rotate so order is broken
    monkeypatch.setattr(oc_mod, "_run_cli", lambda *a, **k: {"data": scrambled})
    oc = OnchainOS(chain="solana")
    candles = oc.get_candles("PYTH_MINT", "5m", limit=30)
    ts = [c["ts"] for c in candles]
    assert ts == sorted(ts)


def test_sort_guard_passes_on_ascending() -> None:
    """The guard accepts a correctly-ordered series (no raise)."""
    _assert_candles_ascending([{"ts": 100.0}, {"ts": 200.0}, {"ts": 300.0}])


def test_sort_guard_raises_on_descending() -> None:
    """The guard raises KlineSortError on a non-ascending series — the invariant
    downstream indicators rely on. Tested in isolation (pure helper) so the
    failure mode is covered without disabling Python's builtin sort."""
    with pytest.raises(KlineSortError):
        _assert_candles_ascending([{"ts": 300.0}, {"ts": 200.0}, {"ts": 100.0}])


def test_sort_guard_raises_on_single_inversion() -> None:
    """One mid-series inverted pair must trip the guard."""
    with pytest.raises(KlineSortError):
        _assert_candles_ascending([{"ts": 100.0}, {"ts": 300.0}, {"ts": 200.0}, {"ts": 400.0}])
