#!/usr/bin/env python3
"""Pre-contest replay — May 20-21 historical artifact vs current bot's gate stack.

Founder's question (2026-05-27): "On the same period, did our bot perform
better or worse? Why? Data not intuition."

Outputs:
1. Historical actual closes (May 20-21) — mean pnl, exit reasons
2. Current era (May 24-27) for comparison
3. Counterfactual: for each historical act, would CURRENT gates accept it?
4. Sprint 7 trailing-stop re-label simulation (limited fidelity)
"""

from __future__ import annotations

import glob
import json
import os
import statistics as st
from collections import Counter


def load_may20_21_events() -> list[dict]:
    events = []
    for f in sorted(glob.glob('contest_bot/artifact_2026052[01]*.jsonl')):
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                        d['_source'] = os.path.basename(f)
                        events.append(d)
                    except json.JSONDecodeError:
                        pass
        except FileNotFoundError:
            pass
    events.sort(key=lambda e: e.get('ts', ''))
    return events


def reconstruct_acts_with_signal(events: list[dict]) -> list[dict]:
    enriched = []
    recent_by_inst: dict[str, dict] = {}
    for e in events:
        p = e.get('payload') or {}
        inst = p.get('instrument') or p.get('symbol') or (p.get('token', '') or '')[:12]
        if e.get('kind') == 'candidate_blocked' and inst:
            recent_by_inst[inst] = {
                'primitive': (p.get('signal_data') or {}).get('signal') or p.get('primitive'),
                'reasons': p.get('reasons') or [],
                'regime_1h': p.get('regime_1h'),
            }
        if e.get('kind') == 'position_open' and inst:
            sd = p.get('signal_data') or {}
            recent_by_inst[inst] = {
                'primitive': sd.get('signal') or sd.get('primitive'),
                'regime_1h': sd.get('regime_1h'),
                'reasons': [],
            }
        if e.get('kind') == 'local_panel' and p.get('action') == 'act':
            enriched.append({
                'ts': e.get('ts'),
                'instrument': inst,
                'rule': p.get('coordinator_rule_fired'),
                'reason_text': p.get('reason'),
                'context': recent_by_inst.get(inst) or {},
            })
    return enriched


def counterfactual(act: dict) -> dict:
    ctx = act.get('context') or {}
    primitive = ctx.get('primitive') or 'unknown'
    regime = ctx.get('regime_1h')
    reasons = ctx.get('reasons') or []

    is_vs = primitive == 'volume_spike'
    has_breakout = 'volume_spike_without_breakout' not in reasons
    fix4 = (not is_vs) or has_breakout
    fix5 = regime == 'TREND-UP'

    panel_likely = True
    rt = (act.get('reason_text') or '').lower()
    if '/' in rt:
        try:
            after = rt.split(':')[-1].split('(')[0].strip()
            parts = after.split('/')
            if len(parts) == 4:
                bear = int(''.join(c for c in parts[1] if c.isdigit()) or 0)
                neutral = int(''.join(c for c in parts[2] if c.isdigit()) or 0)
                if bear > 0 or neutral > 0:
                    panel_likely = False
        except Exception:
            pass

    overall = fix4 and fix5 and panel_likely
    return {
        'primitive': primitive, 'regime_1h': regime,
        'fix4': fix4, 'fix5': fix5, 'panel': panel_likely, 'overall': overall,
    }


def main() -> int:
    print("=" * 100)
    print("PRE-CONTEST REPLAY (May 20-21) vs current bot's gate stack")
    print("=" * 100)
    print()

    events = load_may20_21_events()
    print(f"Loaded {len(events)} May 20-21 events")

    # Tally events by kind
    kind_count = Counter(e.get('kind') for e in events)
    print(f"  by kind: {dict(kind_count)}")
    print()

    # ── Historical actual closes
    closes = [(e.get('ts'), e.get('payload') or {}) for e in events if e.get('kind') == 'position_close']
    print("HISTORICAL ACTUAL — May 20-21 closes:")
    actual_pnls = []
    for ts, p in closes:
        sym = p.get('symbol', '?')
        pnl = p.get('pnl_pct')
        reason = p.get('exit_reason')
        if isinstance(pnl, (int, float)):
            actual_pnls.append(pnl)
        print(f"  {ts[:19]}  {sym:18s}  pnl={pnl:>+6}%  {reason}")
    if actual_pnls:
        wins = sum(1 for p in actual_pnls if p >= 0.5)
        losses = sum(1 for p in actual_pnls if p <= -0.5)
        scratches = len(actual_pnls) - wins - losses
        print(f"\n  Hist N={len(actual_pnls)}  mean={st.mean(actual_pnls):+.2f}%  sum={sum(actual_pnls):+.2f}%  W/S/L={wins}/{scratches}/{losses}")
    print()

    # ── Current era comparison
    try:
        cur = json.load(open('contest_bot/bot_state.json'))
        cur_pnls = [p.get('pnl_pct') for p in cur.get('positions', []) if p.get('status') == 'closed' and isinstance(p.get('pnl_pct'), (int, float))]
        if cur_pnls:
            wins = sum(1 for p in cur_pnls if p >= 0.5)
            losses = sum(1 for p in cur_pnls if p <= -0.5)
            scratches = len(cur_pnls) - wins - losses
            print(f"CURRENT-ERA (May 24-27) closes from bot_state.json:")
            print(f"  N={len(cur_pnls)}  mean={st.mean(cur_pnls):+.2f}%  sum={sum(cur_pnls):+.2f}%  W/S/L={wins}/{scratches}/{losses}")
    except Exception as e:
        print(f"  (couldn't load current bot_state: {e})")
    print()

    # ── Counterfactual gate pass
    enriched = reconstruct_acts_with_signal(events)
    may20 = [a for a in enriched if (a.get('ts') or '').startswith('2026-05-20')]
    print(f"COUNTERFACTUAL — would CURRENT gates accept the {len(may20)} May-20 historical acts?")
    print()
    print(f"  {'ts':<20s}  {'instr':<8s}  {'primitive':<14s}  {'regime':<12s}  {'fix4':>5s}  {'fix5':>5s}  {'panel':>6s}  {'overall':>10s}")
    print("-" * 110)
    pass_count = 0
    fail_reasons = Counter()
    for a in may20:
        cf = counterfactual(a)
        if cf['overall']:
            pass_count += 1
        else:
            if not cf['fix4']: fail_reasons['fix4_volume_spike_without_breakout'] += 1
            if not cf['fix5']: fail_reasons[f'fix5_regime={cf["regime_1h"]}'] += 1
            if not cf['panel']: fail_reasons['panel_4voice_vote_split'] += 1
        verdict = '✓ PASS' if cf['overall'] else '✗ BLOCK'
        print(f"  {a['ts'][:19]}  {a['instrument']:<8s}  {cf['primitive']:<14s}  "
              f"{str(cf['regime_1h']):<12s}  {'✓' if cf['fix4'] else '✗':>5s}  "
              f"{'✓' if cf['fix5'] else '✗':>5s}  {'✓' if cf['panel'] else '✗':>6s}  {verdict:>10s}")
    print()
    print(f"COUNTERFACTUAL RESULT:")
    print(f"  PASS: {pass_count}/{len(may20)} ({100*pass_count/max(len(may20),1):.0f}%)")
    print(f"  BLOCK: {len(may20)-pass_count}/{len(may20)}")
    print()
    print(f"  Block reasons:")
    for r, n in fail_reasons.most_common():
        print(f"    {n:>3d}×  {r}")

    # ── Sprint 7 exit re-label
    print()
    print("SPRINT 7 EXIT RE-LABELING (limited — close events lack peak/entry prices):")
    for ts, p in closes:
        sym = p.get('symbol', '?')
        pnl = p.get('pnl_pct')
        reason = p.get('exit_reason')
        if reason == 'trailing_stop' and isinstance(pnl, (int, float)) and pnl < -1.0:
            note = f"would relabel as stop_loss (Sprint 7 floor)"
        elif reason == 'trailing_stop':
            note = f"Sprint 7 floor unaffected; tighter trail (0.5% vs 1%) would exit EARLIER → likely +0.2-0.5pp better"
        else:
            note = "Sprint 7 logic unchanged"
        print(f"  {ts[:19]}  {sym:18s}  {reason}@{pnl:>+5}%  → {note}")

    # ── Synthesis
    print()
    print("=" * 100)
    print("SYNTHESIS:")
    print("=" * 100)
    if actual_pnls:
        hist = st.mean(actual_pnls)
        cur_pnls = [p.get('pnl_pct') for p in json.load(open('contest_bot/bot_state.json')).get('positions', []) if p.get('status')=='closed' and isinstance(p.get('pnl_pct'), (int, float))]
        cur = st.mean(cur_pnls) if cur_pnls else float('nan')
        print(f"  Historical (pre-contest, May 20-21):  mean/trade {hist:+.2f}%  N={len(actual_pnls)}")
        print(f"  Current era (post-fixes, May 24-27):  mean/trade {cur:+.2f}%  N={len(cur_pnls)}")
        print(f"  Per-trade delta historical−current:   {hist - cur:+.2f}pp")
        print()
        if pass_count < len(may20) * 0.3:
            print(f"  Of {len(may20)} historical acts, current gates would BLOCK {len(may20)-pass_count} ({100*(len(may20)-pass_count)//len(may20)}%).")
            print(f"  If the BLOCKED acts were among the winners, the gates are leaving EV on the table.")
            print(f"  → Recommend: investigate per-block which acts would NOT have been blocked + their outcomes.")
        elif pass_count > len(may20) * 0.7:
            print(f"  Current gates accept MOST historical acts. The pnl difference isn't gate-driven.")
            print(f"  → The difference is regime/universe — pre-contest market was more favorable.")
        else:
            print(f"  Current gates would have allowed some, blocked others.")
            print(f"  → Mid-zone. Per-act analysis needed for actionable insight.")

    print()
    print("CAVEATS:")
    print("  1. Close events lack peak/entry/exit prices — can't compute exact Sprint 7 PnL deltas")
    print("  2. Historical voice rules + chart_analyst prompt differ from current — panel-pass approximation is rough")
    print("  3. Only 6 historical closes May 20-21 — small N; directional only")
    print("  4. signal_context recovered best-effort from artifact log; some primitives/regimes may be missing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
