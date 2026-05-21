#!/usr/bin/env python3
"""Entry-rule backtest harness (iter-3.10, 2026-05-21).

Compares three entry rules on recent 5m candle history for the live
universe, simulating the live bot's exit stack, and reports a PnL delta:

  OLD       — the shipped test-mode bug: close >= prior 4-bar high * 1.002
  NEW       — the iter-3.10 revert:      close >= prior 24-bar high * 1.015
  PROPOSED  — strategist design:         NEW breakout + adx>=22 + close>ema50
                                         + rsi<68 + mfi>=55  (4 uncorrelated gates)

WHY: the founder caught us entering on noise (0.2% over a 20-min high). This
harness validates the fix + the proposed indicator-gated entry on data, not
vibes (per the strategist: "backtest first, live never-first"). N is small
(get_candles caps at 299 bars ≈ 25h), so treat results as directional and
re-run with deeper history when pagination lands.

Indicators are pure-Python (Wilder's RSI/ATR/ADX, standard EMA/MFI) so the
backtest is reproducible with no per-bar API calls. Exit simulation mirrors
the live bot: TP +4 / SL -3 / trail(activate +2, give 1) / stall_green
(60min +2) / flat_stall (90min, -0.5..+2, no-new-high 30min) / time-stop 12h.

Usage:
    python3 backtest_entry.py                 # default run, all three rules
    python3 backtest_entry.py --sweep         # threshold sweep on PROPOSED
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

sys.path.insert(0, ".")
from onchainos import OnchainOS  # noqa: E402

# ── Universe (live bot's 6 symbols) ────────────────────────────────
UNIVERSE = [
    ("PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"),
    ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
    ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),
    ("BOME", "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82"),
    ("DRIFT", "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7"),
    ("TNSR", "TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6"),
]
BAR = "5m"
BARS_PER_MIN = 1 / 5  # one 5m bar per 5 min

# ── Exit params (mirror the live bot iter-3.x) ─────────────────────
TP_PCT = 4.0
SL_PCT = 3.0
TRAIL_STOP_PCT = 1.0
TRAIL_ACTIVATE_PCT = 2.0
STALL_GREEN_AGE_BARS = 12  # 60 min / 5m
STALL_GREEN_MIN_PCT = 2.0
FLAT_STALL_AGE_BARS = 18  # 90 min / 5m
FLAT_STALL_LO, FLAT_STALL_HI = -0.5, 2.0
FLAT_STALL_NO_NEW_HIGH_BARS = 6  # 30 min / 5m
TIME_STOP_BARS = 144  # 12h / 5m


# ── Pure-Python indicators ─────────────────────────────────────────
def ema(vals: list[float], n: int) -> list[float | None]:
    if len(vals) < n:
        return [None] * len(vals)
    k = 2 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    seed = sum(vals[:n]) / n
    out.append(seed)
    for v in vals[n:]:
        out.append(out[-1] * (1 - k) + v * k)  # type: ignore[operator]
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
            avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        out[i] = 100.0 if avg_l == 0 else 100 - (100 / (1 + rs))
    return out


def _wilder_smooth(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < n:
        return out
    s = sum(vals[:n])
    out[n - 1] = s
    for i in range(n, len(vals)):
        s = s - (s / n) + vals[i]
        out[i] = s
    return out


def adx(highs: list[float], lows: list[float], closes: list[float], n: int = 14) -> list[float | None]:
    m = len(closes)
    out: list[float | None] = [None] * m
    if m < 2 * n:
        return out
    tr, plus_dm, minus_dm = [0.0], [0.0], [0.0]
    for i in range(1, m):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
    atr_s = _wilder_smooth(tr, n)
    pdm_s = _wilder_smooth(plus_dm, n)
    mdm_s = _wilder_smooth(minus_dm, n)
    dx: list[float | None] = [None] * m
    for i in range(m):
        if atr_s[i] and atr_s[i] != 0 and pdm_s[i] is not None and mdm_s[i] is not None:
            pdi = 100 * pdm_s[i] / atr_s[i]
            mdi = 100 * mdm_s[i] / atr_s[i]
            dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
    # ADX = Wilder average of DX
    first = next((i for i, v in enumerate(dx) if v is not None), None)
    if first is None or first + n > m:
        return out
    seed = sum(v for v in dx[first : first + n] if v is not None) / n  # type: ignore[arg-type]
    out[first + n - 1] = seed
    for i in range(first + n, m):
        if dx[i] is not None:
            out[i] = (out[i - 1] * (n - 1) + dx[i]) / n  # type: ignore[operator]
    return out


def mfi(highs, lows, closes, vols, n: int = 14) -> list[float | None]:
    m = len(closes)
    out: list[float | None] = [None] * m
    if m <= n:
        return out
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(m)]
    pos, neg = [0.0], [0.0]
    for i in range(1, m):
        rmf = tp[i] * vols[i]
        if tp[i] > tp[i - 1]:
            pos.append(rmf)
            neg.append(0.0)
        elif tp[i] < tp[i - 1]:
            pos.append(0.0)
            neg.append(rmf)
        else:
            pos.append(0.0)
            neg.append(0.0)
    for i in range(n, m):
        p = sum(pos[i - n + 1 : i + 1])
        ng = sum(neg[i - n + 1 : i + 1])
        out[i] = 100.0 if ng == 0 else 100 - (100 / (1 + p / ng))
    return out


# ── Entry rules ────────────────────────────────────────────────────
def entry_old(c: dict, i: int) -> bool:
    if i < 4:
        return False
    prior_high = max(c["high"][i - 4 : i])
    return prior_high > 0 and (c["close"][i] - prior_high) / prior_high * 100 >= 0.2


def entry_new(c: dict, i: int) -> bool:
    if i < 24:
        return False
    prior_high = max(c["high"][i - 24 : i])
    return prior_high > 0 and (c["close"][i] - prior_high) / prior_high * 100 >= 1.5


def entry_proposed(c: dict, i: int, p: dict) -> bool:
    if not entry_new(c, i):
        return False
    a, e, r, mf = c["adx"][i], c["ema50"][i], c["rsi"][i], c["mfi"][i]
    if a is None or e is None or r is None or mf is None:
        return False
    return (
        a >= p["adx_min"]
        and c["close"][i] > e
        and r < p["rsi_max"]
        and mf >= p["mfi_min"]
    )


# ── Exit simulation (mirrors live bot) ─────────────────────────────
def simulate_exit(c: dict, entry_idx: int) -> float:
    """Walk forward from entry_idx+1, return realized pnl_pct at exit.
    Conservative: if a bar's low hits SL and high hits TP, assume SL first."""
    ep = c["close"][entry_idx]
    if ep <= 0:
        return 0.0
    peak = ep
    last_new_high_bar = entry_idx
    n = len(c["close"])
    for j in range(entry_idx + 1, n):
        hi, lo, cl = c["high"][j], c["low"][j], c["close"][j]
        age = j - entry_idx
        if hi > peak:
            peak = hi
            last_new_high_bar = j
        pnl = (cl - ep) / ep * 100
        peak_pct = (peak - ep) / ep * 100
        no_new_high = j - last_new_high_bar
        # SL (conservative — check before TP)
        if (lo - ep) / ep * 100 <= -SL_PCT:
            return -SL_PCT
        # TP (intrabar touch)
        if (hi - ep) / ep * 100 >= TP_PCT:
            return TP_PCT
        # trail (activate after peak +2%, 1% give-back from peak)
        if peak_pct >= TRAIL_ACTIVATE_PCT:
            if (peak - cl) / peak * 100 >= TRAIL_STOP_PCT:
                return pnl
        # stall_green
        if age >= STALL_GREEN_AGE_BARS and pnl >= STALL_GREEN_MIN_PCT:
            return pnl
        # flat_stall
        if (
            age >= FLAT_STALL_AGE_BARS
            and FLAT_STALL_LO <= pnl <= FLAT_STALL_HI
            and no_new_high >= FLAT_STALL_NO_NEW_HIGH_BARS
        ):
            return pnl
        # time-stop
        if age >= TIME_STOP_BARS:
            return pnl
    # ran out of data — mark to last close (open at end of window)
    return (c["close"][-1] - ep) / ep * 100


# ── Backtest engine ────────────────────────────────────────────────
@dataclass
class RuleResult:
    name: str
    trades: list[float] = field(default_factory=list)

    @property
    def n(self) -> int:
        return len(self.trades)

    @property
    def wins(self) -> int:
        return sum(1 for t in self.trades if t > 0)

    @property
    def total(self) -> float:
        return sum(self.trades)

    @property
    def avg(self) -> float:
        return self.total / self.n if self.n else 0.0


def run_symbol(c: dict, proposed_params: dict) -> dict[str, RuleResult]:
    results = {
        "OLD": RuleResult("OLD"),
        "NEW": RuleResult("NEW"),
        "PROPOSED": RuleResult("PROPOSED"),
    }
    n = len(c["close"])
    # No-overlap: after an entry, skip ahead past its exit (single position per rule).
    for name, fn in (
        ("OLD", lambda i: entry_old(c, i)),
        ("NEW", lambda i: entry_new(c, i)),
        ("PROPOSED", lambda i: entry_proposed(c, i, proposed_params)),
    ):
        i = 50  # warmup for indicators
        while i < n:
            if fn(i):
                pnl = simulate_exit(c, i)
                results[name].trades.append(pnl)
                # advance past a nominal hold to avoid re-entering same move
                i += 6
            else:
                i += 1
    return results


def enrich(candles: list[dict]) -> dict:
    """Build column arrays + indicator series from raw candles."""
    c = {
        "open": [x["open"] for x in candles],
        "high": [x["high"] for x in candles],
        "low": [x["low"] for x in candles],
        "close": [x["close"] for x in candles],
        "volume": [x["volume"] for x in candles],
    }
    c["ema50"] = ema(c["close"], 50)
    c["rsi"] = rsi(c["close"], 14)
    c["adx"] = adx(c["high"], c["low"], c["close"], 14)
    c["mfi"] = mfi(c["high"], c["low"], c["close"], c["volume"], 14)
    return c


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sweep", action="store_true", help="threshold sweep on PROPOSED")
    args = ap.parse_args()

    oc = OnchainOS(chain="solana")
    base_params = {"adx_min": 22.0, "rsi_max": 68.0, "mfi_min": 55.0}

    print(f"Fetching {BAR} candles (max 299/symbol ≈ 25h) for {len(UNIVERSE)} symbols...\n")
    data = {}
    for sym, mint in UNIVERSE:
        candles = oc.get_candles(mint, BAR, limit=299)
        if len(candles) < 60:
            print(f"  {sym}: only {len(candles)} candles — skipping (need ≥60)")
            continue
        data[sym] = enrich(candles)
        print(f"  {sym}: {len(candles)} candles loaded")

    if not data:
        print("\nNo usable data. Aborting.")
        return

    if args.sweep:
        print("\n=== THRESHOLD SWEEP (PROPOSED) ===")
        print(f"{'adx':>4} {'rsi':>4} {'mfi':>4} | {'n':>3} {'win%':>5} {'avg%':>7} {'total%':>8}")
        for adx_min in (18, 22, 26):
            for rsi_max in (65, 68, 72):
                for mfi_min in (50, 55, 60):
                    p = {"adx_min": adx_min, "rsi_max": rsi_max, "mfi_min": mfi_min}
                    agg = RuleResult("P")
                    for c in data.values():
                        agg.trades += run_symbol(c, p)["PROPOSED"].trades
                    wr = 100 * agg.wins / agg.n if agg.n else 0
                    print(f"{adx_min:>4} {rsi_max:>4} {mfi_min:>4} | {agg.n:>3} {wr:>5.0f} {agg.avg:>7.2f} {agg.total:>8.2f}")
        return

    # Default: aggregate the three rules across the universe.
    agg = {"OLD": RuleResult("OLD"), "NEW": RuleResult("NEW"), "PROPOSED": RuleResult("PROPOSED")}
    per_symbol = {}
    for sym, c in data.items():
        res = run_symbol(c, base_params)
        per_symbol[sym] = res
        for k in agg:
            agg[k].trades += res[k].trades

    print("\n=== PER-SYMBOL (signals fired) ===")
    print(f"{'symbol':>8} | {'OLD':>4} {'NEW':>4} {'PROP':>4}")
    for sym, res in per_symbol.items():
        print(f"{sym:>8} | {res['OLD'].n:>4} {res['NEW'].n:>4} {res['PROPOSED'].n:>4}")

    print("\n=== AGGREGATE (all symbols, ~25h of 5m bars) ===")
    print(f"{'rule':>10} | {'signals':>7} {'win%':>5} {'avg%':>7} {'total%':>8}")
    for k in ("OLD", "NEW", "PROPOSED"):
        r = agg[k]
        wr = 100 * r.wins / r.n if r.n else 0
        print(f"{k:>10} | {r.n:>7} {wr:>5.0f} {r.avg:>7.2f} {r.total:>8.2f}")

    print("\n=== DELTA vs OLD ===")
    old_total = agg["OLD"].total
    for k in ("NEW", "PROPOSED"):
        print(f"  {k}: {agg[k].total - old_total:+.2f}% total PnL vs OLD  ({agg[k].n} signals vs {agg['OLD'].n})")

    print(
        "\n⚠ N is small (≈25h window, get_candles caps at 299 bars). Directional only.\n"
        "  Re-run with deeper history (pagination / longer bar) before promoting the\n"
        "  proposed rule to a live sole-gate. See docs/strategy/2026-05-21-entry-quality-fix.md."
    )


if __name__ == "__main__":
    main()
