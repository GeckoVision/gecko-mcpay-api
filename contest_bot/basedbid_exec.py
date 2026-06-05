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
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass

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

        # 4. OKX TEE sign + broadcast (the unsigned based.bid tx already carries blockhash)
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
