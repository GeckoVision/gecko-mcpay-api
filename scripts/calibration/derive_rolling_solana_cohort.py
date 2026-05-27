"""Phase D #2 — rolling 90d cohort re-derivation (regime-drift protection).

Same simulator as derive_solana_cohort.py but windowed to the most-recent
90 days of ingested data. Run on cron (nightly) — bot picks up the fresh
cohort on next restart.

Why rolling?

Per Phase D #1 train/test finding: JTO appeared in the 2024-half-derived
cohort but NOT in the full-period derivation. That's regime drift — JTO's
character changed between early-2024 and late-2025. The static cohort
hard-codes a SPECIFIC slice of history; a 1-year-old cohort against
current-month behavior risks the BTC pattern (was 2024 #4 +EV but Phase
B's chronic -EV — character flip).

A rolling 90d window:
- Adapts to current market regime
- Surfaces NEW chronic losers as they emerge
- Drops yesterday's losers if they've reverted to neutral/winning
- Smooths the cohort identity vs deriving over hundreds of days

Output: overwrites scripts/calibration/data/solana/_cohort_result.json
(same shape as derive_solana_cohort.py — JSON contract is the boundary
between the derivation layer and the v2 voice loader).

Run:
    uv run python scripts/calibration/derive_rolling_solana_cohort.py

Schedule (founder cron-skeleton, NOT installed by this PR):
    0 6 * * * cd /path/to/repo && \\
        uv run python scripts/calibration/ingest_coingecko_solana_universe.py \\
        && uv run python scripts/calibration/derive_rolling_solana_cohort.py

For Phase D #2 ship: this script + the JSON-loading v2 voice (done in same
PR). The cron + hot-reload is documented but not wired — operator
schedules + restarts the bot to pick up fresh cohorts. Hot-reload (SIGHUP)
is a deferred ticket.
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
from datetime import datetime, timezone
from glob import glob
from pathlib import Path

# Import the same simulator that derive_solana_cohort.py uses — single
# source of truth for the strategy under test. If the simulator params
# change, both static + rolling derivations update in lockstep.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
import derive_solana_cohort as dsc  # noqa: E402

REPO_ROOT = _HERE.parent.parent
SOLANA_DATA_DIR = REPO_ROOT / "scripts" / "calibration" / "data" / "solana"

ROLLING_WINDOW_DAYS = int(os.environ.get("ROLLING_WINDOW_DAYS", "90"))
MIN_TRADES_FOR_COHORT = 3  # rolling window has fewer bars → fewer trades; lower the floor


def _filter_to_rolling_window(rows: list[dict], days: int) -> list[dict]:
    """Keep only the most-recent `days` of daily rows."""
    if not rows:
        return rows
    last_ts = max(r["ts"] for r in rows)
    cutoff_ts = last_ts - days * 24 * 3600 * 1000
    return [r for r in rows if r["ts"] >= cutoff_ts]


def stratify_rolling(window_days: int = ROLLING_WINDOW_DAYS) -> dict[str, dict]:
    """Simulate over the rolling window per token; return summary stats."""
    out: dict[str, dict] = {}
    for sym in dsc.list_tokens():
        rows = dsc.load_token(sym)
        if not rows:
            continue
        rows_windowed = _filter_to_rolling_window(rows, window_days)
        if len(rows_windowed) < dsc.LOOKBACK_DAYS + 2:
            out[sym] = {"n": 0, "trades": []}
            continue
        trades = dsc.simulate_token(rows_windowed)
        if not trades:
            out[sym] = {"n": 0, "trades": []}
            continue
        pnls = [t["net_pnl_pct"] for t in trades]
        wins = sum(1 for p in pnls if p >= 0.5)
        losses = sum(1 for p in pnls if p <= -0.5)
        scratches = len(pnls) - wins - losses
        mean = st.mean(pnls)
        sd = st.pstdev(pnls) if len(pnls) > 1 else 1.0
        sharpe = (mean / sd) if sd > 0 else 0.0
        out[sym] = {
            "n": len(pnls),
            "wins": wins, "losses": losses, "scratches": scratches,
            "mean_pct": mean,
            "sum_pct": sum(pnls),
            "sharpe_per_trade": sharpe,
            "strict_wr": (wins / len(pnls)) if pnls else 0.0,
            "trades": trades,
        }
    return out


def cohort_lists_rolling(strat: dict[str, dict], k: int = 10) -> dict:
    """Same shape as derive_solana_cohort.cohort_lists but with lower n floor."""
    valid = {s: d for s, d in strat.items() if d.get("n", 0) >= MIN_TRADES_FOR_COHORT}
    if len(valid) < 2 * k:
        # Not enough tokens with sufficient trades; take what we can
        k = max(1, len(valid) // 2)
    ranked = sorted(valid.items(), key=lambda kv: kv[1]["sum_pct"])
    bottom = ranked[:k]
    top = ranked[-k:][::-1]
    return {
        "minus_ev_cohort": [s for s, _ in bottom],
        "plus_ev_cohort": [s for s, _ in top],
        "n_valid": len(valid),
        "k": k,
    }


def diff_against_prior(prior: dict, current: dict) -> dict:
    """Compute symbol-level diff between prior + current cohorts."""
    p_minus = set(prior.get("minus_ev_cohort", []))
    c_minus = set(current["minus_ev_cohort"])
    p_plus = set(prior.get("plus_ev_cohort", []))
    c_plus = set(current["plus_ev_cohort"])
    return {
        "minus_added": sorted(c_minus - p_minus),
        "minus_removed": sorted(p_minus - c_minus),
        "minus_stable": sorted(c_minus & p_minus),
        "plus_added": sorted(c_plus - p_plus),
        "plus_removed": sorted(p_plus - c_plus),
        "plus_stable": sorted(c_plus & p_plus),
    }


def main() -> int:
    if not SOLANA_DATA_DIR.exists() or not dsc.list_tokens():
        print(f"NO DATA at {SOLANA_DATA_DIR}; run ingest_coingecko_solana_universe.py first")
        return 1

    print(f"=== Phase D #2: rolling Solana cohort re-derivation ===")
    print(f"  window: last {ROLLING_WINDOW_DAYS}d  (vs derive_solana_cohort.py = full history)")
    print(f"  strategy: {dsc.LOOKBACK_DAYS}d breakout / {dsc.STOP_PCT}% SL / {dsc.TP_PCT}% TP / {dsc.MAX_HOLD_DAYS}d max hold / {dsc.FLIP_COST_PCT}%/trip")
    print(f"  min_trades_for_cohort: {MIN_TRADES_FOR_COHORT}")
    print()

    # Read prior cohort for diff (if exists)
    json_path = SOLANA_DATA_DIR / "_cohort_result.json"
    prior = None
    if json_path.exists():
        try:
            prior = json.loads(json_path.read_text())
        except json.JSONDecodeError:
            prior = None

    print("[1/3] Simulating rolling window per token...")
    strat = stratify_rolling()
    n_trades_total = sum(d.get("n", 0) for d in strat.values())
    n_with_trades = sum(1 for d in strat.values() if d.get("n", 0) >= MIN_TRADES_FOR_COHORT)
    print(f"  {n_trades_total} total trades  |  {n_with_trades} tokens with >= {MIN_TRADES_FOR_COHORT} trades")
    print()

    print("[2/3] Top + bottom per rolling window:")
    cohorts = cohort_lists_rolling(strat, k=10)
    print(f"  MINUS_EV ({len(cohorts['minus_ev_cohort'])} symbols): {cohorts['minus_ev_cohort']}")
    print(f"  PLUS_EV  ({len(cohorts['plus_ev_cohort'])} symbols): {cohorts['plus_ev_cohort']}")
    print()

    if prior is not None:
        print("[3/3] Diff vs prior cohort:")
        d = diff_against_prior(prior, cohorts)
        print(f"  MINUS_EV: stable={len(d['minus_stable'])}  added={d['minus_added']}  removed={d['minus_removed']}")
        print(f"  PLUS_EV:  stable={len(d['plus_stable'])}  added={d['plus_added']}  removed={d['plus_removed']}")
        # Surface the rotation — symbols that shifted from minus → plus or vice versa
        rotated_to_plus = set(d['plus_added']) & set(prior.get('minus_ev_cohort', []))
        rotated_to_minus = set(d['minus_added']) & set(prior.get('plus_ev_cohort', []))
        if rotated_to_plus or rotated_to_minus:
            print(f"  ⚠️  REGIME ROTATION:")
            for s in sorted(rotated_to_plus):
                print(f"    {s}: was MINUS_EV → now PLUS_EV (recovery)")
            for s in sorted(rotated_to_minus):
                print(f"    {s}: was PLUS_EV → now MINUS_EV (deterioration)")
    else:
        print("[3/3] No prior cohort found; this is the first derivation.")
    print()

    # Bot universe stratification
    print("Bot universe classification (rolling):")
    bot_syms = ["JTO", "JUP", "WIF", "PYTH", "RAY"]
    for sym in bot_syms:
        d = strat.get(sym)
        if not d or d.get("n", 0) < MIN_TRADES_FOR_COHORT:
            print(f"  {sym}: INSUFFICIENT DATA in rolling window")
            continue
        classification = (
            "MINUS_EV" if sym in cohorts["minus_ev_cohort"]
            else "PLUS_EV" if sym in cohorts["plus_ev_cohort"]
            else "neutral"
        )
        print(f"  {sym}: n={d['n']}  sum_pct={d['sum_pct']:+.1f}%  → {classification}")
    print()

    # Persist (overwrite the static cohort file → next bot restart picks it up)
    out_payload = {
        "minus_ev_cohort": cohorts["minus_ev_cohort"],
        "plus_ev_cohort": cohorts["plus_ev_cohort"],
        "n_tokens_simulated": n_with_trades,
        "total_trades": n_trades_total,
        "derivation_kind": "rolling",
        "window_days": ROLLING_WINDOW_DAYS,
        "derived_at_utc": datetime.now(timezone.utc).isoformat(),
        "strategy_params": {
            "lookback_days": dsc.LOOKBACK_DAYS,
            "stop_pct": dsc.STOP_PCT,
            "tp_pct": dsc.TP_PCT,
            "max_hold_days": dsc.MAX_HOLD_DAYS,
            "flip_cost_pct": dsc.FLIP_COST_PCT,
            "cooldown_days": dsc.COOLDOWN_DAYS,
        },
    }
    json_path.write_text(json.dumps(out_payload, indent=2))
    print(f"Saved → {json_path.relative_to(REPO_ROOT)} (bot picks up on next restart)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
