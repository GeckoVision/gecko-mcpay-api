# López de Prado — 7 Pitfalls of Financial ML

**Source:** Dr. Marcos López de Prado, *Advances in Financial Machine Learning* + the 2026 lecture series. Public summary curated from a talk where he walks through why "most investment strategies fail."

**Why this lives in our docs:** the `quant-backtest-rigor` skill (`.claude/skills/quant-backtest-rigor/SKILL.md`) encodes the methodology operationally; this doc names the source, defines each pitfall, and maps where Gecko honors or violates it today. Sub-agents should cite this when proposing model-validation work.

**Core insight (LdP, verbatim):** *"A ML algorithm will always find a pattern, even if there is none. ML does not fail; researchers fail. Financial ML ≠ ML algorithms + financial data — finance requires a unique toolkit."*

---

## The 7 pitfalls + Gecko status

### 1. The Generalist Approach

**Pitfall:** The industry forces quants to be generalists — one person doing data engineering, modeling, portfolio construction, execution. No one specializes deeply enough to solve the hard problems.

**LdP recommendation:** specialize. Assign quants to focused areas (data structuration, modeling, portfolio construction, execution) and let teams compose. A team of specialists beats a generalist on any given subproblem.

**Gecko status:** **HONORED structurally** by the sub-agent design. Per `CLAUDE.md` the team is twelve specialists: `quant-analyst` owns "is this number real," `trading-strategist` owns "does this trade make money," `data-engineer` owns "the data is stored correctly," `ai-ml-engineer` owns "the model gives the right answer," etc. Each sub-agent stays in its lane; cross-lane work routes through `staff-engineer`. The lane discipline IS the anti-generalist defense.

**Counter-evidence to watch for:** if any single sub-agent is doing more than one of LdP's specialist roles (e.g. `quant-analyst` also writing the data ingestion code), that's drift and the work should be re-routed.

---

### 2. Integer Differentiation

**Pitfall:** To make non-stationary financial series stationary, the standard move is integer differencing (returns = price[t] - price[t-1], i.e. d=1). But integer differencing destroys memory — the resulting series has no predictive power left.

**LdP recommendation:** **fractional differentiation** (d ∈ (0, 1)). Achieves stationarity while preserving most of the long-memory signal. Optimal d is typically 0.3–0.5 for financial price series.

**Gecko status:** **VIOLATED** — we feed voices raw ADX/RSI/MFI/EMA/range/BB-width values computed from un-differenced price bars. No fractional differentiation anywhere in the pipeline.

**Mitigating factor:** our voices are LLM-graded heuristics on indicator snapshots, not classifiers being trained on a feature matrix. The "memory destruction" pitfall lands hardest on supervised ML pipelines. For our rule-based + LLM panel, it's a latent risk that becomes binding only if we move to learned models in Sprint 28+.

**Future ticket:** when feature engineering becomes a learned-model dependency, add a frac-diff layer (`mlfinlab.features.fracdiff_FFD`) on price-derived inputs.

---

### 3. Inefficient Sampling

**Pitfall:** Time bars (5m, 1h, 1d) sample regardless of whether information has arrived. Most of the bar is noise; the bar that contains the actual information event is averaged with 11 silent bars.

**LdP recommendation:** information-driven bars:
- **Tick bars** — every N trades
- **Volume bars** — every N traded units
- **Dollar bars** — every $N notional (best for cross-asset comparability)
- **Dollar-imbalance bars** — every $N of order-flow imbalance (best for detecting informed trading)

**Gecko status:** **VIOLATED** — 5m time bars exclusively for both the bot's signal generation and the voice panel's indicator snapshot.

**Mitigating factor:** our entry primitive is `breakout+volume` which IS information-driven within the time-bar framework (we require BOTH a price break and a volume spike). It's a coarse approximation of dollar-imbalance gating — better than pure price-breakout, worse than true dollar-imbalance bars.

**Future ticket:** if we ship a 5m → dollar-bar feature pipeline, expect (a) bar count to vary dramatically per symbol, (b) backtests to need re-validation under the new sampling, (c) memory_voice's cross-instrument ledger logic to need re-thinking (already filtered per-instrument as of S24-S, fix 2b).

---

### 4. Wrong Labeling (Fixed-Horizon Returns)

**Pitfall:** ML on finance typically labels "what was the return over the next K periods?" But real investors exit early on stops, take profits at targets, or hit time-budget limits. A fixed-horizon return is rarely what actually happened.

**LdP recommendation:** **triple-barrier method** — for each entry, label by which of three barriers is hit first:
- Upper barrier (take profit)
- Lower barrier (stop loss)
- Time barrier (max holding period)

Plus **meta-labeling**: a primary model decides direction; a secondary model decides whether to trade (filters false positives without lowering recall).

**Gecko status:** **VIOLATED in label shape, HONORED in execution.** Our outcome label IS the realized PnL pct at the actual exit (whether TP, SL, trail, stall, or time-stop fired), not a fixed-horizon return. So we're closer to triple-barrier-in-spirit than to fixed-K returns. BUT — we don't formalize "which barrier fired" as a categorical label; we just record `exit_reason` ∈ {take_profit, stop_loss, trailing_stop, flat_stall_exit}. The training signal is there; the labeling discipline isn't formal.

**Meta-labeling parallel:** the Gecko Oracle's grounded-pass veto on a panel-act decision IS meta-labeling: primary signal = panel verdict, secondary filter = oracle veto on weak fundamentals. So we honor the *concept* without using the *name*.

**Future ticket:** if a learned model gets trained on our decision-vector substrate (Voyage-1024 embeddings in `bot_behaviors`), the label MUST be the barrier-fired category, not the raw PnL.

---

### 5. Weighting of Non-IID Samples

**Pitfall:** Standard ML assumes samples are independent and identically distributed. Financial samples almost never are — overlapping holding periods create serial correlation; a sample from t=0 and a sample from t=1 share most of their information content. Equal-weighting these double-counts the same signal.

**LdP recommendation:** weight samples by their **uniqueness**:
- Compute average uniqueness per sample (how many other samples share its time window)
- Down-weight non-unique samples in training
- For triple-barrier labels, weight by inverse-overlap

**Gecko status:** **N/A today** — we don't train classifiers, so non-IID sample weighting doesn't apply.

**Latent risk:** when Sprint 28+ adds memory_voice_v2 cohort filtering or any learned model on the decision-vector substrate, this becomes binding immediately. Pre-S28 ticket: ship sample-uniqueness weights as a `mlfinlab.sample_weights` import before any classifier sees the substrate.

---

### 6. Leaky Cross-Validation

**Pitfall:** Standard k-fold CV randomly partitions data. In finance, training and test folds overlap in time AND share serial-correlated samples. The "test" set is leaking train-set information; reported CV scores wildly overstate generalization.

**LdP recommendation:** **purged + embargoed k-fold CV** (and its combinatorial extension **CPCV**):
- **Purge** any training sample whose label-end-time overlaps a test sample
- **Embargo** N samples after each test set to break the residual serial correlation
- CPCV: combinatorial paths from C(N, k) test partitions → distribution of out-of-sample scores instead of a single number

**Gecko status:** **HONORED** in our backtest validation:
- `scripts/calibration/overfitting_rigor.py` implements CPCV + purge + embargo
- `scripts/calibration/carry_universe_validation.py` used CPCV for Sprint 4
- `scripts/calibration/cpcv_classifier.py` separate module for classifier-validation cases
- `quant-backtest-rigor` skill documents the required defaults

This is one of our STRONGEST anti-pitfall defenses.

---

### 7. Backtest Overfitting

**Pitfall:** Researchers try many strategies / parameter combos and report the best. With enough trials, ANY strategy looks good by chance — even pure noise.

**LdP recommendation:** account for the number of trials:
- **Deflated Sharpe Ratio (DSR)** — deflates the observed SR by the variance-of-best-of-N
- **Probability of Backtest Overfitting (PBO)** — fraction of cases where the best in-sample variant fails to be top-half out-of-sample
- **Minimum Track Record Length (MinTRL)** — bars needed to declare SR > 0 at given confidence

DSR threshold: ≥0.95 to claim a strategy is real. PBO < 0.2 = informative selection process; PBO ≥ 0.5 = the selection process is no better than random.

**Gecko status:** **HONORED** — gauntlet shipped:
- Sprint 4.5 ran 4 PBO partition strategies on the carry-universe backtest
- DSR ≥ 0.95 is the verdict gate in `carry_universe_validation.py`
- `quant-backtest-rigor` skill enforces both metrics + MinTRL in any verdict block
- We have **8 validated nulls** as falsifier track record — we explicitly do not promote until the gauntlet clears

---

## Scorecard

| # | Pitfall | Gecko status | Where |
|---|---|---|---|
| 1 | Generalist approach | **HONORED** structurally | Sub-agent specialization in CLAUDE.md |
| 2 | Integer differentiation | **VIOLATED** (latent) | All voices feed raw indicator values |
| 3 | Inefficient sampling | **VIOLATED** (mitigated) | 5m time bars; breakout+volume primitive partially mitigates |
| 4 | Wrong labeling | **PARTIAL** (in-spirit honored) | exit_reason captured; not formalized as triple-barrier categories |
| 5 | Non-IID sample weights | **N/A** today | No classifier; binding only when learned models land |
| 6 | Leaky cross-validation | **HONORED** | CPCV + purge + embargo in calibration scripts |
| 7 | Backtest overfitting | **HONORED** | DSR ≥ 0.95 + PBO < 0.2 + MinTRL — Sprint 4.5 substrate |

**Strong: 3/7** (1, 6, 7) — the most-important ones for our current rule-based + LLM-graded architecture.
**Weak: 4/7** (2, 3, 4, 5) — but most of these are pure-ML pitfalls; we're closer to meta-labeling than classifier-training. They become binding when Sprint 28+ introduces learned models on the decision-vector substrate.

---

## Action items by sprint horizon

**Today (this sprint):**
- No immediate code change required.
- Cite this doc when proposing model-validation work.

**Sprint 28+ (when learned models touch the decision-vector substrate):**
- Pitfall 4 — change label shape to triple-barrier category before any classifier sees `bot_behaviors`
- Pitfall 5 — wire `mlfinlab.sample_weights` for sample-uniqueness weighting
- Pitfall 2 — frac-diff layer on price-derived features
- Pitfall 3 — evaluate dollar-bar pipeline as a feature alternative

**Permanent discipline (already in place):**
- Pitfall 6 — every backtest uses CPCV + purge + embargo via `overfitting_rigor.py`
- Pitfall 7 — every "win" claim requires DSR ≥ 0.95, PBO < 0.2, MinTRL met
- Pitfall 1 — never let one sub-agent do two specialist lanes; route through `staff-engineer`

---

## See also

- `.claude/skills/quant-backtest-rigor/SKILL.md` — operational checklist
- `scripts/calibration/overfitting_rigor.py` — CPCV/PBO/DSR implementations
- `scripts/calibration/carry_universe_validation.py` — full gauntlet example
- `private/strategy/2026-05-26-carry-universe-precommit-interpretation.md` — pre-commit verdict discipline (Op-1)
- `feedback_dogfood_loop` memory — pattern of validated nulls before any greenlight
