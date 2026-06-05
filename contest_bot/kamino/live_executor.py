"""Kamino LIVE executor (A6) — the proven real-money flow as reusable, gated code.

This formalizes the exact path validated on mainnet 2026-06-05 ($10 USDC deposit +
withdraw round-trip): our TS sidecar builds an UNSIGNED klend tx → base64→base58 →
`onchainos wallet contract-call --chain solana --unsigned-tx` → the OKX Agentic
Wallet TEE signs + scans + broadcasts (custody never leaves the TEE).

DOUBLE-GATED so it can never spend by accident:
  1. instance `dry_run=True` (default) — builds + returns the tx, NEVER submits.
  2. per-call `confirm=True` — required IN ADDITION to dry_run=False to submit.
Submission happens ONLY when `dry_run=False AND confirm=True`. Anything else is a
build-only dry run. The orchestrator never flips both on its own — a real deposit
is always an explicit, founder-gated action (per the standing X402/PAPER discipline).

⚠️ Under the OKX per-tx policy limit, `contract-call` broadcasts DIRECTLY (no extra
confirm prompt). So `dry_run=False, confirm=True` IS the broadcast — treat it as live.
"""

from __future__ import annotations

import base64
import json
import subprocess
from dataclasses import dataclass
from decimal import Decimal

from kamino.apy_cache import KAMINO_MAIN_MARKET, KAMINO_USDC_RESERVE
from kamino.devnet_harness import KAMINO_KLEND_DEVNET, build_unsigned_kamino_tx

# Mainnet klend program (the eventual real path; KAMINO_*_DEVNET in devnet_harness
# is the same program id string — klend is deployed under one id on both clusters).
KLEND_PROGRAM = KAMINO_KLEND_DEVNET  # "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"


def _b64_to_b58(b64: str) -> str:
    raw = base64.b64decode(b64)
    try:
        import base58

        return base58.b58encode(raw).decode()
    except ImportError:  # solana-py ships based58
        import based58

        return based58.b58encode(raw).decode()


@dataclass
class ExecOutcome:
    ok: bool
    submitted: bool
    action: str
    amount_usd: float
    detail: str
    tx_hash: str | None = None
    num_instructions: int | None = None


class KaminoLiveExecutor:
    """Reusable deposit/withdraw against real Kamino via the OKX TEE. Default dry."""

    def __init__(
        self,
        owner_pubkey: str,
        *,
        dry_run: bool = True,
        market: str = KAMINO_MAIN_MARKET,
        reserve: str = KAMINO_USDC_RESERVE,
        cluster: str = "mainnet",
        rpc_url: str | None = None,
        onchainos_bin: str = "onchainos",
    ) -> None:
        self.owner = owner_pubkey
        self.dry_run = dry_run
        self.market = market
        self.reserve = reserve
        self.cluster = cluster
        self.rpc_url = rpc_url
        self._cli = onchainos_bin

    def deposit(self, amount_usd: float, *, confirm: bool = False) -> ExecOutcome:
        return self._run("deposit", amount_usd, confirm=confirm)

    def withdraw(self, amount_usd: float, *, confirm: bool = False) -> ExecOutcome:
        return self._run("withdraw", amount_usd, confirm=confirm)

    # ── internals ────────────────────────────────────────────────────────────
    def _run(self, action: str, amount_usd: float, *, confirm: bool) -> ExecOutcome:
        # 1. build the unsigned tx via the sidecar (always — cheap, no money)
        env = build_unsigned_kamino_tx(
            cluster=self.cluster, action=action, market=self.market, reserve=self.reserve,
            amount_usd=Decimal(str(amount_usd)), owner_pubkey=self.owner, rpc_url=self.rpc_url,
        )
        if not env.get("ok"):
            return ExecOutcome(False, False, action, amount_usd, f"sidecar build failed: {env}")
        nix = env.get("numInstructions")
        b58 = _b64_to_b58(env["unsignedTxBase64"])

        # 2. the double gate — submit ONLY when explicitly armed AND confirmed
        will_submit = (not self.dry_run) and confirm
        if not will_submit:
            why = "dry_run" if self.dry_run else "confirm=False"
            return ExecOutcome(
                True, False, action, amount_usd,
                f"built+ready (NOT submitted: {why}); {nix}-ix tx", num_instructions=nix,
            )

        # 3. live submit via OKX TEE (broadcasts directly under policy limit)
        proc = subprocess.run(
            [self._cli, "wallet", "contract-call", "--chain", "solana",
             "--to", KLEND_PROGRAM, "--unsigned-tx", b58],
            capture_output=True, text=True, timeout=180.0,
        )
        out = (proc.stdout or "").strip()
        try:
            resp = json.loads(out)
        except json.JSONDecodeError:
            return ExecOutcome(False, False, action, amount_usd,
                               f"contract-call non-JSON: {(out or proc.stderr)[:300]}")
        if not resp.get("ok"):
            return ExecOutcome(False, False, action, amount_usd, f"contract-call error: {resp}")
        tx_hash = (resp.get("data") or {}).get("txHash")
        return ExecOutcome(
            True, True, action, amount_usd,
            "submitted via OKX TEE (txHash is for tracking only — verify on-chain)",
            tx_hash=tx_hash, num_instructions=nix,
        )
