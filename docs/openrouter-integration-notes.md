# OpenRouter integration — actionable notes

Distilled from `docs/external/openrouter-llms_full.txt` (gitignored, ~80K lines, snapshot 2026-04-29). This doc is the lean summary that drives our LLM router decisions; consult the raw file for edge cases.

## Model identifiers

OpenRouter prefixes model strings with provider slug:

```
openai/gpt-4o-mini
openai/gpt-4o
anthropic/claude-sonnet-4-6
anthropic/claude-opus-4-7
google/gemini-2.5-pro-preview
```

Bare names (no slash) DO NOT work via OpenRouter — they only work against OpenAI's direct API. Our `gecko_core.orchestration.pro.router` already handles this via the per-router model matrix.

## Cost in API responses (the load-bearing fact)

Every chat-completions response includes a `usage` object with **billed cost in USD already computed**:

```json
{
  "usage": {
    "prompt_tokens": 194,
    "completion_tokens": 2,
    "total_tokens": 196,
    "cost": 0.95,
    "cost_details": {
      "upstream_inference_cost": 19
    },
    "completion_tokens_details": {
      "reasoning_tokens": 0
    },
    "prompt_tokens_details": {
      "cached_tokens": 0,
      "cache_write_tokens": 100,
      "audio_tokens": 0
    }
  }
}
```

**Implications for our code:**
1. `usage.cost` is the canonical billing figure — read this, don't recompute.
2. Our `gecko_core.routing.costs.MODEL_PRICING` table is now best for **pre-flight estimation** (cost gating before the call) and **AG2 price-injection** (silences the WARNING, keeps AG2's internal bookkeeping happy). Post-call truth comes from `usage.cost`.
3. Sprint 4 ticket: hook into the response handler in `pro/agents.py` / `routing/__init__.py` to surface `usage.cost` in the session economics ledger. This makes margin reporting accurate without depending on our hardcoded price table staying in sync.
4. `cached_tokens` counts cache reads (free); `cache_write_tokens` counts cache writes (charged). Both surfaced — no extra parameters needed.
5. Cache hits return all token counts as 0 in `usage` per the docs (zero-billed). Only the cache-populating MISS is billed.

The `usage: {include: true}` and `stream_options: {include_usage: true}` parameters are **deprecated** — OpenRouter always includes usage now.

## Required headers

```
HTTP-Referer: <your site URL>      # OPTIONAL — used for openrouter.ai rankings
X-Title: <your app name>            # OPTIONAL — used for openrouter.ai analytics
```

Neither is required for the API to work, but populating them gets us into the OpenRouter analytics dashboard for free. Our `RouterConfig.extra_headers` already sets both — keep doing this.

## Error codes (BYOK + standard)

| Code | Meaning | Our handling |
|---|---|---|
| 400 | Bad request — model/key config invalid | Loud fail; surface to user |
| 401 | API key invalid or revoked | Fail loudly; logs but never echo key |
| 403 | Permission missing on provider side (AWS Bedrock IAM, GCP service account) | Same as 401 |
| 429 | Rate limit on provider account | Retry with exponential backoff (tenacity); fall back to alternate provider via `models` array |
| 500 | Provider-side error | Retry once, then fail |

Our embedder already has tenacity retry for 429 (`packages/gecko-core/src/gecko_core/ingestion/embedder.py`). Pro tier inherits this. `gecko_route` should add the same pattern when we ship Path B.

## Provider routing + fallbacks

Two ways to handle "primary unavailable":

### `models` array (simple fallback chain)
```python
extra_body = {
    "models": ["anthropic/claude-sonnet-4-6", "openai/gpt-4o", "google/gemini-2.5-pro-preview"]
}
```
Tries in order if primary returns: rate limit, 5xx, content moderation refusal, timeout. With OpenAI SDK, pass via `extra_body=`.

### `provider` object (fine-grained control)
```python
extra_body = {
    "provider": {
        "allow_fallbacks": True,         # default; set False to never fall back
        "sort": "throughput",             # or "latency", "price"
        "data_collection": "deny",        # for privacy-sensitive routes
    }
}
```

For our use case, the `models` array is enough for v1. Sprint 4 `gecko_route` Path B should expose this as a config field.

## Rate limits (free tier)

Per the FAQ:
- Free models with **< some-credits-threshold** purchased: capped at **N requests/day**
- Free models with **>= threshold** credits purchased: capped at higher RPD (number redacted in template form `{FREE_MODEL_HAS_CREDITS_RPD}`)
- BYOK requests bypass OpenRouter's shared-credit limits (use the underlying provider's quotas)

For our Pro tier (paid models with our OpenRouter credits), rate limits are managed by OpenRouter against the underlying provider quota — we should not hit them at single-builder volumes.

## Streaming + `usage` field

For SSE/streaming responses, the `usage` object lands in the **last chunk** (with `object: "chat.completion.chunk"`). Our AG2 path is non-streaming today, so this isn't a concern; if/when we stream debate transcripts to the user, surface usage from the final chunk.

## What our code does today vs. what's optimal

| Behavior | Today | Optimal | Sprint |
|---|---|---|---|
| Model name resolution | Per-router matrix in `pro/router.py` | Same (data is fine) | — |
| AG2 price WARNING | Silenced via `_price_per_1k_for(model)` injection (commit `adc268e`) | Same | Done |
| Pre-flight cost estimate | `gecko_core.routing.costs.estimate_cost_usd` | Same | Done (S3-05) |
| Post-call billing accuracy | Read `usage` from AG2's wrapped response (sometimes lossy) | Read `usage.cost` directly from OpenRouter response | **Sprint 4 follow-up** |
| Fallback on rate limit | Tenacity retry | Add `models` array to `extra_body` for cross-provider fallback | Sprint 4 |
| Streaming usage | N/A (non-streaming) | Last-chunk surfacing if we add streaming | V2 |
| HTTP-Referer / X-Title | Set in `extra_headers` | Same | — |

## Sprint 4 follow-up ticket sketch

**S4-XX: surface OpenRouter `usage.cost` in session economics**
- After AG2 GroupChat returns, walk each agent's `client.total_usage_summary` (or equivalent) for the `cost` field directly from response payloads.
- Compare against our pre-flight estimate (`MODEL_PRICING` × tokens) to catch table drift.
- Persist the truth (`usage.cost` sum) to `sessions.cost_llm_usd`, not the estimate.
- Add ledger reconciliation alarm if drift > 10% (suggests our price table is stale).

**S4-YY: cross-provider fallback chain in gecko_route**
- Extend `RouteResult` model with `fallback_chain: list[str]` config field.
- Pass via `extra_body.models` to OpenAI client.
- Surface `model_used` (which one actually answered) in the demo log line.

## Reference snippet — minimal OpenRouter-correct call

```python
import openai

client = openai.OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=settings.openrouter_api_key,
    default_headers={
        "HTTP-Referer": "https://app.geckovision.tech",
        "X-Title": "Gecko",
    },
)

resp = client.chat.completions.create(
    model="openai/gpt-4o-mini",
    messages=[{"role": "user", "content": "..."}],
    extra_body={
        "models": ["openai/gpt-4o-mini", "anthropic/claude-sonnet-4-6"],
        "provider": {"sort": "price"},
    },
)

cost = resp.usage.cost  # USD, already computed
tokens_in = resp.usage.prompt_tokens
tokens_out = resp.usage.completion_tokens
```

This is the shape `gecko_route` Path B should emit.
