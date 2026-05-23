# Yield-Base Sleeve — Step 1 Free-Simulation Results

*2026-05-22. Step 1 of the Pattern B/C gate from `docs/strategy/2026-05-22-yield-base-build-plan.md` §4.
All data pulled live from the `onchainos defi` verbs (CLI v3.2.0, Solana chainIndex 501).
**$0 spent. No transaction signed. No transaction broadcast.** The live trading bot was
stopped (port 8265 free); no conflict.*

---

## Step 1 free-sim verdict: **PASS** (deposit) / **PASS-with-caveat** (redeem)

| Check | Result |
|---|---|
| `defi search` finds a Kamino USDC-lend product on Solana | PASS — id **29130**, Kamino / Main Pool |
| `defi detail` returns APY + token metadata | PASS — 8.19% APY, USDC mint confirmed |
| `defi prepare` returns supported tokens + precision | PASS — USDC accepted, precision 6 |
| `defi deposit` returns **unsigned** deposit calldata for $25 | PASS — decodable, structurally valid |
| Calldata decodes as a real Solana versioned tx | PASS — `solders` parses 753-byte MessageV0 |
| Calldata is UNSIGNED (nothing signed) | PASS — signature slot empty |
| Calldata targets the Kamino klend program | PASS — `to`/programs = `KLend2g3cP87…` (5 klend instrs) |
| Fee-payer = our wallet | PASS — account[0] == response `from` |
| `$25 → minimal units` precision | PASS — 25 USDC → `25000000` (10^6) |
| `defi redeem --ratio 1` returns exit calldata | **CAVEAT** — fails `code=84027 "Failed to build transaction data"** because the wallet holds **no position yet**. Exit calldata is gated on an actual on-chain position; only fully testable in Step 2 (recorded fixture from a funded wallet) or Step 3 (live). Crucially, redeem returns a clean error, **not malformed calldata** — the integration did not silently produce a garbage exit tx. |

**Bottom line:** the deposit path is proven offline for $0 — onchainOS builds a correct,
unsigned Kamino USDC-lend deposit transaction we could hand to the wallet to sign. The
withdraw/exit path could not be falsified at Step 1 because there's nothing to exit; that
validation moves to Step 2/3. This is the expected gate behavior, not a blocker.

The reusable gate script: `scripts/yield/sim_kamino_deposit.py` (offline replay by default,
`--live` to re-fetch). Committed fixtures: `scripts/yield/fixtures/`.

---

## Founder question 1 — Stablecoin choice: USDC vs USDT vs USDG

Live APYs on Solana via `onchainos defi search/detail` (2026-05-22):

| Stable | Best lend/earn product | APY (today) | TVL | Notes |
|---|---|---|---|---|
| **USDC** | Kamino / Main Pool — **LENDING**, id **29130** | **8.19%** | **$142.3M** | Deepest reserve; what we already hold; mint `EPjFWdd5…Dt1v`; 95.45% utilization (drives variability) |
| USDC (alt) | Kamino Main, SINGLE_EARN, id 227050 | 6.55% | $149.1M | Same venue, the "earn" wrapper — lower headline than the lending product |
| USDC (alt) | Jupiter earn, id 41000 | 4.66% | $437.7M | Largest TVL, lowest rate |
| **USDG** | Kamino / Main Pool — **LENDING**, id **29122** | **7.73%** | **$32.5M** | Newer/incentivized; thinner ($32M vs $142M); mint `2u1tszSe…jGWH`; mcap ~$815M |
| USDG (alt) | Kamino Main, SINGLE_EARN, id 29121 | 6.21% | $33.9M | |
| **USDT** | **no LENDING product on Solana** | — | — | Only SINGLE_EARN exists |
| USDT (alt) | Kamino Main, SINGLE_EARN, id 227052 | **3.59%** | $8.0M | mint `Es9vMFrz…wNYB`; mcap ~$3.8B |
| USDT (alt) | Jupiter earn, id 41002 | 2.82% | $21.4M | |

### Recommendation: **USDC, Kamino / Main Pool, investment id 29130** (8.19% base, variable)

Data-backed reasoning:

- **USDC wins on APY *and* depth simultaneously.** 8.19% on a $142M reserve. That is both
  the highest stable lend rate available and by far the deepest pool — depth matters because
  it's what lets us withdraw the reserve on demand without rate impact (the whole point of a
  "deployable-in-<X" reserve).
- **USDT is structurally worse here.** There is **no USDT lending product** on Solana via
  onchainOS — only an earn wrapper at **3.59%** on a thin $8M pool. That's less than half the
  USDC rate, on top of the well-known Tether issuer/reserve-transparency risk. **Reject USDT.**
- **USDG is a credible #2 but not the base.** 7.73% is close to USDC's 8.19%, but the reserve
  is **4.4× thinner** ($32M vs $142M) and USDG is the newest of the three (its rate is
  partly incentive-driven, which can compress without warning). Thinner depth = more
  withdraw-time rate/slippage risk for a reserve we need to pull on a signal. Hold USDG as a
  *split-or-rotate* candidate if USDC utilization compresses its rate below USDG's, not as the
  default base.
- **We already hold USDC** (the bot's working capital), so using it as the base means **zero
  swap cost / zero swap risk** to seed the reserve. Swapping into USDG/USDT to chase a few bps
  would burn the edge on swap fees + slippage.

**Verdict: USDC is the stable base — best rate, deepest, safest issuer, zero swap to enter.**

---

## Founder question 2 — JLP / vaults vs plain USDC-lend: risk-tier classification

This is the most important distinction. **Do NOT blend any of the below into "stable yield."**

### Risk Tier 0 — STABLE FLOOR (the FII-comparison floor; eligible for the reserve)

| Product | id | APY | Why it's floor-tier |
|---|---|---|---|
| Kamino USDC lend (Main) | **29130** | 8.19% | Single-asset USDC supply. **No impermanent loss, no directional exposure, no leverage, no liquidation.** Withdrawable to USDC 1:1 (minus the variable rate already earned). Counterparty = the klend lending program only. |
| Kamino USDG lend (Main) | 29122 | 7.73% | Same shape, thinner pool. Floor-eligible but issuer/depth note above. |
| Kamino PYUSD / USDS lend | 31619 / 33013 | 5.81% / 5.07% | Same single-stable-supply shape; lower rate. Floor-eligible alternatives. |

**This is the only tier that belongs in the "stable yield vs FII" comparison.** Use 29130.

### Risk Tier 1 — VOLATILE / DIRECTIONAL (a SEPARATE higher-risk sleeve — NOT the floor)

| Product | id | APY | Why it is NOT stable yield |
|---|---|---|---|
| **JLP-USDC pool** (Orca V3) | 423354979 | 12.83% | **JLP is the Jupiter perps LP token — you are the counterparty to perp traders' PnL.** This is a DEX_POOL position with **impermanent loss + directional/perp-counterparty exposure**, not a deposit. The headline 12.83% is fee+reward APR, not a stable coupon. **Higher-risk sleeve only.** |
| SOL lend (Kamino Main) | 227048 | 5.81% | Single-asset but **SOL price exposure** — the principal moves with SOL. Not a stable floor. |
| SOL/USDC, cbBTC/USDC, equity-x/USDC DEX pools | 416348165, 552111621, NVDAx/TSLAx/… | 21.9%–119% | LP pools with one volatile leg → **impermanent loss + price exposure**. The eye-popping APRs are IL-bearing fee yields, not stable. Higher-risk sleeve only. |
| "Kamino Multiply / leveraged vault" style | (not surfaced as a stable lend; lives behind leverage products) | — | **Liquidation risk.** Explicitly excluded from the reserve by the build plan (§5: "USDC main reserve only, no kTokens/Multiply/leverage"). |

**Crystal-clear rule for the founder:**
- The **reserve / FII-floor comparison uses Tier 0 only** (USDC lend 29130). No IL, no
  liquidation, withdrawable — that's the honest "park idle USDC" floor at ~3–8%.
- **JLP and the DEX pools are a different product** — a deliberate, separately-sized
  higher-risk sleeve, never a substitute for the stable floor. JLP's 12.83% is **not**
  "USDC yield + a bit more"; it's perp-LP counterparty risk. Quoting it next to the FII
  floor would be the exact kind of yield-washing the build plan warns against.

---

## Founder question 3 — APY stability (rate-chart variability)

`onchainos defi rate-chart --investment-id 29130 --time-range MONTH` (180 hourly-ish samples,
2026-04-22 → 2026-05-22):

| Statistic | Value |
|---|---|
| Min | 4.54% |
| p05 | 4.62% |
| p25 | 5.48% |
| **Median (p50)** | **6.39%** |
| p75 | 7.40% |
| p95 | 10.46% |
| Max | 46.05% (3 short utilization-spike samples > 15%) |
| Mean (excl. spikes) | 6.64% |
| Last 5 samples | 9.61%, 8.02%, 8.62%, 7.35%, 8.48% |

**Read:** the rate lives roughly in a **4.5%–10.5% core band**, median ~6.4%, with brief
utilization-driven spikes above that. This **confirms the "~3–8%, not a promise" framing** —
if anything the realized band over the last month skews to the higher end of it. The rate is
utilization-driven (95.45% utilization right now), so it moves continuously; never quote a
fixed yield. Re-poll APY at sweep time.

---

## What Step 2 and Step 3 need (do NOT do now)

### Step 2 — Recorded-fixture contract test (the `live_cdp`/vcr pattern, Pattern C)
- Already captured (committed under `scripts/yield/fixtures/`): `defi search`, `detail`,
  `prepare`, `deposit` (calldata), `positions` (empty). These become the replay corpus.
- **Missing for full coverage:** a `redeem`/`withdraw` calldata fixture. It cannot be
  recorded until a position exists (Step 3 creates one). So Step 2's redeem assertion is
  blocked on Step 3, OR we record it immediately after the Step-3 deposit confirms.
- Build `tests/test_yield_base_kamino_contract.py` that replays the fixtures and asserts the
  parser extracts `investmentId`, `to`/klend program, `serializedData` decodes, precision.
  Mark the once-off recording `live_kamino`; replay runs offline in CI. **Adding the adapter
  is gated on this test passing** (Pattern C).
- Promote the assertion helpers from `sim_kamino_deposit.py` into a `gecko-core` module
  (`packages/gecko-core/.../execution/yield_base/`) per the "logic in gecko-core" rule; the
  script + test become thin callers.

### Step 3 — Small live smoke ($5–10, FOUNDER-AUTHORIZED only)
- Needs: (a) explicit founder go-ahead (separate from the X402 stub→live flip and separate
  from any change to the running bot); (b) ~$5–10 USDC + a small native SOL gas float in the
  onchainOS wallet (`3HrXPr…JN4i`).
- Sequence: `defi deposit` → `wallet contract-call` (the ONLY step that signs/broadcasts) →
  `defi position-detail` to confirm the position → `defi redeem --ratio 1` → `wallet
  contract-call` → confirm USDC back. **Measure deposit→confirmed and withdraw→confirmed
  latency** — that number sizes the real `ACTIVE_headroom` in the reserve policy (§3 of the
  build plan).
- This is also when we record the redeem fixture for Step 2's full coverage.

---

## Blockers

- **None for Step 1.** Deposit path validated offline for $0.
- **Redeem calldata validation is deferred**, not blocked — it's gated on a real position
  (Step 3) by design. The free-sim correctly surfaced this (clean error, not garbage tx).
- The build-plan referenced a DeFiLlama pool at ~6.1%; the onchainOS-native product (29130)
  reads **8.19% today** and the same number via both `search` and `detail`. We standardize on
  the onchainOS figure since that's the venue we'd actually transact through.

---

## Recommended stable base (one line)

**USDC → Kamino / Main Pool lending, onchainOS investment id `29130`, ~8.19% today
(core band ~4.5–10.5%, median ~6.4%, variable), Tier-0 stable floor, withdrawable, no IL.**

## Sources (all live this session)
- `onchainos defi search/detail/prepare/deposit/redeem/rate-chart/positions`, CLI v3.2.0,
  chainIndex 501 (Solana), 2026-05-22.
- Deposit calldata fixture: `scripts/yield/fixtures/deposit_29130_25usdc.json`
  (`to` = `KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD`, unsigned MessageV0, 5 klend instrs).
- Reusable gate: `scripts/yield/sim_kamino_deposit.py` (replay + `--live`).
