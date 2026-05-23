# Decision-record store

Records **every agent decision** the contest bot makes — all voices + the
indicator snapshot + the (future) market-context slot + the oracle verdict +
the coordinator outcome — tagged by simulation / strategy / agent-group, with
the **realized outcome linked** on position close. The point is to be able to
analyze, backtest, and tune strategies against real recorded decisions instead
of guessing.

## Durability model

Two sinks, in priority order:

1. **Per-run JSONL on disk** — *synchronous, the source of truth.* Every
   decision is appended to `contest_bot/decision_runs/<run_id>/decisions.jsonl`
   the instant it's made. Outcomes are appended later as **immutable patch
   rows** (`{"decision_id": ..., "outcome": {...}}`) — the original decision row
   is never mutated.
2. **MongoDB** — *best-effort, asynchronous-feeling.* Each write also upserts to
   Mongo via `best_effort_upsert`, which **never raises**. If Mongo is down,
   unreachable, or `MONGODB_URI` is unset, the trading loop keeps running and the
   JSONL remains complete. Backfill later with the `sync` CLI.

> The recorder is wired into the bot so that **a recorder fault can never break
> the trading loop** — both the recorder internals (best-effort Mongo) and every
> call site in the bot are wrapped in `try/except` + log.

## On-disk layout

```
contest_bot/decision_runs/
  <run_id>/
    simulation.json     # one SimulationDoc — the run's tags + config
    decisions.jsonl     # one DecisionDoc per line, then outcome patch rows
```

`decision_runs/` is gitignored — it's local telemetry, synced to Mongo.

## Schema

**`simulations`** (one per bot run — `SimulationDoc`):

| field | meaning |
|---|---|
| `run_id` | uuid hex, the join key |
| `strategy_id` | e.g. `jto_breakout` |
| `agent_group` | which voice group ran (`default` today; multi-group is future) |
| `symbol_universe` / `universe_label` | the instruments + a human label (`no-tax-majors`) |
| `config` | floors, caps, tp/sl, entry type |
| `mode` | `paper` \| `live` |
| `code_commit` | short git SHA at boot |
| `started_at` / `ended_at` / `host` | run metadata |

**`decisions`** (one per panel decision — `DecisionDoc`):

| field | meaning |
|---|---|
| `decision_id` | uuid hex, the join key to the outcome |
| `run_id` | FK to the simulation |
| `symbol` / `symbol_group` | instrument + bucket |
| `signal` | the entry primitive that fired (`{fired, type}`) |
| `indicators` | adx / di / rsi / mfi / chop / bb_width / ema_stack / regime + the 3 new distance/slope features (`adx_slope`, `adx_distance`, `chop_distance`) |
| `voices` | per-voice `{name, verdict, confidence, reasoning}` |
| `oracle` | fundamentals verdict `{verdict, confidence, citations, grounded}` or `null` |
| `coordinator` | `{action, rule}` — the final act/decline + the rule that fired |
| `market_context` | **future slot** (#2) — `null` today |
| `candles_ref` | **future slot** — `{window_hash, last_ts, n_bars}` or `null` |
| `outcome` | `null` until close, then the `Outcome` (pnl_pct, pnl_usd, exit_reason, duration_min, entry/exit price, peak_pct) |

## Backfill JSONL → Mongo

Run after Mongo was down, or to seed a fresh Mongo from local runs:

```bash
cd contest_bot
python -m decision_store.sync
```

It folds outcome patch rows onto their decision before upserting, so Mongo gets
one merged document per decision. Set `MONGODB_URI` (and optionally
`MONGODB_DB`, default `gecko`) first; with no URI it no-ops gracefully.

## Querying Mongo

```js
// every decision in a run
db.decisions.find({ run_id: "<run_id>" })

// only the trades that fired and have a realized outcome
db.decisions.find({ "coordinator.action": "act", outcome: { $ne: null } })

// the run's tags
db.simulations.findOne({ run_id: "<run_id>" })
```

## Env tags

The bot reads these at startup to tag the run:

| env | default | effect |
|---|---|---|
| `AGENT_GROUP` | `default` | tags which voice group produced the decisions |
| `UNIVERSE_LABEL` | `no-tax-majors` | human label for the symbol set |
| `MONGODB_URI` | *(unset)* | Mongo sink; unset = JSONL-only |
| `MONGODB_DB` | `gecko` | Mongo database name |
| `GECKO_DECISION_STORE_OFF` | *(unset)* | set to disable the recorder entirely |

Tests run with the recorder armed only via fakes — no live Atlas required.
