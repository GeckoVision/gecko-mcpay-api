"""Light tests for ``ingest_ccxt_funding_universe`` driver.

Stubs ``ccxt_spine.pick_binance_universe`` + ``ccxt_spine.fetch_funding_history``
via monkeypatch so the driver runs end-to-end without touching Binance.
Per ``feedback_lighter_tests``: targeted, no big fixtures, no live-network.

Asserts the contract the carry harness will rely on:
- per-coin file is written at ``OUT_DIR/{SYM}_funding.json`` with the
  shape ``[{ts, fundingRate, premium}]``;
- coverage manifest at ``OUT_DIR/funding_coverage.json`` contains an
  entry per written coin with ``{n, first_ts, last_ts, ann_mean_pct,
  perp_symbol}``;
- per-coin fetch failure → skip that coin, continue with the rest;
- ``--coins`` subset filter narrows the loop without touching the
  cached universe.
"""

from __future__ import annotations

import json
import os
from typing import Any

import pytest

from scripts.calibration import ingest_ccxt_funding_universe as driver


@pytest.fixture
def fake_universe() -> dict:
    return {
        "selected_at": "2026-05-26T00:00:00Z",
        "n": 3,
        "ranking": [
            {
                "symbol": "BTC",
                "perp_symbol": "BTC/USDT:USDT",
                "spot_symbol": "BTC/USDT",
                "vol_quote_24h": 1e10,
            },
            {
                "symbol": "ETH",
                "perp_symbol": "ETH/USDT:USDT",
                "spot_symbol": "ETH/USDT",
                "vol_quote_24h": 5e9,
            },
            {
                "symbol": "SOL",
                "perp_symbol": "SOL/USDT:USDT",
                "spot_symbol": "SOL/USDT",
                "vol_quote_24h": 1e9,
            },
        ],
    }


@pytest.fixture
def patched_driver(monkeypatch, tmp_path, fake_universe):
    """Redirect OUT_DIR to tmp_path and stub the spine to return canned data."""
    out_dir = tmp_path / "funding-binance"
    monkeypatch.setattr(driver, "OUT_DIR", str(out_dir))
    monkeypatch.setattr(driver, "MANIFEST_PATH", str(out_dir / "funding_coverage.json"))

    def fake_pick(n: int = 50, force: bool = False) -> dict:
        return fake_universe

    monkeypatch.setattr(driver.ccxt_spine, "pick_binance_universe", fake_pick)
    return out_dir


def test_writes_per_coin_files_and_manifest(monkeypatch, patched_driver, fake_universe):
    def fake_fetch(venue: str, symbol: str, since_ms: int, end_ms: int | None = None):
        # Synthesize three plausible funding events; venue + symbol traced
        # back to per-coin in the assertions.
        base = since_ms or 1
        return [
            {"ts": base + 0, "fundingRate": 0.00010, "premium": 0.0},
            {"ts": base + 8 * 3600 * 1000, "fundingRate": -0.00005, "premium": 0.0},
            {"ts": base + 16 * 3600 * 1000, "fundingRate": 0.00020, "premium": 0.0},
        ]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_funding_history", fake_fetch)
    manifest = driver.run(days=30, n=3, coin_filter=None, force_universe=False)

    assert manifest["n_coins_written"] == 3
    assert set(manifest["coins"]) == {"BTC", "ETH", "SOL"}
    for sym in ("BTC", "ETH", "SOL"):
        f = patched_driver / f"{sym}_funding.json"
        assert f.exists(), f"missing {f}"
        rows = json.loads(f.read_text())
        assert len(rows) == 3
        assert all("fundingRate" in r and "ts" in r for r in rows)
        # ann_mean_pct = mean(rates) * 3 * 365 * 100 = (0.00010 - 0.00005 + 0.00020)/3 * 1095 * 100
        assert manifest["coins"][sym]["n"] == 3
        assert manifest["coins"][sym]["ann_mean_pct"] == pytest.approx(
            (0.00010 - 0.00005 + 0.00020) / 3 * 1095 * 100, rel=1e-6
        )

    coverage = patched_driver / "funding_coverage.json"
    assert coverage.exists()
    cov = json.loads(coverage.read_text())
    assert cov["venue"] == "binance"
    assert cov["kind"] == "funding"
    assert cov["days_requested"] == 30


def test_per_coin_fetch_error_skips_coin(monkeypatch, patched_driver):
    def flaky_fetch(venue: str, symbol: str, since_ms: int, end_ms: int | None = None):
        if "ETH" in symbol:
            raise RuntimeError("simulated venue timeout")
        return [{"ts": 1, "fundingRate": 0.0001, "premium": 0.0}]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_funding_history", flaky_fetch)
    manifest = driver.run(days=30, n=3, coin_filter=None, force_universe=False)

    # ETH errored → not written; BTC + SOL written
    assert set(manifest["coins"]) == {"BTC", "SOL"}
    assert manifest["n_coins_written"] == 2
    assert not (patched_driver / "ETH_funding.json").exists()
    assert (patched_driver / "BTC_funding.json").exists()
    assert (patched_driver / "SOL_funding.json").exists()


def test_empty_fetch_result_skips_coin(monkeypatch, patched_driver):
    def empty_fetch(venue: str, symbol: str, since_ms: int, end_ms: int | None = None):
        return [] if "SOL" in symbol else [{"ts": 1, "fundingRate": 0.0, "premium": 0.0}]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_funding_history", empty_fetch)
    manifest = driver.run(days=30, n=3, coin_filter=None, force_universe=False)

    assert set(manifest["coins"]) == {"BTC", "ETH"}
    assert not (patched_driver / "SOL_funding.json").exists()


def test_coins_filter_narrows_loop(monkeypatch, patched_driver):
    calls: list[str] = []

    def tracking_fetch(venue: str, symbol: str, since_ms: int, end_ms: int | None = None):
        calls.append(symbol)
        return [{"ts": 1, "fundingRate": 0.0, "premium": 0.0}]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_funding_history", tracking_fetch)
    manifest = driver.run(days=30, n=3, coin_filter=["BTC"], force_universe=False)

    assert calls == ["BTC/USDT:USDT"], "fetch should only be called for filtered coin"
    assert set(manifest["coins"]) == {"BTC"}
    assert manifest["n_coins_written"] == 1
