#!/usr/bin/env python3
"""Oracle A/B proof artifact — "does plugging in the Oracle make the bot better?"

The user-zero question: a bare agentic wallet (e.g. OKX OnchainOS) EXECUTES every
signal with no judgment. The Gecko Oracle is a judgment layer above it. The only
honest claim is measurable: SAME candidates, Oracle-ON vs Oracle-OFF →
is ON better? This renders that A/B from the recorded real-Oracle gating-delta
eval runs (tests/eval/live_runs/*gating-delta*.json), per window AND pooled.

Two framings:
  • USER-FACING  — ON (take only verdict='act') vs OFF (take EVERYTHING, the bare
    bot). "Does the Oracle improve the average trade vs taking all signals?"
  • DISCRIMINATION — act vs {defer,pass}. "Do the trades the Oracle APPROVES beat
    the ones it REJECTS?" (the sharper selection test).

NO profit promise. This reports whatever the data says — CI-clean or not — at a
realistic round-trip fee, with block-bootstrap CIs. pnl_real is treated as GROSS
forward return (the eval crosses fee separately); net = gross - round-trip fee.

Run: uv run python scripts/calibration/oracle_ab_artifact.py [--fee 0.04] [--json-out PATH]
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import random
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import overfitting_rigor as ofr  # noqa: E402  sharpe_ratio + max_drawdown

EVAL_GLOB = os.path.join(_HERE, "..", "..", "tests", "eval", "live_runs", "*gating-delta*.json")
ACT = {"act"}  # Oracle says "take it"
REJECT = {"defer", "pass"}  # Oracle says "don't"
DEFAULT_FEE = 0.04  # % per side (Jupiter-reachable); round-trip = 2x
BLOCK = 3  # house block-bootstrap config (matches gating-delta script)
REPS = 5000
SEED = 1729


# ── data ────────────────────────────────────────────────────────────
def load_windows() -> dict[str, list[dict]]:
    """Return {window_label: [entry,...]} for each eval run found."""
    out: dict[str, list[dict]] = {}
    for path in sorted(glob.glob(EVAL_GLOB)):
        label = os.path.basename(path).replace(".json", "")
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, json.JSONDecodeError):
            continue
        entries = [e for e in d.get("entries", []) if e.get("pnl_real") is not None]
        if entries:
            out[label] = entries
    return out


# ── stats ───────────────────────────────────────────────────────────
def _ordered(entries: list[dict]) -> list[dict]:
    return sorted(entries, key=lambda e: (e.get("entry_ts_iso") or "", e.get("idx") or 0))


def arm_metrics(entries: list[dict], fee_rt: float) -> dict:
    """Per-trade metrics for one arm. net = gross pnl_real - round-trip fee."""
    ents = _ordered(entries)
    gross = [float(e["pnl_real"]) for e in ents]
    net = [g - fee_rt for g in gross]
    n = len(net)
    if n == 0:
        return {"n": 0}
    wins = sum(1 for g in gross if g > 0)
    return {
        "n": n,
        "win_rate": wins / n,
        "ev_gross": st.mean(gross),
        "ev_net": st.mean(net),
        "total_net": sum(net),
        "max_dd_net": ofr.max_drawdown(net),
        "sharpe_net": ofr.sharpe_ratio(net),
    }


def block_diff_ci(a: list[float], b: list[float]) -> tuple[float, float, float, bool]:
    """Block-bootstrap 5-95% CI on mean(a) - mean(b) (two independent arms,
    moving blocks, house seed). Returns (delta, lo, hi, ci_excludes_zero)."""
    if len(a) < 2 or len(b) < 2:
        return float("nan"), float("nan"), float("nan"), False
    delta = st.mean(a) - st.mean(b)
    rng = random.Random(SEED)

    def boot_mean(x: list[float]) -> float:
        nx = len(x)
        acc, cnt = 0.0, 0
        while cnt < nx:
            start = rng.randrange(nx)
            for k in range(BLOCK):
                acc += x[(start + k) % nx]
                cnt += 1
                if cnt >= nx:
                    break
        return acc / nx

    diffs = sorted(boot_mean(a) - boot_mean(b) for _ in range(REPS))
    lo = diffs[int(0.05 * REPS)]
    hi = diffs[int(0.95 * REPS)]
    return delta, lo, hi, (lo > 0 or hi < 0)


def ab(entries: list[dict], fee_rt: float) -> dict:
    """The two A/B framings for one set of entries."""
    on = [e for e in entries if e.get("verdict") in ACT]
    off = entries  # bare bot takes everything
    rejected = [e for e in entries if e.get("verdict") in REJECT]
    g_on = [float(e["pnl_real"]) - fee_rt for e in on]
    g_off = [float(e["pnl_real"]) - fee_rt for e in off]
    g_rej = [float(e["pnl_real"]) - fee_rt for e in rejected]
    d_user, lo_u, hi_u, clean_u = block_diff_ci(g_on, g_off)
    d_disc, lo_d, hi_d, clean_d = block_diff_ci(g_on, g_rej)
    return {
        "ON_gated": arm_metrics(on, fee_rt),
        "OFF_takeall": arm_metrics(off, fee_rt),
        "REJECTED": arm_metrics(rejected, fee_rt),
        "delta_user_ON_minus_OFF": {"delta": d_user, "ci": [lo_u, hi_u], "ci_clean": clean_u},
        "delta_discrim_ACT_minus_REJECT": {
            "delta": d_disc,
            "ci": [lo_d, hi_d],
            "ci_clean": clean_d,
        },
    }


# ── render ──────────────────────────────────────────────────────────
def _row(label: str, m: dict) -> str:
    if not m or m.get("n", 0) == 0:
        return f"  {label:<14} (no trades)"
    return (
        f"  {label:<14} n={m['n']:>3}  win={m['win_rate']:>5.1%}  "
        f"EV_gross={m['ev_gross']:>+6.3f}%  EV_net={m['ev_net']:>+6.3f}%  "
        f"maxDD={m['max_dd_net']:>+6.2f}  Sharpe={m['sharpe_net']:>+5.2f}"
    )


def render(label: str, r: dict, fee: float) -> str:
    lines = [
        "=" * 92,
        f"ORACLE A/B — {label}   (fee {fee:.2f}%/side, round-trip {2 * fee:.2f}%)",
        "=" * 92,
        _row("OFF take-all", r["OFF_takeall"]),
        _row("ON gated(act)", r["ON_gated"]),
        _row("REJECTED", r["REJECTED"]),
        "",
    ]
    du = r["delta_user_ON_minus_OFF"]
    dd = r["delta_discrim_ACT_minus_REJECT"]
    lo_u, hi_u = du["ci"]
    lo_d, hi_d = dd["ci"]
    lines.append(
        f"  USER  (ON - OFF) per-trade EV delta : {du['delta']:>+6.3f}%  "
        f"95% CI [{lo_u:+.3f}, {hi_u:+.3f}]  {'CI-CLEAN ✓' if du['ci_clean'] else 'not clean'}"
    )
    lines.append(
        f"  DISCR (act - reject)         delta  : {dd['delta']:>+6.3f}%  "
        f"95% CI [{lo_d:+.3f}, {hi_d:+.3f}]  {'CI-CLEAN ✓' if dd['ci_clean'] else 'not clean'}"
    )
    return "\n".join(lines)


def run(fee: float) -> dict:
    windows = load_windows()
    if not windows:
        print(f"no eval runs matched {EVAL_GLOB}", file=sys.stderr)
        return {}
    fee_rt = 2 * fee
    out: dict = {"fee_per_side": fee, "round_trip_fee": fee_rt, "windows": {}}
    pooled: list[dict] = []
    for label, entries in windows.items():
        r = ab(entries, fee_rt)
        out["windows"][label] = r
        pooled.extend(entries)
        print(render(label, r, fee))
        print()
    rp = ab(pooled, fee_rt)
    out["pooled"] = rp
    print(render(f"POOLED ({len(pooled)} decisions across {len(windows)} windows)", rp, fee))
    # honest one-line verdict
    du = rp["delta_user_ON_minus_OFF"]
    print(
        "\nVERDICT: the Oracle "
        + (
            "ADDS selection value (ON beats take-all, CI-clean pooled)"
            if du["ci_clean"] and du["delta"] > 0
            else "shows POSITIVE-but-not-CI-clean selection (directionally better, needs more N)"
            if du["delta"] > 0
            else "does NOT beat take-all on this data"
        )
        + f" — pooled ON-OFF = {du['delta']:+.3f}%/trade."
    )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fee", type=float, default=DEFAULT_FEE, help="%% per side (round-trip=2x)")
    ap.add_argument("--json-out", default="")
    a = ap.parse_args()
    res = run(a.fee)
    if a.json_out and res:
        with open(a.json_out, "w") as f:
            json.dump(res, f, indent=2)
        print(f"\nwrote {a.json_out}")
