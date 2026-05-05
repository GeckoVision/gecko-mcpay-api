# TICKET: basic-synthesis-empty-content-2026-05-05

**Date:** 2026-05-05  
**Status:** Open — P0 (every basic-tier session fails)  
**Severity:** P0 — `OrchestrationError: LLM returned empty content` on every call across all three tier presets  
**Owner:** software-engineer + ai-ml-engineer

---

## Symptom

After deploying 0.2.10 (provider pin + diagnostic logging), every basic-tier
research call fails:

| Session | tier_preset | Resolved model | Error |
|---|---|---|---|
| `cba87d9d-f166-4934-980d-7d97e03aec17` | balanced | `openai/gpt-4.1-mini` | empty content |
| `19f61d9d-0491-4554-969a-515766353736` | budget | `x-ai/grok-4.1-fast` | empty content |
| `380cf8e0-6b1b-434a-ba85-5b6f2a239ab2` | quality | `openai/gpt-5.5` | empty content |

## Critical observation

**Zero of these three calls appear in the OpenRouter activity log.** Last
100 OpenRouter rows show only `deepseek-v4-flash` post-processor calls. Either:

1. The request is being rejected at the OpenRouter API gateway with a 4xx that
   doesn't generate an activity entry
2. The OpenAI Python SDK is silently returning empty content instead of raising
3. `LLM_ROUTER` is set to `openai` (not `openrouter`) and the call is going to
   OpenAI direct — but OpenAI access has its own issue (key invalid, etc.)

## Likely root cause

The 0.2.10 patch in `packages/gecko-core/src/gecko_core/orchestration/basic.py`
added an `extra_body` block for `openai/*` model slugs:

```python
if model.startswith("openai/"):
    create_kwargs["extra_body"] = {
        "provider": {"order": ["OpenAI"], "allow_fallbacks": False},
        "transforms": [],
    }
```

**Failure modes to investigate:**

A. The `extra_body` syntax may not be accepted by the OpenAI Python SDK's
   `with_raw_response.create()` wrapper. Verify with a direct call.

B. If `LLM_ROUTER=openai` (not openrouter), the call goes to OpenAI direct.
   OpenAI rejects unknown body fields with 400. The `extra_body` would cause
   that. The OpenAI SDK should raise on 400, but maybe it doesn't.

C. The `provider.allow_fallbacks: False` may be too strict — if OpenAI is
   rate-limited at request time, OpenRouter returns no provider, and the
   response is empty content with `finish_reason="error"`.

D. Budget tier (`x-ai/grok-4.1-fast`) does NOT have `extra_body` set (the
   `model.startswith("openai/")` check is false). It also returns empty
   content. **This rules out the `extra_body` as the sole cause** —
   something else is wrong on the request path for non-openai models too.

## Diagnostic steps required

1. **ECS task logs.** Pull the CloudWatch logs for the three session
   timestamps. The 0.2.10 logger.info line is:
   ```
   llm.call model=... provider=... finish=... prompt_tokens=... completion_tokens=... gen_id=...
   ```
   - If this line is **present**: the `_call_llm` reached OpenRouter and got a
     200 OK with empty content. Look at `provider` and `finish_reason`.
   - If this line is **absent**: the call failed before reaching OpenRouter.
     The exception would be in the log instead. Look for a 401/400/connection
     error.

2. **SSM verification.** Confirm the active values:
   ```bash
   aws ssm get-parameter --name /gecko-api/LLM_ROUTER --region us-east-2 --query "Parameter.Value" --output text
   aws ssm get-parameter --name /gecko-api/OPENROUTER_API_KEY --with-decryption --region us-east-2 --query "Parameter.Value" --output text | head -c 12
   aws ssm get-parameter --name /gecko-api/OPENAI_API_KEY --with-decryption --region us-east-2 --query "Parameter.Value" --output text | head -c 12
   ```

3. **Local reproduction.** Run `bb research` locally with real OpenRouter env
   vars (and `--auto-approve` to skip the source prompt). If it succeeds
   locally with the same code, the issue is environment-specific to ECS.

## Required Fix

**Short-term (rollback):** if this issue is blocking, revert 0.2.10's
`extra_body` block and ship 0.2.11 without the provider pin while we
diagnose. The previous failure (truncated JSON) was at least sometimes
recoverable; empty content is a complete block.

**Medium-term:** see ticket `e2e-local-real-openrouter-test.md` and
`bypass-openrouter-for-synthesis.md`.

## Files

- `packages/gecko-core/src/gecko_core/orchestration/basic.py` lines ~243–303
  (the `_call_llm` body with the new `extra_body` block + diagnostic logger)
- `infra/ecs-stack.yml` — ECS task definition env/secrets
- `infra/push-ssm-params.sh` — what gets pushed to SSM
