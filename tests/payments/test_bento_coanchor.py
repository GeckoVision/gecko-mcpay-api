"""Bento co-anchor memo (Option 2) — second SPL Memo, frozen hash UNCHANGED.

Pure + offline. Pins:
  * the ``bento:v1:{allow|deny}:{ref}`` memo string shape,
  * that the frozen ``gecko:v1:{h}`` verdict-hash spec + published test vector
    are UNCHANGED by this feature (the Bento memo is a second instruction, not
    a change to ``h``),
  * the co-anchor flag default (off) gating.

No network, no Solana stack.
"""

from __future__ import annotations

from gecko_core.payments.receipt.anchor import (
    BENTO_COANCHOR_ENV,
    is_bento_coanchor_enabled,
)
from gecko_core.payments.receipt.hash import (
    BENTO_MEMO_PREFIX,
    RECEIPT_MEMO_PREFIX,
    bento_memo_string,
    memo_string,
    receipt_hash,
)

# The published verdict-hash vector (must stay identical to test_receipt_hash.py).
_VECTOR_ENVELOPE = {
    "verdict": "pass",
    "confidence": 0.72,
    "citations": [
        {"id": 1, "source": "paysh", "url": "https://pay.sh/docs/x402"},
        {"id": 2, "source": "berkshire", "url": "https://berkshirehathaway.com/letters/2008.pdf"},
    ],
    "dissent": [
        {"voice": "risk_voice", "stance": "oppose", "verbatim": "bearish", "on_topic": "risk band"}
    ],
}
_VECTOR_HASH = "8821a7156451e9b5c8492b07c1f1985905589206a39847c9ffb40b4f4d9bf56b"


def test_bento_memo_allow_shape():
    assert bento_memo_string(allow=True, ref="att-123") == "bento:v1:allow:att-123"


def test_bento_memo_deny_shape():
    assert bento_memo_string(allow=False, ref="att-456") == "bento:v1:deny:att-456"


def test_bento_memo_prefix_is_distinct_from_verdict_prefix():
    assert BENTO_MEMO_PREFIX != RECEIPT_MEMO_PREFIX
    assert bento_memo_string(allow=True, ref="x").startswith("bento:v1:")


def test_frozen_verdict_hash_is_unchanged_by_bento_feature():
    """The load-bearing guarantee: the Bento co-anchor is a SECOND memo, it does
    NOT touch ``h`` or the ``gecko:v1:`` memo. The published vector still holds."""
    assert receipt_hash(_VECTOR_ENVELOPE) == _VECTOR_HASH
    assert memo_string(_VECTOR_ENVELOPE) == f"{RECEIPT_MEMO_PREFIX}{_VECTOR_HASH}"


def test_bento_memo_stays_under_spl_memo_limit():
    assert len(bento_memo_string(allow=True, ref="att-123").encode("utf-8")) < 566


def test_coanchor_flag_default_off():
    assert is_bento_coanchor_enabled({}) is False
    assert is_bento_coanchor_enabled({BENTO_COANCHOR_ENV: ""}) is False


def test_coanchor_flag_on():
    assert is_bento_coanchor_enabled({BENTO_COANCHOR_ENV: "1"}) is True
    assert is_bento_coanchor_enabled({BENTO_COANCHOR_ENV: "true"}) is True
    assert is_bento_coanchor_enabled({BENTO_COANCHOR_ENV: "on"}) is True
