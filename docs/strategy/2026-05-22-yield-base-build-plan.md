# Build Plan — Yield-Base Sleeve (park idle USDC in Kamino Lend)

*2026-05-22. Implements the scope at `docs/strategy/2026-05-22-yield-base-sleeve-scope.md`.
Research + design only. NO mainnet/money-moving code in this doc. The live bot
(PID 2198871, port 8265) and its state/artifact files are out of scope and untouched.*

## TL;DR for the founder
- **Access path: OKX onchainOS `okx-defi-invest` skill (`defi invest`/`withdraw`/`collect`).**
  onchainOS natively exposes Kamino USDC lending and returns unsigned calldata that
  broadcasts through the **same `wallet contract-call` path the live bot already uses
  for swaps**. Lowest custody (TEE keys, no private key in our code), zero new
  wallet/facilitator coupling, neutrality-respecting. Direct Kamino/klend SDK is the
  fallback only if the onchainOS DeFi verb proves unreliable for our reserve.
- **Current Kamino USDC supply APY: ~6.1% base, variable** (DeFiLlama, 2026-05-22:
  6.12% today; 5.66% on 05-20; 6.18% on 05-21 — the swing in 48h is exactly why the
  scope says "3–8%, not a promise"). No reward APY on this reserve; ~$7M reserve TVL.
- **Free simulation IS feasible** without spending money — fetch unsigned calldata from
  `defi invest`/`defi withdraw` and assert its structure offline; never call
  `wallet contract-call`. This falsifies the integration for $0.
- **Value is honest: negligible at $100 (~$3/yr on $50 idle), material at $3–5k
  (~$180–360/yr) + the ρ≈0 Sharpe lift.** At $100 this is plumbing + discipline, not yield.

---

## 1. Access path — recommendation + rationale

### Decision: onchainOS `okx-defi-invest` (primary)

OKX onchainOS ships an `okx-defi-invest` skill: *"DeFi product discovery, deposit,
withdraw, claim rewards"* across **Aave, Lido, PancakeSwap, Kamino, NAVI and hundreds
more.** Kamino USDC lending is in scope. The CLI surface:

| Operation | Command |
|---|---|
| Discover product | `defi search --token USDC --platform Kamino --chain solana` |
| Confirm details | `defi detail --investment-id <id>` |
| Deposit | `defi invest --investment-id <id> --address <ADDR> --token USDC --amount <MINIMAL_UNITS> --chain solana` |
| Position read | `defi position-detail --address <ADDR> --chain solana --platform-id <PID>` |
| Withdraw (full) | `defi withdraw --investment-id <id> --address <ADDR> --chain solana --ratio 1 --platform-id <pid>` |
| Withdraw (partial) | `defi withdraw --investment-id <id> --address <ADDR> --chain solana --amount <MINIMAL_UNITS> --platform-id <pid>` |
| Claim rewards | `defi collect --address <ADDR> --chain solana --reward-type <T> --investment-id <id> --platform-id <pid>` |

Each operation **returns unsigned calldata in `dataList`**; execution is the same
broadcast verb the bot already uses for swaps:
```
onchainos wallet contract-call --to <TO> --chain <INDEX> --input-data <DATA> --value <UI> --biz-type defi
```
Amounts are in **minimal units** (100 USDC, 6 decimals = `100000000`).

**Why this wins (3 reasons):**
1. **Lowest custody.** TEE keys are non-exportable; our code never holds a private key.
   We build/fetch an unsigned tx and hand it to the wallet to sign — exactly the
   pattern `kamino_devnet.py` already enforces ("this module never holds private keys").
2. **Zero new coupling.** `contest_bot/onchainos.py` already wraps
   `wallet contract-call --unsigned-tx` (line 755, `wallet_contract_call`). We add a
   thin `defi_*` method group, no new SDK, no new wallet. Wallet/facilitator neutrality
   preserved — onchainOS is one adapter slot, not a hard dependency.
3. **DeFi venues are PARTNER integrations, not in-house protocol builds** (ownership-tier
   memory). onchainOS owns the Kamino calldata generation + precision handling; we own
   the reserve/active *policy*, never the protocol mechanics.

### Fallback: direct Kamino Lend (klend) SDK / KTX REST

The repo already has `packages/gecko-core/src/gecko_core/execution/kamino_devnet.py`,
which fetches an unsigned base64 deposit tx from **KTX REST** (`/ktx/klend/deposit`) and
leaves signing client-side. If the onchainOS `defi invest` verb is missing/unreliable for
our reserve, we extend that adapter to mainnet (a NEW path, gated — see §4) and broadcast
the KTX-built tx through the same `wallet contract-call`. **This stays the fallback** —
it adds a second source-of-calldata to maintain and is less neutral (KTX-specific). Recommend
onchainOS first; keep KTX as the proven backup since its unsigned-tx shape is already coded.

### Not the SendAI agent-kit path (for v1)
SendAI's kit can do Kamino, but it would mean a second execution stack alongside onchainOS
and a key-handling model to vet. The bot's whole live path is onchainOS; staying on it is
the smaller, more-auditable surface. Revisit only if onchainOS DeFi proves a dead end.

---

## 2. APY reality (cite + date)

| Metric | Value | Source / date |
|---|---|---|
| Kamino USDC supply APY (base) | **6.12%** | DeFiLlama yields API, pool `d2141a59…`, 2026-05-22 03:01 UTC |
| Same pool, 24h prior | 6.18% | 2026-05-21 23:01 UTC |
| Same pool, 48h prior | 5.66% | 2026-05-20 23:01 UTC |
| Reward APY | none | (no KMNO incentive on this reserve currently) |
| Reserve TVL | ~$7.0M | DeFiLlama, 2026-05-22 |
| Broader Kamino USDC main-market | 5–12% strategy-dependent | OKX Learn / Kamino, May 2026 |

**Read:** ~6% base, swinging ~0.5pp in 48h — utilization-driven, exactly the
variable rate the scope warns about. Treat 3–8% as the planning band; never quote a
fixed yield to anyone. Re-poll the live APY (DeFiLlama or `defi detail`) at sweep time;
don't sweep into a compressed rate if a better idle option exists.

---

## 3. Reserve/active split design

### Tranches (one wallet, two logical buckets at $100; two wallets at $3–5k)
```
wallet_usdc_total
├── ACTIVE  = USD_PER_TRADE × MAX_CONCURRENT + headroom_buffer   (NEVER swept)
└── RESERVE = max(0, wallet_usdc_total − ACTIVE − min_gas_float) (swept to Kamino)
```
Live bot today: `USD_PER_TRADE=45`, `MAX_CONCURRENT=2`, `MAX_BUDGET_USD=100` →
ACTIVE ≈ $90. At $100 that leaves ~$10 reserve = noise (the honest part). The design
must hold at $3–5k where ACTIVE stays ~$90–180 and RESERVE becomes the bulk.

### The "deployable in < X" rule (drives reserve-only)
- The bot polls on a cadence (poll loop). A Kamino withdraw is **one tx, must
  sign+broadcast within 60s, confirms in seconds** — but that still risks missing a
  fast breakout that fires *this* poll.
- **Rule:** only sweep capital that passes "not needed within the next `N` poll cycles."
  Concretely: `RESERVE = total − ACTIVE_committed − ACTIVE_headroom`, where
  `ACTIVE_headroom` covers the worst-case number of new entries that can fire before a
  withdraw can settle. At current poll cadence, size headroom = `1 extra USD_PER_TRADE`
  so a single fresh signal never has to wait on Kamino.
- **Never park the active tranche.** Momentum needs instant capital; the reserve is only
  the genuinely-idle remainder.

### Withdraw-on-signal
- If active runs short (a signal fires but committed active is exhausted), the bot
  *prefers to abstain* rather than block on a withdraw (matches the conservative,
  participation-first posture). A withdraw-then-enter path is a v2 option, explicitly
  gated, only once latency is measured live and we trust the 60s window.
- Withdraw is also the scheduled path: at a chosen cadence (or on a chop→trend regime
  flip) top active back up from reserve.

### Dynamic split — "in chop → sweep more" (recommend dynamic, simple form)
The scope's elegant idea: in chop the bot declines entries → capital sits idle → sweep
more to yield. Implement as a **regime-aware reserve target**, not a continuous controller:
- `TREND` regime (or open positions near max): reserve target = baseline (keep full active headroom).
- `CHOP` regime sustained `M` cycles with 0 open positions: raise reserve target (sweep
  the would-be-active capital, since it's earning 0% while abstaining).
- Hysteresis: only re-sweep / re-pull on a *sustained* regime flip (avoid tx churn — each
  sweep/pull is an on-chain tx with cost + the 60s window). Min dwell time between sweeps.

Keep v1 a **fixed conservative split** (e.g. ACTIVE = committed + 1× headroom, rest to
reserve) and ship the dynamic regime-aware target as v1.1 once we've watched real chop
periods. Dynamic is the prize but needs live regime data to tune `M`/hysteresis.

### Profit sweep (the vault)
- On `close_position` with realized PnL > 0, the *realized USDC profit* flows to the
  RESERVE target on the next sweep tick — it compounds in Kamino. This is the "vault" the
  founder grows with ~2k BRL/month. Losses simply reduce what's available to sweep; no
  special handling.
- Sweep is **batched on a tick**, never per-trade (per-trade sweeps = tx spam + 60s-window
  exposure on every close). One reconciliation pass per `K` poll cycles: compute target
  reserve, compare to on-chain Kamino position, deposit/withdraw the delta if it exceeds a
  min-sweep threshold (e.g. don't sweep < $5 — tx cost would dominate).

### Scale-up shape ($3–5k)
Per the scope's architecture-fit: at multi-wallet stage the reserve becomes its **own
wallet/sleeve** (one wallet = momentum, one = yield/vault) via the `WalletHandle` +
strategy-instance abstraction. The policy code written now (target computation, sweep
reconciler) is wallet-agnostic — it takes a balance + a deposit/withdraw adapter, so the
single-wallet-two-tranches v1 and the two-wallet v2 share the same core.

---

## 4. Build sequence — the Pattern B/C gate

`kamino_devnet.py` is **devnet-sim only and refuses mainnet custody.** A live deposit is
a NEW mainnet path, NOT a flip of that adapter. Three steps, in order; money only at step 3.

### Step 1 — Free local simulation (no money, falsifiable) — gecko-core, not the live bot
**Goal:** prove we can build correct deposit/withdraw calldata and round-trip the policy
math, spending $0 and touching no live wallet.

Tasks:
1. New module `packages/gecko_core/execution/yield_base/` (lives in core per the
   "business logic in gecko-core" rule; the bot only consumes a thin adapter).
2. `reserve_policy.py` — pure functions: `compute_active_floor(per_trade, max_concurrent, headroom)`,
   `compute_reserve_target(total, active_floor, gas_float, regime, open_positions)`,
   `compute_sweep_delta(target, current_kamino, min_sweep)`. **Pure, no I/O — unit-test
   directly** (light-fakes pattern; no run_post_processors-style over-simulation).
3. `kamino_invest_sim.py` — fetch unsigned calldata via `defi invest`/`defi withdraw`
   in **dry-run/quote mode** (or KTX REST unsigned-tx, reusing `fetch_unsigned_deposit_tx`)
   and assert structure: non-empty `dataList`/`transaction`, decodable, correct `to`,
   amount in minimal units matches input. **Never call `wallet contract-call`.** This is
   the eth_call-style local falsifier the scope demands.
4. `--amount` precision tests: 100 USDC ↔ `100000000`, fractional rounding, dust handling.

Exit gate: policy math unit-tested; unsigned-calldata builder produces a structurally
valid (but unsigned, un-broadcast) deposit + withdraw tx for a sample reserve. Reviewable
by defi-engineer + solana-architect. **No private key, no broadcast, no $.**

### Step 2 — Recorded-fixture contract test (the `live_cdp`/vcr pattern)
**Goal:** lock the wire shape against onchainOS's real `defi` responses so a future CLI
change can't silently break us.

Tasks:
1. Capture real (read-only) responses once: `defi search`, `defi detail`,
   `defi invest` (the calldata-returning call, NOT broadcast), `defi position-detail`,
   `defi withdraw` (calldata-returning). Store as fixtures (vcr-style), redacted of any
   wallet/secret.
2. Contract test `tests/test_yield_base_kamino_contract.py` replays fixtures and asserts
   our parser extracts `investment-id`, `platform-id`, `dataList`, `to`, decimals, minimal
   units. Mark `live_kamino` for the once-off recording; replay runs offline in CI.
3. Per Pattern C: **adding the adapter is gated on this contract test passing.** Replays
   the real facilitator's relevant endpoints, not a stub.

Exit gate: contract test green offline; fixtures committed (redacted). This is what
catches the "tests exercise stubs not real wires" failure (Pattern C).

### Step 3 — Small live smoke ($5–10, FOUNDER-AUTHORIZED, final verification only)
**Goal:** one real deposit + one real withdraw of a tiny amount, end-to-end, as the LAST
check — never the primary debug tool (Pattern B).

Tasks (only after founder explicit go-ahead — separate from the X402 flip, separate from
the live bot):
1. Deposit $5–10 USDC into the Kamino USDC reserve via `defi invest` → `wallet contract-call`.
2. Confirm via `defi position-detail` the position exists; read accrued (will be ~$0 instantly).
3. Withdraw full (`--ratio 1`) → confirm USDC back in wallet; **measure deposit→confirmed
   and withdraw→confirmed latency** (drives the real `ACTIVE_headroom` sizing in §3).
4. Record latency + tx hashes in a smoke note. Tear down (leave 0 in reserve) unless
   founder wants to leave the dogfood position open.

Exit gate: round-trip works on mainnet at $10; measured latency validates (or revises) the
"deployable in < X" rule. Only then consider wiring the sweep reconciler to the live bot —
and that wiring is its own founder-gated decision (it touches the running bot's capital).

**Hard boundary for all 3 steps:** none of this modifies the running live bot (PID 2198871)
or its state. Steps 1–2 are pure gecko-core + tests. Step 3 is a standalone smoke script
run by the founder, not an edit to the bot loop. Wiring into the bot is a *fourth*,
separately-authorized step outside this plan.

---

## 5. Risks + mitigations

| Risk | Severity | Mitigation |
|---|---|---|
| Kamino program (smart-contract) risk | Med | Largest, most-audited Solana lender; USDC main reserve only (no kTokens/Multiply/leverage); cap reserve exposure; non-zero residual — accept consciously. |
| USDC depeg | Med (systemic) | Unhedgeable here; keep a min gas float in native SOL; size reserve so a depeg is survivable not ruinous; v1 at $100 it's noise. |
| Withdraw latency missing a breakout | Med | The reserve-only rule + `ACTIVE_headroom` ≥ 1 extra entry; prefer abstain over block-on-withdraw; measure real latency in Step 3 before trusting withdraw-on-signal. |
| Variable APY compresses | Low | 3–8% planning band, never a fixed quote; re-poll APY at sweep; the Sharpe/ρ≈0 benefit holds even at low APY. |
| onchainOS `defi` verb changes/unreliable | Med | Pattern C contract test catches wire drift; KTX REST unsigned-tx fallback already coded in `kamino_devnet.py`. |
| 60s Solana tx-expiry window | Low | Build→sign→broadcast in one tight path; batch sweeps off the hot poll loop; retry on expiry, never auto-retry a possibly-landed tx without a position-detail re-read. |
| Tx-cost churn from over-sweeping | Low | Min-sweep threshold ($5), hysteresis + dwell time on the dynamic split, batched reconciliation not per-trade. |
| Stranded position on partial failure | Med | Always re-read `position-detail` after any deposit/withdraw before acting again (mirrors the bot's `bal>0` exit-swap lesson). |

---

## 6. Capital-staged value (honest)

| Stage | Idle USDC | ~Yield @6% | Real point |
|---|---|---|---|
| **Now ($100)** | ~$50 | ~$3/yr | Plumbing + discipline. Yield is noise. Dogfood the round-trip. |
| **$3–5k** | ~$2.5–4k idle (rest active) | ~$150–240/yr | Material; the ρ≈0 diversification Sharpe (~1.4–1.6×) is the real prize, not the coupon. |
| **+2k BRL/mo → vault** | growing | compounding | The Kamino reserve IS the profit vault; future opt-in vault-privacy attaches here. |

Don't oversell the $100 stage. Build it now for the *capability*; the returns case is the
$3–5k stage + the diversification math, which the quant review already validated.

---

## 7. Open questions for the founder (3 decisions)

1. **Capital split.** v1 fixed split (ACTIVE = committed + 1× `USD_PER_TRADE` headroom,
   rest → reserve), or go straight to the dynamic "in chop → sweep more" target?
   *Recommendation:* fixed in v1, dynamic in v1.1 after watching real chop periods —
   dynamic needs live regime data to tune dwell/hysteresis.
2. **Access path confirmation.** Confirm onchainOS `okx-defi-invest` as primary (vs the
   KTX/klend direct fallback). Needs the founder to verify the `defi` subcommands exist in
   the installed `onchainos` CLI v3.2.0 (the skill repo documents them; our CLI build may
   differ). *Recommendation:* onchainOS primary, KTX REST as the proven backup.
3. **Risk tolerance / authorization.** (a) Max % of wallet in the Kamino reserve at the
   $3–5k stage. (b) Explicit go-ahead for the Step-3 $5–10 live smoke — separate from the
   X402 stub→live flip and separate from any change to the running live bot.

---

## Appendix — what's already in the repo (starting points)
- `packages/gecko-core/src/gecko_core/execution/kamino_devnet.py` — devnet-sim adapter;
  proves the unsigned-tx pattern (KTX `/ktx/klend/deposit` → base64 → client signs).
  Refuses mainnet. The fallback path extends from here.
- `contest_bot/onchainos.py:755` `wallet_contract_call(to, unsigned_tx)` — the TEE
  sign+broadcast verb; the live deposit/withdraw broadcasts through this exact path.
- `contest_bot/onchainos.py` `swap_execute`, `get_all_balances`, `get_token_balance` —
  the balance reads the reserve policy needs as inputs.
- Live bot capital config: `USD_PER_TRADE=45`, `MAX_CONCURRENT=2`, `MAX_BUDGET_USD=100`
  in `jto_breakout_gecko_gated_contest_bot.py` — the ACTIVE-floor inputs.

## Sources
- OKX onchainOS skills (DeFi invest/withdraw/collect, Kamino supported):
  https://github.com/okx/onchainos-skills/blob/main/CLAUDE.md and
  https://github.com/okx/onchainos-skills/blob/main/skills/okx-defi-invest/SKILL.md
- Kamino USDC supply APY (6.12% on 2026-05-22, variable): DeFiLlama yields API,
  pool `d2141a59-c199-4be7-8d4b-c8223954836b`
  (https://defillama.com/yields/pool/d2141a59-c199-4be7-8d4b-c8223954836b)
- OKX Learn — Solana lending protocols / Kamino:
  https://www.okx.com/en-us/learn/solana-lending-protocols
