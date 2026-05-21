# chart_analyst momentum-acceleration prompt amendment (S40-LAB-#11)

**Mode:** prompt-amendment proposal, read-only diagnosis + dry-run prompt diff.
No code changes in this commit; the diff is text, with a one-test validation
plan attached.
**Owner:** `ai-ml-engineer`. Branch: `s39/okx-contest-entry`.
**Companion docs:** `lab-validated/2026-05-20-local-panel-voices-spec.md` (the v0.1
contract that froze the chart_analyst prompt), `2026-05-20-panel-act-rate-on-momentum-spot.md`
(the diagnosis that motivated the lab).
**Memory anchors:** `feedback-prompt-iteration-plateau`, `feedback-lighter-tests`,
`project-local-lab-strategy-2026-05-20`.

---

## 0. Bottom line, up front

- **Diagnosis:** of 36 `local_panel` turns logged today, **34 declined; 33 of those
  on `chart_below_threshold`**. The chart voice is the *only* meaningful gate the
  lab is exercising. Raising the chart floor to 0.85 with the current prompt
  would push acts from 2 → ~0-1 in a comparable window. The current prompt's
  confidence ceiling is being hit at 0.85 only on *exceptional* alignment per
  the prompt anchors (`>0.80 = exceptional alignment — use sparingly`).
- **The "fewer entries" risk is real and quantifiable.** Of the 2 chart-bullish
  calls in `local_memory.jsonl`, confidences were `[0.75, 0.85]`. Only **one**
  cleared a 0.85 floor. Raise to 0.85 *and* the prompt's own anchor language
  caps the model at "use sparingly" — that's a fire-rate cliff, not a slope.
- **The fix is asymmetric prompt language.** Add a *positive criterion*
  (a named, structured "momentum-acceleration" setup class) that re-anchors
  `≥0.85` to a concrete observable pattern, instead of relaxing any abstain
  rule. This is the same shape as the existing "Confidence anchors" block —
  we're not weakening it, we're adding one named anchor where the model is
  currently rounding down.
- **Ship recommendation: YES, ship tonight** — see §6 for the gating evidence
  and §5 for the test that runs in < 60s with no live spend.

---

## 1. Diagnosis — what the chart voice has been saying

### 1.1 Volume

| Source | rows | chart calls captured |
|---|---|---|
| `contest_bot/local_memory.jsonl` | 5 panel turns | 5 chart_analyst opinions w/ reasoning + confidence |
| `contest_bot/artifact_20260520.jsonl` | 36 `local_panel` rows | summaries only (rule + action), no per-voice text |

Per-voice text isn't ledgered in the artifact log today — only the coordinator
summary lands there. So per-opinion diagnosis runs on **N=5** from
`local_memory.jsonl`. Action-distribution diagnosis runs on **N=36** from the
artifact log. Both are small. Treat verdict-count distinctions below as
*directional*, not statistically significant (`feedback-prompt-iteration-plateau`:
±0.10 swings at small N are noise; we use the larger-N action distribution as
the dominant signal).

### 1.2 The dominant signal — coordinator-side

From `artifact_20260520.jsonl`:

```
local_panel actions: {'decline': 34, 'act': 2}
rule_fired:          {'chart_below_threshold': 33, 'all_voices_aligned': 2, 'risk_veto': 1}
```

**33 of 34 declines came from chart.** Risk vetoed once. Memory has not
contradicted once (it's in cold-start abstain — pinned in
`lab-validated/2026-05-20-local-panel-voices-spec.md` §7.7). The chart voice is
the *single* governor of the lab's fire rate.

### 1.3 Per-opinion sample (N=5, the only granular signal we have)

| instrument | verdict | confidence | reasoning |
|---|---|---|---|
| RAY | bullish | 0.75 | "Recent uptrend with breakout confirmation and strong volume." |
| PYTH | bearish | (n/a) | "Recent downtrend with a confirmed breakout below the trailing low." |
| ORCA | bearish | (n/a) | "Recent downtrend with a confirmed breakout below the trailing low." |
| WIF | bullish | 0.85 | "Recent breakout with strong volume and uptrend in both short and longer timeframes." |
| MEW | abstain | 0.00 | "24h range is below 1%, indicating range-bound chop." |

- **Bullish confidences (n=2):** [0.75, 0.85]. Mean 0.80. **One** clears 0.85.
- **Dominant abstain reason:** "range-bound chop" (1/1 in sample; not enough
  to call it dominant rigorously, but the *prompt structurally biases here* —
  see §1.4).
- **No "thin liquidity" abstain observed** in the sample. The synthetic-zero-vol
  defense has not had a real-data trigger to exercise.
- **No "fewer than 24 bars" abstain observed.** onchainos klines have been
  returning full windows.

### 1.4 Why the model is anchoring at 0.75-0.85, not 0.85+

The existing chart_analyst system prompt
(`contest_bot/voices/chart_analyst.py:97-101`) carries this anchor block:

```
Confidence anchors:
  0.50-0.60 = soft lean (one of the five gradings supports the call)
  0.60-0.70 = clean lean (two of five align)
  0.70-0.80 = strong setup (three of five align, including volume)
  >0.80     = exceptional alignment (four+ of five) - use sparingly
```

The model is reading "use sparingly" as **"do not emit > 0.80 unless I have
something special to point to"** — and it has no language for what that special
thing is. So even when 4-of-5 align (the WIF case: short uptrend + long uptrend
+ breakout + volume + normal-drift), it stops at 0.85. The anchor wants
"exceptional" but doesn't name an observable that *justifies* exceptional.

This is the prompt-engineering fix: **name the observable.** The model needs a
concrete, falsifiable pattern label (not just "use sparingly") to feel licensed
to emit ≥0.85.

---

## 2. Proposed prompt amendment — momentum-acceleration as a positive criterion

### 2.1 Design constraints (the wedge — non-negotiable)

Re-pinning so the diff stays inside the lines:

- "abstain when uncertain" — **kept verbatim**, no edit.
- "do not invent patterns" — **kept verbatim**, no edit.
- "penalize thin liquidity, gap fills, weekend low-vol, range-bound chop" —
  the abstain protocol block stays **byte-identical**.
- Synthetic-zero-vol probe must still trigger abstain — defended at two layers:
  (a) the prompt's `>4 zero-vol bars → abstain` line is untouched, and
  (b) the response-side override at `chart_analyst.py:191-209` is unchanged.

The amendment is **strictly additive**. It introduces a new *positive*
criterion. It does not weaken any abstain rule, lower any threshold, or relax
any "do not invent" clause.

### 2.2 The new criterion — "Momentum acceleration"

Frame: **momentum acceleration is a specific, observable, six-cell-test setup
class that — when ALL six cells fire — licenses confidence ≥ 0.85.** This
re-anchors "exceptional alignment" to a falsifiable pattern instead of a
vague "use sparingly" instruction.

The six cells (drafted so each maps to an existing data field in the user
prompt, no new inputs needed):

1. **Last 3 bars all green** (close > open on each of bars t-2, t-1, t).
2. **Volume rising over those 3 bars** (vol[t] > vol[t-1] > vol[t-2]; OR
   vol[t] > 1.5 × median(last 6 vol)).
3. **Fresh higher-high** — bar t's high strictly above the trailing-24-bar
   high prior to bar t (the model already grades this; the criterion sharpens
   it to "fresh", i.e. newly crossed within the last 3 bars).
4. **Above the 24h mid-point** — current close > midpoint of (24h high, 24h
   low). The model already has 24h range %; midpoint is derivable.
5. **24h range ≥ 2%** (not tight chop). This is already a soft tier in the
   prompt; we make it a hard cell of the criterion.
6. **Not in any abstain condition** (full abstain protocol holds — this cell
   is the wedge guard: momentum-acceleration *cannot* override thin-liquidity,
   stale feed, weekend low-vol).

When 5-of-6 fire → confidence may reach 0.80-0.85 ("strong momentum
acceleration"). When 6-of-6 fire → confidence may reach 0.85-0.92
("textbook momentum acceleration"). > 0.92 stays reserved.

### 2.3 Why naming-the-pattern works

`feedback-prompt-iteration-plateau` warned that gpt-4o-mini rounds toward
caution on any *defer-related* instruction. The inverse also holds: it rounds
toward caution on any *high-confidence* instruction unless given a concrete
hook to anchor on. The current "exceptional alignment — use sparingly" reads
like a soft cap. A named, six-cell, falsifiable pattern (with the abstain
protocol still dominant) reads like a license, not a cap, and the model will
emit ≥0.85 *only when the named cells fire*.

---

## 3. Risk analysis — where this can go wrong

### 3.1 The failure mode I am most worried about

**False-positive bullish on terminal-pump chop.** A token in a 4-8% chop band
can produce, within a single 30-bar window, six bars that look like
"momentum acceleration": three green closes (chop high-leg), rising volume
(retail piling in), fresh higher-high (the chop ceiling getting tagged),
above midpoint (yes — it's the high leg), 2%+ range (chop band is wide enough),
no abstain (volume is real). All six cells fire. Model emits 0.85+.
**But the next bar is the chop reversal, and we just bought the top.**

This is the textbook "buying the breakout that wasn't" — and it's a real
short-horizon failure on Solana memecoins. The lab universe (RAY, BONK, KMNO,
WIF, MEW, etc.) has multiple instruments where this pattern fires several
times per 24h.

**Mitigations the amendment carries:**

- The "fresh higher-high" cell (cell 3) requires the trailing-24-bar high to
  be newly crossed *within the last 3 bars*. A chop ceiling tagged repeatedly
  is NOT a fresh higher-high — by the second touch, the trailing-24-bar high
  has been incorporated, so the "fresh" qualifier fails. This is the
  load-bearing cell.
- The 5-of-6 vs 6-of-6 split lets the model express "strong but not textbook"
  at 0.80-0.85, which still trips the new 0.85 coordinator floor only on
  6-of-6 — keeping the cliff steep enough that chop-induced false-positives
  need to clear a high bar.
- The abstain protocol is dominant; cell 6 is the explicit guard. Range < 1%
  still hits abstain *before* the momentum-acceleration check runs.

**Mitigations the amendment does NOT carry (acknowledged residual risk):**

- The amendment cannot distinguish a *real* breakout from a *terminal-leg
  chop tag* on the 5m bar grain alone. That distinction needs either (a) a
  longer-horizon trend confirmation (which the prompt's "trend over last 24
  bars" already covers, but at lower weight than the 6-bar trend), or
  (b) volume-profile context (which the lab does not have). The lab v0.1
  ships without it; v0.2 may add a "is the breakout level consistent with
  the 24-bar trend direction?" cell as cell 7.

### 3.2 Synthetic-zero-vol probe still triggers abstain — proof by reading

The amendment text is added **after** the existing ABSTAIN PROTOCOL block
and **before** the OUTPUT block. The abstain protocol's six conditions
remain the first-evaluated gate. The momentum-acceleration cell 6 explicitly
re-asserts "abstain protocol takes precedence." The response-side override
(`chart_analyst.py:192-209`, the `_count_zero_volume_bars > 4` forced abstain)
is **completely independent of the prompt** — it inspects the bar payload
directly, not the model's verdict. A model that ignores both the abstain
protocol AND cell 6 still hits the response-side override and is forced to
abstain on a zero-vol synthetic.

### 3.3 What I am NOT worried about

- **Range < 1% chop** — the abstain protocol catches this before any positive
  criterion fires. The MEW row in §1.3 is the proof; the existing prompt
  correctly returned abstain on a 0.8% range.
- **Weekend low-vol** — the existing weekend clause is untouched; the
  amendment does not override it.
- **Cold-start memory** — the amendment does not touch memory_voice; cold-start
  abstain there remains the right behavior (`spec §7.7`).
- **Coordinator rule shape** — coordinator stays five lines of pinned Python
  per `feedback-prompt-iteration-plateau`. The 0.85 floor is a single numeric
  change in `coordinator_rules.py`, separate from this prompt diff.

---

## 4. Concrete prompt diff — exact text to ADD

### 4.1 Where it goes

In `contest_bot/voices/chart_analyst.py`, inside `_SYSTEM_PROMPT`
(currently lines 44-102):

- **Insertion point:** immediately after the ABSTAIN PROTOCOL block
  (after the line ending `'neutral' is NOT an abstain; the coordinator
  treats it as a real call.`) and **before** the `DO NOT` block.
- **Unchanged:** the ROLE, INPUTS, WHAT TO GRADE, ABSTAIN PROTOCOL, DO NOT,
  OUTPUT, and Confidence anchors sections all remain byte-identical except
  for the new MOMENTUM ACCELERATION block inserted between ABSTAIN PROTOCOL
  and DO NOT.

### 4.2 Verbatim addition (this is the entire diff)

```
MOMENTUM ACCELERATION (positive-criterion lens — does NOT override abstain)
A specific, observable setup class. When a setup fires this pattern, the
confidence anchor for "exceptional alignment" applies; do NOT use this lens
to invent patterns that don't fire all six cells. Check each cell independently
on the bars in front of you:
  Cell 1 — Last 3 bars all green: close > open on each of t-2, t-1, t.
  Cell 2 — Volume rising over those 3 bars: vol[t] > vol[t-1] > vol[t-2], OR
           vol[t] > 1.5x the median of the last 6 bars' volume.
  Cell 3 — Fresh higher-high: bar t's high strictly above the trailing-24-bar
           high computed BEFORE bar t, AND the crossing happened within the
           last 3 bars (not a repeated tag of an old ceiling).
  Cell 4 — Above 24h midpoint: current close > 0.5 * (24h high + 24h low).
  Cell 5 — Not tight chop: 24h range >= 2%.
  Cell 6 — Abstain protocol clean: none of the abstain conditions above hold.
           If any abstain condition fires, the momentum-acceleration lens is
           NOT applicable and you MUST return abstain.

Momentum-acceleration confidence licensing (when verdict='bullish'):
  - 6 of 6 cells fire -> confidence may reach 0.85-0.92 ("textbook acceleration").
  - 5 of 6 cells fire -> confidence may reach 0.80-0.85 ("strong acceleration");
    name which cell failed in reasoning.
  - <= 4 of 6 cells fire -> momentum-acceleration is NOT the setup; fall back
    to the standard Confidence anchors below.

This lens does NOT relax any abstain rule. It only re-anchors what "exceptional
alignment" looks like so the model has a falsifiable pattern to point at when
emitting confidence >= 0.85. Do NOT invent acceleration that isn't on the bars.
```

### 4.3 What the existing Confidence anchors block becomes

**Unchanged.** The existing anchors stay (`0.50-0.60 = soft lean`, ...,
`>0.80 = exceptional alignment - use sparingly`). The new MOMENTUM ACCELERATION
block is an *additional* anchor that **specializes** the "exceptional alignment"
band by naming what licenses it. When momentum-acceleration cells do not fire,
the model falls back to the existing anchors — including the existing soft cap.

### 4.4 Token-budget impact

The new block is ~280 tokens (system prompt grows from ~440 to ~720 tokens).
Per `lab-validated/2026-05-20-local-panel-voices-spec.md` §7.6, the per-call
cost (~300 tok in + 100 tok out at gpt-4o-mini OpenRouter rates) goes to
~580 tok in + 100 tok out — roughly **+50% input tokens, +20% per-call cost,
~+1.5x over the 30h contest window: +$0.15**. Well within budget.

---

## 5. Validation plan — one test before deploy

### 5.1 Fixture additions (under `contest_bot/tests/`)

Reuse the synthetic-zero-vol fixture (already implied by the response-side
override; if not present as a literal fixture, add it). Add one new fixture:

**`fixture_momentum_acceleration_clean.py`** — a synthetic 30-bar window with:

- Bars 1-25: realistic noise around price 1.00 with healthy volume
  (~1000 units/bar), range 1.00 - 1.05.
- Bars 26-28: three green bars closing at 1.06, 1.07, 1.09 with volume
  1500, 2000, 2700 (strictly rising, each > 1.5x the 6-bar median).
- Bar 29-30: continuation, closing at 1.10, 1.11.
- 24h range computed: ~10% (passes cell 5).
- Trailing-24-bar high (bars 1-25): ~1.05. Bar 28's high = 1.09 (clears).
- 24h midpoint: ~1.05. Current close 1.11 (clears cell 4).
- All abstain cells clean: 30 bars, no zero-vol, fresh feed, 10% range.

**Expected:** chart_analyst returns `verdict="bullish"`, `confidence >= 0.85`.

### 5.2 Negative fixtures (must still abstain)

- **`fixture_zero_vol_synthetic.py`** — 30 bars where 5+ bars have vol=0,
  but bars 26-28 otherwise look like the acceleration pattern.
  **Expected:** abstain (either prompt-side or response-side override).
- **`fixture_tight_chop_with_3_green.py`** — 30 bars in 0.8% range; bars
  26-28 happen to be green with rising volume.
  **Expected:** abstain (range < 1% trips abstain protocol; cell 5 fails;
  cell 6 forces abstain).

### 5.3 Test runner

`contest_bot/tests/test_chart_analyst_momentum.py` (new), follows the
light-fakes pattern per `feedback-lighter-tests`. Use `model_construct` to
stub the OpenRouter client; run the **real prompt** through it; assert on
the verdict + confidence band. Three test cases, < 5s wall clock, costs $0
(uses recorded LLM fixtures, not live).

For one **live** probe before the contest: a single bb-research-style direct
call against OpenRouter with the clean acceleration fixture; record the
response in `tests/fixtures/`; if `confidence < 0.85`, the prompt amendment
needs hardening (likely the cell-3 "fresh" qualifier needs sharpening, or
the "may reach" language needs to become "should reach"). Budget: 1 LLM call,
~$0.0003.

### 5.4 Coordinator-floor change is a SEPARATE step

The 0.85 floor in `coordinator_rules.py` lands in a **separate commit** after
the prompt amendment validates. Do not bundle. The order is:

1. **This commit (docs only):** the proposal lands; no behavior change.
2. **Next commit (prompt only):** add the MOMENTUM ACCELERATION block to
   `_SYSTEM_PROMPT`; run the three fixture tests; observe `live_memory.jsonl`
   for one bot cycle (~10-20 polls); confirm at least one ≥0.85 emit on a
   clean acceleration setup, and that abstain rates on zero-vol/chop are
   unchanged.
3. **Then (coordinator floor):** raise the chart confidence floor from 0.6
   to 0.85 in `coordinator_rules.py`. This is the actual selectivity change.

Decoupling lets us roll back either lever independently.

---

## 6. Ship-tonight recommendation

**YES — ship the prompt amendment tonight; defer the 0.85 coordinator floor
to a separate commit after one validation cycle.**

Gating evidence:

1. **The current chart prompt is the gate's only governor.** 33/34 declines
   came from the chart. Tuning the chart prompt is the highest-leverage
   single change available.
2. **The amendment is strictly additive.** It cannot weaken any abstain rule
   by construction (§4.3). The synthetic-zero-vol response-side override is
   wire-isolated from the prompt (§3.2). The wedge ("abstain when uncertain,
   do not invent patterns") is preserved verbatim in the prompt; the new
   block explicitly reinforces it ("Do NOT invent acceleration that isn't
   on the bars").
3. **The failure mode (terminal-pump chop false-positive, §3.1) is bounded
   by cell 3 (fresh higher-high)** — the load-bearing cell that distinguishes
   a real breakout from a chop ceiling re-tag. If this cell holds in
   contest-week data, the amendment is safe; if it doesn't, we roll back to
   the byte-identical pre-amendment prompt (one git revert).
4. **Cost is bounded.** +50% input tokens, +$0.15 over the remaining contest
   window. Well within `lab-validated/2026-05-20-local-panel-voices-spec.md`
   §7.6's $0.30 cost ceiling.
5. **Validation is cheap and fast.** Three light-fakes tests + one $0.0003
   live probe. No live X402 spend, no PRD oracle changes, no shadow-mode
   contract changes.

**The single residual risk** is whether gpt-4o-mini honors cell 3's "fresh"
qualifier under pressure. The one live probe in §5.3 tests exactly that. If
it fails, harden the cell-3 language ("strictly the first crossing of the
trailing-24-bar high in the last 3 bars") and re-probe; that is a
two-iteration max budget per `feedback-prompt-iteration-plateau`.

**The single thing I am NOT willing to ship tonight without one more bot
cycle of evidence:** the 0.85 coordinator floor itself. Land the prompt;
let the bot run for 1-2 hours with the new prompt at the 0.60 floor;
confirm the bullish-confidence distribution shifts upward on real
acceleration setups (and stays low on chop); *then* tighten the floor.
That separation is the difference between a prompt regression and a
selectivity regression — both fixable, but in different commits.

---

## 7. Report-back summary

- **Proposed prompt addition (verbatim):** the MOMENTUM ACCELERATION block
  in §4.2, ~280 tokens, inserted between the ABSTAIN PROTOCOL and DO NOT
  sections of `_SYSTEM_PROMPT` in `contest_bot/voices/chart_analyst.py`.
- **Failure mode I am most worried about:** false-positive bullish ≥0.85 on
  a *terminal-leg chop tag* that happens to fire all six cells (three
  green closes + rising volume + tagging an old chop ceiling + above
  midpoint + 4-8% range + no abstain). Cell 3's "fresh" qualifier is the
  load-bearing defense; if gpt-4o-mini honors it, the amendment is safe.
  If it does not, terminal-pump chop reads as bullish 0.85 and we buy tops.
- **Ship tonight:** **YES** for the prompt amendment (decoupled from the
  0.85 coordinator floor). The amendment is additive, the wedge is
  preserved verbatim, the response-side zero-vol defense is independent,
  and the validation plan is fast + cheap. Hold the coordinator floor
  change for a separate commit after one bot cycle of evidence on
  the new bullish-confidence distribution.

---

## 8. Done-criteria for this proposal

- [x] Diagnosis grounded in actual local_memory.jsonl + artifact log data.
- [x] Per-instrument abstain reasons surfaced (chop dominant in N=5;
      `chart_below_threshold` is the *coordinator-side* dominant signal at N=36).
- [x] Amendment framed as a *new positive criterion*, not a relaxation.
- [x] Failure mode named, mitigations enumerated, residual risk acknowledged.
- [x] Exact verbatim prompt text drafted with insertion point pinned.
- [x] Validation plan with three fixture tests + one live probe (<$0.001).
- [x] Decoupled from the 0.85 coordinator-floor change so each lever rolls
      back independently.
- [x] Token-budget impact computed (+$0.15 over remaining contest window).
- [x] Ship recommendation explicit (YES for prompt, NOT YET for floor).
