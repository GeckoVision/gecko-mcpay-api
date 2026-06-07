"""Live Kamino catalog → list[LeverageStrategy]. Fallback to curated templates.

Source of truth is the same proven endpoint apy_cache.py uses:
    https://api.kamino.finance/kamino-market/{MAIN_MARKET}/reserves/metrics
Each row is a LEND reserve: {liquidityToken, supplyApy, borrowApy, maxLtv, ...}
(APYs + maxLtv are fractions, e.g. 0.037 == 3.7%, 0.8 == 80%). The endpoint
does NOT expose a liquidation threshold, so we derive it conservatively from
maxLtv. Leveraged Multiply vaults aren't in this feed — the selector overlays
the curated leveraged templates (CURATED_FALLBACK) on top of the live lend set.

Never raises into the caller: any failure falls back to the vetted templates.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from kamino.apy_cache import KAMINO_API_BASE, KAMINO_MAIN_MARKET
from kamino.multiply import LeverageStrategy

logger = logging.getLogger("kamino.catalog")

_RESERVES_ENDPOINT = "/kamino-market/{market}/reserves/metrics"
_HTTP_TIMEOUT_SEC = 12.0
_LIQ_LTV_BUFFER = (
    0.05  # Kamino's liquidation threshold sits just above maxLtv; derive conservatively.
)

# Stables map to stable_spread; well-known LSTs to lst_staking. Anything else is
# left as a generic lend (stable_spread) — the selector's profile filter decides
# whether a generic asset is eligible.
_STABLES = {"USDC", "USDT", "USDG", "PYUSD", "FDUSD", "DAI"}
_LSTS = {"JitoSOL", "mSOL", "bSOL", "JupSOL", "INF", "hSOL"}

# Curated, vetted leveraged templates (mirror vault_orchestrator). Used both as
# the fallback when the API is down and as the Multiply overlay.
CURATED_FALLBACK: list[LeverageStrategy] = [
    LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread"),
    LeverageStrategy("JitoSOL/SOL 4x", 0.07, 0.06, 4.0, 0.90, 0.93, True, "lst_staking"),
    LeverageStrategy("JLP/USDC 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees"),
]


def _yield_source_for(token: str) -> str:
    if token in _LSTS:
        return "lst_staking"
    return "stable_spread"


def normalize_market(
    raw: dict, *, leverage: float, correlated: bool, yield_source: str
) -> LeverageStrategy:
    """Map one Kamino reserve-metrics row → LeverageStrategy. Derives the
    liquidation threshold from maxLtv (the feed doesn't expose it)."""
    max_ltv = float(raw["maxLtv"])
    liq_ltv = min(max_ltv + _LIQ_LTV_BUFFER, 0.98)
    return LeverageStrategy(
        name=str(raw["liquidityToken"]),
        collateral_yield=float(raw["supplyApy"]),
        borrow_rate=float(raw["borrowApy"]),
        leverage=leverage,
        max_ltv=max_ltv,
        liquidation_ltv=liq_ltv,
        correlated=correlated,
        yield_source=yield_source,
    )


def _fetch_live() -> list[dict]:
    url = KAMINO_API_BASE + _RESERVES_ENDPOINT.format(market=KAMINO_MAIN_MARKET)
    with httpx.Client(timeout=_HTTP_TIMEOUT_SEC) as client:
        resp = client.get(url)
        resp.raise_for_status()
        body = resp.json()
    if not isinstance(body, list):
        raise ValueError(f"reserves endpoint returned non-list: {type(body)}")
    return body


def load_catalog(fetch: Callable[[], list[dict]] = _fetch_live) -> list[LeverageStrategy]:
    """Live lend catalog if reachable, else CURATED_FALLBACK. Never raises."""
    try:
        rows = fetch()
    except Exception as e:
        logger.warning("kamino catalog fetch failed (%s) — using curated fallback", e)
        return CURATED_FALLBACK
    out: list[LeverageStrategy] = []
    for raw in rows:
        try:
            token = str(raw["liquidityToken"])
            out.append(
                normalize_market(
                    raw, leverage=1.0, correlated=True, yield_source=_yield_source_for(token)
                )
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out or CURATED_FALLBACK
