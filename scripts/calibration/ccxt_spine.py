#!/usr/bin/env python3
"""ccxt research-only data spine for the universe-carry pre-reg.

Read-only adapter over ccxt's unified API for funding + OHLCV across major
CEX venues (Binance, OKX, Bybit, Hyperliquid). Handles pagination, dedup,
gap-detection, and frozen-on-first-call universe selection.

Sprint 0.5 scope per ``private/strategy/2026-05-26-quant-program-of-work-review.md``
§6 — research/backtest only. **Do NOT import this from ``packages/gecko-core``**
or any runtime Oracle path. Runtime ccxt adoption is deferred per §4 item 15;
when an Oracle voice eventually depends on live CEX features (orderbook /
recent trades / live funding) that's a separate decision routed to
``staff-engineer``.

Why this exists
---------------
The frozen universe-carry pre-reg (``private/strategy/2026-05-26-carry-universe-prereg.md``)
needs Binance USDT-perp funding + perp 4h OHLCV + paired USDT-spot 4h OHLCV
across a 50-coin universe over the deepest history Binance public endpoints
will give us. The existing HL ingestion scripts (``ingest_hyperliquid_{funding,perp}.py``)
talk to the Hyperliquid info API directly with ``urllib``; this module gives the
Binance equivalent without writing per-venue boilerplate by leaning on ccxt's
unified API.

Outputs
-------
* ``data/binance_universe.json`` — frozen universe (selected_at, ranking).
* (driven by the ingest scripts) ``data/funding/binance/{SYM}_funding.json``,
  ``data/perp/binance/{SYM}_perp.json``, ``data/spot/binance/{SYM}_spot.json``.

Quick checks
------------
* ``python scripts/calibration/ccxt_spine.py --status``
    Print ccxt version + available venue ids this module wires up.
* ``python scripts/calibration/ccxt_spine.py --pick-universe --n 50``
    Materialise / refresh the frozen Binance universe. ``--force`` to overwrite.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import time
from typing import Any, Iterable

import ccxt

# ── Layout ────────────────────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(_HERE, "data")
UNIVERSE_PATH = os.path.join(DATA_DIR, "binance_universe.json")

# ── Venue id map ──────────────────────────────────────────────────────
# Logical name -> (ccxt id, default_type). For Binance we want the futures
# (USDT-margined perps) for funding + perp candles AND the spot exchange for
# the paired USDT spot candles. ccxt exposes these as two separate exchange
# objects; users of this module pick which by passing the logical name.
VENUE_IDS: dict[str, dict[str, Any]] = {
    "binance_perp": {"id": "binanceusdm", "options": {"defaultType": "future"}},
    "binance_spot": {"id": "binance", "options": {"defaultType": "spot"}},
    "okx_perp": {"id": "okx", "options": {"defaultType": "swap"}},
    "okx_spot": {"id": "okx", "options": {"defaultType": "spot"}},
    "bybit_perp": {"id": "bybit", "options": {"defaultType": "swap"}},
    "hyperliquid": {"id": "hyperliquid", "options": {}},
}

# Pagination + politeness defaults. Binance USDT-margined funding caps at 1000
# records per call (~333d at 8h cadence). OHLCV caps at 1500 candles per call
# (~250d at 4h). ccxt's per-venue rate limiter handles throttling when
# enableRateLimit=True is set on the instance.
_FUNDING_LIMIT = 1000
_OHLCV_LIMIT = 1500
_POLITENESS_SEC = 0.15  # extra sleep beyond ccxt's built-in rate-limit pacing

# Cache of constructed venue objects so repeated calls in the same process
# reuse one ccxt instance + its internal market metadata.
_VENUE_CACHE: dict[str, ccxt.Exchange] = {}


# ── Pure helpers (network-free; safe to unit-test directly) ───────────
def _dedup_by_ts(rows: Iterable[dict], ts_key: str = "ts") -> list[dict]:
    """Return ``rows`` sorted ascending by ``ts_key`` with duplicate timestamps
    coalesced (later occurrence wins). Pure function, no I/O."""
    by_ts: dict[int, dict] = {}
    for r in rows:
        t = r.get(ts_key)
        if not isinstance(t, (int, float)):
            continue
        by_ts[int(t)] = r
    return [by_ts[t] for t in sorted(by_ts)]


def paginate_windows(
    since_ms: int, end_ms: int, window_ms: int
) -> list[tuple[int, int]]:
    """Generate consecutive ``(start_ms, end_ms)`` windows covering
    ``[since_ms, end_ms]``. The last window is clamped so end <= end_ms.
    Pure function; useful for time-windowed paginated APIs.

    >>> paginate_windows(0, 100, 30)
    [(0, 30), (30, 60), (60, 90), (90, 100)]
    """
    if window_ms <= 0 or end_ms <= since_ms:
        return []
    out: list[tuple[int, int]] = []
    cur = since_ms
    while cur < end_ms:
        nxt = min(cur + window_ms, end_ms)
        out.append((cur, nxt))
        cur = nxt
    return out


def detect_gaps(
    rows: list[dict], ts_key: str = "ts", expected_step_ms: int | None = None
) -> list[dict]:
    """Detect time gaps in an ascending-by-ts row list. Returns a list of
    ``{"after": ts, "before": ts, "missing_steps": int}``. Caller supplies
    the expected sampling cadence; if not given, gaps are calculated using
    the modal step in the data (no gap reported when only one step exists).

    Honest about its limits: detects *positive* gaps only — overlap /
    out-of-order rows should be dropped via :func:`_dedup_by_ts` first.
    """
    if len(rows) < 2:
        return []
    ts = [int(r[ts_key]) for r in rows if ts_key in r]
    diffs = [ts[i + 1] - ts[i] for i in range(len(ts) - 1)]
    if expected_step_ms is None:
        # Use modal step
        from collections import Counter

        c = Counter(diffs)
        if not c:
            return []
        expected_step_ms = c.most_common(1)[0][0]
    if expected_step_ms <= 0:
        return []
    gaps: list[dict] = []
    for i, d in enumerate(diffs):
        if d > expected_step_ms * 1.5:  # 50% over modal = real gap
            gaps.append(
                {
                    "after": ts[i],
                    "before": ts[i + 1],
                    "missing_steps": d // expected_step_ms - 1,
                    "duration_ms": d,
                }
            )
    return gaps


# ── Venue construction (lazy + cached) ────────────────────────────────
def _venue(name: str) -> ccxt.Exchange:
    """Return a cached ccxt instance for ``name`` (one of VENUE_IDS keys).

    The instance has ``enableRateLimit=True`` so ccxt's built-in pacing
    applies; we still add a tiny extra sleep between paginated calls
    (``_POLITENESS_SEC``) to stay well under venue limits even with
    multiple harnesses running.
    """
    if name in _VENUE_CACHE:
        return _VENUE_CACHE[name]
    spec = VENUE_IDS.get(name)
    if spec is None:
        raise ValueError(f"unknown venue {name!r}; known: {sorted(VENUE_IDS)}")
    cls = getattr(ccxt, spec["id"])
    inst = cls(
        {
            "enableRateLimit": True,
            "options": spec.get("options", {}),
        }
    )
    _VENUE_CACHE[name] = inst
    return inst


# ── Universe selection ────────────────────────────────────────────────
def pick_binance_universe(n: int = 50, force: bool = False) -> dict:
    """Return the frozen Binance USDT-perp universe; pick it on first call.

    Selection rule per the pre-reg: top ``n`` USDT-margined perpetuals by
    24h-quote-volume that ALSO have a USDT spot pair active (needed for
    realistic basis tracking). Frozen result is cached to
    ``data/binance_universe.json`` and never re-picked unless ``force=True``.

    Returns the universe dict (also written to disk). Shape::

        {
            "selected_at": "2026-05-26T...Z",
            "n": 50,
            "ranking": [
                {"symbol": "BTC", "perp_symbol": "BTC/USDT:USDT",
                 "spot_symbol": "BTC/USDT", "vol_quote_24h": 12345.6},
                ...
            ],
        }

    The harness MUST treat this cached selection as immutable for the rest
    of the pre-reg's life — survivorship bias is acknowledged in the
    finding-doc caveats, not engineered away.
    """
    if not force and os.path.exists(UNIVERSE_PATH):
        with open(UNIVERSE_PATH) as f:
            return json.load(f)
    perp = _venue("binance_perp")
    spot = _venue("binance_spot")
    perp.load_markets()
    spot.load_markets()
    # Build symbol sets we can intersect: perp must be 'BTC/USDT:USDT'-style,
    # spot must be 'BTC/USDT'. coin-id = the base from either.
    perp_by_base: dict[str, str] = {}
    for sym, m in perp.markets.items():
        if not m.get("active"):
            continue
        if not m.get("swap") and m.get("type") != "swap":
            continue
        if m.get("quote") != "USDT":
            continue
        base = m.get("base")
        if not base:
            continue
        perp_by_base[base] = sym
    spot_bases: set[str] = set()
    for sym, m in spot.markets.items():
        if not m.get("active"):
            continue
        if m.get("type") != "spot":
            continue
        if m.get("quote") != "USDT":
            continue
        base = m.get("base")
        if base:
            spot_bases.add(base)
    common = sorted(set(perp_by_base) & spot_bases)
    # Get 24h tickers for the common-set perps, sort by quoteVolume desc.
    tickers = perp.fetch_tickers([perp_by_base[b] for b in common])
    ranked: list[dict] = []
    for base in common:
        psym = perp_by_base[base]
        t = tickers.get(psym) or {}
        qv = t.get("quoteVolume")
        if not isinstance(qv, (int, float)):
            continue
        ranked.append(
            {
                "symbol": base,
                "perp_symbol": psym,
                "spot_symbol": f"{base}/USDT",
                "vol_quote_24h": float(qv),
            }
        )
    ranked.sort(key=lambda r: -r["vol_quote_24h"])
    top = ranked[:n]
    universe = {
        "selected_at": dt.datetime.utcnow().isoformat() + "Z",
        "n": len(top),
        "ranking": top,
    }
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(UNIVERSE_PATH, "w") as f:
        json.dump(universe, f, indent=2)
    return universe


# ── Network: funding history ──────────────────────────────────────────
def fetch_funding_history(
    venue_name: str, symbol: str, since_ms: int, end_ms: int | None = None
) -> list[dict]:
    """Paginated funding history for ``symbol`` on ``venue_name``, covering
    ``[since_ms, end_ms or now]``.

    Returns rows shaped like the HL ingest output (so downstream carry
    harnesses can read either source the same way)::

        [{"ts": ms, "fundingRate": float, "premium": float}, ...]

    ascending by ts, deduped. ``premium`` is the venue-reported funding-rate
    premium when ccxt surfaces it under ``info`` (Binance does as
    ``estimatedSettlePrice`` / ``markPrice`` differential); otherwise 0.0.

    The caller is responsible for choosing the venue (``binance_perp``,
    ``okx_perp``, ``bybit_perp``, or ``hyperliquid``); pagination respects
    ccxt's per-call ``_FUNDING_LIMIT`` and the venue's modal funding cadence
    inferred from the first returned page.
    """
    end_ms = end_ms or int(time.time() * 1000)
    if since_ms >= end_ms:
        return []
    venue = _venue(venue_name)
    if not getattr(venue, "has", {}).get("fetchFundingRateHistory", False):
        raise RuntimeError(
            f"venue {venue_name!r} ({venue.id}) does not advertise "
            "fetchFundingRateHistory in ccxt; use a venue-specific ingester."
        )
    rows: list[dict] = []
    cursor = since_ms
    while cursor < end_ms:
        try:
            page = venue.fetch_funding_rate_history(
                symbol, since=cursor, limit=_FUNDING_LIMIT
            )
        except Exception as exc:
            print(
                f"  {venue_name}/{symbol}: page error at {cursor} "
                f"({type(exc).__name__}: {exc}); skipping window"
            )
            # Advance by 30d on error so a single bad page doesn't deadlock the run.
            cursor += 30 * 86_400_000
            continue
        if not page:
            break
        for r in page:
            t = r.get("timestamp")
            if not isinstance(t, (int, float)):
                continue
            rate = r.get("fundingRate")
            if rate is None:
                # Some venues key the rate under info; ccxt normalises to top-level
                # fundingRate for most. Fall through to 0 if truly absent.
                info = r.get("info") or {}
                rate = info.get("fundingRate") or info.get("lastFundingRate") or 0
            try:
                rate_f = float(rate)
            except (TypeError, ValueError):
                rate_f = 0.0
            # Premium: Binance USDM exposes index vs mark via info; we
            # report 0.0 when the venue doesn't surface it cleanly. Carry
            # harness can recompute basis from spot+perp OHLCV separately.
            info = r.get("info") or {}
            premium = 0.0
            try:
                premium = float(
                    info.get("premium")
                    or info.get("estimatedSettlePrice")
                    or info.get("premiumIndex")
                    or 0
                )
            except (TypeError, ValueError):
                pass
            rows.append({"ts": int(t), "fundingRate": rate_f, "premium": premium})
        # Advance cursor past the last returned ts so the next call doesn't
        # re-fetch the same window. +1ms guarantees forward progress on
        # exact-ts boundary cases.
        last_ts = int(page[-1].get("timestamp") or cursor)
        cursor = max(last_ts + 1, cursor + 1)
        time.sleep(_POLITENESS_SEC)
    return _dedup_by_ts(rows)


# ── Network: OHLCV ────────────────────────────────────────────────────
def fetch_ohlcv(
    venue_name: str,
    symbol: str,
    timeframe: str,
    since_ms: int,
    end_ms: int | None = None,
) -> list[dict]:
    """Paginated OHLCV for ``symbol`` on ``venue_name`` at ``timeframe``.

    Returns rows shaped to play with the HL perp ingest output (``ts`` +
    ``close``) but extended with the rest of the OHLCV bar so spot+perp
    basis tracking has open/high/low/volume available::

        [{"ts": ms, "open": ., "high": ., "low": ., "close": ., "volume": .}, ...]

    ascending by ts, deduped. Timeframe strings are ccxt-standard
    (``"1m"`` / ``"5m"`` / ``"15m"`` / ``"1h"`` / ``"4h"`` / ``"1d"``).
    """
    end_ms = end_ms or int(time.time() * 1000)
    if since_ms >= end_ms:
        return []
    venue = _venue(venue_name)
    if not getattr(venue, "has", {}).get("fetchOHLCV", False):
        raise RuntimeError(
            f"venue {venue_name!r} ({venue.id}) does not advertise fetchOHLCV"
        )
    rows: list[dict] = []
    cursor = since_ms
    while cursor < end_ms:
        try:
            page = venue.fetch_ohlcv(
                symbol, timeframe=timeframe, since=cursor, limit=_OHLCV_LIMIT
            )
        except Exception as exc:
            print(
                f"  {venue_name}/{symbol} ({timeframe}): page error at {cursor} "
                f"({type(exc).__name__}: {exc}); skipping window"
            )
            cursor += 30 * 86_400_000
            continue
        if not page:
            break
        for bar in page:
            # ccxt OHLCV: [timestamp, open, high, low, close, volume]
            if not bar or len(bar) < 6:
                continue
            ts = bar[0]
            if not isinstance(ts, (int, float)):
                continue
            try:
                rows.append(
                    {
                        "ts": int(ts),
                        "open": float(bar[1]) if bar[1] is not None else 0.0,
                        "high": float(bar[2]) if bar[2] is not None else 0.0,
                        "low": float(bar[3]) if bar[3] is not None else 0.0,
                        "close": float(bar[4]) if bar[4] is not None else 0.0,
                        "volume": float(bar[5]) if bar[5] is not None else 0.0,
                    }
                )
            except (TypeError, ValueError):
                continue
        last_ts = int(page[-1][0] or cursor)
        cursor = max(last_ts + 1, cursor + 1)
        time.sleep(_POLITENESS_SEC)
    return _dedup_by_ts(rows)


# ── CLI ───────────────────────────────────────────────────────────────
def _print_status() -> None:
    print(f"ccxt {ccxt.__version__}")
    print("wired venues:")
    for name, spec in VENUE_IDS.items():
        has_cls = hasattr(ccxt, spec["id"])
        print(f"  {name:14s} -> ccxt.{spec['id']:<14s} {'OK' if has_cls else 'MISSING'}")


def _cli() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true", help="Print ccxt + venue inventory and exit")
    ap.add_argument(
        "--pick-universe", action="store_true", help="Materialise the frozen Binance universe"
    )
    ap.add_argument("--n", type=int, default=50, help="Universe size for --pick-universe")
    ap.add_argument(
        "--force",
        action="store_true",
        help="With --pick-universe, overwrite the cached universe file",
    )
    a = ap.parse_args()
    if a.status:
        _print_status()
        return
    if a.pick_universe:
        u = pick_binance_universe(n=a.n, force=a.force)
        print(f"universe (n={u['n']}, selected_at={u['selected_at']}):")
        for r in u["ranking"]:
            print(
                f"  {r['symbol']:8s} perp={r['perp_symbol']:18s} "
                f"spot={r['spot_symbol']:14s} vol24h_usdt={r['vol_quote_24h']:>20,.0f}"
            )
        print(f"\nwrote {UNIVERSE_PATH}")
        return
    ap.print_help()


if __name__ == "__main__":
    _cli()
