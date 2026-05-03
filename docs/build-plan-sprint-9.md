# Sprint 9 — Config plane finishing, advisor reliability, Colosseum-style verdict structure

**Status:** ready to fire
**Predecessor:** Sprint 8 (10 commits) shipped ingestion fix, config unification (incomplete), live x402, polish.
**Driver:** post-Sprint-8 dogfood loop on the Gecko pitch surfaced 4 new findings (F13–F16) + 2 borrowable techniques from Colosseum Copilot research.

**Done = `bb doctor` is the canonical pre-flight gate; advisor panel never returns empty voices silently; verdict shape is structured enough to drive precedent labeling.**

---

## Tracks

### Track A — Config plane finishing (S9-CONFIG-03, S9-DOCTOR-01, S9-CONFIG-04)

Three coupled fixes around the config plane and `bb doctor` (the tool we shipped in Sprint 8 that is itself buggy — the dogfood is working).

- **S9-CONFIG-03 — Fix F15: legacy precedence too aggressive.**
  In `packages/gecko-core/src/gecko_core/orchestration/settings.py::resolve_llm_config()`, the rule "legacy wins when both `LLM_ROUTER` and `GECKO_LLM_ENDPOINT` are set" treats any `GECKO_LLM_ENDPOINT` value as set — even default. Replace with: legacy wins ONLY when the user has *explicitly* set `GECKO_LLM_ENDPOINT` to a non-default value AND `LLM_ROUTER` is unset. When `LLM_ROUTER=openrouter` is present, OpenRouter wins regardless of `GECKO_LLM_ENDPOINT`. Reproduces in dogfood: `bb plan` returns `Error code: 400 - 'invalid model ID'` on every voice when `.env` has `LLM_ROUTER=openrouter` + `GECKO_LLM_ENDPOINT=https://api.openai.com/v1`. Add regression test in `tests/orchestration/test_advisor_router.py`.

- **S9-DOCTOR-01 — Fix F13 + F14 in `bb doctor`.**
  - **F13:** `bb doctor` doesn't load `.env`. Add explicit `dotenv.load_dotenv()` at the top of `apps/cli/src/gecko_cli/commands/doctor.py::doctor_cmd` (or in a CLI-wide hook). Verify `bb doctor` shows `Supabase URL OK` when `.env` has `SUPABASE_URL=...`.
  - **F14:** doctor checks `FRAMES_API_KEY` env var, but the real apiToken lives in `~/.agentwallet/config.json`. Update the wallet check to (1) try the env var, (2) fall back to reading `~/.agentwallet/config.json` (existing helper in `gecko-mcp/src/gecko_mcp/wallet.py::_read_config` — extract a shared util in `gecko-core/src/gecko_core/wallet/agent_config.py` to avoid duplication). Mask token to `set (...XXXX)` per the existing pattern. Add tests for both paths.

- **S9-CONFIG-04 — `bb doctor` self-tests the LLM call.**
  Today doctor only checks env presence. Add a 6th row: "LLM ping" — issues a 5-token chat completion against the resolved router/endpoint with a stub prompt ("ping"). Asserts 200 + non-empty response. Catches F15 + F16 (silent empty completions) at config time, not at first paid call. Cost cap: ≤ $0.0001 per `bb doctor` run.

**Owner:** software-engineer
**Acceptance:** `bb doctor` returns all green on a fresh checkout with only `.env` loaded — no env overrides needed for `bb plan` / `bb research` to work afterward.

### Track B — Advisor reliability (S9-ADVISOR-01)

- **S9-ADVISOR-01 — Fix F16: silent empty closing line.**
  In `packages/gecko-core/src/gecko_core/orchestration/advisor/agents.py`, when an LLM call returns content that doesn't match `_CLOSING_PATTERNS`, the voice silently emits an empty closing line. Reproduces: in the post-Sprint-8 dogfood, business_manager voice returned `"(voice produced no closing line)"`.
  Fix:
  1. **Detect**: explicit check for empty/missing closing line.
  2. **Retry once** with a stricter system prompt suffix ("You MUST end with a line starting with one of: ## Strategic priority / ## Critical path / Lever this sprint: / Top backlog item: / ## Sprint plan: ").
  3. **Surface**: if retry also fails, emit `"(voice failed: no_closing_line after 2 attempts)"` and increment a `voices_no_closing_line` counter on the panel result so callers can detect quality regressions.
  Add tests covering: matched-on-first-try, matched-on-retry, no-match-after-retry.

**Owner:** software-engineer
**Acceptance:** running `bb plan` 5x against the same session, no voice silently returns empty; if a voice truly can't close, error is explicit.

### Track C — Colosseum-derived verdict structure (S9-PRECEDENT-01, S9-VERDICT-01)

Two cheap structural improvements borrowed from the Colosseum Copilot deep-dive (`docs/community/colosseum-research-deep-dive.md`):

- **S9-PRECEDENT-01 — Ship/kill labels on precedent corpus.**
  Today our precedent retrieval (Pro debate's RAG context) treats all precedents equally. Colosseum's wedge is *labeled outcomes* (winners cohort vs all). Add a `precedents.outcome` column: `shipped | killed | unknown`. Backfill with `unknown` for existing rows. Add a sidecar table `precedent_outcomes` with `(precedent_id, outcome, source_url, labeled_at, labeled_by)` so we can append labels over time without rewriting the precedent.
  Update the critic agent's prompt to receive precedents grouped by outcome ("Here are 3 SHIPPED, 2 KILLED, 4 UNKNOWN"). Don't auto-label yet — that's Sprint 10. Just make the schema ready.

- **S9-VERDICT-01 — Gap taxonomy in ValidationReport.**
  Today `ValidationReport` is prose. Add a structured `gap_classification` field: `Full | Partial[segment|UX|geo|pricing|integration] | False`. Update the judge agent's prompt to emit one of these explicitly. Surface in `bb research` output as a bold one-liner: "Gap: Partial[pricing] — competitor X covers segments A/B but not C." Render in PRD too. Add tests verifying the judge always emits a valid taxonomy value.

**Owner:** data-engineer (precedents schema), software-engineer (verdict shape + judge prompt)

---

## Out of scope

- Auto-labeling of precedents (Sprint 10 — needs a labeling UI or LLM extractor).
- Live-V1 eval gate run (now unblocked but separate work).
- Mainnet cutover.
- V3 dashboard.
- Integration with Colosseum Copilot API as a source (interesting but not high-leverage right now).

## Acceptance (sprint-level)

- [ ] `bb doctor` returns all green on `.env` alone, no overrides
- [ ] `bb plan` works without `GECKO_LLM_ENDPOINT` override
- [ ] `bb plan` repeatedly produces 5/5 closing lines (or explicit failures)
- [ ] `precedent_outcomes` migration applied; critic receives grouped precedents
- [ ] `ValidationReport.gap_classification` populated on every research run
- [ ] Sprint 9 dogfood loop passes the post-Sprint-9 stress matrix (run after all tracks land)

## Test plan

Re-run the post-Sprint-8 dogfood: `bb research --idea "Gecko: pay-per-use AI co-founder MCP for Claude Code"` then `bb plan <session>` then `bb sprint-review`. Should produce identical-quality output to the Sprint 8 dogfood without any env overrides AND with a populated `gap_classification`.

## Reference

- `docs/audits/integration-audit-2026-04-30.md`
- `docs/community/colosseum-research-deep-dive.md`
- `docs/community/solana-claude-collaboration.md`
- Post-Sprint-8 dogfood findings F13–F16 (this doc)
