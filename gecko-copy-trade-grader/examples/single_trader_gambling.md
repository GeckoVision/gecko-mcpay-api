# Example: catch a gambling-profile trader (三年好日子)

Live OKX leaderboard, captured 2026-05-28. OKX rank #22 with +64% PnL — looks decent. Gecko grade: **D**. Most-overrated trader by OKX (Δ +23 rank delta).

## Input

```json
{
  "nickName": "三年好日子",
  "authorId": "872833029876953088",
  "asset": "40451.39",
  "pnl": "26203.95",
  "pnlRatio": "0.6400",
  "winRate": "0.4807",
  "maxDrawdown": "-0.9998",
  "rates": [...31 days of cumulative PnL...]
}
```

## Output

```
GECKO COPY-TRADE GRADER — 三年好日子 (OKX #22)

  GRADE: D
    • Triggered D-gate: gambling profile
    •   → catastrophic_rate 65% > 25%
    • override → D: catastrophic_rate 65% > 15
    • → caution: max DD -191.7% historically; drawdown risk severe

  Sample:                   days=31, AUM=$40,451
  Sharpe (annualized):      +1.76  (deflated for 50 peers: +1.26)
  True max drawdown:        -191.7%  (peak-to-trough on cum-PnL %)
  Catastrophic-day rate:    65%  (20 of 31 days worse than -3%)
  Stability:                -1.96  (DEGRADING)
  Annualized return:        +753%/yr · Calmar: 3.93
```

## Why OKX ranks them high

OKX's leaderboard sees +64% cumulative PnL over 30 days and ranks accordingly. What they DON'T show:

- **65% of days were worse than -3%** — this trader is dangerous on a per-day basis
- **True max-DD on cumulative PnL was -191.7%** — they blew through their initial capital and came back, but a copier joining today is one bad day away from disaster
- **Stability -1.96** — 2nd half is significantly worse than 1st half. **The trader is degrading, not improving.**
- **OKX's own `maxDrawdown` field shows -0.9998 (99.98%!)** — but it's buried; the ranking still puts them at #22

## What a copier sees vs gets

| Metric | OKX surface | Gecko surface |
|---|---|---|
| Headline | "+64% PnL in 30 days" | "Grade D" |
| Risk | "7D max-DD 3.32%" (the easy number) | "Cumulative DD -191.7%, 65% catastrophic days" |
| Trajectory | "ranking #22" | "stability -1.96 = degrading" |

**A user filtering by Gecko grade would skip this trader entirely. A user sorting by OKX PnL would copy them.** The downside variance is real and unaffordable.
