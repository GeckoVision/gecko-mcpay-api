"""Diagnose CDP /settle 'transfer amount exceeds balance' failure.

Purpose
-------
Reproduces, at the protocol level, the exact transferWithAuthorization
that ``CDPX402Client`` would hand to the CDP facilitator, then:

1. Decodes the signed authorization and confirms the on-chain ``value``
   in smallest USDC units (should be 100000 = $0.10).
2. Reads the buyer's USDC balance from Base mainnet via free RPC.
3. Recovers the signer address from the EIP-712 signature and checks
   it equals the configured TWITSH address (no normalization drift).
4. Simulates ``transferWithAuthorization`` via ``eth_call`` against
   Base public RPC. ``eth_call`` is free and returns the underlying
   revert reason verbatim, which is what we need — the facilitator's
   500 message is generic.
5. Probes the USDC contract for ``paused()`` and ``isBlacklisted(buyer)``
   if those selectors exist. Prints a pass/fail diagnostic table.

Costs nothing on chain. No /settle, no /verify, no signed-tx broadcast.

Usage
-----
    uv run python scripts/diagnose_cdp_settle.py

Required env (already in `.env`):
    TWITSH_WALLET_ADDRESS
    TWITSH_WALLET_PRIVATE_KEY
    GECKO_WALLET_ADDRESS_BASE
"""

from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

# Load `.env` without depending on python-dotenv at module-import time.
ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
if ENV_PATH.exists():
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from eth_account import Account  # noqa: E402
from gecko_core.payments.cdp_x402_client import (  # noqa: E402
    BASE_MAINNET_NETWORK_ID,
    BASE_MAINNET_USDC_CONTRACT,
    _build_payment_payload,
    _build_payment_requirements,
)
from web3 import Web3  # noqa: E402

BASE_PUBLIC_RPC = os.environ.get("BASE_RPC_URL") or "https://base-rpc.publicnode.com"

ERC20_BALANCEOF_ABI: list[dict] = [
    {
        "constant": True,
        "inputs": [{"name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "name",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "version",
        "outputs": [{"name": "", "type": "string"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "decimals",
        "outputs": [{"name": "", "type": "uint8"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [],
        "name": "DOMAIN_SEPARATOR",
        "outputs": [{"name": "", "type": "bytes32"}],
        "type": "function",
    },
    {
        "constant": True,
        "inputs": [
            {"name": "authorizer", "type": "address"},
            {"name": "nonce", "type": "bytes32"},
        ],
        "name": "authorizationState",
        "outputs": [{"name": "", "type": "bool"}],
        "type": "function",
    },
    {
        "constant": False,
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"},
        ],
        "name": "transferWithAuthorization",
        "outputs": [],
        "type": "function",
    },
]


def hr(title: str) -> None:
    print()
    print("=" * 72)
    print(title)
    print("=" * 72)


def main() -> int:
    twitsh_addr = os.environ["TWITSH_WALLET_ADDRESS"]
    twitsh_pk = os.environ["TWITSH_WALLET_PRIVATE_KEY"]
    treasury = os.environ["GECKO_WALLET_ADDRESS_BASE"]

    if not twitsh_pk.startswith("0x"):
        twitsh_pk = "0x" + twitsh_pk

    w3 = Web3(Web3.HTTPProvider(BASE_PUBLIC_RPC))
    assert w3.is_connected(), "cannot connect to Base public RPC"

    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(BASE_MAINNET_USDC_CONTRACT),
        abi=ERC20_BALANCEOF_ABI,
    )

    hr("STEP 1 — Contract identity")
    name = usdc.functions.name().call()
    decimals = usdc.functions.decimals().call()
    try:
        version = usdc.functions.version().call()
    except Exception as e:  # pragma: no cover
        version = f"<no version()> {type(e).__name__}"
    print(f"  asset           = {BASE_MAINNET_USDC_CONTRACT}")
    print(f"  name()          = {name!r}")
    print(f"  version()       = {version!r}")
    print(f"  decimals()      = {decimals}")
    print("  cdp_x402_client extra.name    = 'USD Coin'")
    print("  cdp_x402_client extra.version = '2'")
    if name != "USD Coin":
        print("  !! MISMATCH on name: signing domain will fail EIP-712 verify")
    if str(version) != "2":
        print("  !! MISMATCH on version: signing domain will fail EIP-712 verify")

    hr("STEP 2 — Buyer balance on Base")
    raw_bal = usdc.functions.balanceOf(Web3.to_checksum_address(twitsh_addr)).call()
    print(f"  TWITSH addr     = {twitsh_addr}")
    print(f"  balanceOf raw   = {raw_bal} (smallest units)")
    print(f"  balanceOf usdc  = {Decimal(raw_bal) / Decimal(10**decimals)}")

    hr("STEP 3 — Build & sign the authorization (locally, free)")
    requirements = _build_payment_requirements(
        amount_usd=Decimal("0.10"),
        pay_to=treasury,
        network=BASE_MAINNET_NETWORK_ID,
        asset=BASE_MAINNET_USDC_CONTRACT,
        resource_url="https://geckovision.tech/research",
        max_timeout_seconds=60,
    )
    print(f"  requirements.amount       = {requirements.amount}")
    print(f"  requirements.pay_to       = {requirements.pay_to}")
    print(f"  requirements.asset        = {requirements.asset}")
    print(f"  requirements.network      = {requirements.network}")
    print(f"  requirements.extra.name   = {requirements.extra.get('name')!r}")
    print(f"  requirements.extra.ver    = {requirements.extra.get('version')!r}")
    print(f"  requirements.extra.vc     = {requirements.extra.get('verifyingContract')!r}")

    payload = _build_payment_payload(
        intent_id="diag-001",
        requirements=requirements,
        payer_private_key=twitsh_pk,
        resource_url="https://geckovision.tech/research",
    )
    inner = payload.payload
    auth = inner["authorization"]
    sig = inner["signature"]
    print(f"  auth.from       = {auth['from']}")
    print(f"  auth.to         = {auth['to']}")
    print(f"  auth.value      = {auth['value']}  (== {int(auth['value'])} smallest units)")
    print(f"  auth.validAfter = {auth['validAfter']}")
    print(f"  auth.validBefore= {auth['validBefore']}")
    print(f"  auth.nonce      = {auth['nonce']}")
    print(f"  signature       = {sig[:18]}...{sig[-8:]}  ({len(sig)} chars)")

    if int(auth["value"]) != 100_000:
        print("  !! VALUE DRIFT: expected 100000 (= $0.10), got", auth["value"])
    if Web3.to_checksum_address(auth["from"]) != Web3.to_checksum_address(twitsh_addr):
        print("  !! FROM MISMATCH: signed-from != TWITSH env")
    if int(auth["value"]) > raw_bal:
        print(f"  !! INSUFFICIENT BALANCE: signed value {auth['value']} > balance {raw_bal}")
    else:
        print(f"  OK balance ({raw_bal}) >= signed value ({auth['value']})")

    hr("STEP 4 — Recover signer from signature (verify no key drift)")
    from eth_account.messages import encode_typed_data

    encoded = encode_typed_data(
        domain_data={
            "name": "USD Coin",
            "version": "2",
            "chainId": 8453,
            "verifyingContract": Web3.to_checksum_address(BASE_MAINNET_USDC_CONTRACT),
        },
        message_types={
            "TransferWithAuthorization": [
                {"name": "from", "type": "address"},
                {"name": "to", "type": "address"},
                {"name": "value", "type": "uint256"},
                {"name": "validAfter", "type": "uint256"},
                {"name": "validBefore", "type": "uint256"},
                {"name": "nonce", "type": "bytes32"},
            ]
        },
        message_data={
            "from": auth["from"],
            "to": auth["to"],
            "value": int(auth["value"]),
            "validAfter": int(auth["validAfter"]),
            "validBefore": int(auth["validBefore"]),
            "nonce": bytes.fromhex(auth["nonce"].removeprefix("0x")),
        },
    )
    recovered = Account.recover_message(encoded, signature=sig)
    print(f"  recovered       = {recovered}")
    print(f"  TWITSH          = {Web3.to_checksum_address(twitsh_addr)}")
    if Web3.to_checksum_address(recovered) != Web3.to_checksum_address(twitsh_addr):
        print("  !! SIGNER MISMATCH: signature recovers to a different address")
    else:
        print("  OK signature recovers to TWITSH (signing pipeline is correct)")

    hr("STEP 5 — Authorization replay state")
    nonce_b32 = bytes.fromhex(auth["nonce"].removeprefix("0x"))
    used = usdc.functions.authorizationState(
        Web3.to_checksum_address(auth["from"]), nonce_b32
    ).call()
    print(f"  authorizationState(from, nonce) = {used}")
    if used:
        print("  !! NONCE ALREADY USED — would revert with 'authorization is used or canceled'")
    else:
        print("  OK nonce is fresh")

    hr("STEP 6 — Simulate transferWithAuthorization via eth_call (FREE, no spend)")
    # Split signature into v, r, s
    sig_bytes = bytes.fromhex(sig.removeprefix("0x"))
    if len(sig_bytes) != 65:
        print(f"  !! signature wrong length: {len(sig_bytes)} bytes")
        return 1
    r = sig_bytes[0:32]
    s = sig_bytes[32:64]
    v = sig_bytes[64]
    if v < 27:
        v += 27

    # Choose `from` for the eth_call. transferWithAuthorization is callable
    # by anyone with a valid signature, so the simulator tx sender is
    # arbitrary. Use buyer; what matters is the signed authorization.
    try:
        result = usdc.functions.transferWithAuthorization(
            Web3.to_checksum_address(auth["from"]),
            Web3.to_checksum_address(auth["to"]),
            int(auth["value"]),
            int(auth["validAfter"]),
            int(auth["validBefore"]),
            nonce_b32,
            v,
            r,
            s,
        ).call({"from": Web3.to_checksum_address(twitsh_addr)})
        print(f"  eth_call SUCCESS — return={result!r}")
        print("  ===> No revert. The bug is NOT on Base; it's in CDP's settle layer.")
    except Exception as e:
        msg = str(e)
        print(f"  eth_call REVERT — error class: {type(e).__name__}")
        print(f"  message: {msg}")
        # web3.py surfaces the revert reason in `data` or in str(e).
        # Common EIP-3009 reverts include:
        #   "FiatTokenV2: invalid signature"
        #   "FiatTokenV2: authorization is not yet valid"
        #   "FiatTokenV2: authorization is expired"
        #   "FiatTokenV2: authorization is used or canceled"
        #   "ERC20: transfer amount exceeds balance"
        #   "Pausable: paused"
        #   "Blacklistable: account is blacklisted"

    return 0


if __name__ == "__main__":
    sys.exit(main())
