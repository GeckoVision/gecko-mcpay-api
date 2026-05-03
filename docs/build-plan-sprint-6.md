# Sprint 6 — Memory mining, tier ladder, live reconciliation, V2 sources, catalog auto-refresh

**Status:** ready to fire
**Predecessor:** Sprint 5 shipped (commit `58b20f9`) — native memory layer + paid `/plan` + `pulse_runs` + tiered `/route`
**Goal:** turn the memory layer from a write-only journal into a reasoning surface, fold the per-tier ladder into the user-facing pricing UX, reconcile stub-mode receipts with live x402 settlement, expand source coverage beyond Tavily+YT, and keep the model catalog from rotting.

---

## Tracks

Each track ships independently. Run in parallel where possible; reconcile via a final integration pass.

### Track A — Memory mining (S6-MINE-01..03)

The journal exists; nothing reads it yet. This track turns memory into priors that bias future calls.

- **S6-MINE-01 — `gecko_memory_query` tool**
  Query memory by `(scope, entry_type, since, k)` returning ranked entries. Surface in MCP + `/memory/query`. Wraps `MemoryStore.search` with filters; no new infra.

- **S6-MINE-02 — Prior injection in `/research` and `/plan`**
  Before debate/advisor calls, fetch top-k prior `verdict_received` + `feature_shipped` entries for the project, render as a "PRIOR DECISIONS" context block, prepend to system prompt. Cap at ~800 tokens. Gated by `GECKO_MEMORY_PRIORS=1` env (default on once eval gate confirms no regression).

- **S6-MINE-03 — Eval gate: priors-on vs. priors-off**
  Re-run `tests/eval/holdout-live` with priors enabled vs. disabled. Confirm verdict accuracy ≥ baseline; flag drift on ideas where priors invert the verdict (those are the interesting cases — log to `docs/eval/priors_inversions.md`).

**Owner:** software-engineer (priors render + injection), data-engineer (query indexes if needed)

### Track B — Tier ladder UX (S6-TIER-01..03)

The catalog supports 4 tiers; the user surface only exposes "basic/pro". Make the ladder visible and selectable.

- **S6-TIER-01 — Per-tier price quotes**
  `GET /pricing` returns `{tier_preset: {price_usd, est_latency_ms, model_summary}}` for each Tier × endpoint. Sources from catalog + `MODEL_PRICING`. No payment changes — informational only.

- **S6-TIER-02 — `tier_preset` query param on `/research`, `/plan`, `/route`**
  Already plumbed through `RouterConfig`; add to FastAPI request models, validate against Tier enum, default `balanced`. Update OpenAPI.

- **S6-TIER-03 — CLI `bb pricing` subcommand**
  Prints the ladder as a Rich table. Reads from `/pricing`. Lets users see "this idea on `quality` costs $0.40 vs $0.05 on `budget`" before committing.

**Owner:** software-engineer

### Track C — Live x402 reconciliation (S6-RECON-01..02)

Stub mode writes synthetic `tx_signature` strings. Live mode writes real Solana sigs. Right now there's no path to verify a sig actually settled on-chain.

- **S6-RECON-01 — `gecko_economics --verify` flag**
  When set, fetch each `tx_signature` from Helius DAS / RPC; assert status == `confirmed`, amount matches expected, recipient matches treasury. Report mismatches as a Rich diff. Skips stub sigs (prefix `stub_`).

- **S6-RECON-02 — Nightly reconcile job**
  `scripts/reconcile_economics.py` — pulls last 24h of `pulse_runs` + `memory` rows with `tx_signature`, runs verify, posts a summary to a Slack/Discord webhook (env-gated). Stub-only by default; live mode behind `GECKO_X402_MODE=live`.

**Owner:** web3-engineer

### Track D — V2 sources (S6-V2-01..03)

Tavily + YT transcripts cover ~70% of high-signal sources. Missing: Reddit threads, GitHub README/discussions, paper PDFs.

- **S6-V2-01 — Reddit adapter**
  `gecko_core/sources/reddit.py` — accepts `https://reddit.com/r/.../comments/...` URLs, fetches via `https://www.reddit.com/.../.json`, chunks top-N comments by score. Cap fetched comments at 100. Respect rate limit (1 req/s).

- **S6-V2-02 — GitHub adapter**
  Accepts repo URLs and discussion URLs. README via `raw.githubusercontent.com`. Discussions via REST API (token optional, falls back to anon at lower rate). Indexes README + open discussion bodies.

- **S6-V2-03 — PDF adapter**
  `pypdfium2` extraction for arxiv + dropbox-style PDF URLs. Cap at 100 pages. Reject if extracted text < 500 chars (likely scanned, not native PDF).

Wire all three into `discover_sources` selection logic; URL pattern → adapter map.

**Owner:** data-engineer

### Track E — Catalog auto-refresh (S6-CATALOG-01..02)

`model_catalog.json` is hand-curated. SWE-bench/openrouter prices drift weekly. Catch drift instead of finding out from a broken eval gate.

- **S6-CATALOG-01 — `scripts/check_catalog_drift.py`**
  Pulls current OpenRouter pricing for every catalog model, diffs against `model_catalog.json`, exits non-zero if any price changed > 10% or model is delisted. Wire into a weekly GitHub Action (`.github/workflows/catalog-drift.yml`).

- **S6-CATALOG-02 — Auto-PR on drift**
  When the action detects drift, open a PR titled `catalog: refresh prices YYYY-MM-DD` with the json updated. Requires human approval (no auto-merge — price changes can surface model deprecations that warrant a substitution).

**Owner:** staff-engineer (workflow), data-engineer (script)

---

## Acceptance

- [ ] All 5 tracks merged behind feature flags where appropriate.
- [ ] Eval gate passes (general 0.95+, holdout 1.0, holdout-live 0.95+) with priors ON.
- [ ] `bb pricing` renders the ladder cleanly.
- [ ] `gecko_economics --verify` runs cleanly against last sprint's stub sigs (no false positives).
- [ ] V2 source adapters hit by `bb research` smoke against fixture URLs.
- [ ] Catalog drift action runs once green on `main`.

## Out of scope

- Mainnet cutover (still gated on user choice + funded wallet).
- V3 dashboard (lives in `gecko-mcpay-app`).
- Landing v2 implementation (briefs are in `gecko-mcpay-landing`).

## Test plan

See `docs/test-plan-sprint-2-to-5.md` for the regression baseline. Sprint 6 adds:

- `tests/memory/test_priors_injection.py` — render block ≤ 800 tokens; opt-out flag honored.
- `tests/sources/test_reddit_adapter.py` + `test_github_adapter.py` + `test_pdf_adapter.py` — fixture-based, no network.
- `tests/eval/test_priors_inversions.py` — captures ideas where priors flip the verdict.
- `tests/economics/test_verify.py` — stub vs. live sig discrimination.
