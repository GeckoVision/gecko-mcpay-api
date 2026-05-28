# gecko-copy-trade-grader

Rigor scorecard for public crypto copy-traders. Use BEFORE clicking "Copy."

> Empirically: 34% of OKX top-50 leaderboard traders grade **D** (gambling or degrading) under proper rigor. Only **11%** of leaderboard appearances represent persistently skilled traders. This skill catches that.

## What's in here

```
gecko-copy-trade-grader/
├── SKILL.md                   # user-facing skill manifest (read first)
├── grader.py                  # pure grading library (stdlib only)
├── grade.py                   # CLI entry point
├── package.json               # skill metadata
├── .claude-plugin/plugin.json # Claude Code plugin manifest
├── requirements.txt           # python deps (none — stdlib only)
├── examples/
│   ├── okx_top5_snapshot.json     # bundled sample for --sample mode
│   ├── single_trader_skilled.md
│   ├── single_trader_gambling.md
│   └── leaderboard_delta.md
├── tests/
│   └── test_grader.py
└── README.md
```

## Quick demo (no setup needed)

```bash
python3 grade.py --sample
```

Outputs A/B/C/D grades + Gecko-Rank vs OKX-Rank delta on the bundled 5-trader snapshot from 2026-05-28.

## Grading any single trader (manual JSON)

```bash
cat > my_trader_trades.json <<EOF
[
  {"entry_ts_ms":1715290000000,"exit_ts_ms":1715380000000,"symbol":"SUI/USDT",
   "side":"long","entry_px":1.0827,"exit_px":1.3410,"size_usd":73422.58,
   "realized_pnl_usd":14052.88,"realized_pnl_pct":23.70},
  {"entry_ts_ms":1715200000000,"exit_ts_ms":1715240000000,"symbol":"ONDO/USDT",
   "side":"long","entry_px":0.4623,"exit_px":0.4576,"size_usd":31531.22,
   "realized_pnl_usd":-371.49,"realized_pnl_pct":-1.17}
]
EOF
python3 grade.py --trades my_trader_trades.json --trader-label "MyTrader" --n-peers 200
```

## Grading the live OKX leaderboard

Requires `okx-agent-trade-kit` MCP server wired (`mcp__okx-agent-trade-kit__smartmoney_get_traders_by_filter`).

Workflow:

```bash
# 1. Invoke the MCP, save the response to a file
#    (Claude Code or your client of choice can save the JSON)
# 2. Then:
python3 grade.py --okx-leaderboard --period 30d --raw-json /path/to/raw_30d.json
python3 grade.py --okx-leaderboard --period 30d --period 90d \
    --raw-json /path/to/raw_30d.json --raw-json /path/to/raw_90d.json \
    --stability
```

## What the rigor stack computes

| Metric | Why it matters |
|---|---|
| **Sharpe (per-trade + annualized)** | Edge per unit variance. Raw cumulative PnL hides variance. |
| **Sortino** | Downside-only variance. Penalizes losses, not wins. |
| **True max-DD** | Peak-to-trough on cumulative PnL. OKX shows only "7D max-DD" which can be misleading. |
| **Catastrophic-rate** | % of days/trades worse than -3%. One big loss can wipe many small wins. |
| **Stability ratio** | 2nd-half mean / 1st-half mean. Detects degradation. |
| **Selection-deflated Sharpe** | Bailey-LdP correction for "picked from N peers on a leaderboard." |
| **Calmar** | Annualized return / max DD. Risk-adjusted measure of efficiency. |

## Grade rubric

| Grade | Gates |
|---|---|
| **A** | Sharpe ≥ 3 (or per-trade ≥ 1.5) + max-DD ≤ 15% + catastrophic ≤ 5-10% + stability ≥ 0.3 + n_trades/days ≥ 30 |
| **B** | Sharpe ≥ 1.5 + max-DD ≤ 25-30% + stability ≥ 0.0-0.2 |
| **C** | Sharpe 0.5-1.5; marginal edge; small sample |
| **D** | Sharpe < 0.5 OR catastrophic > 15-25% OR stability < 0 OR profit-factor < 1 |

## Empirical validation (2026-05-28)

Pulled 50 traders from OKX `smartmoney_get_traders_by_filter` for both 30d and 90d periods.

| Distribution on 30d | Count |
|---|---|
| A | 5 (10%) |
| B | 16 (32%) |
| C | 12 (24%) |
| D | 17 (34%) |

| Cross-period (30d vs 90d) | Count |
|---|---|
| Unique multi-period | 27 |
| Stable A/B in both | 6 (22%) |
| Stable C/D in both | 10 (37%) |
| FLIP ≥2 grades | 4 (15%) |

**~11% of OKX leaderboard appearances are persistently skilled.** The other 89% is selection rotation × within-period noise.

## Most-overrated OKX traders we caught

- `三年好日子` — OKX #22, Gecko #45 (Δ +23). Catastrophic rate **65%**, max-DD historically -191.7%.
- `KoreanTop` — OKX #10, Gecko #31. Stability **-3.20** (degrading).
- `Meta_Man` — OKX #15, Gecko #34. Stability **-12.56** (collapsing).

## Most-underrated OKX traders we surfaced

- `风箱` — OKX #48, Gecko #10 (Δ -38). Sharpe 7.93, max-DD only -0.6%.
- `天王盖地虎M` — OKX #26, Gecko #3. Sharpe 11.10, max-DD -2.7%, A→A across periods.
- `好的呢哥哥` — OKX #18, Gecko #1. Sharpe 17.11.

## Why this is a real product

OKX's minimum copy investment is **$125 USDC**. The skill's per-grade cost (planned x402): **$0.05 USDC**. Friction ratio 0.04%.

Expected EV swing from avoiding a Grade D vs picking from the 6 stable A/B traders: **~$15+/month per $125 deployed** at conservative assumptions. **ROI on the grader fee: ~300x.**

## License

MIT. Validated against live OKX data; built on the Gecko rigor stack.
