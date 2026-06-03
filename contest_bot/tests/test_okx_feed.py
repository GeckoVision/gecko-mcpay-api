"""Contract test for OkxSpotCandleProvider — no network (fake ccxt exchange).

Asserts the provider matches the OnchainOS get_candles contract that the whole
monolith lifecycle depends on: dict shape, ASCENDING order, forming-bar drop,
mint→symbol alias, and the {"data":{"price"}} price shape.
"""

from __future__ import annotations

import sys
from pathlib import Path

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from strategies.okx_feed import OkxSpotCandleProvider  # noqa: E402


class _FakeOKX:
    """Records the symbol/timeframe it was asked for; returns canned OHLCV."""

    def __init__(self):
        self.last_symbol = None
        self.last_tf = None

    def fetch_ohlcv(self, symbol, timeframe="5m", limit=100):
        self.last_symbol = symbol
        self.last_tf = timeframe
        # ascending [ts_ms, o, h, l, c, v]; last row is the "forming" bar
        return [
            [1_000_000, 10.0, 11.0, 9.0, 10.5, 100.0],
            [1_300_000, 10.5, 12.0, 10.0, 11.5, 120.0],
            [1_600_000, 11.5, 13.0, 11.0, 12.5, 140.0],  # forming (newest)
        ]

    def fetch_ticker(self, symbol):
        self.last_symbol = symbol
        return {"last": 12.34}


def _provider() -> tuple[OkxSpotCandleProvider, _FakeOKX]:
    p = OkxSpotCandleProvider()
    fake = _FakeOKX()
    p._x = fake  # swap the public-data client for the fake
    return p, fake


def test_candles_shape_and_keys():
    p, _ = _provider()
    rows = p.get_candles("BTC/USDT", "5m", limit=3, drop_forming=False)
    assert len(rows) == 3
    for r in rows:
        assert set(r) == {"ts", "open", "high", "low", "close", "volume", "vol_usd", "confirm"}
    assert rows[0]["vol_usd"] == 10.5 * 100.0  # close*volume


def test_candles_ascending_and_drop_forming():
    p, _ = _provider()
    kept = p.get_candles("BTC/USDT", "5m", limit=3, drop_forming=True)
    assert [r["ts"] for r in kept] == [1000.0, 1300.0]  # forming newest dropped; ascending
    assert all(r["confirm"] == 1 for r in kept)


def test_forming_bar_marked_when_kept():
    p, _ = _provider()
    rows = p.get_candles("BTC/USDT", "5m", limit=3, drop_forming=False)
    assert rows[-1]["confirm"] == 0  # the current bar is flagged forming


def test_bar_code_maps_to_ccxt():
    p, fake = _provider()
    p.get_candles("SOL/USDT", "1H", limit=3)
    assert fake.last_tf == "1h"


def test_bare_symbol_gets_usdt_quote():
    p, fake = _provider()
    p.get_candles("SOL", "5m", limit=3)
    assert fake.last_symbol == "SOL/USDT"


def test_btc_mint_alias_resolves_to_okx_symbol():
    p, fake = _provider()
    p.get_candles("3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh", "5m", limit=3)
    assert fake.last_symbol == "BTC/USDT"  # BTC overlay keeps working


def test_price_info_shape():
    p, _ = _provider()
    resp = p.get_price_info("BTC/USDT")
    assert resp == {"data": {"price": 12.34}}


def test_fetch_failure_returns_empty_not_raise():
    p, _ = _provider()

    def boom(*a, **k):
        raise RuntimeError("network down")

    p._x.fetch_ohlcv = boom
    p._max_retries = 1
    assert p.get_candles("BTC/USDT", "5m", limit=3) == []
