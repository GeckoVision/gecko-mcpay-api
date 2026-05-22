#!/usr/bin/env python3
"""Chart-floor calibration study (s41, 2026-05-21).

QUESTION (founder): is the live DEX-momentum bot too conservative — declining
candidates that would have won — or well-calibrated? This gates whether we
loosen the chart-confidence entry floor (currently 0.85, raised to 0.92 in a
confirmed-chop regime).

WHAT THIS DOES
  1. Fetches 5m candles (≤299 bars ≈ 24h) for the live universe via the bot's
     OWN onchainos wrapper (byte-faithful to what the bot sees: ascending sort,
     same float coercion, same live-bar inclusion).
  2. Replays the bot's DETERMINISTIC candidate logic at each bar:
       - breakout : close >= prior 24-bar high * (1 + 1.5%)   (ENTRY_PARAMS)
       - volume_spike : vol[-1] >= 1.5 * median(last 24 vols) (VOL_SPIKE_*)
     OR-semantics, exactly like poll_instruments().
  3. For each candidate, computes a CHART-CONFIDENCE PROXY that is faithful to
     chart_analyst's *own* confidence-licensing rules. chart_analyst is an LLM
     (non-deterministic, unreplayable) BUT its prompt anchors confidence to a
     falsifiable, fully-deterministic ladder:
        - momentum-acceleration: 6 boolean cells. 6/6 -> 0.85-0.92,
          5/6 -> 0.80-0.85, <=4/6 -> standard anchors.
        - standard anchors: count of {trend, flow, room, breakout, vol-confirm}
          that align -> 0.50..>0.80.
        - abstain protocol forces conf=0 (thin liq / <24 bars / tight chop).
     We compute exactly those cells from candles. This makes the floor sweep a
     faithful model of "what confidence would chart_analyst license", not a guess.
  4. Determines regime deterministically (ADX>=25 trend / <=18 chop / between
     = transitional) — mirrors regime_analyst + the coordinator chop-modulator.
  5. Simulates the live exit stack (TP4/SL3/trail/stall/time-stop) forward from
     each candidate bar — logic copied (NOT imported) from backtest_entry.py.
  6. Sweeps the chart floor 0.50->0.95. Per floor per regime: how many declines
     flip to entries, would-have-won rate, simulated EV ($/trade at USD_PER_TRADE),
     with BOOTSTRAP 95% CIs and sample sizes.

THE METRIC: decline-counterfactual win-rate + chart-floor EV curve. If EV at a
LOWER floor is higher with NON-OVERLAPPING CIs and adequate N, the bot is too
conservative. Otherwise: hold the floor, collect more data.

This script is READ-ONLY w.r.t. the live bot. It does NOT import or mutate the
running bot module; it only re-uses the pure indicators + the data wrapper.

Usage:
    python3 scripts/calibration/chart_floor_calibration.py
    python3 scripts/calibration/chart_floor_calibration.py --cached candles.json
    python3 scripts/calibration/chart_floor_calibration.py --dump-candles candles.json
"""

from __future__ import annotations

import argparse
import json
import os
import random
import statistics
import sys
from dataclasses import dataclass

# ── Faithful imports from the bot's package (pure / read-only) ──────
# We add contest_bot to the path so `import indicators` and the onchainos
# wrapper resolve to the EXACT code the live bot runs. We do NOT import the
# bot's main module (no globals, no network side effects, no state).
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_CONTEST = os.path.join(_REPO, "contest_bot")
sys.path.insert(0, _CONTEST)

import indicators as ind  # noqa: E402  (the live bot's indicators module)

# ── Live config (mirrored from the bot — single source of truth is the bot;
#    we copy the constants so this script never imports its module) ─────────
UNIVERSE = [
    ("PYTH", "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3"),
    ("WIF", "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"),
    ("POPCAT", "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"),
    ("BOME", "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82"),
    ("DRIFT", "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7"),
    ("TNSR", "TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6"),
]
BAR = "5m"
USD_PER_TRADE = 25.0  # live sizing

# Candidate primitives (jto_..._bot.py)
BREAKOUT_LOOKBACK = 24  # ENTRY_PARAMS lookback_bars
BREAKOUT_CONFIRM_PCT = 1.5  # ENTRY_PARAMS confirm_pct
VOL_SPIKE_MULT = 1.5  # VOL_SPIKE_MULTIPLIER
VOL_SPIKE_BARS = 24  # VOL_SPIKE_AVG_BARS

# Exit stack (backtest_entry.py, mirrors live iter-3.x)
TP_PCT = 4.0
SL_PCT = 3.0
TRAIL_STOP_PCT = 1.0
TRAIL_ACTIVATE_PCT = 2.0
STALL_GREEN_AGE_BARS = 12
STALL_GREEN_MIN_PCT = 2.0
FLAT_STALL_AGE_BARS = 18
FLAT_STALL_LO, FLAT_STALL_HI = -0.5, 2.0
FLAT_STALL_NO_NEW_HIGH_BARS = 6
TIME_STOP_BARS = 144

# Regime thresholds (regime_analyst + coordinator B6)
ADX_TREND = 25.0
ADX_CHOP = 18.0
CHART_FLOOR_NORMAL = 0.85
CHART_FLOOR_CHOP = 0.92

# chart_analyst abstain protocol (faithful subset that is deterministic)
ABSTAIN_TIGHT_RANGE_24H_PCT = 1.0  # 24h range < 1% => abstain
ABSTAIN_MAX_ZERO_VOL_BARS = 4  # >4 zero-vol bars in last 30 => abstain
MIN_BARS = 24

WARMUP = 50  # bars before we trust ADX(14)/EMA(50)

FLOOR_SWEEP = [0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.90, 0.95]
N_BOOTSTRAP = 5000
RNG_SEED = 1729


# ── Data ────────────────────────────────────────────────────────────
def fetch_candles() -> dict[str, list[dict]]:
    """Fetch via the bot's OWN wrapper so data is byte-faithful."""
    from onchainos import OnchainOS

    oc = OnchainOS(chain="solana")
    out: dict[str, list[dict]] = {}
    for sym, mint in UNIVERSE:
        candles = oc.get_candles(mint, BAR, limit=299)
        out[sym] = candles
        print(f"  {sym}: {len(candles)} candles", file=sys.stderr)
    return out


# ── Candidate detection (faithful to the live bot) ─────────────────
def _median(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def breakout_fires(c: dict, i: int) -> bool:
    """close[i] >= prior 24-bar high * (1 + confirm%). Mirrors evaluate_breakout
    which uses candles[-(lookback+1):-1] as prior and candles[-1] as recent."""
    if i < BREAKOUT_LOOKBACK:
        return False
    prior = c["high"][i - BREAKOUT_LOOKBACK : i]
    prior_high = max(prior) if prior else 0.0
    if prior_high <= 0:
        return False
    delta_pct = (c["close"][i] - prior_high) / prior_high * 100.0
    return delta_pct >= BREAKOUT_CONFIRM_PCT


def volume_spike_fires(c: dict, i: int) -> bool:
    """vol[i] >= mult * median(last N vols incl. i). Mirrors evaluate_volume_spike
    which uses candles[-N:] window and compares the last element."""
    if i < 1:
        return False
    lo = max(0, i - VOL_SPIKE_BARS + 1)
    window = c["volume"][lo : i + 1]
    if not window:
        return False
    med = _median(window)
    if med <= 0:
        return False
    return c["volume"][i] >= VOL_SPIKE_MULT * med


# ── Chart-confidence proxy (faithful to chart_analyst licensing) ────
def chart_abstains(c: dict, i: int) -> bool:
    """Deterministic subset of chart_analyst's abstain protocol."""
    if i + 1 < MIN_BARS:
        return True
    last30 = range(max(0, i - 29), i + 1)
    zero_vol = sum(1 for j in last30 if c["volume"][j] == 0.0)
    if zero_vol > ABSTAIN_MAX_ZERO_VOL_BARS:
        return True
    # 24h range proxy: last 288 bars (24h of 5m). If <1%, tight chop -> abstain.
    lo = max(0, i - 287)
    hh = max(c["high"][lo : i + 1])
    ll = min(c["low"][lo : i + 1])
    rng = (hh - ll) / ll * 100.0 if ll > 0 else 0.0
    return rng < ABSTAIN_TIGHT_RANGE_24H_PCT


def momentum_cells(c: dict, i: int) -> int:
    """Count the 6 momentum-acceleration cells from chart_analyst's prompt
    (lines 92-103). All deterministic from candles."""
    if i < 24:
        return 0
    o, h, low, cl, v = c["open"], c["high"], c["low"], c["close"], c["volume"]
    cells = 0
    # Cell 1: last 3 bars all green (close>open on t-2,t-1,t)
    if cl[i] > o[i] and cl[i - 1] > o[i - 1] and cl[i - 2] > o[i - 2]:
        cells += 1
    # Cell 2: volume rising over 3 bars OR vol[t] > 1.5x median(last 6)
    med6 = _median(v[i - 5 : i + 1])
    if (v[i] > v[i - 1] > v[i - 2]) or (med6 > 0 and v[i] > 1.5 * med6):
        cells += 1
    # Cell 3: fresh higher-high — high[i] > trailing-24-bar high BEFORE bar i,
    # crossing within last 3 bars (i.e. one of i-2..i first to clear it).
    prior24_high = max(h[i - 24 : i])
    crossed_recent = any(h[k] > max(h[k - 24 : k]) for k in (i, i - 1, i - 2))
    if h[i] > prior24_high and crossed_recent:
        cells += 1
    # Cell 4: close > 24h midpoint
    lo24 = max(0, i - 287)
    mid = 0.5 * (max(h[lo24 : i + 1]) + min(low[lo24 : i + 1]))
    if cl[i] > mid:
        cells += 1
    # Cell 5: not tight chop — 24h range >= 2%
    ll = min(low[lo24 : i + 1])
    hh = max(h[lo24 : i + 1])
    rng = (hh - ll) / ll * 100.0 if ll > 0 else 0.0
    if rng >= 2.0:
        cells += 1
    # Cell 6: abstain protocol clean
    if not chart_abstains(c, i):
        cells += 1
    return cells


def standard_anchor_aligned(c: dict, i: int) -> int:
    """Count of the 5 standard gradings that align (chart_analyst anchors,
    lines 56-63 + 134-138): trend(adx>=25 & ema stacked), flow(mfi>=55),
    room(rsi<72), breakout posture (cleared 24-bar high), vol confirm
    (breakout-bar vol > 6-bar median)."""
    aligned = 0
    a = c["adx"][i]
    e9, e21, e50 = c["ema9"][i], c["ema21"][i], c["ema50"][i]
    r = c["rsi"][i]
    mf = c["mfi"][i]
    # trend
    stacked = e9 is not None and e21 is not None and e50 is not None and e9 > e21 > e50
    if a is not None and a >= ADX_TREND and stacked:
        aligned += 1
    # flow
    if mf is not None and mf >= 55:
        aligned += 1
    # room
    if r is not None and r < 72:
        aligned += 1
    # breakout posture
    if i >= 24 and c["close"][i] > max(c["high"][i - 24 : i]):
        aligned += 1
    # volume confirm
    med6 = _median(c["volume"][i - 5 : i + 1]) if i >= 5 else 0.0
    if med6 > 0 and c["volume"][i] > med6:
        aligned += 1
    return aligned


def chart_confidence_proxy(c: dict, i: int) -> float:
    """Faithful deterministic model of chart_analyst's licensed confidence.

    Returns 0.0 if the abstain protocol fires (chart_analyst would abstain,
    confidence=0). Otherwise applies the momentum-acceleration licensing ladder
    when applicable, else the standard anchors. We use the MIDPOINT of each
    licensed band as the point estimate (the model is told it 'may reach' the
    top of a band — midpoint is the unbiased central read)."""
    if chart_abstains(c, i):
        return 0.0
    # Need indicators present
    if c["adx"][i] is None or c["rsi"][i] is None or c["mfi"][i] is None:
        return 0.0

    cells = momentum_cells(c, i)
    if cells == 6:
        return 0.885  # band 0.85-0.92 midpoint
    if cells == 5:
        return 0.825  # band 0.80-0.85 midpoint
    # <=4 cells -> standard anchors
    aligned = standard_anchor_aligned(c, i)
    if aligned >= 4:
        return 0.81  # ">0.80 exceptional, use sparingly" -> just above floor
    if aligned == 3:
        return 0.75  # 0.70-0.80 strong (incl volume)
    if aligned == 2:
        return 0.65  # 0.60-0.70 clean lean
    if aligned == 1:
        return 0.55  # 0.50-0.60 soft lean
    return 0.40  # no grading aligns -> below soft-lean, neutral-ish


def chart_verdict_bullish(c: dict, i: int) -> bool:
    """chart_analyst returns bullish only when the setup leans up. We proxy
    'bullish-eligible' as: not abstaining AND price posture up (close>ema21
    OR cleared 24-bar high). A bearish/neutral chart never passes the floor
    regardless of confidence, so this gates entry too."""
    if chart_abstains(c, i):
        return False
    e21 = c["ema21"][i]
    cleared = i >= 24 and c["close"][i] > max(c["high"][i - 24 : i])
    return cleared or (e21 is not None and c["close"][i] > e21)


# ── Regime (deterministic, mirrors regime_analyst) ─────────────────
def regime_at(c: dict, i: int) -> str:
    a = c["adx"][i]
    if a is None:
        return "transitional"
    if a >= ADX_TREND:
        return "trend"
    if a <= ADX_CHOP:
        return "chop"
    return "transitional"


def regime_confident_chop(c: dict, i: int) -> bool:
    """regime_analyst is 'bearish & conf>=0.6' (the coordinator's chop-modulator
    trigger). Its conf formula: min(0.85, 0.55 + (18-adx)/40). conf>=0.6 needs
    18-adx >= 2 => adx <= 16.0."""
    a = c["adx"][i]
    return a is not None and a <= 16.0


def effective_floor(c: dict, i: int) -> float:
    return CHART_FLOOR_CHOP if regime_confident_chop(c, i) else CHART_FLOOR_NORMAL


# ── Exit simulation (copied from backtest_entry.py — NOT imported) ──
def simulate_exit(c: dict, entry_idx: int) -> float:
    """Forward-walk realized pnl_pct. Conservative: SL checked before TP on a
    bar that straddles both. Identical logic to backtest_entry.simulate_exit."""
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
        if (lo - ep) / ep * 100 <= -SL_PCT:
            return -SL_PCT
        if (hi - ep) / ep * 100 >= TP_PCT:
            return TP_PCT
        if peak_pct >= TRAIL_ACTIVATE_PCT:  # noqa: SIM102  (verbatim from backtest_entry.simulate_exit — keep faithful)
            if (peak - cl) / peak * 100 >= TRAIL_STOP_PCT:
                return pnl
        if age >= STALL_GREEN_AGE_BARS and pnl >= STALL_GREEN_MIN_PCT:
            return pnl
        if (
            age >= FLAT_STALL_AGE_BARS
            and FLAT_STALL_LO <= pnl <= FLAT_STALL_HI
            and no_new_high >= FLAT_STALL_NO_NEW_HIGH_BARS
        ):
            return pnl
        if age >= TIME_STOP_BARS:
            return pnl
    return (c["close"][-1] - ep) / ep * 100


def has_full_horizon(c: dict, entry_idx: int, min_bars: int = 18) -> bool:
    """Censoring guard: a candidate too close to the end of the window can't be
    fairly forward-simulated (it would mark-to-last-close, biasing toward ~0).
    Require at least `min_bars` of forward data (90 min = the flat-stall horizon)."""
    return (len(c["close"]) - 1 - entry_idx) >= min_bars


# ── Enrichment ──────────────────────────────────────────────────────
def enrich(candles: list[dict]) -> dict:
    c = {
        "ts": [x["ts"] for x in candles],
        "open": [x["open"] for x in candles],
        "high": [x["high"] for x in candles],
        "low": [x["low"] for x in candles],
        "close": [x["close"] for x in candles],
        "volume": [x["volume"] for x in candles],
    }
    cl, h, low, vol = c["close"], c["high"], c["low"], c["volume"]
    c["ema9"] = ind.ema(cl, 9)
    c["ema21"] = ind.ema(cl, 21)
    c["ema50"] = ind.ema(cl, 50)
    c["rsi"] = ind.rsi(cl, 14)
    c["adx"] = ind.adx(h, low, cl, 14)
    c["mfi"] = ind.mfi(h, low, cl, vol, 14)
    return c


# ── Candidate collection ────────────────────────────────────────────
@dataclass
class Candidate:
    sym: str
    idx: int
    proxy_conf: float
    chart_bullish: bool
    regime: str
    floor: float  # effective floor at this bar (0.85 or 0.92)
    pnl_pct: float  # forward-simulated realized pnl
    won: bool  # hit TP (+4) before SL (-3) — won = pnl >= TP_PCT


def collect_candidates(data: dict[str, dict]) -> list[Candidate]:
    cands: list[Candidate] = []
    for sym, c in data.items():
        n = len(c["close"])
        i = WARMUP
        while i < n:
            fires = breakout_fires(c, i) or volume_spike_fires(c, i)
            if fires and has_full_horizon(c, i):
                pnl = simulate_exit(c, i)
                cands.append(
                    Candidate(
                        sym=sym,
                        idx=i,
                        proxy_conf=chart_confidence_proxy(c, i),
                        chart_bullish=chart_verdict_bullish(c, i),
                        regime=regime_at(c, i),
                        floor=effective_floor(c, i),
                        pnl_pct=pnl,
                        won=pnl >= TP_PCT,
                    )
                )
                i += 6  # no-overlap, mirrors backtest run_symbol
            else:
                i += 1
    return cands


# ── Bootstrap CI ────────────────────────────────────────────────────
def bootstrap_ci(vals: list[float], stat=statistics.mean, n_boot=N_BOOTSTRAP, alpha=0.05):
    if not vals:
        return (float("nan"), float("nan"), float("nan"))
    rng = random.Random(RNG_SEED)
    point = stat(vals)
    if len(vals) == 1:
        return (point, point, point)
    boots = []
    m = len(vals)
    for _ in range(n_boot):
        sample = [vals[rng.randrange(m)] for _ in range(m)]
        boots.append(stat(sample))
    boots.sort()
    lo = boots[int((alpha / 2) * n_boot)]
    hi = boots[int((1 - alpha / 2) * n_boot)]
    return (point, lo, hi)


# ── Floor sweep ─────────────────────────────────────────────────────
@dataclass
class FloorRow:
    floor: float
    regime: str
    n_entries: int
    win_rate: float
    win_lo: float
    win_hi: float
    ev_pct: float
    ev_lo: float
    ev_hi: float
    ev_usd: float


def entries_at_floor(
    cands: list[Candidate], floor_override: float | None, regime_filter: str | None
) -> list[Candidate]:
    """A candidate ENTERS at a swept floor if chart is bullish-eligible AND
    proxy_conf >= the floor. When floor_override is given we apply it uniformly
    (the swept parameter) but STILL respect the chop-modulator: in confident
    chop the floor is max(override, 0.92) only if we're modeling the *current*
    policy. For the pure sweep we apply the override as the normal floor and
    keep the chop bump relative — but simplest+faithful: sweep replaces the
    NORMAL floor; chop floor stays at +0.07 above it (mirrors 0.85->0.92 gap)."""
    out = []
    for cand in cands:
        if regime_filter and cand.regime != regime_filter:
            continue
        if not cand.chart_bullish:
            continue
        if floor_override is None:
            f = cand.floor  # current policy
        else:
            # chop bump preserved as +0.07 (0.92-0.85) above the swept normal floor
            chop = regime_confident_chop_from_regime(cand)
            f = min(0.99, floor_override + 0.07) if chop else floor_override
        if cand.proxy_conf >= f:
            out.append(cand)
    return out


def regime_confident_chop_from_regime(cand: Candidate) -> bool:
    # We stored floor=0.92 exactly when regime_confident_chop was true at collect.
    return abs(cand.floor - CHART_FLOOR_CHOP) < 1e-9


def sweep(cands: list[Candidate]) -> list[FloorRow]:
    rows: list[FloorRow] = []
    regimes = [None, "trend", "chop", "transitional"]
    for floor in FLOOR_SWEEP:
        for rg in regimes:
            ent = entries_at_floor(cands, floor, rg)
            n = len(ent)
            wins = [1.0 if cand.won else 0.0 for cand in ent]
            pnls = [cand.pnl_pct for cand in ent]
            wr, wlo, whi = bootstrap_ci(wins) if wins else (float("nan"),) * 3
            ev, elo, ehi = bootstrap_ci(pnls) if pnls else (float("nan"),) * 3
            rows.append(
                FloorRow(
                    floor=floor,
                    regime=rg or "ALL",
                    n_entries=n,
                    win_rate=wr,
                    win_lo=wlo,
                    win_hi=whi,
                    ev_pct=ev,
                    ev_lo=elo,
                    ev_hi=ehi,
                    ev_usd=(ev / 100 * USD_PER_TRADE) if ev == ev else float("nan"),
                )
            )
    return rows


# ── Reporting ───────────────────────────────────────────────────────
def fmt_pct(x: float) -> str:
    return "  nan" if x != x else f"{x:+.2f}"


def fmt_rate(x: float) -> str:
    return " nan" if x != x else f"{x * 100:.0f}%"


def print_window_summary(data: dict[str, dict]) -> None:
    print("\n=== DATA WINDOW ===")
    for sym, c in data.items():
        n = len(c["close"])
        if n < 2:
            print(f"  {sym}: {n} bars (UNUSABLE)")
            continue
        span_h = (c["ts"][-1] - c["ts"][0]) / 1000 / 3600
        adx_vals = [a for a in c["adx"] if a is not None]
        med_adx = statistics.median(adx_vals) if adx_vals else float("nan")
        trend = sum(1 for a in adx_vals if a >= ADX_TREND)
        chop = sum(1 for a in adx_vals if a <= ADX_CHOP)
        trans = len(adx_vals) - trend - chop
        print(
            f"  {sym}: {n} bars, {span_h:.1f}h | median ADX={med_adx:.1f} | "
            f"bars trend/chop/trans = {trend}/{chop}/{trans}"
        )


def print_candidate_summary(cands: list[Candidate]) -> None:
    print("\n=== CANDIDATES (deterministic gate, full-horizon only) ===")
    by_reg: dict[str, list[Candidate]] = {}
    for cand in cands:
        by_reg.setdefault(cand.regime, []).append(cand)
    print(f"  total candidates: {len(cands)}")
    for rg, lst in sorted(by_reg.items()):
        wins = sum(1 for x in lst if x.won)
        avg = statistics.mean([x.pnl_pct for x in lst]) if lst else 0.0
        print(
            f"    {rg:>13}: n={len(lst):>3}  raw-would-win={wins}/{len(lst)} "
            f"({100 * wins / len(lst) if lst else 0:.0f}%)  avg pnl={avg:+.2f}%"
        )
    confs = [cand.proxy_conf for cand in cands]
    if confs:
        print(
            f"  proxy-conf distribution: min={min(confs):.2f} "
            f"median={statistics.median(confs):.2f} max={max(confs):.2f}"
        )
        for thr in (0.85, 0.80, 0.75):
            print(f"    candidates with proxy_conf >= {thr}: {sum(1 for x in confs if x >= thr)}")


def print_sweep(rows: list[FloorRow]) -> None:
    print("\n=== CHART-FLOOR SWEEP — would-have-won rate + EV (95% bootstrap CI) ===")
    print("  EV is per-trade realized pnl%; EV$ at USD_PER_TRADE=$25.\n")
    hdr = (
        f"{'floor':>6} {'regime':>13} {'N':>4} | {'winRate':>8} "
        f"{'win 95% CI':>16} | {'EV%':>7} {'EV% 95% CI':>18} | {'EV$':>7}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        wci = f"[{fmt_rate(r.win_lo)},{fmt_rate(r.win_hi)}]" if r.n_entries else "  —"
        eci = f"[{fmt_pct(r.ev_lo)},{fmt_pct(r.ev_hi)}]" if r.n_entries else "  —"
        evusd = "   —" if r.ev_usd != r.ev_usd else f"{r.ev_usd:+.2f}"
        print(
            f"{r.floor:>6.2f} {r.regime:>13} {r.n_entries:>4} | "
            f"{fmt_rate(r.win_rate):>8} {wci:>16} | "
            f"{fmt_pct(r.ev_pct):>7} {eci:>18} | {evusd:>7}"
        )


def emit_json(data, cands, rows, path) -> None:
    out = {
        "generated": "2026-05-21",
        "universe": [s for s, _ in UNIVERSE],
        "bar": BAR,
        "usd_per_trade": USD_PER_TRADE,
        "config": {
            "chart_floor_normal": CHART_FLOOR_NORMAL,
            "chart_floor_chop": CHART_FLOOR_CHOP,
            "breakout_lookback": BREAKOUT_LOOKBACK,
            "breakout_confirm_pct": BREAKOUT_CONFIRM_PCT,
            "vol_spike_mult": VOL_SPIKE_MULT,
        },
        "window": {
            sym: {
                "bars": len(c["close"]),
                "span_h": (c["ts"][-1] - c["ts"][0]) / 1000 / 3600 if len(c["ts"]) > 1 else 0,
            }
            for sym, c in data.items()
        },
        "n_candidates": len(cands),
        "sweep": [
            {
                "floor": r.floor,
                "regime": r.regime,
                "n": r.n_entries,
                "win_rate": r.win_rate,
                "win_ci": [r.win_lo, r.win_hi],
                "ev_pct": r.ev_pct,
                "ev_ci": [r.ev_lo, r.ev_hi],
                "ev_usd": r.ev_usd,
            }
            for r in rows
        ],
    }
    with open(path, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nWrote {path}", file=sys.stderr)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cached", help="load raw candles from JSON instead of fetching")
    ap.add_argument("--dump-candles", help="dump fetched raw candles to JSON")
    ap.add_argument("--json-out", default=None, help="write results JSON")
    args = ap.parse_args()

    if args.cached:
        with open(args.cached) as f:
            raw = json.load(f)
        print(f"Loaded cached candles from {args.cached}", file=sys.stderr)
    else:
        print("Fetching candles via the bot's onchainos wrapper...", file=sys.stderr)
        raw = fetch_candles()
        if args.dump_candles:
            with open(args.dump_candles, "w") as f:
                json.dump(raw, f)
            print(f"Dumped raw candles to {args.dump_candles}", file=sys.stderr)

    data = {sym: enrich(candles) for sym, candles in raw.items() if len(candles) >= 60}
    skipped = [sym for sym, candles in raw.items() if len(candles) < 60]
    if skipped:
        print(f"  skipped (<60 bars): {skipped}", file=sys.stderr)
    if not data:
        print("No usable data. Aborting.", file=sys.stderr)
        sys.exit(2)

    print_window_summary(data)
    cands = collect_candidates(data)
    print_candidate_summary(cands)
    rows = sweep(cands)
    print_sweep(rows)

    if args.json_out:
        emit_json(data, cands, rows, args.json_out)


if __name__ == "__main__":
    main()
