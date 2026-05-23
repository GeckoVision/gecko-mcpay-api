# Decision-Record Store — Design Spec

*2026-05-23. Piece #1 of the "recorded, market-aware, backtestable, multi-strategy"
platform. Brainstormed + approved by the founder. The substrate for agent memory,
behavior analysis, counterfactual backtesting, and (later) auto-calibration —
"answer with data," not just watch the indexes.*

## Goal
Capture **every decision the agent makes** — fully contextualized, tagged by
simulation/strategy/agent-group, with the realized outcome linked — in a structured,
queryable store, so we can:
- analyze our own behavior per strategy/group ("were these good decisions?"),
- **counterfactually backtest** ("how would a stricter / per-group / conservative
  strategy have done last night, on the *same* moments?"),
- answer "too strict or too permissive — with data," and
- feed the agent's long-term memory + a future auto-calibrator.

## The gap this closes (current state)
Today: two flat per-day JSONL files — `eval_telemetry` (per-poll indicators + chart
verdict) and `artifact` (decisions + trades). Insufficient because: (1) **no run /
strategy / agent-group tag** (last night's safe run, the loose experiment, and the
gate-off run all landed in one file); (2) **no market/macro context** per decision;
(3) **partial decision detail** (only the chart voice; not all voices + oracle in one
place); (4) **outcomes separate** from the causing decision; (5) **flat, not
queryable** by strategy/regime/market-state.

## Non-goals (separate specs, later)
- **#2 Market/macro context layer** — wiring OKX market + sentiment + social to fill
  the `market_context` slot. (This spec only *reserves* the slot.)
- **#3 Analysis/backtest layer** — the counterfactual replay engine + the
  too-strict/too-permissive reports. (This spec makes it *possible*; it's built next.)
- **#4 Multi-agent-group runtime** — actually running aggressive/conservative ×
  stable/meme/6-types concurrently. (This spec makes the schema *ready*; the runtime
  is later.)

## Architecture
- **Query store: MongoDB Atlas** (`MONGODB_URI`) — two collections: `simulations`,
  `decisions`. Queryable by strategy/group/regime/market-state; scales to many runs.
- **Durable write path: per-run JSONL.** The bot's hot loop writes each record to
  `contest_bot/decision_runs/<run_id>/decisions.jsonl` (+ `simulation.json`) — always,
  synchronously, no network dependency in the trading loop. Then a **best-effort
  upsert to Mongo** (if reachable). If Mongo is down, JSONL persists and a `sync`
  command backfills later. *The bot never blocks or crashes on Mongo.*
- **Recorder module: `contest_bot/decision_store.py`** — clean, dependency-light,
  promotable to `gecko-core` when the PRD agents need it. Public surface:
  - `SimulationRegistry.start(config) -> run_id` — registers a run (writes
    `simulation.json` + upserts the `simulations` doc).
  - `DecisionRecorder.record(decision_doc) -> decision_id` — writes one decision
    (JSONL append + best-effort Mongo upsert). Immutable.
  - `DecisionRecorder.attach_outcome(decision_id, outcome)` — patches the outcome on
    close (a NEW immutable patch row in JSONL; `$set` in Mongo). Mirrors the existing
    artifact "rows immutable, outcome patches append" pattern.

## Design rationale: store the un-recoverable (founder)
Market data is **re-fetchable** — OKX gives real-time *and* historical candles/depth on
demand. **Our decisions + the agent's reasoning are not** — once a run ends, *why* it
acted or abstained is gone forever. So the store's job is to capture the **un-recoverable**
thing (the full decision + every voice's reasoning), and merely *reference* the candle
window (the approved "lean": `candles_ref`; re-fetch market data when replaying). That
asymmetry — ephemeral decisions vs durable, fetchable market data — is what the whole
design turns on, and it's why we don't bank candle content.

## Data model

**`simulations`** (one per run):
```
run_id          # uuid
strategy_id     # e.g. "jto_breakout" — the strategy identity
agent_group     # "default" now; "aggressive"/"conservative"/… future
symbol_universe # ["PYTH","WIF",…] + a label ("no-tax-majors","meme","stable",…)
config          # full param snapshot: floors, caps, TP/SL/trail, breaker, gate flags
mode            # "paper" | "live"
code_commit     # git SHA
started_at, ended_at, host
```

**`decisions`** (one per decision point, see Granularity):
```
decision_id, run_id, ts, symbol, symbol_group
signal:        { fired: bool, type: "breakout"|"volume_spike", confirm_pct, lookback, … }
indicators:    { adx, plus_di, minus_di, rsi, mfi, chop, bb_width, ema_stack,
                 range_24h_pct,
                 adx_slope, chop_distance, adx_distance }   # ← NEW (founder's distance/slope idea)
market_context: null                                        # ← slot for #2 (OKX market+sentiment+social)
voices:        [ {name, verdict, confidence, reasoning} … ] # ALL voices, full reasoning
oracle:        { verdict, confidence, citations, grounded } | null
coordinator:   { action: "act"|"decline", rule, decline_reason }
candles_ref:   { window_hash, last_ts, n_bars }             # replay reference (candles cached/fetchable)
outcome:       null                                          # ← patched on close
# outcome (when set): { pnl_pct, pnl_usd, exit_reason, duration_min, entry_price, exit_price, peak_pct }
```

**Replay-completeness:** the captured `indicators` + `voices` + `oracle` +
`candles_ref` are enough to re-run an *alternative coordinator / threshold* against the
recorded moments (the #3 counterfactual). Candle windows are cached per run (or
re-fetchable by `last_ts` via the OKX market history) so an alternative *entry*
threshold can also be replayed.

## New indicator features (the founder's "distance" point)
The current code uses point values + thresholds only (ADX≥25, CHOP vs 61.8). This spec
adds three pure-function features to `indicators.py`, captured in every record:
- `adx_slope` — ADX rising vs falling (Δ over the last k bars).
- `adx_distance` — signed margin from the 25/18 thresholds.
- `chop_distance` — signed margin from 61.8 / 38.2.
Each ships with a unit test on synthetic data. (Decorrelated from the point value;
"ADX 26-and-falling" ≠ "ADX 45-and-rising.")

## Bot integration
- On startup: `run_id = SimulationRegistry.start(config_snapshot)`.
- At each **decision point** (a breakout/volume signal fires → coordinator returns
  act/decline): assemble the decision_doc from the already-computed voices + indicators
  + oracle + coordinator result, `DecisionRecorder.record(...)`.
- On `close_position`: `DecisionRecorder.attach_outcome(decision_id, outcome)`.
- The existing `eval_telemetry` / `artifact` logs stay (no removal) — the new store is
  additive and authoritative.

## Granularity
A record per **decision point** (signal fired → act or decline) + the linked outcome.
The ~4,000 no-signal polls/day are NOT recorded (noise). This keeps the store the size
of *decisions*, not *polls*, and is exactly the analyzable unit for too-strict/permissive.

## What it unlocks (preview of #3, not built here)
- Per strategy/group/symbol-group: EV, win-rate, **gating delta** (declined-would-have-won
  = too strict; took-losers = too permissive).
- Counterfactual replay: "how would strategy X / threshold Y have done last night?"
- The data answers "do meme vs stable behave differently → need different strategies?"

## Future-fit
- **Memory:** the store is the long-term-memory substrate the `memory_voice` reads
  (realized outcomes by setup). Short-term memory = the current run's recent decisions.
- **Auto-calibrate (#4):** reads the store → proposes param tweaks within bounds.
- **Multi-group:** the `agent_group` / `symbol_universe` tags + per-run `simulations`
  doc make concurrent strategies first-class; the runtime is later, the schema is ready now.

## Error handling
- Mongo unreachable → JSONL still written (durable); `decision_store sync` backfills.
- Recorder failures NEVER propagate into the trading loop (wrapped, logged, best-effort).
- Records immutable; outcome is a patch (no in-place mutation of the decision).

## Testing
- Unit tests (light fakes, per `feedback_lighter_tests`): `SimulationRegistry.start`
  writes a valid `simulation.json`; `record` appends a schema-valid decision;
  `attach_outcome` patches correctly; Mongo-down path still writes JSONL; the 3 new
  indicator features on synthetic candles. No live Mongo required (a fake/in-memory
  store conformer for the unit tests; one optional integration test against Atlas).

## Build scope (this spec's implementation)
1. `indicators.py`: the 3 distance/slope features + tests.
2. `contest_bot/decision_store.py`: `SimulationRegistry`, `DecisionRecorder`, JSONL +
   best-effort Mongo, the `sync` command, models.
3. Bot integration: start the run, record at decision points, attach outcomes.
4. Tests as above.
Single bot, single `agent_group="default"`; `market_context=null`. Future slots present
but minimally filled.
