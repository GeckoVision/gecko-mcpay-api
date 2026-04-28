# Gecko — Revised Deck Narrative

## Cover
**Gecko Protocol**

**The brand cannot cancel. The code says so.**

**Oracle-first campaign escrow on Solana**

---

## Slide 1
**Creator marketing still breaks at the moment of commitment**

Current campaigns still run on emails, PDFs, manual approvals, and post-hoc negotiation.

| What breaks today | Why it matters |
|---|---|
| **Brands can delay, renegotiate, or disappear** | Creators carry delivery risk without guaranteed recourse |
| **Creators can underdeliver or go silent** | Brands commit budget without enforceable execution logic |
| **Most contracts are too small to enforce legally** | Trust replaces infrastructure |

**Bottom line:** creator marketing has coordination, enforcement, and payout risk on both sides.

---

## Slide 2
**This is not a transparency problem**

**It is an enforceability problem.**

| Most tools do this | Gecko thesis |
|---|---|
| Show status in a dashboard | **Lock commitment in code** |
| Add a middleman | **Enforce release logic onchain** |
| Track payment manually | **Tie payout to predefined conditions** |
| Rely on policy and support teams | **Rely on program rules and timestamps** |

> Transparency only shows that something went wrong. Enforceability changes what can happen.

---

## Slide 3
**A campaign should behave like code, not a promise**

Gecko reframes a sponsorship as a programmable agreement with explicit rules from day one.

| Requirement evidenced by the market | Why it matters |
|---|---|
| **Commitment must be visible upfront** | Creators need to know funds are real before prioritizing work |
| **Release conditions must be explicit** | Both sides need less ambiguity during execution |
| **Early exit must have consequences** | Otherwise commitment is not credible |
| **Progress must be inspectable** | Brands need proof without endless coordination |

---

## Slide 4
**Gecko turns a campaign into 5 enforceable operations**

| Step | What happens onchain |
|---|---|
| **1. Deposit** | Brand locks USDC into a campaign vault |
| **2. Creator setup** | Creators are added with fixed allocation weights |
| **3. Launch** | A 10% advance is released automatically on set-live |
| **4. Milestone logic** | Oracle score updates unlock tranche releases |
| **5. Close** | After the cliff, the vault closes and unused funds return |

**Key mechanism:** the program, not a human, governs release, timing, and exit logic.

---

## Slide 5
**Under the hood, the product is simple and technical**

| Layer | Role |
|---|---|
| **Anchor program** | Vault lifecycle, creator allocations, milestone logic, cliff enforcement |
| **API / webhook layer** | Transaction building, oracle updates, partner event delivery |
| **SDK + app** | Campaign creation, vault inspection, partner embedding, sponsor/creator dashboards |

**Why this matters:** Gecko can work both as a direct app and as infrastructure embedded into existing creator platforms.

---

## Slide 6
**Why this is credible on Solana**

| Solana primitive | Why Gecko depends on it |
|---|---|
| **Fast settlement** | Payout actions and campaign state changes need to feel immediate |
| **Low fees** | Frequent updates and releases only work if operations stay cheap |
| **Programmatic accounts** | Vaults, creator allocations, and milestone state must live onchain |
| **Oracle-compatible automation** | Milestone-based release needs machine-readable score updates |

**This is not “payments on blockchain.”**

**It is a rules-based campaign primitive that needs fast, cheap, programmable execution.**

---

## Slide 7
**The product is already legible as a protocol**

| Live or built | What it proves |
|---|---|
| **Vault lifecycle on devnet** | Campaign logic is already operational |
| **10% advance on launch** | Commitment can become automatic, not manual |
| **Creator allocation logic** | Multi-creator campaigns can be structured onchain |
| **Oracle score pipeline** | Milestone release can be tied to external updates |
| **Dashboard + SDK** | The protocol is usable, not just conceptual |

**Narrative point:** this is no longer only a thesis. It is already becoming a working system.

---

## Slide 8
**Go-to-market starts where enforcement pain is already expensive**

| Initial ICP | Why they matter first |
|---|---|
| **DeFi protocols** | Crypto-native teams already understand onchain capital and performance incentives |
| **Gaming / esports organizations** | They run campaign-like creator programs with measurable outcomes |
| **Platforms that already aggregate creators** | Embedding is faster than building distribution from zero |

**Approach:** protocol-first distribution through partners, then direct campaigns, then broader inbound.

---

## Slide 9
**Monetization follows locked capital and campaign activity**

| Revenue stream | Logic |
|---|---|
| **Yield fee** | Gecko captures a small fee on routed yield |
| **Launch / advance fee** | Gecko charges when campaigns go live and creators are activated |
| **Partner API plans** | Platforms pay for webhook, score, and infrastructure access |

**Important:** the business model scales with campaign volume and locked capital, not with manual service work.

---

## Slide 10
**Roadmap is narrow by design**

| Phase | Focus |
|---|---|
| **Now** | Devnet vault lifecycle, creator setup, advance logic, milestone release |
| **Next** | Harden oracle flow, improve dashboard legibility, tighten partner workflow |
| **Then** | Mainnet deployment, first live pilot, selective integrations |

**What we are deliberately not doing now:** expanding scope before the core primitive is proven.

---

## Slide 11
**This team can ship the primitive**

| Founder | Role |
|---|---|
| **Ernani Britto** | Engineering and infrastructure. Builds onchain, automation, validation, and payout systems end to end. |
| **Leticia Almeida** | Product and operations. Turns the thesis into execution, playbooks, and pilot workflows. |

**Advantage:** technical execution plus direct proximity to football creator communities and early demand signals.

---

## Slide 12
**The bigger idea is simple**

**Creator sponsorships should not depend on goodwill once money moves.**

**Gecko turns campaign budgets into enforceable onchain commitments.**

| Closing proof points | |
|---|---|
| **Funds are locked** | before delivery risk is taken |
| **Milestones are explicit** | before ambiguity turns into dispute |
| **Payout logic is automatic** | when conditions are met |

**Gecko brings escrow, accountability, and programmable campaign payouts to creator marketing.**
