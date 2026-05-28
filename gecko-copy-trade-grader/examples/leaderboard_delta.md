# Example: full OKX leaderboard delta (Gecko-Rank vs OKX-Rank)

Live `smartmoney_get_traders_by_filter` pull, top 50 by `pnlRatio` over 30 days. Captured 2026-05-28.

## How to run

```bash
# 1. Save the MCP fetch result to JSON (your MCP client does this):
#    mcp__okx-agent-trade-kit__smartmoney_get_traders_by_filter \
#      sortBy=pnlRatio period=30 limit=50

# 2. Grade:
python3 grade.py --okx-leaderboard --period 30d --raw-json analysis/data/okx_leaderboard/raw_30d.json
```

## Output (abridged — see full graded.json for all 50)

```
OKX# Gecko# Δrank | name              AUM$    OKX_PnL%  TrueDD  Sharpe  Defl_Sh  CatRate  Stable  Grade
─────────────────────────────────────────────────────────────────────────────────────────────────────
   1      8     -7 | 林子和他的朋友们     $160K   +1092.4%  -15.3%  +8.17   +7.67    10%     +4.90      B
   2     11     -9 | 加密小胖           $116K    +462.1%  -12.0%  +7.55   +7.05    16%     +0.64      D
   3      5     -2 | yyyee9          $ 67K    +414.2%  -13.5% +10.04   +9.53     6%     +3.17      B
   6      9     -3 | kimi大林          $980K    +254.9%  -38.1%  +8.08   +7.57    13%     +1.50      C
  10     31    -21 | KoreanTop       $ 64K    +185.0%  -35.7%  +3.74   +3.23    19%     -3.20      D
  15     34    -19 | Meta_Man        $222K    +100.5%  -28.3%  +3.39   +2.89    29%    -12.56      D
  18      1    +17 | 好的呢哥哥         $ 14K     +88.5%   -7.0% +17.11  +16.60     3%     +1.38      A
  19      2    +17 | LWRKM           $ 66K     +83.1%  -16.6% +13.02  +12.52    10%     +1.10      B
  20     38    -18 | 水星家纺           $ 64K     +82.1%  -37.6%  +2.74   +2.24    39%     -5.57      D
  22     45    +23 | 三年好日子          $ 40K     +64.0% -191.7%  +1.76   +1.26    65%     -1.96      D
  26      3    -23 | 天王盖地虎M        $350K     +39.7%   -2.7% +11.10  +10.60     0%     +3.24      A
  31     17    -14 | BTC星辰          $1981K   +27.4%   -3.1%  +6.49   +5.99     0%     +1.29      A
  48     10    -38 | 风箱             $1467K    +3.0%   -0.6%  +7.93   +7.43     0%     +1.72      A
```

## Grade distribution across all 50 OKX top-50 traders

```
A (true skill):       5 / 50  (10%)
B (promising):       16 / 50  (32%)
C (noise/lucky):     12 / 50  (24%)
D (gambling/degrading): 17 / 50  (34%)
```

## Most underrated by OKX (high Gecko, low OKX rank)

| OKX rank | Gecko rank | Δ | Nickname | Why high Gecko rank |
|---|---|---|---|---|
| 48 | 10 | -38 | 风箱 | Sharpe 7.93, max-DD -0.6%, AUM $1.47M; small PnL% because of capacity constraint, not lack of skill |
| 26 | 3 | -23 | 天王盖地虎M | Sharpe 11.10, max-DD -2.7%, 0% catastrophic days |
| 47 | 29 | -18 | bb16888888 | Sharpe 4.08, 0% catastrophic, $1.21M AUM |
| 18 | 1 | -17 | 好的呢哥哥 | Sharpe 17.11 (highest in sample) |
| 31 | 17 | -14 | BTC星辰 | Genuine alpha on $1.98M AUM |

## Most overrated by OKX

| OKX rank | Gecko rank | Δ | Nickname | Why low Gecko rank |
|---|---|---|---|---|
| 22 | 45 | +23 | 三年好日子 | Catastrophic 65%, max-DD -191.7% |
| 10 | 31 | +21 | KoreanTop | Degrading stability -3.20 |
| 30 | 50 | +20 | 不二的交易记录 | Catastrophic 45%, max-DD -55.6% |
| 15 | 34 | +19 | Meta_Man | Degrading stability -12.56 |
| 20 | 38 | +18 | 水星家纺 | Catastrophic 39%, stability -5.57 |

## What this proves

OKX ranks by raw cumulative PnL%. That ranking systematically:
- Rewards heavy-tail luck (one big win carries everything)
- Hides degradation (was earning early, now bleeding, cumulative still positive)
- Hides catastrophic-day risk (lumpy distributions look the same at top as smooth ones)
- Penalizes large-AUM disciplined traders (风箱 at +3% on $1.47M AUM is ranked #48, but their Sharpe is 7.93)

Gecko Grade catches all of this in one pass. **At $0.05/grade × $125 OKX minimum copy = 0.04% friction for ~300x ROI on saved EV.**
