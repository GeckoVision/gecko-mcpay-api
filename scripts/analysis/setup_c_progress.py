#!/usr/bin/env python3
"""Setup C experiment — daily-progress monitor.

Run this any time to see the live experiment's state vs the Sprint 8
baseline (the 20-trade autopsy from before Setup C started).

Compares:
  - Trade frequency (acts/day) — does legacy mode trade MORE than strict?
  - Per-symbol distribution — is alpha coming from WIF/PYTH/RAY as Sprint 8
    predicted, or is RAY now dragging?
  - Exit-reason mix — does tight_trail_03 reduce trailing_stop give-back?
  - Mean per-trade — versus pre-experiment baseline (-0.47%) and the +1.7%
    May 20-21 contest reference

Usage:  python3 scripts/analysis/setup_c_progress.py
"""
from __future__ import annotations

import json
import statistics as st
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


EXPERIMENT_START_TS = datetime(2026, 5, 28, 0, 18, tzinfo=timezone.utc)


def main() -> int:
    s = json.load(open("contest_bot/bot_state.json"))
    positions = s.get("positions", [])
    closed = [p for p in positions if p.get("status") == "closed"]
    open_pos = [p for p in positions if p.get("status") == "open"]

    pre, post = [], []
    for p in closed:
        ts_str = p.get("exit_ts") or p.get("entry_ts") or ""
        try:
            t = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            if t.tzinfo is None:
                t = t.replace(tzinfo=timezone.utc)
            if t < EXPERIMENT_START_TS:
                pre.append(p)
            else:
                post.append(p)
        except Exception:
            pre.append(p)  # default to pre if ts unparseable

    print("=" * 80)
    print(f"SETUP C PROGRESS — started {EXPERIMENT_START_TS.isoformat()}")
    print("=" * 80)
    now = datetime.now(timezone.utc)
    days_elapsed = (now - EXPERIMENT_START_TS).total_seconds() / 86400
    print(f"\nNow: {now.isoformat()}  |  Days elapsed: {days_elapsed:.2f}")
    print(f"\n  Open positions: {len(open_pos)}")
    for p in open_pos:
        print(f"    {p.get('symbol'):<10s}  entry@{p.get('entry_price')}  ts={p.get('entry_ts')}")

    def summary(name, group):
        if not group:
            print(f"\n  {name}: 0 closes")
            return
        pnls = [p.get("pnl_pct", 0) for p in group if isinstance(p.get("pnl_pct"), (int, float))]
        if not pnls:
            print(f"\n  {name}: {len(group)} closes (no pnl data)")
            return
        wins = sum(1 for v in pnls if v >= 0.5)
        losses = sum(1 for v in pnls if v <= -0.5)
        scratch = len(pnls) - wins - losses
        by_sym = defaultdict(list)
        by_reason = Counter()
        for p in group:
            by_sym[p.get("symbol", "?")].append(p.get("pnl_pct", 0))
            by_reason[p.get("exit_reason", "?")] += 1
        print(f"\n  {name}: {len(pnls)} closes")
        print(f"    mean={st.mean(pnls):+.2f}%/trade · sum={sum(pnls):+.2f}% · W/S/L={wins}/{scratch}/{losses}")
        print(f"    best={max(pnls):+.2f}% · worst={min(pnls):+.2f}%")
        if days_elapsed > 0 and name.startswith("POST"):
            print(f"    trade rate: {len(pnls) / days_elapsed:.1f}/day")
        print(f"    by symbol:")
        for sym, vs in sorted(by_sym.items(), key=lambda x: -len(x[1])):
            print(f"      {sym:<10s} n={len(vs):>2d}  mean={st.mean(vs):+.2f}%  sum={sum(vs):+.2f}%")
        print(f"    by exit_reason: {dict(by_reason)}")

    summary("PRE Setup C (baseline, n=20 expected)", pre)
    summary("POST Setup C (experiment closes)", post)

    # Verdict gate (after N≥15 post closes)
    print("\n" + "=" * 80)
    print("EARLY VERDICT GATES (need N≥15 post-experiment closes for honest signal)")
    print("=" * 80)
    if len(post) < 15:
        print(f"  Post-experiment N={len(post)} < 15 → no verdict yet. Keep watching.")
    else:
        post_pnls = [p.get("pnl_pct", 0) for p in post if isinstance(p.get("pnl_pct"), (int, float))]
        post_mean = st.mean(post_pnls)
        post_wr = 100 * sum(1 for v in post_pnls if v >= 0.5) / len(post_pnls)
        cat_count = sum(1 for v in post_pnls if v <= -2.5)
        gates = [
            (f"mean/trade ≥ pre-baseline (-0.47%) + 0.5pp  =  ≥ +0.03% (got {post_mean:+.2f}%)",
             post_mean >= 0.03),
            (f"catastrophic-rate (worst than -2.5%) ≤ 5%  (got {100*cat_count/len(post_pnls):.0f}%)",
             cat_count / len(post_pnls) <= 0.05),
            (f"win-rate ≥ 45% (got {post_wr:.0f}%)", post_wr >= 45),
        ]
        for desc, ok in gates:
            print(f"  [{('PASS' if ok else 'FAIL')}]  {desc}")
        n_pass = sum(1 for _, ok in gates if ok)
        if n_pass == 3:
            v = "SUCCESS — Setup C beats baseline. Make permanent."
        elif n_pass == 2:
            v = "PARTIAL — promising; keep running another 7d for more samples"
        else:
            v = "FAIL — revert to backup file (cp jto_breakout...py.bak-pre-setup-c → ...py)"
        print(f"\n  → VERDICT: {v}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
