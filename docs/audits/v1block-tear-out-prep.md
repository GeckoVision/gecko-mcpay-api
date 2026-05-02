# v1_block Tear-Out Prep — Read-Only Audit

**Ticket:** S19-V1BLOCK-AUDIT-01 (S19 §2c)
**Author:** ai-ml-engineer
**Date:** 2026-05-02
**Status:** Read-only. No code changed. No tests run.

## Goal

Inventory every prompt / call site / contract that depends on the `v1_block`'s "always-render-four-headings" behavior so the S20 tear-out doesn't sleepwalk into a regression.

## TL;DR

- **8 production call sites** + 1 module + 1 test file reference `v1_block`.
- **3 are heading-contract dependent** (the genuine S20 blockers): `_opening_prompt` / `_run_pro_debate` rag-context prepend, the Pro-tier `analyst` system prompt's "V1 source weighting" block (4 prompt versions: v5 → v5.4), and the advisor `render_context_block` empty-state contract.
- **0 schema dependencies.** `V1Block` is a transient in-memory dataclass; no Postgres column, no Pydantic-Persisted field, no Mongo doc field. The only DB surface is the `cost_v1_sources_usd` rollup column (`infra/supabase/migrations/20260429000000_v1_source_telemetry.sql`), which is a $-cost telemetry sum, **not** the rendered block. Tear-out leaves it untouched (rename later).

## 1. Inventory table

| file:line | classification | snippet / role |
|---|---|---|
| `packages/gecko-core/src/gecko_core/sources/v1_block.py:1-242` | **Module** (source of truth) | `render_block`, `dispatch_and_render`, `V1Block` dataclass, `V1_SOURCES_SPEND_CAP_USD=0.10` |
| `packages/gecko-core/src/gecko_core/__init__.py:63` | Render-only | re-export `"v1_block"` in dynamic submodule list — mechanical drop |
| `packages/gecko-core/src/gecko_core/workflows.py:842-925` (`_dispatch_v1_sources`) | Render-only orchestrator | Calls `dispatch_and_render`, debits cost, returns `(rag_block_str, spend_by_source)` |
| `packages/gecko-core/src/gecko_core/workflows.py:365-371` | **Heading-contract dependent** | `v1_rag` is prepended ABOVE the Tavily corpus into `rag_context`. The pro `analyst` prompt expects this block to start with `## V1 Source Signal` and contain four named subheadings. |
| `packages/gecko-core/src/gecko_core/orchestration/pro/__init__.py:90-105, 191-253` | Render-only consumer of `rag_context` | `_opening_prompt` slices `rag_context[:_RAG_CONTEXT_CHAR_CAP]`. Doesn't itself parse v1 headings, but the analyst prompt does. |
| `packages/gecko-core/src/gecko_core/orchestration/pro/_default_prompts_v5.json:5` (and `v5_1`, `v5_2`, `v5_3`, `v5_4`) | **Heading-contract dependent** | `analyst` system prompt: *"V1 source weighting (read these before TAM math): - gecko_precedent ... - colosseum ... - hn / reddit ... - twit_sh ..."*. Names four V1 sources by id, expects them to appear by name in `rag_context`. |
| `packages/gecko-core/src/gecko_core/orchestration/advisor/__init__.py:109,125,145,203,229,348,421` | Render-only param-passing | `v1_source_signal: str = ""` plumbing through the panel entrypoints |
| `packages/gecko-core/src/gecko_core/orchestration/advisor/context.py:50,130,140-143,194,240-243` | **Heading-contract dependent** | `AdvisorContext.v1_source_signal: str` field; `render_context_block` appends raw `v1_source_signal` if non-empty, else emits stub `"# V1 source signal\n(not dispatched for this advisor run)"`. Advisor `business_manager` and `product_manager` prompts read this section by heading. |
| `packages/gecko-core/src/gecko_core/orchestration/advisor/_default_advisor_prompts.json:2,5,7,8,9` | **Heading-contract dependent** | `_comment` declares "V1 source signal" as an input. CEO prompt names "twit_sh / HN / Reddit ... gecko_precedent". `business_manager` says *"any channel signal in the V1 source block"* and *"if twit.sh is dead silent on this category, do NOT allocate to it"* — both depend on the `### Twitter / X (twit.sh)` heading + "No data found." absence-of-signal contract from `render_block`. `product_manager` reads "user-voice signal from twit_sh / Reddit comments". `staff_manager` reads "the gecko_precedent block". |
| `packages/gecko-core/tests/test_twitsh_active.py:21-25,318-365` | Test (heading-contract dependent) | `test_render_block_empty_sources_keeps_all_four_headings`, `test_v1_block_prepends_above_tavily_corpus` — both literally assert `"## V1 Source Signal"` substring and four subheadings present. These are the contract tests Pattern C wants — they pin the heading shape. |

**Total v1_block production call sites: 8** (excluding the module itself and the test file). **Heading-contract dependent: 4** (workflows.py:365-371, all pro analyst prompts v5–v5.4 collectively, advisor/context.py:240-243, advisor prompts v1).

## 2. Heading-contract risks

The "always-render-heading" contract is encoded in `render_block()` at `sources/v1_block.py:156-179`:

```
parts = [
    "## V1 Source Signal", "",
    "### Twitter / X (twit.sh)", _render_twitsh(...), "",
    "### Hacker News",          _render_hn(...),     "",
    "### Reddit",               _render_reddit(...), "",
    "### Prior Gecko Verdicts (gecko_precedent)", _render_precedents(...),
]
```

This shape is load-bearing for:

1. **Pro analyst prompt (v5+).** Quote: *"V1 source weighting (read these before TAM math): - gecko_precedent — internal Gecko Flywheel ... When gecko_precedent shows ≥2 prior killed similar ideas, weight that signal heavily ... twit_sh — twit.sh builder posts ..."* (`_default_prompts_v5_4.json:5`). The prompt directs the model to *find* signal under each named source. If the headings vanish, the analyst quietly degrades to TAM-only reasoning and we lose the gecko_precedent kill-pattern weighting that S2X-06/11 tuned in. A regression here will not be loud — it will look like vibe drift in eval scores.

2. **Absence-of-signal channel (advisor business_manager).** Quote: *"if twit.sh is dead silent on this category, do NOT allocate to it"* (`_default_advisor_prompts.json:7`). This relies on `### Twitter / X (twit.sh)\nNo data found.` actually appearing in the prompt. A render that simply omits empty sections breaks "absence is signal."

3. **Advisor empty-state stub (`context.py:240-243`).** When dispatch wasn't called, the advisor sees `"# V1 source signal\n(not dispatched for this advisor run)"`. Note: this stub uses `# V1 source signal` (single `#`) while the dispatched block uses `## V1 Source Signal` (double `#`, capitalized). That inconsistency is already a minor bug; tear-out is the right time to unify the empty-state contract.

4. **Pro debate prepend invariant (`workflows.py:365-371`).** The `f"{v1_rag}\n\n{tavily_rag}"` ordering is asserted by `test_v1_block_prepends_above_tavily_corpus`. Tear-out either keeps the prepend ordering with a replacement context block, or migrates analyst prompts to read citations purely from the Tavily corpus. The latter is the cleaner path but loses the "absence is signal" guarantee.

## 3. Schema dependencies

**None.** Verified:

- `models.py` and `persistence/` contain no `v1_block` or `v1_source_signal` field.
- No SQL migration creates a `v1_block` column. The only related migration is `infra/supabase/migrations/20260429000000_v1_source_telemetry.sql`, which adds `cost_v1_sources_usd` (a `numeric` rollup of paid V1 source spend) — that's an economics ledger column, not the rendered block, and it survives tear-out unchanged. Per CLAUDE.md Pattern A, this column would only become a problem if a future tear-out renamed the cost-telemetry concept; today it doesn't.
- `V1Block` is `@dataclass(frozen=True)` in `sources/v1_block.py:47-62`. Lifetime is one orchestration call; never serialized, never persisted.

## 4. Tear-out checklist for S20 (Pattern C-gated)

Ordered. Each step gated on the prior passing.

1. **Lock the contract before touching it.** Promote `tests/test_twitsh_active.py::test_render_block_empty_sources_keeps_all_four_headings` and `::test_v1_block_prepends_above_tavily_corpus` to a contract-test marker (per CLAUDE.md Pattern C). Add a fresh fixture-level test that asserts the *Pro analyst*, *advisor business_manager*, and *advisor product_manager* prompts all produce non-empty per-source reasoning when the V1 block is fully populated (eval-harness, not unit). This is the regression detector — without it, step 4 is unsafe.
2. **Decide replacement contract.** Two viable shapes:
   - (a) Keep the four-heading block but source it from Mongo hybrid retrieval (post-S18) instead of `dispatch_and_render`. Lowest prompt churn.
   - (b) Drop the V1 block entirely and rewrite the analyst + advisor prompts to read citations purely from the Tavily/Mongo corpus. Lower context-token cost, higher prompt-rewrite risk (≥4 prompt versions to revise).
   Recommend (a). It preserves the absence-of-signal contract.
3. **Promote a new module** (e.g. `gecko_core.sources.signal_block`) implementing the same `render_block(results)` four-heading contract over the post-S18 retrieval primitives. Module gets its own contract test mirroring the v1_block ones.
4. **Migrate call sites in this order** (each in a separate PR):
   1. `workflows.py:842-925` — swap `_dispatch_v1_sources` to the new module. Eval-gate (basic + holdout-live, ≥2 reruns).
   2. `advisor/context.py:140-143,240-243` — re-target the docstring + empty-state stub. Unify the heading depth (`##` vs `#`) while at it.
   3. `__init__.py:63` — drop `"v1_block"` from the dynamic re-export list.
5. **Delete** `sources/v1_block.py` only after step 4 is green for ≥2 baseline holdout-live runs. Per CLAUDE.md ai-ml-engineer principle: ±0.10 verdict-accuracy swings on N=10 are noise. Require structural argument or ≥2 failures before reverting.
6. **Update prompts** (`_default_prompts_v5_4.json`, `_default_advisor_prompts.json`) ONLY if step 2 chose path (b). Under path (a), prompts are untouched.
7. **Migrate test_twitsh_active.py** to the new module name; keep the tests, retarget the imports.

## 5. Pattern references

- **Pattern A (parallel Literal redeclarations).** Doesn't bite here — `v1_block` is in one module. The risk is *prompt-text* duplication: the four V1 source ids (`gecko_precedent`, `twit_sh`, `hn`, `reddit`) are hardcoded in 5 prompt JSONs (v5, v5_1, v5_2, v5_3, v5_4) AND the advisor prompts v1. If S20 renames any source id, all 6 prompt files must move together. Add a schema-drift-style test asserting source ids appear in every active prompt version, mirroring `test_payment_mode_consistency.py`.
- **Pattern C (tests that exercise stubs, not real wires).** The current `test_twitsh_active.py` tests are unit-level over stubbed sources. They prove the renderer works; they do NOT prove the rendered block actually changes analyst behavior. The fixture-level eval test in checklist step 1 closes that gap before tear-out.

## 6. Risks for S20

**Single biggest risk:** the four V1 source ids (`gecko_precedent` / `twit_sh` / `hn` / `reddit`) are referenced *by name* inside 5 versions of the pro analyst prompt and 4 of the 5 advisor prompts. Tear-out without a Pattern-A-style consistency test will leave a stale prompt referencing a removed source id, and the failure mode is silent — the model just stops weighting that signal. The fix is cheap (add the consistency test in checklist step 1) but it has to land *before* the tear-out, not after.
