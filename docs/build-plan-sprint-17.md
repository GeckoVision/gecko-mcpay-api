# Sprint 17 — Demo-Grade Verdict, On the Path

**Window:** 2026-05-02 → 2026-05-08 (<1 week, demo end-of-sprint)
**Predecessor:** Sprint 16 (Bazaar consumer + twit.sh on basic-tier hot path)
**Inputs:** S16 stub-smoke review (2026-05-01), HTML design/business lenses, bazaar consumer design memo

## Theme

Close the gap between what `bb research` can produce in stub today and what we can put in front of a founder without flinching. The S16 smoke surfaced four trust-breakers: missing persistence, miscalibrated verdicts, off-tone language, and dictionary-bombed citations. Fix those four and the demo arc carries itself. Everything else is upside.

## MUST-SHIP (demo blockers)

| Ticket | Owner | Status | Acceptance |
|---|---|---|---|
| S17-PERSIST-01 | software-eng | ✅ landed 2026-05-02 | CLI workflow persists `result_json`; advisor + scaffold downstream load it without error. Regression test asserts row contains non-null `result_json` after `bb research`. |
| S17-VERDICT-01 | ai-ml | ✅ landed 2026-05-02 | Gap-tagged verdicts respect tag scope (Partial:UX cannot KILL); `evidence_strength` floors verdict to REFINE when citations ≤2 OR max cosine sim <0.4. Eval harness threshold updated; holdout regression green. |
| S17-TONE-01 | software-eng | ✅ landed 2026-05-02 | KILL→PIVOT, BUILD→GO across `gecko_core`, CLI renderer, MCP surface, API response model. Pattern A enforced; backfill migration + `_missing_` shim for legacy rows. |
| S17-DISCOVERY-01 | ai-ml | ⏳ start Monday | Tavily wrapper rejects domains matching `*.txt`, `*.dat`, `dict.*`, `*-words/*` and a small curated blocklist. Category hints injected for `agentic-economy / marketplace / web3` queries. Holdout idea "judgment as a service" returns ≥6/8 substantive sources. |

Three already in flight; DISCOVERY-01 is the new ask and the highest-risk item.

## NICE-TO-SHIP (if MUST lands by Wednesday EOD)

| Ticket | Owner | Why nice |
|---|---|---|
| S17-HTML-01 | product-designer + software-eng | `--format html` long-scroll verdict-first render per design lens. JSON embedded as canonical data layer. Wow delta for demo, terminal stays the fallback. |
| S17-PITCH-NARRATIVE-01 | product-designer | `--pitch narrative` 5-section markdown (problem / wedge / customer / GTM / risks). **Insight layer only — not a deck.** Downstream rendering is Claude Design / PPT skills. |
| S17-DOCTOR-BAZAAR-ROW-01 | data-eng | Apply `20260501150000_bazaar_spend_ledger.sql`; `gecko-mcp doctor` shows bazaar row populated. Low risk, high signal. |
| S17-X402-LIVE-CANARY-01 | web3-eng | One real $0.01 Bazaar call on Base mainnet, captured as VCR cassette per Pattern C. **Gated on wallet funded by Wednesday.** Drop if not ready — do not leave half-done. |

## DEFER (S18+)

| Ticket | Reason |
|---|---|
| S17-INGEST-TIMEOUT-01 | Mostly hidden once DISCOVERY-01 blocks dictionary domains. Real fix (chunked upserts) deserves its own slice. |
| S17-DISPATCH-CONSOLIDATE-01 | Two paths work today; consolidating one week before demo is gratuitous risk. S18 with a contract test (Pattern C). |
| S17-COST-BAZAAR-COL-01 | Cost piggybacking works; dedicated column is hygiene. Bundle with the next economics-ledger pass. |
| S17-DISCOVERY-TAVILY-RESEARCH-SPIKE-01 | Adds variance during a demo week. Spike post-demo with proper A/B on the holdout eval. |

## Demo Arc — moments the MUST-SHIP unlocks

The demo script is separate work. These are the moments S17 makes load-bearing:

1. **`bb research --idea "<founder's actual idea>"` runs end-to-end** — PERSIST-01 means the session is queryable after the run; no "let me re-run that" moment.
2. **Verdict reads as PIVOT or GO, with calibrated confidence** — TONE-01 + VERDICT-01. Founder hears product language, not engineering language.
3. **Citations are real domains the audience recognizes** — DISCOVERY-01. No `snap.berkeley.edu/dictionary.txt` on screen.
4. **Evidence-strength floor visible in the verdict explanation** — "REFINE: only 2 citations above similarity floor" reads as honest, not broken. This is the wedge per Pattern D — adversarial-debate verdict + grounded dissent, not orchestration.
5. **(If HTML lands)** Same verdict rendered as a shareable HTML artifact the founder can forward.

What the demo deliberately does NOT show: model names, token counts, per-call costs (project convention), raw reputation floats (bucketed only), wallet-specific branding (neutrality).

## Risk Register

| Risk | Likelihood | Mitigation |
|---|---|---|
| DISCOVERY-01 turns into a rabbit hole — domain blocklists are a losing game long-term | Med | Ship the blocklist + category hints as the V1 floor. Acceptance is "holdout idea returns 6/8 substantive sources," not "perfect discovery." Spike Tavily Research in S18. |
| VERDICT-01 threshold tuning shifts holdout eval scores in unintuitive ways the day before demo | Med | Freeze thresholds Friday EOD. Any drift Monday morning rolls back, not forward. Eval harness must be green on Friday's commit. |
| HTML-01 sneaks into MUST because it's visually compelling, eats the week | Low-Med | Staff-eng holds the line: HTML gated on all four MUST being green by Wednesday EOD. No exceptions. |

## Workflow gate (per CLAUDE.md)

Before merging any S17 ticket:
- `uv run ruff format && uv run ruff check --fix`
- `uv run mypy packages/ apps/`
- `uv run pytest`
- Pipeline-touched: `bb research --idea "smoke test"` in stub mode
- Env/schema-touched: `gecko-mcp doctor` passes
- API-shape-touched: notify `frontend-engineer` in `gecko-mcpay-app` (OpenAPI is the contract)

## Out of scope (explicit)

- Pitch decks. Per `project_output_layer_positioning`, Gecko produces the insight layer; rendering belongs to Claude Design / PPT skills downstream.
- clawrouter deprecation. Stays — load-bearing for cost telemetry per `project_clawrouter_deprecated`.
- Public reputation surfaces with raw floats. Buckets only.

## Open questions

1. Wallet funded for X402-LIVE-CANARY-01 by Wednesday? If no, drop entirely — don't leave dangling.
2. Demo audience composition — payments folks vs founders/investors? Shifts canary priority.
