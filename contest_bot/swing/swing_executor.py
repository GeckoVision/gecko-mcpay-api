#!/usr/bin/env python3
"""Swing executor — Phase 2 of the swing track (Sprint 19 #1).

Lifts the Sprint 9 trend_adx_30 rule into real PAPER trading. Reuses the
swing_signal_logger's scoring logic + adds:
  - Position state tracking (open / closed) with persistence
  - swap_execute integration (PAPER mode = simulated fills at candle close)
  - Exit logic: RSI > 70 / ADX cross-down 20 / 5% trail from peak / 5-day timeout
  - Artifact log per session (parallel to scalp bot's pattern)

WHY DIFFERENT FROM swing_signal_logger.py:
  The logger ONLY scores + logs. This executor scores, OPENS positions,
  tracks them, and CLOSES on exit triggers. Separate process, separate
  state dir, separate artifact log so neither contaminates the other.

UNIVERSE: DRIFT, FIDA, IO, KMNO (Sprint 9 per-symbol winners — kept distinct
from the scalp bot's PYTH/WIF/RAY universe).

CADENCE: 4h candles, poll every 60s for new bar close.

SIZING: $45 / position (matches scalp bot for consistency).

RULE (Sprint 9 trend_adx_30, the variant that cleared 3/4 pre-commit gates):
  ENTRY (all of):
    - ADX >= 30 AND rising over 2 bars
    - CHOP <= 60
    - RSI in [35, 55] AND rising over 2 bars
    - MFI rising over 2 bars
  EXIT (first of):
    - RSI > 70 (exhaustion)
    - ADX cross-down 20 (trend ending)
    - 5% trail from peak
    - 5-day (30-bar) timeout

PAPER MODE: always. No real money. swap_execute simulated as
fill-at-current-bar-close.

PRE-COMMIT INTERPRETATION (Op-1 discipline, written BEFORE first trade):
  - Sprint 9 backtest predicted ~0.3 fires/day across 5 symbols (~19 trades / 60d).
  - With 4 symbols and similar density: ~0.25 fires/day = ~5 fires/3wk.
  - Verdict gate (after N >= 5 closes):
    - mean per-trade >= +1.5% (matches Sprint 9 trend_adx_30 +1.82%)
    - sharpe per-trade >= 0.20
    - catastrophic-rate (<=-2.5%) <= 10%
  - If pass: confirmed Sprint 9 result holds in live (paper) data
  - If fail: Sprint 9 finding was a backtest artifact; close the swing class
"""
from __future__ import annotations

import json
import logging
import math
import os
import signal as _signal
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Reuse Sprint 9 indicators + the logger's scoring helpers
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts" / "calibration"))
from swing_window_validation import adx, chop, mfi, rsi  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from onchainos import OnchainOS  # type: ignore
except Exception as _exc:
    OnchainOS = None  # type: ignore
    _IMPORT_ERROR = str(_exc)
else:
    _IMPORT_ERROR = ""


# ── Config ─────────────────────────────────────────────────────────


UNIVERSE: list[dict[str, str]] = [
    {"symbol": "DRIFT", "mint": "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7"},
    {"symbol": "FIDA",  "mint": "EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp"},
    {"symbol": "IO",    "mint": "BZLbGTNCSFfoth2GYDtwr7e4imWzpR5jqcUuGEwr646K"},
    {"symbol": "KMNO",  "mint": "KMNo3nJsBXfcpJTVhZcXLW7RmTwTt4GVFE7suUBo9sS"},
]

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USD_PER_TRADE = 45.0

# Confluence — Sprint 9 trend_adx_30
ADX_FLOOR = 30.0
CHOP_CEILING = 60.0
RSI_LO = 35.0
RSI_HI = 55.0
RISING_LOOKBACK_BARS = 2
INDICATOR_PERIOD = 14

# Exit
EXIT_RSI_EXHAUSTED = 70.0
EXIT_ADX_FLOOR = 20.0
TRAIL_PCT = 0.05
TIMEOUT_BARS = 30   # 30 × 4h = 5 days

# Cadence
POLL_INTERVAL_SEC = int(os.environ.get("SWING_EXEC_POLL_SEC", "60"))
CANDLE_INTERVAL = os.environ.get("SWING_EXEC_CANDLE_INTERVAL", "4H")
HISTORY_BARS = int(os.environ.get("SWING_EXEC_HISTORY_BARS", "60"))

# Safety
PAPER_TRADE = os.environ.get("PAPER_TRADE", "true").strip().lower() not in ("false", "0", "no")
MAX_CONCURRENT = int(os.environ.get("SWING_EXEC_MAX_CONCURRENT", "4"))

# State
STATE_DIR = Path(
    os.environ.get("SWING_STATE_DIR",
                   str(Path(__file__).parent.parent.parent / "swing_state"))
)
STATE_DIR.mkdir(parents=True, exist_ok=True)
POSITIONS_FILE = STATE_DIR / "executor_positions.json"
ARTIFACT_FILE = STATE_DIR / f"executor_signals_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"


# ── Logging ────────────────────────────────────────────────────────


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [swing-exec] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("swing-exec")


# ── Position state ─────────────────────────────────────────────────


@dataclass
class Position:
    symbol: str
    mint: str
    entry_ts: str           # ISO UTC
    entry_bar_ts_ms: int    # the 4h bar at entry
    entry_px: float
    units: float            # token units held
    usd_invested: float
    status: str = "open"    # open | closed
    peak_px: float = 0.0
    exit_ts: str | None = None
    exit_bar_ts_ms: int | None = None
    exit_px: float | None = None
    exit_reason: str | None = None
    pnl_pct: float | None = None
    pnl_usd: float | None = None
    bars_held: int = 0
    decision_id: str = ""

    def update_peak(self, price: float) -> None:
        if price > self.peak_px:
            self.peak_px = price


def _load_positions() -> list[Position]:
    if not POSITIONS_FILE.exists():
        return []
    try:
        raw = json.loads(POSITIONS_FILE.read_text())
        return [Position(**p) for p in raw.get("positions", [])]
    except Exception as e:
        log.warning("load_positions failed: %s", e)
        return []


def _save_positions(positions: list[Position]) -> None:
    POSITIONS_FILE.write_text(json.dumps({
        "positions": [asdict(p) for p in positions],
        "saved_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2))


def _emit_artifact(kind: str, payload: dict[str, Any]) -> None:
    row = {"ts": datetime.now(timezone.utc).isoformat(), "kind": kind, "payload": payload}
    with open(ARTIFACT_FILE, "a") as fh:
        fh.write(json.dumps(row, default=str) + "\n")


# ── Confluence + exit helpers ──────────────────────────────────────


def _is_rising(series: list[float], i: int, lookback: int) -> bool:
    if i < lookback:
        return False
    a, b = series[i - lookback], series[i]
    if not (a == a and b == b):
        return False
    return b > a


def fires_entry(rows: list[dict]) -> tuple[bool, dict[str, Any]]:
    """Score the LATEST closed bar. Returns (fires, indicator_snapshot)."""
    if len(rows) < HISTORY_BARS // 2:
        return False, {}
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    close = [r["close"] for r in rows]
    volume = [r["volume"] for r in rows]
    adx_s = adx(high, low, close, INDICATOR_PERIOD)
    chop_s = chop(high, low, close, INDICATOR_PERIOD)
    rsi_s = rsi(close, INDICATOR_PERIOD)
    mfi_s = mfi(high, low, close, volume, INDICATOR_PERIOD)

    i = len(rows) - 1
    if i < INDICATOR_PERIOD:
        return False, {}

    a, ch, r, m = adx_s[i], chop_s[i], rsi_s[i], mfi_s[i]
    if any(x != x for x in (a, ch, r, m)):
        return False, {}

    adx_ok = a >= ADX_FLOOR and _is_rising(adx_s, i, RISING_LOOKBACK_BARS)
    chop_ok = ch <= CHOP_CEILING
    rsi_ok = RSI_LO <= r <= RSI_HI and _is_rising(rsi_s, i, RISING_LOOKBACK_BARS)
    mfi_ok = _is_rising(mfi_s, i, RISING_LOOKBACK_BARS)
    fires = adx_ok and chop_ok and rsi_ok and mfi_ok

    snap = {
        "bar_ts_ms": int(rows[i]["ts"]),
        "bar_close": close[i],
        "adx": round(a, 2),
        "chop": round(ch, 2),
        "rsi": round(r, 2),
        "mfi": round(m, 2),
        "adx_rising": _is_rising(adx_s, i, RISING_LOOKBACK_BARS),
        "rsi_rising": _is_rising(rsi_s, i, RISING_LOOKBACK_BARS),
        "mfi_rising": _is_rising(mfi_s, i, RISING_LOOKBACK_BARS),
        "adx_above_floor": adx_ok,
        "chop_clear": chop_ok,
        "rsi_in_band": rsi_ok,
        "confluence": fires,
    }
    return fires, snap


def fires_exit(rows: list[dict], pos: Position, current_bar_ts_ms: int) -> str | None:
    """Check exit triggers on the latest closed bar."""
    if not rows:
        return None
    close = [r["close"] for r in rows]
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    volume = [r["volume"] for r in rows]
    adx_s = adx(high, low, close, INDICATOR_PERIOD)
    rsi_s = rsi(close, INDICATOR_PERIOD)

    i = len(rows) - 1
    if i < INDICATOR_PERIOD:
        return None

    # Bars held: count 4h bars since entry
    bars_since = sum(1 for r in rows if r["ts"] > pos.entry_bar_ts_ms)
    if bars_since >= TIMEOUT_BARS:
        return "timeout"

    if rsi_s[i] == rsi_s[i] and rsi_s[i] > EXIT_RSI_EXHAUSTED:
        return "rsi_exhausted"

    if (adx_s[i] == adx_s[i] and adx_s[i - 1] == adx_s[i - 1]
        and adx_s[i] < EXIT_ADX_FLOOR and adx_s[i - 1] >= EXIT_ADX_FLOOR):
        return "adx_cross_dn"

    cur_close = close[i]
    if pos.peak_px > 0 and cur_close <= pos.peak_px * (1 - TRAIL_PCT):
        return "trail_stop"

    return None


# ── Position lifecycle ─────────────────────────────────────────────


def _new_decision_id() -> str:
    import uuid
    return uuid.uuid4().hex


def open_position(sym: str, mint: str, snap: dict[str, Any], oc: Any) -> Position | None:
    """PAPER fill at current bar close. No real swap."""
    entry_px = float(snap["bar_close"])
    units = USD_PER_TRADE / entry_px if entry_px > 0 else 0
    if units <= 0:
        log.warning("open_position: zero units for %s @ %f — skipping", sym, entry_px)
        return None

    pos = Position(
        symbol=sym,
        mint=mint,
        entry_ts=datetime.now(timezone.utc).isoformat(),
        entry_bar_ts_ms=int(snap["bar_ts_ms"]),
        entry_px=entry_px,
        units=units,
        usd_invested=USD_PER_TRADE,
        peak_px=entry_px,
        decision_id=_new_decision_id(),
    )
    _emit_artifact("position_open", {
        "symbol": sym,
        "entry_px": entry_px,
        "units": units,
        "usd_invested": USD_PER_TRADE,
        "snapshot": snap,
        "paper": PAPER_TRADE,
        "decision_id": pos.decision_id,
    })
    log.info("🟢 OPEN %s @ %.6g  units=%.4f  invested=$%.2f  ADX=%.1f RSI=%.1f MFI=%.1f",
             sym, entry_px, units, USD_PER_TRADE,
             snap["adx"], snap["rsi"], snap["mfi"])
    return pos


def close_position(pos: Position, current_bar: dict, reason: str) -> None:
    """PAPER close at current bar close."""
    exit_px = float(current_bar["close"])
    pnl_pct = (exit_px / pos.entry_px - 1) * 100 if pos.entry_px > 0 else 0
    # Account for round-trip cost (0.4% same as the backtest)
    pnl_pct_net = pnl_pct - 0.4
    pnl_usd = pos.usd_invested * (pnl_pct_net / 100)

    pos.status = "closed"
    pos.exit_ts = datetime.now(timezone.utc).isoformat()
    pos.exit_bar_ts_ms = int(current_bar["ts"])
    pos.exit_px = exit_px
    pos.exit_reason = reason
    pos.pnl_pct = round(pnl_pct_net, 3)
    pos.pnl_usd = round(pnl_usd, 3)
    pos.bars_held = max(1, (int(current_bar["ts"]) - pos.entry_bar_ts_ms) // (4 * 3600_000))

    _emit_artifact("position_close", {
        "symbol": pos.symbol,
        "entry_px": pos.entry_px,
        "exit_px": exit_px,
        "peak_px": pos.peak_px,
        "exit_reason": reason,
        "pnl_pct": pos.pnl_pct,
        "pnl_usd": pos.pnl_usd,
        "bars_held": pos.bars_held,
        "paper": PAPER_TRADE,
        "decision_id": pos.decision_id,
    })
    icon = "✅" if pos.pnl_pct > 0 else "❌"
    log.info("%s CLOSE %s %s @ %.6g  pnl=%+.2f%% ($%+.2f)  bars=%d  reason=%s",
             icon, pos.symbol, "🟢" if pos.pnl_pct > 0 else "🔴",
             exit_px, pos.pnl_pct, pos.pnl_usd, pos.bars_held, reason)


# ── Main loop ──────────────────────────────────────────────────────


_running = True


def _sigterm_handler(*_: Any) -> None:
    global _running
    log.info("SIGTERM — shutting down cleanly")
    _running = False


def main() -> int:
    if OnchainOS is None:
        log.error("OnchainOS import failed: %s", _IMPORT_ERROR)
        return 1

    _signal.signal(_signal.SIGTERM, _sigterm_handler)
    _signal.signal(_signal.SIGINT, _sigterm_handler)

    log.info("=" * 70)
    log.info("Swing executor — Sprint 19 #1")
    log.info("Universe: %s", [u["symbol"] for u in UNIVERSE])
    log.info("Cadence:  %s, poll every %ds", CANDLE_INTERVAL, POLL_INTERVAL_SEC)
    log.info("Rule:     ADX>=%g rising + CHOP<=%g + RSI in [%g,%g] rising + MFI rising",
             ADX_FLOOR, CHOP_CEILING, RSI_LO, RSI_HI)
    log.info("Exit:     RSI>%g OR ADX cross-down %g OR trail %g%% OR timeout %d bars (%dd)",
             EXIT_RSI_EXHAUSTED, EXIT_ADX_FLOOR, TRAIL_PCT * 100, TIMEOUT_BARS,
             TIMEOUT_BARS * 4 // 24)
    log.info("Size:     $%.2f / position, max %d concurrent", USD_PER_TRADE, MAX_CONCURRENT)
    log.info("Mode:     %s", "PAPER 📄" if PAPER_TRADE else "LIVE 🔴")
    log.info("State:    %s", STATE_DIR)
    log.info("Artifact: %s", ARTIFACT_FILE)
    log.info("=" * 70)

    if not PAPER_TRADE:
        log.error("LIVE mode requires explicit founder approval — refusing to start.")
        log.error("Set PAPER_TRADE=true (default) or remove the override to continue.")
        return 1

    oc = OnchainOS()
    positions = _load_positions()
    log.info("Loaded %d positions from state (%d open)",
             len(positions), sum(1 for p in positions if p.status == "open"))

    while _running:
        for inst in UNIVERSE:
            sym = inst["symbol"]
            mint = inst["mint"]
            try:
                rows = oc.get_candles(mint, bar=CANDLE_INTERVAL, limit=HISTORY_BARS)
                if not rows:
                    continue

                # Find any open position for this symbol
                open_pos = next((p for p in positions if p.status == "open" and p.symbol == sym), None)

                if open_pos is not None:
                    # Update peak from latest bar high
                    open_pos.update_peak(float(rows[-1]["high"]))
                    # Check exits
                    exit_reason = fires_exit(rows, open_pos, int(rows[-1]["ts"]))
                    if exit_reason:
                        close_position(open_pos, rows[-1], exit_reason)
                        _save_positions(positions)
                else:
                    # Check entry — only on a NEW closed bar
                    fires, snap = fires_entry(rows)
                    if fires:
                        open_count = sum(1 for p in positions if p.status == "open")
                        if open_count >= MAX_CONCURRENT:
                            log.info("• %s confluence FIRED but MAX_CONCURRENT (%d) reached — skipped",
                                     sym, MAX_CONCURRENT)
                            _emit_artifact("entry_blocked", {
                                "symbol": sym, "reason": "max_concurrent",
                                "open_count": open_count, "snapshot": snap,
                            })
                        else:
                            new_pos = open_position(sym, mint, snap, oc)
                            if new_pos is not None:
                                positions.append(new_pos)
                                _save_positions(positions)
                    else:
                        # Light heartbeat: log every Nth tick (cheap)
                        pass
            except Exception as exc:
                log.warning("%s loop error: %s", sym, exc)
            time.sleep(0.5)
        time.sleep(POLL_INTERVAL_SEC)

    _save_positions(positions)
    log.info("Exited cleanly. State: %s", POSITIONS_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
