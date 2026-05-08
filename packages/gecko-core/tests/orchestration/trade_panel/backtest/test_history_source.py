"""History-source tests (Phase 9 v1).

Two scenarios:

1. **Cache hit** — when ``read_candles`` returns rows, the source
   forwards them and skips the Pyth call entirely.
2. **Cache miss** — empty cache flows into ``_attempt_pyth_fetch``;
   subclassing lets us assert the hook fired and validate the canned
   response shape.

NEVER fire real Pyth requests. The cache-miss test stubs the hook
directly rather than monkeypatching ``httpx``.
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.trade_panel.backtest import Candle, PythHermesHistorySource


@pytest.mark.asyncio
async def test_cache_hit_skips_pyth_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the Mongo cache returns rows, no Pyth fetch is attempted."""
    cached = [
        Candle(
            protocol="jito",
            ts=1_700_000_000,
            granularity="1d",
            source="pyth",
            open=2.5,
            high=2.6,
            low=2.4,
            close=2.55,
        ),
        Candle(
            protocol="jito",
            ts=1_700_086_400,
            granularity="1d",
            source="pyth",
            open=2.55,
            high=2.7,
            low=2.55,
            close=2.65,
        ),
    ]

    async def _fake_read_candles(
        protocol: str, *, granularity: str, ts_start: int, ts_end: int
    ) -> list[Candle]:
        return cached

    # Patch the symbol the module imported, not the original location —
    # `from .storage import read_candles` binds it onto history_source.
    import gecko_core.orchestration.trade_panel.backtest.history_source as hs_mod

    monkeypatch.setattr(hs_mod, "read_candles", _fake_read_candles)

    pyth_calls: list[str] = []

    class _NoPythSource(PythHermesHistorySource):
        async def _attempt_pyth_fetch(
            self, protocol: str, *, granularity, ts_start: int, ts_end: int
        ) -> list[Candle]:
            pyth_calls.append(protocol)
            return []

    source = _NoPythSource()
    out = await source.fetch("jito", granularity="1d", ts_start=1_700_000_000, ts_end=1_700_200_000)
    assert out == cached
    assert pyth_calls == [], "cache hit must not trigger the Pyth attempt"


@pytest.mark.asyncio
async def test_cache_miss_then_pyth_fetch_returns_stubbed_candles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache empty → ``_attempt_pyth_fetch`` is consulted; canned reply forwards through."""

    async def _empty_read_candles(
        protocol: str, *, granularity: str, ts_start: int, ts_end: int
    ) -> list[Candle]:
        return []

    import gecko_core.orchestration.trade_panel.backtest.history_source as hs_mod

    monkeypatch.setattr(hs_mod, "read_candles", _empty_read_candles)

    canned = [
        Candle(
            protocol="jito",
            ts=1_700_000_000,
            granularity="1d",
            source="pyth",
            open=2.0,
            high=2.1,
            low=1.95,
            close=2.05,
        )
    ]

    class _StubPythSource(PythHermesHistorySource):
        async def _attempt_pyth_fetch(
            self, protocol: str, *, granularity, ts_start: int, ts_end: int
        ) -> list[Candle]:
            assert protocol == "jito"
            return list(canned)

    source = _StubPythSource()
    out = await source.fetch("jito", granularity="1d", ts_start=1_700_000_000, ts_end=1_700_200_000)
    assert out == canned
