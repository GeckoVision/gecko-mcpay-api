"""Pure, offline, deterministic test of the Decision-Receipt canonical hash.

The canonical serialization is a frozen contract (see
``gecko_core.payments.receipt.hash`` module docstring). A third-party verifier
in ANY language must reproduce these exact bytes. This test pins:

  * the canonical JSON string (byte-for-byte),
  * the sha256 hex ``h`` (the published test vector),
  * the on-chain memo string ``gecko:v1:{h}``,

and asserts the projection is STABLE across input shapes (plain dict vs the
pydantic ``VerdictPayload`` carrying enrichment fields) — a divergence there
would silently break verification.

No network, no Solana stack. Runs in the default suite.
"""

from __future__ import annotations

from gecko_core.payments.receipt.hash import (
    RECEIPT_MEMO_PREFIX,
    canonical_envelope_json,
    memo_string,
    receipt_hash,
)
from gecko_core.trade_agent.oracle_client import (
    Citation,
    DissentEntry,
    VerdictPayload,
)

# ---------------------------------------------------------------------------
# THE PUBLISHED TEST VECTOR — do not edit without bumping the memo prefix.
# ---------------------------------------------------------------------------

VECTOR_ENVELOPE = {
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

VECTOR_CANONICAL_JSON = (
    '{"citations":['
    '{"id":"1","source":"paysh","url":"https://pay.sh/docs/x402"},'
    '{"id":"2","source":"berkshire","url":"https://berkshirehathaway.com/letters/2008.pdf"}'
    '],"confidence":0.72,'
    '"dissent":[{"on_topic":"risk band","stance":"oppose","verbatim":"bearish","voice":"risk_voice"}],'
    '"verdict":"pass"}'
)

VECTOR_HASH = "8821a7156451e9b5c8492b07c1f1985905589206a39847c9ffb40b4f4d9bf56b"
VECTOR_MEMO = f"{RECEIPT_MEMO_PREFIX}{VECTOR_HASH}"


def test_canonical_json_is_exact_bytes() -> None:
    assert canonical_envelope_json(VECTOR_ENVELOPE) == VECTOR_CANONICAL_JSON


def test_receipt_hash_matches_vector() -> None:
    assert receipt_hash(VECTOR_ENVELOPE) == VECTOR_HASH


def test_memo_string_matches_vector() -> None:
    assert memo_string(VECTOR_ENVELOPE) == VECTOR_MEMO
    # memo accepts a precomputed hash too.
    assert memo_string(VECTOR_HASH) == VECTOR_MEMO
    # Memo stays well under the 566-byte SPL Memo limit.
    assert len(VECTOR_MEMO.encode("utf-8")) < 566


def test_pydantic_envelope_hashes_identically_to_dict() -> None:
    """The SAME logical verdict, built as a pydantic VerdictPayload with
    enrichment fields (turns/backtest/chunk_id/snippet), must hash to the
    SAME ``h`` — the canonical projection excludes everything but the four
    spec fields and the {id,source,url} citation projection."""
    vp = VerdictPayload(
        verdict="pass",
        confidence=0.72,
        citations=[
            Citation(
                id=1,
                source="paysh",
                url="https://pay.sh/docs/x402",
                chunk_id="mongo-oid-aaa",
                snippet="this should NOT enter the hash",
                provider_kind="paysh_live",
            ),
            Citation(
                id=2,
                source="berkshire",
                url="https://berkshirehathaway.com/letters/2008.pdf",
            ),
        ],
        dissent=[
            DissentEntry(
                voice="risk_voice",
                stance="oppose",
                verbatim="bearish",
                on_topic="risk band",
            )
        ],
        turns=[{"agent": "technical_analyst", "content": "long prose ..."}],
        dissent_count=1,
        backtest={"sharpe": 1.2},
    )
    assert receipt_hash(vp) == VECTOR_HASH


def test_enrichment_fields_do_not_change_hash() -> None:
    """Adding arbitrary extra top-level keys must not change ``h``."""
    base = receipt_hash(VECTOR_ENVELOPE)
    noisy = {**VECTOR_ENVELOPE, "shed": True, "freshness": {"tier": "live"}, "x": [1, 2]}
    assert receipt_hash(noisy) == base


def test_citation_order_is_preserved_not_sorted() -> None:
    """Citation list order is meaningful (matches inline [N] markers); the
    canonical projection must NOT reorder it. Swapping the two citations must
    change the hash."""
    swapped = {
        **VECTOR_ENVELOPE,
        "citations": list(reversed(VECTOR_ENVELOPE["citations"])),  # type: ignore[arg-type]
    }
    assert receipt_hash(swapped) != VECTOR_HASH


def test_missing_optional_fields_default_to_empty() -> None:
    """A bare verdict (no citations / dissent) hashes deterministically."""
    bare = {"verdict": "act", "confidence": 0.5}
    expected = canonical_envelope_json(bare)
    assert expected == '{"citations":[],"confidence":0.5,"dissent":[],"verdict":"act"}'
    # confidence None coerces to 0.0
    none_conf = {"verdict": "act", "confidence": None}
    assert '"confidence":0.0' in canonical_envelope_json(none_conf)


def test_unicode_source_hashes_as_utf8() -> None:
    """ensure_ascii=False — non-ASCII text enters as UTF-8 bytes, not \\uXXXX
    escapes. The canonical string must contain the literal character."""
    env = {
        "verdict": "pass",
        "confidence": 0.5,
        "citations": [{"id": 1, "source": "café", "url": "https://x"}],
        "dissent": [],
    }
    canon = canonical_envelope_json(env)
    assert "café" in canon
    assert "\\u" not in canon
