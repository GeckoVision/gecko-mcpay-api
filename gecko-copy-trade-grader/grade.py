#!/usr/bin/env python3
"""gecko-copy-trade-grader — CLI entry point.

Two invocation modes:

  1. Per-trade JSON input (any source):
     python grade.py --trades trades.json
     python grade.py --trades trades.json --n-peers 200 --trader-label "MyTrader"

  2. OKX leaderboard mode (requires okx-agent-trade-kit MCP wired):
     python grade.py --okx-leaderboard --period 30d
     python grade.py --okx-leaderboard --period 30d --period 90d --stability
     python grade.py --okx-leaderboard --period 30d --author-id <id>
     python grade.py --sample   # use the bundled snapshot (no MCP needed)

Outputs human-readable scorecard to stdout, plus JSON to
analysis/data/copy_trade_grader/ if --save is set.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from grader import (
    cross_period_stability,
    grade_okx_trader_from_payload,
    grade_trades,
    render_okx_scorecard,
    render_scorecard,
)
from handoff import render_handoffs

SKILL_DIR = Path(__file__).parent


def cmd_trades(args) -> int:
    raw = json.loads(Path(args.trades).read_text())
    sc = grade_trades(raw, trader_label=args.trader_label, n_peers=args.n_peers)
    print(render_scorecard(sc))
    if args.save:
        out_dir = SKILL_DIR / "out"
        out_dir.mkdir(exist_ok=True)
        (out_dir / f"{args.trader_label.replace(' ', '_')}.json").write_text(
            json.dumps(sc.__dict__, indent=2, default=str)
        )
    return 0


def cmd_okx_sample(args) -> int:
    """Use bundled sample data — no MCP required."""
    sample_path = SKILL_DIR / "examples" / "okx_top5_snapshot.json"
    if not sample_path.exists():
        print(f"ERROR: sample missing at {sample_path}")
        return 1
    snapshot = json.loads(sample_path.read_text())
    traders = snapshot.get("data", [])
    print(
        f"Grading {len(traders)} sample OKX traders (snapshot: {snapshot.get('snapshot_ts', 'n/a')})\n"
    )
    results = []
    for t in traders:
        r = grade_okx_trader_from_payload(t)
        results.append(r)
    print(render_okx_scorecard(results, okx_sort_key="okx_pnl_ratio"))
    # Sprint 23 — one-click Oracle handoff for A/B-graded traders.
    print(render_handoffs(results, period="30d"))
    return 0


def cmd_okx_leaderboard(args) -> int:
    """Pull live data via OKX MCP (or read from cached --raw-json)."""
    if args.raw_json:
        paths = {p: Path(rj) for p, rj in zip(args.period, args.raw_json)}
    else:
        # In a fully-wired environment this would call the MCP directly.
        # For the skill repo we expect the user to fetch+save first, then point at JSON.
        print("ERROR: --raw-json required (point at one or more OKX MCP fetch results)")
        print("Example workflow:")
        print("  1. Invoke mcp__okx-agent-trade-kit__smartmoney_get_traders_by_filter")
        print("  2. Save the JSON to a file")
        print(
            "  3. python grade.py --okx-leaderboard --period 30d --raw-json /path/to/raw_30d.json"
        )
        return 1

    graded_by_period = {}
    for period, path in paths.items():
        raw = json.loads(path.read_text())
        traders = raw.get("data", [])
        if args.author_id:
            traders = [t for t in traders if t.get("authorId") == args.author_id]
        graded_by_period[period] = [grade_okx_trader_from_payload(t) for t in traders]

    if args.stability and len(graded_by_period) >= 2:
        print("=" * 100)
        print(f"CROSS-PERIOD STABILITY ({' vs '.join(graded_by_period.keys())})")
        print("=" * 100)
        summary = cross_period_stability(graded_by_period)
        print(summary)
    else:
        for period, results in graded_by_period.items():
            print(f"\n=== Period: {period} ({len(results)} traders) ===\n")
            print(render_okx_scorecard(results, okx_sort_key="okx_pnl_ratio"))
            # Sprint 23 — Oracle handoff for A/B-graders in THIS period.
            print(render_handoffs(results, period=period))
    return 0


def main():
    p = argparse.ArgumentParser(description="gecko-copy-trade-grader")
    p.add_argument("--trades", help="path to per-trade JSON")
    p.add_argument("--trader-label", default="trader", help="label for scorecard header")
    p.add_argument(
        "--n-peers", type=int, default=100, help="leaderboard size for selection-bias deflation"
    )
    p.add_argument("--okx-leaderboard", action="store_true", help="OKX leaderboard mode")
    p.add_argument(
        "--period", action="append", default=[], help="OKX period: 7d, 30d, or 90d (repeatable)"
    )
    p.add_argument(
        "--raw-json", action="append", default=[], help="path to pre-fetched leaderboard JSON"
    )
    p.add_argument("--author-id", help="single OKX authorId to grade")
    p.add_argument("--stability", action="store_true", help="run cross-period stability")
    p.add_argument("--sample", action="store_true", help="use bundled sample (no MCP)")
    p.add_argument("--save", action="store_true", help="save JSON outputs to ./out/")
    args = p.parse_args()

    if args.sample:
        return cmd_okx_sample(args)
    if args.okx_leaderboard:
        return cmd_okx_leaderboard(args)
    if args.trades:
        return cmd_trades(args)
    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
