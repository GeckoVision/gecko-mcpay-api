#!/usr/bin/env python3
"""Live LOCAL-GATE A/B — the growing "user-zero, I'm running it" proof.

⚠️ SCOPE (verified 2026-05-25): the bot's artifact log records the LOCAL 4-voice
panel gate (action act/decline) on EVERY poll. It does NOT give an Oracle A/B — the
Gecko Oracle (FundamentalsOracle) runs slow-cadence and only logs when a trade FIRES
(≈ the rare 'act's), so it never evaluates the declines → there is no live
counterfactual for the Oracle. The ORACLE A/B comes from OFFLINE eval runs on the
full candidate set (scripts/trading_oracle/oracle_gating_delta.py → the recorded
oracle_ab_artifact). This script measures the LOCAL GATE, which prior work found
~anti-predictive — so a negative delta here does NOT contradict the Oracle result.

What it does: reads contest_bot/artifact_*.jsonl and forms the ON-vs-OFF A/B on the
bot's own LOCAL-gate decisions as the stress test accumulates them:
  • ON  (gate approves) = action 'act'
  • OFF (bare bot)      = ALL decisions (act + decline) — a no-judgment wallet
  • REJECTED            = action 'decline'

Outcomes: each decision is enriched with the bot's REAL exit-stack forward PnL once
its window has closed, via a pluggable candle_provider (default null → 'pending';
make_onchainos_provider() = the validated path reusing chart_floor_calibration.enrich
+ has_full_horizon + exit_reconciliation.simulate_exit_real_close — the SAME forward-
PnL the recorded eval uses). Never fabricates: open/unavailable windows count pending.
The forward horizon IS the exit stack (TP/SL/trail/stall) gated by has_full_horizon
(>=18 closed bars); HOLD_H is advisory only.

Run: uv run python scripts/calibration/oracle_ab_live.py --live [--fee 0.04] [--min-n 12]
"""

from __future__ import annotations

import argparse
import datetime as dt
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
    """Default provider: no validated live price source wired → no outcomes.
    The A/B honestly reports 'pending'. Use make_onchainos_provider() for the
    real, validated enrichment."""
    return None


# ── real outcome enrichment (the validated path) ────────────────────
def iso_to_ms(ts_iso: str | None) -> float | None:
    """ISO-8601 (the bot logs UTC) → ms epoch. None on unparseable."""
    if not ts_iso:
        return None
    try:
        return dt.datetime.fromisoformat(ts_iso.replace("Z", "+00:00")).timestamp() * 1000.0
    except (ValueError, TypeError):
        return None


def entry_index(ts_arr: list[float], ts_ms: float) -> int:
    """Largest index i with ts_arr[i] <= ts_ms — the CLOSED bar at decision time
    (no look-ahead). -1 if the decision predates the series. ts_arr ascending.
    This alignment is the load-bearing correctness; base/recon are already tested."""
    i = -1
    for j, t in enumerate(ts_arr):
        if t <= ts_ms:
            i = j
        else:
            break
    return i


def make_onchainos_provider(bar: str = "5m", limit: int = 299):
    """Real enrichment: forward PnL via the bot's REAL exit stack on the bot's own
    candle feed — the SAME path the recorded gating-delta eval used (so live numbers
    are comparable), reusing chart_floor_calibration.enrich + has_full_horizon +
    exit_reconciliation.simulate_exit_real_close. The 'horizon' is the exit stack
    (TP/SL/trail/stall) gated by has_full_horizon (>=18 bars closed); hold_h is
    advisory. Per-symbol candle cache: one fetch per symbol per run. Lazy imports so
    this module + its unit tests don't require the onchainos CLI."""
    cb = os.path.join(_HERE, "..", "..", "contest_bot")
    if cb not in sys.path:
        sys.path.insert(0, cb)
    import chart_floor_calibration as cfc
    import exit_reconciliation as recon
    import universe
    from onchainos import OnchainOS

    oc = OnchainOS(chain="solana")
    cache: dict[str, object] = {}

    def _series(symbol: str):
        if symbol not in cache:
            mint = universe.mint_for(symbol)
            raw = oc.get_candles(mint, bar, limit=limit) if mint else None
            cache[symbol] = cfc.enrich(raw) if raw else None
        return cache[symbol]

    def provider(symbol: str, ts_iso: str | None, hold_h: int) -> float | None:
        c = _series(symbol)
        if not c or not c.get("ts"):
            return None
        ts_ms = iso_to_ms(ts_iso)
        if ts_ms is None:
            return None
        i = entry_index(c["ts"], ts_ms)
        if i < 0 or not cfc.has_full_horizon(c, i):
            return None  # decision predates window, or window still open
        return float(recon.simulate_exit_real_close(c, i))

    return provider


# ── run ─────────────────────────────────────────────────────────────
def run(fee: float, min_n: int, candle_provider=null_candle_provider) -> dict:
    decisions = load_decisions()
    by_action = Counter(d["action"] for d in decisions)
    by_inst = Counter(d["instrument"] for d in decisions)
    print("=" * 92)
    print("LIVE LOCAL-GATE A/B — bot decision ledger (the growing user-zero proof)")
    print("  (measures the local 4-voice gate; the ORACLE A/B = offline eval, see docstring)")
    print("=" * 92)
    print(
        f"  decisions logged : {len(decisions)}  (act={by_action.get('act', 0)}, "
        f"decline={by_action.get('decline', 0)})"
    )
    print(f"  per instrument   : {dict(by_inst)}")
    print("  outcome model    : bot exit-stack (TP/SL/trail/stall), has_full_horizon >=18 bars")

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
    ap.add_argument(
        "--live", action="store_true", help="enrich via onchainos candle feed (real outcomes)"
    )
    a = ap.parse_args()
    provider = make_onchainos_provider() if a.live else null_candle_provider
    res = run(a.fee, a.min_n, candle_provider=provider)
    if a.json_out:
        with open(a.json_out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"\nwrote {a.json_out}")
