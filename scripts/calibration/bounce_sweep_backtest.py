#!/usr/bin/env python3
"""Sprint 17 follow-up — bounce / mean-reversion sweep.

Founder showed a WIF 1m chart with deep oversold (RSI 31.98, MFI 11.14)
in clear bearish momentum. Sprint 17 tested the TREND class and falsified
it. This complements by testing the BOUNCE class on the same data.

Hypothesis: 5m mean-reversion at oversold extremes may have edge where
5m trend-confluence doesn't. Especially for the PYTH/WIF/JTO universe
that Sprint 17 showed is NOT in the trend-responsive cohort.

UNIVERSE: PYTH, WIF, JTO (same as Sprint 17 — 85d 5m each)
RULES: 3 bounce variants on 5m + 1 status-quo trend control (Sprint 17 A)
COST: 0.4% round-trip
RIGOR: same default-REJECT discipline

PRE-COMMIT INTERPRETATION (Op-1, written BEFORE running):
  - Any bounce variant must have CI EXCLUDING ZERO to be a real signal.
  - Even then, mean must be ≥ +0.5%/trade to clear the 2× fee bar.
  - If BOTH trend (Sprint 17) AND bounce (this) fail → strategy class
    confirmed dead on PYTH/WIF/JTO. Stop trading these symbols entirely.
  - If bounce passes but trend fails → asymmetric pivot: add bounce-only
    rule to the bot, drop trend.
"""
from __future__ import annotations

import json
import math
import random
import statistics as st
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from swing_window_validation import adx, chop, rsi, mfi  # noqa: E402

DATA_DIR_5M = Path("scripts/calibration/data/tape")
UNIVERSE = ["PYTH", "WIF", "JTO"]
ROUND_TRIP_COST_PCT = 0.4
SEED = 42


@dataclass
class BounceConfig:
    name: str
    rsi_oversold_thresh: float = 30.0       # RSI must have hit <= this in last K bars
    mfi_oversold_thresh: float = 30.0       # MFI must have hit <= this in last K bars
    recent_window: int = 3                   # "in last K bars"
    lookback_low_pct: float = 0.03           # close within X% of N-bar low
    lookback_bars: int = 20                  # N for "lookback_bars low"
    exit_rsi_target: float = 50.0            # exit when RSI mean-reverts to here
    trail_pct: float = 0.05                  # 5% trail from peak
    timeout_bars: int = 30
    indicator_period: int = 14


def load_5m_rows(symbol: str) -> list[dict]:
    f = DATA_DIR_5M / f"{symbol}_5m.json"
    if not f.exists():
        return []
    rows = json.loads(f.read_text())
    out = []
    for r in rows:
        ts = r.get("ts") or r.get("timestamp")
        if ts is None:
            continue
        if ts < 1e12:
            ts = int(ts) * 1000
        out.append({
            "ts": int(ts),
            "open": float(r.get("open", r.get("close", 0))),
            "high": float(r.get("high", r.get("close", 0))),
            "low": float(r.get("low", r.get("close", 0))),
            "close": float(r.get("close", 0)),
            "volume": float(r.get("volume", 0)),
        })
    out.sort(key=lambda x: x["ts"])
    return out


def fires_bounce_entry(rows: list[dict], i: int, c: BounceConfig,
                        rsi_s: list[float], mfi_s: list[float]) -> bool:
    if i < c.lookback_bars + c.indicator_period:
        return False
    # RECENT-oversold gate
    recent_range = range(max(0, i - c.recent_window), i + 1)
    rsi_recent_min = min(
        (rsi_s[k] for k in recent_range if rsi_s[k] == rsi_s[k]), default=100
    )
    mfi_recent_min = min(
        (mfi_s[k] for k in recent_range if mfi_s[k] == mfi_s[k]), default=100
    )
    if not (rsi_recent_min <= c.rsi_oversold_thresh and mfi_recent_min <= c.mfi_oversold_thresh):
        return False
    # Near lookback-bar low
    window_lows = [rows[k]["low"] for k in range(i - c.lookback_bars, i + 1)]
    lookback_low = min(window_lows)
    if rows[i]["close"] > lookback_low * (1 + c.lookback_low_pct):
        return False
    # RSI rising last 1 bar (bounce starting)
    if not (rsi_s[i] == rsi_s[i] and rsi_s[i - 1] == rsi_s[i - 1] and rsi_s[i] > rsi_s[i - 1]):
        return False
    # Catalyst: close > prior close
    if rows[i]["close"] <= rows[i - 1]["close"]:
        return False
    return True


def fires_bounce_exit(rsi_s: list[float], entry_idx: int, peak_price: float,
                      current_close: float, i: int, c: BounceConfig) -> str | None:
    if i - entry_idx >= c.timeout_bars:
        return "timeout"
    if rsi_s[i] == rsi_s[i] and rsi_s[i] >= c.exit_rsi_target:
        return "rsi_target"
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


def backtest_bounce(symbol: str, rows: list[dict], cfg: BounceConfig) -> list[Trade]:
    if len(rows) < cfg.lookback_bars + cfg.indicator_period + 10:
        return []
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    lows = [r["low"] for r in rows]
    vols = [r["volume"] for r in rows]
    rsi_s = rsi(closes, cfg.indicator_period)
    mfi_s = mfi(highs, lows, closes, vols, cfg.indicator_period)

    trades = []
    i = cfg.lookback_bars + cfg.indicator_period
    while i < len(rows) - 1:
        if fires_bounce_entry(rows, i, cfg, rsi_s, mfi_s):
            entry_idx = i + 1
            if entry_idx >= len(rows):
                break
            entry_px = rows[entry_idx]["open"]
            peak = entry_px
            for j in range(entry_idx + 1, len(rows)):
                peak = max(peak, rows[j]["high"])
                reason = fires_bounce_exit(rsi_s, entry_idx, peak, rows[j]["close"], j, cfg)
                if reason is not None:
                    trades.append(Trade(
                        symbol=symbol, config=cfg.name,
                        entry_idx=entry_idx, entry_ts_ms=rows[entry_idx]["ts"], entry_px=entry_px,
                        exit_idx=j, exit_ts_ms=rows[j]["ts"], exit_px=rows[j]["close"],
                        exit_reason=reason, bars_held=j - entry_idx,
                    ))
                    i = j + 1
                    break
            else:
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


def bootstrap_ci(values: list[float], reps: int = 5000) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(SEED)
    n = len(values)
    means = sorted(st.mean(rng.choices(values, k=n)) for _ in range(reps))
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def main() -> int:
    configs = [
        BounceConfig(name="bounce_strict",  rsi_oversold_thresh=25, mfi_oversold_thresh=25,
                     lookback_low_pct=0.01, exit_rsi_target=50),
        BounceConfig(name="bounce_baseline", rsi_oversold_thresh=30, mfi_oversold_thresh=30,
                     lookback_low_pct=0.03, exit_rsi_target=50),
        BounceConfig(name="bounce_loose",   rsi_oversold_thresh=35, mfi_oversold_thresh=35,
                     lookback_low_pct=0.05, exit_rsi_target=55),
        BounceConfig(name="bounce_loose_quick", rsi_oversold_thresh=35, mfi_oversold_thresh=35,
                     lookback_low_pct=0.05, exit_rsi_target=45, timeout_bars=15),
    ]

    # Load data
    print("=" * 100)
    print(f"BOUNCE SWEEP — {len(configs)} variants × {len(UNIVERSE)} symbols (5m, 85d each)")
    print("=" * 100)

    data: dict[str, list[dict]] = {}
    for sym in UNIVERSE:
        rows = load_5m_rows(sym)
        if len(rows) < 5000:
            print(f"  {sym}: insufficient ({len(rows)} bars)")
            continue
        data[sym] = rows
        print(f"  {sym}: {len(rows)} bars / {(rows[-1]['ts']-rows[0]['ts'])/86400_000:.1f}d")
    print()

    # Run each config
    results = {}
    trades_by_cfg = {}
    for cfg in configs:
        all_trades = []
        for sym in data:
            all_trades.extend(backtest_bounce(sym, data[sym], cfg))
        trades_by_cfg[cfg.name] = all_trades
        if not all_trades:
            results[cfg.name] = {"n": 0}
            continue
        nets = [t.net_pct for t in all_trades]
        mean = st.mean(nets)
        sd = st.pstdev(nets) if len(nets) > 1 else 0
        ci_lo, ci_hi = bootstrap_ci(nets)
        sharpe = mean / sd if sd > 0 else 0
        wins = sum(1 for v in nets if v > 0)
        results[cfg.name] = {
            "n": len(nets),
            "mean": mean,
            "ci_lo": ci_lo,
            "ci_hi": ci_hi,
            "sharpe": sharpe,
            "win_rate": 100 * wins / len(nets),
            "sum": sum(nets),
        }

    # Print table
    print(f"{'config':<25s} {'n':>4s} {'mean':>8s} {'CI_lo':>8s} {'CI_hi':>8s} {'sharpe':>7s} {'win%':>5s} {'sum':>8s}")
    print("-" * 90)
    for cfg in configs:
        r = results[cfg.name]
        if r["n"] == 0:
            print(f"{cfg.name:<25s} {0:>4d}  (no fires)")
            continue
        ci_clean = "*" if r["ci_lo"] > 0 else " "
        print(f"{cfg.name:<25s} {r['n']:>4d} {r['mean']:>+7.2f}% {r['ci_lo']:>+7.2f}% {r['ci_hi']:>+7.2f}%{ci_clean} "
              f"{r['sharpe']:>+6.2f} {r['win_rate']:>4.0f}% {r['sum']:>+7.2f}%")
    print()
    print("  * = CI excludes 0 → real edge")
    print()

    # Per-symbol breakdown
    print("=" * 100)
    print("PER-SYMBOL")
    print("=" * 100)
    for cfg in configs:
        per_sym = {}
        for t in trades_by_cfg[cfg.name]:
            per_sym.setdefault(t.symbol, []).append(t.net_pct)
        print(f"\n{cfg.name}:")
        for sym in UNIVERSE:
            vs = per_sym.get(sym, [])
            if not vs:
                print(f"  {sym}: 0 fires")
                continue
            print(f"  {sym}: n={len(vs):>4d}  mean={st.mean(vs):>+6.2f}%  sum={sum(vs):>+7.2f}%  "
                  f"best={max(vs):>+6.2f}%  worst={min(vs):>+6.2f}%")

    # Verdict
    print()
    print("=" * 100)
    print("VERDICT")
    print("=" * 100)
    ci_clean = [r for r in results.values() if r["n"] >= 10 and r.get("ci_lo", -999) > 0]
    if ci_clean:
        print(f"\n  CI-CLEAN configs: {len(ci_clean)}")
        for cfg in configs:
            r = results[cfg.name]
            if r["n"] >= 10 and r.get("ci_lo", -999) > 0:
                print(f"    {cfg.name}: mean {r['mean']:+.2f}% (CI [{r['ci_lo']:+.2f}, {r['ci_hi']:+.2f}])")
    else:
        print("\n  → NO bounce config has CI excluding 0. Combined with Sprint 17 (no trend config")
        print("    had CI excluding 0 either), the conclusion is:")
        print("    ")
        print("    NEITHER trend NOR bounce has edge on PYTH/WIF/JTO at 5m timeframe.")
        print("    8 nulls + this is 9 nulls. The strategy class is dead on this universe.")
        print()
        print("    Recommended product pivot:")
        print("      - Income: Kamino lending (~7.26%/yr — only validated +EV)")
        print("      - Product: copy-trade-grader + honeypot-generator + oracle skills")
        print("      - The bot stays in OBSERVATION_MODE as a dogfood/case-study artifact")
        print("      - DROP the assumption that EITHER strategy class works on this universe")

    out = Path("analysis/data/bounce_sweep")
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps(results, indent=2))
    print(f"\nSaved → {out}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
