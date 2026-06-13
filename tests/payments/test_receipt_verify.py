"""Verifier contract test against a recorded getTransaction fixture.

Pattern C (CLAUDE.md): every payment-touching path ships a recorded-fixture
contract test before the live wire. The verifier reads the JSON-RPC ``result``
dict for a memo tx; the fixture
(``fixtures/receipt_get_transaction_jsonparsed.json``) is exactly what
``getTransaction(encoding=jsonParsed)`` returns for a Decision-Receipt anchor.

The ``fetch`` callable is injected, so this test does NO live RPC. The live
path (``default_rpc_fetch``) is exercised only under the ``live_solana`` marker,
opt-in, not in the default run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from gecko_core.payments.receipt.verify import RpcFetch, verify_receipt

# Must match tests/payments/test_receipt_hash.py — the same logical envelope.
ENVELOPE = {
    "verdict": "pass",
    "confidence": 0.72,
    "citations": [
        {"id": 1, "source": "paysh", "url": "https://pay.sh/docs/x402"},
        {
            "id": 2,
            "source": "berkshire",
            "url": "https://berkshirehathaway.com/letters/2008.pdf",
        },
    ],
    "dissent": [
        {
            "voice": "risk_voice",
            "stance": "oppose",
            "verbatim": "bearish",
            "on_topic": "risk band",
        },
    ],
}
VECTOR_HASH = "8821a7156451e9b5c8492b07c1f1985905589206a39847c9ffb40b4f4d9bf56b"
ORACLE_PUBKEY = "GEcKoOrac1eDevNetPubKeyPlaceholder1111111111"
RECEIPT_SIG = (
    "5DecisionReceiptDevnetSignaturePlaceholderXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
)

_FIXTURE = Path(__file__).parent / "fixtures" / "receipt_get_transaction_jsonparsed.json"


def _load_result() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_FIXTURE.read_text())
    return data


def _fetch_ok() -> RpcFetch:
    result = _load_result()
    return lambda _sig: result


def test_verify_passes_on_matching_memo_and_signer() -> None:
    res = verify_receipt(
        ENVELOPE,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey=ORACLE_PUBKEY,
        fetch=_fetch_ok(),
    )
    assert res.verified is True
    assert res.h == VECTOR_HASH
    assert res.reason == ""
    assert res.to_dict() == {
        "verified": True,
        "h": VECTOR_HASH,
        "receipt_sig": RECEIPT_SIG,
        "oracle_pubkey": ORACLE_PUBKEY,
        "reason": "",
    }


def test_verify_fails_when_envelope_tampered() -> None:
    """Flip the verdict — the re-hash no longer matches the on-chain memo."""
    tampered = {**ENVELOPE, "verdict": "act"}
    res = verify_receipt(
        tampered,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey=ORACLE_PUBKEY,
        fetch=_fetch_ok(),
    )
    assert res.verified is False
    assert "memo mismatch" in res.reason
    assert res.h != VECTOR_HASH


def test_verify_fails_when_oracle_pubkey_wrong() -> None:
    res = verify_receipt(
        ENVELOPE,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey="SomeOtherKeyThatDidNotSign2222222222222222",
        fetch=_fetch_ok(),
    )
    assert res.verified is False
    assert "not among tx signers" in res.reason


def test_verify_fails_when_tx_not_found() -> None:
    res = verify_receipt(
        ENVELOPE,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey=ORACLE_PUBKEY,
        fetch=lambda _sig: None,
    )
    assert res.verified is False
    assert res.reason == "transaction not found"


def test_verify_fails_when_no_memo_instruction() -> None:
    result = _load_result()
    result["transaction"]["message"]["instructions"] = []
    result["meta"]["logMessages"] = []
    res = verify_receipt(
        ENVELOPE,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey=ORACLE_PUBKEY,
        fetch=lambda _sig: result,
    )
    assert res.verified is False
    assert res.reason == "no memo instruction in tx"


def test_verify_via_log_message_fallback() -> None:
    """An RPC that leaves the memo instruction unparsed but logs it still
    verifies (the log-message fallback in _extract_memo_strings)."""
    result = _load_result()
    # Drop the parsed memo string; keep only the log echo.
    result["transaction"]["message"]["instructions"][0]["parsed"] = None
    res = verify_receipt(
        ENVELOPE,
        receipt_sig=RECEIPT_SIG,
        oracle_pubkey=ORACLE_PUBKEY,
        fetch=lambda _sig: result,
    )
    assert res.verified is True


@pytest.mark.live_solana
def test_verify_live_devnet() -> None:  # pragma: no cover - opt-in only
    """Live devnet round-trip. Opt-in (live_solana marker, excluded from the
    default run). Requires GECKO_RECEIPT_RPC_URL + a real receipt_sig +
    oracle pubkey from a prior anchor smoke. Skipped unless those are set."""
    import os

    rpc = os.environ.get("GECKO_RECEIPT_RPC_URL")
    sig = os.environ.get("GECKO_RECEIPT_TEST_SIG")
    pubkey = os.environ.get("GECKO_RECEIPT_ORACLE_PUBKEY")
    if not (rpc and sig and pubkey):
        pytest.skip("set GECKO_RECEIPT_RPC_URL / _TEST_SIG / _ORACLE_PUBKEY")

    from gecko_core.payments.receipt.verify import default_rpc_fetch

    res = verify_receipt(
        ENVELOPE, receipt_sig=sig, oracle_pubkey=pubkey, fetch=default_rpc_fetch(rpc)
    )
    assert res.verified is True
