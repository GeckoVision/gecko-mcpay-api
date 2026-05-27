"""Phase D #1 — derive Solana cohort from daily OHLCV.

Uses the same SHAPE as Phase B's cohort derivation (PR #54 by-symbol
stratification + PR #56 train/test validation), but on daily candles
appropriate for the cohort granularity. The bot trades 30s polls; the
cohort filter is a defensive "which tokens chronically lose on momentum
strategies" rule that doesn't need intra-day fidelity to be useful.

Strategy under test (per token, long-only, daily):
- ENTRY: close[t] > max(high[t-lookback : t])  — breakout
- EXIT:  whichever of:
         · stop_loss: close drops > STOP_PCT from entry
         · take_profit: close rises > TP_PCT from entry
         · time_stop: held for MAX_HOLD_DAYS without trigger
- One position per token at a time; cooldown after exit.
- Flat cost per round trip: FLIP_COST_PCT.

Outputs:
- Per-token cumulative PnL, mean per-trade PnL, trade count, Sharpe
- Bottom-N (chronic -EV) cohort list — candidates for v2's MINUS_EV
- Top-N (chronic +EV) cohort — candidates for v2's PLUS_EV
- Train/test split (early-period train, late-period test) for OOS lift check

Run: uv run python scripts/calibration/derive_solana_cohort.py
"""

from __future__ import annotations

import json
import os
import statistics as st
from glob import glob
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SOLANA_DATA_DIR = REPO_ROOT / "scripts" / "calibration" / "data" / "solana"

# Daily-strategy params — slower than the 30s-bot's params since we have no
# intra-day granularity. Same SHAPE as the bot (breakout + stop/TP/time),
# different magnitudes appropriate for daily candles.
LOOKBACK_DAYS = 5            # breakout = close > prior 5-day high
STOP_PCT = 8.0               # daily candles are noisy; 3% would whip out
TP_PCT = 12.0                # asymmetric R:R favoring trend continuation
MAX_HOLD_DAYS = 15           # 3-week max hold
FLIP_COST_PCT = 0.5          # round-trip cost; DEX swap + slippage proxy
COOLDOWN_DAYS = 1            # one-bar cooldown between exit + re-entry


def load_token(symbol: str) -> list[dict]:
    """Load one token's daily rows from the ingested JSON."""
    f = SOLANA_DATA_DIR / f"{symbol}_dex.json"
    if not f.exists():
        return []
    return json.loads(f.read_text())


def list_tokens() -> list[str]:
    """Return sorted list of ingested token symbols."""
    return sorted(
        Path(f).stem.replace("_dex", "")
        for f in glob(str(SOLANA_DATA_DIR / "*_dex.json"))
    )


def simulate_token(
    rows: list[dict],
    *,
    lookback: int = LOOKBACK_DAYS,
    stop_pct: float = STOP_PCT,
    tp_pct: float = TP_PCT,
    max_hold: int = MAX_HOLD_DAYS,
    flip_cost: float = FLIP_COST_PCT,
    cooldown: int = COOLDOWN_DAYS,
) -> list[dict]:
    """Daily-momentum simulator. Returns list of trade dicts.

    Long-only. Enters when close[t] > max(high[t-lookback : t]).
    Exits on stop/TP/time. One-position-at-a-time per token.
    """
    if len(rows) < lookback + 2:
        return []
    closes = [r["close"] for r in rows]
    highs = [r["high"] for r in rows]
    timestamps = [r["ts"] for r in rows]

    trades: list[dict] = []
    i = lookback
    last_exit = -1
    while i < len(rows) - 1:
        if i <= last_exit + cooldown:
            i += 1
            continue
        prior_high = max(highs[i - lookback : i])
        if closes[i] <= prior_high:
            i += 1
            continue
        # ENTRY at close[i]
        entry_price = closes[i]
        entry_idx = i
        exit_idx: int | None = None
        exit_reason = "time_stop"
        exit_price = entry_price
        for fwd in range(1, max_hold + 1):
            j = i + fwd
            if j >= len(rows):
                exit_idx = len(rows) - 1
                exit_price = closes[exit_idx]
                exit_reason = "time_stop"
                break
            cj = closes[j]
            pnl_pct = (cj - entry_price) / entry_price * 100
            if pnl_pct <= -stop_pct:
                exit_idx = j
                exit_price = entry_price * (1 - stop_pct / 100)
                exit_reason = "stop_loss"
                break
            if pnl_pct >= tp_pct:
                exit_idx = j
                exit_price = entry_price * (1 + tp_pct / 100)
                exit_reason = "take_profit"
                break
        if exit_idx is None:
            exit_idx = min(i + max_hold, len(rows) - 1)
            exit_price = closes[exit_idx]
            exit_reason = "time_stop"
        gross_pnl = (exit_price - entry_price) / entry_price * 100
        net_pnl = gross_pnl - flip_cost
        trades.append({
            "entry_ts": timestamps[entry_idx],
            "entry_price": entry_price,
            "exit_ts": timestamps[exit_idx],
            "exit_price": exit_price,
            "exit_reason": exit_reason,
            "gross_pnl_pct": gross_pnl,
            "net_pnl_pct": net_pnl,
            "hold_days": exit_idx - entry_idx,
        })
        last_exit = exit_idx
        i = exit_idx + 1
    return trades


def stratify_universe() -> dict[str, dict]:
    """Run simulator over every token; return per-token summary stats.

    Each entry: {n, wins, losses, scratches, mean_pct, sum_pct, sharpe, trades}.
    """
    out: dict[str, dict] = {}
    for sym in list_tokens():
        rows = load_token(sym)
        if not rows:
            continue
        trades = simulate_token(rows)
        if not trades:
            out[sym] = {"n": 0, "trades": []}
            continue
        pnls = [t["net_pnl_pct"] for t in trades]
        wins = sum(1 for p in pnls if p >= 0.5)
        losses = sum(1 for p in pnls if p <= -0.5)
        scratches = len(pnls) - wins - losses
        mean = st.mean(pnls)
        sd = st.pstdev(pnls) if len(pnls) > 1 else 1.0
        sharpe_per_trade = (mean / sd) if sd > 0 else 0.0
        out[sym] = {
            "n": len(pnls),
            "wins": wins,
            "losses": losses,
            "scratches": scratches,
            "mean_pct": mean,
            "sum_pct": sum(pnls),
            "sharpe_per_trade": sharpe_per_trade,
            "strict_wr": (wins / len(pnls)) if pnls else 0.0,
            "trades": trades,
        }
    return out


def cohort_lists(strat: dict[str, dict], k: int = 10) -> dict:
    """Rank tokens; produce TOP / BOTTOM cohort symbol lists.

    Excludes tokens with N < 5 trades (insufficient sample).
    Ranking metric: sum_pct (cumulative net PnL — same as Phase B).
    """
    valid = {s: d for s, d in strat.items() if d.get("n", 0) >= 5}
    ranked = sorted(valid.items(), key=lambda kv: kv[1]["sum_pct"])
    bottom = ranked[:k]
    top = ranked[-k:][::-1]
    return {
        "minus_ev_cohort": [s for s, _ in bottom],
        "plus_ev_cohort": [s for s, _ in top],
        "ranked_all": [
            (s, d["sum_pct"], d["n"], d.get("strict_wr", 0.0))
            for s, d in ranked
        ],
    }


def train_test_split(strat: dict[str, dict]) -> dict:
    """Derive cohort from EARLY half of each token's trades; validate on LATE half.

    Returns dict with train-cohort, test-period lift, cohort stability metrics.
    """
    # Build per-token train/test trade lists
    train_strat: dict[str, dict] = {}
    test_strat: dict[str, dict] = {}
    for sym, data in strat.items():
        trades = data.get("trades") or []
        if len(trades) < 4:
            continue
        mid = len(trades) // 2
        train_trades = trades[:mid]
        test_trades = trades[mid:]
        for label, tlist, target in (("train", train_trades, train_strat), ("test", test_trades, test_strat)):
            if not tlist:
                continue
            pnls = [t["net_pnl_pct"] for t in tlist]
            wins = sum(1 for p in pnls if p >= 0.5)
            target[sym] = {
                "n": len(pnls), "wins": wins,
                "mean_pct": st.mean(pnls),
                "sum_pct": sum(pnls),
            }
    # Derive cohort from TRAIN
    train_cohort = cohort_lists(train_strat, k=10)
    train_minus = set(train_cohort["minus_ev_cohort"])
    # Apply blind to TEST
    test_kept = {s: d for s, d in test_strat.items() if s not in train_minus}
    test_declined = {s: d for s, d in test_strat.items() if s in train_minus}
    sum_all = sum(d["sum_pct"] for d in test_strat.values())
    sum_kept = sum(d["sum_pct"] for d in test_kept.values())
    sum_declined = sum(d["sum_pct"] for d in test_declined.values())
    lift = sum_kept - sum_all
    return {
        "train_minus_ev_cohort": sorted(train_minus),
        "train_n_trades": sum(d["n"] for d in train_strat.values()),
        "test_n_trades": sum(d["n"] for d in test_strat.values()),
        "test_all_sum_pct": sum_all,
        "test_kept_sum_pct": sum_kept,
        "test_declined_sum_pct": sum_declined,
        "oos_lift_pct": lift,
    }


def main() -> int:
    if not SOLANA_DATA_DIR.exists() or not list_tokens():
        print(f"NO DATA at {SOLANA_DATA_DIR}; run ingest_coingecko_solana_universe.py first")
        return 1

    print(f"=== Phase D #1: derive Solana cohort ===")
    tokens = list_tokens()
    print(f"  ingested tokens: {len(tokens)}")
    print(f"  daily-strategy params: lookback={LOOKBACK_DAYS}d  stop={STOP_PCT}%  TP={TP_PCT}%  max_hold={MAX_HOLD_DAYS}d  cost={FLIP_COST_PCT}%/trip")
    print()

    print("[1/3] Simulating per-token daily-momentum strategy...")
    strat = stratify_universe()
    n_trades_total = sum(d.get("n", 0) for d in strat.values())
    print(f"  total trades simulated: {n_trades_total}")

    print()
    print("[2/3] By-symbol stratification (sorted by cumulative PnL):")
    ranked = sorted(strat.items(), key=lambda kv: kv[1].get("sum_pct", 0))
    print(f"  {'sym':<10s}  {'n':>4s}  {'W/S/L':>10s}  {'strict_wr':>10s}  {'mean':>8s}  {'sum':>9s}  {'sharpe':>7s}")
    print("  " + "-" * 70)
    bot_universe = {"JTO", "JUP", "WIF", "PYTH", "RAY"}
    for sym, d in ranked:
        if d.get("n", 0) < 5:
            continue
        marker = " ★ BOT" if sym in bot_universe else ""
        print(f"  {sym:<10s}  {d['n']:>4d}  {d['wins']:>3d}/{d['scratches']:>3d}/{d['losses']:>3d}  {d['strict_wr']:>10.1%}  {d['mean_pct']:>+7.2f}%  {d['sum_pct']:>+8.1f}%  {d['sharpe_per_trade']:>+6.2f}{marker}")

    print()
    print("[3/3] Cohort lists (in-sample, top/bottom 10):")
    cohorts = cohort_lists(strat, k=10)
    print(f"  MINUS_EV (chronic losers): {cohorts['minus_ev_cohort']}")
    print(f"  PLUS_EV  (chronic winners): {cohorts['plus_ev_cohort']}")

    # Bot universe classification
    print()
    print("Bot universe classification:")
    for sym in ("JTO", "JUP", "WIF", "PYTH", "RAY"):
        if sym in strat and strat[sym].get("n", 0) >= 5:
            d = strat[sym]
            classification = (
                "MINUS_EV" if sym in cohorts["minus_ev_cohort"]
                else "PLUS_EV" if sym in cohorts["plus_ev_cohort"]
                else "neutral"
            )
            print(f"  {sym}: n={d['n']}  sum_pct={d['sum_pct']:+.1f}%  → {classification}")
        else:
            print(f"  {sym}: INSUFFICIENT DATA (need n>=5)")

    print()
    print("[BONUS] Train/test split validation (early half train; late half test):")
    tt = train_test_split(strat)
    print(f"  train_minus_ev_cohort: {tt['train_minus_ev_cohort']}")
    print(f"  train trades: {tt['train_n_trades']}  test trades: {tt['test_n_trades']}")
    print(f"  TEST all (no filter):           sum_pct = {tt['test_all_sum_pct']:+.1f}%")
    print(f"  TEST after train-cohort filter: sum_pct = {tt['test_kept_sum_pct']:+.1f}%")
    print(f"  Declined (train-cohort) on test: sum_pct = {tt['test_declined_sum_pct']:+.1f}%")
    print(f"  OOS LIFT from filter: {tt['oos_lift_pct']:+.1f}%")
    print(f"    (positive = filter improved out-of-sample; negative = made it worse)")

    # Persist final cohort lists to JSON
    out = {
        "minus_ev_cohort": cohorts["minus_ev_cohort"],
        "plus_ev_cohort": cohorts["plus_ev_cohort"],
        "n_tokens_simulated": len([s for s, d in strat.items() if d.get("n", 0) >= 5]),
        "total_trades": n_trades_total,
        "train_test": {
            "train_minus_ev_cohort": tt["train_minus_ev_cohort"],
            "oos_lift_pct": tt["oos_lift_pct"],
        },
        "strategy_params": {
            "lookback_days": LOOKBACK_DAYS,
            "stop_pct": STOP_PCT,
            "tp_pct": TP_PCT,
            "max_hold_days": MAX_HOLD_DAYS,
            "flip_cost_pct": FLIP_COST_PCT,
            "cooldown_days": COOLDOWN_DAYS,
        },
    }
    out_path = SOLANA_DATA_DIR / "_cohort_result.json"
    out_path.write_text(json.dumps(out, indent=2))
    print()
    print(f"Cohort saved → {out_path.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
