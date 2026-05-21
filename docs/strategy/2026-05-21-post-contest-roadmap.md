# Post-Contest Roadmap — evolve the agent, the skills, and the data

*2026-05-21. The OKX Agentic Trading Contest is live and we're in it
(+1.67% real, 3W/0L). Leaderboard top-50 needs ~9% PnL — unreachable in a
single day in this chop regime, and we already accepted that. The contest
is not the goal; it's the proving ground. **The agent keeps running after
the contest closes.** This roadmap is the continuous-improvement plan:
better agents, better skills, and — the foundation under both — real data.*

---

## Guiding principle

Per `local_lab_strategy` (2026-05-20): **build in the lab (contest_bot),
validate on live data, transplant winners to the PRD oracle.** Every
improvement below follows that cadence. We do not tune on vibes; we
collect data, falsify against it, then promote.

The contest taught us the real lesson: **paper mode hides production bugs.**
We found 6 live-only bugs in 2 hours of real trading. The roadmap is built
to keep that feedback loop running — the agent stays live (small capital),
keeps generating data, and each sprint hardens it.

---

## The three tracks

### Track A — Data (the foundation everything else needs)

The quant's verdict was decisive: *we cannot validate any stall/strategy
threshold because we don't store per-poll data.* iter-3.8 fixed the first
half (per-poll telemetry now writes to `poll_telemetry_YYYYMMDD.jsonl`).

| Sprint | Deliverable | Why |
|---|---|---|
| **A1 (done)** | Per-poll telemetry logger (price, pnl, peak, mins_since_high, age) | The missing return-series; supports the autocorrelation stall signal |
| **A2** | Add volume + range to telemetry rows (one candle fetch per poll, cached) | Volume-decay is the strongest pause-vs-stall discriminator (strategist) |
| **A3** | Telemetry → MongoDB Atlas loader | Promote from JSONL when: multiple agent instances, OR cross-session querying, OR volume outgrows files. **Schema already maps 1:1.** Reuses the existing Mongo Atlas the PRD chunks live in. |
| **A4** | Outcome-labeling pass | Tag each telemetry episode with its eventual exit (TP/SL/trail/stall/time-stop) so v2 detectors have labeled training data |

**MongoDB decision (founder's question):** *not yet.* Local JSONL is correct
today — zero infra, matches the lab pattern, single-writer at our volume.
Move to Mongo at sprint A3 when we have a second agent instance or need to
query across days. The collection schema = the JSONL row schema, so it's a
loader, not a rewrite.

### Track B — Agents (the strategy + the voices)

| Sprint | Deliverable | Why |
|---|---|---|
| **B1 (done)** | Flat-stall exit (simple time+structure rule) | Catches the BONK no-man's-land; falsified against live trades |
| **B2** | Stall-detector v2 — data-driven | Once A2+A4 give ~100 labeled episodes: build the volume-decay + return-autocorrelation classifier the strategist designed, validated on real data with a bootstrap CI (not fit to BONK) |
| **B3** | Rotation gate | "Only exit a stall if a fresh higher-conviction candidate exists" — wire the monitor loop to the candidate scan so freed slots are actually filled |
| **B4** | New voices (transplant candidates) | smart_money_voice (OKX signal feed), regime_analyst (BTC/SOL macro state). Build in lab, validate, promote to PRD oracle |
| **B5** | Entry-quality study | We decline ~95% of candidates (chart < 0.85). Use telemetry to check: of the declines, how many *would* have been winners? Tune the floor on data, not feel |

### Track C — Skills (the sellable product)

| Sprint | Deliverable | Why |
|---|---|---|
| **C1 (done)** | geckovision-risk-oracle v2.0 — adversarial three-lens + stall section | The wedge, packaged. Pre-trade verdict + post-entry stall management |
| **C2** | Wire the skill to call the live PRD oracle | The skill currently instructs an agent to reason; C2 makes it call `gecko_trade_research` for the *real* grounded verdict + citations. Skill becomes a thin client of the oracle we sell |
| **C3** | x402 metering on the skill | Per-call USDC payment, the actual revenue model. Stub-mode first (per `project_x402_stub_then_live`), live only on founder go-ahead |
| **C4** | Second skill: copy-trade guardrail | Mirror-with-safety — wraps okx-dex-signal smart-money copies with the risk oracle. Diversification bucket from the milestone plan |

---

## How the tracks interlock

```
Track A (data) ──feeds──> Track B (better agents) ──transplant──> Track C (sellable skills)
     ▲                                                                      │
     └──────────────── live agent generates more data ◀────────────────────┘
```

The agent stays live on small capital → generates telemetry (A) → the
telemetry trains better detectors/voices (B) → the validated logic is
packaged into metered skills (C) → the skills (and the agent) generate more
data. The contest just bootstrapped the loop with real money on the line.

---

## Near-term sprint order (next 2–3 sprints)

1. **A2** — volume+range in telemetry (small, unblocks B2)
2. **B5** — entry-quality study on accumulated telemetry (are we too strict?)
3. **A4 + B2** — labeled episodes → data-driven stall-detector v2
4. **C2** — skill calls the live PRD oracle (turns the skill into a real product surface)

Everything else (Mongo migration, new voices, copy-trade skill, x402
metering) sequences behind these as the data and the capital grow.

---

## What stays locked

- Contest bot settings during the grow phase (per milestone plan)
- chart_floor 0.85 / abstain-not-fabricate — the wedge
- Small capital until the 48h unattended soak passes
- One knob per sprint; validate on data before promoting
- x402 stays stub until explicit founder go-ahead

---

## The honest framing

We will not win the contest leaderboard (top-50 = ~9% in a chop day —
structurally out of reach, and chasing it means burning the wedge). What
we *are* building is the thing the contest can't measure: a live-proven,
honestly-accounted, continuously-improving trading agent + a sellable risk
oracle, both fed by a data loop that compounds. That outlasts the contest.
