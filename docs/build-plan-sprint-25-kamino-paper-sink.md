# Sprint 25 — Kamino USDC Paper Sink (Build Plan)

**Ticket(s):** #117, #141
**Mode:** PAPER ONLY — no real on-chain calls this sprint
**Default state:** `GECKO_KAMINO_PAPER_SINK=0` (OFF). Founder flips per-launcher.
**Bot impact when flag OFF:** zero. Code path is not reached.

---

## 1. Problem framing

The contest_bot closes positions and accumulates realized USDC in its `realized_pnl_today` counter, plus the wallet's static starting balance. That cash sits idle. The only **validated +EV income lane** we have (memory: `project_kamino_lending_validated`; cross-ref Sprint 17 nulls in `project_sprint_17_strategy_class_dead`) is **Kamino USDC lending** in the main market reserve.

Sprint 25 builds the PAPER-mode simulation of that sink so we can:

- Measure the simulated yield on idle USDC against the live Kamino APY
- Validate the auto-deposit / auto-withdraw mechanics on close events without touching mainnet
- Produce a ledger we can audit later against a real-money run

This sprint does NOT execute on-chain. The existing `packages/gecko-core/src/gecko_core/execution/kamino_devnet.py` scaffold (`fetch_unsigned_deposit_tx`) is intentionally **not wired**.

---

## 2. Architecture

```
                 ┌──────────────────────────────┐
   close_position────┤ paper_sink.on_position_close ├──► (deposit if idle > threshold)
                 └──────────────┬───────────────┘
                                │
                                ▼
                ┌────────────────────────────────────┐
                │ KaminoPaperSink (singleton)        │
                │  ── reads idle USDC                │
                │  ── deposits excess over THRESH    │
                │  ── accrues yield via APYCache     │
                │  ── persists via PaperLedger       │
                └──────────────┬────────────────-───┘
                               │
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
    ┌───────────────┐                    ┌────────────────┐
    │ APYCache      │  fetch every 6h    │ PaperLedger    │
    │ (httpx GET)   │──► Kamino API ───► │ JSONL append + │
    │ fallback=0.0  │                    │ in-mem state   │
    └───────────────┘                    └────────────────┘
```

### Fire policy

The sink fires on **two events** (event-driven; no separate scheduler thread to keep the bot loop simple):

1. **On position close** — after `report_close` in `close_position`. The bot just realized PnL; the wallet's idle USDC may have changed. If idle > deposit_threshold, deposit the excess.
2. **On position open** — checked in `bootstrap.py` before `swap_execute`. If the bot needs USDC and the paper-sink holds a position, withdraw the needed amount from Kamino first.

Wire ONLY the close-side this sprint (per the founder's stated wire site near line 2740). The open-side withdrawal stays a documented v2 follow-up; bot won't open more positions while idle is below threshold in practice during the contest cap.

### Thresholds (configurable via env, conservative defaults)

| Env | Default | Meaning |
|---|---|---|
| `GECKO_KAMINO_PAPER_SINK` | `0` | Master flag. Anything but `1` = sink no-op. |
| `GECKO_KAMINO_DEPOSIT_THRESHOLD_USD` | `10.00` | Min idle USDC to trigger a deposit. |
| `GECKO_KAMINO_DEPOSIT_RESERVE_USD` | `5.00` | Always leave this much idle for gas/buffer. |
| `GECKO_KAMINO_APY_TTL_SEC` | `21600` | 6h cache TTL on Kamino APY fetch. |
| `GECKO_KAMINO_APY_FALLBACK` | `0.0` | If API unreachable, accrue at this rate. ZERO by default so we never overstate yield. |
| `GECKO_KAMINO_APY_OVERRIDE` | unset | If set (e.g. `0.0421`), skip API entirely and use this value. Useful for replays + tests. |

### State location

Paper ledger lives at `_STATE_BASE / kamino_paper_ledger.jsonl` (`_STATE_BASE` is the contest_bot's `GECKO_STATE_DIR`, so it parallels the existing `artifact_*.jsonl` / `poll_telemetry_*.jsonl` family — no special path).

In-memory state (current principal, accrued interest, last-accrue-ts) is rebuilt from the JSONL on import (so a bot restart resumes correctly). NOT mixed into `bot_state.json` — keeps the contest's PnL accounting clean and the Kamino sink trivially deletable.

### Accrual model

Per-second compounding, simple:

```
elapsed_sec = now - last_accrue_ts
new_principal = principal * (1 + apy/seconds_per_year)^elapsed_sec
```

`seconds_per_year = 365.25 * 86400`. Kamino's real model is per-slot compounding off a borrow-utilization curve — close enough at 4% APY scale over hours/days that the paper number stays within the conservativeness band of `GECKO_KAMINO_APY_FALLBACK=0`.

Every accrue event appends a `{"type":"accrue", ...}` row to the JSONL with the timestamp + principal delta. Enables exact audit later.

### Withdrawal flow (this sprint = manual / disabled)

The sink exposes `withdraw(amount_usd)` for the v2 open-position wire. NOT invoked this sprint. Documented + tested; just not connected to bootstrap.py. Wiring it requires the bot to actually track "available USDC" coherently across the live + paper lanes, which is its own ticket.

---

## 3. Falsifiability

How do we know the sink is doing what it claims?

- **Ledger invariant:** at any point, `current_principal == sum(deposits) - sum(withdrawals) + sum(accruals)` modulo float epsilon. Asserted on every read.
- **Live comparison:** if a future real-money sibling is run in parallel against the same Kamino reserve, the paper ledger's accrued interest should match the real account's balance growth within ±20bps over a 7-day window (the gap = the real curve's utilization shifts vs our cached APY snapshot). Documented; not enforced this sprint.
- **Test gate:** `test_kamino_paper.py` proves that the accrual math is correct deterministically for a fixed APY + elapsed window.

---

## 4. Live Kamino APY snapshot (verified 2026-05-31)

Pulled from the live Kamino REST API:

```
GET https://api.kamino.finance/kamino-market/{MAIN_MARKET}/reserves/metrics
```

Main market address: `7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF`
USDC reserve address: `D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59`
USDC mint: `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`

**Supply APY at snapshot: `0.042154922207012335`** → **4.2155% APY**

Other anchoring data points (sanity check):
- USDT supply APY: 3.527%
- USDS supply APY: 4.019%
- PYUSD supply APY: 3.226%

Stablecoin APYs cluster in the 3–6% range; USDC at 4.22% is in-band. We will cache this and refresh every 6h. Test fixtures use 4.2% (`0.042`) for deterministic accrual math.

---

## 5. Risk note

**Load-bearing assumption:** *the paper-sink's APY accrual will track the real Kamino USDC reserve's accrual within a tolerable error band over the bot's holding horizon.*

This fails if:
- **Variable utilization:** Kamino's supply APY is utilization-driven — when borrowers leave or whales deposit, the rate moves. A cached 6h snapshot drifts. The paper number will diverge from a real account's growth during volatile borrow windows.
- **Vault caps / cooldowns / withdraw fees:** the real Kamino main reserve has no hard cap nor cooldown on USDC at current TVL, but **klend reserves can be paused** by Kamino governance for risk events (e.g. depegs, oracle outages). The paper model treats deposits as instantaneous and risk-free. A real outage = paper says "+$0.03 accrued" while a real wallet is frozen.
- **Reserve token volatility:** USDC is taken as par-to-USD in the paper model. A USDC depeg event (Mar 2023 precedent) would not show up in paper accrual at all — paper assumes 1 USDC = $1 forever.
- **Mainnet ≠ live snapshot:** the snapshot above was pulled from a public REST endpoint with no signing; the actual reserve we'd deposit into via `kamino_devnet.py` references the SAME on-chain account, but a real deposit flows through KTX (`https://...ktx/klend/deposit`) which adds its own routing + slippage path we have NOT exercised in paper.

The right mental model: this sprint produces a **lower-bound estimate of foregone yield**, not a forecast of real-money outcome. Anything the paper sink says we accrue is an optimistic floor on what a real deployment would accrue minus operational frictions. Use it to size the opportunity (~$0.10/day per $1k idle, basically), NOT to back a real-money go-live decision without a live-mode parity check first.

---

## 6. Out of scope (deferred to S26+)

- Real on-chain deposit signing/sending via `kamino_devnet.fetch_unsigned_deposit_tx`
- Withdrawal wire on the open-position side
- Multi-reserve routing (USDT/USDS as fallback if USDC paused)
- Kamino Multiply vaults (different risk profile, not validated)
- Reading the live wallet's actual USDC balance via Helius (this sprint uses the bot's tracked counters)
