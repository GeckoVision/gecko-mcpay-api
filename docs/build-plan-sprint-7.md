# Sprint 7 — Dogfood, CI safety net, test plan

**Status:** ready to fire
**Predecessor:** Sprint 6 shipped (commits `f153c4c`, `9dae155`, `0f37521`, `b5142e0`) — memory query + tier ladder + reconcile + V2 sources + catalog drift.
**Goal:** ship the missing meta-tool so Gecko can review *its own delivery*; lock in a CI safety net so regressions surface before merge; document the manual + automated test plan covering Sprint 2 → 6.

The dogfood attempt at the end of Sprint 6 surfaced the gap: `gecko_advise` and `gecko_plan` require a research session_id — there's no surface for "review what we shipped this sprint". Sprint 7 closes that loop.

---

## Tracks

### Track A — Dogfood meta-tool (S7-DOGFOOD-01..03)

- **S7-DOGFOOD-01 — `gecko_review` core**
  New module `packages/gecko-core/src/gecko_core/review/`. Reads `git log --since=<date>` + memory entries (`scope=project`, `entry_type` in `{verdict_received, scaffold_generated, plan_advised, advisor_voiced, pulse_run, feature_shipped}`) + on-disk `docs/build-plan-sprint-*.md`. Synthesizes a structured `SprintReview` object: shipped (bullets), weakest_link (string), proposed_next (3 bullets).

- **S7-DOGFOOD-02 — `gecko_review` MCP tool + `POST /review`**
  Wraps the core. Default scope `since=14d`. Optional `tier_preset` for the synthesis LLM call. **Free** in stub mode; **$0.10** in live (one quality-tier call). Auto-journals as `entry_type=sprint_reviewed`.

- **S7-DOGFOOD-03 — `bb sprint-review` CLI**
  Renders the `SprintReview` as a Rich panel. `--since` / `--project-id` / `--write-doc` flags. `--write-doc` saves the output to `docs/sprint-reviews/YYYY-MM-DD.md` for archival.

**Owner:** software-engineer

### Track B — CI safety net (S7-CI-01..03)

- **S7-CI-01 — End-to-end smoke job**
  `.github/workflows/e2e-smoke.yml`: spins up Postgres + pgvector, runs Supabase migrations, starts gecko-api in stub mode, runs MCP tools (`gecko_research` → `gecko_scaffold` → `gecko_plan` → `gecko_pulse` → `gecko_review`) against it, asserts receipts in `gecko_economics`. Fails the build on any non-2xx or missing receipt.

- **S7-CI-02 — Fix `X402_MODE` defaults**
  Update `.env.example` to `X402_MODE=stub` with a comment block explaining the `live` cutover steps. Local `.env` fix requires user action (we don't touch their `.env`).

- **S7-CI-03 — Sources collision regression test**
  The `gecko_core.sources` shadowing issue Track D flagged needs a guard — add `tests/sources/test_dispatcher_import.py` that imports `discover_adapter` from a fresh subprocess Python, asserting no shadow. Catches the bug class on next refactor.

**Owner:** staff-engineer (workflow), software-engineer (test)

### Track C — Test plan documentation (S7-TESTPLAN-01)

- **S7-TESTPLAN-01 — `docs/test-plan.md`**
  Comprehensive doc covering Sprint 2 → 6:
  - **Automated coverage matrix**: every shipped feature × test file × what it asserts.
  - **Manual smoke checklist**: 10–15 minute walkthrough an engineer runs before any release.
  - **Dogfood flow** (the new bit): how to run `gecko_review` against the repo itself, what good output looks like, what to do with the "weakest_link" finding.
  - **Live-mode pre-flight**: the funding + reconcile checks before flipping `X402_MODE=live`.
  - **Eval gates**: how to run general / crypto / saas / holdout / holdout-live, and the pass thresholds.

**Owner:** software-engineer or staff-engineer

---

## Dogfood test plan (the bit Sprint 7 enables)

### Stub-mode dogfood (no funding required)

```bash
# 1. Confirm stub
grep '^X402_MODE' .env  # must read 'stub'; if 'live', prepend X402_MODE=stub to commands

# 2. Start gecko-api locally
uv run uvicorn gecko_api.main:app --port 8000 &

# 3. Run the loop on the repo itself
bb research --idea "Should Sprint 8 prioritize live cutover or V3 dashboard?"  # writes session_id
bb advise --session <id> --voice cto    # single voice
bb plan --session <id>                   # full panel
bb sprint-review --since 14d             # NEW — Sprint 7 deliverable
bb pulse --session <id>                  # delta vs. prior

# 4. Verify receipts
bb economics <session_id>                # all stub_ prefixed
```

**Expected:** every call succeeds, journal entries land in memory, `gecko_review` returns a `SprintReview` whose `shipped` bullets match the last 14 days of git log.

### Live-mode dogfood (optional, requires ~$1 SOL)

```bash
# 1. Fund client wallet with ~$1 SOL (gas only — USDC roundtrips to your own treasury)
#    Frames.ag UI → deposit SOL to the wallet shown in the OTP flow

# 2. Flip mode for one call
X402_MODE=live bb research --idea "smoke test live x402"

# 3. Verify on-chain
bb economics <session_id> --verify       # Sprint 6 Track C deliverable
```

**Expected:** real `tx_signature` (not `stub_` prefixed), reconcile shows status `confirmed`, treasury balance increases by the USDC amount minus facilitator fee.

---

## Acceptance

- [ ] `gecko_review` MCP tool returns valid `SprintReview` for any project_id with ≥1 memory entry.
- [ ] `bb sprint-review --write-doc` produces a markdown file that builds in `docs/`.
- [ ] E2E smoke workflow green on a fresh PR.
- [ ] `docs/test-plan.md` covers every endpoint shipped Sprint 2-6.
- [ ] One round of stub-mode dogfood completes cleanly on a clean checkout.
- [ ] (Optional) one live-mode call lands a real tx_signature and reconciles.

## Out of scope

- **Funding the treasury wallet** — user decision, not blocked on dev work.
- **Live-V1 eval gate run** — separate $5–7 spend, can fire after Sprint 7 lands.
- **V3 dashboard** — `gecko-mcpay-app` repo.

## Timing & order

Track C (test plan doc) can ship same-day; it's pure documentation.
Track A and Track B are independent and can run in parallel.
Live-mode dogfood waits on user funding the client wallet — not blocking.
