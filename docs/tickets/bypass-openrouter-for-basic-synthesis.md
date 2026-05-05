# TICKET: bypass-openrouter-for-basic-synthesis

**Date:** 2026-05-05  
**Status:** Open — proposed architectural change  
**Severity:** P1 — long-term reliability fix

---

## Proposal

Move `AgentRole.research_basic` synthesis off OpenRouter and onto the OpenAI
direct API (`api.openai.com`). Keep OpenRouter for AG2 voices and
post-processors where model variety has value.

## Why

The basic synthesis call has unique reliability requirements:

1. **It is the single most critical call in the pipeline.** Every basic-tier
   user request goes through it. Every pro-tier user request also goes
   through it (basic synthesis runs before the AG2 debate).
2. **It uses `response_format=json_object` with strict schema downstream.**
   The Pydantic adapter chain (the `what_they_do` / `acceptance_criteria`
   string-vs-list coercers) is the safety net for json_object output drift.
3. **It needs to produce ~2,500–3,500 tokens of dense JSON.** Output cap
   variance across OpenRouter sub-providers (193 tokens avg on DeepInfra vs
   1,127 on AtlasCloud for the same model id) is unacceptable.

OpenRouter is great for the AG2 voices (model variety produces sharper
debates) and post-processors (parallel cheap calls, best-effort). It is
pathologically bad for a single high-stakes structured-output synthesis call.

## What changes

`packages/gecko-core/src/gecko_core/orchestration/basic.py`:

1. `_resolve_basic_research_model` reads from the catalog as today, but the
   resolved model is **always passed through `resolve_model_for_router(role,
   tier, "openai")`** — forcing the OpenAI fallback ladder regardless of
   `LLM_ROUTER`. The fallback ladder is in
   `packages/gecko-core/src/gecko_core/routing/catalog.py`
   `_OPENAI_FALLBACK_BY_TIER`:
   - `quality` → `openai/gpt-5.5`
   - `balanced` → `openai/gpt-5-mini`
   - `budget` → `openai/gpt-4.1-nano`
   - `free` → `openai/gpt-4.1-nano`

2. The `AsyncOpenAI` client for this call is constructed with
   `base_url="https://api.openai.com/v1"` and `api_key=OPENAI_API_KEY` —
   independent of the global `LLM_ROUTER` setting.

3. `extra_body` is removed (no need for OpenRouter's `provider` field when
   we go to OpenAI direct).

4. Strict `json_schema` mode is enabled for OpenAI direct. The
   `supports_strict_outputs` predicate already handles this — it returns
   True for `router=="openai"` and OpenAI-provider model ids.

## What stays on OpenRouter

- AG2 5-voice debate (analyst, critic, architect, scoper, judge) —
  plain-text generation, model variety is a feature.
- Post-processors (the 5 parallel JSON extraction calls in
  `pro/post_processors.py`) — cheap, best-effort, model variety OK.
- `gecko_ask` — follow-up Q&A, also short and best-effort.
- `gecko_refine` — idea sharpening, json_object but lower stakes than
  research_basic.

## Cost / quality impact

- Quality: **same or better.** OpenAI's json_object is the gold standard;
  schema-strict mode adds field-presence enforcement.
- Cost: **higher per call.** GPT-5 Mini costs ~$0.40/$1.60 per 1M
  input/output. At 8K input + 3.5K output per basic synthesis, that's
  ~$0.009 per call vs ~$0.005 on Kimi/DeepSeek via OpenRouter.
- Reliability: **dramatically better.** Eliminates the entire class of
  OpenRouter provider-routing variance bugs.

## Required env / SSM

`OPENAI_API_KEY` must be set in production SSM. (Already in
`infra/push-ssm-params.sh`.) Confirm it's not the `__unset__` sentinel.

## Tests required

- `tests/integration/test_basic_synthesis_live.py` (new — see
  `e2e-local-real-openrouter-test.md`) updated to assert the resolved
  client is `api.openai.com`, not OpenRouter.
- `packages/gecko-core/tests/orchestration/test_basic.py` — update mocks
  to reflect the new base_url.

## Estimated effort

1–2 hours. Most of the plumbing exists; this is a surgical change to
`_resolve_basic_research_model` and the client construction.

## Reversibility

Two-way. Single function change. If we want to go back to OpenRouter for
basic synthesis later, we revert.
