"""Kamino profit-vault DEVNET harness (S43).

Validates OUR integration plumbing end-to-end against a REAL Solana devnet RPC,
then feeds the resulting position into the merged S42 monitor (`monitor.evaluate`)
to produce a HOLD / EXIT / DELEVERAGE / ROTATE verdict.

The point of the devnet test is NOT to test Kamino. It is to test the seam:
keypair custody, RPC reachability, deposit, position read, accrual, and — the
product — the safety monitor firing on a real on-chain position.

DISCIPLINE (CLAUDE.md):
- NO real money, NO mainnet. Devnet airdrop SOL only. Default cluster = devnet.
- Stub/paper posture: this harness never touches a funded mainnet wallet and
  never flips X402_MODE / PAPER. There is no mainnet branch in this file.
- Keypair lives in a gitignored file (`*.keypair.json` is in .gitignore). Never
  logged, never committed. We print only the PUBLIC key.
- Pattern B (CLAUDE.md): the FREE local/devnet simulation is the primary debug
  tool. Mainnet smoke is a separate, founder-gated, far-future step.

ADAPTER SEAM (the load-bearing design choice):
The harness talks to a vault through `VaultAdapter`. Two conformers ship here:

  1. MockVaultAdapter   — DEFAULT. A "deposit" is a real devnet lamport transfer
     from the harness wallet to a vault pubkey (an account the wallet controls).
     This exercises real RPC + signing + confirmation + balance read with ZERO
     Kamino dependency. Accrual is simulated forward in time over the position.
     This is the right FIRST devnet test: it falsifies our plumbing without
     depending on Kamino's devnet reserve config or the TS-only KTX SDK.

  2. KaminoDevnetVaultAdapter — STUB / documented, NOT wired. Kamino klend IS on
     devnet (verified on-chain: program KLend2g3… is executable on devnet with
     140 markets / 220 reserves; kvault devnet program devkRngFnfp4… exists).
     BUT the public REST/KTX API (api.kamino.finance) is mainnet-only, so a
     devnet deposit tx must be built with the klend TS SDK pointed at a devnet
     RPC + devnet program IDs — out of scope for THIS Python-first first cut.
     This stub marks exactly where that swaps in behind the same seam.

Both map onto the future `KaminoDelegatedExecutionAdapter` + the "kamino" venue
in `contest_bot/trade_safety.py` (sketched in the §seam section of the runbook).

Run it via the runbook script:  scripts/calibration/kamino_devnet_runbook.py
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from solders.keypair import Keypair
from solders.pubkey import Pubkey

# Real S42 modules — imported, never modified.
from kamino.monitor import FIAT_CDB_BR, Hurdle, VaultVerdict, evaluate, hurdle_for
from kamino.multiply import LeverageStrategy

# ── Cluster constants ───────────────────────────────────────────────────
DEVNET_RPC = "https://api.devnet.solana.com"
LAMPORTS_PER_SOL = 1_000_000_000

# Kamino DEVNET program IDs — VERIFIED on-chain 2026-06-04 (executable on devnet).
# Kept here for the follow-on real-klend tier; NOT used by MockVaultAdapter.
KAMINO_KLEND_DEVNET = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
KAMINO_KVAULT_DEVNET = "devkRngFnfp4gBc5a3LsadgbQKdPo8MSZ4prFiNSVmY"
# Devnet USDC mint (from the founder's gecko-vault init-devnet.ts).
DEVNET_USDC_MINT = "4zMMC9srt5Ri5X14GAgXhaHii3GnPAEERYPJgZJDncDU"

# Mainnet main-market + USDC reserve (from apy_cache.py) — the eventual real
# path. Kept here so the Kamino adapter is cluster-parameterized; mainnet build
# is read-only here (build+sign only, NEVER submitted without founder go-ahead).
KAMINO_MAIN_MARKET = "7u3HeHxYDLhnCoErrtycNokbQYbWGzLs6JSDqGAv5PfF"
KAMINO_USDC_RESERVE = "D6q6wuQSrifJKZYpR1M8R4YawnLDtDsMmWM1NbBmgJ59"

# TS sidecar that builds UNSIGNED Kamino txs (KTX REST is mainnet-only; devnet/
# cluster-parameterized tx construction must use the klend TS SDK).
TS_SIDECAR_DIR = Path(__file__).resolve().parent / "ts-sidecar"
TS_SIDECAR_BUILD = TS_SIDECAR_DIR / "build_tx.ts"


# ── Position model: the bridge from on-chain state → S42 LeverageStrategy ──
@dataclass(frozen=True)
class VaultPosition:
    """A point-in-time read of an on-chain vault position, normalized so the
    S42 monitor can judge it. `principal_usd` is what we put in; `value_usd` is
    what it's worth now (principal + simulated accrual). The monitor doesn't use
    USD directly — it judges the LeverageStrategy snapshot — but we carry these
    so the runbook can show the founder's `$1000 → +$X` framing.
    """

    venue: str
    deposit_sig: str | None
    principal_usd: Decimal
    value_usd: Decimal
    elapsed_years: float
    strategy: LeverageStrategy  # the snapshot fed to monitor.evaluate()


@runtime_checkable
class VaultAdapter(Protocol):
    """The seam. A devnet vault we can deposit into and read back.

    Mirrors the shape of `trade_safety.ExecutionAdapter` so a future
    `KaminoDelegatedExecutionAdapter` slots in unchanged. All methods are sync
    here for harness simplicity; the delegated/live adapter will be async.
    """

    venue: str

    def deposit(self, owner: Keypair, amount_usd: Decimal) -> str: ...

    def read_position(
        self, owner: Pubkey, principal_usd: Decimal, elapsed_seconds: float
    ) -> VaultPosition: ...


# ── Mock adapter: real devnet RPC, no Kamino dependency (DEFAULT) ─────────
class MockVaultAdapter:
    """A vault that is a plain account the harness wallet controls. "Deposit" is
    a real devnet lamport transfer; "value" = principal compounded at a fixed
    mock APY over elapsed time. Real network, real signature, real confirmation
    — only the YIELD SOURCE is mocked. This is the Pattern-B falsifier for our
    plumbing.

    The mock strategy mirrors a conservative Kamino kvault Earn tier (correlated
    stable, leverage configurable so we can exercise the 5x Multiply economics
    AND the monitor's leverage branches without a real flash loop).
    """

    venue = "mock-devnet"

    def __init__(
        self,
        rpc_url: str = DEVNET_RPC,
        *,
        mock_collateral_yield: float = 0.06,
        mock_borrow_rate: float = 0.04,
        leverage: float = 5.0,
        correlated: bool = True,
        yield_source: str = "stable_spread",
        max_ltv: float = 0.90,
        liquidation_ltv: float = 0.95,
        vault_pubkey: Pubkey | None = None,
    ) -> None:
        # Lazy import so importing this module never forces a solana-py client.
        from solana.rpc.api import Client

        self._client = Client(rpc_url)
        self._rpc_url = rpc_url
        self._yield = mock_collateral_yield
        self._borrow = mock_borrow_rate
        self._leverage = leverage
        self._correlated = correlated
        self._yield_source = yield_source
        self._max_ltv = max_ltv
        self._liq_ltv = liquidation_ltv
        # The "vault": a fresh ephemeral account we transfer to. Deterministic if
        # supplied, otherwise random per-run (it just needs to be a real pubkey).
        self._vault = vault_pubkey or Keypair().pubkey()

    @property
    def vault_pubkey(self) -> Pubkey:
        return self._vault

    def deposit(self, owner: Keypair, amount_usd: Decimal) -> str:
        """Transfer a small devnet lamport amount to the vault account as a stand-in
        for a USDC deposit. The USD amount is the LOGICAL deposit (what the monitor
        reasons about); the on-chain leg is a token-free SOL transfer so the harness
        needs no SPL mint/ATA bootstrap on the first cut. Returns the tx signature.
        """
        from solana.rpc.commitment import Confirmed
        from solders.message import MessageV0
        from solders.system_program import TransferParams, transfer
        from solders.transaction import VersionedTransaction

        # Fixed tiny on-chain leg (0.001 SOL) — the deposit's REALITY is the
        # confirmed signature, not the lamport size. Devnet SOL is free.
        lamports = 1_000_000  # 0.001 SOL
        ix = transfer(
            TransferParams(
                from_pubkey=owner.pubkey(),
                to_pubkey=self._vault,
                lamports=lamports,
            )
        )
        blockhash = self._client.get_latest_blockhash().value.blockhash
        msg = MessageV0.try_compile(owner.pubkey(), [ix], [], blockhash)
        tx = VersionedTransaction(msg, [owner])
        sig = self._client.send_transaction(tx).value
        self._client.confirm_transaction(sig, commitment=Confirmed)
        return str(sig)

    def read_position(
        self, owner: Pubkey, principal_usd: Decimal, elapsed_seconds: float
    ) -> VaultPosition:
        """Build the S42 LeverageStrategy snapshot + a compounded value projection.

        The strategy carries the (mock) live rates; the monitor decides on it. The
        value_usd uses the NET apy (after borrow drag at the configured leverage),
        i.e. the same number the monitor judges — so the displayed growth and the
        verdict are consistent.
        """
        strategy = LeverageStrategy(
            name="mock-kvault-earn",
            collateral_yield=self._yield,
            borrow_rate=self._borrow,
            leverage=self._leverage,
            max_ltv=self._max_ltv,
            liquidation_ltv=self._liq_ltv,
            correlated=self._correlated,
            yield_source=self._yield_source,
        )
        years = elapsed_seconds / (365.25 * 24 * 3600)
        value = principal_usd * Decimal(str((1.0 + strategy.net_apy) ** years))
        return VaultPosition(
            venue=self.venue,
            deposit_sig=None,  # filled by the runbook from deposit()
            principal_usd=principal_usd,
            value_usd=value,
            elapsed_years=years,
            strategy=strategy,
        )


# ── Kamino TS-sidecar bridge ──────────────────────────────────────────────
# (S43's KaminoDevnetVaultAdapter STUB is now REAL — it builds an unsigned klend
# tx via the TS sidecar (@kamino-finance/klend-sdk) and signs/submits in Python.
# KTX REST is mainnet-only, so cluster-parameterized tx construction must use the
# klend TS SDK. See contest_bot/kamino/ts-sidecar/.)
class SidecarError(RuntimeError):
    """The TS sidecar failed. Carries the sidecar's verbatim error envelope so
    failures propagate unrephrased (CLAUDE.md: surface failures verbatim)."""


def build_unsigned_kamino_tx(
    *,
    cluster: str,
    action: str,
    market: str,
    reserve: str,
    amount_usd: Decimal,
    owner_pubkey: str,
    rpc_url: str | None = None,
    decimals: int = 6,
    node_bin: str = "node",
    timeout_s: float = 180.0,
) -> dict[str, Any]:
    """Shell out to the TS sidecar (`node build_tx.ts`) to build an UNSIGNED
    Kamino klend deposit/withdraw tx. Returns the parsed JSON envelope, which
    includes `unsignedTxBase64`, `programId`, `numInstructions`, `ixLabels`.

    The sidecar NEVER signs and NEVER holds a key. Python (the caller) signs +
    submits. The sidecar's request payload is sent on stdin as JSON.
    """
    if not TS_SIDECAR_BUILD.exists():
        raise SidecarError(
            f"TS sidecar not found at {TS_SIDECAR_BUILD}. "
            f"Run `npm install` in {TS_SIDECAR_DIR} first."
        )
    payload: dict[str, Any] = {
        "cluster": cluster,
        "action": action,
        "market": market,
        "reserve": reserve,
        "amountUsd": str(amount_usd),
        "ownerPubkey": owner_pubkey,
        "decimals": decimals,
    }
    if rpc_url:
        payload["rpcUrl"] = rpc_url
    proc = subprocess.run(
        [node_bin, str(TS_SIDECAR_BUILD)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        cwd=str(TS_SIDECAR_DIR),
        timeout=timeout_s,
    )
    out = proc.stdout.strip()
    # The sidecar emits exactly one JSON line on stdout (ok or error envelope).
    # A non-zero exit with a JSON error line is the expected failure shape —
    # surface its message verbatim.
    parsed: dict[str, Any] | None = None
    if out:
        try:
            parsed = json.loads(out.splitlines()[-1])
        except json.JSONDecodeError:
            parsed = None
    if parsed is not None and parsed.get("ok") is False:
        raise SidecarError(f"{parsed.get('error', 'Error')}: {parsed.get('message', out)}")
    if proc.returncode != 0 or parsed is None:
        raise SidecarError(
            f"sidecar exited {proc.returncode}; stdout={out!r} stderr={proc.stderr.strip()!r}"
        )
    return parsed


# ── Kamino devnet adapter: REAL (klend TS-SDK sidecar + Python sign/submit) ─
class KaminoDevnetVaultAdapter:
    """Real Kamino klend lend deposit/withdraw, cluster-parameterized.

    Flow (per S43 design): the TS sidecar (@kamino-finance/klend-sdk) builds an
    UNSIGNED klend deposit tx -> this adapter signs it with the harness keypair
    (devnet) -> submits to the cluster RPC. Mainnet later swaps the local-keypair
    sign for a delegated OKX-TEE/Privy backend (custody flip; founder-gated).

    KNOWN devnet limitation (verified 2026-06-04 via `verify_devnet.ts`): the
    devnet USDC reserve has NO working oracle (klend-sdk: "Could not find oracle
    for USDC"; devnet Pyth accounts fail to decode). So a real devnet deposit
    BUILD fails at market-load / refresh_reserve. The same builder works against
    mainnet (oracle present) — that is the real path, founder-gated for submit.
    This adapter therefore proves BUILD+SIGN; on-chain SUBMIT is devnet-blocked
    by the missing oracle and mainnet-blocked by the founder gate.

    `submit=False` (default) builds+signs only and never sends — safe anywhere.
    `submit=True` sends to the configured cluster RPC.
    """

    venue = "kamino-devnet"

    def __init__(
        self,
        rpc_url: str = DEVNET_RPC,
        *,
        cluster: str = "devnet",
        market: str | None = None,
        reserve: str | None = None,
        submit: bool = False,
        node_bin: str = "node",
    ) -> None:
        self._rpc_url = rpc_url
        self._cluster = cluster
        if cluster == "mainnet":
            self._market = market or KAMINO_MAIN_MARKET
            self._reserve = reserve or KAMINO_USDC_RESERVE
        else:
            # No verified usable devnet USDC market/reserve (no oracle); caller
            # must pass one explicitly to even attempt a devnet build.
            self._market = market or ""
            self._reserve = reserve or ""
        self._submit = submit
        self._node_bin = node_bin
        self._last_build: dict[str, Any] | None = None

    @property
    def last_build(self) -> dict[str, Any] | None:
        """The most recent sidecar build envelope (programId, ixLabels, etc.)."""
        return self._last_build

    def deposit(self, owner: Keypair, amount_usd: Decimal) -> str:
        """Build (sidecar) -> sign (harness keypair) -> optionally submit.

        Returns the tx signature when submitted, else a `built+signed:<sig>`
        marker derived from the signed (un-submitted) tx. Build or submit errors
        are surfaced verbatim (never faked-success) per CLAUDE.md.
        """
        if not self._market or not self._reserve:
            raise SidecarError(
                "no Kamino market/reserve configured for cluster "
                f"{self._cluster!r}. Devnet has no verified usable USDC reserve "
                "(no oracle, per verify_devnet.ts) — pass market/reserve to "
                "force, or use cluster=mainnet (founder-gated for submit)."
            )
        build = build_unsigned_kamino_tx(
            cluster=self._cluster,
            action="deposit",
            market=self._market,
            reserve=self._reserve,
            amount_usd=amount_usd,
            owner_pubkey=str(owner.pubkey()),
            rpc_url=self._rpc_url,
            node_bin=self._node_bin,
        )
        self._last_build = build
        return self._sign_and_maybe_submit(owner, build["unsignedTxBase64"])

    def _sign_and_maybe_submit(self, owner: Keypair, unsigned_tx_b64: str) -> str:
        """Deserialize the unsigned versioned tx, sign with the harness keypair,
        and (if submit=True) send to the cluster RPC. Submit errors (e.g. an
        unfunded wallet) are surfaced verbatim, never swallowed.
        """
        from solders.transaction import VersionedTransaction

        raw = base64.b64decode(unsigned_tx_b64)
        unsigned = VersionedTransaction.from_bytes(raw)
        # The sidecar left the signature slot empty (noopSigner). Re-sign the
        # message with the owner keypair (sole signer / fee payer).
        signed = VersionedTransaction(unsigned.message, [owner])

        if not self._submit:
            return f"built+signed:{signed.signatures[0]}"

        from solana.rpc.api import Client
        from solana.rpc.commitment import Confirmed

        client = Client(self._rpc_url)
        sig = client.send_transaction(signed).value  # surfaces RPC errors verbatim
        client.confirm_transaction(sig, commitment=Confirmed)
        return str(sig)

    def read_position(
        self, owner: Pubkey, principal_usd: Decimal, elapsed_seconds: float
    ) -> VaultPosition:
        """Real Kamino obligation read (decode obligation account +
        refreshedStats) is the documented follow-on to the deposit
        build+sign+submit path. Gated on a usable on-chain position (devnet
        oracle blocker / mainnet founder gate)."""
        raise NotImplementedError(
            "real Kamino obligation read is the follow-on to deposit; gated on a "
            "usable on-chain position (devnet oracle blocker / mainnet founder gate)."
        )


# ── Keypair custody (gitignored) ──────────────────────────────────────────
def load_or_create_keypair(path: Path) -> Keypair:
    """Load a devnet keypair from a gitignored JSON file (solana-cli array format),
    creating it if absent. NEVER logs the secret. The filename must match the
    `*.keypair.json` .gitignore rule so it can never be committed.
    """
    if not path.name.endswith(".keypair.json"):
        raise ValueError(
            f"keypair path {path.name!r} must end in '.keypair.json' (the gitignore rule) "
            "so a devnet secret can never be committed"
        )
    if path.exists():
        secret = json.loads(path.read_text())
        return Keypair.from_bytes(bytes(secret))
    kp = Keypair()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(bytes(kp))))
    path.chmod(0o600)
    return kp


def ensure_devnet_funds(
    client: Any, pubkey: Pubkey, min_sol: float = 0.05, rpc_url: str = DEVNET_RPC
) -> float:
    """Airdrop devnet SOL if the balance is below `min_sol`. Returns the final
    balance in SOL. Devnet airdrop is rate-limited and flaky — surfaces the error
    verbatim (CLAUDE.md: surface failures, don't rephrase) so the runbook can tell
    the user to use the web faucet (faucet.solana.com) instead.

    `client` is a `solana.rpc.api.Client`; typed as Any to avoid forcing the
    solana-py import at module load.
    """
    from solana.rpc.commitment import Confirmed

    bal = float(client.get_balance(pubkey).value) / LAMPORTS_PER_SOL
    if bal >= min_sol:
        return bal
    sig = client.request_airdrop(pubkey, int(0.1 * LAMPORTS_PER_SOL)).value
    client.confirm_transaction(sig, commitment=Confirmed)
    deadline = time.time() + 30
    while time.time() < deadline:
        bal = float(client.get_balance(pubkey).value) / LAMPORTS_PER_SOL
        if bal >= min_sol:
            return bal
        time.sleep(2)
    return bal


# ── The one end-to-end flow ───────────────────────────────────────────────
@dataclass(frozen=True)
class HarnessResult:
    pubkey: str
    balance_sol: float
    deposit_sig: str
    position: VaultPosition
    verdict: VaultVerdict


def run_flow(
    adapter: VaultAdapter,
    keypair: Keypair,
    *,
    principal_usd: Decimal,
    accrual_seconds: float,
    hurdle: Hurdle = FIAT_CDB_BR,
    predicted_drawdown_pct: float | None = None,
    balance_sol: float = 0.0,
) -> HarnessResult:
    """deposit -> accrue -> read position -> S42 monitor verdict. One pass.

    `accrual_seconds` advances the (simulated) position age so we can exercise the
    monitor on a position that has grown. `predicted_drawdown_pct` is the Oracle's
    downside prediction for the collateral leg, wired into the same monitor branch
    the live vault uses (founder's '1000x10 dies on a 10% drop' insight).
    """
    sig = adapter.deposit(keypair, principal_usd)
    position = adapter.read_position(keypair.pubkey(), principal_usd, accrual_seconds)
    position = VaultPosition(
        venue=position.venue,
        deposit_sig=sig,
        principal_usd=position.principal_usd,
        value_usd=position.value_usd,
        elapsed_years=position.elapsed_years,
        strategy=position.strategy,
    )
    verdict = evaluate(
        position.strategy,
        hurdle=hurdle,
        predicted_drawdown_pct=predicted_drawdown_pct,
    )
    return HarnessResult(
        pubkey=str(keypair.pubkey()),
        balance_sol=balance_sol,
        deposit_sig=sig,
        position=position,
        verdict=verdict,
    )


def default_keypair_path() -> Path:
    """Gitignored devnet keypair location. Override with GECKO_DEVNET_KEYPAIR."""
    env = os.environ.get("GECKO_DEVNET_KEYPAIR")
    if env:
        return Path(env)
    return Path.home() / ".config" / "gecko" / "devnet-vault.keypair.json"


def make_adapter(kind: str, **kwargs: Any) -> VaultAdapter:
    """Adapter factory mirroring the X402 `get_client(mode)` pattern (CLAUDE.md)."""
    if kind == "mock":
        return MockVaultAdapter(**kwargs)
    if kind == "kamino":
        return KaminoDevnetVaultAdapter(**kwargs)
    raise ValueError(f"unknown vault adapter kind: {kind!r} (use 'mock' or 'kamino')")


def hurdle_from_profile(profile: str) -> Hurdle:
    return hurdle_for(profile)
