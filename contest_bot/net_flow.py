"""Net-flow / CVD (Cumulative Volume Delta) computation for the wave-2b EDGE gate.

Public API:
    compute_net_flow(token, symbol, oc_client) -> NetFlowSignal | None

Strategy:
  1. Fetch recent trades via ``get_token_trades(token, limit=100)``.
     Each trade dict should carry ``side`` ("buy"/"sell" variants) and
     ``usd_amount`` (or equivalent). We reconstruct CVD = sum(buy USD) -
     sum(sell USD).
  2. Optionally augment with ``get_signals(wallet_type=1, token=token)``
     for smart-money buy signals (wallet_type=1 = Smart Money).
  3. Return a ``NetFlowSignal`` with:
       net_flow_usd     : float  — positive = net buying, negative = net selling
       smart_money_buys : int    — count of smart-money buy signals
       verdict          : "accumulation" | "distribution" | "neutral"
       cached_at        : float  — time.time() of computation

Design rules:
  - Per-instrument LRU cache with TTL_SECONDS (90s default). These are
    network calls — don't hammer onchainos on every poll.
  - Degrade gracefully: any onchainos failure → return None (caller
    treats None as neutral / pass-through). NEVER raise into the trading
    loop.
  - The gate in poll_instruments() blocks only "distribution" — it does
    NOT block "neutral" (unknown is pass-through, not a veto).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Per-instrument cache: {token: (NetFlowSignal, computed_at)}
_CACHE: dict[str, tuple["NetFlowSignal", float]] = {}
TTL_SECONDS: float = 90.0  # cache lifetime — two polls at 30s each


@dataclass
class NetFlowSignal:
    """On-chain net-flow snapshot for one instrument."""

    net_flow_usd: float
    smart_money_buys: int
    verdict: str  # "accumulation" | "distribution" | "neutral"
    cached_at: float = field(default_factory=time.time)

    # Thresholds used to compute the verdict, exposed for telemetry / tests.
    buy_usd: float = 0.0
    sell_usd: float = 0.0
    trade_count: int = 0


# Minimum net-flow magnitude (USD) to call accumulation or distribution.
# Below this the signal is too weak; classify as neutral.
_NEUTRAL_BAND_USD: float = 500.0

# Minimum absolute net-flow as % of total volume to overcome the neutral band.
# Prevents tiny-vol tokens from false accumulation verdicts on $1 imbalance.
_NEUTRAL_BAND_PCT: float = 0.10  # 10% net imbalance required

# Smart-money buy signals below this count don't upgrade neutral → accumulation
# (we leave verdict based on CVD alone; SM buys are additive confirmation).
_SM_UPGRADE_THRESHOLD: int = 2


def _parse_side(trade: dict[str, Any]) -> str:
    """Normalize trade side to 'buy' or 'sell'. Returns '' if unknown."""
    raw = (
        trade.get("side")
        or trade.get("tradeType")
        or trade.get("type")
        or ""
    )
    s = str(raw).lower()
    if s in ("buy", "1", "b"):
        return "buy"
    if s in ("sell", "2", "s"):
        return "sell"
    return ""


def _parse_usd(trade: dict[str, Any]) -> float:
    """Extract USD amount from a trade dict (best-effort, multiple field names)."""
    for key in ("usd_amount", "usdAmount", "amount_usd", "amountUsd", "amount"):
        v = trade.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 0.0


def _verdict_from_cvd(buy_usd: float, sell_usd: float) -> str:
    """Classify net flow given total buy/sell USD volumes."""
    net = buy_usd - sell_usd
    total = buy_usd + sell_usd
    if total <= 0:
        return "neutral"
    net_pct = abs(net) / total
    if abs(net) < _NEUTRAL_BAND_USD or net_pct < _NEUTRAL_BAND_PCT:
        return "neutral"
    return "accumulation" if net > 0 else "distribution"


def compute_net_flow(
    token: str,
    symbol: str,
    oc_client: Any,
) -> NetFlowSignal | None:
    """Compute (or return cached) CVD net-flow for *token*.

    Returns ``None`` on any network/parse failure — caller treats as neutral.
    The result is cached per-token for ``TTL_SECONDS`` to avoid hammering
    onchainos on every 30s poll.

    Args:
        token:     SPL mint address (used as cache key + onchainos address).
        symbol:    Display symbol (PYTH/WIF/JTO…) — used only for logging.
        oc_client: ``OnchainOS`` instance (duck-typed; tests pass fakes).
    """
    now = time.time()
    cached = _CACHE.get(token)
    if cached is not None and (now - cached[1]) < TTL_SECONDS:
        return cached[0]

    try:
        return _fetch_and_cache(token, symbol, oc_client, now)
    except Exception as exc:
        # Broad except: onchainos subprocess errors, JSON issues, etc.
        # Never propagate into the trading loop — instrumentation must not
        # crash trading (same contract as _log_eval_telemetry).
        print(f"[net_flow] {symbol} compute failed ({type(exc).__name__}: {exc}) — degrading to None")
        return None


def _fetch_and_cache(
    token: str,
    symbol: str,
    oc_client: Any,
    now: float,
) -> NetFlowSignal | None:
    """Inner fetch — called only when cache is cold. Raises on error (caller wraps)."""
    # Step 1: token trades → CVD
    trades: list[dict[str, Any]] = oc_client.get_token_trades(token, limit=100)

    buy_usd = 0.0
    sell_usd = 0.0
    count = 0

    for t in trades:
        if not isinstance(t, dict):
            continue
        side = _parse_side(t)
        usd = _parse_usd(t)
        if usd <= 0 or not side:
            continue
        count += 1
        if side == "buy":
            buy_usd += usd
        else:
            sell_usd += usd

    # Step 2: smart-money signal count (best-effort; degrade to 0 on failure)
    sm_buys = 0
    try:
        signals: list[dict[str, Any]] = oc_client.get_signals(
            wallet_type=1, token=token
        )
        # Count signals where direction is bullish/buy
        for sig in signals:
            if not isinstance(sig, dict):
                continue
            direction = str(sig.get("direction", sig.get("type", ""))).lower()
            if direction in ("buy", "bullish", "long", "1"):
                sm_buys += 1
    except Exception:
        # get_signals is optional — CVD alone is sufficient for the gate.
        sm_buys = 0

    verdict = _verdict_from_cvd(buy_usd, sell_usd)

    # Upgrade neutral → accumulation if strong smart-money buy confirmation
    # (doesn't downgrade accumulation → distribution; SM count is additive).
    if verdict == "neutral" and sm_buys >= _SM_UPGRADE_THRESHOLD:
        verdict = "accumulation"

    sig = NetFlowSignal(
        net_flow_usd=round(buy_usd - sell_usd, 2),
        smart_money_buys=sm_buys,
        verdict=verdict,
        cached_at=now,
        buy_usd=round(buy_usd, 2),
        sell_usd=round(sell_usd, 2),
        trade_count=count,
    )
    _CACHE[token] = (sig, now)
    return sig


def cache_clear(token: str | None = None) -> None:
    """Clear cache for testing. Pass token=None to clear all."""
    if token is None:
        _CACHE.clear()
    else:
        _CACHE.pop(token, None)


__all__ = ["NetFlowSignal", "compute_net_flow", "cache_clear", "TTL_SECONDS"]
