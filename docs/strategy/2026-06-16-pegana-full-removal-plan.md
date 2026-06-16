# Pegana Full-Removal Plan (roadmap — not yet scheduled)

**Status:** DEFERRED to a future sprint. Pegana stays wired for now (free,
no-auth, fail-OPEN). This doc is the executable plan for when we decide to own
peg-integrity end-to-end.

**Goal:** Replace `gecko_core.sources.pegana.PeganaClient` entirely with
in-house peg-risk detection, so the pre-trade safety gate and the vault
safety-monitor no longer depend on the third-party `api.pegana.xyz` (a single
v0.1.0 startup API = a single point of failure).

**Why eventually do it:** Peg-integrity is a sub-case of decision-integrity (our
wedge). Owning the signal end-to-end is on-brand and removes an external SPOF.
It is NOT the wedge's center of gravity (manipulation / Information-MEV is), so
this is a hardening task, not a priority.

---

## What Pegana does for us today (the thing to replace)

One call — `PeganaClient.depeg_risk_by_mint(mint)` — returns a `DepegRisk`
(`state`, `is_pegged`, `discount_abs`, `stale`, `risk_off`) for **both**
stablecoins and LSTs. Wired in:

- `packages/gecko-core/src/gecko_core/orchestration/trade_panel/safety_check.py`
  — `_fetch_depeg(...)` (~L465), called best-effort/fail-OPEN; result lands on
  `SafetyBlock.depeg_risk` + `SafetyBlock.peg_status` (models.py ~L293-305).
- The `/safety` fast endpoint treats `depeg_risk` as a **block** flag
  (`gecko_api/main.py` `_safety_gate`: `flags & {"fake_market_cap","depeg_risk"}`).
- Consumed wherever `evaluate_contract_safety` runs (pre-panel injection +
  vault monitor).

The real value Pegana adds is **class-aware calibration** (an LST at a 2%
discount is healthy — unstaking delay; USDC at 2% is a crisis). The arithmetic
is trivial; the per-class thresholds are the IP.

---

## Three pieces, by difficulty

### Phase 1 — Stablecoin depeg (TRIVIAL, ~hours)
Stablecoins peg to a fiat target (almost always $1.00). Depeg = `|market - 1.00|`.
We already have the market price feed (GeckoTerminal / Jupiter, keyless).

- **New:** `gecko_core/sources/stable_depeg.py` — `StableDepegClient` (or a pure
  function `assess_stable_depeg(mint, market_usd) -> DepegRisk`).
  - Maintain a small **known-stablecoin registry**: `{mint -> (symbol, peg_target)}`
    for USDC, USDT, USDe, USDS, PYUSD, FDUSD, DAI(if bridged), USDG, etc.
    (Pattern A: one canonical module; add a `ProviderKind` if it becomes a chunk
    source. It is a structured data provider, NOT a RAG source — do not register
    with the embedding dispatcher, same as pegana.py.)
  - `discount = (peg_target - market_usd) / peg_target` (signed; report `abs`).
  - Thresholds (calibrate, start conservative): `> 0.5%` = drift/elevated,
    `> 2.0%` = depeg/risk_off. Stables have tight bands — unlike LSTs.
  - Reuse the existing market-price read in `safety_check.compute_manipulation_signals`
    (we already fetch `market_usd` there) so no extra network call.
- **Return the SAME `DepegRisk` shape** (or a shared peg-result dataclass) so the
  safety gate is source-agnostic.
- **Tests:** USDC at $1.00 → pegged; USDC at $0.97 → risk_off; unknown mint →
  None (not a tracked stable). vcr-style with a MockTransport price feed.

### Phase 2 — LST peg (MEDIUM, ~1–2 days)
LSTs (jitoSOL, mSOL, JupSOL, bSOL, INF, ...) peg to their **intrinsic NAV**, not
$1.00. `discount = (intrinsic_usd - market_usd) / intrinsic_usd`, where
`intrinsic_usd = sol_per_lst × SOL/USD`.

- **Primary source — Sanctum `sol_value` API** (canonical Solana LST aggregator,
  covers ~all LSTs): `GET sanctum API → sol_value per LST mint`. One dependency,
  broad coverage. (Verify current endpoint + shape at build time.)
- **Fallback — SPL stake-pool RPC read** via our existing Helius/QuickNode RPC:
  for SPL-stake-pool-program LSTs, `sol_per_lst = total_lamports / pool_token_supply`
  from the pool state account. One formula covers the majority; Sanctum-Infinity
  / non-standard pools differ (lean on Sanctum for those).
- SOL/USD from Pyth (we already ingest oracle prices) or GeckoTerminal.
- **New:** `gecko_core/sources/lst_nav.py` — `LstNavClient` →
  `assess_lst_depeg(mint) -> DepegRisk`.
- **Tests:** jitoSOL at NAV → pegged; jitoSOL at a 5% discount (drained pool) →
  risk_off; respect class-aware threshold (see Phase 3).

### Phase 3 — Class-aware thresholds (the real IP, ~1 day of calibration)
A per-class threshold table so we don't false-positive healthy LSTs:

| Class | Normal band | Elevated | Depeg |
|---|---|---|---|
| Fiat stablecoin | ±0.3% | >0.5% | >2.0% |
| LST (liquid) | ±1.0% | >2.0% | >5.0% |
| LST (illiquid / long unstake) | ±2.0% | >4.0% | >8.0% |

- Calibrate from historical Pegana readings while it's still wired (capture
  `discount` per asset over a few weeks → empirical normal bands). This is the
  one place to do real work, not guess.
- Single canonical thresholds module (Pattern A) + a drift test.

### Phase 4 — Routing, cutover, delete Pegana
- In `safety_check._fetch_depeg`: route by asset class —
  known stablecoin mint → Phase 1; known LST mint → Phase 2; else → None
  (today's non-peg behavior). Keep fail-OPEN throughout.
- Keep the `DepegRisk` / `SafetyBlock.depeg_risk` / `peg_status` shape identical
  so `/safety` `_safety_gate`, the panel injection, and the vault monitor need
  ZERO changes downstream (Pattern: stable interface, swap the source).
- Delete `gecko_core/sources/pegana.py` + its tests + the `PeganaClient` import
  in `safety_check.py`. Grep `pegana` → 0 hits in `packages/`.
- Update `docs/` references; drop the Pegana mention from the safety-read prose.

---

## Critical files

| File | Action |
|---|---|
| `packages/gecko-core/src/gecko_core/sources/stable_depeg.py` | NEW (Phase 1) |
| `packages/gecko-core/src/gecko_core/sources/lst_nav.py` | NEW (Phase 2) |
| `packages/gecko-core/src/gecko_core/sources/peg_thresholds.py` | NEW (Phase 3, canonical) |
| `packages/gecko-core/src/gecko_core/orchestration/trade_panel/safety_check.py` | MODIFY `_fetch_depeg` routing; drop `PeganaClient` import (Phase 4) |
| `packages/gecko-core/src/gecko_core/sources/pegana.py` | DELETE (Phase 4) |
| `packages/gecko-core/tests/.../test_okx_*`-style contract tests | NEW per source |
| `gecko_api/main.py` `_safety_gate` | NO CHANGE (interface preserved) |

## Verification (end-to-end)
1. Phase 1: `assess_stable_depeg` on USDC/USDT at peg → pegged; off-peg → risk_off; unknown mint → None.
2. Phase 2: `assess_lst_depeg` on jitoSOL/mSOL → matches Sanctum `sol_value` within tolerance; drained-pool fixture → risk_off.
3. Phase 4: live `gecko_trade_research` on an LST mint → `safety.depeg_risk` populated WITHOUT Pegana in the call path; `git grep pegana packages/` = 0.
4. Reachability (Pattern E): the depeg flag still reaches the `/safety` gate + the panel — direct end-to-end test, not per-layer only.

## Risks / notes
- **Sanctum = a new single dependency** for LSTs. Mitigate with the SPL
  stake-pool RPC fallback so we degrade, not fail, if Sanctum is down.
- **Calibration is the hard part** — capture Pegana's readings BEFORE removal to
  ground the thresholds empirically. Removing Pegana before calibrating would
  ship guessed bands (the exact false-positive trap Pegana avoids).
- Keep everything **fail-OPEN** — a peg read failing must never block a verdict.
- `X402_MODE=stub`, PAPER, no live flips — unchanged by this work.
