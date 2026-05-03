# Authority-First: The Public Calibration Record Is the Moat

**Date:** 2026-05-03
**Author:** ernani (via staff-engineer dispatch)
**Status:** DRAFT
**Supersedes:** prior "network of named human judges" framing as the foundational moat (see `docs/strategy/program-judges-wedge.md`, which is reframed below as a V2 premium accelerator).

---

## 1. TL;DR

The moat is not the model, the debate engine, or the roster of named judges. The moat is the public calibration record: every Gecko verdict carries a hash and dated falsifiers, and in 90 days anyone can query whether Gecko was right. Anthropic can ship a Claude Verdict feature next month; they cannot ship 12 months of calibrated public outcomes. History compounds, and history cannot be cloned.

## 2. What changed and why

Prior framing positioned a network of named human judges (`program-judges-wedge.md`) as the foundational wedge. That framing fails an order-of-operations test ernani surfaced directly:

- He can convince Brazilian judges. He cannot convince global judges.
- Judges will not opt in until the product is credible.
- The product is not credible until judges are on it.

That is a deadlock. The only way out is authority earned via track record — a calibration history that does not require any third party's permission to start accumulating. Once the record exists and is public, judges have a reason to attach their name to it. The network becomes a premium accelerator on top of an already-credible asset, not the precondition for credibility.

The corrected thesis, stated without softening:

> The moat is the public calibration record. Every verdict has a hash and dated falsifiers; in 90 days, anyone can query "did Gecko get this right." Anthropic can ship a Claude Verdict feature next month — they can ship the model, they cannot ship 12 months of calibrated public outcomes. History is the only moat that compounds and can't be cloned. It requires being willing to be publicly wrong, on the record.

## 3. The trinity

Three layers, each a precondition for the next. Build in this order.

### Layer 1 — Public calibration record (foundation)

`verdict_hash` plus dated falsifiers plus a public outcome stitching pipeline. Buildable solo, no third-party permission required, starts compounding from day one. Every verdict shipped without this layer is a verdict whose value evaporates.

### Layer 2 — Settlement primitive

Disputable verdicts as financial assets. Anyone can stake against a verdict; if a falsifier triggers, the staker is paid. This is fintech infra Anthropic structurally will not ship — model labs do not run dispute markets. This layer turns the calibration record from a credibility asset into a tradeable one.

### Layer 3 — Named judge layer (V2+ premium)

Bolted onto a credible record. Adds regional distribution (Superteam Brasil first) and brand. Judges sign because the record is already worth signing. This is where `program-judges-wedge.md` lives — not as the foundation but as the accelerator.

The ordering is non-negotiable: settlement without calibration is a casino; judges without calibration is a panel of strangers; calibration alone is already a defensible product.

## 4. What dies vs. what survives

**Dies:**

- "Just another Claude skill / wrapper." Anthropic shipped a vulnerability scanner this week. Claude Design shipped weeks ago. Wrappers are extinction-bait — every capability we lean on as our differentiator becomes a first-party Anthropic feature within a quarter.
- "Network of named judges = moat" as the foundation. It is a premium accelerator. It cannot exist before the record exists.
- "Multi-voice debate is the moat." Debate is the engine. The engine is not the product. The product is the public history of what the engine got right and wrong.

**Survives:**

- Public, hash-anchored history of calibrated predictions with dated falsifiers.
- A settlement layer that turns those predictions into stakeable claims.
- Named judges, when they arrive, attached to a record that already has weight.

The user-facing canonical sentence does not change yet:

> Gecko gives crypto builders a deep, multi-voice verdict on their idea — with the dissent and falsifiers attached — so they know what to do next. Complementary to frames.ag (settlement) and Bazaar (marketplace).

What changes is the internal thesis. Replace every internal mention of "network of judges = moat" with "public calibration record = moat; judges = premium accelerator, V2+."

## 5. Build sequence

**V1 (today):** verdict synthesis, falsifiers, hash anchoring, paywalled detail. Already shipping. The piece missing for V1 to count as moat-building is that falsifiers must be dated and queryable post hoc — confirm S20 covers this.

**V1.5 (calibration plumbing):**

- `bb verdict-status <hash>` — query past verdict outcome. Founder self-reports, signed with wallet. Cheap to build; produces the first usable calibration signal.
- `app.geckovision.tech/calibration` — public stats page. REFINE-ship rate, KILL-pivot rate, falsifier-trigger rate. Updates as verdicts age. This page is the moat made legible.

**V2 (settlement plus judges):**

- Outcome stitching — automatic signal from GitHub commits, hackathon submissions, on-chain activity. Removes founder self-report bias.
- Disputable verdicts — stake against a verdict; falsifier trigger pays staker. Settlement primitive.

**V2.5+ (regional rollout, dispute markets):**

- Premium named judges, BR-first, design partner is Superteam Brasil. `program-judges-wedge.md` reactivates here.
- Deeper dispute market shape (prediction-market vs single-stake — see open questions).

## 6. Cross-doc consequences

Edits to propose in a follow-up pass. Do not make them now.

- `docs/strategy/program-judges-wedge.md`
  - Add a banner at the top: "Superseded as foundational moat by `2026-05-03-authority-first-calibration-moat.md`. Judges are V2 premium ON TOP OF the calibration record, not the wedge itself."
  - Reframe Section 1: judges are the premium tier of a credibility asset whose foundation is calibration history.
- `docs/PRD.md`
  - Add `app.geckovision.tech/calibration` as a V1.5 deliverable.
  - Add `bb verdict-status <hash>` as a V1.5 CLI surface.
  - Add a moat section that names public calibration as the foundational defensibility claim.
- `docs/icp.md`
  - In the Caio willingness-to-pay section, add: "Gecko publishes its calibration record; you can verify the verdict is calibrated before paying $2.50." Willingness to pay is downstream of demonstrated calibration, not of debate quality alone.
- `CLAUDE.md` Pattern D entry
  - Already aligned. Reinforce by adding: "Moat candidates that pass the test: public calibration record, settlement primitive. Moat candidates that fail: orchestration quality, judge roster as foundation."

## 7. Open questions

Three real unknowns. Resolve before V1.5 lands.

1. **Outcome stitching in V1.5.** Founder self-report is cheap but biased. GitHub or on-chain stitching is unbiased but lagging and noisy. The V1.5 answer is probably "self-report signed with wallet, marked as such, with stitched signal layered in V2." Confirm with `data-engineer`.

2. **Dispute primitive shape.** Stake-against-verdict is simpler — binary, falsifier-triggered, single counterparty. Prediction-market shape is richer — continuous price, liquidity provision, but heavier infra and regulatory exposure. Default to single-stake for V2; revisit prediction-market for V2.5+. `web3-engineer` to weigh in.

3. **Bootstrap before 90-day backlog.** The thesis claims compounding history; on day one there is no history. Mitigations: (a) backfill verdicts on already-shipped public crypto projects (no payment, illustrative only) to seed the calibration page; (b) lead with falsifiers explicit per verdict so the calibration claim is testable from day one even before outcomes accrue; (c) be explicit on the calibration page about cohort age — "this verdict is 14 days old, falsifier window 76 days remaining" turns a weakness into transparency.

A subtler open question worth flagging: is settlement actually orderable before calibration? An argument exists that a small settlement primitive (stake against any single verdict) is what *makes* the calibration record matter to outsiders, and so should ship alongside, not after. The brief orders calibration first; I agree, because settlement on an unproven record is a market with no signal. But if V1.5 calibration plumbing slips, a minimal stake primitive is the better fallback than nothing.

## 8. Status

DRAFT. Author: ernani via staff-engineer dispatch. Date: 2026-05-03. Supersedes prior network-as-moat framing in `docs/strategy/program-judges-wedge.md` as the foundational defensibility claim. Judges remain a real V2+ premium layer, not the wedge.
