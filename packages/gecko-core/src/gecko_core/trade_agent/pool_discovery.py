"""Pool discovery — mint → which pools the Launch Firewall should watch.

The map the live ingest runner needs: given only a token mint, find its DEX
pools, identify the deep "truth-price" pool vs the thin satellite pools (the F5
price-bait candidates), and resolve the quote→USD rate. Built on the keyless
GeckoTerminal per-pool endpoint we already use (no new API key).

Lives one level ABOVE the hotpath island (it may import `gecko_core.sources`) so
the hotpath stream stays dependency-clean. The API lifespan calls
:func:`discover_pools`, then hands the selected pools to the runner's
``track_pool`` — the runner never imports this.

What it does NOT do: resolve the on-chain *vault account addresses* a swap
subscription needs. GeckoTerminal exposes pool metadata + reserves but not the
two SPL token-vault PDAs; that resolution is per-DEX on-chain decoding and is the
live-smoke step (the `VaultResolver` seam below documents it). Everything here is
offline-testable against recorded pool payloads (Pattern B).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.sources.coingecko import CoinGeckoClient, OnchainPool

# A token is treated as a stablecoin quote when its USD price is ~1; below this
# absolute reserve a pool is too thin to be the index-truth pool.
MIN_INDEX_RESERVE_USD = 1_000.0
DEFAULT_MAX_WATCH = 6


class DiscoveredPool(BaseModel):
    """One pool oriented to the analyzed mint (our mint = ``base``).

    ``quote_usd_per_unit`` is the USD value of one quote token (≈1.0 for USDC,
    the live price for SOL) — the rate the reserve tracker needs to value the
    quote leg without a separate price feed.
    """

    model_config = ConfigDict(extra="forbid")

    pool_addr: str
    dex: str | None = None
    base_mint: str | None = Field(default=None, description="The analyzed token's mint.")
    quote_mint: str | None = None
    tvl_usd: float | None = Field(default=None, ge=0.0)
    base_price_usd: float | None = Field(default=None, ge=0.0)
    quote_usd_per_unit: float | None = Field(default=None, ge=0.0)
    buys_5m: int | None = None
    sells_5m: int | None = None
    vol_5m_usd: float | None = Field(default=None, ge=0.0)


@runtime_checkable
class VaultResolver(Protocol):
    """The live seam: pool address → its two token-vault account pubkeys.

    GeckoTerminal does not expose vaults, so a concrete resolver reads the pool
    account on-chain (per-DEX layout) or uses a provider. Deferred to the live
    smoke; the runner is handed (base_vault, quote_vault) once resolved.
    """

    async def resolve(self, pool: DiscoveredPool) -> tuple[str, str] | None: ...


def orient_to_mint(pool: OnchainPool, mint: str) -> DiscoveredPool:
    """Re-orient a raw pool so the analyzed ``mint`` is the base leg.

    GeckoTerminal's base/quote ordering is arbitrary w.r.t. the token we're
    analyzing; we flip so ``base`` is always our mint and ``quote_usd_per_unit``
    is the other leg's USD price.
    """
    mint_is_base = pool.base_mint == mint
    if mint_is_base:
        base_mint, quote_mint = pool.base_mint, pool.quote_mint
        base_price = pool.base_token_price_usd
        quote_usd = pool.quote_token_price_usd
    else:
        base_mint, quote_mint = pool.quote_mint, pool.base_mint
        base_price = pool.quote_token_price_usd
        quote_usd = pool.base_token_price_usd
    return DiscoveredPool(
        pool_addr=pool.pool_address,
        dex=pool.dex,
        base_mint=base_mint,
        quote_mint=quote_mint,
        tvl_usd=pool.reserve_in_usd,
        base_price_usd=base_price,
        quote_usd_per_unit=quote_usd,
        buys_5m=pool.buys_5m,
        sells_5m=pool.sells_5m,
        vol_5m_usd=pool.volume_5m_usd,
    )


def rank_pools(pools: list[DiscoveredPool]) -> list[DiscoveredPool]:
    """Deepest TVL first — the canonical ordering."""
    return sorted(pools, key=lambda p: p.tvl_usd or 0.0, reverse=True)


def select_index_pool(pools: list[DiscoveredPool]) -> DiscoveredPool | None:
    """The deep pool whose price is the truth (the F5 reference). None if all thin.

    Requires a minimum absolute reserve so a manipulated thin pool can't pose as
    the index.
    """
    for p in rank_pools(pools):
        if (p.tvl_usd or 0.0) >= MIN_INDEX_RESERVE_USD:
            return p
    ranked = rank_pools(pools)
    return ranked[0] if ranked else None


def select_watch_set(
    pools: list[DiscoveredPool], *, max_watch: int = DEFAULT_MAX_WATCH
) -> list[DiscoveredPool]:
    """Which pools to subscribe to: the deepest (index) + thin satellites.

    The deep pool anchors the true price; the thin/overpriced satellites are the
    F5 price-bait candidates. We watch the top-N by TVL (which always includes
    the index) so both ends are covered without subscribing to every dust pool.
    """
    return rank_pools(pools)[: max(1, max_watch)]


async def discover_pools(
    mint: str,
    market_client: CoinGeckoClient | None = None,
    *,
    network: str = "solana",
) -> list[DiscoveredPool]:
    """Fetch + orient + rank the pools for ``mint``. Fail-OPEN to ``[]``.

    Thin wrapper: the network call lives in the CoinGecko client; the orientation
    + ranking is pure (and unit-tested directly). A default client is built when
    one isn't injected.
    """
    client = market_client if market_client is not None else CoinGeckoClient()
    try:
        raw = await client.onchain_token_pools(mint, network=network)
    except Exception:
        return []
    return rank_pools([orient_to_mint(p, mint) for p in raw])
