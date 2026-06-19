"""Fresh-launch fallback: synthesize the market read from pools when the
aggregate /tokens/{addr} endpoint is empty (the firewall's core ICP — confirmed
dark on ~half of live fresh tokens via manipulation_check_unavailable).
"""

from __future__ import annotations

from gecko_core.orchestration.trade_panel.safety_check import evaluate_contract_safety
from gecko_core.sources.coingecko import OnchainPool
from gecko_core.sources.quicknode import TokenSafety

_MINT = "BCAxFqs3VJGTmVsBsyYxWL2zZG6xR1kAynCKkhBKEkxx"  # valid base58-ish 44-char


class _FakeQuickNode:
    """token_safety + token_largest_accounts; supply/decimals drive the mcap synth."""

    def __init__(self, supply: str, decimals: int) -> None:
        self._supply, self._decimals = supply, decimals

    async def token_safety(self, mint: str) -> TokenSafety:
        return TokenSafety(
            mint=mint,
            mint_renounced=True,
            freeze_renounced=True,
            decimals=self._decimals,
            supply=self._supply,
            rug_risk=False,
        )

    async def token_largest_accounts(self, mint: str) -> list[dict]:
        return []  # holder read empty -> top_holder_pct None (orthogonal here)


class _FakeMarket:
    """Aggregate read is EMPTY (fresh token); pools endpoint HAS data."""

    def __init__(self, pools: list[OnchainPool]) -> None:
        self._pools = pools

    async def onchain_token_market(self, mint: str, *, network: str = "solana"):
        return None  # the dark path the live scan exposed

    async def onchain_token_pools(self, mint: str, *, network: str = "solana"):
        return self._pools


class _FakePeg:
    async def depeg_risk_by_mint(self, mint: str):
        raise RuntimeError("no peg")  # -> fail-OPEN None


async def test_fallback_lights_up_fake_mcap_on_fresh_token():
    # 1,000,000 supply (6 decimals) at $5.73 deepest-pool price = $5.73M mcap,
    # backed by $6.5K pool liquidity -> 0.11% -> fake_market_cap (the BrCA shape).
    pools = [
        OnchainPool(
            pool_address="deep",
            dex="raydium",
            base_mint=_MINT,
            quote_mint="So11111111111111111111111111111111111111112",
            base_token_price_usd=5.73,
            quote_token_price_usd=150.0,
            reserve_in_usd=6500.0,
        )
    ]
    block = await evaluate_contract_safety(
        target=_MINT,
        mint=_MINT,
        client=_FakeQuickNode(supply="1000000000000", decimals=6),  # 1,000,000 UI
        market_client=_FakeMarket(pools),
        peg_client=_FakePeg(),
    )
    assert block.checked is True
    # The manipulation read is no longer dark:
    assert "manipulation_check_unavailable" not in block.rug_flags
    assert block.liquidity_usd == 6500.0
    assert block.market_cap_usd is not None and block.market_cap_usd > 5_000_000
    assert block.liquidity_to_mcap_pct is not None and block.liquidity_to_mcap_pct < 0.2
    assert "fake_market_cap" in block.rug_flags
    assert block.information_mev is not None and block.information_mev.label == "manipulated"


async def test_no_pools_still_fails_open():
    # Aggregate empty AND no pools -> still honest 'unavailable', never fabricated.
    block = await evaluate_contract_safety(
        target=_MINT,
        mint=_MINT,
        client=_FakeQuickNode(supply="1000000000000", decimals=6),
        market_client=_FakeMarket([]),
        peg_client=_FakePeg(),
    )
    assert block.checked is True
    assert "manipulation_check_unavailable" in block.rug_flags
    assert block.liquidity_to_mcap_pct is None
