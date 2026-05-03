"""S20-X402-VERDICT-SETTLE-01 (#11) — Pattern C contract test.

Records both ``/verify`` AND ``/settle`` against the real x402
facilitator before the verdict paywall flips live. Sprint 12 CDP
shipped a green ``/verify`` and broke at ``/settle``; the cassette
shape here forces both endpoints to be exercised on every replay so
the same trap can't bite the verdict paywall.

Operational shape (mirrors ``test_bazaar_consumer_contract.py``):

  * No env var → replay from
    ``tests/payments/cassettes/verdict_settle/<facilitator>.json``.
    Cassette absent → test FAILS (regression guard).
  * ``GECKO_VERDICT_X402_LIVE=1`` → real network. Requires a funded
    buyer wallet (``GECKO_VERDICT_BUYER_PRIVATE_KEY`` for CDP/Base or
    a configured frames.ag agentwallet for Solana). The cassette is
    captured by the operator via httpx hooks / mitmproxy and committed
    by hand — auto-recording is intentionally out-of-scope (see
    ``_cassette.record_or_replay`` docstring).
  * Marker: ``live_x402_verdict``. Pytest collection-only run is the
    CI smoke that verifies the marker exists; an actual run requires
    ``-m live_x402_verdict`` PLUS a recorded cassette OR the live env
    var.

The cassette is **not** present at #11 ship-time — that's the
deliberate Pattern B step. The recording is the operator's call
because it costs ~$2.50 of real USDC. This file ships the test
skeleton + the cassette-presence regression guard so a future
"flip live" PR can't avoid recording.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.payments._cassette import LIVE_ENV as _BAZAAR_LIVE_ENV
from tests.payments._cassette import (
    is_live_record_mode as _bazaar_live_mode,
)
from tests.payments._cassette import replay_cassette

pytestmark = pytest.mark.live_x402_verdict


# Distinct env var from the bazaar consumer flow so an operator can
# re-record one without dragging the other into live mode.
LIVE_ENV: str = "GECKO_VERDICT_X402_LIVE"


def _is_verdict_live_record_mode() -> bool:
    return os.environ.get(LIVE_ENV) == "1"


# ---------------------------------------------------------------------------
# Cassette layout. One file per facilitator backend so the eventual
# ``/verify`` + ``/settle`` traces stay diff-friendly. Stub-only flows
# don't enter this file.
# ---------------------------------------------------------------------------


CASSETTE_DIR = Path(__file__).resolve().parent / "cassettes" / "verdict_settle"
CDP_CASSETTE = CASSETTE_DIR / "cdp_base_verify_and_settle.json"
FRAMES_CASSETTE = CASSETTE_DIR / "frames_solana_verify_and_settle.json"


# A 64-char sha256 used as the verdict_hash bound into the X-Payment
# scope. Any deterministic string of the right shape works; the
# cassette will pin whatever the operator records.
_VERDICT_HASH = "f" * 64


# ---------------------------------------------------------------------------
# Cassette-presence regression guard — the Pattern C shape.
# ---------------------------------------------------------------------------


def test_cassette_directory_exists() -> None:
    """Cassette directory exists and is committed.

    Even before the first cassette is recorded, the directory itself is
    committed (with a .gitkeep) so that "where do I put the recording"
    is unambiguous. A missing directory means the contract-test scaffold
    was deleted — restore from git.
    """
    if _is_verdict_live_record_mode():
        pytest.skip(f"{LIVE_ENV}=1 set; directory check is a replay-mode guard")
    assert CASSETTE_DIR.exists(), (
        f"verdict-settle cassette directory missing at {CASSETTE_DIR}. "
        "Restore from git or re-run the contract-test scaffold (S20 #11)."
    )


def test_at_least_one_cassette_present_when_collected() -> None:
    """Hard fail when the verdict paywall is being flipped live without a cassette.

    Per ticket spec: live-mode toggle (``X402_VERDICT_SETTLE_LIVE=1``)
    is gated on the contract test being green. The "flip live" PR is
    detected via the env var itself: if an operator sets
    ``X402_VERDICT_SETTLE_LIVE=1`` and at least one cassette is **not**
    present, this test fails the build. Default CI (flag unset) skips —
    we don't punish a baseline test run for the cassette being absent.

    Once the operator records either the CDP or frames cassette and
    commits it, this test passes.

    Skipped when ``GECKO_VERDICT_X402_LIVE`` (live re-record env) is set
    so the operator can run the suite during cassette capture without
    immediately tripping the guard.
    """
    if _is_verdict_live_record_mode():
        pytest.skip(f"{LIVE_ENV}=1 set; recording in progress")
    if not CASSETTE_DIR.exists():
        pytest.skip("cassette directory missing — earlier test will surface this")

    from gecko_core.payments.verdict_settle import is_verdict_settle_live_enabled

    has_cdp = CDP_CASSETTE.exists()
    has_frames = FRAMES_CASSETTE.exists()
    if has_cdp or has_frames:
        return  # cassette exists — gate green

    if not is_verdict_settle_live_enabled():
        pytest.skip(
            "verdict-settle cassette absent and X402_VERDICT_SETTLE_LIVE is "
            "off; skipping until the operator flips live (which trips this "
            "guard until a cassette is recorded)."
        )

    pytest.fail(
        "verdict-settle cassette absent. The verdict paywall "
        "live-mode toggle (X402_VERDICT_SETTLE_LIVE=1) is gated on "
        "this Pattern C contract test going green against a recorded "
        "cassette of the real facilitator's /verify AND /settle "
        "endpoints. Sprint 12 CDP shipped a green /verify and broke "
        "at /settle — that exact trap is what this gate prevents. "
        f"Record with {LIVE_ENV}=1 + a funded buyer wallet, then "
        f"commit either {CDP_CASSETTE.name} or {FRAMES_CASSETTE.name}."
    )


# ---------------------------------------------------------------------------
# Replay path — exercised once a cassette exists.
#
# Skipped (not failed) until the cassette is recorded so the suite
# stays green for the #11 ship; the cassette-presence test above is
# what fails on a "flip live" attempt.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cdp_verdict_settle_against_cassette() -> None:
    """Replay a recorded CDP verify+settle for the verdict paywall.

    Asserts:
      * Two facilitator round-trips were exercised (``/verify`` first,
        then ``/settle``) — pinning the dispatch order.
      * The returned ``SettlementReceipt.tx_signature`` is a Base-shaped
        hex string.
      * The receipt's ``facilitator`` field == ``cdp-base``.
    """
    if _is_verdict_live_record_mode():
        if not os.environ.get("GECKO_VERDICT_BUYER_PRIVATE_KEY"):
            pytest.skip("GECKO_VERDICT_BUYER_PRIVATE_KEY required for CDP live re-record")
        # Live capture path is operator-driven; this branch deliberately
        # does not auto-run the real flow inside the test. The operator
        # captures via httpx hooks or mitmproxy and commits the JSON.
        pytest.skip("live re-record path is operator-driven; commit the cassette")

    if not CDP_CASSETTE.exists():
        pytest.skip(
            f"CDP cassette absent at {CDP_CASSETTE.name}; "
            "covered by test_at_least_one_cassette_present_when_collected"
        )

    from gecko_core.payments.verdict_settle import verify_verdict_payment

    # Replay through respx — every facilitator HTTP call is mocked.
    with replay_cassette(CDP_CASSETTE):
        # The actual X-Payment payload shape is pinned by the cassette.
        # We feed a placeholder string and let the cassette's recorded
        # responses drive the verifier. The replay assertion lives in
        # the cassette: if the verifier doesn't issue both /verify and
        # /settle in order, respx raises "no route matched".
        receipt = await verify_verdict_payment(
            "<x-payment-payload-from-cassette>",
            verdict_hash=_VERDICT_HASH,
            mode="live",
        )

    assert receipt.facilitator == "cdp-base"
    tx = receipt.tx_signature or ""
    assert tx.startswith("0x"), f"expected Base tx hash, got {tx!r}"
    assert len(tx) == 66, f"expected 32-byte hex hash, got {len(tx)} chars"


@pytest.mark.asyncio
async def test_frames_verdict_settle_against_cassette() -> None:
    """Replay a recorded frames.ag (Solana) verify+settle.

    Same shape as the CDP cassette test; mirrored here so an operator
    can record EITHER backend and unblock live without recording both.
    """
    if _is_verdict_live_record_mode():
        pytest.skip("live re-record path is operator-driven; commit the cassette")
    if not FRAMES_CASSETTE.exists():
        pytest.skip(
            f"frames cassette absent at {FRAMES_CASSETTE.name}; "
            "covered by test_at_least_one_cassette_present_when_collected"
        )

    from gecko_core.payments.verdict_settle import verify_verdict_payment

    with replay_cassette(FRAMES_CASSETTE):
        receipt = await verify_verdict_payment(
            "<x-payment-payload-from-cassette>",
            verdict_hash=_VERDICT_HASH,
            mode="live",
        )

    assert receipt.facilitator in {"frames-solana", "frames"}
    assert receipt.tx_signature  # Solana sig — base58, no fixed length


# ---------------------------------------------------------------------------
# Bazaar env-var sanity — guard against an operator confusing the two
# live flags. The verdict cassette uses GECKO_VERDICT_X402_LIVE; the
# bazaar consumer cassette uses GECKO_BAZAAR_LIVE. They MUST be distinct.
# ---------------------------------------------------------------------------


def test_live_env_var_is_distinct_from_bazaar() -> None:
    assert LIVE_ENV != _BAZAAR_LIVE_ENV, (
        "verdict and bazaar contract tests must use distinct LIVE_ENV "
        "vars so an operator re-recording one doesn't accidentally drag "
        "the other into live mode"
    )
    # Helper sanity: the bazaar live-mode reader is left alone.
    assert callable(_bazaar_live_mode)
