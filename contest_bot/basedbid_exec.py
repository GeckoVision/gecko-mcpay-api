"""based.bid execution adapter (Arena) — LBP/Flash buy/sell via OKX TEE.

based.bid's API (`POST {sdk}/sol/lbp-buy|lbp-sell`) returns a base64 UNSIGNED
VersionedTransaction (their SDK's own flow). That fits Gecko's proven custody
pattern EXACTLY: HTTP → unsigned tx → OKX Agentic Wallet TEE signs+broadcasts.
No sidecar needed (based.bid builds the tx server-side). Covers BOTH the
pre-graduation bonding curve AND graduated tokens — the whole arena token life.

Endpoints (from github.com/basedbid-public/openbid):
  sandbox/devnet SDK : https://cdn.based.bid/api      (chainId 5011)
  production SDK      : https://static.based.bid/api   (chainId 501)
  body : {chainId, signer, memeMint, amount, slippage, referrer, isSandboxMode}
  resp : {transaction (base64), blockhash, lastValidBlockHeight}
  x-api-key only for custom boards; default board needs none.

DOUBLE-GATED (mirrors live_executor): instance `dry_run=True` default + per-call
`confirm=True`; submits ONLY when both. The irreversible line is the onchainos
contract-call. Sandbox/devnet (chainId 5011) is FREE to test end-to-end.

TWO SIGNING STRATEGIES (the seam this module adds in S50):
  - signer="okx-tee" (DEFAULT) — mainnet custody. The unsigned tx is signed +
    broadcast by the OKX Agentic Wallet TEE (`onchainos wallet contract-call`).
    The TEE is mainnet-only; it will NOT sign a devnet (chainId 5011) tx.
  - signer="local-keypair" — DEVNET ONLY. Decodes based.bid's base64 unsigned
    VersionedTransaction, signs it with a LOCAL devnet keypair (solders), and
    submits to the devnet cluster RPC. This is the EXACT proven pattern from
    `contest_bot/kamino/devnet_harness.py` (KaminoDevnetVaultAdapter:
    `_sign_and_maybe_submit`). It NEVER touches the mainnet OKX-TEE wallet and
    never moves real money. Same double-gate applies. The keypair is loaded from
    a gitignored file (GECKO_DEVNET_KEYPAIR or ~/.config/gecko/devnet-vault.keypair.json)
    and its secret bytes are NEVER logged.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import httpx
from trade_safety import (  # reuse the proven base64→base58 + the safety gate
    Order,
    SafetyContext,
    TradeSafetyPolicy,
    _b64_to_b58,
    basedbid_policy,
    check_order,
    with_global_kill,
)

SDK_SANDBOX = "https://cdn.based.bid/api"
SDK_PROD = "https://static.based.bid/api"
DEVNET_CHAIN = 5011
MAINNET_CHAIN = 501
ZERO_REFERRER = "11111111111111111111111111111111"  # also the System Program (inert --to)
_HTTP_TIMEOUT = 15.0

# Signing strategies (mirrors the X402 get_client(mode) factory shape, CLAUDE.md).
SIGNER_OKX_TEE = "okx-tee"  # mainnet custody (default) — onchainos wallet contract-call
SIGNER_LOCAL_KEYPAIR = "local-keypair"  # DEVNET ONLY — local solders keypair + cluster RPC

# Default devnet cluster RPC (override via GECKO_DEVNET_RPC). Mirrors the Kamino harness.
DEVNET_RPC = "https://api.devnet.solana.com"

# Conservative SOL→USD reference used ONLY to convert an arena `amount_sol` into the
# USD-equivalent notional the safety gate caps on. Deliberately HIGH (fail-closed):
# overstating the USD value can only make the notional cap bite SOONER, never later.
_DEFAULT_SOL_PRICE_USD = 250.0


def _resolve_global_kill() -> bool:
    """Read the operator-wide kill flag from the control plane. Lazy import keeps
    this module light + avoids a hard dep on agent_store at import time; if the
    store is unavailable we FAIL CLOSED (treat as killed)."""
    try:
        from agent_store import is_global_kill

        return bool(is_global_kill())
    except Exception:
        return True


def default_devnet_keypair_path() -> Path:
    """Gitignored devnet keypair location (shared with the Kamino harness).
    Override with GECKO_DEVNET_KEYPAIR. The filename ends in '.keypair.json' so it
    matches the .gitignore rule and a devnet secret can never be committed."""
    env = os.environ.get("GECKO_DEVNET_KEYPAIR")
    if env:
        return Path(env)
    return Path.home() / ".config" / "gecko" / "devnet-vault.keypair.json"


def load_devnet_keypair(path: Path | None = None):
    """Load the LOCAL devnet keypair (solders) from a gitignored JSON file
    (solana-cli byte-array format). NEVER logs the secret bytes — callers only
    ever see the PUBLIC key. Lazy solders import so a plain `import basedbid_exec`
    never forces solders. Mirrors devnet_harness.load_or_create_keypair, minus the
    create branch (the based.bid signer must use the funded, known wallet — it
    refuses to silently mint a fresh unfunded key)."""
    from solders.keypair import Keypair

    p = path or default_devnet_keypair_path()
    if not p.name.endswith(".keypair.json"):
        raise ValueError(
            f"keypair path {p.name!r} must end in '.keypair.json' (the gitignore rule) "
            "so a devnet secret can never be committed"
        )
    if not p.exists():
        raise FileNotFoundError(
            f"devnet keypair not found at {p}. Set GECKO_DEVNET_KEYPAIR or place the "
            "gitignored keypair at ~/.config/gecko/devnet-vault.keypair.json."
        )
    secret = json.loads(p.read_text())
    return Keypair.from_bytes(bytes(secret))


def default_devnet_rpc() -> str:
    """Devnet cluster RPC; override via GECKO_DEVNET_RPC."""
    return os.environ.get("GECKO_DEVNET_RPC", DEVNET_RPC)


@dataclass
class BasedBidOutcome:
    ok: bool
    submitted: bool
    action: str
    mint: str
    amount_sol: float
    detail: str
    tx_hash: str | None = None


class BasedBidExecutionAdapter:
    """LBP/Flash buy+sell for based.bid tokens, signed by the OKX TEE. Default dry+sandbox."""

    venue = "basedbid"

    def __init__(
        self,
        owner_pubkey: str,
        *,
        dry_run: bool = True,
        sandbox: bool = True,
        slippage: int = 5,
        referrer: str = ZERO_REFERRER,
        api_key: str | None = None,
        onchainos_bin: str = "onchainos",
        http_client: httpx.Client | None = None,
        # signing strategy: "okx-tee" (mainnet custody, default) or "local-keypair"
        # (DEVNET ONLY — local solders keypair signs + submits to the cluster RPC).
        signer: str = SIGNER_OKX_TEE,
        devnet_keypair_path: Path | None = None,
        devnet_rpc: str | None = None,
        # injectable for tests: a pre-loaded solders Keypair (so the signer path can
        # be exercised with a MOCKED keypair, no file read, no real wallet).
        devnet_keypair=None,
        # safety-gate wiring (the kill-switch + notional/daily-loss caps). Injectable
        # so the orchestrator passes per-agent caps; defaults to a deny-default policy
        # that ALWAYS honors the global kill-switch even when nothing is wired.
        policy: TradeSafetyPolicy | None = None,
        safety_ctx: SafetyContext | None = None,
        sol_price_usd: float = _DEFAULT_SOL_PRICE_USD,
        global_kill_fn=None,
    ) -> None:
        self.owner = owner_pubkey
        self.dry_run = dry_run
        self.sandbox = sandbox
        self.slippage = slippage
        self.referrer = referrer
        self.api_key = api_key
        self._cli = onchainos_bin
        self._client = http_client
        # default policy enables the basedbid venue but keeps require_verified_strategy
        # (deny-default): a caller must pass a DEPLOY verdict via safety_ctx to proceed.
        self.policy = policy if policy is not None else basedbid_policy()
        self.safety_ctx = safety_ctx if safety_ctx is not None else SafetyContext()
        self.sol_price_usd = sol_price_usd
        self._global_kill_fn = global_kill_fn or _resolve_global_kill
        if signer not in (SIGNER_OKX_TEE, SIGNER_LOCAL_KEYPAIR):
            raise ValueError(
                f"unknown signer {signer!r} (use {SIGNER_OKX_TEE!r} or {SIGNER_LOCAL_KEYPAIR!r})"
            )
        # local-keypair is DEVNET ONLY — refuse to pair it with a mainnet (sandbox=False)
        # adapter so a devnet key can never be aimed at the mainnet chain id.
        if signer == SIGNER_LOCAL_KEYPAIR and not sandbox:
            raise ValueError(
                "signer='local-keypair' is devnet-only; it cannot run with sandbox=False "
                "(mainnet, chainId 501). Use signer='okx-tee' for mainnet."
            )
        self.signer = signer
        self._devnet_keypair_path = devnet_keypair_path
        self._devnet_rpc = devnet_rpc or default_devnet_rpc()
        # pre-loaded keypair wins (tests / explicit injection); else lazy-loaded on submit.
        self._devnet_keypair = devnet_keypair

    @property
    def _api(self) -> str:
        return SDK_SANDBOX if self.sandbox else SDK_PROD

    @property
    def _chain(self) -> int:
        return DEVNET_CHAIN if self.sandbox else MAINNET_CHAIN

    def buy(self, mint: str, amount_sol: float, *, confirm: bool = False) -> BasedBidOutcome:
        return self._run("lbp-buy", mint, amount_sol, confirm=confirm)

    def sell(self, mint: str, amount_sol: float, *, confirm: bool = False) -> BasedBidOutcome:
        return self._run("lbp-sell", mint, amount_sol, confirm=confirm)

    # ── internals ────────────────────────────────────────────────────────────
    def _build_unsigned(self, action: str, mint: str, amount_sol: float) -> dict:
        """POST based.bid → {transaction(base64), blockhash, lastValidBlockHeight}."""
        payload = {
            "chainId": self._chain, "signer": self.owner, "memeMint": mint,
            "amount": amount_sol, "slippage": self.slippage, "referrer": self.referrer,
            "isSandboxMode": self.sandbox,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["x-api-key"] = self.api_key
        url = f"{self._api}/sol/{action}"
        if self._client is not None:
            return self._client.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT).json()
        with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
            r = c.post(url, json=payload, headers=headers)
            r.raise_for_status()
            return r.json()

    def _run(self, action: str, mint: str, amount_sol: float, *, confirm: bool) -> BasedBidOutcome:
        # 1. build the unsigned tx via based.bid (always — cheap, no money)
        try:
            env = self._build_unsigned(action, mint, amount_sol)
        except Exception as exc:
            return BasedBidOutcome(False, False, action, mint, amount_sol, f"based.bid API error: {type(exc).__name__}: {exc}")
        tx_b64 = env.get("transaction")
        if not tx_b64:
            return BasedBidOutcome(False, False, action, mint, amount_sol, f"no transaction in based.bid response: {env}")

        # 2. SAFETY GATE (deny-default) — global kill → check_order. This is the
        #    gate the app's /kill + per-agent notional/daily-loss caps ride on.
        #    Mirrors JupiterSwapExecutionAdapter going through check_order/dispatch.
        side = "buy" if action == "lbp-buy" else "sell"
        notional_usd = float(amount_sol) * float(self.sol_price_usd)
        order = Order(symbol=mint, venue=self.venue, notional_usd=notional_usd, side=side)
        policy = with_global_kill(self.policy, self._global_kill_fn())
        verdict = check_order(order, policy, self.safety_ctx)
        if not verdict.allow:
            return BasedBidOutcome(
                False, False, action, mint, amount_sol,
                "safety-gate denied: " + "; ".join(verdict.reasons),
            )

        # 3. double gate — submit ONLY when armed AND confirmed
        if self.dry_run or not confirm:
            why = "dry_run" if self.dry_run else "confirm=False"
            return BasedBidOutcome(True, False, action, mint, amount_sol,
                                   f"built+ready (NOT submitted: {why}); sandbox={self.sandbox}")

        # 4. SIGN + BROADCAST — dispatch on the signing strategy.
        if self.signer == SIGNER_LOCAL_KEYPAIR:
            return self._submit_local_keypair(action, mint, amount_sol, tx_b64)
        return self._submit_okx_tee(action, mint, amount_sol, tx_b64)

    def _submit_okx_tee(
        self, action: str, mint: str, amount_sol: float, tx_b64: str
    ) -> BasedBidOutcome:
        """Mainnet custody: OKX TEE signs + broadcasts the unsigned based.bid tx
        (the tx already carries blockhash). NEVER reachable on the devnet signer."""
        # TODO(item #6): unify the broadcast seam — Jupiter goes through the OnchainOS
        # Python wrapper (wallet_contract_call); this + kamino/live_executor shell out to
        # subprocess directly. Same CLI underneath; migrate both to OnchainOS so there is
        # ONE broadcast path to audit/mock. Deferred (touches live-money seam; risky now).
        b58 = _b64_to_b58(tx_b64)
        proc = subprocess.run(
            [self._cli, "wallet", "contract-call", "--chain", "solana",
             "--to", ZERO_REFERRER, "--unsigned-tx", b58],  # --to inert; real targets are in the tx
            capture_output=True, text=True, timeout=180.0,
        )
        out = (proc.stdout or "").strip()
        try:
            resp = json.loads(out)
        except json.JSONDecodeError:
            return BasedBidOutcome(False, False, action, mint, amount_sol,
                                   f"contract-call non-JSON: {(out or proc.stderr)[:300]}")
        if not resp.get("ok"):
            return BasedBidOutcome(False, False, action, mint, amount_sol, f"contract-call error: {resp}")
        return BasedBidOutcome(
            True, True, action, mint, amount_sol,
            "submitted via OKX TEE (txHash tracking-only — verify on-chain)",
            tx_hash=(resp.get("data") or {}).get("txHash"),
        )

    def _submit_local_keypair(
        self, action: str, mint: str, amount_sol: float, tx_b64: str
    ) -> BasedBidOutcome:
        """DEVNET ONLY: decode based.bid's base64 unsigned VersionedTransaction,
        sign it with the local devnet keypair (solders), submit to the cluster RPC.

        EXACT mirror of devnet_harness.KaminoDevnetVaultAdapter._sign_and_maybe_submit:
        based.bid leaves the fee-payer signature slot empty (the `signer` we POST is
        the sole signer / fee payer), so we re-sign the message with the owner keypair.
        Submit/RPC errors are surfaced verbatim (CLAUDE.md), never faked-success.
        The keypair's secret bytes are never logged."""
        from solders.transaction import VersionedTransaction

        # Lazy-load the keypair (or use the injected one). Secret bytes never logged.
        try:
            keypair = self._devnet_keypair or load_devnet_keypair(self._devnet_keypair_path)
        except Exception as exc:
            return BasedBidOutcome(False, False, action, mint, amount_sol,
                                   f"devnet keypair load error: {type(exc).__name__}: {exc}")

        # Defense-in-depth: the signer pubkey MUST equal the based.bid `signer` we
        # built the tx for, or the tx will fail / target the wrong account.
        if str(keypair.pubkey()) != self.owner:
            return BasedBidOutcome(
                False, False, action, mint, amount_sol,
                f"devnet keypair pubkey {keypair.pubkey()} != adapter owner {self.owner}; "
                "build the unsigned tx for the same wallet that signs it",
            )

        try:
            raw = base64.b64decode(tx_b64)
            unsigned = VersionedTransaction.from_bytes(raw)
            signed = VersionedTransaction(unsigned.message, [keypair])
        except Exception as exc:
            return BasedBidOutcome(False, False, action, mint, amount_sol,
                                   f"devnet sign error: {type(exc).__name__}: {exc}")

        from solana.rpc.api import Client
        from solana.rpc.commitment import Confirmed

        try:
            client = Client(self._devnet_rpc)
            sig = client.send_transaction(signed).value  # surfaces RPC errors verbatim
            client.confirm_transaction(sig, commitment=Confirmed)
        except Exception as exc:
            return BasedBidOutcome(False, False, action, mint, amount_sol,
                                   f"devnet submit error: {type(exc).__name__}: {exc}")

        return BasedBidOutcome(
            True, True, action, mint, amount_sol,
            f"submitted via local devnet keypair to {self._devnet_rpc} "
            "(verify on devnet explorer)",
            tx_hash=str(sig),
        )


# ── Best-effort self-mint of a sandbox token (so we don't block on based.bid) ──
@dataclass
class SandboxTokenResult:
    ok: bool
    mint: str | None
    detail: str
    raw: dict | None = None


def self_create_sandbox_token(
    *,
    name: str,
    symbol: str,
    metadata_url: str,
    signer: str,
    data: dict | None = None,
    api_key: str | None = None,
    http_client: httpx.Client | None = None,
) -> SandboxTokenResult:
    """Best-effort: ask based.bid's sandbox to BUILD an unsigned create-LBP tx so we
    can mint our OWN devnet test token (then sign+submit via the local-keypair path,
    and confirm-launch). This removes the external "we need a sandbox mint" blocker
    IF the create endpoint accepts an unauthenticated default-board launch.

    STATUS (probed 2026-06-06, unauthenticated, chainId 5011): the endpoint is
    reachable and DOES build + simulate a real devnet token-creation tx (token mint
    + Metaplex metadata succeed in simulation). It fails at the LBP curve math
    (`SolDivisionFailed`, AnchorError 6049) when the `data` launch params are
    incomplete — i.e. the missing piece is the EXACT LbpCreationRework Sol-branch
    `data` subschema (sale supply / price / curve fields), NOT auth and NOT
    reachability. Pass a complete `data` dict to drive it; this helper returns the
    based.bid envelope verbatim so the caller can see exactly which field is missing.

    Returns the create-lbp envelope. On success the caller signs the returned
    unsigned tx (local-keypair), submits, then POSTs /sol/confirm-launch with the
    tx signature + mintAddress. The mint is then a tradable sandbox token.
    """
    payload: dict = {
        "chainId": DEVNET_CHAIN,
        "signer": signer,
        "isSandboxMode": True,
        "data": {
            "token": {"name": name, "symbol": symbol, "metadataUrl": metadata_url},
            **(data or {}),
        },
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    url = f"{SDK_SANDBOX}/sol/create-lbp"
    try:
        if http_client is not None:
            env = http_client.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT).json()
        else:
            with httpx.Client(timeout=_HTTP_TIMEOUT) as c:
                env = c.post(url, json=payload, headers=headers).json()
    except Exception as exc:
        return SandboxTokenResult(False, None, f"create-lbp API error: {type(exc).__name__}: {exc}")

    if not isinstance(env, dict) or env.get("ok") is False or "transaction" not in env:
        # Surface based.bid's error verbatim (CLAUDE.md) — usually the missing
        # `data` subschema field; that is the exact external ask.
        return SandboxTokenResult(
            False, None,
            f"create-lbp did not return an unsigned tx: {env}", raw=env if isinstance(env, dict) else None,
        )
    return SandboxTokenResult(
        True, env.get("mintAddress") or env.get("mint"),
        "create-lbp built an unsigned token-creation tx; sign+submit (local-keypair) "
        "then POST /sol/confirm-launch with the signature + mintAddress",
        raw=env,
    )
