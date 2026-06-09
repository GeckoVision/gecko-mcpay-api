"""L2 policy-enforcement smoke — LIVE Privy signing on Solana DEVNET ONLY.

This is the probe that answers the OPEN QUESTION gating production signing:
does Privy's policy engine ACTUALLY reject a non-self transfer at signing time,
INCLUDING a foreign-destination transfer bundled alongside an otherwise-allowed
instruction in a single transaction?

DEVNET ONLY. Every transaction is built against Solana devnet and submitted
through Privy with the devnet CAIP-2. No mainnet RPC, no real money. The wallet
is funded via devnet airdrop. Signing is armed ONLY because this script sets
``GECKO_PRIVY_SIGNING_DEVNET=1`` in-process — the production adapter never does.

SECURITY: never prints PRIVY_APP_ID / PRIVY_APP_SECRET. Wallet addresses, tx
signatures, wallet_ids and policy_ids are public and ARE printed.

What it does:
  1. link a fresh Privy devnet wallet (real create_solana_wallet).
  2. grant_scope (trade-only + withdraw-allowlist = the wallet's own address).
  3. fund via devnet airdrop (requestAirdrop, retry/backoff; soft-blocker if it
     ultimately fails — we still attempt signing to observe ALLOW/DENY, since a
     policy DENY happens before broadcast and does not require a funded wallet).
  4. attempt sign+send for cases (a)-(e), recording Privy ALLOW (tx sig) vs DENY.
  5. revoke (deny-all) and re-attempt (a) to prove revoke blocks all signing.
  6. print a case -> expected -> actual -> pass/fail table + an overall verdict.

Run:
    set -a; source .env; set +a
    GECKO_PRIVY_SIGNING_DEVNET=1 uv run python scripts/privy/smoke_l2_policy_enforcement.py
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

# Arm the devnet signing path for THIS process only, before importing the
# client. Production never sets this; the smoke owns the arming.
os.environ.setdefault("GECKO_PRIVY_SIGNING_DEVNET", "1")

from gecko_core.wallets.factory import make_wallet_provider
from gecko_core.wallets.privy import PrivyClientError
from gecko_core.wallets.privy_adapter import PrivyWalletAdapter
from gecko_core.wallets.provider import TRADE_ONLY_ACTIONS, Scope
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.message import Message
from solders.pubkey import Pubkey
from solders.system_program import TransferParams, transfer
from solders.transaction import Transaction

DEVNET_RPC = "https://api.devnet.solana.com"
# Memo program (NOT in the trade-action allowlist) — case (c) should DENY.
MEMO_PROGRAM_ID = "MemoSq4gq4mTM2BWaHzg4F4w6VfXkLDeAfWqXxQy7Ed"
# A throwaway, well-known devnet pubkey to act as the FOREIGN destination.
# (Solana incinerator address — exists, never the user's wallet.)
FOREIGN_DEST = "1nc1nerator11111111111111111111111111111111"

_RUN = time.strftime("%Y%m%dT%H%M%S")
USER_ID = f"gecko-l2-smoke-{_RUN}"
PLACEHOLDER_ADDR = "placeholder-address-ignored-by-privy-create"


# ---------------------------------------------------------------------------
# Devnet RPC helpers (stdlib only — no extra deps, devnet-pinned).
# ---------------------------------------------------------------------------
def _rpc(method: str, params: list) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        DEVNET_RPC, data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def _latest_blockhash() -> Hash:
    res = _rpc("getLatestBlockhash", [{"commitment": "finalized"}])
    bh = res["result"]["value"]["blockhash"]
    return Hash.from_string(bh)


def _airdrop(address: str, lamports: int) -> bool:
    """requestAirdrop with backoff. Returns True on a confirmed-ish airdrop."""
    for attempt in range(5):
        try:
            res = _rpc("requestAirdrop", [address, lamports])
            if res.get("result"):
                sig = res["result"]
                print(f"        airdrop requested: {sig}")
                # poll for confirmation
                for _ in range(15):
                    time.sleep(2)
                    bal = _rpc("getBalance", [address])
                    lam = bal.get("result", {}).get("value", 0)
                    if lam and lam >= lamports // 2:
                        print(f"        balance now {lam} lamports")
                        return True
                return True  # requested ok even if confirmation poll timed out
            err = res.get("error", {})
            print(f"        airdrop attempt {attempt + 1} error: {err.get('message', err)}")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            print(f"        airdrop attempt {attempt + 1} transport error: {exc}")
        # backoff + shrink request
        time.sleep(2**attempt)
        lamports = max(lamports // 2, 100_000_000)
    return False


def _balance_lamports(address: str) -> int:
    try:
        return int(_rpc("getBalance", [address]).get("result", {}).get("value", 0))
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Transaction builders. We build UNSIGNED legacy transactions with the wallet
# as fee-payer; Privy signs (or refuses) on its side. solders lets us build the
# message + an unsigned Transaction, which we serialize to base64.
# ---------------------------------------------------------------------------
def _b64_unsigned(instructions: list[Instruction], payer: Pubkey, bh: Hash) -> str:
    msg = Message.new_with_blockhash(instructions, payer, bh)
    tx = Transaction.new_unsigned(msg)
    return base64.b64encode(bytes(tx)).decode("ascii")


def _self_transfer_ix(payer: Pubkey) -> Instruction:
    return transfer(TransferParams(from_pubkey=payer, to_pubkey=payer, lamports=1000))


def _foreign_transfer_ix(payer: Pubkey) -> Instruction:
    dest = Pubkey.from_string(FOREIGN_DEST)
    return transfer(TransferParams(from_pubkey=payer, to_pubkey=dest, lamports=1000))


def _memo_ix(payer: Pubkey) -> Instruction:
    return Instruction(
        program_id=Pubkey.from_string(MEMO_PROGRAM_ID),
        accounts=[AccountMeta(pubkey=payer, is_signer=True, is_writable=False)],
        data=b"gecko-l2-memo",
    )


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

    ALLOW means Privy signed+broadcast (policy permitted). A PrivyClientError
    is the DENY/path: we surface its body verbatim. We treat a policy-rejection
    body as DENY; a transport/4xx unrelated to policy is ERROR. We classify by
    looking at the verbatim Privy message.
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
        # Policy denials surface with policy/denied/violat wording. Anything
        # else (e.g. insufficient funds = ALLOW-by-policy-but-chain-rejected)
        # is classified separately by the caller.
        if any(
            k in low for k in ("policy", "denied", "deny", "not allowed", "violat", "unauthorized")
        ):
            return ("DENY", msg[:200])
        return ("ERROR", msg[:200])


def main() -> int:
    print("=== L2 policy-enforcement smoke: Privy DEVNET signing (LIVE) ===\n")
    print(f"    DEVNET RPC      : {DEVNET_RPC}")
    print(
        f"    signing armed   : GECKO_PRIVY_SIGNING_DEVNET={os.environ.get('GECKO_PRIVY_SIGNING_DEVNET')}"
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
    wallet_id = adapter._store.get(USER_ID).wallet_id
    payer = Pubkey.from_string(link.address)
    print(f"        wallet_id = {wallet_id}")
    print(f"        address   = {link.address}")

    # -- grant ------------------------------------------------------------
    print("\n[2] grant_scope() -> trade-only + withdraw-allowlist = self")
    scope = Scope(
        allowed_actions=TRADE_ONLY_ACTIONS,
        withdraw_allowlist=frozenset({link.address}),
    )
    adapter.grant_scope(USER_ID, scope)
    policy_id = adapter._store.get(USER_ID).policy_id
    print(f"        policy_id = {policy_id}")

    # -- fund -------------------------------------------------------------
    print("\n[3] devnet airdrop (~1 SOL, retry/backoff)")
    funded = _airdrop(link.address, 1_000_000_000)
    bal = _balance_lamports(link.address)
    if funded and bal > 0:
        print(f"  OK    funded: {bal} lamports")
    else:
        print(
            "  SOFT-BLOCKER  airdrop failed/rate-limited. Continuing: a policy "
            "DENY is evaluated BEFORE broadcast, so cases (b)/(c)/(e) still prove "
            "rejection. An ALLOW case (a) may surface chain 'insufficient funds' "
            "which we treat as policy-ALLOW (the policy let it through)."
        )

    results: list[CaseResult] = []

    def run_case(name: str, expected: str, instructions: list[Instruction], note: str) -> None:
        print(f"\n[case {name}] {note}  (expect {expected})")
        try:
            bh = _latest_blockhash()
            b64 = _b64_unsigned(instructions, payer, bh)
        except Exception as exc:
            print(f"        build/blockhash error: {exc}")
            results.append(CaseResult(name, expected, "ERROR", f"build: {exc}"[:200]))
            return
        actual, detail = _attempt(adapter, wallet_id, b64)
        # An ALLOW-then-chain-failure (insufficient funds / blockhash) still
        # means the POLICY allowed signing. Reclassify those as ALLOW.
        if actual == "ERROR" and any(
            k in detail.lower()
            for k in ("insufficient", "fund", "blockhash", "0x1", "debit", "lamport")
        ):
            actual = "ALLOW"
            detail = f"policy-ALLOW; chain-side: {detail}"
        print(f"        actual = {actual}  | {detail}")
        results.append(CaseResult(name, expected, actual, detail))

    # (a) self->self  => ALLOW
    run_case("a", "ALLOW", [_self_transfer_ix(payer)], "system transfer self->self")

    # (b) self->OTHER => DENY  (core non-custodial proof)
    run_case("b", "DENY", [_foreign_transfer_ix(payer)], "system transfer self->FOREIGN")

    # (c) memo program (not allowlisted) => DENY (program-allowlisting)
    run_case("c", "DENY", [_memo_ix(payer)], "memo-program call (not in allowlist)")

    # (e) bundled: self-allowed + foreign-transfer in ONE tx => DENY (critical)
    run_case(
        "e",
        "DENY",
        [_self_transfer_ix(payer), _foreign_transfer_ix(payer)],
        "BUNDLED self-transfer + foreign-transfer in one tx (CRITICAL)",
    )

    # (d) revoke -> (a) now DENY too
    print("\n[case d] revoke (deny-all) then retry (a)  (expect DENY)")
    adapter.revoke(USER_ID)
    try:
        bh = _latest_blockhash()
        b64 = _b64_unsigned([_self_transfer_ix(payer)], payer, bh)
        actual, detail = _attempt(adapter, wallet_id, b64)
    except Exception as exc:
        actual, detail = "ERROR", f"build: {exc}"[:200]
    print(f"        actual = {actual}  | {detail}")
    results.append(CaseResult("d", "DENY", actual, detail))

    # -- table ------------------------------------------------------------
    print("\n" + "=" * 72)
    print(f"{'CASE':<6}{'WHAT':<44}{'EXPECT':<8}{'ACTUAL':<8}{'PASS'}")
    print("-" * 72)
    labels = {
        "a": "self->self transfer",
        "b": "self->FOREIGN transfer",
        "c": "memo program (not allowlisted)",
        "d": "after revoke: self->self",
        "e": "BUNDLED self + foreign (CRITICAL)",
    }
    for r in sorted(results, key=lambda x: x.case):
        mark = "PASS" if r.passed else "FAIL"
        print(f"{r.case:<6}{labels.get(r.case, ''):<44}{r.expected:<8}{r.actual:<8}{mark}")
    print("=" * 72)

    crit = next((r for r in results if r.case == "e"), None)
    all_pass = all(r.passed for r in results)
    print("\n=== VERDICT ===")
    print(f"  wallet_id : {wallet_id}")
    print(f"  address   : {link.address}")
    print(f"  policy_id : {policy_id}")
    if all_pass:
        print("  ALL CASES PASS — including the bundled/critical case (e).")
        print("  Non-custodial guarantee VERIFIED on devnet for these cases.")
    else:
        print("  NOT all cases pass. Signing MUST stay gated. See table above.")
    if crit is not None and not crit.passed:
        print(
            "  CRITICAL (e) did NOT behave as DENY — bundled foreign transfer "
            "is the residual risk; KEEP SIGNING GATED."
        )
    print("\nL2 DONE")
    return 0 if all_pass else 2


if __name__ == "__main__":
    try:
        rc = main()
    except Exception as exc:
        print(f"\nL2 FAIL: {type(exc).__name__}: {exc}")
        rc = 1
    sys.exit(rc)
