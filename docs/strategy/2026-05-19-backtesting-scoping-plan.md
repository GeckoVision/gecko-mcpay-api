# S39-#129 — Backtesting Layer Scoping Plan

**Date:** 2026-05-19 · **Mode:** read-only scoping pass. No code, no spend.
Backtesting is an S39+ workstream — NOT blocking S38.
**Companion:** `2026-05-19-gecko-verdict-demo-comparison-design.md` (S38-#128)
designs the *forward* paper-trade comparison; this doc designs its
*retrospective* complement.

## 0. Recommendation, up front

1. **Do NOT adopt Backtrader, NautilusTrader, vectorbt, backtesting.py, or
   zipline-reloaded. Build a thin custom event-loop in `gecko-core`** (~250–400
   LOC). Every generic engine is built around an *indicator-signal* unit of
   action; Gecko's unit is *"a grounded verdict at time T."* The impedance
   mismatch costs more than the loop saves.
2. **The real engineering is point-in-time corpus + on-chain reconstruction**,
   not the simulator. That is where the budget goes.
3. **The methodological blocker is LLM-hindsight contamination** — it bounds
   *what* can be backtested far more than any framework choice (§3).
4. **Phase it.** Phase 0 ships a replay harness on already-frozen fixture
   dates; live historical reconstruction (Phase 2) is the expensive deferred
   part.

## 1. Framework — Backtrader is dead; a generic engine is the wrong tool

Backtrader is abandoned (creator considers it complete; the `backtrader2`
community fork is itself inactive as of 2025). Strike it from the architecture
diagram.

But the issue is not just abandonment — a generic engine *mismatches* Gecko:

| Engine | Status | Why it mismatches |
|---|---|---|
| backtrader / backtrader2 | abandoned | dead |
| nautilus_trader | healthy, Rust HFT engine | built for order-book/latency/fill realism; Gecko makes one decision per pool per ~14-day window — massive overkill |
| vectorbt | healthy, vectorized | vectorization = NumPy over indicator signals; a `gecko_trade_research` call is an irreducible async LLM call — cannot vectorize |
| backtesting.py | maintained, light | closest, but its `Strategy.next()` assumes an OHLCV bar feed — more glue than a bare loop |
| zipline-reloaded | maintained | equities/pipeline-factor domain — wrong domain |

**The custom loop is genuinely simple:** iterate decision points → call
`gecko_trade_research` on point-in-time inputs → map verdict to action
(GO→deposit, REFINE→downsize, PIVOT→decline) → accrue PnL/adverse-events over
the holding window → write the **same JSONL ledger schema** the S38-#128 doc
specifies. Shared ledger = shared metrics code.

**Lives in** `packages/gecko-core/src/gecko_core/backtest/` — `engine.py` (the
loop), `metrics.py` (pure functions; the S38 doc already forward-references
`backtest/metrics.py` — build here, both docs consume it), `reconstruction.py`
(Phase 2). CLI: `bb backtest`. **Boundary:** the loop is pure orchestration —
it calls the *same* oracle path the live product calls; it must NOT fork
retrieval or touch `trade_agent/hotpath/` (Pattern E — fork it and you are
testing a different system).

## 2. The hard part — point-in-time reconstruction, no lookahead

Every input the panel sees at T must be reconstructed as-of-T.

- **2a. Corpus chunks — partially solved.** `protocol_native` chunks carry
  `as_of_date` (S33-#68); `market_data.py` renderers key Pyth/DeFiLlama chunks
  on `as_of`. Gap: the retrieval `$match` has **no `as_of_date <= T` predicate**
  — adding one is the core data-engineer ticket. It is a retrieval *gate*, so
  Pattern F applies — it needs a direct end-to-end leakage probe (a question
  at T whose expected citations are all `as_of_date <= T`, asserting zero
  future chunks leak).
- **2b. On-chain price/yield as-of-T — the expensive part.** Pyth Hermes
  (historical by publish-time) + DeFiLlama (`yields.llama.fi/chart/{pool}` —
  full APY/TVL series per pool), both free/no-key. Work: `reconstruction.py`
  fetches the series, truncates at T, renders through the *existing*
  renderers. Cache on `(pool, T)` — historical data is immutable, so re-runs
  cost $0. SSRF/httpx caps from CLAUDE.md apply.
- **2c. The corpus didn't exist at T — the honest limit.** Gecko's corpus was
  built in 2026. A backtest measures *"today's corpus + today's panel judging
  point-in-time market data"* — NOT "the product as it would have run in
  2024." The market data is genuinely as-of-T; only the (timeless) canon is
  anachronistic. Acceptable — but label it in every output, never sell it as
  "we would have caught X in real time."

## 3. The LLM-hindsight contamination trap

The methodological blocker. The panel models have training data through
~2024–2025 — backtest the verdict over the UST depeg / FTX / a known exploit
and the model *knows the ending*. A contaminated backtest is **worse than no
backtest** — a confident, invalid number.

Design around it, in priority order:
1. **Post-cutoff-only test windows (primary)** — only backtest periods after
   the panel models' training cutoff. The window slides forward as models
   update.
2. **Adverse-event obscurity filter** — prefer long-tail, non-famous events
   over headline depegs (headlines leak even post-cutoff).
3. **Entity ablation** — strip protocol names, leave only on-chain facts; if
   the verdict holds, it is reasoning not recall. Secondary arm (it also
   strips canon-citation matchability).
4. **Contamination probe** — before trusting a window, ask the panel model
   directly what it knows about events around T with no corpus; if it narrates
   the outcome, the window is burned.

`quant-analyst` owns this. No backtest number is quotable until the controls
are pre-registered. A backtest with no clean window simply does not run — and
that is a correct outcome.

## 4. Metrics + the comparison

Reuse the S38 ledger schema + `backtest/metrics.py`.
- **PnL** — realised return of acted-on positions + counterfactual of declined
  pools (shadow positions); holding-window-normalised, bps.
- **Drawdown** — max peak-to-trough on cumulative PnL, per arm.
- **Sharpe / Sortino** — annualised, Sortino preferred (skewed return dist);
  report only at N≥30, else point estimate + CI.
- **Inference-cost-vs-return** — total `gecko_trade_research` spend ÷ PnL edge
  over baseline. The metric unique to an *oracle* backtest. **Internal
  economics telemetry only** — never a buyer-facing surface (CLAUDE.md: no
  per-operation cost to users).
- **The "user agent vs GeckoVision agent" comparison** — two arms over the
  *same* reconstructed decision points, paired (McNemar on discordant pairs —
  identical stats to S38 §3). Headline = the paired difference + bootstrap CI,
  never two solo numbers. Primary metric stays **Bad-Pool Avoidance Rate**.

Backtest vs forward demo: backtest is *instant* (no 6–10-week accrual) but
caveated (contamination, corpus anachronism); forward demo is *slow* but
defensible/quotable. Complements — never let a backtest number carry a
forward-demo claim.

## 5. Phased plan

- **Phase 0 — replay harness on frozen fixtures** (the minimum first
  capability). Build `engine.py` + `metrics.py`; test set = the already-frozen
  fixture dates in `tests/sources/fixtures/`. No new data infra, no spend.
  ~3–4d — `software-engineer` + `quant-analyst`.
- **Phase 1 — `as_of_date <= T` retrieval gate** + a Pattern-F leakage probe.
  `data-engineer`. ~2–3d. Gates Phase 2.
- **Phase 2 — live historical reconstruction** (`reconstruction.py`: DeFiLlama
  `/chart/{pool}` + Pyth historical, truncate-at-T, cache). The cost center.
  `data-engineer` + `trading-strategist`. ~5–7d.
- **Phase 3 — contamination-controlled backtest cycle.** Pre-registered
  post-cutoff windows, obscurity filter, ablation arm, probe. `quant-analyst`
  owns; `trading-strategist` curates the adverse-event set.
- **Deferred beyond S39:** entity-ablation as a standing arm; multi-protocol
  sweeps; a polished `bb backtest` CLI; any user-facing "compare your agent"
  surface in `gecko-mcpay-app`.

**Effort:** ~12–17 days across phases; P0 is genuinely cheap, P2 is the cost
center.

## 6. Strategic intent — a public trust benchmark, not internal telemetry

Founder direction (2026-05-19): the backtest is a **credibility instrument**.
"Gecko builds skills people rely on because it works" — the benchmark is how
that is *shown*, publicly and verifiably. Two refinements to this plan:

- **The performance comparison (Gecko vs baseline) is public-benchmark-grade**,
  not internal-only. (Only the inference-cost economics in §4 stay internal.)
  The methodology must be **pre-registered** and the result ledger **immutable
  + auditable** — a benchmark people rely on is one a skeptic cannot quietly
  re-cut.
- **A backtest alone is NOT the headline trust claim.** An LLM-verdict
  backtest is attackable on its face — "the panel was trained through 2025, of
  course it 'called' a 2024 event." The bulletproof, un-game-able benchmark is
  the **forward audited track record**: every verdict timestamped, outcomes
  recorded, nothing editable (the S38-#128 forward demo, run as a permanent
  public ledger). The backtest is the *fast directional companion* to that
  record — never the claim that stands alone.

**Trust stack, strongest first:** (1) the forward immutable track record;
(2) the S37 6/6 ship-gate — verdict *quality*, proven at N=57, publishable
today; (3) the contamination-controlled backtest — fast, caveated.

## Sources

- Backtrader Community — "Is Backtrader dead?"; `backtrader2` Snyk health (inactive 2025)
- NautilusTrader / vectorbt / backtesting.py / zipline-reloaded docs
- DeFiLlama API docs + `yield-server` (historical APY/TVL)
