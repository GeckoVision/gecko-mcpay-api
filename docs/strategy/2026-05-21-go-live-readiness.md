# Go-Live Readiness — first real oracle-gated execution

*2026-05-21. The bot runs LOCALLY (not deployed); it calls the DEPLOYED oracle
(`api.geckovision.tech/trade_research`, stub payment, $0, real grounded
verdicts). "First real execution" = the OKX swap is real USDC; the oracle call
stays stub. This is the checklist to flip from paper to live safely.*

## What "live" means here

The bot is **conservative by design**: it abstains in chop, requires a clean
momentum setup (chart ≥ 0.85, regime not-chop), caps at `MAX_DAILY_TRADES=3`,
`MAX_CONCURRENT=2`, `USD_PER_TRADE=45`, `MAX_BUDGET_USD=100`. Going live means
the bot is **armed and waiting** — the first real trade may take hours until a
setup appears. The oracle adds a soft gate: a `pass` verdict blocks an entry.

## Two money axes (keep them straight)

| Axis | State | To go live |
|---|---|---|
| **Oracle x402 call** | **stub ($0)** — stays stub per `project_x402_stub_then_live` | nothing — stays stub |
| **OKX swap execution** | **paper** (`PAPER_TRADE=True`) | the flip below — real USDC |

Only the swap axis flips. The oracle stays free.

## Pre-flight checklist (all must be ✅ before the flip)

- [ ] **Paper demo green** — oracle preloads real verdicts, studio shows the
      Oracle panel, soft-gate fires on `pass`, no traceback. (S41 T4.)
- [ ] **Wallet funded** — the OKX onchainOS wallet holds enough USDC for ≥3
      trades + gas. `USD_PER_TRADE=45 × MAX_CONCURRENT=2 = $90` deployed +
      headroom → **fund ~$100 USDC + a little SOL for gas/ATAs.** Confirm with
      `onchainos wallet balance --chain solana`.
- [ ] **OKX policy limits set** — set a per-tx + daily cap on the agent wallet
      at/above our config (`singleTxLimit ≥ $45`, daily ≥ $135) so the platform
      is a backstop to our own caps.
- [ ] **Config sane** (already paper-safe defaults): `USD_PER_TRADE=45`,
      `MAX_CONCURRENT=2`, `MAX_BUDGET_USD=100`, `MAX_DAILY_TRADES=3`,
      `STOP_LOSS_PCT=3`, `TAKE_PROFIT_PCT=4`, trail activate +2% / give-back 1%.
- [ ] **Founder present** for the first armed run (watch the first real fill).
- [ ] **Explicit "go live"** — the flip is a deliberate, confirmed action.

## The flip (only after the checklist)

1. In `contest_bot/jto_breakout_gecko_gated_contest_bot.py` (or `config.py` in
   the skill), set `PAPER_TRADE = False`.
2. Start the bot locally:
   `cd contest_bot && set -a; . ../.env; set +a; python3 -u jto_breakout_gecko_gated_contest_bot.py`
   (it will print a live-mode confirmation gate requiring a typed `CONFIRM`).
3. Open `http://localhost:8265` — watch the Oracle panel + Agent Voices + the
   first armed decisions. The first real swap fires only on a clean setup.

## Kill switch / monitoring

- Ctrl+C stops the bot; positions persist in `bot_state.json` (reboot resumes).
- The circuit breaker halts entries after consecutive losses.
- Watch real-fill PnL on the dashboard (computed from actual swap `to_amount`,
  not oracle price — the iter-3.7 accounting fix).

## What I will NOT do autonomously

Flip `PAPER_TRADE=False`, fund the wallet, or set live x402. Those move real
money and need the founder's explicit confirm + presence. Everything up to the
flip (wiring, paper validation, this checklist) is done for $0.
