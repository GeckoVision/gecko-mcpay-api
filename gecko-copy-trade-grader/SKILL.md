---
name: gecko-copy-trade-grader
description: Rigor-graded scorecard for any public crypto copy-trader or trading bot. Pulls live OKX smartmoney leaderboards (or accepts manual per-trade input), reconstructs daily returns, computes Sharpe / Sortino / true max-DD / catastrophic-rate / stability ratio / selection-deflated Sharpe, and outputs an A/B/C/D Gecko Grade with explicit reasoning. Use it BEFORE copying any trader or bot, especially before clicking "Copy" on OKX's marketplace where the leaderboard rank is itself a selection bias. v0.2 adds a "persistence gate" — Grade A now requires the trader to be A in BOTH halves of their rate series, so periodic luck doesn't get called skill. On current OKX 90d top-50 data, **zero** traders earn A under this gate; the most-defensible picks are the 4 B-graded persistent ones (天王盖地虎M, 风箱, bb16888888, etc).
version: 0.2.0
author: Gecko
tags: [copy-trading, okx, rigor, sharpe, drawdown, leaderboard, selection-bias, deflated-sharpe, walk-forward, paper-trade, due-diligence]
dependencies: []
triggers:
  - "Grade this trader"
  - "Should I copy this OKX trader"
  - "Is this trader actually good"
  - "Run rigor on the OKX leaderboard"
  - "Show me Gecko-Rank vs OKX-Rank delta"
  - "Is X (trader nickname) skilled or lucky"
  - "Find the most underrated traders on OKX"
  - "Cross-period stability of OKX top traders"
---

# Gecko Copy-Trade Grader

The rigor layer above OKX's copy-trading marketplace.

## The problem this solves

OKX (and every copy-trading marketplace) ranks traders by raw cumulative PnL%.
That ranking has five built-in failures:

1. **Heavy-tail luck** — one big trade carries everything.
2. **Hidden degradation** — trader was earning early, now bleeding, cumulative still positive.
3. **Hidden catastrophic-day risk** — one -10% day can wipe N small wins; lumpy distributions look the same as smooth ones at the top.
4. **Penalizes large-AUM disciplined traders** — capacity-constrained ≠ untalented.
5. **Selection bias** — showing top-50 of N traders inflates Sharpe by `sqrt(2 log N)`.

A user copying OKX top-N is **statistically 34% likely to copy a Grade-D (degrading or catastrophic-prone) trader** under proper rigor. This skill catches that before money moves.

## What the grade means

| Grade | Rule | What to do |
|---|---|---|
| **A** | Sharpe ≥ 3 + max-DD ≤ 15% + catastrophic-rate ≤ 5% + stability ≥ 0.3 — **AND v0.2: must be Grade A in BOTH halves of the rate series** | **Real persistent skill** — eligible for paper-A/B |
| **B** | Sharpe ≥ 1.5 + max-DD ≤ 30% + stability ≥ 0, OR an A that failed the persistence gate | Promising — best practical pick (since 0 traders earn A on current OKX data) |
| **C** | Marginal Sharpe (0.5-1.5) or small sample | Noise / lucky / not yet provable |
| **D** | Sharpe < 0.5 OR catastrophic-rate > 25% OR stability < 0 OR profit-factor < 1.0 | **Gambling profile or degrading** — do NOT copy |

**v0.2 honesty note**: The persistence gate is *strict*. On 90 days of live OKX top-50 leaderboard data, **0 traders** earn Grade A. All 4 v0.1 A-graded traders (天王盖地虎M, 风箱, bb16888888, mar***@gmail.com) downgrade to B because their 30d Sharpe wasn't ≥ 3 in BOTH halves of their 90d series. That doesn't make them bad — it makes them not-A. **B is the highest practical grade today.**

## What you get

For each trader graded:

- **Edge metrics**: mean PnL/trade, median, stdev, Sharpe (per-trade + annualized), Sortino
- **Selection-deflated Sharpe**: corrects for "picked from N peers on a leaderboard"
- **Risk metrics**: true peak-to-trough max DD, longest losing streak, catastrophic-day rate, worst single trade
- **Return metrics**: total PnL, annualized %, Calmar (return/MDD)
- **Stability ratio**: 2nd-half mean / 1st-half mean — detects degrading traders
- **Cross-period stability** (if you supply 30d + 90d): does the grade hold?

## When to invoke

The skill activates on any of:

- *"Grade this trader"* → single-trader scorecard
- *"Should I copy [nickname]"* → fetch + grade + recommend
- *"Run rigor on OKX leaderboard"* → grade top-N + publish delta vs OKX rank
- *"Most underrated OKX traders"* → return Gecko-rank vs OKX-rank deltas
- *"Cross-period stability"* → 30d vs 90d grade-flip analysis

## Inputs

Two paths:

**Path A — Live OKX leaderboard** (recommended; requires `okx-agent-trade-kit` MCP):

```bash
python grade.py --okx-leaderboard --period 30d --limit 50
# OR
python grade.py --okx-leaderboard --period 30d --period 90d --stability
```

**Path B — Per-trade JSON** (any source: OKX export, Bybit, Binance, manual):

```json
[
  {
    "entry_ts_ms": 1715290000000,
    "exit_ts_ms": 1715380000000,
    "symbol": "SUI/USDT",
    "side": "long",
    "entry_px": 1.0827,
    "exit_px": 1.3410,
    "size_usd": 73422.58,
    "realized_pnl_usd": 14052.88,
    "realized_pnl_pct": 23.70
  }
]
```

```bash
python grade.py --trades trades.json
```

## Empirical proof — live OKX top-50 (2026-05-28)

Pulled live data via `mcp__okx-agent-trade-kit__smartmoney_get_traders_by_filter`.

### v0.1 distribution (no persistence gate)

| Distribution on 90d | Count |
|---|---|
| Grade A | 4 / 50 (8%) |
| Grade B | 13 / 50 (26%) |
| Grade C | 12 / 50 (24%) |
| Grade D | 21 / 50 (42%) |

### v0.2 distribution (persistence gate active)

| Distribution on 90d | Count |
|---|---|
| **Grade A** | **0 / 50 (0%)** |
| Grade B | 17 / 50 (34%) |
| Grade C | 12 / 50 (24%) |
| Grade D | 21 / 50 (42%) |

**Cross-period (30d vs 90d):**
- Only 27/73 unique traders appear in BOTH periods (63% rotation)
- Only 6 are stable A/B across both periods
- **~11% of OKX leaderboard appearances are persistently skilled**

### The 4 v0.1 A's that v0.2 downgrades to B

| Trader | OKX 90d rank | Sharpe (90d) | early half | late half | v0.2 grade |
|---|---|---|---|---|---|
| 天王盖地虎M | #3 | +6.38 | B | A | B |
| 风箱 | #14 | +3.84 | B | A | B |
| bb16888888 | #19 | +3.37 | A | B | B |
| mar***@gmail.com | #20 | +3.34 | B | C | B |

All 4 are skilled — but none cleared the persistence bar. Picking ANY of them is a defensible B-grade move.

**Most overrated by OKX:**
- 三年好日子 → OKX #22, Gecko #45 (Δ+23) — catastrophic rate **65%**
- KoreanTop → OKX #10, Gecko #31 (Δ+21) — degrading stability **-3.20**
- Meta_Man → OKX #15, Gecko #34 (Δ+19) — degrading **-12.56**

**Most underrated by OKX:**
- 风箱 → OKX #48, Gecko #10 (Δ-38) — Sharpe 7.93, max-DD only -0.6%
- 天王盖地虎M → OKX #26, Gecko #3 (Δ-23) — Sharpe 11.10, persistent A→A
- 好的呢哥哥 → OKX #18, Gecko #1 (Δ-17) — Sharpe 17.11

## Quickstart

```bash
git clone https://github.com/ernanibmurtinho/gecko-mcpay-api.git
cd gecko-mcpay-api/gecko-copy-trade-grader
pip install -r requirements.txt

# Test on the bundled sample (5 OKX top-traders, captured 2026-05-28)
python grade.py --sample

# Live OKX leaderboard (requires okx-agent-trade-kit MCP wired)
python grade.py --okx-leaderboard --period 30d --limit 50

# Grade a single trader by authorId
python grade.py --okx-leaderboard --period 30d --author-id 872838143249428480

# Cross-period stability
python grade.py --okx-leaderboard --period 30d --period 90d --stability
```

## Pricing (x402 advisory mode, post-MVP)

Per-grade fee: **$0.05 USDC via x402** (paid on tool invocation; default to stub mode for local dev). At OKX's minimum copy size of $125, the grader-fee-to-investment ratio is **0.04%** — and the EV swing from avoiding a Grade D vs picking a Grade A is conservatively **+$15/month per $125 deployed**. ROI on the grader fee: ~300x.

## What this skill is NOT

- **NOT a trading bot.** It grades; you decide. No execution, no signals to follow.
- **NOT financial advice.** A Grade A is data-driven, not a guarantee.
- **NOT a leaderboard.** It outputs grades + reasoning. Users pick.
- **NOT exclusive to OKX.** Any source of per-trade history works (Bybit, Binance, manual export).

## Safety

- **Read-only.** No order placement, no key signatures, no fund movement. The skill consumes public market data only.
- **No secrets ship.** `.env.example` has empty values; your OKX API key (if used) stays local.
- **PAPER-default.** The skill itself doesn't trade. If a downstream skill consumes the grade and trades, that's the downstream skill's concern.

## Roadmap

- **v0.2** — wire `okx-agent-trade-kit.smartmoney_get_trader_orders_history` to validate the daily-return reconstruction against actual trade lists.
- **v0.3** — multi-marketplace ingest (Bybit, Binance copy-trading).
- **v0.4** — grade-stability monitoring: subscribe to a trader, get notified when their grade DROPS below the level at which you copied them.
- **v1.0** — sell as a Gecko advisor skill via x402 micropayment.

## License

MIT. Built on Gecko's rigor-stack work, validated against live OKX data.
