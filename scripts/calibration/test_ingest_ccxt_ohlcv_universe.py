"""Light tests for ``ingest_ccxt_ohlcv_universe`` driver.

Stubs ``ccxt_spine.pick_binance_universe`` + ``ccxt_spine.fetch_ohlcv`` via
monkeypatch. Same pattern as the funding-ingest test — no live network.

Asserts:
- ``--leg perp,spot`` (default) writes both per-coin files + both manifests;
- ``--leg perp`` writes only perp files / perp manifest;
- per-coin fetch error skips that coin for that leg, continues on the others;
- ``--coins`` subset filter narrows the loop;
- output rows preserve the OHLCV shape (open/high/low/close/volume).
"""

from __future__ import annotations

import json
import os

import pytest

from scripts.calibration import ingest_ccxt_ohlcv_universe as driver


@pytest.fixture
def fake_universe() -> dict:
    return {
        "selected_at": "2026-05-26T00:00:00Z",
        "n": 2,
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
        ],
    }


@pytest.fixture
def patched_driver(monkeypatch, tmp_path, fake_universe):
    """Redirect LEG_TO_DIR entries to tmp_path subdirs and stub the spine."""
    perp_dir = tmp_path / "perp-binance"
    spot_dir = tmp_path / "spot-binance"
    monkeypatch.setattr(
        driver,
        "LEG_TO_DIR",
        {"perp": str(perp_dir), "spot": str(spot_dir)},
    )

    def fake_pick(n: int = 50, force: bool = False) -> dict:
        return fake_universe

    monkeypatch.setattr(driver.ccxt_spine, "pick_binance_universe", fake_pick)
    return perp_dir, spot_dir


def _ohlcv_row(ts: int, close: float) -> dict:
    return {"ts": ts, "open": close, "high": close, "low": close, "close": close, "volume": 1.0}


def test_default_legs_writes_perp_and_spot(monkeypatch, patched_driver, fake_universe):
    perp_dir, spot_dir = patched_driver

    def fake_fetch(venue: str, symbol: str, timeframe: str, since_ms: int, end_ms=None):
        return [_ohlcv_row(since_ms or 1, 100.0), _ohlcv_row((since_ms or 1) + 14400000, 101.0)]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_ohlcv", fake_fetch)
    manifests = driver.run(
        days=30, timeframe="4h", n=2, coin_filter=None, legs=["perp", "spot"]
    )

    for leg, base_dir in (("perp", perp_dir), ("spot", spot_dir)):
        assert manifests[leg]["n_coins_written"] == 2
        for sym in ("BTC", "ETH"):
            f = base_dir / f"{sym}_{leg}.json"
            assert f.exists()
            rows = json.loads(f.read_text())
            assert all({"ts", "open", "high", "low", "close", "volume"} <= set(r) for r in rows)
        manifest_file = base_dir / f"{leg}_coverage.json"
        assert manifest_file.exists()
        m = json.loads(manifest_file.read_text())
        assert m["kind"] == f"{leg}_ohlcv"
        assert m["timeframe"] == "4h"


def test_single_leg_only_writes_that_leg(monkeypatch, patched_driver):
    perp_dir, spot_dir = patched_driver

    def fake_fetch(venue: str, symbol: str, timeframe: str, since_ms: int, end_ms=None):
        return [_ohlcv_row(since_ms or 1, 50.0)]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_ohlcv", fake_fetch)
    manifests = driver.run(days=30, timeframe="4h", n=2, coin_filter=None, legs=["perp"])

    assert set(manifests) == {"perp"}
    assert (perp_dir / "BTC_perp.json").exists()
    assert (perp_dir / "ETH_perp.json").exists()
    # spot leg was not requested → its file shouldn't exist (the spot
    # directory may not even have been created since fetch wasn't called)
    assert not (spot_dir / "BTC_spot.json").exists()
    assert not (spot_dir / "spot_coverage.json").exists()


def test_per_coin_fetch_error_skips_that_coin_for_that_leg(monkeypatch, patched_driver):
    perp_dir, spot_dir = patched_driver

    def flaky_fetch(venue: str, symbol: str, timeframe: str, since_ms: int, end_ms=None):
        if venue == "binance_spot" and "ETH" in symbol:
            raise RuntimeError("simulated spot error on ETH")
        return [_ohlcv_row(since_ms or 1, 1.0)]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_ohlcv", flaky_fetch)
    manifests = driver.run(
        days=30, timeframe="4h", n=2, coin_filter=None, legs=["perp", "spot"]
    )

    assert manifests["perp"]["n_coins_written"] == 2  # both ETH + BTC on perp
    assert manifests["spot"]["n_coins_written"] == 1  # ETH spot errored
    assert "ETH" not in manifests["spot"]["coins"]
    assert (spot_dir / "BTC_spot.json").exists()
    assert not (spot_dir / "ETH_spot.json").exists()
    assert (perp_dir / "BTC_perp.json").exists()
    assert (perp_dir / "ETH_perp.json").exists()


def test_coins_filter_narrows_loop(monkeypatch, patched_driver):
    perp_dir, _ = patched_driver
    calls: list[tuple] = []

    def tracking_fetch(venue: str, symbol: str, timeframe: str, since_ms: int, end_ms=None):
        calls.append((venue, symbol))
        return [_ohlcv_row(since_ms or 1, 1.0)]

    monkeypatch.setattr(driver.ccxt_spine, "fetch_ohlcv", tracking_fetch)
    manifests = driver.run(days=30, timeframe="4h", n=2, coin_filter=["BTC"], legs=["perp"])

    # Only BTC perp should have been requested
    assert calls == [("binance_perp", "BTC/USDT:USDT")]
    assert set(manifests["perp"]["coins"]) == {"BTC"}


def test_unknown_leg_raises_value_error(patched_driver):
    # Direct call into _symbol_for_leg to exercise the validation branch
    # without spinning the whole driver.
    with pytest.raises(ValueError, match="unknown leg"):
        driver._symbol_for_leg({"perp_symbol": "x", "spot_symbol": "y"}, "futures")
