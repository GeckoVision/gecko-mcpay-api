"""S14-PARA-02 — Creator payout settlement on cite.

When a Paragraph-sourced chunk lands in the verdict's RAG context (cite
carries `creator_handle` + `creator_wallet`), Gecko fires a small payout
to the creator's wallet via the X402Client Protocol seam. Default
$0.005/cite, configurable via `CREATOR_PAYOUT_PER_CITE`. Stub mode
simulates; live mode lands on Base mainnet via CDP.

Test surfaces:
  1. Env reader (`resolve_per_cite_amount_usd`) — default + override +
     garbage fallback.
  2. Eligibility — only Paragraph-provenanced cites with a wallet are
     eligible; Tavily/free cites pass through unchanged.
  3. Aggregation — multiple cites for same (handle, wallet) batch into
     one settle call with summed amount.
  4. Stub mode — `settle_creator_payouts` populates
     `creator_payout_usd` + `Provenance.payment` receipt on each
     eligible cite without making a real charge (uses StubX402Client).
  5. CDP mock — fixture-mocked CDPX402Client returns a tx hash; the
     receipt threads through to `Provenance.payment.tx_signature`.
  6. `bb economics` line items — `aggregate_creator_payouts` emits
     `cost_creator_usd` totals grouped by handle.
  7. Failure policy — facilitator exception leaves the cite in the
     report with `creator_payout_usd=None` (no halt).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from gecko_core.models import Citation, Provenance
from gecko_core.payments.creator_payout import (
    DEFAULT_PER_CITE_USD,
    aggregate_creator_payouts,
    resolve_per_cite_amount_usd,
    settle_creator_payouts,
)
from gecko_core.payments.models import PaymentIntent, PaymentResult
from gecko_core.payments.x402_client import StubX402Client

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _paragraph_cite(
    *, handle: str, wallet: str = "0xCreator0000000000000000000000000000Author"
) -> Citation:
    return Citation(
        source_url="https://paragraph.xyz/@author/post-1",  # type: ignore[arg-type]
        chunk_index=0,
        similarity=0.9,
        provenance=Provenance(provider_name="paragraph", provider_kind="x402-bazaar"),
        creator_handle=handle,
        creator_wallet=wallet,
    )


def _tavily_cite() -> Citation:
    return Citation(
        source_url="https://example.com/article",  # type: ignore[arg-type]
        chunk_index=0,
        similarity=0.8,
        provenance=Provenance(provider_name="tavily", provider_kind="free"),
    )


# ---------------------------------------------------------------------------
# resolve_per_cite_amount_usd — env reader
# ---------------------------------------------------------------------------


def test_resolve_per_cite_amount_default_when_unset() -> None:
    assert resolve_per_cite_amount_usd({}) == DEFAULT_PER_CITE_USD


def test_resolve_per_cite_amount_override() -> None:
    assert resolve_per_cite_amount_usd({"CREATOR_PAYOUT_PER_CITE": "0.02"}) == Decimal("0.02")


def test_resolve_per_cite_amount_garbage_falls_back() -> None:
    assert resolve_per_cite_amount_usd({"CREATOR_PAYOUT_PER_CITE": "abc"}) == DEFAULT_PER_CITE_USD


def test_resolve_per_cite_amount_zero_falls_back() -> None:
    assert resolve_per_cite_amount_usd({"CREATOR_PAYOUT_PER_CITE": "0"}) == DEFAULT_PER_CITE_USD


# ---------------------------------------------------------------------------
# Stub mode — populate fields, no real charge
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_settle_paragraph_cites_with_stub_client() -> None:
    session_id = uuid4()
    cites = [
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author1"),  # second cite — same author batches
        _paragraph_cite(handle="@author2", wallet="0xOtherAuthor000000000000000000000000Bytes"),
        _tavily_cite(),  # ineligible — no creator info
    ]

    updated = await settle_creator_payouts(
        session_id=session_id,
        citations=cites,
        client=StubX402Client(),
        per_cite_usd=Decimal("0.005"),
    )

    # Eligible cites get the per-cite amount + a payment receipt.
    assert updated[0].creator_payout_usd == 0.005
    assert updated[0].provenance.payment is not None
    assert updated[0].provenance.payment["status"] == "success"
    assert updated[1].creator_payout_usd == 0.005
    assert updated[2].creator_payout_usd == 0.005
    # Tavily cite is untouched.
    assert updated[3].creator_payout_usd is None
    assert updated[3].provenance.payment is None


@pytest.mark.asyncio
async def test_settle_returns_input_when_no_paragraph_cites() -> None:
    session_id = uuid4()
    cites = [_tavily_cite(), _tavily_cite()]
    updated = await settle_creator_payouts(
        session_id=session_id, citations=cites, client=StubX402Client()
    )
    assert updated == cites


@pytest.mark.asyncio
async def test_settle_skips_cites_without_wallet() -> None:
    """Handle alone isn't enough — without a wallet there's nothing to settle."""
    session_id = uuid4()
    cite = Citation(
        source_url="https://paragraph.xyz/@nowallet/post",  # type: ignore[arg-type]
        chunk_index=0,
        similarity=0.7,
        provenance=Provenance(provider_name="paragraph", provider_kind="x402-bazaar"),
        creator_handle="@nowallet",
        creator_wallet=None,
    )
    updated = await settle_creator_payouts(
        session_id=session_id, citations=[cite], client=StubX402Client()
    )
    assert updated[0].creator_payout_usd is None


# ---------------------------------------------------------------------------
# Aggregation — same author batches into a single settle
# ---------------------------------------------------------------------------


@dataclass
class _RecordingClient:
    """Records every charge() arg + returns success with a deterministic tx."""

    facilitator_id: str = "stub"
    supported_networks: tuple[str, ...] = ()
    calls: list[PaymentIntent] = field(default_factory=list)

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        self.calls.append(intent)
        return PaymentResult(
            intent_id=intent.intent_id,
            status="success",
            tx_signature=f"0xtx-{len(self.calls)}",
            error=None,
        )

    async def verify(self, tx_signature: str) -> str:
        return "confirmed"


@pytest.mark.asyncio
async def test_settle_batches_cites_by_creator() -> None:
    """Three cites for @author1 (same wallet) → one settle for $0.015."""
    session_id = uuid4()
    cites = [
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author2", wallet="0xOther000000000000000000000000000000Bytes"),
    ]
    rec = _RecordingClient()
    await settle_creator_payouts(
        session_id=session_id,
        citations=cites,
        client=rec,
        per_cite_usd=Decimal("0.005"),
    )
    # 2 settle calls (one per unique author), not 4.
    assert len(rec.calls) == 2
    by_amount = sorted(c.amount_usd for c in rec.calls)
    assert by_amount[0] == Decimal("0.005")  # @author2 (1 cite)
    assert by_amount[1] == Decimal("0.015")  # @author1 (3 cites)


# ---------------------------------------------------------------------------
# CDP mock — receipt threads through to Provenance.payment
# ---------------------------------------------------------------------------


@dataclass
class _FakeSettleResponse:
    success: bool
    transaction: str = ""


@dataclass
class _FakeCDPFacilitator:
    response: _FakeSettleResponse
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def settle(self, payload: Any, requirements: Any) -> _FakeSettleResponse:
        self.calls.append({"payload": payload, "requirements": requirements})
        return self.response


@pytest.mark.asyncio
async def test_creator_payout_through_cdp_fixture_threads_tx_hash() -> None:
    """Mock the CDP facilitator end-to-end: the resulting tx hash lands
    on each cited Citation's Provenance.payment.tx_signature."""
    from gecko_core.payments.cdp_x402_client import (
        BASE_MAINNET_NETWORK_ID,
        CDPX402Client,
    )

    session_id = uuid4()
    fake = _FakeCDPFacilitator(_FakeSettleResponse(success=True, transaction="0xabc123"))
    client = CDPX402Client(
        facilitator=fake,
        treasury_address="0xC0FFEE0000000000000000000000000000000000",
        network=BASE_MAINNET_NETWORK_ID,
    )
    cites = [_paragraph_cite(handle="@author1"), _paragraph_cite(handle="@author1")]
    updated = await settle_creator_payouts(
        session_id=session_id,
        citations=cites,
        client=client,
        per_cite_usd=Decimal("0.005"),
    )

    assert len(fake.calls) == 1, "two cites for one author should batch to one CDP call"
    for cite in updated:
        assert cite.creator_payout_usd == 0.005
        assert cite.provenance.payment is not None
        assert cite.provenance.payment["tx_signature"] == "0xabc123"
        assert cite.provenance.payment["facilitator_id"] == "cdp-base"


# ---------------------------------------------------------------------------
# Failure policy — settle exception keeps cite in report without payout
# ---------------------------------------------------------------------------


@dataclass
class _ExplodingClient:
    facilitator_id: str = "stub"
    supported_networks: tuple[str, ...] = ()

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        raise RuntimeError("simulated facilitator outage")

    async def verify(self, tx_signature: str) -> str:
        return "unknown"


@pytest.mark.asyncio
async def test_settle_failure_keeps_cite_without_payout() -> None:
    session_id = uuid4()
    cites = [_paragraph_cite(handle="@author1"), _tavily_cite()]
    updated = await settle_creator_payouts(
        session_id=session_id,
        citations=cites,
        client=_ExplodingClient(),
    )
    # Paragraph cite stays in the report with no payout; Tavily untouched.
    assert updated[0].creator_payout_usd is None
    assert updated[0].provenance.payment is None
    assert updated[0].creator_handle == "@author1"
    assert updated[1] == cites[1]


# ---------------------------------------------------------------------------
# Aggregation for `bb economics` line items
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_creator_payouts_groups_by_creator() -> None:
    """`bb economics` reads `cost_creator_usd` per handle from this aggregate."""
    session_id = uuid4()
    cites = [
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author1"),
        _paragraph_cite(handle="@author2", wallet="0xOther000000000000000000000000000000Bytes"),
    ]
    settled = await settle_creator_payouts(
        session_id=session_id,
        citations=cites,
        client=StubX402Client(),
        per_cite_usd=Decimal("0.005"),
    )

    agg = aggregate_creator_payouts(settled)
    assert agg["total_usd"] == Decimal("0.015")
    by_handle = {row["handle"]: row for row in agg["per_creator"]}
    assert by_handle["@author1"]["amount_usd"] == Decimal("0.010")
    assert by_handle["@author1"]["cite_count"] == 2
    assert by_handle["@author2"]["amount_usd"] == Decimal("0.005")
    assert by_handle["@author2"]["cite_count"] == 1


def test_aggregate_with_no_payouts_returns_zero_total() -> None:
    cites = [_tavily_cite()]
    agg = aggregate_creator_payouts(cites)
    assert agg["total_usd"] == Decimal("0")
    assert agg["per_creator"] == []
