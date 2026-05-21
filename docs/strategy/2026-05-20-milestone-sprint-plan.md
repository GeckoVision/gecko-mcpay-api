# Milestone Sprint Plan — toward 2000 BRL balance, then recurring income

*2026-05-20. Founder goal: grow total account balance to 2000 BRL (~$370)
first, then build toward recurring monthly income. Fund the wallet to
accelerate; treat funded capital as tuition until the agent is proven
autonomous. Continuous improvement per sprint — the bot evolves, it does
not arrive finished.*

---

## North star

```
Phase 1 (NOW)      → PROVE: a bot trustworthy enough to run unattended 48h
Phase 2 (weeks)    → GROW:  balance milestone 500 → 1000 → 2000 BRL
Phase 3 (months)   → DIVERSIFY: 3-bucket risk ladder, reduce single-strategy risk
Phase 4 (later)    → INCOME: scale capital to where 2000 BRL/mo is structural
```

The lever for a **balance milestone** is capital + steady execution.
The lever for **recurring income** is capital scaled to the liquidity
ceiling + the oracle sold as a service. The daily % is already near its
sane ceiling (~0.5%); do not chase a higher daily rate — chase volume and
reliability.

---

## The honest math (anchored 2026-05-20)

- Live result day 1: **+1.16% / +$1.05** real (OKX wallet), heavy manual help
- Realistic sustained unattended: **+0.2% to +0.5%/day** average, with down days
- Quant median: +0.6%/day, P10-P90 [-2.5%, +5.5%] — plan around the median

**Time to 2000 BRL (~$370) total balance, by funding level:**

| Fund to | Gap | +0.5%/day | +1%/day (aggressive) |
|---|---|---|---|
| $100 | 3.7× | ~8.7 months | ~4.4 months |
| $200 | 1.85× | ~4 months | ~2 months |
| $300 | 1.23× | ~6 weeks | ~3 weeks |

**Aggressive ≠ higher expected return — it's higher variance.** Bigger
tickets widen the outcome cone, they don't raise the mean (quant, verified).
The reliable accelerator is funding, not the risk dial.

---

## Phase 1 — PROVE (now → bot trustworthy unattended)

**Exit criterion:** bot runs 48h unattended with zero manual intervention,
honest dashboard, no stranded positions, no silent failures.

Bugs fixed 2026-05-20 (all were paper-invisible, live-only):
- artifact-replay resurrecting closed positions
- `--biz-type` stale swap CLI arg
- AccountNotFound (no SOL for gas/ATAs)
- get_token_balance nested-response (stranded PYTH)
- oracle-price PnL accounting (inflated 3.5×)
- budget-cap not decrementing on close

Remaining Phase-1 hardening (sprint backlog):
- [ ] flat-stall exit: positions open >Xh at ~0% should free the slot
- [ ] dashboard "Per trade $25" hardcoded string → read USD_PER_TRADE
- [ ] FundamentalsOracle parallel-preload rate-limit (serialize)
- [ ] reboot script as a single `restart.sh` (kill-by-name + env + CONFIRM pipe)
- [ ] 48h unattended soak test before adding meaningful capital

**Capital during Phase 1:** keep small ($100-200). This is tuition.

---

## Phase 2 — GROW to balance milestones

**Fund target: ~$200-300** (≈ 1,100-1,600 BRL). At $300, 2000 BRL is
weeks away, and the capital is still small enough that meme liquidity edge
is fully intact.

**Locked settings during the grow phase** (do NOT tune for "more
aggressive" — variance ≠ return):

```
USD_PER_TRADE          $45      (≤ OKX singleTxLimit $50 with buffer)
MAX_CONCURRENT         2
MAX_DAILY_TRADES       3
TAKE_PROFIT_PCT        4        (matches ~2% natural oscillation + headroom)
STOP_LOSS_PCT          3
TRAIL_ACTIVATE_AFTER   2
TRAIL_STOP_PCT         1
STALL_GREEN_EXIT       60min + 2%
chart_floor            0.85     (the wedge — do not lower for more entries)
```

**Weekly checkpoints:**
- Reinvest gains (compound, don't withdraw) until $370+
- Each week: review the artifact log, count win/loss, check real wallet
  PnL vs dashboard (must match now), note any new failure mode
- One knob per sprint if a clear failure mode emerges (per
  `feedback_prompt_iteration_plateau` — logic in code, not prompt)

**Milestone ladder:**
- 500 BRL (~$93): basically funded — focus on unattended reliability
- 1000 BRL (~$185): first real compounding checkpoint
- 2000 BRL (~$370): Phase 2 complete → begin diversification

---

## Phase 3 — DIVERSIFY (the "no eggs in one basket")

Risk-laddered allocation once balance ≥ 2000 BRL:

| Bucket | % | What | Role |
|---|---|---|---|
| 🔴 Active | 20-30% | meme momentum bot (this) | growth, you babysit |
| 🟡 Copy-trade | 20-30% | mirror proven OKX smart-money wallets | semi-passive alpha |
| 🟢 Yield/lending | 40-50% | Kamino/Marginfi USDC lending | stable floor |

The green bucket makes income *stable*; the red bucket makes it *grow*.
Build the copy-trade + yield buckets as roadmap sprints (they reuse the
same OnchainOS skills the bot already calls).

---

## Phase 4 — INCOME (structural 2000 BRL/mo)

Only reachable with real capital. Capital needed for 2000 BRL/mo:

| Strategy | Sustainable return | Capital needed |
|---|---|---|
| Active trading | ~5-8%/mo (good months) | ~$5,000 |
| Copy trading | ~3-6%/mo | ~$7,500 |
| DeFi lending | ~8-15%/yr | ~$35,000 |

Plus the real product lever: **the oracle sold as a service** (per-call
x402 revenue), which scales without your own capital at risk.

---

## Guardrails (non-negotiable)

- Fund only tuition-level capital until the 48h soak test passes
  (`feedback_okx_no_funding_pressure`)
- No eggs in one basket — diversify by Phase 3
- Variance ≠ return — don't crank risk for a balance milestone
- Honest accounting always — dashboard must match the OKX wallet
- One knob per sprint — continuous improvement, not lurching
- The wedge stays intact — chart_floor 0.85, abstain-not-fabricate

---

## Continuous improvement cadence

Each sprint: dogfood the bot → identify the binding constraint (a failure
mode or a missed-opportunity pattern) → one targeted change → soak test →
promote winners to the PRD oracle (`local_lab_strategy`). The bot is a
proof artifact that feeds the real product; every lab improvement that
survives gets transplanted to the oracle others pay to call.
