# Pitch Documentation Strategy
*From: product-designer*
*To: Ernani*
*Re: end-to-end documentation plan for the Colosseum submission, reconciling the new "oracle-first campaign escrow" thesis with the prior Builder Bootstrap artifacts*

---

## 0. The repositioning, named

There is a real product-positioning fork in this repo and the submission cannot ride both rails. Let me state it plainly so we stop pretending the artifacts are coherent:

- **Product A — Builder Bootstrap.** An AI agent that pays (via x402 on Solana) to research and validate a founder's idea, returning a Business Plan / Validation Report / PRD. This is what `gecko-core`, `gecko-api`, `apps/cli`, and the existing pitch artifacts (`01` through `05`) describe. The demo moment is "402 → on-chain payment → documents render."
- **Product B — Gecko Protocol.** An Anchor program on Solana that escrows brand-creator campaign budgets, releases a 10% advance on launch, gates milestone tranches behind oracle scores, and enforces a cliff. This is what the revised 12-slide narrative and the new Figma deck describe. The demo moment is "vault deposit → advance release → oracle update unlocks tranche → cliff returns unused funds."

These share a name and a wallet. They do not share a product, an ICP, a moat, or a demo. The slide that says "oracle-first campaign escrow" is incompatible with the slide that says "an AI agent just paid for its founder to find out if their idea is real." A judge cannot watch both videos and conclude there is one company here.

### Recommendation: **Product B (Gecko Protocol) becomes canonical for the Colosseum submission.**

Three reasons, recommendation-first:

1. **The thesis is sharper.** "Enforceability, not transparency" is a defensible, one-sentence wedge. "Agents buying validation for founders" is a demo, not a thesis — and Colosseum judges have seen ten variants of agent-buys-thing-via-x402 by now.
2. **The on-chain surface is real and load-bearing.** Product B *requires* an Anchor program with vault state, allocation logic, and a cliff. That is unambiguously Solana-native. Product A's on-chain surface is a single USDC transfer that any chain could host; the rest is an LLM pipeline.
3. **The moat is encoded in the program, not in prompts.** The prior consultation flagged that Product A's moat depended on "two days of prompt engineering" producing output measurably better than ChatGPT. That is a fragile bet for a hackathon panel. Product B's moat — vault lifecycle + oracle-gated release + cliff enforcement — is code that exists or doesn't.

### What this means for existing artifacts

| Existing artifact | Disposition under Product B canon |
|---|---|
| `00-design-consultation.md` | Keep as historical record. Do not edit. The structural advice (cold open, reveal-first, no jargon-decoration, founder-narrator) ports cleanly to Product B; the *content* of the demo moment changes. |
| `01-pitch-script.md` | **Supersede.** Rewrite end-to-end against the campaign escrow demo. The 15-second cold open changes from "402 → docs render" to "brand deposits USDC → set-live triggers 10% advance to creator wallet → Solana Explorer confirms." |
| `02-cold-open-storyboard.md` | **Supersede.** New storyboard below in §4. |
| `03-one-pager.md` | **Merge into business plan (§1).** The one-pager becomes the executive summary of the business plan, not a separate artifact. |
| `04-qa-prep.md` | **Revise, don't rewrite.** ~60% of questions transfer (team, GTM, why-Solana, why-now). Replace the prompt-quality and "is this just ChatGPT" questions with oracle-credibility and program-audit questions. |
| `05-backup-slides-spec.md` | **Retire.** The 12-slide revised narrative *is* the backup deck. Don't maintain two. |
| `Builder Bootstrap Deck.html` | **Archive.** Move to `gecko_pitch/Gecko - pitch/archive/` with a README noting it reflects the prior positioning. Do not delete — it is useful provenance if a judge asks "what changed." |
| `Gecko Pitch Deck.html` + `components/*.jsx` | **Promote to canonical.** This is the deck that ships. |
| `gecko-core` Builder Bootstrap code | **Out of scope for the pitch.** Don't show it, don't reference it. It can continue to exist in the repo as a parallel surface for `bb research`, but the pitch and the docs treat Gecko Protocol as the product. If you want, frame Builder Bootstrap internally as "the dogfood tool the team built while shaping the thesis" — but that line does not belong in the pitch. |

If the user disagrees and wants both products represented, the answer is *two separate submissions* or *one submission that explicitly bills Builder Bootstrap as a research tool used to validate Gecko Protocol's thesis*. Do not try to fuse them into a single 3-minute narrative.

---

## 1. Business plan

**What it is.** A 6–10 page document that a non-technical investor or accelerator partner can read in 15 minutes and walk away knowing what Gecko Protocol does, who pays for it, and why now.

**Audience.** Colosseum judges doing diligence after the video; accelerator scouts; the "leave-behind" reader who liked the pitch and wants depth.

**What goes in.**
- One-paragraph summary (the supersede of `03-one-pager.md`)
- Problem: enforcement gap in creator marketing, sized in dollars not adjectives
- Thesis: enforceability vs transparency, stated as a falsifiable claim
- Product: the 5 enforceable operations (deposit / setup / launch / milestone / close), each with the on-chain mechanism named
- ICP: DeFi protocols, gaming/esports orgs, creator-aggregator platforms — with one named design partner per row, even if early
- Business model: yield fee, launch/advance fee, partner API plans, with assumed take-rates and a single-page unit economics table
- GTM: protocol-first via partners → direct campaigns → inbound, with a 90-day milestone plan
- Competitive landscape: name 3 incumbents (manual escrow / influencer marketplaces / payout tools) and the row each one fails on
- Team: Ernani + Leticia, with specific proof of execution (links to deployed program, dashboard, repo)
- Risks: enforceability theater (oracle quality), regulatory surface on escrow, two-sided cold start

**What stays out.**
- Tokenomics. There is no token. Don't invent one.
- Five-year revenue projections. Single 12-month plan with explicit assumptions, then stop.
- Architecture diagrams. Those go in the PRD.
- Anything about Builder Bootstrap, AutoGen, or x402-as-headline. The business plan is about the protocol, not about the toolchain that built the thesis.

**Format and location.** Markdown at `docs/business-plan.md`, exported to PDF for submission. ~6 pages. Numbered sections, no marketing copy, no decoration.

**Supersedes.** `03-one-pager.md` (folded in as §1 executive summary).

---

## 2. PRD

**What it is.** The product requirements doc for Gecko Protocol's V1 (devnet → mainnet pilot). It defines what ships, what doesn't, and what acceptance looks like.

**Audience.** Engineering (you, future contributors), and judges who want to verify that the pitch's claims map to scoped work.

**What goes in.**
- V1 scope: vault lifecycle on devnet, single-creator and multi-creator campaigns, 10% advance on launch, oracle-gated tranche release, cliff close
- V2 scope: mainnet, partner SDK, dashboard polish, first paying pilot
- V3 scope: deferred — multi-oracle aggregation, dispute window, secondary-market resale of vault positions
- Acceptance criteria per scope item, written as on-chain assertions ("after `set_live`, vault balance decreases by exactly 10%, creator ATA increases by exactly 10% minus fee")
- Non-functional: program size budget, compute-unit ceilings per instruction, RPC fallback, oracle update SLO
- Success metrics: # of campaigns deposited, $ locked, # of milestone releases triggered, % of cliffs that returned funds (this last one is the enforceability proof point)
- Out-of-scope, named: KYC, fiat on-ramp, creator discovery, content moderation

**What stays OUT, given `docs/PRD.md` already exists.**
- Anything about Builder Bootstrap document generation, AutoGen, citation rendering, or the three-document reveal. The existing `docs/PRD.md` describes Product A. Either:
  - **Option 1 (recommended):** Rename existing `docs/PRD.md` to `docs/PRD-builder-bootstrap.md` and write a new `docs/PRD-gecko-protocol.md`. Two PRDs, both honest about which product they describe. Update the README index.
  - **Option 2:** Replace `docs/PRD.md` entirely with the Gecko Protocol PRD and archive the old one in `docs/archive/`. Simpler, but loses the Builder Bootstrap PRD context if you keep `bb research` working.
- Roadmap fluff. The roadmap is the three rows in §10 of the revised deck. Don't expand it into a 30-row Gantt.
- Anything that's actually a business plan concern (pricing, ICP, GTM). PRD is what ships, not why it sells.

**Format and location.** Markdown at `docs/PRD-gecko-protocol.md` (assuming Option 1). ~8 pages. Acceptance criteria as code-block assertions, not prose.

**Supersedes.** Nothing directly — it sits beside the existing `docs/PRD.md` and either coexists or replaces it depending on Option 1 vs 2.

---

## 3. Thesis validation

**What it is.** The evidence file that backs the headline claim "enforceability, not transparency." Without this, slide 2 of the deck is an assertion and the whole pitch is vibes.

**Audience.** The skeptical judge who reads the deck, agrees the framing is sharp, and then asks "prove it."

**What goes in.** Three layers of evidence, in this order:

1. **Market evidence — that the pain is real.**
   - 10–15 cited interviews / public posts / Reddit threads / Twitter cases of brand-creator deals breaking at the moment of commitment. Each one labeled with the failure mode (delayed payment, scope creep, ghosted brand, ghosted creator).
   - 2–3 industry reports with $ figures on creator marketing spend and dispute rates. Cite the source URL inline.
   - One named pattern per ICP: what specifically breaks for DeFi protocols vs gaming orgs vs aggregator platforms.

2. **Mechanism evidence — that enforceability changes outcomes.**
   - Side-by-side comparison: same campaign run as a PDF contract vs run on Gecko. What can each party do at hour 0, day 7, day 30? This is the table that makes "enforceability" concrete.
   - One worked example with real numbers: $50K campaign, 5 creators, milestone schedule, what happens onchain at each step including the failure cases (creator ghosts, brand cancels, oracle disputes).

3. **On-chain evidence — that the mechanism exists, not just the claim.**
   - Devnet program ID with link to explorer
   - Transaction signatures for: a deposit, a set-live triggering a 10% advance, an oracle update unlocking a tranche, a cliff close returning unused funds
   - Dashboard URL showing a live campaign in progress
   - Repo link to the Anchor program with the specific instruction handlers named

The third layer is the load-bearing one. If the program does not actually do what slide 4 claims, the thesis cannot be validated and the rest of the document is performance. **Build the on-chain demo before writing the thesis validation doc.** Don't write claims you cannot link to a transaction.

**What stays out.**
- TAM math dressed up as validation. Market size is a business plan concern.
- Quotes from advisors. Use end-user pain, not authority signals.
- "Web3 is the future" framing. The thesis is about enforceability as a category, not about blockchain as a category.

**Format and location.** Markdown at `docs/thesis-validation.md`. ~5–7 pages. Heavy on links and transaction signatures, light on prose.

**Supersedes.** Nothing. This artifact does not currently exist and is the single biggest gap in the submission package.

---

## 4. Video pitch (3 min)

**What it is.** The recorded artifact judges actually watch. Same structural principles as the prior consultation: cold open with the reveal, problem second, solution third, why-now and team to close. The *content* of the demo moment changes from document rendering to vault enforcement.

**Audience.** Tired judge, 47th video of the night, 15 seconds to decide whether to keep watching.

**Structure (revised for Product B).**

```
[0:00 – 0:15]  COLD OPEN
                Split screen. Left: a "set live" button being clicked
                in the Gecko dashboard. Right: Solana Explorer.
                The vault balance ticks down 10%. The creator wallet
                ticks up. Confirmation in 2 seconds.
                Caption: "A brand just paid a creator before the
                campaign even started. The code released the money,
                not a person."
                No logo, no name, no problem statement yet.

[0:15 – 0:45]  THE PROBLEM
                Founder on camera. Plain language.
                "Creator marketing runs on emails, PDFs, and trust.
                Brands stall. Creators ghost. Most contracts are too
                small to enforce legally. Both sides take risk that
                no one is paid to absorb."
                B-roll: a Discord screenshot of a creator chasing
                payment, a brand-side spreadsheet of late campaigns.

[0:45 – 1:30]  THE SOLUTION
                Demo proper. Show the 5 operations as the dashboard
                walks them: deposit, creator setup, launch (advance
                fires), milestone (oracle update releases tranche),
                close (cliff returns unused funds).
                Each operation shows a real Solana tx signature.
                One sentence under each: "the program did this, not
                a human."

[1:30 – 2:15]  WHY SOLANA, WHY NOW
                Fast settlement, low fees, programmatic accounts,
                oracle-compatible automation — but stated in
                product terms, not protocol terms.
                "This only works if releases feel instant and cost
                nothing. Solana is the only chain where this is a
                product, not a science project."
                Flag the moat: the program enforces the cliff. No
                competitor has the cliff, because no competitor has
                a program.

[2:15 – 2:45]  TEAM + ASK
                Ernani + Leticia, 10 seconds each, with one specific
                proof of execution per person.
                Ask: accelerator slot, pilot partners in DeFi /
                gaming, not vague "support."

[2:45 – 3:00]  END CARD
                Domain. Devnet program ID. Repo. One QR.
```

**What goes in.** Real on-chain transactions. Real dashboard. Founder face on camera for problem and team segments. Voice-over for demo segments.

**What stays out.**
- The word "x402." It is not part of this product anymore.
- AutoGen, GroupChat, RAG, embeddings, citations. None of that is Product B.
- Architecture diagrams. They belong in the technical walkthrough, not the pitch.
- Tokenomics. There is no token.
- The phrase "AI agent." Gecko Protocol does not have AI agents in its critical path. The oracle is not an agent in the LLM sense.

**Format and location.** MP4, 1080p, 3:00 hard cap. Source script at `gecko_pitch/Gecko - pitch/uploads/01-pitch-script.md` (rewritten). Storyboard at `02-cold-open-storyboard.md` (rewritten).

**Supersedes.** `01-pitch-script.md` and `02-cold-open-storyboard.md` in their current Builder Bootstrap form.

---

## 5. Pitch deck (12 slides)

**What it is.** The slide artifact for live screen-share moments and as a leave-behind PDF. The revised 12-slide narrative is the source of truth.

**Audience.** Panel reviewers in conversation, scouts who skim the deck instead of watching the video, the judge who wants to send slide 2 to a colleague.

**What goes in.** The 12 slides as written in `Gecko - Revised Deck Narrative.md`. Don't expand them. Each slide is one idea, one table, one closing line. The narrative is already tight.

**What stays out.**
- Appendix slides. If a panelist asks for depth, they get the business plan or the thesis validation doc, not slide 13–25.
- A "thank you" slide. The closing slide *is* the thank-you.
- Speaker notes longer than the slide. If the slide needs explanation, the slide is wrong.

**Format and location.**
- Live presentation: the existing `Gecko Pitch Deck.html` rendered from `components/*.jsx`. Keep this as the canonical interactive version.
- Leave-behind: PDF export of the same 12 slides. Stored at `gecko_pitch/Gecko - pitch/exports/gecko-deck.pdf`.
- Source of truth for content: `Gecko - Revised Deck Narrative.md`. Any change to the deck changes the markdown first, then the JSX.

**Supersedes.** `Builder Bootstrap Deck.html`, `05-backup-slides-spec.md`.

---

## 6. Production order

Build in this order. Each artifact depends on the one above.

1. **On-chain demo works end-to-end on devnet.** Vault deposit, advance on set-live, oracle-gated tranche, cliff close. Real transaction signatures captured. *No documentation can claim what the program does not do.*
2. **Thesis validation doc.** Written against the working demo. This is the file that forces honesty about what is real vs aspirational. If a claim cannot be cited to a transaction or an interview, it gets cut here, not later.
3. **PRD (Gecko Protocol).** Scoped against what the demo proves and what V2 needs to add. Acceptance criteria as on-chain assertions.
4. **Business plan.** Synthesizes thesis validation + PRD into the investor-readable artifact. The exec summary becomes the leave-behind.
5. **Deck refinement.** The 12-slide narrative is already there; this pass aligns slide 7 ("the product is already legible as a protocol") with the actual demo evidence from step 1.
6. **Pitch script + storyboard rewrite.** Now that the demo is real and the thesis is validated, the script writes itself in 2–3 hours.
7. **Record video.** Cold open first, multiple takes, then founder segments, then voice-over.
8. **Q&A prep revision.** Last, because the questions you'll get are determined by what's on the deck and in the video.

The order matters because writing 4 before 1 produces fiction, and recording 7 before 5 produces a video that contradicts the slide deck a panelist will pull up mid-conversation.

---

## 7. The 2–3 biggest risks with the new narrative

### Risk 1: "Oracle-first" implies an oracle that exists.

Slide 4 says "oracle score updates unlock tranche releases." Slide 7 lists "oracle score pipeline" as a built artifact. If the oracle is a single signer wallet that you control and call manually, the word "oracle" is doing too much work and an informed judge will catch it in 30 seconds. Two acceptable responses:

- **Honest framing:** "The oracle interface is defined; the V1 oracle is operator-signed; V2 integrates a third-party score provider." Put this in the PRD and the thesis validation doc. Don't put it in the deck — but don't contradict it either.
- **Ship a real oracle integration before submission.** Even a thin one — a Switchboard or Pyth-style attestation feed for one metric — earns the slide.

If neither happens, change the slide language from "oracle-first" to "rules-based campaign escrow with a programmable score input." Less catchy, more defensible.

### Risk 2: "Enforceability" claims need an actual on-chain cliff demo.

The cliff is the proof point. If you say "after the cliff, the vault closes and unused funds return" and your demo doesn't show that transaction, the thesis is unfalsified and unproved. The cliff close is harder to demo than the advance because it requires time to pass — solve this with a configurable cliff duration (60 seconds for the demo recording) and capture the close transaction explicitly. This goes in the cold open or in the [0:45-1:30] solution segment, not in a footnote.

### Risk 3: The repositioning leaves a trail of contradictions in the repo.

The repo today still says `gecko-core` is for ingestion, embeddings, and AutoGen orchestration. The pitch says Gecko is an Anchor program. A judge who clicks through to the repo from the video will see Python, not Rust/Anchor. Two responses:

- **Minimum:** Add a top-level README section that explicitly names the two surfaces — "Gecko Protocol (Anchor program, this submission's focus)" and "Builder Bootstrap (Python research tool, internal dogfood)." Link to each. This costs an hour and saves a panel question.
- **Better:** Move the Anchor program into this monorepo (or link to its repo prominently) and make it the thing the README leads with. The Python packages get demoted to a `tools/` or `research/` subtree.

The failure mode is a judge watching a polished video about an Anchor program, opening the GitHub repo, and seeing zero Rust. That contradiction kills credibility faster than any missing feature.

---

## 8. What I need from the user before the next pass

Three confirmations, recommendation-first:

1. **Product B becomes canonical for Colosseum. Builder Bootstrap moves to `archive/` or `tools/`.** Confirm or push back.
2. **The Anchor program either exists on devnet by end of week or we soften "oracle-first" and "enforceable" language across all artifacts.** Confirm which path.
3. **Two PRDs (Option 1) or replace existing PRD (Option 2).** I recommend Option 1 — keeps history, costs nothing.

Once those are answered, the rewrite of `01` and `02`, the new `docs/thesis-validation.md`, the new `docs/PRD-gecko-protocol.md`, and the new `docs/business-plan.md` can land in 2–3 days of focused work.

---

*— product-designer*
