#!/usr/bin/env python3
"""Counterfactual labeler for `bot_behaviors` rows.

Standalone script the founder runs manually (cron automation deferred to v2).
For each `bot_behaviors` row with `counterfactual.status == "pending"` AND
`ts <= now - window_min`, fetch forward N-min OHLCV via ccxt, compute
`forward_max_pct`, `forward_min_pct`, `forward_close_pct`, and apply the label.

Label rules (per design doc §3, locked decisions §Task 4):

    action=decline OR action=candidate_blocked
        if forward_min_pct <= -SL_PCT: PREVENTED_LOSS
        elif forward_max_pct >= +TP_PCT: MISSED_WIN
        else:                            NEUTRAL

    action=act (i.e. position fired)
        if outcome.pnl_pct > 0:  REALIZED_WIN
        elif outcome.pnl_pct < 0: REALIZED_LOSS
        elif outcome present:     NEUTRAL
        else:                     skip (still open) — status stays "pending"

Defaults:
    window_min: 240 (locked)
    SL_PCT:     3.0 (bot's STOP_LOSS_PCT default)
    TP_PCT:     1.5 (bot's adaptive_tp_pct midpoint)

Override per-call. Both SL/TP and window come from env or CLI flags so we
can compare labeling strategies retroactively.

Dry-run is the DEFAULT. `--apply` is the explicit opt-in to write back.

Usage:
    # Dry-run summary
    uv run python scripts/labeler/counterfactual_labeler.py

    # Apply patches
    uv run python scripts/labeler/counterfactual_labeler.py --apply

    # Scope to a symbol
    uv run python scripts/labeler/counterfactual_labeler.py --symbol WIF --apply

    # Use a shorter window for A/B
    uv run python scripts/labeler/counterfactual_labeler.py --window-min 60 --apply

Requires:
    MONGODB_URI in env. Network: OKX swap candles via ccxt (no key needed,
    read-only public endpoint).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

# Repo path for ccxt_spine reuse
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

logger = logging.getLogger("counterfactual_labeler")

DEFAULT_WINDOW_MIN = int(os.environ.get("GECKO_BEHAVIOR_COUNTERFACTUAL_WINDOW_MIN", "240"))
DEFAULT_SL_PCT = float(os.environ.get("STOP_LOSS_PCT", "3.0"))
DEFAULT_TP_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "1.5"))
DEFAULT_TIMEFRAME = "5m"  # 240 min / 5m = 48 candles — fine resolution


# ── ccxt fetch wrapper ─────────────────────────────────────────────────


def _fetch_forward_ohlcv(
    symbol: str,
    decision_ts: datetime,
    window_min: int,
    timeframe: str = DEFAULT_TIMEFRAME,
    venue: str = "okx_perp",
) -> list[dict]:
    """Pull `window_min` of forward OHLCV after `decision_ts`.

    Reuses `scripts/calibration/ccxt_spine.fetch_ohlcv`. Returns [] on any
    failure (caller treats as "no data, skip this row").

    Symbol mapping: bot uses "PYTH" / "WIF" — okx swap symbols are
    "PYTH/USDT:USDT" / "WIF/USDT:USDT". We try the swap form first and fall
    back to a spot pair if the swap symbol isn't listed.
    """
    try:
        from calibration.ccxt_spine import fetch_ohlcv
    except Exception as exc:
        logger.warning("ccxt_spine import failed: %s", exc)
        return []

    since_ms = int(decision_ts.timestamp() * 1000)
    end_ms = since_ms + window_min * 60_000
    candidates = [
        (venue, f"{symbol}/USDT:USDT"),
        ("okx_perp", f"{symbol}/USDT:USDT"),
        ("binance_spot", f"{symbol}/USDT"),
    ]
    for v, sym in candidates:
        try:
            rows = fetch_ohlcv(v, sym, timeframe, since_ms, end_ms)
        except Exception as exc:
            logger.debug("forward fetch %s/%s failed: %s", v, sym, exc)
            continue
        if rows:
            return rows
    logger.warning("no forward candles for %s @ %s", symbol, decision_ts.isoformat())
    return []


# ── Label logic (pure, easily testable) ────────────────────────────────


@dataclass
class CounterfactualResult:
    forward_max_pct: float
    forward_min_pct: float
    forward_close_pct: float
    label: str


def compute_counterfactual(
    *,
    decision_price: float,
    forward_candles: list[dict],
    action: str,
    outcome: dict | None,
    sl_pct: float = DEFAULT_SL_PCT,
    tp_pct: float = DEFAULT_TP_PCT,
) -> CounterfactualResult | None:
    """Compute label given decision-time price + forward candles.

    Returns None when we can't label (no candles, or `act` with no outcome).
    """
    if action == "act":
        if outcome is None:
            return None  # still open; defer
        pnl = outcome.get("pnl_pct")
        if pnl is None:
            return CounterfactualResult(0.0, 0.0, 0.0, "NEUTRAL")
        label = "REALIZED_WIN" if pnl > 0 else ("REALIZED_LOSS" if pnl < 0 else "NEUTRAL")
        # forward_*_pct here describes the live trade, not a hypothetical.
        # Surface peak_pct / pnl_pct so the doc is self-describing.
        peak = outcome.get("peak_pct") or 0.0
        return CounterfactualResult(
            forward_max_pct=float(peak),
            forward_min_pct=float(pnl) if pnl < 0 else 0.0,
            forward_close_pct=float(pnl),
            label=label,
        )

    if not forward_candles or decision_price is None or decision_price <= 0:
        return None

    highs = [c.get("high", 0.0) for c in forward_candles if c.get("high")]
    lows = [c.get("low", 0.0) for c in forward_candles if c.get("low")]
    closes = [c.get("close", 0.0) for c in forward_candles if c.get("close")]
    if not highs or not lows or not closes:
        return None

    max_px = max(highs)
    min_px = min(lows)
    close_px = closes[-1]

    fwd_max_pct = (max_px - decision_price) / decision_price * 100.0
    fwd_min_pct = (min_px - decision_price) / decision_price * 100.0
    fwd_close_pct = (close_px - decision_price) / decision_price * 100.0

    # action in {decline, candidate_blocked, unknown}
    if fwd_min_pct <= -abs(sl_pct):
        label = "PREVENTED_LOSS"
    elif fwd_max_pct >= abs(tp_pct):
        label = "MISSED_WIN"
    else:
        label = "NEUTRAL"
    return CounterfactualResult(fwd_max_pct, fwd_min_pct, fwd_close_pct, label)


# ── Main labeling pass ─────────────────────────────────────────────────


@dataclass
class LabelStats:
    scanned: int = 0
    too_recent: int = 0
    skipped_open: int = 0
    no_candles: int = 0
    labeled: int = 0
    by_label: dict[str, int] | None = None

    def summary(self) -> str:
        by = self.by_label or {}
        breakdown = " ".join(f"{k}={v}" for k, v in sorted(by.items()))
        return (
            f"scanned={self.scanned} too_recent={self.too_recent} "
            f"skipped_open={self.skipped_open} no_candles={self.no_candles} "
            f"labeled={self.labeled} {breakdown}"
        )


def _parse_ts(ts_val: Any) -> datetime | None:
    if isinstance(ts_val, datetime):
        return ts_val if ts_val.tzinfo else ts_val.replace(tzinfo=UTC)
    if isinstance(ts_val, str):
        try:
            return datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def run_labeler(
    *,
    collection: Any,
    window_min: int = DEFAULT_WINDOW_MIN,
    sl_pct: float = DEFAULT_SL_PCT,
    tp_pct: float = DEFAULT_TP_PCT,
    symbol: str | None = None,
    apply: bool = False,
    limit: int | None = None,
    fetch_fn: Callable[..., list[dict]] | None = None,
    now: datetime | None = None,
    log: Callable[[str], None] | None = None,
) -> LabelStats:
    """Walk pending behaviors and label them.

    Injection points:
        fetch_fn: defaults to `_fetch_forward_ohlcv` (live ccxt). Tests pass a
            stub returning canned candles.
        now: defaults to `datetime.now(UTC)`.
        log: defaults to print.
    """
    fetch = fetch_fn or _fetch_forward_ohlcv
    say = log or print
    _now = now or datetime.now(UTC)

    stats = LabelStats(by_label={})

    flt: dict[str, Any] = {"counterfactual.status": "pending"}
    if symbol is not None:
        flt["symbol"] = symbol

    cursor = collection.find(flt)
    if limit is not None:
        cursor = cursor.limit(limit)

    for doc in cursor:
        stats.scanned += 1
        ts = _parse_ts(doc.get("ts"))
        if ts is None:
            stats.no_candles += 1
            continue
        # Need window_min of forward data to label.
        if ts + timedelta(minutes=window_min) > _now:
            stats.too_recent += 1
            continue

        action = doc.get("action") or "unknown"
        outcome = doc.get("outcome")
        if action == "act" and outcome is None:
            stats.skipped_open += 1
            continue

        ms = doc.get("market_state") or {}
        decision_price = ms.get("price") or (ms.get("indicators") or {}).get("price")

        forward_candles: list[dict] = []
        if action != "act":
            symbol_name = doc.get("symbol")
            if not symbol_name:
                stats.no_candles += 1
                continue
            forward_candles = fetch(symbol_name, ts, window_min)
            if not forward_candles:
                stats.no_candles += 1
                continue

        result = compute_counterfactual(
            decision_price=decision_price,
            forward_candles=forward_candles,
            action=action,
            outcome=outcome,
            sl_pct=sl_pct,
            tp_pct=tp_pct,
        )
        if result is None:
            stats.skipped_open += 1
            continue

        patch = {
            "counterfactual.status": "labeled",
            "counterfactual.forward_max_pct": round(result.forward_max_pct, 4),
            "counterfactual.forward_min_pct": round(result.forward_min_pct, 4),
            "counterfactual.forward_close_pct": round(result.forward_close_pct, 4),
            "counterfactual.label": result.label,
            "counterfactual.labeled_at": _now,
            "counterfactual.sl_pct_used": sl_pct,
            "counterfactual.tp_pct_used": tp_pct,
            "counterfactual.window_min": window_min,
        }
        if apply:
            try:
                collection.update_one(
                    {"decision_id": doc.get("decision_id")},
                    {"$set": patch},
                )
            except Exception as exc:
                say(f"  WARN: update failed for {doc.get('decision_id')}: {exc}")
                continue
        stats.labeled += 1
        stats.by_label[result.label] = (stats.by_label or {}).get(result.label, 0) + 1
        # Politeness: don't hammer OKX when running over hundreds of rows.
        time.sleep(0.05)

    say(f"[labeler] {stats.summary()}")
    if not apply:
        say("[labeler] dry-run (default) — pass --apply to write back")
    return stats


def _get_collection() -> Any | None:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None
    try:
        from pymongo import MongoClient

        return MongoClient(uri, serverSelectionTimeoutMS=3000)[
            os.environ.get("MONGODB_DB", "gecko")
        ][os.environ.get("MONGODB_BEHAVIOR_COLL", "bot_behaviors")]
    except Exception as exc:
        print(f"[labeler] mongo unavailable: {exc}", file=sys.stderr)
        return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="counterfactual_labeler",
        description="Label pending bot_behaviors rows with forward-window outcomes.",
    )
    p.add_argument("--apply", action="store_true", help="actually write patches (default: dry-run)")
    p.add_argument("--window-min", type=int, default=DEFAULT_WINDOW_MIN)
    p.add_argument("--sl-pct", type=float, default=DEFAULT_SL_PCT)
    p.add_argument("--tp-pct", type=float, default=DEFAULT_TP_PCT)
    p.add_argument("--symbol", default=None, help="scope to one symbol (e.g. WIF)")
    p.add_argument("--limit", type=int, default=None, help="cap rows processed")
    args = p.parse_args(argv)

    coll = _get_collection()
    if coll is None:
        print("[labeler] MONGODB_URI not set — exiting", file=sys.stderr)
        return 2

    stats = run_labeler(
        collection=coll,
        window_min=args.window_min,
        sl_pct=args.sl_pct,
        tp_pct=args.tp_pct,
        symbol=args.symbol,
        apply=args.apply,
        limit=args.limit,
    )
    return 0 if stats.scanned >= 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
