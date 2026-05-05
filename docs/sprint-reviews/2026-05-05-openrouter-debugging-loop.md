# Sprint review — 2026-05-05 — OpenRouter debugging loop

**TL;DR:** Five releases (0.2.6 → 0.2.10) in one calendar day chasing a single
P0 (`OrchestrationError: LLM returned empty content` / truncated JSON on
basic-tier research synthesis). Each release fixed *something* but exposed
the next failure mode. Root issue: we have no local end-to-end tests against
real OpenRouter, and we have been guessing at fixes through production deploys.

## Release timeline

| Release | Change | What it fixed | What broke next |
|---|---|---|---|
| **0.2.6** | `_VOICE_TIMEOUT_SECONDS=60`, strip `name` field, basic.py retry loop | AG2 voice timeouts at 15s; OpenRouter returning content=null with `name` field | Basic synthesis still failing intermittently |
| **0.2.7** | `(general_reasoning, balanced)` Kimi K2.6 → DeepSeek V3.2; `finish_reason=length` early-break in `_call_llm` | Kimi K2.6 reasoning tokens consuming entire `max_tokens` budget | DeepSeek V3.2 truncates at ~360 tokens via Baidu/Novita |
| **0.2.8** | Also (`creative_writing, balanced`), (`tool_calling, balanced`) → DeepSeek V3.2 | `bb refine` (the `refiner` AgentRole) had the same Kimi problem | (Same DeepSeek truncation, no improvement) |
| **0.2.9** | `(general_reasoning, balanced)` DeepSeek V3.2 → GPT-4.1 Mini | Should have fixed truncation by routing to OpenAI via OpenRouter | Output truncated at column 3947 — provider routing, not a model property |
| **0.2.10** | `extra_body={"provider": {"order":["OpenAI"]}, "transforms":[]}` for `openai/*` slugs + diagnostic logging + length-on-content detection | Should have pinned routing to OpenAI direct | **Empty content on every tier preset, even non-openai/* models** — basic call no longer reaching OpenRouter at all |

## What we learned (the painful way)

1. **OpenRouter routes the same model id to multiple sub-providers**, and
   each sub-provider applies its own output cap. Same `deepseek-v4-flash`
   model with `max_tokens=6000` produces:
   - 193 tokens avg on DeepInfra
   - 1,127 tokens avg on AtlasCloud
   - 4,298 tokens max on SiliconFlow
   The OpenRouter `model` field alone is insufficient — you must pin the
   `provider.order` to control output reliability.

2. **`finish_reason='stop'` from a truncated provider is a lie.** Bottom-tier
   providers (Baidu, Novita, AkashML) return `stop` while having silently
   capped output below the model's true budget. Always also inspect
   `usage.completion_tokens` against `max_tokens` — if it's < 20% of budget
   AND the JSON is malformed, that's a provider clamp.

3. **Reasoning models charge against `max_tokens` for thinking tokens too.**
   Kimi K2.6 was generating 5,755 tokens of internal reasoning per call,
   which consumed the entire `max_tokens=6000` budget before any visible
   output. `content=null` with `finish_reason='length'` is the signature.
   Never put a reasoning model on a `json_object` synthesis path.

4. **Production-only debugging is unaffordable.** Each failed release was a
   3–5 minute deploy cycle plus a paid OpenRouter call. Five versions × 5
   tests × 10 minutes per round = 4+ hours of pure deploy/test wait. Plus
   real money on OpenRouter for each test (basic+pro tier). All of this
   could have been caught in a 10-second local test against real
   OpenRouter — if such a test existed.

5. **Diagnostic logging should have been there from day one.** The single
   line added in 0.2.10:
   ```
   llm.call model=... provider=... finish=... prompt_tokens=... completion_tokens=... gen_id=...
   ```
   would have made every prior failure diagnosable from a single log entry.
   Catalog this pattern; replicate for every other LLM call site.

## Open follow-up tickets

| Ticket | Type | Priority |
|---|---|---|
| [`basic-synthesis-empty-content-2026-05-05.md`](../tickets/basic-synthesis-empty-content-2026-05-05.md) | Bugfix — diagnose 0.2.10 empty content | P0 |
| [`e2e-local-real-openrouter-test.md`](../tickets/e2e-local-real-openrouter-test.md) | Test infra — local E2E against real OpenRouter | P1 |
| [`bypass-openrouter-for-basic-synthesis.md`](../tickets/bypass-openrouter-for-basic-synthesis.md) | Architecture — move critical synthesis to OpenAI direct | P1 |
| [`kimi-k2.6-full-audit.md`](../tickets/kimi-k2.6-full-audit.md) | Audit — already partially closed | done |
| [`openrouter-agent-deep-analysis.md`](../tickets/openrouter-agent-deep-analysis.md) | Investigation report — closed | done |

## Process changes (effective immediately)

1. **No more catalog or `_call_llm` change without first running the new
   `tests/integration/test_basic_synthesis_live.py` locally** (see ticket
   `e2e-local-real-openrouter-test.md`). Add this to `CLAUDE.md` "Mandatory
   workflow" section once the test exists.

2. **Every LLM call site logs `model / provider / finish_reason /
   completion_tokens / gen_id` on success and on failure.** Replicate the
   0.2.10 logger.info pattern in `_call_json` (post-processors), the AG2
   voice loop, the `ask` endpoint, and the `refiner`.

3. **Every release that touches the model matrix or `_call_llm` includes a
   ticket reference.** No more silent catalog edits between unrelated
   commits — they create the kind of drift that took us from 0.2.7 to
   0.2.10 across one day.

## Cost incurred today

- ~5 OpenRouter test runs at ~$0.005 each
- ~50 GPT-4o-mini calls at ~$0.001 each (post-processor batches that fired
  during failed pro-tier tests)
- ~15 Kimi K2.6 calls at ~$0.03 each (reasoning-heavy)
- Estimated: **~$0.50–$1.00 in OpenRouter spend** burned chasing this bug.
  Cheap in dollars; expensive in 6 hours of debugging time.

## What to do tomorrow

1. **Investigate the 0.2.10 empty-content bug** using ticket
   `basic-synthesis-empty-content-2026-05-05.md`. Pull the ECS CloudWatch
   logs for the three failed sessions. The 0.2.10 diagnostic logger output
   tells us within seconds whether the request is reaching OpenRouter or
   not.
2. **If the issue is not obvious from logs, ship a 0.2.11 rollback** that
   removes the `extra_body` block. Restore the previous behaviour
   (truncation, but at least visible) while we debug.
3. **Implement the local E2E test.** This is the highest-leverage change —
   it would have prevented every iteration after 0.2.7.
4. **Then implement the OpenAI-direct bypass for basic synthesis.** Long-term
   architectural fix that eliminates the OpenRouter provider variance class
   of bugs entirely.
