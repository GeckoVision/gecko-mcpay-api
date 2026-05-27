#!/usr/bin/env python3
"""Shadow exit-logic counterfactual on the 20-trade autopsy.

Per the 2026-05-27 four-agent synthesis (`private/strategy/2026-05-27-four-agent-synthesis.md`):
trading-strategist identified EXIT HYGIENE as the dominant loss driver:
    trailing_stop n=3 mean -2.18%/trade  (peaks were +1.0% to +1.7% then gave back ALL)
    stop_loss     n=3 mean -3.08%/trade
    flat_stall    n=8 mean +0.02%/trade  (scratch — was green at peak then exited flat)
    take_profit   n=4 mean +0.86%/trade  (the only +EV bucket)
    stall_green   n=2 mean +1.40%/trade

This script replays the 20 actual closes through 6 alternate exit policies and reports
per-policy mean/sum/CI. Inputs: bot_state.json (entry, peak, exit, reason, tp_pct).

PRE-COMMIT INTERPRETATION (Op-1 discipline, written BEFORE running):
  - Baseline: mean -0.47%, sum -9.37% (current actual)
  - Policy X "ship-worthy" IFF: mean ≥ baseline + 0.5pp AND CI lower bound ≥ baseline mean
  - Policy X "directionally promising" IFF: mean ≥ baseline + 0.5pp (CI may straddle at N=20)
  - Policy X "no-improvement" IFF: |mean - baseline| < 0.5pp
  - Policy X "WORSE" IFF: mean ≤ baseline - 0.5pp

Default-REJECT: at N=20 we cannot ship any policy from this harness — per quant-analyst,
MIN VALIDATION N = 79 per arm. This script PRIORITIZES which policy goes to live paper A/B.
"""
from __future__ import annotations

import json
import random
import statistics as st
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Close:
    symbol: str
    entry: float
    peak: float
    exit_actual: float
    reason: str
    tp_pct_set: float
    pnl_actual: float

    @property
    def peak_ret(self) -> float:
        """peak/entry - 1, as fraction."""
        return (self.peak / self.entry - 1) if self.entry else 0.0

    @property
    def exit_ret(self) -> float:
        return (self.exit_actual / self.entry - 1) if self.entry else 0.0


def load_closes(path: str = "contest_bot/bot_state.json") -> list[Close]:
    s = json.load(open(path))
    closes = []
    for p in s.get("positions", []):
        if p.get("status") != "closed":
            continue
        e = p.get("entry_price") or 0
        pk = p.get("peak_price") or e
        ex = p.get("exit_price") or e
        if not e:
            continue
        closes.append(
            Close(
                symbol=p.get("symbol", "?"),
                entry=e,
                peak=pk,
                exit_actual=ex,
                reason=p.get("exit_reason", "?"),
                tp_pct_set=p.get("tp_pct") or 0,
                pnl_actual=p.get("pnl_pct") or 0,
            )
        )
    return closes


# ── Exit policies — each returns counterfactual return as fraction ──────


def policy_baseline(c: Close) -> tuple[str, float]:
    """As-is."""
    return c.reason, c.exit_ret


def policy_tight_trail_03(c: Close) -> tuple[str, float]:
    """Trailing stop with 0.3% trail-back from peak (vs current 0.5%)."""
    if c.peak_ret < 0.005:  # never armed trailing
        # fall through to actual reason
        if c.reason == "stop_loss":
            return "stop_loss", c.exit_ret  # SL still fires
        if c.reason == "take_profit":
            return "take_profit", c.exit_ret  # TP still fires
        # else: position would have stalled out — use actual
        return f"fallback:{c.reason}", c.exit_ret
    # peak ≥ 0.5%; tight trail kicks in
    if c.reason == "take_profit":
        # TP hit before trail — TP wins
        return "take_profit", c.exit_ret
    # trail at peak - 0.3% (in fraction): exit = peak * (1 - 0.003)
    trail_exit_ret = c.peak_ret - 0.003
    return "tight_trail_03", trail_exit_ret


def policy_fixed_tp_06(c: Close) -> tuple[str, float]:
    """Force TP at +0.6% on every trade. Exit at +0.6% if peak ≥ 0.6%; else actual."""
    if c.peak_ret >= 0.006:
        # TP would have fired at +0.6%
        # but stop_loss might have fired first if entry → -SL before reaching peak
        # approximation: peak comes BEFORE exit_ts in most cases; assume TP fires
        return "forced_tp_06", 0.006
    # peak < 0.6% — never hit; fall to actual logic
    return f"fallback:{c.reason}", c.exit_ret


def policy_kill_stall(c: Close) -> tuple[str, float]:
    """Remove flat_stall_exit. Keep TP/SL/trailing. flat_stall closes hold longer."""
    if c.reason == "flat_stall_exit":
        # would have either (a) eventually hit a trail / TP / SL, or (b) timed out
        # approximation: assume held to peak (best case for stall-was-green)
        # OR held to current exit (worst case)
        # midpoint: hold to (peak + actual) / 2
        cf = (c.peak_ret + c.exit_ret) / 2
        return "stall_killed_midpoint", cf
    return c.reason, c.exit_ret


def policy_tp_or_sl_only(c: Close) -> tuple[str, float]:
    """Allow ONLY TP (forced at +0.6%) and SL (at -2%). Kill trailing + stall."""
    # SL fires first if it would
    # we don't have intra-bar data — heuristic: if actual was stop_loss, SL fires here too
    if c.reason == "stop_loss":
        return "stop_loss", c.exit_ret  # actual SL ≈ -3%, we'd cap at -2%
    if c.peak_ret >= 0.006:
        return "tp_only_06", 0.006
    # neither fired; we'd hold until... what? End of day. Use actual.
    return f"hold:{c.reason}", c.exit_ret


def policy_tight_trail_05_no_stall(c: Close) -> tuple[str, float]:
    """Combine current trail 0.5% with stall-kill."""
    if c.reason == "stop_loss":
        return "stop_loss", c.exit_ret
    if c.reason == "take_profit":
        return "take_profit", c.exit_ret
    # else: enforce 0.5% trail if peak armed it
    if c.peak_ret >= 0.005:
        trail_exit_ret = c.peak_ret - 0.005
        return "trail_05", trail_exit_ret
    # peak < 0.5% — held flat, use stall midpoint as least-info
    return "fallback_midpoint", (c.peak_ret + c.exit_ret) / 2


POLICIES = [
    ("baseline", policy_baseline),
    ("tight_trail_03", policy_tight_trail_03),
    ("fixed_tp_06", policy_fixed_tp_06),
    ("kill_stall", policy_kill_stall),
    ("tp_or_sl_only", policy_tp_or_sl_only),
    ("trail_05_no_stall", policy_tight_trail_05_no_stall),
]


def bootstrap_ci(values: list[float], reps: int = 10_000, seed: int = 42) -> tuple[float, float]:
    if not values:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(values)
    means = [st.mean(rng.choices(values, k=n)) for _ in range(reps)]
    means.sort()
    return (means[int(0.025 * reps)], means[int(0.975 * reps)])


def permutation_test(a: list[float], b: list[float], reps: int = 10_000, seed: int = 42) -> float:
    """Two-sided permutation p-value for mean(a) - mean(b)."""
    if not a or not b:
        return 1.0
    rng = random.Random(seed)
    obs = abs(st.mean(a) - st.mean(b))
    pool = a + b
    n_a = len(a)
    hits = 0
    for _ in range(reps):
        rng.shuffle(pool)
        d = abs(st.mean(pool[:n_a]) - st.mean(pool[n_a:]))
        if d >= obs:
            hits += 1
    return hits / reps


def main() -> int:
    closes = load_closes()
    print("=" * 100)
    print(f"SHADOW EXIT-LOGIC COUNTERFACTUAL  (N={len(closes)})")
    print("=" * 100)
    print()

    # ── Per-position table per policy ──
    print(f"{'symbol':<11s} {'actual':<22s} {'pk%':>7s} {'ex%':>7s}  " + "  ".join(f"{p:<22s}" for p, _ in POLICIES[1:]))
    rows_per_policy: dict[str, list[float]] = defaultdict(list)
    for c in closes:
        rows_per_policy["baseline"].append(c.pnl_actual)
        line = f"{c.symbol:<11s} {c.reason:<22s} {100*c.peak_ret:>+6.2f} {100*c.exit_ret:>+6.2f}  "
        for name, fn in POLICIES[1:]:
            reason_cf, ret_cf = fn(c)
            rows_per_policy[name].append(100 * ret_cf)
            line += f"{reason_cf:<10s}{100*ret_cf:>+6.2f}%       "
        print(line)
    print()

    # ── Summary table ──
    print("=" * 100)
    print(f"{'policy':<22s} {'N':>3s} {'mean':>8s} {'sum':>8s} {'95% CI':>20s} {'win%':>6s} {'perm-p vs base':>16s}")
    print("-" * 100)
    base = rows_per_policy["baseline"]
    base_mean = st.mean(base)
    for name, _ in POLICIES:
        vs = rows_per_policy[name]
        m = st.mean(vs)
        s = sum(vs)
        ci_lo, ci_hi = bootstrap_ci(vs)
        wr = 100 * sum(1 for v in vs if v >= 0.5) / len(vs)
        p = "-" if name == "baseline" else f"{permutation_test(vs, base):.4f}"
        print(f"{name:<22s} {len(vs):>3d} {m:>+7.2f}% {s:>+7.2f}% [{ci_lo:>+6.2f}, {ci_hi:>+6.2f}] {wr:>5.0f}% {p:>16s}")
    print()

    # ── Verdict block per pre-commit interpretation ──
    print("=" * 100)
    print("VERDICT (per pre-commit interpretation; threshold = baseline + 0.5pp on mean)")
    print("=" * 100)
    for name, _ in POLICIES:
        if name == "baseline":
            continue
        vs = rows_per_policy[name]
        m = st.mean(vs)
        ci_lo, _ = bootstrap_ci(vs)
        delta = m - base_mean
        if m >= base_mean + 0.5 and ci_lo >= base_mean:
            v = "SHIP-WORTHY (CI clears baseline)"
        elif m >= base_mean + 0.5:
            v = "PROMISING (mean clears, CI doesn't — N=20 underpowered)"
        elif m <= base_mean - 0.5:
            v = "WORSE — reject"
        else:
            v = "NO-IMPROVEMENT (within 0.5pp of baseline)"
        print(f"  {name:<22s}  delta={delta:+.2f}pp  → {v}")
    print()
    print("BINDING CONSTRAINT (quant-analyst): MIN VALIDATION N = 79 per arm.")
    print("This harness PRIORITIZES which policy goes to live paper A/B; it does not ship anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
