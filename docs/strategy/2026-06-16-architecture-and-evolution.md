# Gecko — Architecture Analysis + Strategic Evolution (2026-06-16)

Synthesis of a 9-lens homework pass (codebase map + Colosseum gap analysis + Solana ecosystem research + anti-wash feasibility + 6 specialist lenses: solana-research / defi / web3 / ai-ml / data / software). Scored against the new `docs/strategy/planning-rubric.md`.

---

## 0. TL;DR — the evolution in one page

**From:** a conservative value-investing trading oracle ("I don't lose money because I don't buy risk").
**To:** a **data-driven token pre-analysis + anti-wash decision-integrity gate that any agent plugs into (BYOA).** Wedge = **Information-MEV / "Plane C: data integrity"** — verifying the price/volume/oracle a decision rests on hasn't been manufactured.

**The anchor proof (real, $285M):** The **Drift Protocol hack (April 1 2026)** — attacker minted a fake token (CVT), seeded ~$500 liquidity on Raydium, **wash-traded a ~12-minute price history near $1**, that price got picked up by oracles, listed on Drift, drained $285M. **RugCheck would pass it** (no authority issues), **GoPlus AgentGuard would pass it** (execution-safe swap), **SicariusGuard would pass it** (holder concentration fine). The manipulation lived in the *data*, not the contract. **Nobody occupies that plane. We do.**

**The "too conservative" critique is literally encoded in our code** (ai-ml lens): the panel forces ~40% of its chunks to be investor-philosophy *by retrieval quota*, while live on-chain data has **no quota slot at all** and the manipulation signal we already compute is **inert in the verdict logic**. Fixing the thesis is mostly changing integers + adding a deterministic escalation — not a rewrite.

**Rubric score of the evolution (Colosseum weights): Novelty 7.5 / Impact 8 / weighted ≈ 7.4.** "Oracle" is the single highest-winning primitive (+27% winner lift); the consumer rug-checker lane is the *losing* distribution. Lead as **oracle/infra for agents**, never a human rug-checker. **Avoid the literal phrase "on-chain verification" (0/55 win rate in the corpus).**

---

## 1. Updated technical & architectural analysis

### 1.1 Workspace (uv monorepo)
- `gecko-core` (~39k LOC) — all business logic: trade panel, safety, RAG, ingestion, payments, receipts, trade_agent. **The core/transport-thin rule is followed** (api/mcp/cli import core; no logic leaks) — with ONE violation: `contest_bot` (~12k LOC) is a self-contained monolith that duplicates orchestration.
- `gecko-api` (FastAPI), `gecko-mcp` (HTTP client of the API, 20 tools), `apps/cli`.

### 1.2 The oracle (7-voice panel) — LIVE (basic tier)
technical → sentiment → fundamental → risk → strategist → bull_bear → coordinator. Closing-line regex parse; **dissent surface** (oppose/abstain, verbatim) is the product moat; **grounding gate** nulls ungrounded numbers; **coordinator escalation rules in code** (not prompt — per the prompt-plateau finding). S35 split: canon → `framework_context`, live/protocol → `evidence_citations`.

### 1.3 Safety / Information-MEV — LIVE
`safety_check.py`: honeypot/mint-authority (QuickNode→Helius fallback), holder concentration (>35%), liquidity-to-mcap (`thin_liquidity` <1%, `fake_market_cap` <0.2%, abs floor $500K), peg (Pegana). `InformationMEVBlock{score,label∈clean/elevated/manipulated,reasons}`. Injected pre-panel as a synthetic `onchain_live` chunk (Pattern E/F clean). Fast **`POST /safety`** = deterministic, free, sub-second, fail-OPEN, returns a one-glance `gate`.

### 1.4 RAG — LIVE
Mongo Atlas `$vectorSearch` (Voyage `voyage-3-large`, 1024-dim) + provider-weighted rerank + Voyage rerank-2; canon corpus (Marks/Damodaran/Berkshire/Mauboussin/macro). **Finance-embed A/B (this session): keep `voyage-3-large` — voyage-finance-2 was noise at N=5.**

### 1.5 Providers
OKX news (HMAC, **fixed this session** — was silently empty), OKX OnchainOS market (holders/liq/index price), Dune (credit-guarded), CoinGecko/GeckoTerminal (keyless), Pegana (depeg — keep, full-removal plan saved), Helius/QuickNode RPC, Pyth.

### 1.6 API / payments / receipts
`/research` ($20, x402, stub-only), `/research/pro` (**501 — not implemented**), `/safety` (free), MCP mount. x402 stub default + kill-switch + allowlist (defense-in-depth). **Decision Receipts exist end-to-end** (`payments/receipt/`: hash spec + devnet anchor + verifier route) — only the *emit path* onto responses is missing. Facilitator-neutral (frames.ag Solana / CDP Base).

### 1.7 Agents
Majors monolith on ECS — **healthy but inert** (open=0; majors-5m breakout never fires). New **active-universe paper agent** (PR #144) on a memecoin universe + two-tier `/safety`+oracle gate → observable loop.

### 1.8 Infra
ECS/CloudFormation, `deploy.sh`, SSM `__unset__` sentinel convention. **Merged-but-not-deployed**: wedge fixes + news fix + `/safety` await a `./infra/deploy.sh` to go live.

---

## 2. The critique — where we're too conservative / dark / in debt

1. **Quota conservatism (the smoking gun).** `_PROVIDER_QUOTAS` reserves **10 of 19 slots for canon**; `_CANON_FLOOR_COUNT=6` forces 6 of top-15 to be philosophy *before any live chunk competes*; `onchain_live` has **no quota slot**. ~40% of the panel's attention is forced onto timeless philosophy. This is the literal encoding of "too conservative."
2. **The manipulation signal is inert.** `_attach_safety` floors confidence only on `honeypot`/`fake_market_cap`; it **ignores `information_mev.label=="manipulated"`, `elevated`, and standalone high-concentration** in the verdict literal. Computed, attached, but doesn't bite.
3. **The eval can't prove the thesis.** All 10 rubric fixtures are known DeFi protocols; **no SPL-mint, no wash/BrCA case**; `onchain_live`/`safety`/`information_mev` appear nowhere in the rubric. A philosophy-led and a data-led panel score identically. (This is also why the finance-embed A/B moved nothing — canon was never the binding constraint.)
4. **No swap-level data.** Everything today is token-level aggregates or account-level. Real wash detection (self-trade, circular rings) needs per-swap fills — the one genuinely new data dependency.
5. **contest_bot monolith** (~12k LOC, duplicated orchestration, dark via OBSERVATION_MODE) — refactor-to-delegate or deprecate in favor of the paper agent.
6. **Pro tier `/research/pro` = 501**; **single-provider dependencies** (OKX/Dune/OnchainOS) with thin fallbacks.

---

## 3. Competitive landscape + the whitespace

**Three planes; we own the empty one:**
- **Plane A — static structural risk** ("is the contract a rug?"): RugCheck, Solsniffer, GoPlus Token API, SicariusGuard, Bubblemaps (clusters), GMGN/Nansen (smart money). **Crowded.**
- **Plane B — agent execution safety** ("is my agent being hacked?"): GoPlus AgentGuard (prompt injection, credential leak, wallet drain). **Emerging, complementary.**
- **Plane C — market-data integrity for the decision** ("is the price/volume/oracle this trade rests on real?"): **EMPTY.** Institutional surveillance (Solidus, Chainalysis) has the methodology but is enterprise-priced + human-facing/retrospective — not an agent-callable sub-second gate.

**Colosseum data (5,428 projects / 293 winners):** "oracle" = top winning primitive (+27% lift); consumer rug-checker lane = losing distribution (NFT/token/gating −50%+ among winners); wash-trading exists only as a *buried feature*; the "agent × integrity-of-inputs" quadrant is unoccupied. Novelty 7.5, Impact 8.

**Category framing that wins:** the market has a *transaction firewall* (AgentARC/Blockaid/GoPlus) and an *LLM firewall* (Lakera). It has **no *decision firewall* — "won't take a clean-but-manipulated trade."** GoPlus already proves **x402 pay-per-call** for agent safety → validates our exact billing model.

**Positioning line (data-supported):**
> Gecko is the data-integrity gate between an AI trading agent and its market data — verifying the price, volume, and oracle a decision rests on haven't been manufactured. Every other safety layer checks the contract or the agent's execution; nobody checks whether the information itself was poisoned. The Drift $285M hack is the proof.

**Watch-outs:** (1) lead oracle/infra-for-agents, not human rug-checker (or judges pattern-match you to the losing cohort); (2) avoid "on-chain verification" phrasing; (3) GoPlus/AgentARC could extend *down* into decision-quality — moat must be the **adversarial-debate verdict + investor-canon epistemics + manipulation-screening fused** (hard to bolt onto a contract scanner).

---

## 4. The evolution — data over philosophy (ai-ml lens)

Canon stays the **reasoning frame** (skepticism, falsification, dissent, cycle-position); it stops being a **verdict driver via citation quota**.

**Rebalance (mostly integers + one code escalation):**
- `_PROVIDER_QUOTAS`: add `onchain_live: 2` (reserved, fills first); canon 10→6; `market_data` 2→3.
- `_CANON_FLOOR_COUNT` 6 → **3** (single biggest "stop being conservative" lever).
- `_attach_safety`: **flip `act`→`defer` on IMEV `manipulated`; flip `act`→`pass` on honeypot** (today it only floors confidence — an `act`@0.0 contradiction); surface `manipulated`/`elevated` as a synthetic `risk_manager` **dissent entry** (into the moat surface); add `information_mev` to `_VOICE_ON_TOPIC`.
- 4 surgical persona edits (risk_manager owns the wash signal as first-priority input; fundamental prefers live figure over canon framing; coordinator orders live data above canon in key_drivers). **No "manipulated→defer" in prompts** — that's the plateau trap; it goes in code.

**Eval to prove it:** new `token_safety_holdout.json` (3-4 wash/trap SPL-mints + 3-4 clean majors as false-positive guard + 2 thin-but-legit edge cases); new deterministic `safety_grounding` rubric axis; headline metric = **wash-catch-rate** A/B (Arm A philosophy-led vs Arm B data-led). Thesis proven if Arm B catch-rate > Arm A **with clean-major false-positive rate flat**.

**Risks:** canon-coverage gate regression (migrate the gate weighting in lockstep), over-rotation to data (the clean-major guard + the existing $500K liq floor protect this), losing dissent quality (keep canon as framework + the macro voice philosophical).

---

## 5. The anti-wash / decision-firewall design

**Signals (defi lens) — build order by signal/cost:**
| # | Signal | Source | Status |
|---|---|---|---|
| S5 | DEX price vs OKX-index vs Pyth divergence | clients all exist | **today, pure compose** |
| S6 | LP-vs-volume impossible turnover (`vol24h/liq`) | OKX (fields fetched, discarded) | **today** |
| S7 | holder-vs-volume divergence (`vol24h/holders`) | OKX (both fields present) | **today** |
| S1 | volume-vs-unique-traders | one Dune saved query | next |
| S2 | self-trade / circular rings | Helius parsed swaps | the moat (cache-gated, Pattern B first) |

False-positive guards (must-have): **collapse Jupiter multi-hop routes** before counting sides; discount **MM two-sided quoting** (net-flow-to-self = wash, net-flow-to-LP = MM); **CLMM/DLMM out-of-range TVL** inflates the liq denominator; exempt peg assets (Pegana) + brand-new mints.

**Data layer (data lens):** new `gecko_features` Mongo DB **out of the RAG path** (mirror the pegana "structured provider, not embedded" doctrine). `wash_signal` (Dune cache + TTL = credit guard), `token_feature_snapshot` (time-series — closes the `safety_check.py:64` velocity gap). Hotpath isolation for any streaming.

**Code shape (software lens):** new `WashRiskBlock{score,label∈clean/suspicious/wash,reasons,raw figures}` mirroring `InformationMEVBlock`; one new keyless source `geckoterminal_pools.py`; pure `wash_signals.py`; wire into `safety_check` + extend `_safety_gate` (`wash`→block, `suspicious`→caution). **Rides the existing `SafetyBlock`/`onchain_live` plumbing → the bot and BYOA agents get wash detection for free, no contest_bot change.** No new ProviderKind (Pattern A stays green). Pattern E reachability probe required (signal must reach the panel + `/safety`, end-to-end).

**BYOA (web3 lens):** ship **A** (x402-HTTP `/safety`+`/trade_research`, keep `/safety` free tier + add a paid micro-tier with receipts) **and B** (`gecko_safety` MCP tool + `api_client.safety()` — ~30 LOC, the cheapest high-value thing) together. **Decision Receipts: only the emit path is missing** — off-chain ed25519 sig on `/safety`, on-chain devnet memo on `/trade_research`. **Bill a "no" like a "yes"** (already structurally correct — settle before the panel runs). Distribution rail (solana lens): **MCP + x402**, listed on SkillMarket + OKX Plugin Store + as a Solana Agent Kit plugin (B2B2A model). SicariusGuard (MCP+x402, 100 free/day) is the precedent; GoPlus AgentGuard is complementary upstream.

---

## 6. Roadmap (rubric-scored)

### Phase 1 — Wash v0.1 from discarded fields + make the signal bite (≈1 sprint)
S5/S6/S7 + `WashRiskBlock` + wire into `/safety` gate; the `_attach_safety` verdict escalation (IMEV manipulated→defer, honeypot→pass, dissent surface); `gecko_safety` MCP tool. **No new vendor.** Validate on Drift-CVT-style + BrCA cases (Pattern B) + Pattern E probe.
- **Rubric:** Novelty 7 · Impact 8 · Functionality 7 (live on `/safety`) · UI/UX 8 (MCP-pluggable) · Business 7 · OSS 10 → **weighted ≈ 7.5.** ✅ build.

### Phase 2 — Real wash signal + panel rebalance + prove it (≈1-2 sprints)
Dune `vol_per_trader` query + `gecko_features` store + `token_feature_snapshot`; the quota/canon-floor rebalance; `token_safety_holdout` + `safety_grounding` axis + wash-catch-rate A/B; Decision-Receipt emit path.
- **Rubric:** Novelty 8 · Impact 8 · Functionality 7 · UI/UX 7 · Business 7 · OSS 10 → **weighted ≈ 7.8.** ✅ build.

### Phase 3 — The moat + distribution (≈2-3 sprints)
Helius swap-level self-trade/ring detection (cache-gated); thin BYOA SDK from OpenAPI; list on SkillMarket / OKX Plugin Store / SAK; the **Drift-hack replay demo** ("Gecko flags CVT's 12-minute manufactured price"). Refactor/deprecate contest_bot.
- **Rubric:** Novelty 8.5 · Impact 8.5 · Functionality 7 · UI/UX 8 · Business 8 · OSS 10 → **weighted ≈ 8.2.** ✅ build.

---

## 7. Founder decisions needed
1. **`WashRiskBlock` distinct vs folded into `InformationMEVBlock`** — software + ai-ml both recommend **distinct** (wash = "is the volume fake" vs IMEV = "is the price manipulable" — different data, different buyer question, different gate severity). Staff-engineer-class model call.
2. **Deploy** to activate the already-merged wedge + news + `/safety` work (`./infra/deploy.sh`).
3. **Birdeye** as a new vendor — **defer** (OnchainOS+GeckoTerminal+Dune cover it); revisit only if a specific field is missing.
4. **Colosseum token** — refreshed via `.env.colosseum`, working.

*Sources captured in the 9 agent reports (Drift hack, Cong et al. + Victor & Weintraud wash methods, the 181-token labeled Solana wash set in arXiv 2507.01963, Colosseum Copilot corpus).*
