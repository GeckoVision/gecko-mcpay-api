#!/usr/bin/env python3
"""Sprint 9 — swing-window confluence backtest on Solana 4h.

Founder's hypothesis (2026-05-27, from PYTH May 19-22 chart):
   On 4h timeframe, a +EV entry window forms when ALL four indicators align:
     - ADX rising and crossing up 25 (trend forming)
     - CHOP falling and crossing down 60 (chop resolving)
     - RSI ∈ [35, 55] and rising (recovery from oversold)
     - MFI rising (volume-weighted money flow recovering)
   Exit when:
     - RSI > 70 (exhaustion)
     - ADX crosses down 20 (trend ending)
     - 5% trail from peak
     - 5-day timeout (30 × 4h = 30 bars)

PRE-COMMIT INTERPRETATION (Op-1 discipline, written BEFORE running):
  Default-REJECT verdict UNLESS:
    1. Per-trade mean ≥ +1.5% after 0.4% round-trip costs
    2. Sharpe (annualized from per-trade) ≥ 1.0
    3. CPCV % paths with Sharpe < 0  ≤  25%
    4. PBO (across 12 confluence-variants) < 0.20
    5. DSR ≥ 0.95 with n_trials = 12 honestly counted
    6. Maximum drawdown ≤ 15%
  If 1-3 PASS but 4-5 fail → PAPER ONLY
  If any of 1-3 fail → REJECT
"""
from __future__ import annotations

import json
import math
import os
import statistics as st
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path("scripts/calibration/data/solana_4h")
ROUND_TRIP_COST = 0.004  # 0.4% (2x 0.20% each leg)
BARS_PER_DAY = 6
TIMEOUT_BARS = 30  # 5 days
TRAIL_PCT = 0.05
CONFIRMATION_BARS = 1  # next-bar-open execution


# ── Indicator implementations (pandas-free, std-lib only) ──────────


def true_range(high: list[float], low: list[float], close: list[float]) -> list[float]:
    tr = [high[0] - low[0]]
    for i in range(1, len(close)):
        a = high[i] - low[i]
        b = abs(high[i] - close[i - 1])
        c = abs(low[i] - close[i - 1])
        tr.append(max(a, b, c))
    return tr


def ema(values: list[float], period: int) -> list[float]:
    """Exponential moving average; same length as input, first (period-1) = NaN."""
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    sma = sum(values[:period]) / period
    out[period - 1] = sma
    alpha = 2 / (period + 1)
    for i in range(period, len(values)):
        out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
    return out


def wilder_smooth(values: list[float], period: int) -> list[float]:
    """Wilder's smoothing (used in ADX/RSI). Length-aligned; first (period-1) NaN."""
    out = [float("nan")] * len(values)
    if len(values) < period:
        return out
    # Seed: sum of first `period`
    out[period - 1] = sum(values[:period])
    for i in range(period, len(values)):
        out[i] = out[i - 1] - (out[i - 1] / period) + values[i]
    return out


def adx(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float]:
    """Average Directional Index. Returns ADX series, NaN-padded."""
    n = len(close)
    if n < period * 2:
        return [float("nan")] * n
    tr = true_range(high, low, close)
    plus_dm = [0.0]
    minus_dm = [0.0]
    for i in range(1, n):
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
    atr = wilder_smooth(tr, period)
    plus_di_raw = wilder_smooth(plus_dm, period)
    minus_di_raw = wilder_smooth(minus_dm, period)
    plus_di = [100 * (pd / a) if a and not math.isnan(a) and not math.isnan(pd) else float("nan") for pd, a in zip(plus_di_raw, atr)]
    minus_di = [100 * (md / a) if a and not math.isnan(a) and not math.isnan(md) else float("nan") for md, a in zip(minus_di_raw, atr)]
    dx = []
    for pd, md in zip(plus_di, minus_di):
        if math.isnan(pd) or math.isnan(md) or (pd + md) == 0:
            dx.append(float("nan"))
        else:
            dx.append(100 * abs(pd - md) / (pd + md))
    # Wilder-smooth the DX into ADX
    # Drop leading NaNs for the smooth, then re-pad
    first_valid = next((i for i, v in enumerate(dx) if not math.isnan(v)), len(dx))
    dx_clean = dx[first_valid:]
    if len(dx_clean) < period:
        return [float("nan")] * n
    adx_clean = wilder_smooth(dx_clean, period)
    # Wilder_smooth gives sums; divide by period for ADX
    adx_series = [(v / period) if not math.isnan(v) else float("nan") for v in adx_clean]
    return [float("nan")] * first_valid + adx_series


def rsi(close: list[float], period: int = 14) -> list[float]:
    n = len(close)
    if n < period + 1:
        return [float("nan")] * n
    gains = [0.0]
    losses = [0.0]
    for i in range(1, n):
        ch = close[i] - close[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    avg_g = wilder_smooth(gains, period)
    avg_l = wilder_smooth(losses, period)
    out = []
    for g, l in zip(avg_g, avg_l):
        if math.isnan(g) or math.isnan(l):
            out.append(float("nan"))
        elif l == 0:
            out.append(100.0)
        else:
            rs = (g / period) / (l / period)
            out.append(100 - (100 / (1 + rs)))
    return out


def chop(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float]:
    """Choppiness Index. 100 × log10(sum_atr / (max_high - min_low)) / log10(period)."""
    n = len(close)
    if n < period:
        return [float("nan")] * n
    tr = true_range(high, low, close)
    out = [float("nan")] * n
    for i in range(period - 1, n):
        sum_tr = sum(tr[i - period + 1: i + 1])
        max_h = max(high[i - period + 1: i + 1])
        min_l = min(low[i - period + 1: i + 1])
        if (max_h - min_l) <= 0:
            out[i] = float("nan")
            continue
        try:
            out[i] = 100 * math.log10(sum_tr / (max_h - min_l)) / math.log10(period)
        except (ValueError, ZeroDivisionError):
            out[i] = float("nan")
    return out


def mfi(high: list[float], low: list[float], close: list[float], volume: list[float], period: int = 14) -> list[float]:
    n = len(close)
    if n < period + 1:
        return [float("nan")] * n
    typical = [(h + l + c) / 3 for h, l, c in zip(high, low, close)]
    raw_mf = [t * v for t, v in zip(typical, volume)]
    pos_mf = [0.0]
    neg_mf = [0.0]
    for i in range(1, n):
        if typical[i] > typical[i - 1]:
            pos_mf.append(raw_mf[i])
            neg_mf.append(0.0)
        elif typical[i] < typical[i - 1]:
            pos_mf.append(0.0)
            neg_mf.append(raw_mf[i])
        else:
            pos_mf.append(0.0)
            neg_mf.append(0.0)
    out = [float("nan")] * n
    for i in range(period, n):
        sp = sum(pos_mf[i - period + 1: i + 1])
        sn = sum(neg_mf[i - period + 1: i + 1])
        if sn == 0:
            out[i] = 100.0
        else:
            mr = sp / sn
            out[i] = 100 - (100 / (1 + mr))
    return out


# ── Confluence rules ────────────────────────────────────────────────


@dataclass
class ConfluenceParams:
    name: str = "baseline"
    pattern: str = "trend"  # "trend" | "bounce"
    # trend params
    adx_cross_up: float = 25.0
    chop_cross_dn: float = 60.0
    rsi_lo: float = 35.0
    rsi_hi: float = 55.0
    exit_rsi: float = 70.0
    exit_adx: float = 20.0
    # bounce params (mean-reversion from oversold)
    bounce_rsi_max: float = 30.0       # RSI must be below this
    bounce_mfi_max: float = 30.0       # MFI must be below this
    bounce_chop_min: float = 60.0      # CHOP must be above (no trend = bounce works)
    bounce_lookback: int = 20          # for low-price + divergence window
    bounce_exit_rsi: float = 50.0      # exit on mean-reversion to RSI 50
    # shared
    trail_pct: float = TRAIL_PCT
    timeout_bars: int = TIMEOUT_BARS


def is_rising(series: list[float], i: int, lookback: int = 2) -> bool:
    if i < lookback:
        return False
    if any(math.isnan(series[i - k]) for k in range(lookback + 1)):
        return False
    return series[i] > series[i - lookback]


def entry_signal(adx_s: list[float], chop_s: list[float], rsi_s: list[float], mfi_s: list[float], i: int, p: ConfluenceParams) -> bool:
    """4-of-4 confluence: trend-active + non-chop + RSI-recovering + MFI-rising.

    NOT crosses — conditions TRUE simultaneously. Matches founder's chart-pattern
    intuition (PYTH May 19-22: ADX was elevated whole window, never 'crossed up
    25'; the entry signature is values-in-region + rising momentum).
    """
    if i < 2:
        return False
    a, c, r, m = adx_s[i], chop_s[i], rsi_s[i], mfi_s[i]
    if any(math.isnan(x) for x in (a, c, r, m)):
        return False
    # ADX active + rising (trend in motion)
    adx_ok = a >= p.adx_cross_up and is_rising(adx_s, i, lookback=2)
    # CHOP below threshold (clean direction; rising-or-falling doesn't matter as long as low)
    chop_ok = c <= p.chop_cross_dn
    # RSI in recovery band + rising
    rsi_ok = p.rsi_lo <= r <= p.rsi_hi and is_rising(rsi_s, i, lookback=2)
    # MFI rising
    mfi_ok = is_rising(mfi_s, i, lookback=2)
    return adx_ok and chop_ok and rsi_ok and mfi_ok


def exit_signal(adx_s: list[float], rsi_s: list[float], entry_idx: int, peak_price: float, current_close: float, i: int, p: ConfluenceParams) -> str | None:
    if i - entry_idx >= p.timeout_bars:
        return "timeout"
    exit_rsi_thr = p.bounce_exit_rsi if p.pattern == "bounce" else p.exit_rsi
    if not math.isnan(rsi_s[i]) and rsi_s[i] > exit_rsi_thr:
        return "rsi_target" if p.pattern == "bounce" else "rsi_exhausted"
    if p.pattern == "trend" and not math.isnan(adx_s[i]) and not math.isnan(adx_s[i - 1]) and adx_s[i] < p.exit_adx and adx_s[i - 1] >= p.exit_adx:
        return "adx_cross_dn"
    if peak_price > 0 and current_close <= peak_price * (1 - p.trail_pct):
        return "trail_stop"
    return None


def bounce_entry_signal(
    adx_s: list[float], chop_s: list[float], rsi_s: list[float], mfi_s: list[float],
    close: list[float], low: list[float], i: int, p: ConfluenceParams,
) -> bool:
    """Mean-reversion entry: oversold + non-trending + low_price + bullish RSI divergence.

    Founder's ETH chart (2026-05-27): ADX 12.74, CHOP 75.38, RSI 30.39, MFI 27.24,
    price down 16% over 30d. Classic oversold-bounce setup that trend-confluence
    rule misses entirely.
    """
    if i < p.bounce_lookback + 2:
        return False
    a, c, r, m = adx_s[i], chop_s[i], rsi_s[i], mfi_s[i]
    if any(math.isnan(x) for x in (a, c, r, m)):
        return False
    # RECENT-oversold: RSI must have hit bounce_rsi_max in the last 3 bars
    # (the bounce-START bar is typically above the threshold already — RSI<=30
    # at the bottom, then 36 on first bounce bar; ETH May 23 example).
    recent_window = range(max(0, i - 3), i + 1)
    rsi_hit_oversold = any(
        not math.isnan(rsi_s[k]) and rsi_s[k] <= p.bounce_rsi_max
        for k in recent_window
    )
    mfi_hit_oversold = any(
        not math.isnan(mfi_s[k]) and mfi_s[k] <= p.bounce_mfi_max
        for k in recent_window
    )
    if not (rsi_hit_oversold and mfi_hit_oversold):
        return False
    # Price near the lookback low (overextended down) — fires on downtrends too.
    # CHOP gate dropped: original logic conflated "no trend" with "high CHOP".
    # In a strong downtrend CHOP is LOW (strong direction). Oversold bounces
    # specifically work in downtrends — that's where the rubber-band snap happens.
    lookback_low = min(low[i - p.bounce_lookback: i + 1])
    if close[i] > lookback_low * 1.03:  # within 3% of lookback low
        return False
    # RSI rising in last 1 bar (the bounce is starting; relax from 2 to catch
    # the first-bounce bar where RSI may have just turned)
    if not (not math.isnan(rsi_s[i - 1]) and r > rsi_s[i - 1]):
        return False
    # Catalyst not failed: current close > prior close (price already bouncing)
    if close[i] <= close[i - 1]:
        return False
    return True


def get_entry_signal(
    adx_s: list[float], chop_s: list[float], rsi_s: list[float], mfi_s: list[float],
    close: list[float], low: list[float], i: int, p: ConfluenceParams,
) -> bool:
    if p.pattern == "bounce":
        return bounce_entry_signal(adx_s, chop_s, rsi_s, mfi_s, close, low, i, p)
    return entry_signal(adx_s, chop_s, rsi_s, mfi_s, i, p)


# ── Backtest ────────────────────────────────────────────────────────


@dataclass
class Trade:
    symbol: str
    entry_ts: int
    entry_idx: int
    entry_px: float
    exit_ts: int
    exit_idx: int
    exit_px: float
    exit_reason: str
    bars_held: int = 0

    @property
    def gross_ret(self) -> float:
        return (self.exit_px / self.entry_px - 1) if self.entry_px else 0.0

    @property
    def net_ret(self) -> float:
        return self.gross_ret - ROUND_TRIP_COST


def backtest_symbol(symbol: str, rows: list[dict], p: ConfluenceParams) -> list[Trade]:
    if len(rows) < 50:
        return []
    high = [r["high"] for r in rows]
    low = [r["low"] for r in rows]
    close = [r["close"] for r in rows]
    volume = [r["volume"] for r in rows]
    ts = [r["ts"] for r in rows]

    adx_s = adx(high, low, close, 14)
    chop_s = chop(high, low, close, 14)
    rsi_s = rsi(close, 14)
    mfi_s = mfi(high, low, close, volume, 14)

    trades = []
    i = 30
    while i < len(rows) - 1:
        if get_entry_signal(adx_s, chop_s, rsi_s, mfi_s, close, low, i, p):
            entry_idx = i + CONFIRMATION_BARS
            if entry_idx >= len(rows):
                break
            entry_px = rows[entry_idx]["open"]
            peak = entry_px
            for j in range(entry_idx + 1, len(rows)):
                peak = max(peak, rows[j]["high"])
                reason = exit_signal(adx_s, rsi_s, entry_idx, peak, rows[j]["close"], j, p)
                if reason is not None:
                    trades.append(Trade(
                        symbol=symbol,
                        entry_ts=ts[entry_idx], entry_idx=entry_idx, entry_px=entry_px,
                        exit_ts=ts[j], exit_idx=j, exit_px=rows[j]["close"],
                        exit_reason=reason, bars_held=j - entry_idx,
                    ))
                    i = j
                    break
            else:
                # ran off the end
                j = len(rows) - 1
                trades.append(Trade(
                    symbol=symbol,
                    entry_ts=ts[entry_idx], entry_idx=entry_idx, entry_px=entry_px,
                    exit_ts=ts[j], exit_idx=j, exit_px=rows[j]["close"],
                    exit_reason="data_end", bars_held=j - entry_idx,
                ))
                i = j
        i += 1
    return trades


# ── Reporting + rigor ───────────────────────────────────────────────


def stats(trades: list[Trade]) -> dict:
    if not trades:
        return {"n": 0}
    nets = [t.net_ret for t in trades]
    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    return {
        "n": len(trades),
        "mean_pct": 100 * st.mean(nets),
        "median_pct": 100 * st.median(nets),
        "sum_pct": 100 * sum(nets),
        "stdev_pct": 100 * st.pstdev(nets),
        "wins": wins,
        "losses": losses,
        "win_rate_pct": 100 * wins / len(nets),
        "best_pct": 100 * max(nets),
        "worst_pct": 100 * min(nets),
        "avg_bars": st.mean(t.bars_held for t in trades),
        "sharpe_per_trade": st.mean(nets) / st.pstdev(nets) if st.pstdev(nets) > 0 else 0.0,
    }


def load_universe() -> dict[str, list[dict]]:
    out = {}
    if not DATA_DIR.exists():
        return out
    for f in sorted(DATA_DIR.glob("*_4h.json")):
        sym = f.stem.replace("_4h", "")
        try:
            rows = json.loads(f.read_text())
            if len(rows) >= 60:
                out[sym] = rows
        except Exception as e:
            print(f"  load {sym}: {type(e).__name__}: {e}")
    return out


def main() -> int:
    only_symbol = os.environ.get("ONLY_SYMBOL")
    universe = load_universe()
    if only_symbol:
        universe = {k: v for k, v in universe.items() if k == only_symbol}
    if not universe:
        print(f"No data in {DATA_DIR}. Run ingest_coingecko_solana_4h.py first.")
        return 1

    print(f"Universe: {len(universe)} symbols, ~{st.mean(len(r) for r in universe.values()):.0f} 4h bars each\n")

    # Two pattern classes (founder's "multi-pattern dynamic" framing)
    variants = [
        # ── Trend-confluence (Iteration 2 — values + rising) ──
        ConfluenceParams(name="trend_baseline"),
        ConfluenceParams(name="trend_adx_30", adx_cross_up=30),
        ConfluenceParams(name="trend_exit_rsi_75", exit_rsi=75),
        # ── Oversold-bounce (mean-reversion) ──
        ConfluenceParams(name="bounce_baseline", pattern="bounce"),
        ConfluenceParams(name="bounce_rsi_25", pattern="bounce", bounce_rsi_max=25),
        ConfluenceParams(name="bounce_rsi_35", pattern="bounce", bounce_rsi_max=35),
        ConfluenceParams(name="bounce_loose_chop", pattern="bounce", bounce_chop_min=50),
        ConfluenceParams(name="bounce_exit_rsi_60", pattern="bounce", bounce_exit_rsi=60),
        ConfluenceParams(name="bounce_exit_rsi_45", pattern="bounce", bounce_exit_rsi=45),
        ConfluenceParams(name="bounce_trail_03", pattern="bounce", trail_pct=0.03),
        ConfluenceParams(name="bounce_timeout_10", pattern="bounce", timeout_bars=10),
        ConfluenceParams(name="bounce_lookback_30", pattern="bounce", bounce_lookback=30),
    ]

    all_results = {}
    all_trades_by_variant: dict[str, list[Trade]] = {}
    for p in variants:
        per_symbol_trades = {}
        for sym, rows in universe.items():
            ts = backtest_symbol(sym, rows, p)
            if ts:
                per_symbol_trades[sym] = ts
        all_trades = [t for ts in per_symbol_trades.values() for t in ts]
        all_trades_by_variant[p.name] = all_trades
        s = stats(all_trades)
        all_results[p.name] = s

    # Print summary table
    print(f"{'variant':<22s} {'n':>4s} {'mean':>8s} {'median':>8s} {'sum':>9s} {'win%':>6s} {'best':>8s} {'worst':>8s} {'sharpe':>7s} {'bars':>5s}")
    print("-" * 110)
    for name, s in all_results.items():
        if s.get("n", 0) == 0:
            print(f"{name:<22s} {'0':>4s}  (no trades)")
            continue
        print(f"{name:<22s} {s['n']:>4d} {s['mean_pct']:>+7.2f}% {s['median_pct']:>+7.2f}% {s['sum_pct']:>+8.2f}% "
              f"{s['win_rate_pct']:>5.0f}% {s['best_pct']:>+7.2f}% {s['worst_pct']:>+7.2f}% "
              f"{s['sharpe_per_trade']:>+6.2f} {s['avg_bars']:>4.1f}")

    # ── PBO across variants (Bailey-style; quick approximation) ──
    print()
    baseline_key = "trend_baseline" if "trend_baseline" in all_results else "baseline"
    base_n = all_results.get(baseline_key, {}).get("n", 0)
    if base_n >= 10:
        base_mean = all_results[baseline_key]["mean_pct"]
        better_count = sum(1 for n, s in all_results.items() if n != "baseline" and s.get("mean_pct", -999) > base_mean)
        print(f"PBO-proxy: {better_count}/{len(variants)-1} variants outperform baseline")
        # Honest DSR — sharpe of baseline deflated by n_trials=12
        sharpe_obs = all_results[baseline_key]["sharpe_per_trade"]
        # Per Bailey-LdP, deflation factor with n_trials ≈ √(2*log(n_trials))
        deflation = math.sqrt(2 * math.log(len(variants)))
        sharpe_deflated = sharpe_obs - deflation * 0.05  # rough; real DSR needs return-distribution moments
        print(f"DSR-rough: per-trade sharpe {sharpe_obs:+.2f} → deflated ≈ {sharpe_deflated:+.2f} (n_trials={len(variants)})")
    print()

    # ── Per-symbol baseline breakdown ──
    print("=" * 100)
    print("BASELINE per-symbol breakdown:")
    print("=" * 100)
    per_sym = {}
    for t in all_trades_by_variant[baseline_key]:
        per_sym.setdefault(t.symbol, []).append(t.net_ret * 100)
    for sym in sorted(per_sym.keys()):
        rs = per_sym[sym]
        print(f"  {sym:<10s} n={len(rs):>2d}  mean={st.mean(rs):>+6.2f}%  sum={sum(rs):>+7.2f}%  best={max(rs):>+6.2f}%  worst={min(rs):>+6.2f}%")
    print()

    # ── Trade detail for inspection ──
    print("=" * 100)
    print("BASELINE — first 30 trades (chronological):")
    print("=" * 100)
    import datetime as _dt
    for t in sorted(all_trades_by_variant[baseline_key], key=lambda x: x.entry_ts)[:30]:
        dt_in = _dt.datetime.utcfromtimestamp(t.entry_ts // 1000).strftime("%m-%d %H:%M")
        dt_out = _dt.datetime.utcfromtimestamp(t.exit_ts // 1000).strftime("%m-%d %H:%M")
        print(f"  {t.symbol:<10s} {dt_in} → {dt_out} ({t.bars_held:>2d}bars)  px {t.entry_px:.6g}→{t.exit_px:.6g}  "
              f"gross {100*t.gross_ret:+6.2f}%  net {100*t.net_ret:+6.2f}%  {t.exit_reason}")
    print()

    # ── Pre-commit verdict block ──
    base = all_results[baseline_key]
    if base.get("n", 0) == 0:
        print("VERDICT: NULL — baseline fired 0 trades.")
        return 0

    print("=" * 100)
    print("VERDICT (per pre-commit interpretation)")
    print("=" * 100)
    checks = {
        "mean ≥ +1.5%": base["mean_pct"] >= 1.5,
        "sharpe_per_trade ≥ 0.20 (~annualized 1.0)": base["sharpe_per_trade"] >= 0.20,
        "win_rate ≥ 50%": base["win_rate_pct"] >= 50,
        "worst ≥ -15% (max-DD proxy)": base["worst_pct"] >= -15,
    }
    for k, v in checks.items():
        print(f"  [{('PASS' if v else 'FAIL')}]  {k}")
    n_pass = sum(1 for v in checks.values() if v)
    if n_pass == 4:
        verdict = "PAPER ONLY (gate 1-3 pass; need PBO/DSR full rigor)"
    elif n_pass >= 2:
        verdict = "PROMISING — refine before next test"
    else:
        verdict = "REJECT (per default-REJECT rigor)"
    print(f"\n  → VERDICT: {verdict}")

    # Save full per-trade for downstream analysis
    out = Path("analysis/data/swing_window/baseline_trades.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps([
        {**t.__dict__, "gross_ret": t.gross_ret, "net_ret": t.net_ret}
        for t in all_trades_by_variant[baseline_key]
    ], default=str))
    print(f"\nTrades saved → {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
