# Calibration block + Refine prompt spec — 2026-05-03

Owner: ai-ml-engineer
Status: DRAFT — sister doc to `docs/ai-ml/2026-05-02-demo-prompts-spec.md`
Touches: `packages/gecko-core/src/gecko_core/orchestration/pro/_default_prompts_v5_5.json` (new top-level keys: `calibration.colosseum`, `refine_idea`, `market_landscape_standalone`), `packages/gecko-core/src/gecko_core/models.py` (new types: `RefinedIdea`, `DissentResolution`, `RefinementConfidence`).
Wired by software-engineer in parallel.

## TL;DR

Three additions to the v5.5 bundle:

1. `calibration.colosseum` — a ≤500-token operator-curated block prepended to all 5 voice system messages when `--calibration colosseum` is active. Distilled from the 34-judge Colosseum corpus into 7 evaluation patterns (traction over narrative, payment proof, regulatory awareness, clear one-liner, demo with real usage, competitive analysis depth, builder velocity) plus regional spread + feedback-sparsity reality. **Names zero individual judges.**
2. `refine_idea` — a new on-demand prompt invoked by `bb refine <hash>`. Editorial, anti-roast framing. Outputs `RefinedIdea` (refined statement, parallel claim swaps, dissent resolutions, falsifiers now harder, confidence band: sharper/narrower/pivoted).
3. `market_landscape_standalone` — a tuned variant of the in-pipeline `market_landscape` post-processor for `bb competitors_landscape <hash> --deep`. Cap bumped from 3-5 to 5-8 competitors; everything else unchanged.

## Job 1 — Calibration block design

### Why it must be aggregate, not impersonation

Per the 2026-05-03 authority-first thesis (`docs/strategy/2026-05-03-authority-first-calibration-moat.md`), named-judge voices are a V2+ premium accelerator on top of the calibration record. Shipping named-judge impersonation as the V1 wedge is backwards: it requires judges to opt in before the product is credible, and it confuses "is the model good" with "is this judge consenting to be channeled."

The calibration block therefore biases the panel toward the *patterns* the corpus exhibits, not toward channeling specific humans. The eval gate (see below) enforces this structurally.

### The 7 patterns (re-derived from the corpus, not from the operator note)

I scanned all 34 `profile_summary` entries plus the 8 public feedback posts. The patterns that recur in ≥4 profiles and that the operator note also surfaces:

1. **Traction over narrative** — implicit across DeFi/infra judges (Drift, Raydium, Anza, Solana Foundation president), explicit in the 4 public-feedback posts ("amazing pitch", "non-stop building").
2. **Payment proof** — present in PayFi, RWA, Reflect, Avici, attn.markets, Squads BD, Phantom devtools — all judges who measure "real revenue, real users."
3. **Regulatory awareness** — explicit in Phil Kwok (ex-Linklaters), Jed (CSO Anza), Lily Liu (Solana Foundation), Dom Kwok (ex-Goldman). The Lily Liu Huma/PayFi public post is the cleanest signal here.
4. **Clear one-liner** — present in operator note; reinforced by the BD-heavy roster (Reflect, Phantom, Squads, Colosseum, Superteam).
5. **Demo that shows real usage** — implicit in the engineering-heavy roster (Drift, Raydium, Stripe-eng-cofounder, Arena engineer, Metaplex). Polished demos do not impress technical judges who can read the seed data.
6. **Competitive analysis depth** — VCs (Delphi/Kosmos, Colosseum-native investor, Alliance-backed) and BD operators consistently surface this.
7. **Builder velocity** — Kuka's public post on @usebido ("non-stop building") is the canonical example; reinforced by the Superteam operator profiles which explicitly reward builder consistency.

### The block, verbatim (also lives in the JSON)

> CALIBRATION CONTEXT (operator-curated, aggregate, anonymous).
>
> This panel is being calibrated against a 34-judge corpus drawn from a recent Solana hackathon. The corpus spans 14 regions — Brazil/LatAm, UK, US, Korea, India, Germany/Europe, Balkans, Vietnam, Venezuela, plus globally-distributed operators. You are NOT impersonating any one judge. You are biased toward the recurring evaluation patterns that emerge across all 34 profiles.
>
> [...7 patterns, each one paragraph...]
>
> FEEDBACK SPARSITY. The corpus is mostly private — 26 of 34 profiles have zero public feedback posts; observed public stances are concentrated in 4-5 voices. Weight observed public stances heavily where they exist. Where they do not, fall back on the pattern signals above. DO NOT assume any specific judge has tweeted on any specific topic; do not invoke evidence that does not exist.
>
> REGIONAL SPREAD. The panel is calibrated multi-region, not single-market. Brazil/LatAm and UK/EU operators are real voices in the corpus alongside US/global. If the idea is regionally scoped, do not assume a US default.
>
> BOUNDARIES (hard):
> - Do NOT name individual judges. No @handles. No display names. No 'as a former Stripe engineer might note'.
> - Do NOT invent feedback from any specific judge.
> - Do NOT downweight an idea because it is not Solana-native.
>
> Use these patterns as PRIORS, not as gates. They tilt the panel; they do not override the existing decision pipeline.

Token count (tiktoken `cl100k_base`): ~480 tokens. Inside the ≤500 budget.

### Eval constraint (NEW)

A structural eval (regex, not model-graded) scans `per_voice.voices[*]` (`position`, `tension`, `recommendation`), `surviving_dissent.dissents[*].verbatim`, `surviving_dissent.rationale`, and `next_steps_with_falsifiers.steps[*].action` text for any judge username substring from `docs/judges/sources/judges_source_colosseum.json` (`@kukasolana`, `@toly`, `@scottleesol`, etc.) AND any display-name substring (`Kuka`, `Toly`, `Scott Lee`, `Lily Liu`, etc., minus common-word names like `max`, `Adam`, `Ram`, `Cap`, `Dan`, `Phil`, `Jed`, `Stephen`, `Aditya` to avoid false positives — the username form catches those reliably). Match → fail run. Mock-mode runs (no calibration active) are exempt.

Implementation lives in `tests/eval/test_calibration_no_judge_names.py` (software-engineer to wire when the calibration flag ships).

## Job 2 — Refine prompt design

### Anti-roast framing in 1-2 sentences

The user paid $2.50 for a verdict and is now paying again to refine it. The dissent surfaced by the panel is taken seriously TO MAKE THE IDEA STRONGER, not to win an argument or dunk on the original — tone is editorial (a senior PM rewriting a one-pager), not adversarial.

### Output shape

```python
RefinementConfidence = Literal["sharper", "narrower", "pivoted"]

class DissentResolution(BaseModel):
    dissent_quote: str    # verbatim from surviving_dissent input
    voice: VoiceName
    resolution: str       # CONCRETE, no "consider" / "explore"

class RefinedIdea(BaseModel):
    refined_statement: str
    addresses_dissent: list[DissentResolution]      # max 3, top dissent mandatory
    new_falsifiers_now_harder: list[str]
    what_it_no_longer_claims: list[str]             # parallel
    what_it_now_claims_instead: list[str]           # parallel — same length
    confidence: RefinementConfidence
```

### Hard rules baked into the prompt

1. **Top dissent is not optional.** If the refined statement does not address it, set `confidence: "pivoted"` and explain.
2. **Pivot is allowed.** Do not pretend refinement when the right answer is pivot.
3. **Banned hedge verbs in refined_statement**: `consider`, `explore`, `potentially`, `might`, `could`, `may`, `arguably`, `somewhat`, `perhaps`, `in some cases`, `it depends`. The refined statement is a positive declarative claim.
4. **Parallel swaps.** `what_it_no_longer_claims[i]` is the surgical replacement for `what_it_now_claims_instead[i]`. Same length, parallel index.
5. **Concrete resolutions.** "We will consider customer feedback" is rejected. Resolutions name specific changes in scope, ICP, payment moment, or feature set.
6. **Confidence band semantics**: `sharper` (same wedge, tighter scope), `narrower` (one segment chosen from a range), `pivoted` (sibling idea, not subset).
7. **Respect the user.** No language implying the original was naive or AI-slop.

KILL verdicts default to `confidence: "pivoted"` — the panel said "this cannot ship", refining the prose into SHIP is dishonest. Use the refined_statement to name the adjacent idea the user could pursue instead.

### Verdict-hash exclusion

`RefinedIdea` is NOT included in `verdict_hash._verdict_payload` — refinement is a post-hoc editorial pass. Mirror the post-processor pattern from `tests/test_verdict_hash_post_processor_exclusion.py` if/when refined-idea outputs are persisted on `ResearchResult` (current proposal: persist as a sibling row keyed by `verdict_hash + revision_n`, not on the original result).

## Job 3 — `bb competitors_landscape` recommendation

**Recommendation: re-render existing for the default path, re-call with `--deep` flag.**

Reasoning:
- The pro-tier `market_landscape` post-processor already runs and persists into `ResearchResult.market_landscape`. The verdict-hash already excludes it, so the saved hash maps to a stable landscape.
- Re-calling on every invocation costs real money for no marginal value when the saved landscape is fresh.
- The case for re-call is: (a) the verdict was basic-tier (no landscape exists), (b) the user explicitly asks for deeper retrieval (`--deep`), or (c) the saved landscape was flagged `insufficient_competitors_in_chunks` and we want to retry against a richer corpus.

For the re-call path I added a `market_landscape_standalone` prompt to the JSON. The only delta from the in-pipeline prompt:
- Cap bumped from 3-5 to 5-8 competitors (more headroom because the user explicitly asked for a deeper landscape).
- Same axis enum, same axis-vs-sentence separation, same refusal-to-fabricate.

Software-engineer's CLI dispatch:
```
bb competitors_landscape <hash>          # re-render existing
bb competitors_landscape <hash> --deep   # re-call with market_landscape_standalone
```

If the verdict has no saved landscape (basic tier), the default path falls through to `--deep` automatically.

## Validation

```
uv run ruff format    # 1 file left unchanged
uv run ruff check     # All checks passed
uv run mypy packages/ apps/   # 0 errors in files I touched (56 pre-existing in other files)
uv run pytest tests/test_demo_output_shape_smoke.py tests/test_voice_name_consistency.py tests/test_verdict_hash_post_processor_exclusion.py   # 10 passed
```

## v5.5.1 — named-rubric calibration upgrade (2026-05-03 PM)

Triggered by the new high-signal corpus `docs/judges/sources/judges_feedback_posts.json` — two judges (Billy, Adam) evaluating real Colosseum projects in public, plus their explicit evaluation frameworks. Three structural additions on top of v5.5:

### 1. First-pass classifier on the judge

Adam's framework — `greenfield innovation` vs `iterative innovation` — becomes a Phase 0 step on the judge agent. The judge prompt opens with a classification block and emits a sentinel as the FIRST line of its synthesis:

```
idea_classification: greenfield   # new category, no incumbent
idea_classification: iterative    # improving an existing category
idea_classification: unclear      # genuinely ambiguous (rare)
```

Sentinel format mirrors `gap_classification:` and `INCOHERENT_PREMISE:` — same regex contract, same parser pattern in `gecko_core.orchestration.pro.coherence`.

The classification then feeds the critic's evidence demands:
- ITERATIVE → demand organic users, real feedback loops, no airdrop-farmer dependency, category-specific PMF metrics.
- GREENFIELD → demand experimental rigor, falsifiable hypotheses, founder's willingness to be wrong.
- UNCLEAR → flag the ambiguity, do not gate.

### 2. Feedback-posture observation on the critic

Billy's lens — public-feedback-seeking founders are weighted higher — becomes a one-line tilt on wedge confidence in the critic prompt. Not a kill criterion. Cite the handle when the signal appears in a builder post.

### 3. Calibration block extension

`calibration.colosseum` gains two paragraphs (FIRST-PASS CLASSIFIER + FEEDBACK-SEEKING POSTURE). Token count moved from ~480 to ~720 — still well under a system-prompt budget but worth tracking. **The frameworks are CITED to the corpus, not invented.** Adam and Billy are NOT named in the prompt the model reads; the language is "from the corpus, projects evaluated as greenfield..." That keeps the V2-premium impersonation lane open while baking the named rubric into V1.

### Extraction strategy: regex over judge prose, not a new post-processor

I considered three options:

| Option | Cost | Pros | Cons |
|---|---|---|---|
| New post-processor (`idea_classification_extraction`) | +1 LLM call (~$0.0001/run) + 1-2s latency | Robust to prose drift | Doubles a tiny field's footprint; new failure mode |
| Fold into `per_voice_extraction` | $0 marginal | Reuses existing call | Couples two unrelated concerns; bloats schema |
| **Sentinel regex over judge prose (chosen)** | **$0, deterministic, ~50µs** | Same contract as `gap_classification` / `INCOHERENT_PREMISE`; no new failure mode | Silently degrades to None on prose drift |

The cost calculus is decisive: the judge already emits `gap_classification:` and `Final verdict:` as structured sentinels and we trust the regex to parse them. Adding `idea_classification:` as a sibling sentinel costs zero tokens, zero latency, and inherits all existing test coverage patterns. Silent-None on prose drift is the **correct degrade** — the live eval gate (below) catches it within one run when calibration is active.

Implementation: `extract_idea_classification(turns)` in `gecko_core.orchestration.pro.coherence`. Wired in `workflows.py` immediately after `audit_provider_mix`.

### Eval addition

`tests/test_idea_classification_sentinel.py` — pure-Python structural test. Validates extractor on greenfield/iterative/unclear/missing/invalid label/case-insensitive/dict-replay shapes, plus the verdict-hash exclusion guarantee.

A live eval gate that asserts `idea_classification is not None` when `--calibration colosseum` is active is the natural next step — wire it alongside the calibration flag plumbing in `tests/eval/runner.py` (software-engineer's lane).

### Disagreement with the brief

The brief framed Adam's framework as strong enough to bake in as a first-pass classifier. I agree, with two caveats:

1. **One-judge framework is thin evidence on its own** — the corpus provides ONE explicit articulation. The reason it survives the bar is structural, not statistical: greenfield-vs-iterative is a known framing in product literature (Christensen, the YC playbook), and the corpus offers the sharpest cited articulation we have. That promotes it from "one judge's view" to "named formulation of a recurring pattern." If it were a niche or idiosyncratic frame, I'd push back on baking it in structurally.
2. **Billy's feedback-posture lens is genuinely thin** — it's a tilt, not a structural addition. I deliberately did NOT make it a sentinel or a verdict input; it lives as one paragraph each in the critic and the calibration block. That's the right weight for the evidence we have.

The classifier is a sentinel-grade structural change; the feedback-posture lens is a prompt nudge. Different evidence weights, different surfaces.

## Open questions / follow-ups

1. **Where does `RefinedIdea` get persisted?** Proposal: a new `verdict_refinements` table keyed by `(verdict_hash, revision_n)`, NOT a field on `ResearchResult`. Refinement is a separate event from research. Defer schema design to data-engineer.
2. **Calibration flag wiring.** `--calibration colosseum` needs a CLI flag in `bb research`, an env var (`GECKO_CALIBRATION`), and a build-time hook in `agents.py` to prepend the block. Defer to software-engineer.
3. **Schema-drift test for `calibration.*` keys.** Mirror the `REQUIRED_POST_PROCESSORS` validation pattern in `prompts.py` once a second corpus (`calibration.frontier`?) lands. For a single corpus the validation is trivial; the pattern matters at N≥2.
4. **No-judge-names eval.** Implementation lives in `tests/eval/test_calibration_no_judge_names.py` — software-engineer to wire when the flag goes live. Username substring matching is a hard fail; display-name matching uses an allowlist to avoid common-word false positives (`max`, `Adam`, `Ram`, etc.).
