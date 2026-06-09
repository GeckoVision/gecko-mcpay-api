"""L2b CPI-nested-enforcement smoke — LIVE Privy signing on Solana DEVNET ONLY.

This is the DECISIVE probe that closes the L2 custody gate. L2 proved Privy
denies a *top-level* foreign transfer (system transfer self -> FOREIGN). It
left ONE case open, the one that gates trade-route signing:

    Does Privy's policy engine deny a foreign transfer **nested as a CPI
    inside an otherwise-ALLOWED program call**?

We answer it with the ``custody-probe`` devnet program
(``vDSFZB3vgEndA4qmtWfKq8bvBMQAeHauT9bd3uKDdHy``). Its single instruction
``probe_cpi_transfer(amount)`` CPIs ``system_program::transfer(from -> to,
amount)`` where ``to`` is unconstrained. The test policy ALLOWLISTS this
program's ID (simulating an allowed DeFi program like Jupiter/Kamino) while
keeping the self-only transfer pins. Then:

  * FOREIGN case — ``to`` = a fresh pubkey the policy did NOT pin:
      - DENY  -> Privy walked the CPI, caught the nested foreign transfer -> SAFE,
        ``execute`` can be un-gated (in a separate reviewed PR).
      - ALLOW -> Privy only saw the allowed top-level programId, missed the CPI
        -> UNSAFE, keep ``execute`` permanently gated for program-call signing.
        (An ALLOW that then chain-fails on 0 balance is still an ALLOW: the
        POLICY permitting it is the signal, not whether it lands.)

  * SELF control — SAME program call but ``to`` = the wallet's OWN address:
      - ALLOW expected. Proves the program-allowlist itself works and it is
        specifically the FOREIGN destination that the policy must catch.

DEVNET ONLY. Devnet CAIP-2, devnet RPC, test lamports. Signing is armed ONLY
because this script sets ``GECKO_PRIVY_SIGNING_DEVNET=1`` in-process — the
production adapter never does. This script does NOT un-gate
``execute``/``withdraw`` in the adapter; it only produces the verdict.

SECURITY: never prints PRIVY_APP_ID / PRIVY_APP_SECRET. Wallet addresses, tx
signatures, wallet_ids, policy_ids and program IDs are public and ARE printed.

Run:
    set -a; source .env; set +a
    GECKO_PRIVY_SIGNING_DEVNET=1 uv run python scripts/privy/smoke_l2b_cpi_enforcement.py
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import struct
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

# Arm the devnet signing path for THIS process only, before importing the
# client. Production never sets this; the smoke owns the arming.
os.environ.setdefault("GECKO_PRIVY_SIGNING_DEVNET", "1")

from gecko_core.wallets.factory import make_wallet_provider
from gecko_core.wallets.privy import PrivyClientError
from gecko_core.wallets.privy_adapter import PrivyWalletAdapter
from gecko_core.wallets.privy_rules import scope_to_privy_rules
from gecko_core.wallets.provider import TRADE_ONLY_ACTIONS, Scope
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.keypair import Keypair
from solders.message import Message
from solders.pubkey import Pubkey
from solders.transaction import Transaction

DEVNET_RPC = "https://api.devnet.solana.com"
SYSTEM_PROGRAM_ID = "11111111111111111111111111111111"

# The LIVE custody-probe program on devnet. probe_cpi_transfer(amount: u64)
# CPIs system_program::transfer(from -> to, amount). Accounts:
#   [from: Signer+writable, to: SystemAccount+writable, system_program].
PROBE_PROGRAM_ID = "vDSFZB3vgEndA4qmtWfKq8bvBMQAeHauT9bd3uKDdHy"
# Anchor discriminator = first 8 bytes of sha256("global:probe_cpi_transfer").
# Verified equal to the IDL discriminator [26,56,65,97,199,21,53,45].
PROBE_DISCRIMINATOR = hashlib.sha256(b"global:probe_cpi_transfer").digest()[:8]
PROBE_AMOUNT_LAMPORTS = 5000

_RUN = time.strftime("%Y%m%dT%H%M%S")
USER_ID = f"gecko-l2b-smoke-{_RUN}"
PLACEHOLDER_ADDR = "placeholder-address-ignored-by-privy-create"


# ---------------------------------------------------------------------------
# Devnet RPC helpers (stdlib only — no extra deps, devnet-pinned).
# ---------------------------------------------------------------------------
def _rpc(method: str, params: list[Any]) -> dict[str, Any]:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        DEVNET_RPC, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data: dict[str, Any] = json.loads(resp.read().decode())
    return data


def _latest_blockhash() -> Hash:
    res = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    bh = res["result"]["value"]["blockhash"]
    return Hash.from_string(bh)


def _airdrop(address: str, lamports: int) -> bool:
    """Best-effort airdrop. Funding is NOT required: a policy ALLOW/DENY is
    decided BEFORE broadcast, so the verdict is observable on a 0-balance
    wallet. We try once so an ALLOW *may* also produce an on-chain signature."""
    try:
        res = _rpc("requestAirdrop", [address, lamports])
        if res.get("result"):
            sig = res["result"]
            print(f"        airdrop requested: {sig}")
            for _ in range(8):
                time.sleep(2)
                bal = _rpc("getBalance", [address]).get("result", {}).get("value", 0)
                if bal and bal >= lamports // 2:
                    print(f"        balance now {bal} lamports")
                    return True
            return True
        err = res.get("error", {})
        print(f"        airdrop error (non-fatal): {err.get('message', err)}")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        print(f"        airdrop transport error (non-fatal): {exc}")
    return False


# ---------------------------------------------------------------------------
# Transaction builder. UNSIGNED legacy tx, wallet as fee-payer; Privy signs (or
# refuses). Mirrors the L2 script's solders construction.
# ---------------------------------------------------------------------------
def _b64_unsigned(instructions: list[Instruction], payer: Pubkey, bh: Hash) -> str:
    msg = Message.new_with_blockhash(instructions, payer, bh)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode("ascii")


def _probe_cpi_ix(from_addr: Pubkey, to_addr: Pubkey) -> Instruction:
    """A single custody-probe ``probe_cpi_transfer`` instruction.

    data = discriminator(8) + amount (LE u64). accounts in IDL order:
    from (signer, writable), to (writable), system_program (readonly).
    The value movement (from -> to) happens one CPI level deep, inside the
    allowlisted program — exactly the case L2 could not reach.
    """
    data = PROBE_DISCRIMINATOR + struct.pack("<Q", PROBE_AMOUNT_LAMPORTS)
    accounts = [
        AccountMeta(pubkey=from_addr, is_signer=True, is_writable=True),
        AccountMeta(pubkey=to_addr, is_signer=False, is_writable=True),
        AccountMeta(
            pubkey=Pubkey.from_string(SYSTEM_PROGRAM_ID),
            is_signer=False,
            is_writable=False,
        ),
    ]
    return Instruction(
        program_id=Pubkey.from_string(PROBE_PROGRAM_ID),
        accounts=accounts,
        data=data,
    )


def _probe_program_allow_rule() -> dict[str, Any]:
    """ALLOW interacting with the custody-probe program (simulating an allowed
    DeFi program). Same rule shape that passed live in L2: version-less rule
    dict, ``eq`` operator only, no ``neq``."""
    return {
        "name": "allow-custody-probe-program",
        "method": "signAndSendTransaction",
        "conditions": [
            {
                "field_source": "solana_program_instruction",
                "field": "programId",
                "operator": "eq",
                "value": PROBE_PROGRAM_ID,
            }
        ],
        "action": "ALLOW",
    }


# ---------------------------------------------------------------------------
# Result recording
# ---------------------------------------------------------------------------
@dataclass
class CaseResult:
    case: str
    expected: str  # "ALLOW" | "DENY"
    actual: str  # "ALLOW" | "DENY" | "ERROR"
    detail: str

    @property
    def passed(self) -> bool:
        return self.actual == self.expected


def _attempt(adapter: PrivyWalletAdapter, wallet_id: str, b64_tx: str) -> tuple[str, str]:
    """Return ("ALLOW", sig) or ("DENY", body) or ("ERROR", msg).

    ALLOW = Privy signed+broadcast (policy permitted). A PrivyClientError whose
    verbatim body carries policy/denied/violation wording is DENY. Anything else
    (e.g. insufficient funds = policy-ALLOWED-but-chain-rejected) is ERROR here
    and reclassified to ALLOW by the caller.
    """
    try:
        resp = adapter._run(
            adapter._client.sign_and_send_solana_devnet(wallet_id=wallet_id, b64_tx=b64_tx)
        )
        sig = resp.get("hash") or resp.get("transaction_id") or json.dumps(resp)[:80]
        return ("ALLOW", str(sig))
    except PrivyClientError as exc:
        msg = str(exc)
        low = msg.lower()
        if any(
            k in low for k in ("policy", "denied", "deny", "not allowed", "violat", "unauthorized")
        ):
            return ("DENY", msg[:240])
        return ("ERROR", msg[:240])


def main() -> int:
    print("=== L2b CPI-nested enforcement smoke: Privy DEVNET signing (LIVE) ===\n")
    print(f"    DEVNET RPC      : {DEVNET_RPC}")
    print(f"    probe program   : {PROBE_PROGRAM_ID}")
    print(f"    discriminator   : {list(PROBE_DISCRIMINATOR)}")
    print(
        f"    signing armed   : GECKO_PRIVY_SIGNING_DEVNET="
        f"{os.environ.get('GECKO_PRIVY_SIGNING_DEVNET')}"
    )
    print()

    provider = make_wallet_provider()
    if not isinstance(provider, PrivyWalletAdapter):
        print(
            f"  FAIL  factory returned {type(provider).__name__}, not PrivyWalletAdapter. "
            "Did you `set -a; source .env; set +a`?"
        )
        return 1
    adapter = provider

    # -- link -------------------------------------------------------------
    print("[1] link() -> real Privy devnet wallet")
    link = adapter.link(USER_ID, PLACEHOLDER_ADDR)
    record = adapter._store.get(USER_ID)
    assert record is not None
    wallet_id = record.wallet_id
    from_addr = Pubkey.from_string(link.address)
    print(f"        wallet_id = {wallet_id}")
    print(f"        address   = {link.address}")

    # -- custom policy: self-pins + custody-probe program ALLOW ------------
    print("\n[2] create custom policy: self-only transfer pins + ALLOW custody-probe program")
    scope = Scope(
        allowed_actions=TRADE_ONLY_ACTIONS,
        withdraw_allowlist=frozenset({link.address}),
    )
    # scope_to_privy_rules enforces withdraw_allowlist == {user_address} and
    # emits the self-pinned transfer ALLOWs + the trade-program ALLOWs. We add
    # ONE more ALLOW rule: the custody-probe program (the "allowed DeFi program").
    rules = [*scope_to_privy_rules(scope, link.address), _probe_program_allow_rule()]
    policy = adapter._run(adapter._client.create_policy(name=f"gecko-l2b-{USER_ID}", rules=rules))
    adapter._run(
        adapter._client.attach_policy_to_wallet(wallet_id=wallet_id, policy_ids=[policy.policy_id])
    )
    print(f"        policy_id = {policy.policy_id}")
    print(f"        rules     = {len(rules)} (self-pins + trade-program allows + custody-probe)")

    # -- (best-effort) fund -----------------------------------------------
    print("\n[3] devnet airdrop (best-effort; funding NOT required for the verdict)")
    if _airdrop(link.address, 1_000_000_000):
        print("  OK    funded (an ALLOW may also land on-chain)")
    else:
        print(
            "  SOFT  airdrop unavailable. Continuing: policy ALLOW/DENY is decided "
            "BEFORE broadcast, so the verdict holds on a 0-balance wallet."
        )

    results: list[CaseResult] = []

    def run_case(name: str, expected: str, to_addr: Pubkey, note: str) -> None:
        print(f"\n[case {name}] {note}  (expect {expected})")
        try:
            bh = _latest_blockhash()
            b64 = _b64_unsigned([_probe_cpi_ix(from_addr, to_addr)], from_addr, bh)
        except Exception as exc:
            print(f"        build/blockhash error: {exc}")
            results.append(CaseResult(name, expected, "ERROR", f"build: {exc}"[:240]))
            return
        actual, detail = _attempt(adapter, wallet_id, b64)
        # An ALLOW-then-chain-failure still means the POLICY allowed signing.
        if actual == "ERROR" and any(
            k in detail.lower()
            for k in ("insufficient", "fund", "blockhash", "0x1", "debit", "lamport", "custom")
        ):
            actual = "ALLOW"
            detail = f"policy-ALLOW; chain-side: {detail}"
        print(f"        actual = {actual}  | {detail}")
        results.append(CaseResult(name, expected, actual, detail))

    # FOREIGN: probe CPI-transfers to a fresh, un-pinned pubkey.
    # DENY => Privy walked the CPI (SAFE). ALLOW => Privy missed it (UNSAFE).
    foreign = Keypair().pubkey()
    print(f"\n    foreign destination (fresh, un-pinned) = {foreign}")
    run_case(
        "cpi-foreign",
        "DENY",
        foreign,
        "probe_cpi_transfer -> FOREIGN (CPI-nested foreign transfer; DECISIVE)",
    )

    # SELF control: SAME program call but ``to`` = the wallet's own address.
    # Proves the program-allowlist works and it's specifically the foreign dest.
    run_case(
        "cpi-self",
        "ALLOW",
        from_addr,
        "probe_cpi_transfer -> SELF (control: program-allowlist proof)",
    )

    # -- table ------------------------------------------------------------
    print("\n" + "=" * 84)
    print(f"{'CASE':<14}{'WHAT':<46}{'EXPECT':<8}{'ACTUAL':<8}{'PASS'}")
    print("-" * 84)
    labels = {
        "cpi-foreign": "CPI-nested transfer -> FOREIGN (decisive)",
        "cpi-self": "CPI-nested transfer -> SELF (control)",
    }
    for r in sorted(results, key=lambda x: x.case):
        mark = "PASS" if r.passed else "FAIL"
        print(f"{r.case:<14}{labels.get(r.case, ''):<46}{r.expected:<8}{r.actual:<8}{mark}")
    print("=" * 84)

    foreign_r = next((r for r in results if r.case == "cpi-foreign"), None)
    self_r = next((r for r in results if r.case == "cpi-self"), None)

    print("\n=== VERDICT ===")
    print(f"  wallet_id : {wallet_id}")
    print(f"  address   : {link.address}")
    print(f"  policy_id : {policy.policy_id}")
    print(f"  program   : {PROBE_PROGRAM_ID}")

    if foreign_r is None or self_r is None:
        print("  INCONCLUSIVE — a case failed to produce a result. KEEP execute GATED.")
        return 2

    control_ok = self_r.actual == "ALLOW"
    if not control_ok:
        print(
            "  CONTROL FAILED — the SELF probe call was not ALLOWed, so the "
            "program-allowlist itself did not take effect. The foreign result is "
            "NOT interpretable. KEEP execute GATED; re-run after fixing the policy."
        )
        return 2

    if foreign_r.actual == "DENY":
        print("  FOREIGN-CPI = DENY  ->  Privy INSPECTED the CPI and caught the nested")
        print("  foreign transfer. The non-custodial guarantee is FULLY VERIFIED on devnet.")
        print("  DECISION: `execute` CAN be un-gated (in a SEPARATE reviewed PR — NOT here).")
        return 0

    if foreign_r.actual == "ALLOW":
        print("  FOREIGN-CPI = ALLOW  ->  Privy only saw the allowed top-level programId")
        print("  and MISSED the CPI-nested foreign transfer. This is the residual exfil risk.")
        print("  DECISION: KEEP `execute` PERMANENTLY GATED for program-call signing.")
        print("  Mitigation: never auto-sign Jupiter/Kamino/Drift routes; only sign txns we")
        print("  fully decode + verify ourselves (per-instruction, incl. inner CPIs), or")
        print("  use per-instruction allowlisting if/when Privy exposes inner-ix conditions.")
        return 3

    print(f"  FOREIGN-CPI = {foreign_r.actual} (unexpected). KEEP execute GATED.")
    return 2


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"\nL2b FAIL: {type(exc).__name__}: {exc}")
        rc = 1
    sys.exit(rc)
