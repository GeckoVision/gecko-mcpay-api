"""Tests for the live-ingest decoding layer (step 6).

Pure parser + reserve tracker, exercised against the documented jsonParsed shape
and synthetic reserve sequences. No network. (The exact live Helius payload still
needs a one-time smoke before the runner is enabled — see swap_parser docstring.)
"""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.swap_parser import (
    PoolReserveTracker,
    VaultBalance,
    parse_vault_balance,
)


def _acct_notification(mint: str, ui: float, *, slot: int = 100) -> dict:
    """accountSubscribe jsonParsed shape: result.value.data.parsed.info."""
    return {
        "subscription": 1,
        "result": {
            "context": {"slot": slot},
            "value": {
                "data": {
                    "parsed": {
                        "info": {
                            "mint": mint,
                            "owner": "PoolAuthority",
                            "tokenAmount": {
                                "amount": str(int(ui * 1_000_000)),
                                "decimals": 6,
                                "uiAmount": ui,
                                "uiAmountString": str(ui),
                            },
                        },
                        "type": "account",
                    },
                    "program": "spl-token",
                    "space": 165,
                },
                "lamports": 2039280,
                "owner": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA",
            },
        },
    }


# --------------------------------------------------------------------------- #
# parse_vault_balance                                                          #
# --------------------------------------------------------------------------- #


def test_parse_account_subscribe_shape():
    vb = parse_vault_balance(_acct_notification("MintA", 1000.0), pubkey="vaultA")
    assert vb is not None
    assert vb.mint == "MintA"
    assert vb.ui_amount == 1000.0
    assert vb.pubkey == "vaultA"
    assert vb.slot == 100


def test_parse_program_subscribe_shape_carries_pubkey():
    params = {
        "subscription": 2,
        "result": {
            "context": {"slot": 55},
            "value": {
                "pubkey": "vaultFromProgramSub",
                "account": {
                    "data": {
                        "parsed": {
                            "info": {
                                "mint": "MintB",
                                "tokenAmount": {
                                    "amount": "500000000",
                                    "decimals": 6,
                                    "uiAmount": 500.0,
                                },
                            },
                            "type": "account",
                        },
                        "program": "spl-token",
                    },
                },
            },
        },
    }
    vb = parse_vault_balance(params)
    assert vb is not None
    assert vb.pubkey == "vaultFromProgramSub"
    assert vb.ui_amount == 500.0


def test_parse_computes_ui_from_amount_when_uiamount_absent():
    n = _acct_notification("MintA", 0.0)
    n["result"]["value"]["data"]["parsed"]["info"]["tokenAmount"] = {
        "amount": "12500000",
        "decimals": 6,
    }
    vb = parse_vault_balance(n)
    assert vb is not None
    assert vb.ui_amount == 12.5


def test_parse_base64_data_returns_none():
    # Non-jsonParsed (base64) data is a list/str, not a dict → None.
    n = _acct_notification("MintA", 1.0)
    n["result"]["value"]["data"] = ["base64blob==", "base64"]
    assert parse_vault_balance(n) is None


def test_parse_missing_token_amount_returns_none():
    n = _acct_notification("MintA", 1.0)
    del n["result"]["value"]["data"]["parsed"]["info"]["tokenAmount"]
    assert parse_vault_balance(n) is None


def test_parse_garbage_returns_none():
    assert parse_vault_balance({}) is None
    assert parse_vault_balance({"result": "nope"}) is None


# --------------------------------------------------------------------------- #
# PoolReserveTracker                                                           #
# --------------------------------------------------------------------------- #


def _tracker() -> PoolReserveTracker:
    return PoolReserveTracker(
        "PoolXYZ", base_vault="baseV", quote_vault="quoteV", quote_usd_per_unit=1.0
    )


def _vb(vault: str, mint: str, ui: float) -> VaultBalance:
    return VaultBalance(pubkey=vault, mint=mint, ui_amount=ui, slot=1)


def test_first_observation_emits_no_swap():
    t = _tracker()
    swap, _snap = t.observe(_vb("baseV", "BASE", 1000.0), ts=1.0)
    assert swap is None
    swap2, snap2 = t.observe(_vb("quoteV", "USDC", 1000.0), ts=1.0)
    assert swap2 is None
    assert snap2.spot_price_usd == 1.0  # 1000 quote / 1000 base


def test_base_decrease_is_a_buy():
    t = _tracker()
    t.observe(_vb("quoteV", "USDC", 1000.0), ts=1.0)
    t.observe(_vb("baseV", "BASE", 1000.0), ts=1.0)
    swap, _ = t.observe(_vb("baseV", "BASE", 990.0), ts=2.0)  # 10 base left the pool
    assert swap is not None
    assert swap.side == "buy"
    assert swap.notional_usd > 0
    assert swap.pool_addr == "PoolXYZ"


def test_base_increase_is_a_sell():
    t = _tracker()
    t.observe(_vb("quoteV", "USDC", 1000.0), ts=1.0)
    t.observe(_vb("baseV", "BASE", 1000.0), ts=1.0)
    swap, _ = t.observe(_vb("baseV", "BASE", 1010.0), ts=2.0)  # base returned to pool
    assert swap is not None
    assert swap.side == "sell"


def test_quote_only_update_refreshes_price_no_swap():
    t = _tracker()
    t.observe(_vb("baseV", "BASE", 1000.0), ts=1.0)
    swap, _snap = t.observe(_vb("quoteV", "USDC", 2000.0), ts=2.0)
    assert swap is None
    assert _snap.spot_price_usd == 2.0  # 2000 / 1000


def test_unknown_vault_ignored():
    t = _tracker()
    swap, _ = t.observe(_vb("strangerV", "X", 5.0), ts=1.0)
    assert swap is None
