# S40 Sprint Plan — local agents → validated → API

*2026-05-21. Synthesized from a 4-agent design pass (ai-ml, data, trading-
strategist, staff) + the OKX `agent-skills/REVIEWING.md` rubric + tonight's
live-contest findings. The contest ends ~4h from now; this sprint runs
AFTER it. Mandate: get the local agents to a validated first-running
version (better voices, real data, regime-aware), implement skills-security
+ agent-safety, then transplant to the PRD API.*

---

## Where we are (entering S40)

- **Live contest:** +1.02% real (3W/1L), bot correctly abstaining in chop.
- **Proven tonight:** breakout is -EV in chop (regime problem, not threshold);
  candle-ordering + 6 other live-only bugs fixed; per-poll telemetry now logging.
- **Skill:** Gecko Risk Oracle ready to submit (under rubric size gate, `---`
  frontmatter, explains *why*).
- **The wedge holds:** adversarial voices + abstain-not-fabricate, on-chain proven.

**The strategic reframe:** we're not chasing the leaderboard (~9% in chop is
out of reach). We're building the **data→agents→skills loop** that outlasts
the contest. The agent stays live on small capital, generates data, the data
trains better agents, the validated logic ships as metered skills + the oracle.

---

## Five workstreams

### Track A — DATA (the foundation; unblocks everything)

| Sprint | Deliverable | Priority |
|---|---|---|
| **A0** | **Fill the EMPTY corpus kinds** — `canon_mauboussin` + `canon_macro` are declared in the ProviderKind Literal, the panel cites them, the drift-test passes — but **zero chunks exist** (shipped-but-hollow). Mirror `scripts/canon/ingest_marks.py` on public-domain PDFs (Mauboussin base-rates; Fed/BIS macro). | **P0 — closes a live gap** |
| **A1** | Telemetry → MongoDB loader (`scripts/telemetry/load_poll_telemetry.py`). JSONL maps 1:1; add `episode_id`, `instance_id`, `run_date`. Idempotent upsert. Indexes: `{symbol,ts}`, `{episode_id,ts}`, `{run_date,outcome}`. Build now, flip from JSONL when multi-instance / cross-session needed. | P1 |
| **A2** | Outcome labeling job — join telemetry episodes to artifact close-events → `outcome` (tp/sl/trail/stall/time_stop) + realized_pnl + MFE/MAE on every poll row. Produces the `(features, outcome)` table for v2 classifiers. | P1 |
| **A3** | New live sources: `okx_market` (indicators + smart-money), `onchain_helius` (holders/flows). Each = new ProviderKind + drift-test update + **end-to-end reach test** (≥1 chunk reaches panel; tag `freshness_tier=hot`, never gate on session_id; market chunks carry exact symbol tag, canon stays `protocol=[]`). | P2 |

### Track B — AGENTS (the 5-voice local panel)

Move from 3 voices to 5, all OpenRouter (not OpenAI), verdict logic in CODE.

| Sprint | Deliverable |
|---|---|
| **B1** | `get_indicators()` thin client (one cached OKX `market_get_indicator` call/poll, shared across voices — don't let each voice fetch). |
| **B2** | **chart_analyst v2** — reasons over real indicators (adx, rsi, mfi, ema-stack) not hand-rolled TA. Bullish requires confluence (trend + flow + not-exhausted). Keeps abstain protocol + 0.85 floor (in coordinator). |
| **B3** | **regime_analyst (NEW)** — deterministic-first (like risk_voice): adx≥25 + expanding BB = trend; adx<20 + tight BB = chop. Emits trend/neutral/chop. The highest-value addition — it's the axis chart can't express (the chop -EV problem). |
| **B4** | **memory_voice fix** — remember OUTCOMES not decisions (read `position_close`, not declines). Cold-start: abstain until ≥3 closed outcomes (breaks the feedback-loop bug). Exp decay, half-life 24h, contradict cap ≤0.6. |
| **B5** | **smart_money_voice (NEW)** — OKX `smartmoney_*` + top-long-short. Confirmation-only (never a veto, never sole trigger; caps confidence +0.10). Anti-gaming: ≥N distinct wallets, discount wash patterns. |
| **B6** | **Coordinator v2** — 5-voice rule chain in code, adds `defer_grid` action: risk-veto → chart-missing → chop(→grid unless chart≥0.92+SM) → trend(floor 0.85, −0.05 if SM) → memory-contradict → act. |

### Track C — TRADING STRATEGY (regime-switch + grid)

| Sprint | Deliverable |
|---|---|
| **C1** | **Grid backtest FIRST** — extend `backtest_entry.py` with `simulate_grid()`. Segment series by ADX (≤18 chop / ≥25 trend), run grid on chop segments. **Kill metric:** grid chop-PnL vs cash vs breakout, after 0.6%/leg DEX fees. If ≤0 after fees → shelve grid, keep momentum + an ADX flat-zone "sit in cash during chop" gate (a free win tonight's data already supports). |
| **C2** | **Regime-switch logic** — per-symbol state machine: TREND (adx≥25) = momentum, CHOP (adx≤18) = grid, dead-zone (18-25) = hold regime + 3-bar confirm (hysteresis). One leg holds inventory per symbol at a time. |
| **C3** | **Grid executor (DEX-spot)** — only if C1 clears. Bollinger(20,2σ) bounds, 8 levels (6 for thin BOME/TNSR), per-grid `swap_execute` fills. Range-break (>1 ATR beyond band) → halt + market-exit + hand to regime. **No native OKX grid endpoint — DEX spot via swaps.** |

**Honest EV (strategist):** grid is +EV in chop only if DEX round-trip cost <
grid step — likely true on PYTH/WIF/DRIFT (deep liquidity), likely NOT on
thin BOME/TNSR (fees bleed). Expect a *modest real* improvement, not a step-
change. Backtest decides. Realistic target = the proven ~1.5-2%/week low-DD.

### Track D — SECURITY + SAFETY (gates everything that ships/scales)

| Sprint | Deliverable |
|---|---|
| **D1** | **skill-guard CI gate** (`.github/workflows/skill-guard.yml`, paths-triggered on `gecko-skills-contest/**`): clone OKX skill-guard (pin SHA), scan our skill (malware / secret-leak / prompt-injection), fail-closed. Required-to-merge + required-before-publish. |
| **D2** | **REVIEWING.md self-lint** (pure Python, no LLM): frontmatter present, description **80-150 words (ours ~70 — must expand)**, <500 lines (322 OK), no phantom tools (every dep + `okx-*` ref is real), examples parse as the documented JSON schema. |
| **D3** | **Agent-safety belts** (prioritized, precede any capital scale-up): (1) kill-switch file/env flag polled each loop, (2) max-slippage guard pre-swap (none today!), (3) fill-anomaly detection (fill vs quote delta → breaker), (4) wallet-policy reconciliation at boot (refuse if limits unset), (5) **x402 stub→live flip = founder-only, LAST gate** with contract test + recorded fixture. |

### Track E — API TRANSPLANT (after lab validation)

| Sprint | Deliverable |
|---|---|
| **E1** | Move `local_panel.py` + `voices/` + `coordinator_rules.py` → `gecko-core/orchestration/` (logic in core, never contest_bot). New verdict-shape Literals via `gecko_core.types` + drift test (Pattern A). |
| **E2** | **`POST /v2/trade_research`** (additive) — adds `voices[]` (5 named lenses), `coordinator_rule_fired`, `regime`. `/trade_research` frozen (backward-compat for current skill + frontend). OR additive optional fields on v1 if frontend tolerates (confirm w/ frontend-engineer — cheaper). |
| **E3** | Regenerate `/openapi.json`, notify frontend-engineer (Done checklist contract). Pricing for v2 → business-manager. |

---

## Promotion gate (lab → PRD) — non-negotiable

A voice/strategy change ships to the PRD oracle ONLY when:
1. **Replay harness** (offline, free) shows ≥0 regression on false-bullish-in-chop rate vs incumbent, on identical inputs.
2. **Calibration** improves (confidence→realized-PnL correlation), not just "more trades."
3. **≥2 independent live sessions** improve win-rate or avg-PnL — *one good session is noise* (contest N is tiny; quant-analyst signs the number).
4. The change is **structurally argued**, not curve-fit.

Validatable now: chart v2 confluence, regime classifier, memory cold-start fix.
Speculative until ≥20 closed trades: smart-money lift, exact chop-mode floor.

---

## Critical path / sequencing

```
A0 (fill empty canon) ─┐
D1+D2 (skill-guard CI + self-lint) ─── blocks OKX submit ──┐
                                                            │
A1+A2 (telemetry→Mongo + labeling) ─► B1 (indicators) ─► B2/B3/B4 (voices)
                                                            │
C1 (grid backtest) ──decides──► C2/C3 (regime+grid, or shelve)
                                                            │
D3 (safety belts) ──── blocks capital scale-up ────────────┤
                                                            ▼
              LAB "first running version" validated (promotion gate)
                                                            │
                              E1 (core transplant) ─► E2/E3 (/v2 API + OpenAPI)
                                                            │
                          (founder-only, LAST) x402 stub→live flip
```

**Independent + first:** A0, D1, D2 (no dependencies — start immediately post-contest).
**The API touch (E) is gated on lab validation, not the calendar.**

---

## Capital + safety guardrails (carry over)

- Live capital capped at **$20** until the grid backtest clears + 48h soak passes.
- `X402_MODE=stub` until explicit founder go-ahead (the final gate).
- One knob per cycle; validate on data before promoting (no vibes).
- abstain-not-fabricate + 0.85 chart floor stay intact — the wedge.
- No parallel code-writing agents (git-tangle); implement sequentially or patch-report.

---

## Open questions (resolve before building)

1. **skill-guard runtime:** installable skill (needs agent runtime in CI) vs standalone CLI? Determines if D1 is a script step or containerized agent run.
2. **API v2 path vs additive fields:** if frontend tolerates new optional fields, skip the path bump (cheaper, still backward-compat) — confirm with frontend-engineer.
3. **Grid on thin memes:** C1 backtest will tell us if BOME/TNSR grid bleeds fees. Likely shelve those, grid only PYTH/WIF/DRIFT.

---

## First three things to do when the contest ends

1. **A0** — fill `canon_mauboussin` + `canon_macro` (highest value/effort; closes a hollow-corpus claim).
2. **C1** — grid backtest (one number per symbol kills or confirms the grid leg).
3. **D2** — REVIEWING self-lint + expand the skill description to 80-150 words (cheap, improves the OKX submission score).

Everything else sequences behind these per the critical path.
