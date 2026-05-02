"""S20-X402-VERDICT-SETTLE-01 (#11) — stub-mode end-to-end tests.

Covers the paywall on ``GET /v1/verdict/{hash}?detail=full``:

  * No X-Payment header → 402 with the x402_challenge body.
  * Stub-signed X-Payment matching the verdict_hash → 200 with the
    full ResearchResult-shaped body + settlement_receipt.
  * Bad signature shape (no ``stub:`` prefix) → 402, challenge re-issued
    with ``last_failure`` populated.
  * Wrong scope (signed for verdict B, requesting verdict A) → 402.
  * Path-segment ``/detail`` 308-redirects to ``?detail=full``.
  * Live verifier path refuses to run when X402_VERDICT_SETTLE_LIVE
    is unset (defence-in-depth Pattern C).

Mongo is patched with ``mongomock`` per the existing test_verdict_route
template so these tests are hermetic — no real Mongo, no real x402.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient

_FULL_HASH = "a" * 64
_OTHER_HASH = "b" * 64


def _seed_doc(
    *,
    verdict_hash: str = _FULL_HASH,
    idea_text: str = "a hotel guide for Brazil",
    judge_prose: str = (
        "Final verdict: GO\nThe wedge is grounded in real demand signals "
        "across multiple distinct provider kinds; dissent acknowledged but not load-bearing."
    ),
    actual_verdict_v2: str = "GO",
    tier: str = "pro",
    advisor_voices: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "session_id": f"sess-{verdict_hash[:8]}",
        "idea_text": idea_text,
        "judge_prose": judge_prose,
        "parsed_verdict": actual_verdict_v2,
        "actual_verdict": "ship" if actual_verdict_v2 == "GO" else "pivot",
        "actual_verdict_v2": actual_verdict_v2,
        "gap_classification": "Partial:UX",
        "gap_summary": "wedge defensible against Booking; hotel-host onboarding remains thin",
        "tier": tier,
        "agent_turns": {
            "founder": {"turns": 2},
            "skeptic": {"turns": 3},
            "judge": {"turns": 1},
        },
        "advisor_voices": advisor_voices,
        "verdict_hash": verdict_hash,
        "provider_mix_flag": "balanced",
        "created_at": datetime.now(UTC),
    }


@pytest.fixture
def patched_mongo(monkeypatch: pytest.MonkeyPatch) -> Any:
    import mongomock
    from gecko_api.routes import verdict as v

    fake = mongomock.MongoClient()
    coll = fake["gecko_test"]["judge_transcripts"]
    monkeypatch.setattr(v, "_get_collection", lambda: coll)
    return coll


@pytest.fixture
def stub_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force stub mode on both gates so the paywall stays hermetic."""
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.delenv("X402_VERDICT_SETTLE_LIVE", raising=False)


@pytest.fixture
def client() -> TestClient:
    from gecko_api.main import app

    return TestClient(app)


# ---------------------------------------------------------------------------
# 402 challenge — no X-Payment header.
# ---------------------------------------------------------------------------


def test_detail_full_returns_402_with_challenge(
    patched_mongo: Any, stub_mode: None, client: TestClient
) -> None:
    patched_mongo.insert_one(_seed_doc())

    resp = client.get(f"/v1/verdict/{_FULL_HASH}?detail=full")
    assert resp.status_code == 402, resp.text
    body = resp.json()

    assert body["error"] == "payment_required"
    assert body["verdict_hash"] == _FULL_HASH
    assert body["price_usdc"] == "2.50"

    challenge = body["x402_challenge"]
    assert challenge["scope"] == f"verdict:{_FULL_HASH}"
    assert challenge["price_usdc"] == "2.50"
    assert challenge["network"] == "stub"
    assert challenge["facilitator"] == "stub"
    assert challenge["challenge_id"]  # truthy, non-empty


def test_detail_full_missing_hash_is_404(
    patched_mongo: Any, stub_mode: None, client: TestClient
) -> None:
    """No persisted verdict → 404 even on the paywall surface.

    The paywall must not leak "this hash exists" via a 402 vs. a 404 —
    both branches go through ``_not_found`` early.
    """
    resp = client.get(f"/v1/verdict/{_FULL_HASH}?detail=full")
    assert resp.status_code == 404
    assert resp.json()["error"] == "verdict_not_found"


# ---------------------------------------------------------------------------
# 200 — stub-signed payment.
# ---------------------------------------------------------------------------


def test_detail_full_stub_signed_returns_200(
    patched_mongo: Any, stub_mode: None, client: TestClient
) -> None:
    patched_mongo.insert_one(
        _seed_doc(
            advisor_voices=[
                {"name": "skeptic", "verdict": "PIVOT", "summary": "ICP too narrow"},
                {"name": "founder", "verdict": "GO", "summary": "wedge intact"},
            ],
        )
    )

    resp = client.get(
        f"/v1/verdict/{_FULL_HASH}?detail=full",
        headers={"X-Payment": f"stub:{_FULL_HASH}:nonce-12345"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Identity
    assert body["verdict_hash"] == _FULL_HASH
    assert body["verdict_hash_short"] == f"verdict@{_FULL_HASH[:12]}"
    assert body["verdict"] == "GO"
    assert body["idea_text"] == "a hotel guide for Brazil"
    assert body["tier"] == "pro"

    # Full prose, not the teaser excerpt — buyer paid for it.
    assert "wedge is grounded" in body["judge_prose_full"]
    assert "dissent acknowledged" in body["judge_prose_full"]
    assert body["gap_classification"] == "Partial:UX"
    assert body["gap_summary"]
    assert body["provider_mix_flag"] == "balanced"

    # Optional richer payloads — present here, ``None`` for legacy rows.
    assert body["advisor_voices"][0]["name"] == "skeptic"
    assert body["transcript"] == body["agent_turns"]
    assert body["agent_turns"]["judge"]["turns"] == 1

    # Settlement receipt — stub mode emits no tx_signature but binds
    # the verdict_hash and labels itself as ``stub`` so the buyer can
    # tell apart real vs. stub settlement on the same shape.
    receipt = body["settlement_receipt"]
    assert receipt["verdict_hash"] == _FULL_HASH
    assert receipt["facilitator"] == "stub"
    assert receipt["tx_signature"] is None
    assert receipt["settled_at"]


# ---------------------------------------------------------------------------
# 402 on bad / wrong-scope signatures.
# ---------------------------------------------------------------------------


def test_bad_signature_returns_402(patched_mongo: Any, stub_mode: None, client: TestClient) -> None:
    patched_mongo.insert_one(_seed_doc())

    resp = client.get(
        f"/v1/verdict/{_FULL_HASH}?detail=full",
        headers={"X-Payment": "totally-not-a-stub-signature"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert body["error"] == "payment_required"
    # Failure surfaced so the wallet UX can render diagnostic copy.
    assert "stub" in body["last_failure"].lower()


def test_wrong_scope_returns_402(patched_mongo: Any, stub_mode: None, client: TestClient) -> None:
    """Signature for verdict B must NOT satisfy the paywall on verdict A.

    Pattern C-shaped guard: even in stub mode the scope binding is
    enforced so a leaked stub token can't unlock arbitrary verdicts.
    """
    patched_mongo.insert_one(_seed_doc(verdict_hash=_FULL_HASH))
    patched_mongo.insert_one(_seed_doc(verdict_hash=_OTHER_HASH))

    # Signed for _OTHER_HASH, requesting _FULL_HASH.
    resp = client.get(
        f"/v1/verdict/{_FULL_HASH}?detail=full",
        headers={"X-Payment": f"stub:{_OTHER_HASH}:nonce-1"},
    )
    assert resp.status_code == 402
    body = resp.json()
    assert "scope mismatch" in body["last_failure"].lower()
    # Challenge re-issued for the *requested* hash, not the signed one.
    assert body["x402_challenge"]["scope"] == f"verdict:{_FULL_HASH}"


def test_empty_x_payment_returns_402(
    patched_mongo: Any, stub_mode: None, client: TestClient
) -> None:
    patched_mongo.insert_one(_seed_doc())

    resp = client.get(
        f"/v1/verdict/{_FULL_HASH}?detail=full",
        headers={"X-Payment": ""},
    )
    # Empty header is treated as "no payment present" → fresh 402, no
    # ``last_failure`` (the buyer never attempted a settlement).
    assert resp.status_code == 402
    assert "last_failure" not in resp.json()


# ---------------------------------------------------------------------------
# Path-segment redirect (`/detail` → `?detail=full`).
# ---------------------------------------------------------------------------


def test_detail_path_redirects_to_query_form(
    patched_mongo: Any, stub_mode: None, client: TestClient
) -> None:
    patched_mongo.insert_one(_seed_doc())

    resp = client.get(
        f"/v1/verdict/{_FULL_HASH}/detail",
        follow_redirects=False,
    )
    assert resp.status_code == 308
    assert resp.headers["location"] == f"/v1/verdict/{_FULL_HASH}?detail=full"


# ---------------------------------------------------------------------------
# Live-mode gate — defence-in-depth.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_verifier_refuses_without_env_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``verify_verdict_payment(..., mode='live')`` must refuse to run
    when ``X402_VERDICT_SETTLE_LIVE`` is unset, even if the caller
    asks for live mode directly.

    This is the defence-in-depth check: the route layer collapses to
    stub when the env flag is off, but a unit test or external caller
    that constructs the verifier directly must hit the same gate.
    """
    from gecko_core.payments.verdict_settle import (
        VerdictPaywallNotLiveError,
        verify_verdict_payment,
    )

    monkeypatch.delenv("X402_VERDICT_SETTLE_LIVE", raising=False)

    with pytest.raises(VerdictPaywallNotLiveError):
        await verify_verdict_payment(
            "stub:" + _FULL_HASH + ":nonce",
            verdict_hash=_FULL_HASH,
            mode="live",
        )


def test_resolve_mode_collapses_to_stub_without_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Either gate off → mode collapses to ``stub``."""
    from gecko_core.payments.verdict_settle import resolve_verdict_settle_mode

    # X402_MODE=live + flag unset → stub.
    monkeypatch.setenv("X402_MODE", "live")
    monkeypatch.delenv("X402_VERDICT_SETTLE_LIVE", raising=False)
    assert resolve_verdict_settle_mode() == "stub"

    # X402_MODE=stub + flag set → still stub (the global gate wins).
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.setenv("X402_VERDICT_SETTLE_LIVE", "1")
    assert resolve_verdict_settle_mode() == "stub"

    # Both gates on → live.
    monkeypatch.setenv("X402_MODE", "live")
    monkeypatch.setenv("X402_VERDICT_SETTLE_LIVE", "1")
    assert resolve_verdict_settle_mode() == "live"
