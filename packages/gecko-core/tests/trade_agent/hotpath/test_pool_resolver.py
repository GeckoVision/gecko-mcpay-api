"""Tests for the pool resolver (init tx → ResolvedPool)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.pool_resolver import (
    WSOL_MINT,
    extract_logs,
    extract_signature,
    is_pool_init_log,
    resolve_from_parsed_tx,
)

LAUNCH_MINT = "Lnch1111111111111111111111111111111111111111"
BASE_VAULT = "BaseVau1t11111111111111111111111111111111111"
QUOTE_VAULT = "QuoteVau1t1111111111111111111111111111111111"
POOL_AUTH = "Po01Auth11111111111111111111111111111111111"


def _tx(*, keys, balances, block_time=1000):
    return {
        "blockTime": block_time,
        "transaction": {"message": {"accountKeys": [{"pubkey": k} for k in keys]}},
        "meta": {"postTokenBalances": balances},
    }


def _bal(idx, mint, owner, ui):
    return {"accountIndex": idx, "mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": ui}}


def test_resolves_launch_quote_pair():
    keys = [POOL_AUTH, BASE_VAULT, QUOTE_VAULT]
    tx = _tx(
        keys=keys,
        balances=[
            _bal(1, LAUNCH_MINT, POOL_AUTH, 1_000_000.0),
            _bal(2, WSOL_MINT, POOL_AUTH, 80.0),
        ],
    )
    r = resolve_from_parsed_tx(tx, signature="sig1")
    assert r is not None
    assert r.mint == LAUNCH_MINT
    assert r.base_vault == BASE_VAULT
    assert r.quote_vault == QUOTE_VAULT
    assert r.quote_mint == WSOL_MINT
    assert r.pool_addr == f"pool:{BASE_VAULT}:{QUOTE_VAULT}"
    assert r.pool_created_ts == 1000


def test_no_quote_side_fails_open():
    keys = [POOL_AUTH, BASE_VAULT, QUOTE_VAULT]
    tx = _tx(
        keys=keys,
        balances=[
            _bal(1, LAUNCH_MINT, POOL_AUTH, 1.0),
            _bal(2, "OtherMint1111111111111111111111111111111111", POOL_AUTH, 1.0),
        ],
    )
    assert resolve_from_parsed_tx(tx) is None


def test_too_few_balances_fails_open():
    tx = _tx(keys=[POOL_AUTH, BASE_VAULT], balances=[_bal(1, WSOL_MINT, POOL_AUTH, 1.0)])
    assert resolve_from_parsed_tx(tx) is None


def test_owner_pairing_picks_real_pool_vaults():
    # an unrelated WSOL token account (different owner) must not be chosen as the quote
    keys = [POOL_AUTH, BASE_VAULT, QUOTE_VAULT, "Unrelated111111111111111111111111111111111"]
    tx = _tx(
        keys=keys,
        balances=[
            _bal(1, LAUNCH_MINT, POOL_AUTH, 1_000_000.0),
            _bal(2, WSOL_MINT, POOL_AUTH, 80.0),
            _bal(3, WSOL_MINT, "SomeoneElse1111111111111111111111111111111", 5.0),
        ],
    )
    r = resolve_from_parsed_tx(tx)
    assert r is not None and r.quote_vault == QUOTE_VAULT  # owner-matched, not the bigger orphan


def test_init_log_detection():
    assert is_pool_init_log(["Program log: Instruction: initialize2"]) is True
    assert is_pool_init_log(["Program log: ray_log: ...", "create_pool args"]) is True
    assert is_pool_init_log(["Program log: Instruction: Swap"]) is False
    assert is_pool_init_log([]) is False
    assert is_pool_init_log(None) is False


def test_log_param_extractors():
    params = {"result": {"value": {"signature": "abc", "logs": ["x", "y"], "err": None}}}
    assert extract_signature(params) == "abc"
    assert extract_logs(params) == ["x", "y"]
    assert extract_signature({}) is None
    assert extract_logs({"result": {"value": {}}}) is None
