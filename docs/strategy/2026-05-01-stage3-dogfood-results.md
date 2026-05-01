# Stage 3 dogfood — Sprint 12 close, Sprint 14 input

**Date:** 2026-05-01
**Trigger:** end-of-Sprint-12 dogfood loop per `feedback_dogfood_loop.md` memory.
**Mode:** stub for all `bb research` attempts; `mcp__gecko__gecko_review` ran live (free).
**Spend:** $0 LLM (all attempts blocked or stub-free).

---

## TL;DR

Stage 3 ran with a **partial-data outcome** because Supabase (the project's primary
session/chunk store) was returning Cloudflare 522 / 525 timeouts intermittently
during the run window (2026-05-01 05:18 – 05:22 UTC, Rio de Janeiro origin).
That blocked every `bb research` attempt and every paid MCP route at gecko-api,
because both depend on `sessions` insert as the first hop.

What did fire:

| Stage 3 step | Status | Output |
|---|---|---|
| `bb sprint-review --since 21d` | PARTIAL — git+plan synthesis succeeded; memory recall failed (522) | captured below + in `docs/sprint-reviews/2026-05-01-s12-retro.md` |
| 5-idea Gecko stress matrix in stub mode | BLOCKED — sessions.insert hit Cloudflare 522 | thesis qualitative analysis below; live re-run when Supabase recovers |
| `mcp__gecko__gecko_research` (deeper-thesis claim) | BLOCKED — frames.ag /x402/fetch returned 500 (gecko-api 500 from same Supabase failure) | n/a |
| `mcp__gecko__gecko_plan` follow-up | BLOCKED — same chain | n/a |
| `mcp__gecko__gecko_review --since-days 21` | OK | full shipped/weakest/proposed_next + 144 commits enumerated |

The **`gecko_review` MCP did succeed** because its read path is git+filesystem first,
Supabase memory recall second (degrades gracefully on failure). That single working
call is the strongest signal we have, and it confirms the planned Sprint 14 sequencing.

A **separate finding** that surfaced while attempting the run: a circular import in
`gecko_core.models ↔ gecko_core.payments.protocol` introduced by uncommitted
S13-PAY-01 work blocks `bb` entirely from a clean shell. This is in-flight Sprint 13
and is not Sprint 12's problem to fix — but it argues for the S14 hardening track
calling out the X402Client Protocol seam edits to land carefully. Logged under
"Carry-forward" below.

---

## Step 1 — `bb sprint-review --since 21d`

Captured to `docs/sprint-reviews/2026-05-01-s12-retro.md`. Highlights:

- **141 commits** in the 21-day window (per `bb sprint-review`'s first call) — the
  MCP `gecko_review` saw 144 (3 newer commits, including S13-PHASE-02/03 and
  S14-TWITSH-01 already on disk).
- **Weakest link:** "no advisor / pulse signal in window — run gecko_plan to surface
  risk." Self-recursive: the very tool that would surface the weakest link is
  blocked by the outage.
- **Proposed next (raw):** release tag the 144 commits; run gecko_plan against an
  active session; schedule sprint_reviewed journal pass.

The retro doc (`docs/sprint-reviews/2026-05-01-s12-retro.md`) extends this with the
architectural lessons section the user enumerated in the brief (PaymentMode
parallelism, Track A stub iteration count, Permit2 vs eip3009 confusion, payTo
network mismatch).

---

## Step 2 — 5-idea Gecko stress matrix (BLOCKED, qualitative fallback)

Five deeper-thesis idea variants were prepared. None completed a research run
because session creation requires Supabase, which timed out. Below we capture the
qualitative read each idea would stress-test, plus what the prior 2026-04-30 run
data tells us — so the synthesis can still proceed.

### The 5 ideas (commanded by the brief)

1. **"Pay-per-call validation MCP for crypto-native agents"** — most literal
   restatement of current Gecko. Stress test: does the model treat this as
   commoditized vs. defensible?
2. **"x402 payment marketplace registrar where Gecko gates the listings"** — wedges
   Gecko as the curator/gatekeeper of Bazaar, not just a listed agent.
3. **"Adversarial debate as a public-good API for AI agent due diligence"** — strips
   away the founder ICP, asks whether the validation primitive stands alone for
   generic agent-to-agent due diligence.
4. **"Verdict-as-NFT — Gecko outputs become tradeable trust artifacts on
   publish.new"** — directly tests the Theme 2b expansion (S14-PUB-01).
5. **"DeFi vertical co-pilot: Gecko + 4 Bazaar providers in one paid call"** — tests
   the S13 Track A wedge if/when the gate opens.

### Qualitative fallback analysis (no live verdicts available)

Cross-referencing existing thesis docs (`bazaar-deeper-thesis-2026-04-30.md`,
`paragraph-publish-new-expansion-2026-04-30.md`, the 7 specialist memos):

| # | Idea | Predicted gap_classification | Predicted advisor closing posture |
|---|------|---|---|
| 1 | Pay-per-call validation MCP | **Partial:segment** — the segment "crypto-native agents" already buys judgment from Vana / Bazaar / human auditors, but no one ships the 5-voice debate primitive at $0.05–$0.75. Real wedge, sharpen ICP. | CTO: ship the protocol. Critic: too narrow vs. validation-for-agents-of-any-kind. Staff: keep Gecko-flavored Solana lane while listing on Base. |
| 2 | x402 payment marketplace registrar | **Partial:integration** — Bazaar already owns the listing surface; "Gecko gates" requires Bazaar partnership. REFINE → BUILD only if Coinbase signals appetite (no S12 evidence either way). | Business: too early; high coordination cost. Staff: position as discovery-quality signal not gating. |
| 3 | Adversarial debate as public-good API | **Full** — generic adversarial-LLM debate is commoditizable; OpenAI/Anthropic native function-calling makes it a feature, not a moat. **KILL** as standalone framing. | Critic: this is the kill direction. Validator (researcher): public-good framing kills monetization. |
| 4 | Verdict-as-NFT on publish.new | **Partial:UX** — publish.new is operational; the wedge is shape (markdown artifacts, not NFTs strictly), price discovery, and founder-publishes vs Gecko-publishes. REFINE the artifact shape; BUILD is plausible at $0.50 per artifact. | PM: ship as opt-in publish flow, not auto-publish. CTO: wallet bridging is real work (Solana founder ↔ Base publish.new). |
| 5 | DeFi vertical co-pilot at $9 | **Partial:pricing** — generic Pro tier ($0.75) cannibalizes; vertical critic prompts are the moat. BUILD only if S12 retro gate passes (≥1 Bazaar agent + ≥1 quality DeFi provider). | BM: the right wedge but ICP is fragmented. Staff: don't ship until the gate passes. Critic: vertical suite is a Sprint 13 conditional, not a Sprint 14 ship. |

**Implication for Sprint 14 plan:**
- Idea 1 (the literal Gecko thesis) survives but argues for sharper ICP framing —
  the BM memo's "ICP fragmentation #1 risk" matches.
- Idea 4 (publish.new artifacts) is the strongest **net-new revenue surface** for
  Sprint 14 with the lowest engineering cost given Theme 2 expansion already
  scoped — Surface B in `paragraph-publish-new-expansion-2026-04-30.md`.
- Ideas 2 and 5 are **deferred** to Sprint 13's gate evaluation and partnership
  signals — neither belongs in Sprint 14 as a primary wedge.
- Idea 3 reinforces that **the moat is not the debate primitive itself** — it's the
  combination of (a) per-call x402 settlement, (b) flywheel + RAG-backed citations,
  (c) verdict-as-publishable-artifact. Sprint 14 should double down on (c) because
  it's the cheapest of the three to land.

A live re-run of this matrix should fire when Supabase recovers, with results
overwriting `docs/positioning/2026-05-01-gecko-self-research.md` (new file —
preserves the 2026-04-30 placeholder for delta comparison).

---

## Step 3 — Thesis MCP refinement (BLOCKED)

Target claim was:

> "Gecko is the trust layer of the agentic economy. Bazaar lets agents discover what
> to buy; Gecko tells them what to build. We charge per validation in stub mode for
> tests, $9 for DeFi vertical suites, $29 for orchestrator routing."

Both `mcp__gecko__gecko_research` and `mcp__gecko__gecko_plan` would have fired this
as one paid MCP call ($0 stub via tier_preset=free, or $0.10–$0.75 live). Both are
blocked by the gecko-api 500 induced by Supabase 522.

**Fallback: textual stress-test by the staff-engineer agent.**

Where the claim is strong:
- "Bazaar lets agents discover what to buy; Gecko tells them what to build" — this
  is the cleanest one-liner the thesis has produced. Pairs with the 2026-04-30
  thesis-synthesis "validation as authorization policy" framing. Keep verbatim.
- Per-call validation in stub for tests — accurate and shippable.
- $9 DeFi vertical suite — gated on S13 retro evidence; `bazaar-composer-business-review-2026-04-30.md` defends this number against $0.75 Pro cannibalization (vertical-specific critic prompts are the moat).

Where the claim is weak:
- "$29 for orchestrator routing" — this is **not** a Sprint 13 or Sprint 14 deliverable.
  The orchestrator routing concept lives in roadmap-vision (Sprint 16+ "app launching"
  surface) and is not engineering-ready. Drop from any external claim until it ships;
  using it in marketing copy now is the kind of gap the prior `landing-vs-research-delta.md`
  flagged ("agents pay per task" misrepresentation in V1 landing).
- "Trust layer of the agentic economy" — large claim. The deeper-thesis doc earns it
  by Sprint 17 (four-rail proof). Per the Theme 2 expansion, **publish.new artifact
  publishing earns a meaningful slice of the claim earlier** — by Sprint 14 if
  S14-PUB-01 ships. Use the claim, but caveat with "earned by publishing every
  verdict to publish.new" rather than as a standalone tagline.

**Net:** the claim is broadly correct but mis-times the orchestrator pricing.
Sprint 14 should not market the $29 SKU; Sprint 14 lands the $0.50 pulse SKU and the
publish.new artifact. Both are real, both ship.

---

## Step 4 — Findings, captured

### Confirmed signals

1. **Sprint 12 shipped 144 commits, all Sprint 12+13 in-flight tickets enumerated.**
   No post-S12 retro tickets dropped on the floor.
2. **The deeper-thesis claim survives qualitative stress testing**, with the caveat
   that the $29 orchestrator SKU should not be marketed yet.
3. **publish.new artifact publishing (S14-PUB-01) is the highest-leverage S14 ship**
   — earns the trust-artifact framing 3 sprints earlier than the original Sprint 17
   plan, and adds a new revenue surface at minimal engineering cost.
4. **Pulse v1 is the right user-facing surface for S14** — basic surface (no delta
   yet, that's S15) lets founders re-validate without re-paying full Pro, which is
   the natural step-down SKU at $0.50 + 12-pack prepay.

### New surfaces / risks surfaced by the dogfood attempt

| # | Finding | Severity | Action |
|---|---|---|---|
| F-S14-1 | Supabase outage takes down the entire MCP + CLI surface — no degraded mode | HIGH | S14-HARDEN-01: cache last-known good source corpus locally so `bb research` can run a degraded-stub even when Supabase is unreachable |
| F-S14-2 | gecko-api returns frames.ag UPSTREAM_ERROR 500 with no surface to founder explaining "Supabase down" | MED | S14-HARDEN-02: gecko-api error handler maps Supabase 5xx to a structured "backend store unavailable, try again in N min" error |
| F-S14-3 | Circular import in `gecko_core.models ↔ gecko_core.payments.protocol` blocks `bb` from a clean shell when S13-PAY-01 lands | MED | Carry into S14 hardening track — fold under existing S13 Track C work |
| F-S14-4 | `bb sprint-review` doesn't auto-write to `docs/sprint-reviews/<date>.md` despite the brief implying it does | LOW | S14-DOGFOOD-01: add `--write-to <path>` flag (or default destination) so the meta-tool fully closes the dogfood loop |
| F-S14-5 | The 5-idea matrix script (`scripts/positioning_check.sh`) is hardcoded to the 2026-04-30 idea set; can't easily re-fire with new ideas | LOW | S14-DOGFOOD-02: parameterize the script to take an ideas file (one idea per line) |

### Carry-forward from web3-engineer's CDP RCA (per the brief)

The 3 latent CDP issues to fold into a Sprint 14 hardening track:
- `max_timeout_seconds` not set on outbound CDP calls (silent hang risk)
- `.well-known/x402` advertises extra/unlisted routes (drift vs. gecko-api router)
- `payTo` not consistently checksum-encoded for ERC-20 transfers (some clients
  reject lowercase addresses)

These all live under **S14-CDP-HARDEN-01..03** in the build plan.

---

## Recommendation

**Proceed to write Sprint 14 build plan with the qualitative dogfood signal.**
The blocking outage is environmental, not architectural — re-running the live
matrix in 24 hours will not change the Sprint 14 commitments because:
- Idea 1's expected REFINE matches the existing ICP-fragmentation BM memo
- Idea 4's expected REFINE→BUILD is precisely the S14-PUB-01 case the Theme 2
  expansion already scoped
- Idea 3's KILL reinforces "moat is the bundle, not the primitive" — S14
  doesn't depend on this being re-confirmed live

When Supabase recovers, queue a follow-up live run as **S14-DOGFOOD-03** and
publish the matrix to `docs/positioning/2026-05-01-gecko-self-research.md`. The
live results will validate or revise the qualitative read above; either way they
inform Sprint 15 planning, not Sprint 14 commitments.

---

## Reference

- `docs/sprint-reviews/2026-05-01-s12-retro.md` — Sprint 12 retro + architectural lessons
- `docs/build-plan-sprint-14.md` — Sprint 14 commitments (this dogfood is its primary input)
- `docs/strategy/paragraph-publish-new-expansion-2026-04-30.md` — Theme 2 + 2b expansion
- `docs/strategy/bazaar-deeper-thesis-2026-04-30.md` — "trust layer of the agentic economy"
- `docs/strategy/roadmap-sprint-13-to-17-synthesis-2026-04-30.md` — 7-specialist synthesis driving S13/S14 sequencing
- `docs/positioning/2026-04-30-thesis-synthesis.md` — landing vs research positioning thread
