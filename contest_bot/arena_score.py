"""Arena scoring — verified-safe SURVIVAL board over based.bid tokens (Phase 3).

The Arena's KPI is survival, not PnL. This module turns token OHLCV (via the based.bid
feed) into survival metrics and — for any PUBLIC surface — BUCKETED bands only. Raw
drawdown/return floats stay internal; the public board exposes a band + coarse risk
bucket, never a raw number (CLAUDE.md: bucketed bands, no public raw floats, no public
leaderboards). Reused by both the CLI demo and the `/arena/board` API endpoint.
"""

from __future__ import annotations

import json
import math
import os
from datetime import UTC, datetime
from typing import Any

# Hand-picked graduated Solana tokens (stand-ins; real based.bid mints swap in via the
# arena token list once we have their API). Liquid → GeckoTerminal has OHLCV.
DEFAULT_ARENA_TOKENS: dict[str, str] = {
    "WIF": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm",
    "BONK": "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",
    "POPCAT": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr",
    "JTO": "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL",
    "PYTH": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3",
}

# band severity for ranking (survival-first)
_BAND_ORDER = {"surviving+": 0, "surviving": 1, "at-risk": 2, "eliminated": 3}


def max_drawdown(closes: list[float]) -> float:
    peak, mdd = closes[0], 0.0
    for c in closes:
        peak = max(peak, c)
        if peak > 0:
            mdd = max(mdd, (peak - c) / peak)
    return mdd


def realized_vol(closes: list[float]) -> float:
    rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes)) if closes[i - 1] > 0]
    if len(rets) < 2:
        return 0.0
    mu = sum(rets) / len(rets)
    return math.sqrt(sum((r - mu) ** 2 for r in rets) / (len(rets) - 1))


def survival_band(mdd: float, ret: float) -> str:
    """Survival band — not blowing up is the KPI, return is secondary."""
    if mdd >= 0.50:
        return "eliminated"
    if mdd >= 0.30:
        return "at-risk"
    return "surviving+" if ret >= 0 else "surviving"


def _risk_bucket(mdd: float) -> str:
    """Coarse drawdown bucket for the PUBLIC surface (never the raw %)."""
    if mdd >= 0.50:
        return "extreme"
    if mdd >= 0.30:
        return "high"
    if mdd >= 0.15:
        return "moderate"
    return "contained"


def score_token(provider: Any, name: str, mint: str, *, bar: str = "5m", limit: int = 200) -> dict | None:
    """Full (INTERNAL) score for one token, or None if no data (pre-graduation)."""
    candles = provider.get_candles(mint, bar=bar, limit=limit, drop_forming=True)
    if not candles:
        return None
    closes = [c["close"] for c in candles]
    mdd = max_drawdown(closes)
    ret = closes[-1] / closes[0] - 1.0
    return {
        "name": name, "band": survival_band(mdd, ret), "risk_bucket": _risk_bucket(mdd),
        "max_dd": mdd, "vol": realized_vol(closes), "window_ret": ret, "n": len(closes),  # raw = internal
    }


def public_entry(internal: dict) -> dict:
    """PUBLIC board row — bucketed bands only, NO raw floats (drawdown/vol/return stripped)."""
    return {
        "name": internal["name"],
        "band": internal["band"],          # surviving+/surviving/at-risk/eliminated
        "risk_bucket": internal["risk_bucket"],  # contained/moderate/high/extreme
        "bars": internal["n"],
    }


def build_board(
    provider: Any, tokens: dict[str, str] | None = None, *, public: bool = True, bar: str = "5m", limit: int = 200
) -> list[dict]:
    """Survival board over the arena tokens, survival-first ranked. public=True → bucketed
    rows (the wire-safe shape); public=False → raw internal scores (script/diagnostics)."""
    toks = tokens or DEFAULT_ARENA_TOKENS
    scored = [s for name, mint in toks.items() if (s := score_token(provider, name, mint, bar=bar, limit=limit))]
    scored.sort(key=lambda s: (_BAND_ORDER.get(s["band"], 9), s["max_dd"]))
    return [public_entry(s) for s in scored] if public else scored


# ── snapshot I/O (a worker writes; the API reads) ────────────────────────────
# Building the board hits the GeckoTerminal feed (~2 calls/token, throttled) → too
# slow to compute inside an HTTP request. Same split as market_temp: refresh_arena_
# board.py writes the snapshot; GET /arena/board serves it (fast, honest-empty cold).
def snapshot_path() -> str:
    base = os.environ.get("GECKO_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "arena_board.json")


def save_board_snapshot(board: list[dict], path: str | None = None) -> str:
    p = path or snapshot_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    payload = {"board": board, "n": len(board), "updated_at": datetime.now(UTC).isoformat()}
    with open(p, "w") as f:
        json.dump(payload, f)
    return p


def load_board_snapshot(path: str | None = None) -> dict:
    """Latest board snapshot, or an honest-empty stale default if no worker has run."""
    p = path or snapshot_path()
    if not os.path.exists(p):
        return {"board": [], "n": 0, "stale": True, "note": "no arena-board snapshot yet"}
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"board": [], "n": 0, "stale": True, "note": "unreadable snapshot"}
