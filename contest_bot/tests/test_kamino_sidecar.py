"""Light tests for the Kamino TS-sidecar bridge (S40 real klend integration).

The unit tests here are network-free: they exercise the Python error-handling
seam (sidecar-missing, verbatim error-envelope propagation, sign-without-submit)
with fakes — NOT the real klend build, which needs a live RPC. The real build is
covered by a separate `live_kamino` marked test that hits mainnet read-only
(build+sign only, never submitted) and is skipped by default.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO / "contest_bot"))

from kamino.devnet_harness import (  # noqa: E402
    KaminoDevnetVaultAdapter,
    SidecarError,
    build_unsigned_kamino_tx,
)


def test_sidecar_missing_raises_sidecarerror(monkeypatch):
    """If build_tx.ts is absent, the bridge raises SidecarError (not a raw
    FileNotFound) with a remediation hint."""
    import kamino.devnet_harness as dh

    monkeypatch.setattr(dh, "TS_SIDECAR_BUILD", Path("/nonexistent/build_tx.ts"))
    with pytest.raises(SidecarError, match="TS sidecar not found"):
        build_unsigned_kamino_tx(
            cluster="devnet",
            action="deposit",
            market="M",
            reserve="R",
            amount_usd=Decimal("1"),
            owner_pubkey="O",
        )


def test_error_envelope_propagates_verbatim(monkeypatch):
    """A sidecar JSON error envelope is surfaced unrephrased (CLAUDE.md)."""
    import kamino.devnet_harness as dh

    class _Proc:
        returncode = 1
        stdout = '{"ok":false,"error":"Error","message":"Could not find oracle for USDC"}'
        stderr = ""

    monkeypatch.setattr(dh, "TS_SIDECAR_BUILD", _ExistingPath())
    monkeypatch.setattr(dh.subprocess, "run", lambda *a, **k: _Proc())
    with pytest.raises(SidecarError, match="Could not find oracle for USDC"):
        build_unsigned_kamino_tx(
            cluster="devnet",
            action="deposit",
            market="M",
            reserve="R",
            amount_usd=Decimal("1"),
            owner_pubkey="O",
        )


class _ExistingPath:
    """A stand-in TS_SIDECAR_BUILD whose .exists() is True."""

    def exists(self) -> bool:
        return True

    def __str__(self) -> str:
        return "/fake/build_tx.ts"

    @property
    def parent(self):  # cwd= in subprocess.run(str(...))
        return Path("/fake")


def test_devnet_without_market_refuses(monkeypatch):
    """Devnet adapter with no configured market/reserve refuses before shelling
    out — devnet has no verified usable USDC reserve (no oracle)."""
    from solders.keypair import Keypair

    ad = KaminoDevnetVaultAdapter(cluster="devnet")  # no market/reserve
    with pytest.raises(SidecarError, match="no Kamino market/reserve configured"):
        ad.deposit(Keypair(), Decimal("10"))


def test_sign_without_submit_does_not_send(monkeypatch):
    """build+sign path returns a `built+signed:` marker and never calls the RPC."""
    import kamino.devnet_harness as dh
    from solders.keypair import Keypair
    from solders.message import MessageV0
    from solders.transaction import VersionedTransaction

    kp = Keypair()
    # A minimal real (empty) v0 message so VersionedTransaction round-trips.
    import base64

    from solders.hash import Hash

    msg = MessageV0.try_compile(kp.pubkey(), [], [], Hash.default())
    unsigned = VersionedTransaction(msg, [kp])
    b64 = base64.b64encode(bytes(unsigned)).decode()

    monkeypatch.setattr(
        dh,
        "build_unsigned_kamino_tx",
        lambda **kw: {"unsignedTxBase64": b64, "programId": "KLend2g3", "action": "deposit"},
    )
    ad = KaminoDevnetVaultAdapter(cluster="mainnet", submit=False)
    sig = ad.deposit(kp, Decimal("100"))
    assert sig.startswith("built+signed:")


@pytest.mark.live_kamino
def test_real_mainnet_deposit_build(monkeypatch):
    """INTEGRATION (read-only, no submit): the sidecar builds a real klend deposit
    tx against mainnet and Python signs it. Hits a live RPC; run explicitly with
    `-m live_kamino`. Never submits, never spends."""
    from solders.keypair import Keypair

    ad = KaminoDevnetVaultAdapter(
        rpc_url="https://api.mainnet-beta.solana.com",
        cluster="mainnet",
        submit=False,
    )
    sig = ad.deposit(Keypair(), Decimal("100"))
    assert sig.startswith("built+signed:")
    b = ad.last_build or {}
    assert b.get("programId") == "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
    assert b.get("numInstructions", 0) >= 1
