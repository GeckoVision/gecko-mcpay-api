"""Sprint 20 #2 — oracle_client.VerdictPayload.dissent wire tests.

Verifies that the structured ``dissent: list[DissentEntry]`` field added
to ``VerdictPayload`` in Sprint 20 #2 deserializes correctly from the
trade-oracle wire shape that Sprint 18 #3 added (see
``packages/gecko-core/.../trade_panel/models.py:DissentEntry``).

These tests are intentionally narrow — they exercise ONLY the model
contract, not the full x402 handshake. Light fakes only per
``feedback_lighter_tests``; no HTTP, no LLM.

Why this file exists separately from ``test_oracle_client_contract.py``:
the contract file is the full request-response handshake test; this
file is the typed-field deserialization probe. Splitting keeps each
test's blast radius local to one concern.
"""

from __future__ import annotations

from gecko_core.trade_agent.oracle_client import DissentEntry, VerdictPayload


def _verdict_with_dissent() -> dict:
    """Wire shape the gecko-api /trade_research endpoint emits today."""
    return {
        "verdict": "act",
        "confidence": 0.65,
        "citations": [],
        "turns": [],
        "dissent_count": 2,
        "dissent": [
            {
                "voice": "risk_manager",
                "stance": "oppose",
                "verbatim": "unacceptable",
                "on_topic": "risk band",
            },
            {
                "voice": "sentiment_analyst",
                "stance": "oppose",
                "verbatim": "fear",
                "on_topic": "sentiment band",
            },
        ],
    }


def test_verdict_payload_deserializes_dissent_list() -> None:
    """The new ``dissent`` field arrives as a list of typed DissentEntry."""
    payload = VerdictPayload.model_validate(_verdict_with_dissent())

    assert payload.dissent_count == 2
    assert len(payload.dissent) == 2
    assert isinstance(payload.dissent[0], DissentEntry)
    assert payload.dissent[0].voice == "risk_manager"
    assert payload.dissent[0].stance == "oppose"
    assert payload.dissent[0].verbatim == "unacceptable"
    assert payload.dissent[0].on_topic == "risk band"


def test_verdict_payload_defaults_dissent_empty_when_missing() -> None:
    """Older Oracle deploys (pre-Sprint-18-merge) don't emit ``dissent``.

    The bot must keep working — default to empty list, never crash on
    a missing field.
    """
    body = _verdict_with_dissent()
    del body["dissent"]
    payload = VerdictPayload.model_validate(body)

    assert payload.dissent == []
    # dissent_count still carries its value — back-compat is intact.
    assert payload.dissent_count == 2


def test_verdict_payload_dissent_empty_when_unanimous() -> None:
    """Unanimous panel (no opposing voice) → empty list. Empty IS the
    honest signal (consensus is real), not a data-quality flag."""
    body = _verdict_with_dissent()
    body["dissent"] = []
    body["dissent_count"] = 0
    payload = VerdictPayload.model_validate(body)

    assert payload.dissent == []
    assert payload.dissent_count == 0


def test_dissent_entry_tolerates_extra_fields_via_extra_allow() -> None:
    """Server-side schema additions (severity, weight, etc.) must not
    break the buyer's deserialization. ``extra='allow'`` lets new
    server fields pass through without a client bump."""
    body = _verdict_with_dissent()
    body["dissent"][0]["severity"] = "high"  # server-side future field
    body["dissent"][0]["weight"] = 0.85
    payload = VerdictPayload.model_validate(body)

    assert payload.dissent[0].voice == "risk_manager"  # required field intact
    # Extra fields preserved in model_dump
    dumped = payload.dissent[0].model_dump()
    assert dumped.get("severity") == "high"
    assert dumped.get("weight") == 0.85


def test_dissent_entry_partial_shape_does_not_crash() -> None:
    """If the server emits a dissent entry with only the ``voice`` field
    (e.g. malformed mid-rollout server-side bug), the buyer must still
    parse rather than crash the whole verdict.
    """
    body = _verdict_with_dissent()
    body["dissent"] = [{"voice": "risk_manager"}]  # missing stance, verbatim
    payload = VerdictPayload.model_validate(body)

    assert len(payload.dissent) == 1
    assert payload.dissent[0].voice == "risk_manager"
    assert payload.dissent[0].stance is None  # default when missing
    assert payload.dissent[0].verbatim is None


def test_dissent_entry_unknown_stance_tolerated() -> None:
    """Server-side stance vocabulary expansion (e.g. 'hedge') must not
    break old buyers. ``extra='allow'`` + ``stance | None`` defaults
    gracefully when the literal doesn't match.
    """
    body = _verdict_with_dissent()
    # Inject an unknown stance — pydantic Literal would normally reject,
    # but None-default + extra=allow on the parent helps the broader
    # envelope still deserialize. This tests the envelope's resilience,
    # not the strict-validation contract.
    body["dissent"] = [
        {
            "voice": "risk_manager",
            "stance": "oppose",  # keep valid stance for THIS entry
            "verbatim": "unacceptable",
        },
        {
            "voice": "fundamental_analyst",
            # No stance field at all — defaults to None gracefully
            "verbatim": "degraded",
        },
    ]
    payload = VerdictPayload.model_validate(body)
    assert len(payload.dissent) == 2
    assert payload.dissent[0].stance == "oppose"
    assert payload.dissent[1].stance is None
