# Example: grade a skilled trader (天王盖地虎M)

Live OKX leaderboard, captured 2026-05-28. Hidden at OKX rank #26 — Gecko rank #3, persistent A→A across 30d AND 90d periods.

## Input (per OKX `smartmoney_get_traders_by_filter` schema)

```json
{
  "nickName": "天王盖地虎M",
  "authorId": "954023867877117952",
  "asset": "349884.41",
  "pnl": "103586.39",
  "pnlRatio": "0.3979",
  "winRate": "0.7411",
  "maxDrawdown": "-0.4482",
  "rates": [
    {"statTime": "260428", "value": "590.5"},
    {"statTime": "260429", "value": "2828.08"},
    "...31 days..."
  ]
}
```

## Output

```
GECKO COPY-TRADE GRADER — 天王盖地虎M (OKX #26)

  GRADE: A
    • Sharpe ≥ 3 + low DD + low cat + stable

  Sample:                   days=31, AUM=$349,884
  Sharpe (annualized):      +11.10  (deflated for 50 peers: +10.60)
  Sortino (annualized):     +25.41
  True max drawdown:        -2.7%  (cum-PnL terms)
  Catastrophic-day rate:    0%
  Stability (2H/1H):        +3.24  (improving)
  Annualized return:        +119%/yr · Calmar: 44.07
```

## Why this matters

OKX shows this trader at rank #26 — buried under flashier +400%, +800% headlines. **But:**

- Sharpe 11.10 means **10x more edge per unit variance** than the OKX #1 trader (+8.17 Sharpe at +1092% PnL but max-DD -15%)
- True max-DD only -2.7% — a copy-trader can plan for this drawdown vs the -15% buried in OKX #1
- 0 catastrophic days vs OKX-top traders carrying 13-16% catastrophic rate
- Stability +3.24 = second half outperforming first half (still ramping)

**A user filtering by Gecko Grade A would find this trader; sorting by OKX PnL% would not.**

## Cross-period validation

Same trader on 90d data: **Grade A again**. Stable across both 30d and 90d windows = real skill, not period-specific luck.
