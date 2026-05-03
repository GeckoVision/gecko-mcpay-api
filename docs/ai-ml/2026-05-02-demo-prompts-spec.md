# Demo Output Prompts Spec — 2026-05-02

Owner: ai-ml-engineer
Status: DRAFT — review with staff-engineer + product-designer before software-engineer wires it up
Sister doc: `docs/design/2026-05-02-research-output-shape.md` (output shape, owned by product-designer)
Touches: `packages/gecko-core/src/gecko_core/orchestration/pro/_default_prompts_v5_5.json` (new), `prompts.py` (add v5.5 to bundle map), `coherence.py` (add `no_surviving_dissent` sentinel parser), `models.py` (5 new optional fields on `ResearchResult`).

## TL;DR

Five new post-processor prompts run after the AG2 5-agent GroupChat finishes:

| Key | Purpose | Output shape |
|---|---|---|
| `per_voice_extraction` | Pull each of the 5 voices' position/tension/recommendation out of the transcript without flattening | `{voices: [{name, position, tension, recommendation, status}]}` |
| `transcript_summary` | 4-line plain-prose meeting recap | `{summary: "..."}` (4 sentences, no hedge words) |
| `market_landscape` | Name 3-5 competitors with a specific differentiating axis | `{competitors: [{name, what_they_do, why_we_are_not_them, flag?}]}` |
| `surviving_dissent` | Verbatim dissent that did NOT collapse into consensus | `{dissent_status: "surviving" \| "no_surviving_dissent", dissents: [...], rationale}` |
| `next_steps_with_falsifiers` | Max 5 next steps, each with a dated falsifier | `{steps: [{action, surfaced_by_voice, falsifier: {what_would_disprove_this, by_when}}]}` |

All five run **in parallel** post-GroupChat, on `gpt-4o-mini`, with `response_format={"type": "json_object"}`. A coherence pass after assembly cross-checks that `next_steps_with_falsifiers.steps[*].surfaced_by_voice` only references voices that `per_voice_extraction.voices[*]` marked `status != "silent"`. Mismatches are dropped, not surfaced.

The wedge that must be visible in the rendered output (Pattern D from `CLAUDE.md`):
1. **Per-voice readout** — five distinct positions, never collapsed.
2. **Surviving dissent** — productive disagreement preserved verbatim.
3. **Falsifiers** — every next-step is dated and observable; that's what makes the verdict tradeable.

If any of these three are weak in a given run, the pipeline FLAGS it (surviving_dissent → `no_surviving_dissent`; per_voice → `status: "silent"`; next_steps → falsifier dropped). Flags are signal, not bugs.

---

## Why a v5.5 bundle (vs amending v5.4)

`prompts.py` versions the in-debate system messages (analyst/critic/architect/scoper/judge) and reserves prior versions as rollback targets. The post-processors are a different surface — they don't change the debate, they re-read its transcript. Three options:

1. **Append to v5.4** — pollutes a version pinned for rollback after the v5.0→v5.3 accuracy slide. Rejected.
2. **New file `_default_post_processors.json`** — clean, but doubles the prompt-resolution code paths and breaks the "one bundle = one debate config" mental model.
3. **Bump to v5.5, add a top-level `post_processors` key** — additive, keeps one resolution path, lets a future v5.6 evolve debate prompts AND post-processors atomically. **Chosen.**

Schema for v5.5:

```json
{
  "version": "v5.5",
  "agents": { "analyst": "...", "critic": "...", "architect": "...", "scoper": "...", "judge": "..." },
  "post_processors": {
    "per_voice_extraction": "...",
    "transcript_summary": "...",
    "market_landscape": "...",
    "surviving_dissent": "...",
    "next_steps_with_falsifiers": "..."
  }
}
```

`prompts.py` `load_prompts()` keeps its current return shape (5-agent dict) for backwards compatibility. A new `load_post_processors() -> dict[str, str]` reads the same file, validates the new key, and is called only from the new post-processor module software-engineer will write. v5.4 callers that don't know about post-processors keep working.

The `agents.*` payload in v5.5 is **inherited verbatim from v5.4**. No debate-prompt changes ride on this bundle bump. The eval gate stays unchanged for in-debate prompts.

---

## Orchestration: where the prompts run

### Pipeline (proposed)

```
GroupChat (5 voices, AG2)
   │
   ▼
DebateTranscript (existing)
   │
   ├──> verdict synthesis (existing — judge-prose parser, gap_classification, Verdict)
   │
   └──> post-processors (NEW, parallel asyncio.gather):
            ├── per_voice_extraction      ─┐
            ├── transcript_summary         │
            ├── market_landscape           ├── all 5 fan out concurrently
            ├── surviving_dissent          │
            └── next_steps_with_falsifiers ┘
                       │
                       ▼
              coherence pass (cross-check next_steps[*].surfaced_by_voice
                              ∈ per_voice.voices where status != silent)
                       │
                       ▼
              ResearchResult assembly (5 new optional fields)
                       │
                       ▼
                    renderer
```

### Why five small calls, not one big synthesis call

Trade-off considered:

| | One big synthesis | Five small post-processors |
|---|---|---|
| Coherence between sections | Higher (one model state) | Lower (independent calls) |
| JSON shape reliability | Lower (one big object → mode collapses + truncation risk) | Higher (smaller objects, less prompt budget) |
| Renderer parsing complexity | High (one giant nested object to validate) | Low (5 small validated objects) |
| Cost | ~1 call × ~3K tokens output | 5 calls × ~600 tokens output ≈ same |
| Latency | Sequential bottleneck | `asyncio.gather` → max(individual) |
| Failure isolation | One bad section corrupts the response | One failing call degrades one section |
| A/B-able per section | No — all-or-nothing | Yes — bump one prompt, hold others |

**Decision: five small calls.** The renderer needs structurally clean, independently-validated JSON for each section, and the per-section A/B-ability matters for the eval harness (we will tune `surviving_dissent` separately from `market_landscape`). Coherence risk is mitigated by an explicit cross-check (below) rather than by colocating sections in one prompt.

### Coherence cross-check

Implemented in code, not in a prompt — model-grading model output is the wrong tool for a structural check:

```
for step in result.next_steps_with_falsifiers.steps:
    if step.surfaced_by_voice not in {v.name for v in result.per_voice.voices if v.status != "silent"}:
        # drop the step, log a warning; do NOT surface to user
```

Dropped steps are counted in a debug field (`_dropped_step_count`) so the eval harness can detect drift (a run that drops 3+ steps has a per-voice/next-step coherence problem worth investigating).

### What about `pro_session_summary`?

Stays as the judge's final paragraph (existing). The new `transcript_summary` is a **different artifact** — the meeting recap, not the verdict prose. We keep both because the eval-rubric grades against the judge prose and the demo renders the recap. Conflating them creates a verdict-hash dependency on the recap prose, which we don't want.

---

## Models impact (note only — DO NOT add yet)

`ResearchResult` gains five optional fields. All `Optional` so legacy callers and basic-tier results round-trip without change:

```python
# Pro tier only — populated by post-processors after GroupChat.
per_voice: PerVoiceReadout | None = None
transcript_summary: str | None = None
market_landscape: MarketLandscape | None = None
surviving_dissent: SurvivingDissent | None = None
next_steps_with_falsifiers: NextStepsWithFalsifiers | None = None
```

New shared Literal: `VoiceName = Literal["analyst", "critic", "architect", "scoper", "judge"]`. Per Pattern A (`CLAUDE.md`), this lives in **one** module — proposal: `gecko_core.orchestration.pro.voices` (alongside `REQUIRED_AGENTS` in `prompts.py`). Schema-drift test pattern: `tests/test_voice_name_consistency.py` asserts `set(get_args(VoiceName)) == set(REQUIRED_AGENTS)`. No SQL impact (voices aren't stored as a CHECK-constrained column today; if/when they are, the comment block convention applies).

Pydantic shapes (sketch — software-engineer owns final form):

```python
VoiceStatus = Literal["engaged", "deferred", "silent"]

class VoicePosition(BaseModel):
    name: VoiceName
    position: str | None     # null iff status == "silent"
    tension: str | None      # the disagreement this voice held
    recommendation: str | None
    status: VoiceStatus

class PerVoiceReadout(BaseModel):
    voices: list[VoicePosition]  # always length 5

class Competitor(BaseModel):
    name: str
    what_they_do: str
    why_we_are_not_them: str | None    # null when flag is set
    flag: Literal["cannot_articulate_difference"] | None = None

class MarketLandscape(BaseModel):
    competitors: list[Competitor]      # 3-5

DissentStatus = Literal["surviving", "no_surviving_dissent"]

class Dissent(BaseModel):
    voice: VoiceName
    verbatim: str
    on_topic: str

class SurvivingDissent(BaseModel):
    dissent_status: DissentStatus
    dissents: list[Dissent]            # empty iff dissent_status == "no_surviving_dissent"
    rationale: str

class Falsifier(BaseModel):
    what_would_disprove_this: str
    by_when: str  # ISO date or relative window like "within 14 days of V1 ship"

class NextStep(BaseModel):
    action: str
    surfaced_by_voice: VoiceName
    falsifier: Falsifier

class NextStepsWithFalsifiers(BaseModel):
    steps: list[NextStep]              # 1-5
```

---

## Prompt design notes

### A. `per_voice_extraction`

The hard part is anti-flattening. Mitigations baked in:

- The system prompt **lists the five voices by name** and demands one entry per voice — five entries, no fewer, no more. Missing entries are a parse failure, not a "the panel agreed" shortcut.
- Three explicit `status` values: `engaged` (voice argued a position), `deferred` (voice spoke but only echoed another voice), `silent` (voice did not meaningfully contribute). `silent` is REQUIRED to be marked, not papered over.
- Anti-flattening rule, verbatim: "If two voices arrived at the same conclusion, write each voice's reasoning separately. Do not write 'the panel agreed' or 'both X and Y said'. The reader must be able to read one voice's row without the others."
- `tension` field is the named *disagreement axis*, not a hedge. Every engaged voice should have a non-null tension or it's flagged as deferred.

### B. `transcript_summary`

Plain-prose memo, 4 sentences. Banned-word list ("seems to", "appears to", "it could be argued", "in some sense", "potentially") because hedge words read as LLM, not memo. Required structure: sentence 1 = lead position, sentence 2 = strongest counter, sentence 3 = where consensus landed, sentence 4 = surviving dissent (or "no surviving dissent" — that's information, not failure).

### C. `market_landscape`

The "why we're not them" is **the** wedge surface in the demo output. Hard rules in the prompt:

- The differentiator must point to a specific axis from a closed list: `verdict_shape`, `debate_vs_single_voice`, `judge_attribution`, `falsifier_layer`, `settlement_layer`, `contributor_reputation`, `provider_mix`, `surviving_dissent`. (Mirrors the v5.5 wedge from Pattern D.)
- If none of these axes apply against a specific competitor, set `flag: "cannot_articulate_difference"` and leave `why_we_are_not_them` null. The prompt is **forbidden from inventing a difference** — flagging is the right answer when the difference is fuzzy.
- 3-5 competitors. Fewer than 3 = flag at the section level (the model didn't find enough comparables in the rag_context); more than 5 = drop the weakest in the coherence pass.

### D. `surviving_dissent`

The whole point of the 5-voice debate is productive disagreement. If every run lands on `no_surviving_dissent`, the debate is producing consensus mush — that's a quality failure, not a feature. The prompt:

- Distinguishes "voice disagreed but caved by the end" (NOT surviving) from "voice disagreed and the disagreement was never refuted, just outvoted" (surviving).
- Requires verbatim quotes from the transcript when `dissent_status == "surviving"`. No paraphrasing — paraphrasing is where the wedge gets sanded down.
- Sentinel parser pattern: emits `NO_SURVIVING_DISSENT: yes` on a standalone line when the structured field is `dissent_status == "no_surviving_dissent"`. `coherence.py` gets a sibling scanner — `count_no_surviving_dissent_flags(turns)` mirroring the existing `count_incoherent_premise_flags` — so the eval harness can count the rate across a holdout suite without parsing every JSON.

### E. `next_steps_with_falsifiers`

The hard rule: every step has a falsifier or it doesn't ship. Implementation in the prompt:

- The model is instructed to draft ≥ 5 candidate steps, then **drop any** whose falsifier is vague. Vague is enumerated in the prompt: "if metrics don't improve", "if traction is weak", "based on user feedback", any sentence without a date or observable count.
- `by_when` must be ISO date OR a relative window of the form `within N days of <event>`. Free-form is rejected by the structural eval (below), not by the model itself.
- `surfaced_by_voice` must be one of the five voice names — not "the panel". Coherence cross-check enforces it actually matches an engaged voice.
- Max 5 steps. Fewer is fine (better than padding). Zero is allowed; if the verdict is KILL there may legitimately be no next steps and the prompt must not invent any.

---

## Eval strategy

Constraint from `feedback_eval_harness_rag_gap`: `tests/eval/runner.py --live` uses canned `rag_context` strings, so anything that needs real retrieval has to run through `bb research` end-to-end. The post-processors mostly DON'T need retrieval — they re-read the transcript — so they can be tested in isolation. Only `market_landscape` cares about chunks, and it reads the same rag_context the runner already injects, so it works in the runner.

### Three eval layers

**(a) Smoke — output shape.** New file `tests/eval/test_demo_output_shape.py`. Runs all 5 post-processors against a small fixture transcript (recorded from a prior pro run, lives at `tests/eval/fixtures/demo_transcript.json`). Asserts each output validates against its Pydantic shape, hits required cardinalities (per_voice == 5, market_landscape ∈ [3,5], next_steps ≤ 5), and the cross-section coherence check passes (every `surfaced_by_voice` matches an engaged voice). Pure structural — no model grading. Runs in CI on every PR. Expected runtime: ~5 model calls × 1 transcript = ~$0.005/run; trivial.

**(b) Dissent rate — debate quality.** New aggregator on top of the existing holdout suite: across the 10-idea holdout, count how many runs emit `dissent_status == "no_surviving_dissent"`. Threshold: **≤ 40%** initial bar (4 of 10), with the understanding that some ideas legitimately produce consensus (clear KILLs, clear SHIPs with no debatable wedge). If the rate exceeds 40%, the debate is consensus-mush territory and the *debate* prompts (analyst/critic) need a productive-disagreement nudge — NOT the post-processor. Per project principle, do not tune to a single failed run; require ≥ 2 baseline runs above threshold before changing prompts.

**(c) Falsifier-quality — structural, not model-graded.** Pure regex/parsing checks on every `falsifier.by_when`:
   - Matches ISO date `^\d{4}-\d{2}-\d{2}$`, OR
   - Matches `^within \d+ (days|weeks|months) of [a-z][a-z _-]+$`.
   And `falsifier.what_would_disprove_this` must contain at least one of: a number, a percentage, a named integration, or a named ICP. Implemented as a deterministic check in `tests/eval/test_falsifier_structure.py`. **No LLM grades the falsifier** — that's circular and the failure mode (LLM rates LLM hedging as fine) is well-documented.

### Variance and small-N discipline

The holdout-live suite is 10 ideas. Per project rule (`±0.10 swings are noise, not signal`), do not tune `surviving_dissent` or any post-processor based on a single run. Require ≥ 2 baseline runs at the new threshold OR a structural argument (e.g. "the falsifier regex was wrong") before changing the prompt or the bar.

### What does NOT get an eval

- "Is the per-voice readout *good*?" — model-grading model output. Skipped. We grade by structural cardinalities and trust the existing pro-tier judge eval to catch debate-quality regressions upstream.
- "Is the transcript_summary *well-written*?" — same. We assert no banned hedge words (regex) and 4 sentences (count); the rest is product-designer + manual review on the demo idea.

---

## Risks, open questions, follow-ups

1. **Coherence cross-check drops a step → user sees fewer than 5 next steps.** Acceptable; underclaiming beats over-claiming. Renderer should not pad. Track drop rate in `_dropped_step_count` for the next sprint review.
2. **`market_landscape` flagging "cannot_articulate_difference" on the demo idea.** This is the bug we want to surface, not hide — it tells us the wedge is actually fuzzy against that competitor. Demo prep should rehearse on ideas where the wedge IS articulable, not lean on the flag to escape.
3. **Voyage AI swap (deferred to S19 per memory)** would change retrieval quality and therefore `market_landscape` chunk inputs. Re-run eval (a) when that lands.
4. **`pro_session_summary` vs `transcript_summary` doubling.** Track whether the renderer actually needs both after the demo; if not, deprecate `pro_session_summary` in S22.
5. **Closing-line parsing on advisor panel** (the 5-voice advisor is a *separate* surface from the AG2 5-agent debate) — this spec covers the AG2 debate's post-processors only. The advisor closing-line parser is a different, already-shipped pipeline; do not conflate.
6. **Verdict-hash exclusion.** `transcript_summary`, `per_voice`, `market_landscape`, `surviving_dissent`, and `next_steps_with_falsifiers` MUST be excluded from the verdict-hash payload (`verdict_hash._verdict_payload`). They are post-hoc readouts, not verdict inputs — including them would make the hash flap on prompt changes that don't change the verdict. software-engineer to verify when wiring.

---

## Appendix — prompt fragments

The actual fragments are saved as new keys under `post_processors` in `_default_prompts_v5_5.json`. The shapes there match the Pydantic sketches above. Each prompt:

- Uses `response_format={"type": "json_object"}` (caller's job, but the system prompt explicitly says "respond with a single JSON object matching the schema below; no prose, no markdown, no code fences").
- Includes the schema inline in the system message — the model performs better with the schema visible than with it implied.
- Has explicit refusal language for invented content ("if you cannot, flag it; do not fabricate").
- Has anti-hedge language where prose output is required (transcript_summary).

See `_default_prompts_v5_5.json` for the verbatim fragments.
