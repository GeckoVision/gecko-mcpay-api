# LLM / embedding provider routing map

**Date:** 2026-05-17
**Why:** founder asked which paths call Anthropic, and whether to consolidate
onto OpenRouter. This maps every LLM + embedding call the system makes.

## The map

| Path | What it is | Provider | How it's reached | Model | Key |
|---|---|---|---|---|---|
| **Trade panel** (`gecko_trade_research`) | THE product — 7-voice panel | via `LLM_ROUTER` → **OpenRouter** | `main.py` `_trade_panel_llm_config()` calls `resolve_router()` (S35-#101); both `/trade_research` + `/trade_research/pro` | `openai/gpt-4o-mini` (router-namespaced) | `OPENROUTER_API_KEY` |
| `gecko_research` basic | founder-advisory, single pass | via `LLM_ROUTER` | OpenAI-compatible client; `LLM_ROUTER` picks base_url | gpt-4o-mini class | per router |
| `gecko_research` pro debate | AutoGen multi-agent | via `LLM_ROUTER` → **OpenRouter** | router; the routing matrix can select Claude models (`anthropic/claude-*`) — served through OpenRouter | gpt-4o / claude-* | `OPENROUTER_API_KEY` |
| **Rubric judge — trade** (`tests/eval/scripts/score_defi_trade_rubric.py`) | EVAL harness | **Anthropic, direct** | `from anthropic import Anthropic` SDK | `claude-sonnet-4-6` | `CLAUDE_API_KEY` |
| **Rubric judge — advisory** (`tests/eval/rubric.py`) | EVAL harness | **Anthropic, direct** | `from anthropic import Anthropic` SDK | `claude-sonnet-*` | `CLAUDE_API_KEY` |
| Embeddings | corpus + query vectors | **Voyage, direct** | `voyageai` SDK | `voyage-3-large` | `VOYAGE_API_KEY` |
| Reranker | trade-retrieval rerank | **Voyage, direct** | `voyageai` rerank | `rerank-2` | `VOYAGE_API_KEY` |
| Claude Code subagents (ai-ml-engineer, data-engineer, quant-analyst, …) | DEV-TIME — building Gecko, not runtime | Anthropic, via the Claude Code harness | the agent fleet this session | Claude sonnet/opus | the founder's Claude Code account |

## Who calls Anthropic — the direct answer

**Product runtime: nobody.** The trade panel, `gecko_research` basic, and the
basic-tier generation never instantiate the Anthropic SDK. They all speak the
OpenAI-compatible protocol.

**Direct Anthropic API callers = exactly two, both EVAL harness:**
1. `score_defi_trade_rubric.py` — the trade-rubric judge. **This is what your
   Anthropic dashboard screenshot shows** — `claude-sonnet-4-6`, ~8k in / ~500
   out, one call per fixture. It is the S34-WS5 ship-gate run (#89) in
   progress; it stops when #89 finishes. Judge-side cost of the whole N=30 run
   ≈ **$1** (~$0.032/call × 30).
2. `tests/eval/rubric.py` — the advisory-idea rubric judge, same pattern.

Both are `tests/eval/` — they grade output; they are not part of what a paying
user calls.

**Claude can also be reached via OpenRouter** — the routing matrix
(`routing/matrix.py`) maps the `reasoning`/`code` tiers to `claude-sonnet-4-6` /
`claude-opus-4-7`, and with `LLM_ROUTER=openrouter` those resolve as
`anthropic/claude-*` through OpenRouter. So the pro path *can* spend on Claude
— but billed via OpenRouter, not direct.

## OpenRouter usage — updated S35-#101

`LLM_ROUTER=openrouter` is set. As of S35-#101 the **trade panel** honors it:
`_trade_panel_llm_config()` resolves through `pro/router.py:resolve_router()`,
so both `/trade_research` endpoints now hit OpenRouter (model namespaced to
`openai/gpt-4o-mini`, `HTTP-Referer`/`X-Title` threaded as `default_headers`).
The only remaining direct-provider callers are the **rubric judges**
(Anthropic-direct, intentionally — funded, OpenAI-tool-format port is high
risk for low value). Net: OpenRouter (panel + pro debate), Anthropic (judges +
dev subagents), Voyage (embeddings/rerank). The separate OpenAI panel bill is
retired.

## On "redistribute to OpenRouter, it's cheaper"

One correction: for `gpt-4o-mini` and Claude, OpenRouter is **~price-parity**,
not cheaper — it routes to the same upstreams and adds a small credit-purchase
fee. The real win of consolidating onto OpenRouter is **operational**: one
bill, automatic provider failover, and no per-provider credit scrambles (the
exact thing that prompted this — OpenAI/Anthropic credits running low
independently). Worth doing — for resilience, not for a lower per-token price.

It is **not a one-env-flip**:
- Trade panel — change the `llm_config` builder (`main.py`, both
  `/trade_research` endpoints) to the OpenRouter base_url + key, model id
  namespaced (`openai/gpt-4o-mini`). Moderate, mechanical.
- Rubric judges — they use the Anthropic SDK with Anthropic-shaped
  `tool_use`. Routing via OpenRouter means swapping to an OpenAI-compatible
  client and porting the `submit_rubric` tool to OpenAI tool-call format. A
  real rewrite with verification risk (the judge's structured output is
  load-bearing for every score). Low value — the eval spend is ~$1/run — and
  high risk; recommend leaving the judges on direct Anthropic.

**Recommendation:** an S35 workstream — route the *trade panel* through
`LLM_ROUTER`/OpenRouter (kills the panel's separate OpenAI bill, adds
failover), leave the rubric judges direct. Execute after #89 completes — do
NOT change routing while #89 is mid-run and actively calling Anthropic.
