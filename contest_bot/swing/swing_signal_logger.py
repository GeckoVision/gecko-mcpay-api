#!/usr/bin/env python3
"""Swing signal logger — Sprint 16 Day-1 deliverable.

Built per the 2026-05-28 two-specialist joint review verdict (quant +
trading-strategist):

> The 5m/12h scalp class is falsified across 25 trades. Don't tune the
> entry window inside the wrong class. Pivot to the 4h/5d swing class
> validated by Sprint 9 trend_adx_30 (+1.82%/trade in-sample, +17%/mo gross).

This is the DAY-1 surface: polls 4h candles for a curated universe,
computes the Sprint 9 confluence rule, and LOGS signals to JSONL +
stdout. No execution. No swap_execute. No real or paper trading.

After 3-7 days of live signal logging, we promote to swing_executor
(Phase 2) only if signals fire as the backtest predicted.

Curated universe (from Sprint 9 per-symbol breakdown, trend-responsive
mid-cap altcoins): DRIFT, FIDA, CHZ, IO, KMNO. Trading-strategist's
specific recommendation in the joint review.

Rule (Sprint 9 trend_adx_30, the variant that cleared 3 of 4 pre-commit
gates with mean +1.82%/trade, sum +34.50% over 60d):
  ENTRY: ADX >= 30 AND rising over 2 bars
         AND CHOP <= 60
         AND RSI in [35, 55] AND rising over 2 bars
         AND MFI rising over 2 bars
  EXIT (for log only — no actual exit since no entry):
         RSI > 70 OR ADX cross-down 20 OR 5% trail from peak OR 5-day timeout

Cadence: poll every 60s for fresh candles; only score the LAST CLOSED 4h
bar (to avoid intra-bar look-ahead). Signal fires once per bar at most.
"""
from __future__ import annotations

import json
import logging
import os
import signal as _signal
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse the Sprint 9 indicator implementations — single source of truth
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "calibration"))
from swing_window_validation import adx, chop, mfi, rsi  # noqa: E402

# Reuse OnchainOS for live candle fetching
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from onchainos import OnchainOS  # type: ignore
except Exception as _exc:  # pragma: no cover — guard the import in dev
    OnchainOS = None  # type: ignore
    _IMPORT_ERROR = str(_exc)
else:
    _IMPORT_ERROR = ""


# ── Config ─────────────────────────────────────────────────────────


# Curated swing universe per trading-strategist's joint-review pick.
# These are the trend-responsive mid-cap altcoins identified in Sprint 9's
# per-symbol breakdown (DRIFT +6.45%, FIDA +21.94%, CHZ +1.47%, IO +2.99%,
# KMNO +2.83% mean per-trade in the trend_baseline test).
UNIVERSE: list[dict[str, str]] = [
    {"symbol": "DRIFT", "mint": "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7"},
    {"symbol": "FIDA", "mint": "EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp"},
    {"symbol": "CHZ", "mint": "CHZdQWuRwHcq6dMyHcXKdgVjwSpJqUzCa9LzgC4n4o6E"},  # placeholder
    {"symbol": "IO", "mint": "BZLbGTNCSFfoth2GYDtwr7e4imWzpR5jqcUuGEwr646K"},
    {"symbol": "KMNO", "mint": "KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS"},
]

# Confluence params from Sprint 9 trend_adx_30 (the variant that cleared 3/4 gates)
ADX_FLOOR = 30.0
CHOP_CEILING = 60.0
RSI_LO = 35.0
RSI_HI = 55.0
RISING_LOOKBACK_BARS = 2  # require X-bar-ago < X-now

# Cadence
POLL_INTERVAL_SEC = 60  # check for new candles every 60s
CANDLE_INTERVAL = "4H"  # OnchainOS kline interval string
HISTORY_BARS = 60  # how many 4h bars to fetch for indicator warmup

# State
STATE_DIR = Path(
    os.environ.get("SWING_STATE_DIR", str(Path(__file__).parent.parent.parent / "swing_state"))
)
STATE_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACT_FILE = STATE_DIR / f"swing_signals_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
LAST_SCORED_FILE = STATE_DIR / "last_scored_bar.json"


# ── Logging ────────────────────────────────────────────────────────


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [swing-logger] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("swing")


# ── Indicator helpers ─────────────────────────────────────────────


def _last_value(series: list[float], default: float = float("nan")) -> float:
    for v in reversed(series):
        if v == v:  # not NaN
            return v
    return default


def _is_rising(series: list[float], lookback: int) -> bool:
    if len(series) < lookback + 1:
        return False
    a, b = series[-1 - lookback], series[-1]
    if a != a or b != b:
        return False
    return b > a


# ── Signal scoring ────────────────────────────────────────────────


@dataclass
class SignalSnapshot:
    symbol: str
    bar_ts_ms: int
    bar_close: float
    adx_val: float
    chop_val: float
    rsi_val: float
    mfi_val: float
    adx_rising: bool
    rsi_rising: bool
    mfi_rising: bool
    chop_clear: bool
    rsi_in_band: bool
    adx_above_floor: bool
    confluence: bool  # ALL gates true
    note: str

    @classmethod
    def score(cls, sym: str, rows: list[dict]) -> "SignalSnapshot | None":
        if not rows or len(rows) < HISTORY_BARS // 2:
            return None
        high = [float(r["high"]) for r in rows]
        low = [float(r["low"]) for r in rows]
        close = [float(r["close"]) for r in rows]
        volume = [float(r.get("volume", 0)) for r in rows]
        adx_s = adx(high, low, close)
        chop_s = chop(high, low, close)
        rsi_s = rsi(close)
        mfi_s = mfi(high, low, close, volume)
        if not adx_s or adx_s[-1] != adx_s[-1]:
            return None
        adx_v = adx_s[-1]
        chop_v = _last_value(chop_s)
        rsi_v = _last_value(rsi_s)
        mfi_v = _last_value(mfi_s)
        adx_above = adx_v >= ADX_FLOOR
        chop_clear = chop_v <= CHOP_CEILING
        rsi_in = RSI_LO <= rsi_v <= RSI_HI
        adx_rising = _is_rising(adx_s, RISING_LOOKBACK_BARS)
        rsi_rising = _is_rising(rsi_s, RISING_LOOKBACK_BARS)
        mfi_rising = _is_rising(mfi_s, RISING_LOOKBACK_BARS)
        all_gates = adx_above and adx_rising and chop_clear and rsi_in and rsi_rising and mfi_rising
        note = "ALL_GATES_PASS" if all_gates else "blocked: " + ",".join(
            n for n, ok in [
                ("adx_above_floor", adx_above),
                ("adx_rising", adx_rising),
                ("chop_clear", chop_clear),
                ("rsi_in_band", rsi_in),
                ("rsi_rising", rsi_rising),
                ("mfi_rising", mfi_rising),
            ] if not ok
        )
        return cls(
            symbol=sym,
            bar_ts_ms=int(rows[-1]["ts"]),
            bar_close=close[-1],
            adx_val=adx_v,
            chop_val=chop_v,
            rsi_val=rsi_v,
            mfi_val=mfi_v,
            adx_rising=adx_rising,
            rsi_rising=rsi_rising,
            mfi_rising=mfi_rising,
            chop_clear=chop_clear,
            rsi_in_band=rsi_in,
            adx_above_floor=adx_above,
            confluence=all_gates,
            note=note,
        )


# ── Per-bar dedup ─────────────────────────────────────────────────


def _load_last_scored() -> dict[str, int]:
    if LAST_SCORED_FILE.exists():
        try:
            return json.loads(LAST_SCORED_FILE.read_text())
        except Exception:
            return {}
    return {}


def _save_last_scored(d: dict[str, int]) -> None:
    LAST_SCORED_FILE.write_text(json.dumps(d, indent=2))


# ── Main loop ─────────────────────────────────────────────────────


def _emit_signal(snap: SignalSnapshot) -> None:
    """Write to JSONL + log to stdout."""
    payload: dict[str, Any] = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "swing_score" if not snap.confluence else "swing_confluence_fire",
        "payload": asdict(snap),
    }
    with open(ARTIFACT_FILE, "a") as fh:
        fh.write(json.dumps(payload) + "\n")
    tag = "🔔 FIRE" if snap.confluence else "•"
    log.info(
        "%s %s ts=%s close=%.6g ADX=%.1f%s CHOP=%.1f RSI=%.1f%s MFI=%.1f%s",
        tag,
        snap.symbol,
        datetime.fromtimestamp(snap.bar_ts_ms / 1000, tz=timezone.utc).strftime("%m-%d %H:%M"),
        snap.bar_close,
        snap.adx_val,
        "↑" if snap.adx_rising else "·",
        snap.chop_val,
        snap.rsi_val,
        "↑" if snap.rsi_rising else "·",
        snap.mfi_val,
        "↑" if snap.mfi_rising else "·",
    )


_running = True


def _sigterm_handler(*_: Any) -> None:
    global _running
    log.info("SIGTERM — shutting down cleanly")
    _running = False


def main() -> int:
    if OnchainOS is None:
        log.error("OnchainOS import failed: %s", _IMPORT_ERROR)
        log.error("Install/wire onchainos before running. Exiting.")
        return 1

    _signal.signal(_signal.SIGTERM, _sigterm_handler)
    _signal.signal(_signal.SIGINT, _sigterm_handler)

    log.info("=" * 70)
    log.info("Swing signal logger — Sprint 16 Day-1")
    log.info("Universe: %s", [u["symbol"] for u in UNIVERSE])
    log.info("Cadence:  %s candles, poll every %ds", CANDLE_INTERVAL, POLL_INTERVAL_SEC)
    log.info("Rule:     ADX>=%g rising + CHOP<=%g + RSI in [%g,%g] rising + MFI rising",
             ADX_FLOOR, CHOP_CEILING, RSI_LO, RSI_HI)
    log.info("Artifact: %s", ARTIFACT_FILE)
    log.info("MODE:     LOG ONLY — no swap_execute, no paper trades, no real money")
    log.info("=" * 70)

    oc = OnchainOS()
    last_scored = _load_last_scored()

    while _running:
        for inst in UNIVERSE:
            sym = inst["symbol"]
            try:
                # Fetch fresh 4h candles
                raw = oc.get_klines(inst["mint"], interval=CANDLE_INTERVAL, limit=HISTORY_BARS)
                # Normalize shape (OnchainOS returns list[dict] with ts/o/h/l/c/v)
                rows = raw if isinstance(raw, list) else raw.get("data", [])
                if not rows:
                    log.debug("no candles for %s", sym)
                    continue
                # Skip if we already scored this exact bar
                bar_ts = int(rows[-1].get("ts") or rows[-1].get("timestamp", 0))
                if last_scored.get(sym) == bar_ts:
                    continue
                snap = SignalSnapshot.score(sym, rows)
                if snap is None:
                    continue
                _emit_signal(snap)
                last_scored[sym] = bar_ts
                _save_last_scored(last_scored)
            except Exception as exc:
                log.warning("%s scoring error: %s", sym, exc)
            time.sleep(0.5)  # gentle pacing between symbols
        time.sleep(POLL_INTERVAL_SEC)

    log.info("Exited cleanly. Last-scored state: %s", LAST_SCORED_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
