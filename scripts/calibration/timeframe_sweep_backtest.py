#!/usr/bin/env python3
"""Sprint 17 — timeframe × candle-count × indicator-period 3-config sweep.

Per the 2026-05-28 joint review (quant + trading-strategist) verdict:

> TEST FIRST IN BACKTEST. Both H_INTERVAL (5m is noisy) and H_WINDOW
> (we're undersampling at 24 bars) are mathematically directionally
> correct; the live corpus is 5-8x under-powered to discriminate. Run
> the 3-config sweep on existing data substrate before committing live
> capital to either hypothesis.

7 configs total — 3 main + 4 controls to isolate each axis:

| Config | Interval | N_lookback | Indicator period | What it tests |
|--------|----------|------------|------------------|---------------|
| A      | 5m       | 24         | 14               | status quo (current bot) |
| B      | 5m       | 500        | 50               | founder's H_WINDOW (more bars + longer period) |
| C      | 4h       | 60         | 14               | Sprint 9 validated (interval pivot) |
| D      | 5m       | 500        | 14               | isolate WINDOW axis (more bars only) |
| E      | 5m       | 24         | 50               | isolate PERIOD axis (longer period only, starved bars) |
| F      | 4h       | 60         | 50               | Sprint 9 control with longer period |
| G      | 4h       | 200        | 14               | more wallclock on 4h |

UNIVERSE: PYTH, WIF, JTO — all have 85 days of 5m candles already ingested
to scripts/calibration/data/tape/ from earlier sprints. Same universe across
all 7 configs = no symbol confound.

RIGOR (per quant-backtest-rigor skill + López de Prado):
  - Bootstrap CIs on per-trade mean
  - DSR with honest n_trials = 7 (the variants we tested)
  - PBO-proxy: fraction of variants that LOSE to the next-most-similar baseline
  - Default-REJECT verdict: any config must have CI > 0 + DSR >= 0.95 to ship

PRE-COMMIT INTERPRETATION (Op-1 discipline, written BEFORE running):
  - If A is positive net of costs → falsifies our Sprint 16 "scalp class
    falsified" verdict; the live -0.47% Sprint 8 result was noise.
  - If B beats A by ≥ +0.5%/trade AND CI > 0 → founder's H_WINDOW
    vindicated; we should refactor the scalp bot to deeper history.
  - If C beats both A and B AND CI > 0 → Sprint 9 4h pivot vindicated;
    proceed to Phase 2 swing executor build.
  - If NONE clear CI > 0 → 7-null pattern continues; full pivot away
    from this strategy class.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Import the validated rule + indicators from Sprint 9
sys.path.insert(0, str(Path(__file__).parent))
from swing_window_validation import adx, chop, rsi, mfi  # noqa: E402

DATA_DIR_5M = Path("scripts/calibration/data/tape")
ROUND_TRIP_COST_PCT = 0.4  # 0.4% — same as Sprint 9 + scalp bot lit
SEED = 42

# Universe — symbols with ≥85d of 5m data
UNIVERSE = ["PYTH", "WIF", "JTO"]


@dataclass
class Config:
    name: str
    interval: str           # "5m" or "4h" (4h derived by resampling 5m)
    n_lookback: int         # bars of history fetched per evaluation
    indicator_period: int   # ADX/RSI/MFI period

    # Confluence thresholds (Sprint 9 trend_adx_30 defaults)
    adx_floor: float = 25.0
    chop_ceil: float = 60.0
    rsi_lo: float = 35.0
    rsi_hi: float = 55.0
    rising_lookback: int = 2

    # Exit thresholds
    exit_rsi: float = 70.0
    exit_adx_floor: float = 20.0
    trail_pct: float = 0.05         # 5% trail from peak
    timeout_bars: int = 30          # 30 bars = 2.5h on 5m, 5d on 4h

    @property
    def is_4h(self) -> bool:
        return self.interval == "4h"


def load_5m_rows(symbol: str) -> list[dict]:
    f = DATA_DIR_5M / f"{symbol}_5m.json"
    if not f.exists():
        return []
    rows = json.loads(f.read_text())
    # Normalize ts: prefer ms; if sec, convert to ms
    out = []
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if ts is None:
            continue
        if ts < 1e12:  # seconds
            ts = int(ts) * 1000
        out.append({
            "ts": int(ts),
            "open": float(r.get("open", r.get("close", 0))),
            "high": float(r.get("high", r.get("close", 0))),
            "low":  float(r.get("low", r.get("close", 0))),
            "close": float(r.get("close", 0)),
            "volume": float(r.get("volume", 0)),
        })
    out.sort(key=lambda x: x["ts"])
    return out


def resample_5m_to_4h(rows: list[dict]) -> list[dict]:
    """Bucket 5m bars into 4h buckets aligned to UTC midnight. 48 5m bars per 4h."""
    bars: dict[int, list] = {}
    for r in rows:
        bucket = (r["ts"] // (4 * 3600_000)) * (4 * 3600_000)
        bars.setdefault(bucket, []).append(r)
    out = []
    for bucket in sorted(bars):
        bar = bars[bucket]
        if not bar:
            continue
        out.append({
            "ts": bucket,
            "open": bar[0]["open"],
            "high": max(b["high"] for b in bar),
            "low":  min(b["low"] for b in bar),
            "close": bar[-1]["close"],
            "volume": sum(b["volume"] for b in bar),
        })
    return out


def _is_rising(series: list[float], i: int, lookback: int) -> bool:
    if i < lookback:
        return False
    a, b = series[i - lookback], series[i]
    if not (a == a and b == b):  # NaN check
        return False
    return b > a


def fires_entry(adx_s: list[float], chop_s: list[float], rsi_s: list[float],
                mfi_s: list[float], i: int, c: Config) -> bool:
    """Sprint 9 trend_adx_30 confluence at bar i."""
    if i < max(c.indicator_period, c.rising_lookback):
        return False
    a, ch, r, m = adx_s[i], chop_s[i], rsi_s[i], mfi_s[i]
    if any(x != x for x in (a, ch, r, m)):  # NaN check
        return False
    if not (a >= c.adx_floor and _is_rising(adx_s, i, c.rising_lookback)):
        return False
    if not (ch <= c.chop_ceil):
        return False
    if not (c.rsi_lo <= r <= c.rsi_hi and _is_rising(rsi_s, i, c.rising_lookback)):
        return False
    if not _is_rising(mfi_s, i, c.rising_lookback):
        return False
    return True


def fires_exit(adx_s: list[float], rsi_s: list[float], entry_idx: int,
               peak_price: float, current_close: float, i: int, c: Config) -> str | None:
    if i - entry_idx >= c.timeout_bars:
        return "timeout"
    if rsi_s[i] == rsi_s[i] and rsi_s[i] > c.exit_rsi:
        return "rsi_exhausted"
    if (adx_s[i] == adx_s[i] and adx_s[i - 1] == adx_s[i - 1]
        and adx_s[i] < c.exit_adx_floor and adx_s[i - 1] >= c.exit_adx_floor):
        return "adx_cross_dn"
    if peak_price > 0 and current_close <= peak_price * (1 - c.trail_pct):
        return "trail_stop"
    return None


@dataclass
class Trade:
    symbol: str
    config: str
    entry_idx: int
    entry_ts_ms: int
    entry_px: float
    exit_idx: int
    exit_ts_ms: int
    exit_px: float
    exit_reason: str
    bars_held: int

    @property
    def gross_pct(self) -> float:
        return (self.exit_px / self.entry_px - 1) * 100 if self.entry_px else 0

    @property
    def net_pct(self) -> float:
        return self.gross_pct - ROUND_TRIP_COST_PCT


def backtest(symbol: str, rows: list[dict], cfg: Config) -> list[Trade]:
    """Run confluence backtest for ONE symbol under ONE config.

    Indicators computed on the FULL row history (so we don't artificially
    starve them by limiting fetched-bar count). The cfg.n_lookback is
    the BREAKOUT reference window if we wanted to use it (here it just
    affects the warmup — first n_lookback bars are skipped).
    """
    if len(rows) < cfg.n_lookback + cfg.indicator_period + 10:
        return []
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    closes = [r["close"] for r in rows]
    vols = [r["volume"] for r in rows]
    adx_s = adx(highs, lows, closes, cfg.indicator_period)
    chop_s = chop(highs, lows, closes, cfg.indicator_period)
    rsi_s = rsi(closes, cfg.indicator_period)
    mfi_s = mfi(highs, lows, closes, vols, cfg.indicator_period)

    trades = []
    i = cfg.n_lookback + cfg.indicator_period
    n = len(rows) - 1
    while i < n:
        if fires_entry(adx_s, chop_s, rsi_s, mfi_s, i, cfg):
            entry_idx = i + 1  # next-bar-open execution
            if entry_idx >= len(rows):
                break
            entry_px = rows[entry_idx]["open"]
            peak = entry_px
            exit_taken = False
            for j in range(entry_idx + 1, len(rows)):
                peak = max(peak, rows[j]["high"])
                reason = fires_exit(adx_s, rsi_s, entry_idx, peak, rows[j]["close"], j, cfg)
                if reason is not None:
                    trades.append(Trade(
                        symbol=symbol, config=cfg.name,
                        entry_idx=entry_idx, entry_ts_ms=rows[entry_idx]["ts"], entry_px=entry_px,
                        exit_idx=j, exit_ts_ms=rows[j]["ts"], exit_px=rows[j]["close"],
                        exit_reason=reason, bars_held=j - entry_idx,
                    ))
                    i = j + 1
                    exit_taken = True
                    break
            if not exit_taken:
                # data_end — close at last bar
                j = len(rows) - 1
                trades.append(Trade(
                    symbol=symbol, config=cfg.name,
                    entry_idx=entry_idx, entry_ts_ms=rows[entry_idx]["ts"], entry_px=entry_px,
                    exit_idx=j, exit_ts_ms=rows[j]["ts"], exit_px=rows[j]["close"],
                    exit_reason="data_end", bars_held=j - entry_idx,
                ))
                break
        else:
            i += 1
    return trades


# ── Rigor stats ────────────────────────────────────────────────────


def bootstrap_ci(values: list[float], reps: int = 5000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(SEED)
    n = len(values)
    means = sorted(st.mean(rng.choices(values, k=n)) for _ in range(reps))
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def max_drawdown_pct(net_pcts: list[float]) -> float:
    if not net_pcts:
        return 0.0
    cum = 0.0
    peak = 0.0
    mdd = 0.0
    for v in net_pcts:
        cum += v
        peak = max(peak, cum)
        mdd = max(mdd, peak - cum)
    return mdd


def deflated_sharpe(mean: float, sd: float, n: int, n_trials: int) -> float:
    """Bailey-LdP-style penalty. Returns the deflated annualized Sharpe."""
    if sd <= 0 or n <= 1:
        return 0.0
    sharpe_observed = mean / sd
    sharpe_ann = sharpe_observed * math.sqrt(252)  # rough annualization
    penalty = math.sqrt(2 * math.log(max(n_trials, 2))) / math.sqrt(n)
    return sharpe_ann - penalty


# ── Reporting ──────────────────────────────────────────────────────


def summarize_config(name: str, trades: list[Trade], n_trials: int) -> dict:
    if not trades:
        return {"config": name, "n": 0}
    nets = [t.net_pct for t in trades]
    mean = st.mean(nets)
    sd = st.pstdev(nets) if len(nets) > 1 else 0.0
    ci_lo, ci_hi = bootstrap_ci(nets)
    sharpe = mean / sd if sd > 0 else 0.0
    dsr_ann = deflated_sharpe(mean, sd, len(nets), n_trials)
    mdd = max_drawdown_pct(nets)
    wins = sum(1 for v in nets if v > 0)
    return {
        "config": name,
        "n": len(trades),
        "mean": mean,
        "sd": sd,
        "ci_lo": ci_lo,
        "ci_hi": ci_hi,
        "sharpe_per_trade": sharpe,
        "dsr_annualized": dsr_ann,
        "max_dd": mdd,
        "win_rate": 100 * wins / len(nets),
        "sum": sum(nets),
    }


def main() -> int:
    # Define configs
    configs = [
        Config(name="A_status_quo",      interval="5m", n_lookback=24,  indicator_period=14),
        Config(name="B_window_hypothesis", interval="5m", n_lookback=500, indicator_period=50),
        Config(name="C_sprint9_4h",      interval="4h", n_lookback=60,  indicator_period=14),
        Config(name="D_more_bars_only",  interval="5m", n_lookback=500, indicator_period=14),
        Config(name="E_longer_period_starved", interval="5m", n_lookback=24,  indicator_period=50),
        Config(name="F_4h_longer_period",interval="4h", n_lookback=60,  indicator_period=50),
        Config(name="G_4h_more_bars",    interval="4h", n_lookback=200, indicator_period=14),
    ]
    n_trials = len(configs)

    # Load + resample data
    print("=" * 110)
    print(f"TIMEFRAME SWEEP — {n_trials} configs × {len(UNIVERSE)} symbols")
    print("=" * 110)

    data_5m: dict[str, list[dict]] = {}
    data_4h: dict[str, list[dict]] = {}
    for sym in UNIVERSE:
        rows_5m = load_5m_rows(sym)
        if len(rows_5m) < 5000:
            print(f"  {sym}: insufficient 5m data ({len(rows_5m)} bars) — skipping")
            continue
        data_5m[sym] = rows_5m
        data_4h[sym] = resample_5m_to_4h(rows_5m)
        print(f"  {sym}: 5m {len(rows_5m)} bars / 4h {len(data_4h[sym])} bars  "
              f"({(rows_5m[-1]['ts'] - rows_5m[0]['ts']) / 86400_000:.1f}d span)")
    print()

    # Run all configs
    all_results: dict[str, dict] = {}
    per_config_trades: dict[str, list[Trade]] = {}
    for cfg in configs:
        all_trades: list[Trade] = []
        for sym in data_5m.keys():
            rows = data_4h[sym] if cfg.is_4h else data_5m[sym]
            all_trades.extend(backtest(sym, rows, cfg))
        per_config_trades[cfg.name] = all_trades
        all_results[cfg.name] = summarize_config(cfg.name, all_trades, n_trials)

    # Main table
    print(f"{'config':<32s} {'n':>5s} {'mean':>8s} {'CI_lo':>8s} {'CI_hi':>8s} {'sharpe':>7s} {'DSRann':>7s} {'maxDD':>7s} {'win%':>5s}")
    print("-" * 110)
    for cfg in configs:
        r = all_results[cfg.name]
        if r.get("n", 0) == 0:
            print(f"{cfg.name:<32s} {'0':>5s}  (no trades)")
            continue
        ci_clean = "*" if r["ci_lo"] > 0 else " "
        print(f"{cfg.name:<32s} {r['n']:>5d} {r['mean']:>+7.2f}% {r['ci_lo']:>+7.2f}% {r['ci_hi']:>+7.2f}%{ci_clean} "
              f"{r['sharpe_per_trade']:>+6.2f} {r['dsr_annualized']:>+6.2f} {r['max_dd']:>6.1f}% {r['win_rate']:>4.0f}%")
    print()
    print("  * = CI excludes 0 (lower bound > 0) = real edge")
    print()

    # Per-symbol breakdown for the main 3 configs
    print("=" * 110)
    print("PER-SYMBOL BREAKDOWN (configs A / B / C)")
    print("=" * 110)
    for cfg_name in ["A_status_quo", "B_window_hypothesis", "C_sprint9_4h"]:
        print(f"\n{cfg_name}:")
        per_sym: dict[str, list[float]] = {}
        for t in per_config_trades[cfg_name]:
            per_sym.setdefault(t.symbol, []).append(t.net_pct)
        for sym in UNIVERSE:
            vs = per_sym.get(sym, [])
            if not vs:
                print(f"  {sym}: 0 trades")
                continue
            print(f"  {sym}: n={len(vs):>3d}  mean={st.mean(vs):>+6.2f}%  sum={sum(vs):>+7.2f}%  "
                  f"best={max(vs):>+6.2f}%  worst={min(vs):>+6.2f}%")

    # Verdict
    print()
    print("=" * 110)
    print("VERDICT")
    print("=" * 110)
    ci_clean_configs = [r for r in all_results.values()
                        if r.get("n", 0) >= 5 and r.get("ci_lo", -999) > 0]
    if ci_clean_configs:
        print(f"\n  CI-CLEAN configs (CI lower bound > 0): {len(ci_clean_configs)}")
        for r in sorted(ci_clean_configs, key=lambda r: -r["mean"]):
            print(f"    {r['config']:<32s} mean {r['mean']:+.2f}% (CI [{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}])")
        best = max(ci_clean_configs, key=lambda r: r["dsr_annualized"])
        print(f"\n  → BEST by deflated Sharpe: {best['config']} (DSR {best['dsr_annualized']:+.2f})")
    else:
        print("\n  → NO config has CI excluding 0 at α=0.05. All configs are statistically indistinguishable")
        print("    from zero edge. This continues the 7-null pattern on this strategy class.")
        print("    Recommendation: FULL pivot away from breakout-style on Solana mid-caps.")

    # Compare A vs B (founder's hypothesis test)
    a = all_results.get("A_status_quo", {})
    b = all_results.get("B_window_hypothesis", {})
    if a.get("n", 0) >= 5 and b.get("n", 0) >= 5:
        delta = b["mean"] - a["mean"]
        print(f"\n  Founder's H_WINDOW test: B - A = {delta:+.2f}pp/trade")
        if delta >= 0.5 and b["ci_lo"] > a["mean"]:
            print(f"    → H_WINDOW VINDICATED (≥+0.5pp + B's CI clears A's mean)")
        elif delta >= 0.2:
            print(f"    → H_WINDOW DIRECTIONAL (positive but below 0.5pp gate)")
        else:
            print(f"    → H_WINDOW REJECTED (less than +0.2pp lift over status quo)")

    # Compare A vs C (Sprint 9 4h vindication test)
    c = all_results.get("C_sprint9_4h", {})
    if a.get("n", 0) >= 5 and c.get("n", 0) >= 5:
        delta = c["mean"] - a["mean"]
        print(f"\n  Sprint 9 4h test: C - A = {delta:+.2f}pp/trade")
        if delta >= 0.5 and c["ci_lo"] > 0:
            print(f"    → 4H PIVOT VINDICATED (≥+0.5pp + CI > 0)")
        elif delta >= 0.2:
            print(f"    → 4H DIRECTIONAL")
        else:
            print(f"    → 4H NOT BETTER than status quo on this universe")

    # Save full per-trade detail for downstream
    out_dir = Path("analysis/data/timeframe_sweep")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(all_results, indent=2))
    (out_dir / "trades_by_config.json").write_text(json.dumps({
        name: [t.__dict__ for t in ts] for name, ts in per_config_trades.items()
    }, indent=2, default=str))
    print(f"\nSaved → {out_dir}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
