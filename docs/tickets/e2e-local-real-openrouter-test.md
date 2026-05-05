# TICKET: e2e-local-real-openrouter-test

**Date:** 2026-05-05  
**Status:** Open  
**Severity:** P1 — root cause of the 5-version-in-one-day debugging loop

---

## Problem

We shipped 0.2.7 → 0.2.8 → 0.2.9 → 0.2.10 in a single day, each one chasing a
different failure mode of the basic-tier research synthesis call against real
OpenRouter. Every version was tested **only** by deploying to production and
running `gecko_research` via MCP. **There is no local end-to-end test that
exercises the real OpenRouter API path.**

Local `bb research` does call real OpenRouter — but every time we tried to run
it during this debugging loop, the CLI aborted at the source-approval prompt
("Proceed with these sources? [y/n]"). Result: zero validated local runs in
6 hours of debugging.

## What we need

A local CLI invocation pattern (or pytest fixture) that:

1. Does not prompt for source approval (`--auto-approve` or pipe `y`).
2. Reads real `OPENROUTER_API_KEY` from a local `.env`.
3. Hits the real OpenRouter API for the basic synthesis pass.
4. Asserts the call succeeded with non-empty content and parseable JSON.
5. Logs the resolved model, provider (OpenRouter response header), and
   completion tokens for every call — same shape as the diagnostic logger
   added in 0.2.10.

## Acceptance

A single command that we can run after every catalog/basic.py change before
shipping:

```bash
uv run pytest tests/integration/test_basic_synthesis_live.py -v --markers=live_openrouter
```

Marked with the `live_openrouter` pytest marker (already used by S12-TEST-04
contract tests for the CDP path) so it doesn't run in CI by default. Tagged
"live" because it costs ~$0.005 per run and can't run offline.

The test should:

1. Spin up a tiny in-memory `SessionStore` with one indexed source (a fixed
   URL/text fixture).
2. Call `gecko_core.orchestration.basic.generate(session_id, idea, store)`
   directly — bypass the CLI/MCP/API layers.
3. Assert: returned `ResearchResult.business_plan.problem` is non-empty,
   `validation_report.gap_classification` is in the `_VALID_GAP_VALUES` set,
   and `prd.v1_scope` has ≥1 item.
4. Assert the resolved model_id matches the catalog `(general_reasoning, balanced)`
   cell — so a future catalog change is caught at test time, not after deploy.

## Why this didn't exist

The existing tests in `packages/gecko-core/tests/orchestration/test_basic.py`
use `respx` / `pytest-httpx` mocks. They validate the code path but never hit
real OpenRouter. The contract test pattern from S12-TEST-04 (live mainnet
fixture) wasn't replicated for LLM calls.

## Files to add

- `tests/integration/test_basic_synthesis_live.py` — the new test.
- Update `pyproject.toml` `[tool.pytest.ini_options]` markers to include
  `live_openrouter`.
- Update `CLAUDE.md` "Mandatory workflow" section to mention this test should
  run before any catalog or `_call_llm` change.

## Estimated effort

2–3 hours. Most of the wiring exists; we just need a fixture and a marker.
