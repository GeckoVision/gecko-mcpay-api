#!/usr/bin/env python3
"""Live Oracle A/B — the growing "user-zero, I'm running it" proof.

Reads the running paper bot's decision log (contest_bot/artifact_*.jsonl) and turns
it into the same ON-vs-OFF A/B as oracle_ab_artifact.py, but on the bot's OWN live
decisions as the stress test accumulates them:

  • ON  (gate approves) = decisions with action 'act'
  • OFF (bare bot)      = ALL decisions (act + decline) — what a no-judgment wallet does
  • REJECTED            = action 'decline'

The bot logs DECISIONS (act/decline) but not forward OUTCOMES, so each decision is
enriched with a forward return over a FROZEN horizon once that window has closed.
Enrichment is a pluggable `candle_provider(symbol, ts_iso, hold_h) -> fwd_return%|None`
so the math stays testable and never fabricates: a decision with no available outcome
(window still open, or no validated price source wired) is simply excluded, and the
script reports how many outcomes are still pending.

Frozen horizon HOLD_H = 4 (matches the eval + the bot's typical hold; one config, no
sweep — same discipline as the H1 pre-reg). Reuses oracle_ab_artifact for the A/B.

Run: uv run python scripts/calibration/oracle_ab_live.py [--fee 0.04] [--min-n 12]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import oracle_ab_artifact as base  # noqa: E402  reuse ab()/render()/arm_metrics

LOG_GLOB = os.path.join(_HERE, "..", "..", "contest_bot", "artifact_*.jsonl")
HOLD_H = 4  # frozen forward horizon (hours)
ACT_ACTIONS = {"act"}
DECLINE_ACTIONS = {"decline", "pass", "defer", "skip"}


# ── decision ledger ─────────────────────────────────────────────────
def load_decisions() -> list[dict]:
    """Flatten all artifact logs into [{ts, instrument, action, decision_id}]."""
    out: list[dict] = []
    for path in sorted(glob.glob(LOG_GLOB)):
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        r = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if r.get("kind") != "local_panel":
                        continue
                    p = r.get("payload", {})
                    action = p.get("action")
                    inst = p.get("instrument")
                    if not action or not inst:
                        continue
                    out.append(
                        {
                            "ts": r.get("ts"),
                            "instrument": inst,
                            "action": "act" if action in ACT_ACTIONS else "decline",
                            "decision_id": r.get("decision_id"),
                        }
                    )
        except OSError:
            continue
    out.sort(key=lambda d: d.get("ts") or "")
    return out


def _to_entry(dec: dict, fwd_return: float) -> dict:
    """Normalize a decision + its forward return into an oracle_ab_artifact entry
    (verdict 'act' → ON arm; 'defer' → REJECTED arm; reused ab() does the split)."""
    return {
        "sym": dec["instrument"],
        "verdict": "act" if dec["action"] == "act" else "defer",
        "pnl_real": fwd_return,
        "entry_ts_iso": dec.get("ts"),
        "idx": 0,
    }


def enrich(decisions: list[dict], candle_provider) -> tuple[list[dict], int]:
    """Return (entries_with_outcomes, n_pending). candle_provider may return None
    for an open/unfetchable window — that decision is counted pending, never faked."""
    entries: list[dict] = []
    pending = 0
    for dec in decisions:
        fwd = candle_provider(dec["instrument"], dec.get("ts"), HOLD_H)
        if fwd is None:
            pending += 1
            continue
        entries.append(_to_entry(dec, float(fwd)))
    return entries, pending


def null_candle_provider(symbol: str, ts_iso: str | None, hold_h: int) -> float | None:
    """Default provider: no validated live price source wired yet → no outcomes.
    Replace with a contract-tested candle fetch (bot's oc.get_candles) once the
    founder confirms the horizon; until then the A/B honestly reports 'pending'."""
    return None


# ── run ─────────────────────────────────────────────────────────────
def run(fee: float, min_n: int, candle_provider=null_candle_provider) -> dict:
    decisions = load_decisions()
    by_action = Counter(d["action"] for d in decisions)
    by_inst = Counter(d["instrument"] for d in decisions)
    print("=" * 92)
    print("LIVE ORACLE A/B — bot decision ledger (the growing user-zero proof)")
    print("=" * 92)
    print(
        f"  decisions logged : {len(decisions)}  (act={by_action.get('act', 0)}, "
        f"decline={by_action.get('decline', 0)})"
    )
    print(f"  per instrument   : {dict(by_inst)}")
    print(f"  frozen horizon   : {HOLD_H}h forward")

    entries, pending = enrich(decisions, candle_provider)
    print(f"  outcomes ready   : {len(entries)}  | pending (open window / no price src): {pending}")

    out: dict = {
        "n_decisions": len(decisions),
        "by_action": dict(by_action),
        "by_instrument": dict(by_inst),
        "n_outcomes": len(entries),
        "n_pending": pending,
        "hold_h": HOLD_H,
    }
    if len(entries) < min_n:
        print(
            f"\n  A/B PENDING — need >= {min_n} closed-window outcomes (have {len(entries)}). "
            "Proof populates as the stress test accrues ACT trades + their forward windows close, "
            "once a validated candle provider is wired + the horizon confirmed."
        )
        out["ab"] = None
        return out

    fee_rt = 2 * fee
    r = base.ab(entries, fee_rt)
    print()
    print(base.render(f"LIVE ({len(entries)} closed-window decisions)", r, fee))
    out["ab"] = r
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=0.04)
    ap.add_argument("--min-n", type=int, default=12)
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()
    res = run(a.fee, a.min_n)
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"\nwrote {a.json_out}")
