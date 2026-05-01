# Gecko docs index

50+ files across 12+ subdirs. This page is the map.

If you're new, read in this order:

1. [`PRD.md`](PRD.md) — what the product is (V1 shipped; V2/V3 planned)
2. [`product-story.md`](product-story.md) — how we got here (Gecko → Builder Bootstrap pivot)
3. [`strategy/bazaar-deeper-thesis-2026-04-30.md`](strategy/bazaar-deeper-thesis-2026-04-30.md) — current macro thesis
4. [`build-plan-sprint-14.md`](build-plan-sprint-14.md) — what's shipping right now
5. [`build-plan-sprint-15.md`](build-plan-sprint-15.md) — what's queued

---

## Build plans (sprint-by-sprint)

Each sprint has a self-contained build plan. Drivers, tickets, owners, acceptance criteria, gate evaluations.

| Sprint | Plan | Focus |
|---|---|---|
| 1–8 | `build-plan-sprint-{1..8}.md` | V1 — CLI, ingestion, basic + pro orchestration, x402 stub→live |
| 9 | [`build-plan-sprint-9.md`](build-plan-sprint-9.md) | Config plane finishing, advisor reliability, Colosseum-style verdict |
| 10 | [`build-plan-sprint-10.md`](build-plan-sprint-10.md) | Live mainnet smoke, position stress matrix, landing-vs-research delta |
| 11 | [`build-plan-sprint-11.md`](build-plan-sprint-11.md) | Verdict unification (KILL / REFINE / BUILD), thesis-aligned landing, ICP convergence |
| 12 | [`build-plan-sprint-12.md`](build-plan-sprint-12.md) | CDP Bazaar listing + Base settlement, SourceProvider Protocol |
| 13 | [`build-plan-sprint-13.md`](build-plan-sprint-13.md) | DeFi vertical suite ($9), Phase Primitive Seam, X402Client Protocol, creator citations |
| 14 | [`build-plan-sprint-14.md`](build-plan-sprint-14.md) | `gecko_pulse` v1, Paragraph MCP, publish.new, twit.sh×Colosseum, S12.5 test policy |
| 15 | [`build-plan-sprint-15.md`](build-plan-sprint-15.md) | Profile registry seam + reputation ledger (dormant; wires up S16) |

---

## Strategy + thesis

Macro thesis, lens reviews, dogfood-driven refinements. The 6-lens profile-thesis synthesis is the most recent convergence point.

| Doc | Date | What it says |
|---|---|---|
| [`strategy/bazaar-deeper-thesis-2026-04-30.md`](strategy/bazaar-deeper-thesis-2026-04-30.md) | 2026-04-30 | Capability is commoditized; judgment is scarce. Bazaar makes capability tradeable; Gecko makes judgment tradeable. |
| [`strategy/profile-thesis-synthesis-2026-05-01.md`](strategy/profile-thesis-synthesis-2026-05-01.md) | 2026-05-01 | 6-lens convergence on profile-typed orchestration. Wedge = adversarial-debate verdict + grounded dissent (NOT orchestration). S15-S17 arc. |
| `strategy/profile-thesis-{ai-ml,web3,data,business-manager,product-designer,staff-engineer}-2026-05-01.md` | 2026-05-01 | Per-lens lens memos; convergence inputs |
| [`strategy/paragraph-publish-new-expansion-2026-04-30.md`](strategy/paragraph-publish-new-expansion-2026-04-30.md) | 2026-04-30 | Theme 2 + 2b: Paragraph MCP ingest + publish.new artifacts |
| [`strategy/2026-05-01-stage3-dogfood-results.md`](strategy/2026-05-01-stage3-dogfood-results.md) | 2026-05-01 | Stage 3 dogfood findings (Sprint 12 close → Sprint 14 input) |
| `strategy/roadmap-sprint-13-to-17-synthesis-2026-04-30.md` | 2026-04-30 | 7-specialist roadmap synthesis |
| `strategy/bazaar-composer-*.md` | 2026-04-30 | 5-vector monetization decision pass |
| [`positioning/2026-04-30-thesis-synthesis.md`](positioning/2026-04-30-thesis-synthesis.md) | 2026-04-30 | Validation layer above x402 — first sub-fold |

---

## Runbooks (operational)

How to run things. Pre-flight gates, mainnet smoke, eval harnesses.

- `runbooks/` — operational playbooks (CDP Bazaar listing, mainnet smoke, eval gate live, payment debugging). See per-file table of contents.
- [`test-plan.md`](test-plan.md) — pre-release test plan (header still labeled S2→S6; refresh tracked as **S15-DOCS-01**).
- [`demo/quickstart.md`](demo/quickstart.md) — 10-min stranger-to-first-receipt walkthrough (verdict words pending refresh — **S15-DOCS-02**).

---

## Diagnostics + audits

Dogfood loops, post-mortems, delta analyses, README/docs audits.

- [`audits/`](audits/) — point-in-time audits (this README refresh: `audits/2026-05-01-readme-docs-audit.md`)
- `diagnostics/` — dogfood findings, landing-vs-research deltas
- [`sprint-reviews/`](sprint-reviews/) — per-sprint retros (e.g. `2026-05-01-s12-retro.md`)

---

## Community

Hackathons, OSS partners, ecosystem positioning.

- `community/` — Colosseum, solana-claude (Superteam Brasil collaborator, not competition — see memory `project_solana_brasil_community.md`), twit.sh integration notes

---

## Marketing + positioning

Landing copy, sub-fold gates, founding-contributor program spec.

- `marketing/` — landing copy + positioning docs
- `positioning/` — thesis synthesis (cross-listed under strategy)

---

## Reference

| Doc | Purpose |
|---|---|
| [`PRD.md`](PRD.md) | V1 / V2 / V3 product requirements |
| [`product-story.md`](product-story.md) | Narrative — Gecko → Builder Bootstrap pivot |
| [`migration-plan.md`](migration-plan.md) | One-time V1 → workspace mapping (slated for archive — **S15-DOCS-04**) |

---

## Pending doc tickets (Sprint 15+)

Filed by 2026-05-01 audit:

- **S15-DOCS-01** — refresh `test-plan.md` header to S2-S14 + reconcile eval gate
- **S15-DOCS-02** — fix `demo/quickstart.md` verdict words to KILL/REFINE/BUILD
- **S15-DOCS-03** — add `LICENSE` (Apache-2.0 default per Sprint 9 carry-over)
- **S15-DOCS-04** — move `migration-plan.md` to `docs/archive/`
- **S15-DOCS-05** — fill `<owner>` GitHub URLs once org name is decided
- **S16-DOCS-01** — README earns "profile-typed orchestration" sub-fold only after `min(profile_types_cited) >= 3` over 7 days
- **S17-DOCS-01** — README headline graduates from "budget approver above x402" to "discrimination layer / trust layer of agentic economy" only after 4-rail proof closes
