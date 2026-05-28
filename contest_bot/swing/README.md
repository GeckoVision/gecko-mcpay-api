# Swing track — Sprint 16

Per the 2026-05-28 two-specialist joint review (quant + trading-strategist):

> The 5m/12h scalp class is falsified across 25 trades. Don't tune the entry
> window inside the wrong class. Pivot to the 4h/5d swing class validated by
> Sprint 9 trend_adx_30 (+1.82%/trade in-sample, +17%/mo gross).

This dir is the new home for the swing-class executor. **Day 1 = signal logger only** (no execution). Phase 2 promotes to swap-executor once we see signals fire as backtest predicted.

## Day-1 deliverable: `swing_signal_logger.py`

A standalone Python loop that:

1. Polls 4h candles for the curated universe (DRIFT, FIDA, CHZ, IO, KMNO)
2. Computes the Sprint 9 trend_adx_30 confluence: `ADX>=30 rising + CHOP<=60 + RSI in [35,55] rising + MFI rising`
3. Logs every score to JSONL + stdout (firing or not)
4. Never calls `swap_execute`

State lives in `../../swing_state/` (separate from the scalp bot's `contest_bot/` state).

### Run

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
uv run python contest_bot/swing/swing_signal_logger.py
```

Or in background:

```bash
nohup uv run python contest_bot/swing/swing_signal_logger.py > /tmp/swing_logger.log 2>&1 &
```

### Stop

```bash
pkill -SIGTERM -f swing_signal_logger
# Or by PID — clean shutdown handler logs "exited cleanly"
```

### What you'll see

Per 4h bar per symbol, one JSONL row:

```json
{
  "ts": "2026-05-28T04:00:00+00:00",
  "kind": "swing_score" | "swing_confluence_fire",
  "payload": {
    "symbol": "DRIFT",
    "bar_ts_ms": 1748419200000,
    "bar_close": 0.028401,
    "adx_val": 32.5, "adx_rising": true,
    "chop_val": 48.2, "chop_clear": true,
    "rsi_val": 42.1, "rsi_rising": true, "rsi_in_band": true,
    "mfi_val": 51.7, "mfi_rising": true,
    "adx_above_floor": true,
    "confluence": true,
    "note": "ALL_GATES_PASS"
  }
}
```

When `confluence=true`, stdout shows `🔔 FIRE`. When blocked, stdout shows `•` + the blocker list.

## What it WON'T do (and when it will)

- ❌ Doesn't call `swap_execute` (no execution)
- ❌ Doesn't track positions / PnL (no state beyond per-bar scoring)
- ❌ Doesn't run a dashboard
- ❌ Doesn't post-process exits (TP/SL/trail/timeout)

These come in **Phase 2 = `swing_executor.py`**, gated on:

1. ≥ 7 days of live signal data
2. At least 2-3 confluence fires observed
3. Signal distribution roughly matches Sprint 9 backtest expectations
4. No surprises (e.g., constant fires = rule too loose, zero fires = rule too strict)

Phase 2 then adds: position state, swap_execute (PAPER first), exit logic from Sprint 9 (RSI>70 / ADX cross-down / 5% trail / 5-day timeout), dashboard, artifact log.

## How this relates to the scalp bot

Two bots, two purposes:

| Bot | Purpose | Mode | State |
|---|---|---|---|
| `contest_bot/jto_breakout_gecko_gated_contest_bot.py` (port 8265) | 5m / 12h scalp — FALSIFIED per Sprint 16 joint review | **OBSERVATION_MODE=1** (telemetry only, no swaps) | `contest_bot/` |
| `contest_bot/swing/swing_signal_logger.py` (no port, headless) | 4h / 5d swing — Sprint 9 validated rule | **Signal log only**, no swaps | `swing_state/` |

The scalp bot stays alive in OBSERVATION_MODE for the case-study artifact (we kept it honest enough to keep emitting data we can compare to the swing class). Once swing logger has 7d of live data, we promote to Phase 2 executor.

## Files in this dir

- `swing_signal_logger.py` — Day-1 deliverable (this commit)
- `README.md` — you are here
- Phase 2 (future): `swing_executor.py`, `swing_state.py`, `swing_dashboard.py`

## License

MIT. Built per the rigor stack — same Op-1 default-REJECT discipline. The signal logger IS the gate before the executor; if signals don't fire as predicted, we don't promote.
