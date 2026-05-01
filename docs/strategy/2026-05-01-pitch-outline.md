# Gecko — Pitch Outline (V1-honest)

**Date:** 2026-05-01
**Author:** staff-engineer (synthesis)
**Inputs:**
- `pitch-prep-business-manager-2026-05-01.md`
- `pitch-prep-ai-ml-engineer-2026-05-01.md`
- `pitch-prep-staff-engineer-2026-05-01.md`
- Stub-mode dogfood: **session_id `df14664b-c9d4-49f1-9ade-e437a7eb5499`** (verdict=REFINE, Gap=Partial:UX, tx_signature=`stub://synthetic-receipt` — no on-chain spend; `X402_MODE=stub`, `LLM_ROUTER=openai`)
- Earlier dogfood reference: session `a3eeb5dc-7274-4854-829d-174818010fc5` (failed at PRD validation under OpenRouter — captured in S15-AIML-03 nano-class issue family)

> **Tone gate:** every claim on a slide either (a) cites a commit / file / eval number, or (b) names the milestone that earns it. No exceptions.

---

## 1. One-line pitch (≤10 words)

> **Pre-spend verdict for agents and founders, above x402.**

(9 words.)

## 2. 30-second pitch (3 sentences)

> Agents and founders waste real money building the wrong thing. Gecko is an MCP that returns a signed KILL / REFINE / BUILD verdict — backed by a 5-voice adversarial debate, cited live sources, and an on-chain receipt — for $0.10–$0.75 per call, and we're listed in CDP Bazaar today. Our live-V1 eval gate scores 0.80 on holdout fixtures; we have three payment rails wired (stub, frames.ag/Solana, CDP/Base) through one X402Client Protocol seam, and `gecko_pulse` ships re-validation at $0.50/call.

## 3. 2-minute pitch (5 paragraphs)

**¶1 — The problem.** Bazaar, Anthropic Managed Agents, and CDP all make it easy to *ship* an agent. None of them answer "should this agent spend money on this thing in the first place?" Frames.ag has spend caps; those are budget gates, not judgment gates. Capability is being commoditized; **discrimination** — knowing which spend is the right spend — is the scarce resource.

**¶2 — The wedge.** Gecko is the budget approver that sits above x402. Before an agent or a founder commits real money to a build, Gecko returns a signed KILL/REFINE/BUILD verdict via a 5-voice adversarial debate (CEO / CTO / PM / Staff / Designer voices, then a judge), cited from RAG'd live sources, with an on-chain receipt. Today this is live in CDP Bazaar.

**¶3 — Why us, with numbers.** Live-V1 holdout eval gate at 0.80; general/crypto/saas at 1.0; rubric v2 at ~0.85. 151 test files; S12.5 contract policy enforces single source of truth on 6 shared Literal types. Three rails wired through one Protocol seam (S13-PAY-01). `gecko_pulse` v1 ships at $0.50, 12-pack at $5.40 (S14). Paragraph MCP ingestion with creator payouts on cite (S14-PARA-02). All commits public; all numbers reproducible from `run_eval_gate_live.sh`.

**¶4 — The flywheel.** Same engine, three buyer surfaces: founders pay to validate before building, agents pay to validate before spending, sellers (post-S17) pay to be reviewed for ranking advantage. As more agents call Gecko via Bazaar, more verdicts feed eval data, prompts sharpen, and verdict reliability compounds. Sprint 15-17 lays profile-typed contributor reputation on this base — investors first (50-investor founding-contributor program, $25k seed, S15-BIZ-01).

**¶5 — Honest gates.** "Trust layer of the agentic economy" is V3+, gated on a 4-rail proof (frames.ag + CDP + Cloudflare + awal) we expect to close at S17. We won't claim it before. We dogfooded our own thesis under stub-mode last night — Gecko returned REFINE on itself and missed reputation-gaming as a platform-design anti-pattern; the fix (S15-AIML-02) is in the next sprint plan. We pitch what we ship, not what we promise.

---

## 4. Slide outline (10 slides)

| # | Title | Headline claim | Evidence (V1 fact / V3 promise) |
|---|---|---|---|
| 1 | **Hook** | "Agents will spend your money. Approve the spec first." | V1: framing line; carry-forward from `bazaar-deeper-thesis-2026-04-30.md`. |
| 2 | **The wedge** | Pre-spend verdict above x402 — signed KILL/REFINE/BUILD. | V1 fact: `derive_verdict` shipped S11-VERDICT-01 (commit `400bed4` README refresh). |
| 3 | **5-voice debate architecture** | 5 model voices → judge → 1 signed token. | V1 fact: AutoGen/AG2 GroupChat live; tier-presets balanced/quality/budget/free wired. |
| 4 | **Eval gate** | live-V1=0.80 · general=1.0 · crypto=1.0 · saas=1.0 · rubric v2=0.85 | V1 fact: `run_eval_gate_live.sh`; reproducible. |
| 5 | **Pricing ladder** | $0.10 basic → $0.75 pro → $0.50 pulse (12-pack $5.40) | V1 fact: `RESEARCH_BASIC_PRICE`, `RESEARCH_PRO_PRICE`, `PULSE_PRICE` shipped. **Bury** $9 DeFi suite, $29 orchestrator (V3+). |
| 6 | **Wallet neutrality** | 3 rails wired through one Protocol seam | V1 fact: stub + frames.ag/Solana + CDP/Base via `gecko_core.payments.factory` (S13-PAY-01). 4th rail (Cloudflare/awal) = S15/S17 promise. |
| 7 | **CDP Bazaar listing** | Live at `/.well-known/x402` with 4+ paid routes | V1 fact: `S12-BAZAAR-01` + `S14-PULSE-04`. Show JSON. |
| 8 | **Traction (last 30d)** | See traction section below. | V1 facts; numbers from `git log --since 30d`. |
| 9 | **Self-dogfood transparency** | We pointed Gecko at itself. It said REFINE. It also missed something. | V1 fact: session `df14664b-c9d4-49f1-9ade-e437a7eb5499`; S15-AIML-02 fix queued. |
| 10 | **Honest gates** | What we are saying / what we are NOT saying | V3 framing deferred until S17 4-rail proof closes. |

Optional 11-12 if room: Founding Contributor Program ($25k seed, 50 investors, S15-BIZ-01); ICP map (founders today, agents in flight, sellers V3).

---

## 5. Traction slide content (real numbers)

Pulled `2026-05-01`:

| Metric | Number | Source |
|---|---|---|
| Commits in last 14 days | **52** | `git log --oneline --since 14d \| wc -l` (top of this conversation) |
| Commits in last 30 days | **188** | `git log --oneline --since="30 days ago" \| wc -l` |
| Sprint plans drafted | **12** (S1–S15 with gaps) | `ls docs/build-plan-sprint-*.md \| wc -l` |
| Sprints landed (closed retros) | **S1–S13 closed; S14 in flight; S15 ready-to-fire** | `docs/sprint-reviews/2026-05-01-s12-retro.md`; build plans |
| Test files | **151** | `find tests packages apps -name "test_*.py" \| wc -l` |
| Test pass-rate cited | **180/180 in S13 Track E** baseline | `docs/build-plan-sprint-13.md` Track E acceptance |
| live-V1 holdout eval gate | **≥ 0.80** | `run_eval_gate_live.sh` |
| general / crypto / saas eval gates | **1.0** each | rubric v2 |
| rubric v2 aggregate | **~0.85** | `tests/eval/runner` |
| CDP Bazaar listing | **Live** at `/.well-known/x402`, ≥4 paid routes | `S12-BAZAAR-01`, `S14-PULSE-04` (`f61aaa0`) |
| Payment rails wired | **3** (stub / frames.ag-Solana / CDP-Base) | `S13-PAY-01` (`b77b636`); `S14-PAY-MIGRATE-01..03` |
| MCP/CLI surfaces shipped | research, plan, advise, ask, classify, pulse, review, doctor, sources, precedents, memory_*, route, scaffold, project_economics | README surface table |
| Self-dogfood verdict | **REFINE** on our own thesis (`df14664b-c9d4-49f1-9ade-e437a7eb5499`) | this run |

---

## 6. "What we are NOT saying" — guardrails for feedback collectors

| Aspirational claim | Don't anchor here | Earns it when |
|---|---|---|
| "Trust layer of the agentic economy" | V3+ macro framing | S17 4-rail proof (frames.ag + CDP + Cloudflare + awal) closes |
| "Profile-typed orchestration of paid expertise" | V2/V3 sub-fold | `min(profile_types_cited) >= 3 over 7 days` (PD anti-gaming gate) |
| "Verdicts as on-chain commitment surfaces" | smart-contract gating on Gecko output | EAS-on-Base mirror via outbox pattern (S15-IDENTITY-02 → S17 sync) |
| "$35k MRR by month 6" | revenue projection | S17 chain mirror + Bazaar agent traffic compounding |
| "Discrimination layer / kills bad agents at protocol scale" | V3 macro vision | After Vector-4 orchestrator + Vector-5 certification ship |
| "Best validation for any agent" | unqualified superlative | Cross-product eval against Perplexity / Bazaar discovery is published |
| "Solana-first" or "Base-first" | rail tribalism | We're wallet-neutral by design; product works above any x402-capable wallet |

---

## 7. Three questions per audience type

Don't waste a feedback round. Tailor the question to what that audience can tell us.

### Pre-seed founders
1. If the verdict had been REFINE on your last build, would you have actually paused, or rationalized BUILD? (tests willingness-to-pay vs willingness-to-act)
2. At $0.75/call for the 5-voice debate, is that a *coffee* purchase or a *board memo* purchase? (frames the price anchor)
3. Would you trust a verdict from an MCP more, less, or the same as one from a Twitter founder you respect? (trust-substitution test)

### Agent operators
1. If your agent could call `gecko_research` before any spend ≥ $X, what's X? ($1? $10? $100?) (sets the integration ROI threshold)
2. Do you want a hard `KILL` to halt the agent, or a soft signal it can override with a higher-tier policy? (informs verdict-binding semantics)
3. Would you pay $0.10/call to filter out 80% of bad spends, or $0.75/call to filter out 95%? (price elasticity at the agent layer)

### Crypto-native investors
1. Is the on-chain receipt + EAS-attested verdict (S17) a real moat, or table-stakes by 2027? (validates V3 framing duration)
2. Does "wallet-neutral above x402" land as a differentiator or as hedging? (positioning gut-check)
3. Would you back the Founding Contributor Program ($25k seed for 50 investors at $500/mo retainer) as a sub-line item, or fold it into the round? (signals GTM-vs-product tension)

### Generalist VCs
1. Is "judgment-as-a-service for agents" a category you can pattern-match to existing portfolio bets, or does it need a new lens? (frames the deck's analogies)
2. The dogfood slide shows Gecko caught itself missing reputation-gaming — credible signal or red flag? (tests narrative-honesty appetite)
3. Which is the bigger market in 2027: founders paying for pre-spec validation, agents paying for pre-spend validation, or sellers paying for certification? (forces them to bet on an ICP)

### Potential contributors (investors, judges, PMs, designers)
1. Would you accept $300/mo retainer + $0.40 per cite to be part of a 50-person founding cohort? (validates BM's $25k seed math)
2. Would you publish under your own wallet (Phase 2 wallet-bridge, S15+) or under Gecko's wallet (Phase 1)? (informs wallet-bridge prioritization)
3. What would make you *leave* the cohort after 6 months? (surfaces the churn risk before liquidity)

---

## 8. Dogfood transcript reference

- **Session:** `df14664b-c9d4-49f1-9ade-e437a7eb5499`
- **Mode:** stub (`X402_MODE=stub`); no on-chain spend
- **LLM router:** `openai` (OpenRouter retry failed on PRD list-vs-string shape — captured separately as S15-AIML-03 nano/router-class issue)
- **Verdict:** REFINE
- **Gap:** Partial:UX — "existing decision-making tools lack the multi-voice debate format that Gecko offers"
- **8 sources discovered**, 4 successfully indexed (4 had Unicode/disconnect issues — non-blocking)
- **Tx signature:** `stub://synthetic-receipt` (no facilitator settle)
- **Cost:** $0 (stub)

The verdict converged with the 6-lens team synthesis: orchestration alone is not the wedge; the verdict shape + adversarial dissent is. Same conclusion the team reached on independent prompts — strongest possible internal-validity signal.

---

## Appendix — sources

- README post-`400bed4` (V1-honest framing)
- `docs/audits/2026-05-01-readme-docs-audit.md`
- `docs/strategy/bazaar-deeper-thesis-2026-04-30.md`
- `docs/strategy/profile-thesis-synthesis-2026-05-01.md`
- `docs/strategy/profile-thesis-dogfood-2026-05-01.md`
- `docs/strategy/sprint-11-13-architectural-review-2026-05-01.md`
- `docs/build-plan-sprint-14.md`, `docs/build-plan-sprint-15.md`
- `docs/strategy/pitch-prep-{business-manager,ai-ml-engineer,staff-engineer}-2026-05-01.md`
