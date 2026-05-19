# S39 Backtest Phase 3 — Contamination-Controlled Cycle Design

**Date:** 2026-05-19 · **Owner:** `quant-analyst` (cycle methodology) +
`trading-strategist` (adverse-event curation). **Depends on:** Phase 1
`as_of` gate (`fd082c8`, branch `s39/backtest-phase1`); Phase 2 in-memory
reconstruction (`acf66f8`, branch `s39/backtest-phase2`).
**Companions:** `2026-05-19-backtesting-scoping-plan.md` §3, §4, §5, §6;
`2026-05-19-gecko-verdict-demo-comparison-design.md` (ledger schema,
adverse-event taxonomy, sample-size table).
**Mode:** read-only design pass. No code, no spend, no LLM probes.

---

## 0. Recommendation, up front

Phase 3 ships the **methodological wrapper** around the Phase 0–2 engine,
not new engine code: a curator workflow that proposes a post-cutoff window,
filters it for obscure adverse events, runs a cold-panel contamination
probe, and — only if the probe comes back clean — pre-registers a cycle
against the immutable JSONL ledger schema from #128. Two scripts
(`select_window.py`, `contamination_probe.py`), one pre-registration
template, one named seam on `run_trade_panel_with_retrieval`
(`ablate_entities: bool`), one new metric (`ablation_consistency_rate`).
**Hard gate: no Phase 3 BPAR number is quotable until (a) the
contamination probe transcript is recorded in the ledger with a
"clean" verdict, (b) the pre-registration block is committed before
the first decision lands, and (c) the cycle reaches ≥10 adverse-event
pools (per #128 §3.2).** Sub-10, language is "directional
illustration only."

---

## 1. The contamination problem, stated precisely

**Claim:** an LLM-verdict backtest measures *what the panel knows about
the test period*, not *what the corpus + reasoning produce.* On any
window inside the panel models' training data, "good" verdicts may be
recall, not analysis. The published number would be confident and
invalid — strictly worse than no number (scoping plan §3).

**Operational signature.** A contaminated result and a clean result are
distinguishable *only by direct probe*, not by examining the BPAR alone:

| Observation | Interpretation |
|---|---|
| High BPAR + cold panel (no corpus) narrates pool outcomes when probed | **Contaminated.** The "win" is hindsight; the verdict path replays training data. Burn the window. |
| High BPAR + cold panel professes ignorance about the pools when probed | **Clean signal.** Reasoning + corpus produced the calls. Quotable subject to N. |
| Low BPAR + cold panel ignorant | **Clean null.** Underpowered or genuinely no edge — say which. |
| Low BPAR + cold panel narrates outcomes | **Burned and Gecko lost anyway** — even with hindsight access, the production path missed. Diagnostic, not publishable. |

The probe in §5 is what assigns each cycle to a row of that table.
Without it, every backtest number lives in the first row by default
risk.

---

## 2. Window selection — the primary control

**Claim:** the admissible window is bounded below by the *latest*
training-data cutoff across every model in the panel, with a defensive
buffer. Outside that band, no controls can save a number; inside it,
the other three controls become meaningful.

### 2.1 Cutoff bookkeeping

`gpt-4o-mini` and the panel's pro-tier models have published training
cutoffs in the **2024-Q3 → 2025-Q1** band (scoping plan §3 cites
"~2024–2025"). The exact dates drift per model version and are vendor-
announced; the curator script reads them from a tracked config — not
from memory.

```yaml
# packages/gecko-core/src/gecko_core/backtest/model_cutoffs.yaml
# Updated whenever a panel model version changes. The MAX of these
# defines the lower bound of the admissible window.
gpt-4o-mini-2024-07-18: 2023-10-01
gpt-4o-mini-2024-12: 2024-06-01   # placeholder — confirm at update
# pro-tier entries follow same shape
```

### 2.2 Admissible window — the default

**Default lower bound: max(cutoff over all panel models) + 90 days
buffer.** The buffer absorbs (a) post-cutoff leak via system-prompt
context, RLHF samples, and post-training data shaping, (b) headline
events that get backfilled into model knowledge through fine-tunes.
**Default upper bound: T − holding_window − 30 days** so every decision
in the cycle has settled outcomes by curation time.

### 2.3 Re-evaluation rule

When any panel model version changes (`PANEL_MODEL_VERSION` env or
config), every prior cycle's window must be re-checked against the new
cutoff. If a prior cycle now sits inside the new model's training data,
its result is **demoted to "stale baseline"** in `_trend.json` — not
deleted (immutability), but flagged non-comparable. Model updates do
not silently invalidate the ledger; they annotate it.

### 2.4 Falsification rule (the cycle does not run)

If the admissible window contains **< 10 adverse-event pools after the
obscurity filter (§3)**, the cycle does not run. Reporting an
underpowered cycle as a "directional illustration" is acceptable per
#128 §3.2, but only down to the N ≥ 1 floor; below that, there is
nothing to illustrate. The correct, honest behaviour is to defer the
cycle until the admissible window has accreted enough events, or to
expand the obscurity threshold (recorded as a parameter, not a silent
relaxation).

---

## 3. Adverse-event obscurity filter

**Claim:** within the admissible window, headline events leak through
training data even when nominally post-cutoff (press archives, social
media, secondary articles). The obscurity filter restricts the cycle
to long-tail events whose pre-training-data signal is plausibly near
zero. Adverse-event **taxonomy is reused verbatim from #128 §1.2**
(depeg / utilization spiral / yield collapse / protocol incident);
the filter sits on top, not in place of it.

### 3.1 Screening rules (curator-applied, blind to outcome)

For each candidate pool that hit a #128-defined adverse event in the
admissible window, compute the following obscurity signals **without
reading the event narrative** (to avoid prejudging):

| Signal | Source | Default threshold (long-tail) |
|---|---|---|
| Mainstream-press hit count | Google News search count for `"<protocol>" "<event-keyword>"` within ±7d of event | ≤ 5 results |
| Wikipedia article on protocol | en.wikipedia.org existence | absent OR stub (<2 KB) |
| Tweet / X volume | post-cutoff archive index (e.g. communityarchive, public Tweet datasets) — count of posts mentioning protocol within ±7d of event | ≤ 200 |
| Post-cutoff news-index hits | a fixed news API queried for the protocol name over the event window | ≤ 10 |
| DeFiLlama protocol TVL rank at event time | DeFiLlama `/protocols` snapshot ≤ T | ≥ 50 (i.e. NOT a top-50 protocol) |

A pool passes the filter if it clears **at least 4 of 5** signals at
the default thresholds. The thresholds are pre-registered per cycle
(§6) — adjusting them mid-cycle is a new cycle.

### 3.2 Methodological flag — the alternative

The obscurity filter has a defensible alternative the curator should
weigh: **negative-control inclusion** — deliberately include a small
number of *headline* adverse events as a contamination sanity check.
If Gecko's BPAR on the obscure subset matches its BPAR on the
headline subset, the obscure-subset result is more credible (the
panel is not running on hindsight in either case). If headline-subset
BPAR is materially higher, that is direct evidence the panel benefits
from training-data leakage and the obscure-subset number is the
ceiling of what is honest. Negative controls are **opt-in per cycle**
and recorded in the pre-registration as a separate stratum, never
mixed into the headline BPAR.

---

## 4. Entity-ablation arm (secondary)

**Claim:** ablation distinguishes *recall of named entity outcomes*
from *reasoning over on-chain facts*. If a verdict survives stripping
the protocol/token names, the decision is reasoning-backed; if only
the named arm "calls" the adverse event, the named arm was running on
recall.

### 4.1 What gets stripped

The ablation transforms the panel input *before retrieval and before
the panel call*:

| Field | Named arm (default) | Ablated arm |
|---|---|---|
| `idea` string | `"deposit USDC into Kamino main USDC reserve"` | `"deposit USDC into a Solana lending market, target reserve <ID>"` |
| `protocol` | `"kamino"` | `"unspecified_lending_v1"` (or stable opaque token per pool) |
| Pool ID in chunk render | unchanged (opaque hash) | unchanged |
| On-chain facts (APY, TVL, utilization, chain, contract address) | unchanged | unchanged |
| Token symbols in canon-citation matchable text | unchanged in retrieval; the redaction is on the input, not on chunks |

The redaction is **mechanical and reversible** (curator stores a
per-pool name→token mapping in the ledger). It applies to the
panel's user-facing input only; canon retrieval runs against the
real corpus so canon citations are still surfaced — but the named-arm
and ablated-arm canon slates will diverge because the embedded query
differs. **This is acknowledged cost**: ablation strips
canon-citation matchability for protocol-named canon (scoping plan
§3 already flags this); the ablated arm is a *secondary* signal, not
a co-equal one. Per-cycle, the ablation arm runs on the *same* set of
admissible adverse-event pools as the named arm — paired by
construction.

### 4.2 Read

| Named arm | Ablated arm | Read |
|---|---|---|
| declines | declines | reasoning — consistent verdict survives ablation |
| declines | acts | recall — the named arm needed the entity to "know" |
| acts | declines | over-redaction or ablation noise — re-examine |
| acts | acts | reasoning (or both wrong consistently) — read PnL |

`ablation_consistency_rate` (§8) is the headline summary.

---

## 5. Contamination probe protocol

**Claim:** before any cycle runs, ask the panel — with NO corpus and
NO injected market chunks — what it knows about events around the
candidate pools. If it volunteers outcomes, the window is burned.
This is the single cheapest check that distinguishes the two top rows
of the §1 table.

### 5.1 Procedure

`scripts/backtest/contamination_probe.py` does, per candidate pool in
the (already-obscurity-filtered) admissible set:

1. Strip all corpus + reconstructed-market injection. The panel sees
   the date and the **named** protocol/pool only (the probe targets
   the named arm — the conservative case).
2. Issue the probe prompt:

   > "It is `<T>`. Without using any tools or external data, what do
   > you know about `<protocol>` and its `<pool_id>` pool around this
   > date? Specifically: any incidents, depeg, utilization stress,
   > yield anomalies, or protocol issues you are aware of from
   > pre-existing knowledge. If you do not know, say so. Do not
   > speculate; do not search."

3. Record the verbatim response to a probe transcript file.
4. Apply the **burn criterion** (next).

### 5.2 Burn criterion (quote-verbatim for the curator)

> A window is **BURNED** if, for any adverse-event pool in the
> obscurity-filtered admissible set, the cold panel response
> spontaneously names the realised adverse-event class (depeg /
> utilization spiral / yield collapse / protocol incident) for that
> pool or its host protocol within the window. A window is
> **CLEAN** otherwise. Hedged language ("I'm not aware of specific
> incidents but..."), generic protocol descriptions, and explicit
> "I don't know" answers do NOT burn the window.

The criterion is intentionally **asymmetric and conservative**: only
spontaneous naming of the realised event class burns. Generic risk
talk ("any lending pool can face utilization stress") is allowed —
it is the *type of reasoning Gecko also performs* and is not
hindsight.

### 5.3 Recording

The probe transcript is hashed (sha256 of the JSONL of
`{pool, prompt, response, model_version}`) and the hash + verdict
written into the pre-registration block (§6). The transcript itself
is committed to `tests/demo/yield_verdict_runs/probes/<cycle>.jsonl`
**before** the first decision lands. After the fact, the hash chain
proves the probe predated the result.

### 5.4 Cost

Probe N = obscurity-filtered candidate count (typically ≤ 30 per
cycle). Each call is short, no retrieval, no panel debate — single
model call. Total: under 30 model calls per cycle; <$0.50 even on
pro-tier models. The probe is the cheapest control on this list.

---

## 6. Pre-registration template

**Claim:** committing a structured block *before* the first decision
lands is what makes the cycle result quotable. The template is the
literal markdown that prepends the cycle ledger. Adding a field after
the fact = a new cycle, not an edit.

`tests/demo/yield_verdict_runs/_preregistration_template.md`:

```markdown
# Cycle pre-registration — <cycle_id>

**Committed at:** <ISO-8601 timestamp, before first decision>
**Mode:** backtest (Phase 3 contamination-controlled)
**Ledger file:** tests/demo/yield_verdict_runs/<cycle_id>.jsonl
**Engine commit:** <git sha of gecko-core at curation time>
**Corpus snapshot:** <chunks collection count + index version>

## Window
- admissible_lower: <YYYY-MM-DD>          # max(model cutoffs) + 90d
- admissible_upper: <YYYY-MM-DD>          # T − holding_window − 30d
- holding_window_days: 14                  # reuse #128 §4

## Panel models + cutoffs
- gpt-4o-mini: <version>, cutoff <YYYY-MM-DD>
- <pro-tier model>: <version>, cutoff <YYYY-MM-DD>

## Adverse-event taxonomy (verbatim from #128 §1.2 — not edited)
- depeg: principal stable >0.5% off peg sustained >6h
- utilization_spiral: lending util >95% for >24h
- yield_collapse: realised APY drops >50% vs decision-time APY in holding window
- protocol_incident: exploit / governance freeze / oracle failure

## Obscurity filter parameters
- thresholds: { press_hits: <=5, wikipedia: absent_or_stub,
                tweets: <=200, news_index: <=10, tvl_rank: >=50 }
- pass_rule: clears >= 4 of 5
- negative_controls_included: <true|false>   # §3.2

## Contamination probe
- script: scripts/backtest/contamination_probe.py @ <git sha>
- transcript_path: tests/demo/yield_verdict_runs/probes/<cycle_id>.jsonl
- transcript_sha256: <hash>
- verdict: <CLEAN|BURNED>
- # If BURNED: cycle does not proceed. Block is committed for the record.

## Sample-size targets (from #128 §3.2 — verbatim, not edited)
- target_adverse_event_N: <integer>          # 10 / 25 / honest tier
- claim_tier_at_N:
    "<10":  "directional illustration only"
    "10-25": "early signal, wide CI, not yet conclusive"
    ">=25":  "defensible, bounded to pre-registered defs + corpus state"

## Ablation arm
- enabled: <true|false>                       # §4
- redaction_map_path: tests/demo/yield_verdict_runs/ablation/<cycle_id>.json

## Primary metric
- name: BPAR (Bad-Pool Avoidance Rate)
- test: paired McNemar (exact), two-sided α=0.05
- ci: paired bootstrap on BPAR difference, 10k draws
- decision_threshold: "Gecko wins" iff McNemar p<0.05 AND bootstrap CI
                       on (BPAR_gecko − BPAR_baseline) excludes 0 AND
                       hit_rate degradation < 5 percentage points
                       (composite per #128 §1.3)

## Supporting metrics
- hit_rate, decline_precision, pnl_bps (paired bootstrap CI),
  verdict_stability (noise floor), ablation_consistency_rate (§8).

## Immutability
- ledger hash chain: each row writes prev_hash = sha256(prev_row_canonical_json).
- prev_hash for row 0 = sha256(pre-registration block).
- post-window patch is allowed ONCE per decision_id (outcome fields only,
  per #128 §2.3); patches form a separate signed-edit row, not in-place
  mutation.
```

---

## 7. Sample size + the test

**Claim:** the test, the power table, and the honest-claim tiers are
all reused verbatim from #128 §3 — the binding constraint in a
backtest is the *admissible post-cutoff obscure-event population*,
not calendar time.

### 7.1 Test (unchanged from #128 §3.1)

- **Primary:** McNemar exact (two-sided, α=0.05) on discordant
  decline-vs-act pairs over the adverse-event subset; paired
  bootstrap 95% CI on the BPAR difference (≥10k draws). **Report the
  interval, not the point estimate** (standing rule).
- **Supporting:** paired bootstrap CI on hit-rate, decline-precision,
  PnL bps. Wilcoxon signed-rank on PnL (skewed).
- **Verdict stability** measured at cycle start, reported as the
  noise floor — any BPAR delta smaller than the band is *not signal*.

### 7.2 Power table (verbatim — #128 §3.2)

| To detect (BPAR baseline → Gecko) | Power 0.80 needs ~ | Implied total decisions* |
|---|---|---|
| 0.40 → 0.80 (large effect) | ~25 discordant pairs | ~150–250 decisions |
| 0.50 → 0.75 (moderate) | ~45 discordant pairs | ~300–450 decisions |
| 0.55 → 0.70 (modest) | ~110 discordant pairs | ~700+ decisions |

\* ~12% adverse-event base rate; disagreements concentrate on the
adverse subset.

### 7.3 Backtest is instant *in calendar time only*

A retrospective cycle has no holding-window wait — outcomes are
already known at curation. **But the binding N is not calendar
throughput; it is the size of the obscurity-filtered post-cutoff
adverse-event population.** That population is finite, grows only as
the cutoff slides forward, and at default 2024-Q3+90d lower bound is
realistically in the **dozens, not hundreds**. The honest tiers from
#128 §3.2 apply unchanged:

- **N < 10:** directional illustration only. No rate, no CI, no
  "X% better."
- **10–25:** early signal, wide CI shown, McNemar p reported, framed
  underpowered-not-null.
- **≥25 with McNemar p<0.05 and CI excluding 0:** the first
  defensible "Gecko mode improved BPAR" claim — bounded to the
  pre-registered adverse-event definitions and the corpus state at
  that cycle.

### 7.4 Stratification

Because the admissible set is small, cycles **must not aggregate
across cycles to inflate N**. Each cycle is a separate
pre-registration; the `_trend.json` summary tracks them as a series.
Pooling across cycles is allowed only as a separately pre-registered
meta-analysis with its own ledger entry (deferred beyond Phase 3).

---

## 8. Metrics — reuse + one addition

**Claim:** Phase 3 reuses the existing metrics surface and adds
exactly one Phase-3-specific function.

### 8.1 Reuse (no new code)

- **Ledger schema:** `tests/demo/yield_verdict_runs/<cycle_id>.jsonl`
  per #128 §2.3 — identical row shape (decision_id, arm, ts_decided,
  pool_id, protocol, quoted_apy, verdict, decision, holding_window,
  outcome, settled).
- **Primary:** BPAR (#128 §1.2).
- **Supporting:** decision hit-rate, decline-precision, PnL bps with
  bootstrap CI (paired), verdict stability noise floor. Functions in
  `packages/gecko-core/src/gecko_core/trade_agent/backtest/metrics.py`
  — `hit_rate`, `pnl_pct`, `sharpe_annualized`, `max_drawdown_pct`
  already exist (123 LOC); the BPAR + bootstrap + McNemar helpers
  land alongside the #128 forward harness and Phase 3 consumes them.

### 8.2 Phase-3-only metric — `ablation_consistency_rate`

```python
def ablation_consistency_rate(
    paired_decisions: Sequence[AblationPair],
) -> AblationConsistency:
    """Fraction of adverse-event decisions where the named-arm verdict
    and the ablated-arm verdict agree on the decline-vs-act axis.

    A high rate (e.g. ≥0.80) is reasoning evidence: stripping the
    entity names does not flip the call. A low rate is recall
    evidence: the named arm depended on entity-bound knowledge.

    Returns the point estimate, a paired bootstrap 95% CI (≥10k
    draws), and the underlying disagreement count. Lead with the
    interval per the standing rule.
    """
```

`AblationPair` carries `(decision_id, named_decision, ablated_decision,
adverse_event_flag)`. The metric is computed over `adverse_event_flag
== True` pairs only — consistency on non-adverse pools is uninformative
about contamination. Lives next to the existing metrics. Documented
here; **not implemented in this doc**.

---

## 9. Public-benchmark posture

**Claim:** Phase 3's result is the *caveated companion* to the forward
track record, never the standalone headline.

**Trust stack — verbatim from scoping plan §6:**

> (1) the forward immutable track record;
> (2) the S37 6/6 ship-gate — verdict *quality*, proven at N=57,
>     publishable today;
> (3) the contamination-controlled backtest — fast, caveated.

Phase 3 occupies position (3). It is publishable, with caveats:
window bounds + cutoffs + obscurity-filter parameters + probe
verdict + N must accompany any BPAR claim. The pre-registration
discipline + immutable ledger + hash chain (§6) are what make it
benchmark-grade and not internal telemetry — a skeptic must be able
to re-cut the same ledger and reach the same number, and must not be
able to detect a moved goalpost.

Inference-cost-vs-return stays **internal economics telemetry only**
(scoping plan §4; CLAUDE.md: no per-operation cost to users). It is
not part of the public benchmark surface.

---

## 10. Phase 3 deliverables (next session builds)

| # | Path | Purpose |
|---|---|---|
| a | `scripts/backtest/select_window.py` | Emits an admissible-window proposal: lower/upper bounds from cutoff config + buffer + holding-window. Iterates candidate pools that hit a #128-defined adverse event in-window, applies the obscurity filter (§3), prints a per-candidate trace (signal-by-signal pass/fail) so curator decisions are auditable. Output: a JSON proposal file the curator commits or rejects. |
| b | `scripts/backtest/contamination_probe.py` | Runs the §5 probe over the obscurity-filtered candidate set. Prints `CLEAN` or `BURNED` per the §5.2 criterion. Writes transcript JSONL + sha256 to the path referenced by the pre-registration block. Exits non-zero on `BURNED` so a wrapper script halts before the cycle starts. |
| c | `tests/demo/yield_verdict_runs/_preregistration_template.md` | The literal markdown block from §6, parameterised with `<...>` placeholders. The cycle wrapper renders it once per cycle and commits before the first decision lands. |
| d | Seam on `run_trade_panel_with_retrieval` | Add `ablate_entities: bool = False` (and optional `entity_map: dict[str, str] | None = None`). When True, the `idea` and `protocol` strings are redacted per §4.1 **before** retrieval — so canon matching is consistent across both arms *within* a cycle (named arm uses one query; ablated arm uses the redacted query; chunk store is the same). Production callers omit the param; default behaviour is byte-identical to today. **Documented here; not implemented in this doc.** |
| e | `ablation_consistency_rate` in `trade_agent/backtest/metrics.py` | Signature + docstring per §8.2. Pure function over `Sequence[AblationPair]`. Returns point + paired-bootstrap CI + disagreement count. **Documented here; not implemented in this doc.** |

---

## 11. Out of scope for Phase 3

- Live forward-demo execution — owned by the #128 forward track,
  separate workstream.
- `bb backtest` CLI polish (deferred beyond S39 per scoping plan §5).
- Multi-protocol sweeps (deferred beyond S39).
- Any `gecko-mcpay-app` surface ("compare your agent" UI — deferred).
- Cross-cycle meta-analysis pooling (allowed only as a separately
  pre-registered cycle of its own; not in Phase 3).
- Pyth OHLCV reconstruction (Phase 9.5 per Phase 2 doc §4).
