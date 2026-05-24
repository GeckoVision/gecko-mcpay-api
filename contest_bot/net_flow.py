"""Net-flow / CVD (Cumulative Volume Delta) computation for the wave-2b EDGE gate.

Public API:
    compute_net_flow(token, symbol, oc_client) -> NetFlowSignal | None

Strategy:
  1. Fetch recent trades via ``get_token_trades(token, limit=100)``.
     Each real onchainos ``token trades`` row carries ``type`` ("buy"/"sell")
     and ``changedTokenInfo`` — a 2-leg list [base-token leg, quote-token leg].
     There is NO flat ``usd_amount`` field (the pre-S44 parser probed for one
     and ALWAYS got 0.0 → every trade skipped → CVD always neutral → the gate
     was a silent no-op). We reconstruct per-trade USD from the QUOTE leg:
        usd = quote_amount × quote_token_USD_price
     CVD = sum(buy USD) - sum(sell USD).

     QUOTE-TOKEN UNIT TRAP (the whole reason this is per-trade): the same
     token's trades can be quoted in SOL, USDC, *and* JUP within one response
     (observed live on PYTH 2026-05-23). Stablecoins price ≈ 1; SOL/JUP/etc.
     need a real USD price. We collect the distinct quote mints, price them
     once via ``oc_client.get_price_info`` (stablecoins short-circuit to 1.0),
     then convert each trade against its OWN quote leg — never assume USDC.
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
_CACHE: dict[str, tuple[NetFlowSignal, float]] = {}
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

# Stablecoin mints (Solana) — quote-USD price is 1.0, no network lookup needed.
# Keyed by mint address (the only stable identifier; symbols vary, e.g. "$WIF").
_STABLE_MINTS: dict[str, float] = {
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": 1.0,  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": 1.0,  # USDT
}

# Wrapped SOL mint — common quote leg on Raydium/Orca pools.
_WSOL_MINT = "So11111111111111111111111111111111111111112"


def _parse_side(trade: dict[str, Any]) -> str:
    """Normalize trade side to 'buy' or 'sell'. Returns '' if unknown.

    Real onchainos ``token trades`` rows carry a plain ``type`` of "buy"/"sell".
    We keep the legacy ``side``/``tradeType`` aliases for defensiveness.
    """
    raw = trade.get("type") or trade.get("side") or trade.get("tradeType") or ""
    s = str(raw).lower()
    if s in ("buy", "1", "b"):
        return "buy"
    if s in ("sell", "2", "s"):
        return "sell"
    return ""


def _quote_leg(trade: dict[str, Any], base_addr: str) -> dict[str, Any] | None:
    """Return the quote-token leg of a trade (the changedTokenInfo entry whose
    address is NOT the queried/base token). Returns None if not derivable.

    base_addr falls back to the trade's own ``tokenContractAddress`` so the
    function works even when the caller didn't pass the queried mint.
    """
    legs = trade.get("changedTokenInfo")
    if not isinstance(legs, list) or len(legs) < 2:
        return None
    base = (base_addr or str(trade.get("tokenContractAddress") or "")).lower()
    for leg in legs:
        if not isinstance(leg, dict):
            continue
        addr = str(leg.get("tokenAddress") or "").lower()
        if addr and addr != base:
            return leg
    return None


def _parse_usd(
    trade: dict[str, Any],
    base_addr: str,
    quote_prices: dict[str, float],
) -> float:
    """Reconstruct a trade's USD value from its quote leg × quote-USD price.

    ``quote_prices`` maps quote-token mint (lowercase) → USD price. Returns
    0.0 when the quote leg or its price is unavailable — the caller skips
    such trades (we'd rather drop an unpriceable trade than mis-size CVD).
    """
    leg = _quote_leg(trade, base_addr)
    if leg is None:
        return 0.0
    addr = str(leg.get("tokenAddress") or "").lower()
    price = quote_prices.get(addr)
    if not price:
        return 0.0
    try:
        amount = float(leg.get("amount") or 0)
    except (TypeError, ValueError):
        return 0.0
    return amount * price


def _spot_from_price_response(resp: Any) -> float:
    """Extract a token's USD spot from an onchainos ``token price-info`` response.

    The CLI returns ``{"data": [<dict with "price">]}`` (list-wrapped) or, on
    some single-token paths, ``{"data": <dict>}``. Mirrors the bot's own
    ``_spot_from_price_response`` so net_flow reuses the same price path the
    rest of the runtime already trusts. Returns 0.0 on any parse failure.
    """
    if not isinstance(resp, dict):
        return 0.0
    raw = resp.get("data")
    entry: dict[str, Any] = {}
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        entry = raw[0]
    elif isinstance(raw, dict):
        entry = raw
    try:
        return float(entry.get("price") or 0)
    except (TypeError, ValueError):
        return 0.0


def _resolve_quote_prices(
    trades: list[dict[str, Any]],
    base_addr: str,
    oc_client: Any,
) -> dict[str, float]:
    """Build {quote_mint(lowercase) -> USD price} for every distinct quote leg.

    Stablecoins resolve to 1.0 with no network call. All other quote mints
    (SOL, JUP, …) are priced once via ``oc_client.get_price_info``. A failed
    or zero price is omitted — trades quoted in that token then drop out of
    CVD rather than being mis-valued.
    """
    quote_mints: set[str] = set()
    for t in trades:
        if not isinstance(t, dict):
            continue
        leg = _quote_leg(t, base_addr)
        if leg is not None:
            addr = str(leg.get("tokenAddress") or "").lower()
            if addr:
                quote_mints.add(addr)

    prices: dict[str, float] = {}
    for mint_lc in quote_mints:
        # Stablecoins: short-circuit (keys are checksum-cased mints).
        stable = next((v for k, v in _STABLE_MINTS.items() if k.lower() == mint_lc), None)
        if stable is not None:
            prices[mint_lc] = stable
            continue
        # SOL + everything else: real price lookup. get_price_info wants the
        # original-cased mint; for WSOL we have it, otherwise reuse the leg's
        # tokenAddress as seen in the trades.
        lookup_addr = _WSOL_MINT if mint_lc == _WSOL_MINT.lower() else mint_lc
        try:
            resp = oc_client.get_price_info(lookup_addr)
        except Exception:
            continue
        px = _spot_from_price_response(resp)
        if px > 0:
            prices[mint_lc] = px
    return prices


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
        print(
            f"[net_flow] {symbol} compute failed ({type(exc).__name__}: {exc}) — degrading to None"
        )
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

    # Resolve a USD price for every distinct quote-token leg ONCE (SOL, USDC,
    # JUP, …). Per-trade USD is then quote_amount × that quote's USD price —
    # never assume USDC (the unit-inconsistency trap that the old parser, which
    # probed a non-existent flat usd field, silently no-op'd around).
    quote_prices = _resolve_quote_prices(trades, token, oc_client)

    buy_usd = 0.0
    sell_usd = 0.0
    count = 0

    for t in trades:
        if not isinstance(t, dict):
            continue
        side = _parse_side(t)
        usd = _parse_usd(t, token, quote_prices)
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
        signals: list[dict[str, Any]] = oc_client.get_signals(wallet_type=1, token=token)
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


__all__ = [
    "TTL_SECONDS",
    "NetFlowSignal",
    "_parse_side",
    "_parse_usd",
    "_resolve_quote_prices",
    "cache_clear",
    "compute_net_flow",
]
