"""based.bid GeckoTerminal feed — shape + ordering + drop-forming. Mocked, no network."""

from __future__ import annotations

import sys
from pathlib import Path

_CB = Path(__file__).resolve().parents[1]
if str(_CB) not in sys.path:
    sys.path.insert(0, str(_CB))

from strategies.basedbid_feed import BasedBidCandleProvider  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        pass


class _FakeClient:
    """Routes /pools (pool list) vs /ohlcv (candles); counts calls for cache tests."""

    def __init__(self, pool_addr="POOL1", ohlcv=None, no_pool=False):
        self.pool_addr = pool_addr
        self.ohlcv = ohlcv or []
        self.no_pool = no_pool
        self.calls = {"pools": 0, "ohlcv": 0}

    def get(self, url, headers=None, timeout=None):
        if "/ohlcv/" in url:
            self.calls["ohlcv"] += 1
            return _Resp({"data": {"attributes": {"ohlcv_list": self.ohlcv}}})
        self.calls["pools"] += 1
        data = [] if self.no_pool else [{"attributes": {"address": self.pool_addr}}]
        return _Resp({"data": data})


# GeckoTerminal returns DESCENDING (newest first): [ts, o, h, l, c, vol_usd]
_DESC = [
    [300, 3.0, 3.2, 2.9, 3.1, 900.0],   # newest = forming
    [200, 2.0, 2.5, 1.9, 2.4, 800.0],
    [100, 1.0, 1.5, 0.9, 1.4, 700.0],   # oldest
]


def test_candles_ascending_and_drop_forming():
    p = BasedBidCandleProvider(http_client=_FakeClient(ohlcv=_DESC))
    c = p.get_candles("MINT", bar="5m", limit=3, drop_forming=True)
    assert [r["ts"] for r in c] == [100.0, 200.0]  # ascending, newest(300)=forming dropped
    assert c[0]["open"] == 1.0 and c[-1]["close"] == 2.4


def test_keeps_forming_when_not_dropped():
    p = BasedBidCandleProvider(http_client=_FakeClient(ohlcv=_DESC))
    c = p.get_candles("MINT", bar="5m", limit=3, drop_forming=False)
    assert [r["ts"] for r in c] == [100.0, 200.0, 300.0]
    assert c[-1]["confirm"] == 0  # newest marked forming


def test_candle_shape_matches_okx():
    p = BasedBidCandleProvider(http_client=_FakeClient(ohlcv=_DESC))
    r = p.get_candles("MINT", drop_forming=False)[0]
    assert set(r) == {"ts", "open", "high", "low", "close", "volume", "vol_usd", "confirm"}
    assert r["vol_usd"] == 700.0  # GeckoTerminal volume is already USD


def test_no_pool_returns_empty():
    fc = _FakeClient(no_pool=True)
    p = BasedBidCandleProvider(http_client=fc)
    assert p.get_candles("PREGRAD_MINT") == []
    assert fc.calls["ohlcv"] == 0  # never fetched ohlcv without a pool


def test_pool_resolution_is_cached():
    fc = _FakeClient(ohlcv=_DESC)
    p = BasedBidCandleProvider(http_client=fc)
    p.get_candles("MINT")
    p.get_candles("MINT")
    assert fc.calls["pools"] == 1  # resolved once, cached


def test_price_info_from_last_close():
    p = BasedBidCandleProvider(http_client=_FakeClient(ohlcv=_DESC))
    pi = p.get_price_info("MINT")
    assert pi["data"]["price"] == 3.1  # newest close (drop_forming=False in get_price_info)
