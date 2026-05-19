# Gecko-Verdict Demo Comparison — Methodology Design (S38-#128)

**Mode:** read-only design. No code, no spend, no commit.
**Owner:** `quant-analyst`. Statistical-rigor design for the
`gecko-yield-verdict` with/without-Gecko comparison.
**Companion docs:** `2026-05-19-okx-complement-map-s38-plan.md` (the skill
plan, S38-#126), `2026-05-19-okx-skill-quality-feasibility.md` (#125).

---

## 0. The question this doc answers

The founder wants to measure, in **OKX demo mode** (forward paper-trading,
fake money, $0): *does adding Gecko's grounded verdict to a yield-deposit
decision produce better decisions than the onchainOS-only baseline?*

This doc designs that comparison. It does **not** run it — running it is a
post-S38-#127 task gated on the skill's toggleable baseline mode existing.

**The single most important framing, stated up front:** this is **forward
paper-trading, not backtesting.** A yield deposit is a thesis held for
weeks. PnL accrues in real calendar time. A 5-decision demo is *not proof of
anything* and must never be sold as such — that over-claim is exactly the
failure mode S33–S37 fought (verdict_accuracy swinging 0.60→0.70→0.90 on
N=10 with no interval). The honest, defensible read of an early demo is in
§4 and §5; read those before quoting any number externally.

---

## 1. The metric

### 1.1 Why a naive PnL race is the wrong primary metric

The instinct is "compare forward PnL of baseline-mode deposits vs
Gecko-mode deposits." That is the *eventual* metric but it cannot be the
*primary early* metric, for three reasons:

1. **Yield PnL is slow and low-variance per unit time.** A USDC pool at
   8% APY earns ~0.022%/day. Over a 2-week demo a correct vs incorrect
   *pool selection* differs by single-digit basis points unless a pool
   actually breaks. The signal is dominated by whether a *bad* pool was
   avoided, not by yield-rate optimisation.
2. **The wins are rare and large, the losses of edge are frequent and
   small.** Gecko's value in a yield decision is tail-risk avoidance
   (depeg, utilisation spiral, exploit, unsustainable emissions). Most
   weeks nothing breaks and baseline == Gecko. The distribution is
   heavily skewed — a mean-PnL t-test on a short window has almost no
   power against it.
3. **Acted-on vs declined is a selection-biased pair.** You only observe
   forward PnL for deposits actually made. A verdict that declines a
   deposit produces a *counterfactual* ("what the pool would have done"),
   not a realised PnL. That counterfactual is observable here only
   because it is paper-trading — but it must be tracked deliberately
   (§2.4), not assumed.

### 1.2 Primary metric — **Bad-Pool Avoidance Rate (BPAR)**

> Of the pool-deposit decisions where the pool subsequently experienced a
> **defined adverse event** within the holding window, what fraction did
> the decision-maker *decline or down-size*?

Computed per mode (baseline, Gecko):

```
BPAR = (adverse-event pools declined or down-sized) / (adverse-event pools total)
```

An "adverse event" is **defined in advance** (pre-registration, §2.5) so it
cannot be moved after the fact. The v0.1 definition:

- **Depeg:** pool's principal stable moves >0.5% off peg, sustained >6h.
- **Utilisation spiral:** lending-pool utilisation >95% for >24h (withdrawals
  gated / rate spike).
- **Yield collapse:** realised APY drops >50% vs the APY quoted at decision
  time, within the holding window.
- **Protocol incident:** exploit, governance freeze, or oracle failure on
  the host protocol (binary, sourced from public incident trackers).

BPAR is the primary metric because it isolates **exactly the behaviour
Gecko claims** — the abstain-not-fabricate / surviving-dissent edge — and it
is a *rate*, so it is directly amenable to a proportion test (§3) and does
not require slow yield accrual to register signal. A bad pool that breaks on
day 3 scores immediately.

**Verdict→action mapping** (the skill's toggle determines which produces
the decision):
- Gecko verdict `GO` → act (deposit full size).
- Gecko verdict `REFINE` → down-size (deposit reduced / wait).
- Gecko verdict `PIVOT` → decline.
- Baseline mode: onchainOS data only drives a deposit / no-deposit call
  with no verdict gate — this is the control arm.

### 1.3 Supporting metrics

| Metric | Definition | What it adds |
|---|---|---|
| **Decision hit-rate** | Fraction of *acted-on* deposits whose holding-window outcome was net-positive (yield earned − any adverse loss > 0). Reuse `hit_rate` in `backtest/metrics.py`. | Catches the opposite error — Gecko being so cautious it declines good pools. Guards against an over-abstaining skill scoring a great BPAR by declining everything. |
| **Forward paper PnL (bps, holding-window-normalised)** | Per-decision realised return of acted-on deposits, plus the *counterfactual* return of declined pools. Annualise via `sharpe_annualized` only at ≥30 decisions. | The eventual headline once N is adequate. Reported with a CI from day one, never as a point estimate. |
| **Decline-precision** | Of pools Gecko declined, fraction that *did* hit an adverse event or underperformed the acted-on median. | Direct evidence the verdict's "no" is informative, not random caution. |
| **Abstain honesty** | Fraction of decisions where Gecko returned a low-grounding / `REFINE`-floored verdict *and* the corpus genuinely had thin coverage of that pool's protocol. | Confirms abstention tracks corpus gaps (the wedge), not noise. |
| **Verdict stability** | Same pool, same inputs, re-queried — verdict agreement rate across repeats. | Separates a real decision delta from LLM-judge variance. Borrow the S37 N=57 ship-gate discipline. |

**Composite headline (only once N≥30 per arm):** report BPAR and
decision hit-rate *jointly* — Gecko "wins" only if it improves BPAR
**without** materially degrading hit-rate. A single number invites the
exact over-claim this doc exists to prevent.

---

## 2. Methodology — the A/B

### 2.1 Design

Same skill (`gecko-yield-verdict`, S38-#127), one decision pipeline, two
modes via the built-in toggle:

- **Arm A — baseline:** onchainOS data only. `onchainos defi` discovery
  feeds the deposit decision; no `gecko_trade_research` call.
- **Arm B — Gecko:** identical discovery inputs, then one
  `gecko_trade_research` call; the verdict gates the action per §1.2.

**Paired by construction.** Every decision input (candidate pool set, sizing
budget, timestamp, on-chain facts) is run through *both* arms. This is a
**paired comparison**, not two independent samples — same pools, same
moment, only the decision layer differs. Pairing removes pool-selection and
market-regime variance, which is the dominant noise source, and roughly
halves the N needed for a given power (§3).

### 2.2 What a "run" is

A **run** = one batch of *K* yield-deposit decision points, each:

1. A candidate pool surfaced by `onchainos defi` discovery (the OKX spine —
   primary data source, unchanged).
2. Arm A produces a decision (deposit size or decline) from onchainOS data.
3. Arm B produces a decision from the same data + the Gecko verdict.
4. Both decisions are **dry-run** via `onchainos gateway simulate` (the
   on-chain path has no `--demo`; `gateway simulate` is the tx dry-run) or
   executed in the `agent-trade-kit --demo` account if the pool is on the
   CEX-earn side. No mainnet tx, no real funds.
5. The pool enters a **holding window** (§4) over which adverse events and
   realised yield accrue and are recorded.

### 2.3 Recording — the run ledger

One append-only JSONL ledger, `tests/demo/yield_verdict_runs/<date>-<tag>.jsonl`,
one row per decision per arm:

```json
{
  "run_id": "...", "decision_id": "...", "arm": "gecko|baseline",
  "ts_decided": "...", "pool_id": "...", "protocol": "...",
  "chain": "...", "quoted_apy": 0.082, "sizing_budget_usdc": 1000,
  "onchainos_facts": { ... },
  "verdict": "GO|REFINE|PIVOT|null", "confidence_bucket": "...",
  "surviving_dissent": "...", "citation_count": 3, "low_grounding": false,
  "decision": "deposit|downsize|decline", "deposit_size_usdc": 1000,
  "holding_window_days": 14,
  "outcome": { "adverse_event": null, "realised_apy": null,
               "pnl_bps": null, "settled": false }
}
```

Rows are written `settled: false` at decision time and **patched once** when
the holding window closes. The decision-time fields are immutable —
mirrors the `verdict_hash` discipline so a verdict cannot be rewritten after
its outcome is known.

### 2.4 The declined-pool counterfactual

For every `decline` / `downsize`, the declined (or un-deposited) portion is
tracked as a **shadow position** — paper-only, recorded as if deposited at
full size, so its forward outcome is observable. This is the only way
declined deposits contribute to PnL and decline-precision. It is legitimate
*only* because this is paper-trading; it must never be framed as realised
PnL. Shadow positions are flagged `shadow: true` in the ledger.

### 2.5 Pre-registration

Before the **first** run of any tracked comparison cycle, freeze in a
committed `preregistration` block at the top of the ledger: the adverse-event
definitions (§1.2), the primary metric (BPAR), the target N, the holding
window, and the decision threshold for "Gecko wins." Pre-registration is
what makes the result quotable — it stops the metric being chosen after the
data is seen. Any change = a new cycle with a new pre-registration, not an
edit.

---

## 3. Statistics — what test, what N

### 3.1 The test

BPAR is a proportion compared across two paired arms over the *same* pools.
The correct test is **McNemar's test** on the discordant pairs (pools where
the two arms disagreed on decline-vs-act), not a two-sample proportion test
— the arms are paired, and only disagreements carry information.

- **Null H₀:** Gecko mode and baseline mode decline adverse-event pools at
  the same rate (discordant pairs split 50/50).
- Report the **exact McNemar p-value** *and* a **bootstrap 95% CI on the
  BPAR difference** (resample decision points with replacement, ≥10k draws).
  Lead with the interval, per the quant-analyst standing rule.
- Supporting metrics (hit-rate, PnL bps): paired bootstrap CI on the
  per-decision difference. PnL also gets a Wilcoxon signed-rank test
  (skewed, non-normal — §1.1).
- **Verdict stability** is measured first and reported as the noise floor:
  any BPAR difference smaller than the stability band is *not* signal.

### 3.2 Minimum sample — be explicit

This is the section the founder must internalise before quoting anything.

**Adverse events are rare.** If ~10–15% of surfaced yield pools hit a
defined adverse event in a 2-week window, then **a run of K=10 decisions
yields only ~1–2 adverse-event pools** — the denominator of the primary
metric. BPAR on a denominator of 1 is uninterpretable: it is 0.0 or 1.0
with a 95% CI of essentially [0, 1].

Power analysis (paired proportions, McNemar, two-sided α=0.05):

| To detect (BPAR baseline → Gecko) | Power 0.80 needs ~ | Implied total decisions* |
|---|---|---|
| 0.40 → 0.80 (large effect) | ~25 discordant pairs | ~150–250 decisions |
| 0.50 → 0.75 (moderate) | ~45 discordant pairs | ~300–450 decisions |
| 0.55 → 0.70 (modest) | ~110 discordant pairs | ~700+ decisions |

\* assuming ~12% adverse-event base rate and that disagreements concentrate
on the adverse subset. These are order-of-magnitude planning numbers, not
promises — the true N depends on the realised base rate, which the first
cycle measures.

**Honest thresholds for what an early demo may claim:**

- **N < 10 adverse-event pools (≈ first 1–2 weeks):** *directional
  illustration only.* Permitted language: "in this demo run, Gecko declined
  N of M pools that later broke." **Forbidden:** any rate, percentage,
  Sharpe, "X% better," or the word "proves." No CI is meaningful here.
- **10–25 adverse-event pools:** report BPAR *with its wide CI shown* and
  the McNemar p-value. Frame as "early signal, CI still wide, not yet
  conclusive." A non-significant result here means *underpowered*, not
  *no effect* — say so.
- **≥25 adverse-event pools with a significant McNemar result and a CI
  excluding zero:** the first defensible "Gecko mode improved bad-pool
  avoidance" claim — and even then bounded to the pre-registered
  adverse-event definitions and the corpus state at that cycle.

**The corpus is still small.** S37 shipped the gate at N=57 *rubric*
fixtures; the investor-canon corpus (Marks/Damodaran/Berkshire) is dense on
yield reasoning but thin on long-tail protocols. Where the corpus is thin,
Gecko *should* abstain (`REFINE`/low-grounding) — and the comparison must
credit that as correct behaviour, not a miss. As the corpus grows, expect
BPAR and decline-precision to rise; tracking that trend is the point of §5.

---

## 4. Time horizon

This is **calendar-time forward accrual.** It does not compress.

- **Holding window per decision:** 14 days (pre-registered; covers a depeg /
  utilisation episode but stays inside a demo-cycle budget). A decision made
  today is not `settled` until day 14.
- **One comparison cycle:** rolling decision intake over ~2–4 weeks, then
  all windows close. Earliest a cycle yields *any* settled outcomes is
  ~14 days after the first decision; a full cycle is ~4–6 weeks.
- **First defensible BPAR claim:** realistically **6–10 weeks** out, gated
  on accumulating ≥25 adverse-event pools — which depends on the adverse
  base rate and on decision throughput, not on calendar alone.

There is no way to make this fast without abandoning honesty. A backtest
*would* be instant — but a backtest on a small canon corpus invites
overfitting and look-ahead bias, and the founder explicitly asked for
forward demo-mode measurement. Forward paper-trading is slower precisely
because it is harder to fool.

---

## 5. Continuous-improvement frame — repeatable, not one-shot

The founder's intent: this becomes an **ongoing** measure as the corpus
grows. Design for repeatability.

- **Cycle, don't snapshot.** Each comparison cycle is a fresh
  pre-registered ledger (`<date>-cycle-NN.jsonl`). Adverse-event
  definitions and metric stay fixed across cycles so cycles are
  comparable; the corpus version is a recorded covariate.
- **Tracked baseline.** A `tests/demo/yield_verdict_runs/_trend.json`
  summary table holds, per cycle: corpus chunk-count + version, N
  decisions, N adverse-event pools, BPAR (both arms) + CI, decision
  hit-rate, decline-precision, McNemar p. The expected, falsifiable
  hypothesis: **as corpus grows, Gecko-arm BPAR and decline-precision
  rise while baseline stays flat.** If they don't, the corpus growth
  isn't buying decision quality — that is itself a finding worth having.
- **Re-runnable harness.** The comparison should be a parameterised
  script (`scripts/demo/run_yield_verdict_comparison.py`, K, holding
  window, tag as args) so a cycle is one command + a 2–4-week wait, not
  a bespoke setup each time. Build it once in S38-#127's wake.
- **Guard against drift.** Re-run verdict-stability at the start of every
  cycle; if the noise floor moved, prior cycles' significance must be
  re-read against the new floor.

---

## 6. Environment prerequisites — founder setup steps

The comparison cannot run until these are in place. Steps marked
**[founder]** are manual actions only the founder can perform (auth /
account). The rest can be agent-driven.

1. **[founder] `onchainos` CLI present and logged in.** Binary at
   `~/.local/bin/onchainos` (v3.2.0+ per the OKX-wallet memo). Login is
   OTP-via-email against `gecko-okx-context@geckovision.tech`; session
   token caches in `~/.onchainos/`. Verify with
   `onchainos wallet status` → `loggedIn: true`. Re-login if false.
2. **[founder] OKX demo / sandbox auth.** The `/mcp` authenticate step is
   a founder action — the onchainOS MCP server needs an authenticated
   session for `onchainos defi` discovery and `onchainos gateway simulate`
   to return live pool data. The on-chain path has **no `--demo` flag**;
   decisions are dry-run via `gateway simulate` + the README's built-in
   sandbox keys. No funded balance is required for the comparison — every
   money step is dry-run or shadow.
3. **[founder] `agent-trade-kit` `--demo` account (only if CEX-earn pools
   are in scope).** OKX Demo Trading account: Trading → Demo Trading → API
   Management, set `demo = true` in `~/.okx/config.toml`. Needed *only* if
   the comparison includes CEX `okx earn` pools alongside on-chain DeFi;
   the on-chain-only v0.1 scope does not require it.
4. **Gecko oracle reachable, `X402_MODE=stub`.** Confirm
   `api.geckovision.tech/trade_research` returns a verdict envelope
   (`verdict` / `confidence` / `surviving_dissent` / `citations`) for a
   yield question at $0. This is S38-#126 WS-B; it is a hard gate — a
   500 during a cycle zeroes the Gecko arm.
5. **Skill `gecko-yield-verdict` with the baseline toggle.** S38-#127
   must ship the toggleable baseline/Gecko mode this comparison depends
   on. The comparison is gated on #127 landing.
6. **Ledger + harness scaffolding.** `tests/demo/yield_verdict_runs/`
   directory and the `run_yield_verdict_comparison.py` script (§5).
   No spend; build alongside #127.

**Setup is not yet done.** Items 1–3 are founder actions; 4 is a probe; 5
is the parallel build ticket; 6 is scaffolding. The comparison's first
cycle starts only after all six clear.

---

## 7. Summary — can this produce a meaningful signal soon?

**No — not "soon" in the days sense. It is a genuine multi-week accrual.**

- A meaningful BPAR signal needs ≥25 adverse-event pools; at a ~12% base
  rate that is ~150–250 decisions, accrued over **6–10 weeks** of forward
  paper-trading with a 14-day holding window per decision. There is no
  honest shortcut — compressing it means backtesting, which the founder
  explicitly ruled out and which would overfit the small canon corpus.
- What a **small early demo CAN** legitimately do: produce a *directional
  illustration* — "in this run, Gecko declined N of M pools that
  subsequently broke" — useful for a demo narrative, never as a rate, a
  percentage, a Sharpe, or "proof." That is the precise line S33–S37
  fought to hold.
- The design is built to be **repeatable** (§5): pre-registered cycles, a
  tracked `_trend.json` baseline, a one-command harness. The real payoff
  is the *trend* — Gecko-arm BPAR rising as the corpus grows while the
  baseline stays flat. That trend is the defensible, honest claim, and it
  only exists if the comparison is run as an ongoing cycle, not a
  one-shot.
