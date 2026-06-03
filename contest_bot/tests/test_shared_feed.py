"""Phase-3 shared feed — TTL cache dedup + the okx_feed GECKO_FEED_URL client mode."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from shared_feed import CandleCache  # noqa: E402
from strategies.okx_feed import OkxSpotCandleProvider  # noqa: E402


class _FakeProvider:
    def __init__(self):
        self.candle_calls = 0
        self.price_calls = 0

    def get_candles(self, symbol, bar="5m", limit=210):
        self.candle_calls += 1
        return [{"ts": 1.0, "open": 1, "high": 1, "low": 1, "close": 1, "volume": 1,
                 "vol_usd": 1, "confirm": 1}]

    def get_price_info(self, symbol):
        self.price_calls += 1
        return {"data": {"price": 10.0}}


# ── cache dedup ──────────────────────────────────────────────────────
def test_candle_cache_dedups_within_ttl():
    fp = _FakeProvider()
    c = CandleCache(ttl_sec=45, provider=fp)
    c.get_candles("BTC/USDT", "5m", 210, now=1000.0)
    c.get_candles("BTC/USDT", "5m", 210, now=1010.0)  # within TTL → cached
    c.get_candles("BTC/USDT", "5m", 210, now=1020.0)
    assert fp.candle_calls == 1  # ONE fetch served 3 reads (the whole point)


def test_candle_cache_refetches_after_ttl():
    fp = _FakeProvider()
    c = CandleCache(ttl_sec=45, provider=fp)
    c.get_candles("BTC/USDT", "5m", 210, now=1000.0)
    c.get_candles("BTC/USDT", "5m", 210, now=1100.0)  # past TTL → refetch
    assert fp.candle_calls == 2


def test_candle_cache_keys_by_symbol():
    fp = _FakeProvider()
    c = CandleCache(ttl_sec=45, provider=fp)
    c.get_candles("BTC/USDT", "5m", 210, now=1000.0)
    c.get_candles("ETH/USDT", "5m", 210, now=1000.0)
    assert fp.candle_calls == 2  # different symbols → separate cache entries


def test_price_cache_dedups():
    fp = _FakeProvider()
    c = CandleCache(price_ttl_sec=5, provider=fp)
    c.get_price_info("BTC/USDT", now=1000.0)
    c.get_price_info("BTC/USDT", now=1003.0)  # within price TTL
    assert fp.price_calls == 1


# ── okx_feed GECKO_FEED_URL client mode ──────────────────────────────
def test_okx_feed_client_reads_from_feed(monkeypatch):
    captured = {}

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"candles": [{"ts": 5.0, "open": 1, "high": 2, "low": 1, "close": 2,
                                 "volume": 9, "vol_usd": 18, "confirm": 1}]}

    def fake_get(url, params=None, timeout=None):
        captured["url"] = url
        captured["params"] = params
        return _Resp()

    import httpx

    monkeypatch.setattr(httpx, "get", fake_get)
    p = OkxSpotCandleProvider(feed_url="http://feed:8275")
    rows = p.get_candles("BTC", "5m", 210)
    assert captured["url"] == "http://feed:8275/candles"
    assert captured["params"]["symbol"] == "BTC/USDT"  # symbol resolved before the call
    assert rows[0]["close"] == 2


def test_okx_feed_client_falls_back_to_direct_on_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("feed down")

    import httpx

    monkeypatch.setattr(httpx, "get", boom)
    p = OkxSpotCandleProvider(feed_url="http://feed:8275")

    # direct ccxt path is then taken; stub the exchange so we don't hit the network
    class _X:
        def fetch_ohlcv(self, sym, timeframe="5m", limit=100):
            return [[1000, 1, 2, 1, 2, 9], [1300, 2, 3, 2, 3, 9]]

    p._x = _X()
    rows = p.get_candles("BTC/USDT", "5m", 2, drop_forming=False)
    assert rows and rows[-1]["close"] == 3  # fell back to direct ccxt
