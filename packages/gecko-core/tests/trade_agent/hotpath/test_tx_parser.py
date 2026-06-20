"""Tests for the parsed-tx → ParsedSwap decoder (the snipe-gate keystone)."""

from __future__ import annotations

from gecko_core.trade_agent.hotpath.jito import JITO_TIP_ACCOUNTS
from gecko_core.trade_agent.hotpath.snipe_features import LAMPORTS_PER_SOL
from gecko_core.trade_agent.hotpath.tx_parser import parse_swap_tx

SIGNER = "Buyer1111111111111111111111111111111111111111"
RAYDIUM = "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8"
SYSTEM = "11111111111111111111111111111111"
TIP = next(iter(JITO_TIP_ACCOUNTS))
ALT = "ALT_rig_11111111111111111111111111111111111111"


def _notif(*, keys, instructions, pre, post, err=None, slot=500, alts=None, block_time=1000):
    msg = {
        "accountKeys": keys,
        "instructions": instructions,
    }
    if alts:
        msg["addressTableLookups"] = [{"accountKey": a} for a in alts]
    return {
        "result": {
            "slot": slot,
            "value": {
                "blockTime": block_time,
                "transaction": {"message": msg},
                "meta": {
                    "err": err,
                    "preBalances": pre,
                    "postBalances": post,
                    "innerInstructions": [],
                },
            },
        }
    }


def _signer_key():
    return {"pubkey": SIGNER, "signer": True, "writable": True}


def test_buy_with_jito_tip_and_alt():
    tip_lamports = int(2e-4 * LAMPORTS_PER_SOL)
    notif = _notif(
        keys=[_signer_key(), {"pubkey": RAYDIUM, "signer": False, "writable": False}],
        instructions=[
            {"programId": RAYDIUM},
            {
                "programId": SYSTEM,
                "parsed": {
                    "type": "transfer",
                    "info": {"destination": TIP, "lamports": tip_lamports},
                },
            },
        ],
        pre=[int(5 * LAMPORTS_PER_SOL), 0],
        post=[int(4 * LAMPORTS_PER_SOL), 0],  # signer spent ~1 SOL → a buy
        alts=[ALT],
        slot=777,
    )
    swap = parse_swap_tx(notif)
    assert swap is not None
    assert swap.signer == SIGNER
    assert swap.slot == 777
    assert swap.is_buy is True
    assert swap.notional_sol > 0.9
    assert swap.tip_lamports == tip_lamports
    assert RAYDIUM in swap.program_ids
    assert swap.alt_addresses == [ALT]
    assert swap.timestamp == 1000.0


def test_failed_tx_is_skipped():
    notif = _notif(
        keys=[_signer_key()],
        instructions=[{"programId": RAYDIUM}],
        pre=[int(5 * LAMPORTS_PER_SOL)],
        post=[int(4 * LAMPORTS_PER_SOL)],
        err={"InstructionError": [0, "Custom"]},
    )
    assert parse_swap_tx(notif) is None


def test_no_tip_is_not_a_bundle():
    notif = _notif(
        keys=[_signer_key()],
        instructions=[{"programId": RAYDIUM}],
        pre=[int(5 * LAMPORTS_PER_SOL)],
        post=[int(4 * LAMPORTS_PER_SOL)],
    )
    swap = parse_swap_tx(notif)
    assert swap is not None and swap.tip_lamports == 0


def test_sol_inflow_is_not_a_buy():
    # signer RECEIVES sol (a sell / withdrawal) → not a launch buy
    notif = _notif(
        keys=[_signer_key()],
        instructions=[{"programId": RAYDIUM}],
        pre=[int(4 * LAMPORTS_PER_SOL)],
        post=[int(5 * LAMPORTS_PER_SOL)],
    )
    swap = parse_swap_tx(notif)
    assert swap is not None and swap.is_buy is False


def test_dust_movement_not_a_buy():
    notif = _notif(
        keys=[_signer_key()],
        instructions=[{"programId": RAYDIUM}],
        pre=[1000000],
        post=[999000],  # ~1e-6 SOL — below the buy floor
    )
    swap = parse_swap_tx(notif)
    assert swap is not None and swap.is_buy is False


def test_garbage_fails_open():
    assert parse_swap_tx({}) is None
    assert parse_swap_tx({"result": {"value": {}}}) is None
    assert parse_swap_tx({"result": {"value": {"transaction": {"message": {}}}}}) is None


def test_bare_parsed_tx_shape():
    # the fixture path: a bare parsed tx (no ws envelope)
    bare = {
        "slot": 42,
        "blockTime": 1000,
        "transaction": {
            "message": {"accountKeys": [_signer_key()], "instructions": [{"programId": RAYDIUM}]}
        },
        "meta": {
            "err": None,
            "preBalances": [int(3 * LAMPORTS_PER_SOL)],
            "postBalances": [int(2 * LAMPORTS_PER_SOL)],
            "innerInstructions": [],
        },
    }
    swap = parse_swap_tx(bare)
    assert swap is not None and swap.slot == 42 and swap.is_buy is True
