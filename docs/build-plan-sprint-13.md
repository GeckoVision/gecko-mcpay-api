# Sprint 13 — DeFi Suite + Phase Primitive Seam (gate-conditional)

**Status:** draft, awaits S12 retro gate evaluation
**Predecessor:** Sprint 12 (CDP Bazaar listing + Base settlement + SourceProvider seam + transcripts archive + rubric v2)
**Driver:** `docs/strategy/roadmap-sprint-13-to-17-synthesis-2026-04-30.md` — 7-specialist synthesis. Lifecycle monetization is the top-converged theme; DeFi vertical suite is the top-converged commercial wedge; both ship in S13 if the gate opens, with shared engineering pre-payment underneath either path.

**Done = `gecko_research --vertical defi` ships at $9 with vertical-specific critic prompts (if gate opens) AND every existing surface gains a `phase` field that defaults to `pre_product`, unblocking S14's user-facing `gecko_pulse` and S14's Paragraph creator-monetization.**

---

## Gate evaluation (at S12 retro, before S13 fires)

Two signals must both pass for the **Suite + Seam** path. If either fails, **Seam-Only** path fires.

| Signal | Pass criterion |
|---|---|
| Bazaar agent traffic | ≥1 Bazaar-discovered agent call lands at gecko-api in the 7-14 days post-S12 listing |
| DeFi provider quality | ≥1 named DeFi-relevant Bazaar provider with ≥100 calls/30d AND clean JSON Schema |

Document the gate decision in `docs/sprint-reviews/2026-MM-DD-s12-retro.md` before S13 tickets are cut.

---

## Tracks (Suite + Seam path — gate passes)

### Track A — DeFi Vertical Suite at $9 **HIGH**

The first commercial wedge beyond Pro. Per `docs/strategy/bazaar-composer-business-review-2026-04-30.md`: suites are a moat (vertical-specific critic prompts), not a SKU (generic Pro+ would cannibalize $0.75 Pro).

- **S13-SUITE-01 — DeFi-vertical critic prompt + advisor persona variants.**
  Author DeFi-specialized prompts in `packages/gecko-core/src/gecko_core/orchestration/pro/_default_prompts_v5_5_defi.json`. Critic agent gets DeFi-specific failure modes (rug history, MEV exposure, liquidity assumptions, regulatory shift). Advisor panel: CEO/CTO unchanged; product_manager + business_manager + staff_manager get DeFi-flavored persona suffixes.
  **Owner:** ai-ml-engineer
  **Acceptance:** new prompt files validate against existing schema; stub-mode `bb research --idea "..." --vertical defi` produces output with at least 2 DeFi-specific critiques in the transcript.

- **S13-SUITE-02 — Auto-detect DeFi vertical via classifier; `--vertical` override.**
  Extend `gecko_core/classify` to emit `vertical: Literal[None, "defi"]` (extensible enum) alongside existing categories. Wire `--vertical` CLI flag in `apps/cli/src/gecko_cli/commands/research.py` to override classifier choice.
  **Owner:** software-engineer + ai-ml-engineer (classifier prompt)
  **Acceptance:** 5 DeFi fixtures auto-classify as `defi`; 5 SaaS fixtures don't.

- **S13-SUITE-03 — Bundle 3-5 named DeFi-relevant Bazaar providers.**
  Identify providers from S12 retro evidence (need to have appeared in Bazaar discovery probe). Wire each as a `BazaarProvider` instance via the SourceProvider Protocol from S12. Parallel fan-out with 6s per-provider hard cap (per product-designer's latency mandate).
  **Owner:** software-engineer (orchestration) + web3-engineer (settlement plumbing per provider)
  **Acceptance:** stub-mode run lists all 5 providers; live-mode run pays each provider in parallel and surfaces costs in the receipt.

- **S13-SUITE-04 — DeFi suite UX surface.**
  Vertical-themed spinner ("Pulling DeFi market signals..."). Receipt with single `Bazaar-routed sources $0.20` line + indented `└─ vertical: defi (4 providers)` per product-designer's S12 design memo. `--show-providers` flag to surface names if requested.
  **Owner:** product-designer + software-engineer
  **Acceptance:** stub-mode run shows the vertical-themed spinner and the receipt anatomy; `--show-providers` reveals provider names; without flag, names are hidden.

- **S13-SUITE-05 — DeFi holdout fixture suite + eval gate.**
  10 DeFi-flavored ideas (5 BUILD-expected, 5 KILL-expected) under the rubric v2 native verdict shape from S12. Land at `tests/eval/fixtures/defi_holdout/`. Run as part of the broader eval gate.
  **Owner:** ai-ml-engineer
  **Acceptance:** `defi_holdout` suite runs; aggregate verdict_accuracy ≥ 0.85 in stub mode (live signal in S14).

### Track B — Phase Primitive Seam **CRITICAL**

The 4-lane pre-payment that unblocks S14 (`gecko_pulse`) + S14 (Paragraph) + S15 (pulse delta). Per staff-engineer's S13 architectural pre-payment + independently named by software, data, ai-ml.

- **S13-PHASE-01 — `SessionPhase` enum + `parent_session_id` on Session.**
  Add `SessionPhase = Literal["pre_product", "during_build", "ongoing"]` to `gecko_core/sessions/models.py`. Add `parent_session_id: Optional[UUID]` FK on Session for pulse linkage. Migration applies idempotently with `pre_product` default.
  **Owner:** software-engineer + data-engineer (migration)
  **Acceptance:** all existing sessions remain functional; new sessions can be created with `phase` and `parent_session_id`; FK constraint enforced.

- **S13-PHASE-02 — Temporal chunks: `captured_at` + `project_id` + windowed RPC.**
  Migration `infra/supabase/migrations/20260501000000_chunks_temporal.sql` adds `chunks.captured_at TIMESTAMPTZ` (default now()) and `chunks.project_id UUID` (nullable, FK to a future projects table — projects table not in S13 scope). Create `match_chunks_windowed(query_embedding, window_days INT, project_id UUID)` RPC for time-windowed similarity search. Scoped index on `(project_id, captured_at)`.
  **Owner:** data-engineer
  **Acceptance:** migration applies; existing chunks backfill `captured_at` from `created_at`; RPC returns results constrained to the window.

- **S13-PHASE-03 — Phase-aware fixture loader.**
  Refactor `tests/eval/fixtures/` into `fixtures/{phase}/{vertical}/`. Move all existing fixtures to `fixtures/pre_product/`. Add stub `fixtures/during_build/` and `fixtures/ongoing/` directories with READMEs. Update fixture loader in `tests/eval/runner.py` to dispatch by phase.
  **Owner:** ai-ml-engineer (relabel) + software-engineer (loader)
  **Acceptance:** existing eval gate runs unchanged; new phase directories exist and are discoverable; rubric v2 schema gains nullable `phase` field defaulting to `pre_product`.

### Track C — `X402Client` Protocol formalization **MED**

Web3 pre-payment so S15 Cloudflare integration is a config add, not a 3-class refactor.

- **S13-PAY-01 — Narrow X402Client Protocol + factory.**
  In `packages/gecko-core/src/gecko_core/payments/`, define `X402Client` Protocol with `supported_networks: tuple[NetworkKind, ...]`, `facilitator_id: str`, async `charge(intent) -> Receipt`, async `verify(tx) -> ConfirmationStatus`. Existing `LiveX402Client` (frames.ag) and `CDPX402Client` (Sprint 12) conform. Add `resolve_client(intent) -> X402Client` factory keyed on network. Reserve `http-cloudflare` network slot raising `NotImplementedError("Sprint 15: Cloudflare x402 integration")` so S15 work is purely additive.
  **Owner:** web3-engineer
  **Acceptance:** existing frames.ag + CDP flows pass tests under the Protocol; factory routes correctly per `X402_NETWORK`; `http-cloudflare` slot raises the explicit error.

### Track E — Commoditization expansion (S13-COMMO-01..03) **MED**

Per user prompt 2026-04-30: "beyond judgments, what else can we commoditize?" The 3 highest-leverage candidates that reuse existing infra:

- **S13-COMMO-01 — Standalone advisor voice pricing.** `gecko_advise <session_id> --voice cto` already exists; today it's free (per Sprint 4 deferral). Wire x402 charge: $0.05 per voice via the same payment client used by `gecko_research`. Surface in `bb economics` per-voice line items.
  **Owner:** web3-engineer (payment hop) + software-engineer (CLI surface)
  **Acceptance:** paid `gecko_advise` lands a real receipt; `bb economics` shows per-voice charge.

- **S13-COMMO-02 — Session knowledge base queries.** `gecko_ask <session_id>` already exists; wire x402 charge ($0.01-0.05 per query) so other agents can pay to query an already-researched corpus. Shifts a tool from "free dev convenience" to "monetizable surface."
  **Owner:** software-engineer + web3-engineer
  **Acceptance:** `gecko_ask <session_id>` charges per call; rate-limit + budget guards in place.

- **S13-COMMO-03 — Classify-as-a-service.** Expose `mcp__gecko__gecko_classify <idea>` returning a paid "here are the 6 sources you should hit, with priority weights." $0.10/call. The classifier is genuine first-party IP; selling classification without selling the verdict opens the developer-tools market.
  **Owner:** software-engineer + ai-ml-engineer (classifier prompt review)
  **Acceptance:** new MCP tool + CLI command + Bazaar listing metadata.

These three add SKUs to the existing pricing ladder without expanding the moat surface. Together: estimated <2 days of engineering, real new revenue lines to test.

### Track F — Wallet panel implementation (S13-WALLET-01) **MED**

Spec lands in Sprint 12 Track D (`docs/strategy/wallet-panel-spec-2026-04-30.md`). Implementation here.

- **S13-WALLET-01 — `bb wallet` panel.** Single command shows all configured wallets (frames.ag/TWITSH/awal/publish.new/Paragraph creator) with balances, funding paths, per-rail health. Subcommands: `bb wallet add`, `bb wallet show`, `bb wallet fund`. Match `bb doctor` Rich-table style. **Owner:** product-designer (Rich layout) + software-engineer (state aggregation).
  **Acceptance:** `bb wallet show` returns all wallets in <2s; first-run with no wallet auto-prompts setup; `bb wallet fund frames.ag` surfaces the OTP+faucet path; `bb wallet fund cdp` surfaces the Coinbase onramp path.

### Track D — Citation creator attribution **MED**

Per product-designer S13-PD-01. Pre-payment for S14 Paragraph creator surface — receipt anatomy lands first, Paragraph fills it in.

- **S13-CITE-01 — Optional creator fields on Citation + footer rendering.**
  Add `creator_handle: Optional[str]` + `creator_payout_usd: Optional[float]` + `creator_wallet: Optional[str]` to `Citation` model. Update `apps/cli/src/gecko_cli/render.py` lines 91-107 to render creator handle inline next to source URL when present. Add a "Creator payouts" footer block when any citation has a non-null `creator_payout_usd`. **Hidden when null** — pre-Paragraph runs unaffected.
  **Owner:** product-designer + data-engineer (`source_creators` sibling table per their memo)
  **Acceptance:** existing research runs render identically (no creator fields = no footer); manually-stubbed citation with creator fields renders the inline handle and footer.

---

## Tracks (Seam-Only path — gate fails)

If S12 retro gate fails, **Tracks B + C + D ship as above.** Track A becomes:

### Track A' — Vector 1 doubling-down

- **S13-LIST-01 — Sharpen Bazaar listing metadata.**
  Iterate descriptions, schema completeness, route consolidation prevention. Add 2-3 more discoverable routes if surface allows (e.g. `gecko_advise` if not already listed).
  **Owner:** software-engineer + business-manager (description copy)

- **S13-LIST-02 — Polish Claude Code skill distribution.**
  Revisit `gecko-mcpay-skills` repo, the install path, the first-paid-call walkthrough. Cross-reference S10 demo runbook. Goal: smoother first-time-user funnel.
  **Owner:** product-designer

- **S13-LIST-03 — Quality-rank push.**
  Whatever observable Bazaar quality signal (calls, recency, metadata completeness) we control directly, optimize.
  **Owner:** business-manager + software-engineer

---

## Out of scope

- User-facing `gecko_pulse` surface (S14)
- Paragraph connector implementation (S14 — uses S13 Track D citation surface + S13 Track B phase primitive)
- Cloudflare x402 consumer-side (S15 — uses S13 Track C reserved slot)
- App-launching template (S16+ gated on positioning decision)
- Pulse delta renderer (S15)
- Marketplace cut on hosted-scaffold apps (deferred to option set)
- Edge-deploying gecko-api on Cloudflare Workers (V3+; loses AutoGen)

## Acceptance (sprint-level)

- [ ] `SessionPhase` enum landed; all existing sessions default `pre_product`; `parent_session_id` FK enforced
- [ ] `chunks.captured_at` + `chunks.project_id` migration applied; `match_chunks_windowed` RPC works
- [ ] `X402Client` Protocol formalized; existing flows green; `http-cloudflare` slot raises explicit S15 error
- [ ] `Citation` model gains optional creator fields; footer renders when populated, hidden otherwise
- [ ] **If gate passed:** `bb research --idea "..." --vertical defi` ships at $9 with `defi_holdout` eval ≥ 0.85 in stub
- [ ] **If gate failed:** Bazaar listing metadata sharpened, ≥2 new routes listed, install funnel polished
- [ ] No regression on existing Pro tier flow (live-V1 holdout_live ≥ 0.80 under rubric v2 from S12)

## Test plan

After all tracks land:
1. **Phase seam regression:** existing eval gate (general/crypto/saas/holdout/holdout_live) runs unchanged with `phase=pre_product` defaulted
2. **DeFi suite stub:** `bb research --idea "AMM with adversarial sandwich-protection" --vertical defi` → expect BUILD or REFINE with DeFi-specific critiques in transcript
3. **DeFi suite live (one paid call):** same idea, `--vertical defi --tier suite-defi` settles $9 USDC, returns verdict + 4-provider receipt
4. **X402Client factory:** unit tests exercising frames.ag (Solana), CDP (Base), and the explicit Cloudflare slot error
5. **Citation rendering:** stubbed citation with all 3 creator fields renders; null creator fields render unchanged

## Reference

- `docs/strategy/roadmap-sprint-13-to-17-synthesis-2026-04-30.md` — synthesis driving this plan
- `docs/strategy/sprint-13+-staff-engineer-memo-2026-04-30.md` — sequencing call
- `docs/strategy/sprint-13+-business-manager-memo-2026-04-30.md` — DeFi suite pricing + ICP
- `docs/strategy/sprint-13+-ai-ml-engineer-memo-2026-04-30.md` — phase-aware persona library
- `docs/strategy/sprint-13+-software-engineer-memo-2026-04-30.md` — phase primitive on Session
- `docs/strategy/sprint-13+-data-engineer-memo-2026-04-30.md` — temporal chunks migration
- `docs/strategy/sprint-13+-web3-engineer-memo-2026-04-30.md` — X402Client Protocol
- `docs/strategy/sprint-13+-product-designer-memo-2026-04-30.md` — citation creator attribution
- `docs/strategy/bazaar-deeper-thesis-2026-04-30.md` — macro positioning ("trust layer of the agentic economy")
