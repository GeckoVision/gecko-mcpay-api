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
| **B6** | **Grid strategy for chop regimes** | Spot-grid profits from *oscillation* (buy low / sell high in a range) — exactly the chop where our momentum bot stalls (BONK). It would *make money on the stalls that frustrate us.* Grid is the natural complement to momentum: run momentum in trends, grid in ranges (gate on `adx` — low ADX = chop = grid). Native OKX `grid_create_order` endpoint (Track D). Realistic target modeled on proven OKX grid bots: **~1.5-2.5%/week sustained**, prioritizing **low drawdown** (the best one ran +183% over 2yr at 0.75% max weekly drawdown) |

### Track D — OKX API integration (market data + execution)

The OKX OnchainOS API (docs: `https://web3.okx.com/llms-full.txt`) exposes
far more than we currently use. We poll `/price-info` and compute our own
EMA/breakout by hand. OKX serves **80+ validated technical indicators**,
real-time WebSocket push, smart-money signals, and native grid/DCA bots —
much of it available right now as `okx-agent-trade-kit` MCP tools
(`market_get_indicator`, `market_get_candles`, `smartmoney_*`,
`grid_create_order`, …).

| Sprint | Deliverable | Concrete OKX capability |
|---|---|---|
| **D1** | Enrich chart_analyst with OKX indicators instead of hand-rolled EMA | `market_get_indicator`: `macd`, `rsi`, `supertrend`, `adx` (trend strength), `aroon`, `bb` (Bollinger) — stop maintaining our own TA math |
| **D2** | **Stall-detector v2 inputs — shortcut the data wait** | `hv` (historical volatility — compression = stall), `bbwidth` / `atr` (range compression), and crucially `mfi` / `cmf` / `obv` (volume-flow). **These are the exact volume-decay / pause-vs-stall features the quant said we lacked** — OKX pre-computes them, so we don't have to accumulate 100 episodes first. Still validate thresholds on telemetry, but the signal is available now. |
| **D3** | Real-time WebSocket push → replace 30s polling | OKX WebSocket market channels (added 2026-03-26). Lower latency = catch breakouts/stalls faster, fewer missed exits |
| **D4** | smart_money_voice data source | `smartmoney_*` (signal overview/trend by filter/trader) + `top-long-short` indicator (Top Trader Long/Short Ratio) + address tracking. Feeds Track B4 |
| **D5** | Better candidate discovery | Trenches API (meme / golden-dog tracking) + token rankings — replaces fixed-universe volume_spike scanning with live discovery |
| **D6** | Authoritative PnL accounting | Portfolio API (`market portfolio-token-pnl`) — cross-checks our real-fill PnL, belt-and-suspenders after the oracle-price accounting bug |

**Key insight (D2):** the OKX indicator API partially *shortcuts* the
quant's "we have no data" blocker. `hv`, `bbwidth`, `mfi` are exactly the
stall/pause discriminators — pre-computed and validated by OKX. The
telemetry (Track A) is still the falsification ground-truth, but v2 stall
detection can be prototyped against these indicators immediately rather
than waiting for 100 logged episodes.

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

## Realistic-returns benchmark (proven OKX grid bots, decoded)

The top copy-tradeable OKX spot-grid bots, read correctly:

| Bot | Headline | Runtime | Real weekly avg | Max weekly drawdown |
|---|---|---|---|---|
| SUI/USDT | +226% | 654d | ~2.4%/week | 8.08% |
| XRP/USDT | +208% | 769d | ~1.9%/week | 7.50% |
| TRX/USDT | +183% | 767d | ~1.7%/week | **0.75%** ← the gold standard |

The headline +200% is **total over ~2 years**, not weekly. The "7D max
drawdown" is the worst-week *loss*, not a return. **The honest, proven,
sustainable target is ~1.5-2.5%/week with low drawdown** — and TRX proves
the holy grail (steady return + sub-1% drawdown) is achievable. This is our
north-star return profile: not flashy, low-drawdown, sustained. It matches
the earlier honest math (sustained ~0.3-0.5%/day).

## Near-term sprint order (next 2–3 sprints)

1. **D1 + D2** — wire OKX indicator API (available NOW): `macd`/`rsi`/`adx`
   into chart_analyst, and `hv`/`bbwidth`/`mfi` into stall detection. High
   value, low effort, and D2 shortcuts the "no data" blocker.
2. **A2** — volume+range in telemetry (falsification ground-truth for D2)
3. **B5** — entry-quality study on accumulated telemetry (are we too strict?)
4. **B6 (prototype)** — grid strategy in paper, gated on `adx` (chop detector)
5. **A4 + B2** — labeled episodes → data-driven stall-detector v2
6. **C2** — skill calls the live PRD oracle (turns the skill into a real product surface)

Everything else (Mongo migration, new voices, copy-trade skill, x402
metering, WebSocket push) sequences behind these as data + capital grow.

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
