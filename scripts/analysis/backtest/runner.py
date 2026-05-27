"""Sprint 6 Phase B — orchestrator.

Run:
    uv run python scripts/analysis/backtest/runner.py
    # or A/B comparison (pre-Sprint-7 vs post):
    uv run python scripts/analysis/backtest/runner.py --ab-trailing

Walks every Binance perp symbol, computes entry candidates, simulates exits,
persists trades to ``analysis/data/backtest/{config_name}/trades.parquet`` +
prints summary stats matching the dashboard's "honest decomposition" shape.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.analysis.backtest import loader, signals, simulator  # noqa: E402

DEFAULT_OUT_DIR = _REPO_ROOT / "analysis" / "data" / "backtest"


@dataclass
class BacktestConfig:
    """The knobs that vary between configs. Used as the config_name path tag."""

    name: str
    breakout_lookback: int = signals.DEFAULT_BREAKOUT_LOOKBACK
    trend_window: int = signals.DEFAULT_TREND_SMA_WINDOW
    stop_loss_pct: float = simulator.DEFAULT_STOP_LOSS_PCT
    take_profit_pct: float = simulator.DEFAULT_TAKE_PROFIT_PCT
    trail_activate_pct: float = simulator.DEFAULT_TRAIL_ACTIVATE_PCT
    trail_stop_pct: float | None = simulator.DEFAULT_TRAIL_STOP_PCT
    trail_min_pnl_pct: float = simulator.DEFAULT_TRAIL_MIN_PNL_PCT
    flip_cost_pct: float = simulator.DEFAULT_FLIP_COST_PCT
    # Sprint 6 Phase C 2026-05-27: apply memory_voice v2's cohort filter
    # (decline entries on chronic -EV cohort symbols per Phase B by-symbol).
    apply_v2_cohort_filter: bool = False


def run_backtest(
    universe: dict[str, pd.DataFrame] | None = None,
    config: BacktestConfig | None = None,
) -> pd.DataFrame:
    """Run the v1 backtest over a universe (default: every loaded symbol).

    Returns a DataFrame of synthetic trades.
    """
    cfg = config or BacktestConfig(name="default")
    uni = universe if universe is not None else loader.load_universe()

    # Sprint 6 Phase C: optional v2 cohort filter — skip symbols v2 would decline
    if cfg.apply_v2_cohort_filter:
        # Lazy import — backtest is otherwise bot-module-free; only fires when on.
        import sys as _sys
        from pathlib import Path as _P

        _bot_dir = _P(__file__).resolve().parents[3] / "contest_bot"
        if str(_bot_dir) not in _sys.path:
            _sys.path.insert(0, str(_bot_dir))
        from voices.memory_voice_v2 import would_decline_for_backtest

        declined_symbols = {s for s in uni if would_decline_for_backtest(s)}
        uni = {s: df for s, df in uni.items() if s not in declined_symbols}

    all_trades: list[pd.DataFrame] = []
    for sym, df in uni.items():
        candidates = signals.candidate_entries(
            df,
            breakout_lookback=cfg.breakout_lookback,
            trend_window=cfg.trend_window,
        )
        candidates = signals.dedupe_entries(candidates)
        if not candidates.any():
            continue
        trades = simulator.simulate_symbol(
            df,
            candidates,
            symbol=sym,
            stop_loss_pct=cfg.stop_loss_pct,
            take_profit_pct=cfg.take_profit_pct,
            trail_activate_pct=cfg.trail_activate_pct,
            trail_stop_pct=cfg.trail_stop_pct,
            trail_min_pnl_pct=cfg.trail_min_pnl_pct,
            flip_cost_pct=cfg.flip_cost_pct,
        )
        if not trades.empty:
            all_trades.append(trades)
    if not all_trades:
        return pd.DataFrame()
    combined = pd.concat(all_trades, ignore_index=True).sort_values("entry_ts")
    return combined.reset_index(drop=True)


def label_outcomes(trades: pd.DataFrame, min_win_pct: float = 0.5) -> pd.DataFrame:
    """Add outcome_label column (W/S/L) per MIN_REALIZED_WIN_PCT.

    Matches the bot's bot-honesty Fix 2 + Phase A transform.label_outcome
    semantics so backtest + live use the same labels.
    """
    out = trades.copy()
    if "net_pnl_pct" not in out.columns:
        out["outcome_label"] = "unknown"
        return out

    def _cls(v: float) -> str:
        if pd.isna(v):
            return "unknown"
        if v >= min_win_pct:
            return "win"
        if v <= -min_win_pct:
            return "loss"
        return "scratch"

    out["outcome_label"] = out["net_pnl_pct"].apply(_cls)
    return out


def summarize(trades: pd.DataFrame) -> dict:
    """Produce the dashboard 'honest decomposition' shape from trades.

    Keys: total_n, wins, scratches, losses, strict_wr, mean_net_pct,
    sum_net_pct, by_exit_reason (dict of dicts), by_symbol (top 10).
    """
    if trades.empty:
        return {"total_n": 0}
    pos = trades.copy()
    if "outcome_label" not in pos.columns:
        pos = label_outcomes(pos)
    out: dict = {
        "total_n": int(len(pos)),
        "wins": int((pos["outcome_label"] == "win").sum()),
        "scratches": int((pos["outcome_label"] == "scratch").sum()),
        "losses": int((pos["outcome_label"] == "loss").sum()),
        "mean_net_pct": float(pos["net_pnl_pct"].mean()),
        "sum_net_pct": float(pos["net_pnl_pct"].sum()),
        "mean_age_bars": float(pos["age_bars"].mean()),
    }
    total = out["total_n"]
    out["strict_wr"] = round(out["wins"] / total, 3) if total else 0.0
    # By exit reason
    by_er: dict[str, dict] = {}
    for er, g in pos.groupby("exit_reason"):
        by_er[er] = {
            "n": int(len(g)),
            "wins": int((g["outcome_label"] == "win").sum()),
            "scratches": int((g["outcome_label"] == "scratch").sum()),
            "losses": int((g["outcome_label"] == "loss").sum()),
            "mean_net_pct": round(float(g["net_pnl_pct"].mean()), 3),
            "sum_net_pct": round(float(g["net_pnl_pct"].sum()), 3),
        }
    out["by_exit_reason"] = by_er
    # By symbol — top 10 by trade count
    by_sym = (
        pos.groupby("symbol")
        .agg(n=("symbol", "size"), mean_pct=("net_pnl_pct", "mean"), sum_pct=("net_pnl_pct", "sum"))
        .sort_values("n", ascending=False)
        .head(10)
        .reset_index()
    )
    out["by_symbol_top10"] = by_sym.to_dict(orient="records")
    return out


def _persist(
    trades: pd.DataFrame,
    summary: dict,
    out_dir: Path,
    config: BacktestConfig,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    trades_p = out_dir / "trades.parquet"
    summary_p = out_dir / "summary.json"
    config_p = out_dir / "config.json"
    if not trades.empty:
        trades.to_parquet(trades_p, index=False)
    else:
        # write an empty parquet so the path always exists
        pd.DataFrame().to_parquet(trades_p, index=False)
    summary_p.write_text(json.dumps(summary, indent=2, default=str))
    config_p.write_text(json.dumps(asdict(config), indent=2))
    return {"trades": trades_p, "summary": summary_p, "config": config_p}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    ap.add_argument(
        "--ab-trailing",
        action="store_true",
        help=(
            "Run BOTH pre-Sprint-7 trail config (trail_stop_pct=1.0, no safety floor) "
            "AND post-Sprint-7 (trail_stop_pct=0.5, safety floor=-1.0) for A/B comparison"
        ),
    )
    ap.add_argument(
        "--ab-v2-cohort",
        action="store_true",
        help=(
            "Run BOTH post-Sprint-7 WITHOUT v2 cohort filter AND post-Sprint-7 WITH "
            "v2 cohort filter (Phase C — skip entries on chronic -EV symbols per Phase B)"
        ),
    )
    ap.add_argument("--symbol-limit", type=int, default=None, help="cap symbol count (for fast iteration)")
    args = ap.parse_args(argv)

    out_root = Path(args.out_dir)
    print(f"==> loading Binance perp universe...")
    universe = loader.load_universe()
    if args.symbol_limit:
        symbols = sorted(universe.keys())[: args.symbol_limit]
        universe = {s: universe[s] for s in symbols}
    print(f"    {len(universe)} symbols loaded")

    configs: list[BacktestConfig] = []
    if args.ab_trailing:
        configs.append(
            BacktestConfig(
                name="pre_sprint7",
                trail_stop_pct=1.0,
                trail_min_pnl_pct=-100.0,  # effectively no floor
            )
        )
        configs.append(BacktestConfig(name="post_sprint7"))
    elif args.ab_v2_cohort:
        configs.append(BacktestConfig(name="post_sprint7_no_v2_filter"))
        configs.append(
            BacktestConfig(
                name="post_sprint7_with_v2_cohort",
                apply_v2_cohort_filter=True,
            )
        )
    else:
        configs.append(BacktestConfig(name="default_sprint7"))

    for cfg in configs:
        print(f"\n==> running config '{cfg.name}'...")
        trades = run_backtest(universe=universe, config=cfg)
        trades = label_outcomes(trades)
        summary = summarize(trades)
        out_dir = out_root / cfg.name
        paths = _persist(trades, summary, out_dir, cfg)
        print(f"    trades: {len(trades)}  → {paths['trades'].relative_to(_REPO_ROOT)}")
        print(f"    summary: {paths['summary'].relative_to(_REPO_ROOT)}")
        # echo headline
        if summary.get("total_n", 0) > 0:
            print(
                f"    HEADLINE: n={summary['total_n']}  W={summary['wins']}/"
                f"S={summary['scratches']}/L={summary['losses']}  "
                f"strict_wr={summary['strict_wr']:.1%}  "
                f"mean_net_pct={summary['mean_net_pct']:+.3f}%  "
                f"sum_net_pct={summary['sum_net_pct']:+.1f}%"
            )
            print(f"    BY EXIT REASON:")
            for er, s in summary["by_exit_reason"].items():
                print(
                    f"      {er:18s}  n={s['n']:4d}  W/S/L={s['wins']:3d}/{s['scratches']:3d}/{s['losses']:3d}  "
                    f"mean={s['mean_net_pct']:+.3f}%"
                )

    return 0


if __name__ == "__main__":
    sys.exit(main())
