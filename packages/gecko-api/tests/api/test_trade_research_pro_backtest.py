"""Issue #14 — pro tier must include a `backtest` field absent from basic.

Last week's dogfood verified that POST /trade_research and
POST /trade_research/pro returned structurally identical envelopes —
same top-level keys, same 7-agent panel, same shape. Buyers paid 3x
for +1 cite. P0.

Phase 10A always intended a `backtest` payload on the pro envelope
(schema lives at
``gecko_core.orchestration.trade_panel.backtest.models.BacktestReport``)
but two divergence points were missed:

1. The pro handler never passed ``enable_backtest=True`` into
   ``run_trade_panel_with_retrieval``.
2. ``TradeResearchResponse`` had no ``backtest`` field, so even when the
   panel produced one, it was silently dropped on serialization.

This test fires both tiers against the same idea/protocol with the
shared stub-mode payment header and asserts:

- ``pro.keys() != basic.keys()``  (envelopes are not identical)
- ``backtest`` is present and non-null on pro
- ``backtest`` is absent from basic (response_model_exclude_none=True)

Mocks ``run_trade_panel_with_retrieval`` so this never fires AG2,
CoinGecko, or Mongo.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from collections.abc import Iterator
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")


def _decode_payment_required_header(value: str) -> dict:
    return json.loads(base64.b64decode(value).decode("utf-8"))


def _build_payment_payload_header(accepts_entry: dict) -> str:
    payload_obj = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    return base64.b64encode(json.dumps(payload_obj).encode("utf-8")).decode("utf-8")


def _paid_post(client: TestClient, *, path: str, body: dict) -> tuple[int, dict]:
    r0 = client.post(path, json=body)
    assert r0.status_code == 402, r0.text
    accepts_entry = _decode_payment_required_header(r0.headers["payment-required"])["accepts"][0]
    payment_header = _build_payment_payload_header(accepts_entry)
    r = client.post(path, json=body, headers={"PAYMENT-SIGNATURE": payment_header})
    out: dict = {}
    try:
        out = r.json()
    except Exception:
        out = {}
    return r.status_code, out


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Patch run_trade_panel_with_retrieval; basic returns no backtest, pro returns one.

    The fake mirrors what the real wrapper does in
    ``run_trade_panel_with_retrieval`` — when ``enable_backtest`` is
    truthy, attach a :class:`BacktestReport`; otherwise leave it None.
    """
    os.environ["X402_NETWORK"] = "solana-devnet"
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)

    from gecko_api.main import app
    from gecko_core.orchestration.trade_panel import TradePanelTurn, TradePanelVerdict
    from gecko_core.orchestration.trade_panel.backtest import BacktestReport

    base_turns = [
        TradePanelTurn(
            agent="technical_analyst",
            content="bullish trend",
            parsed_verdict={"trend_verdict": "bullish"},
        ),
        TradePanelTurn(
            agent="coordinator",
            content='```json\n{"verdict": "act"}\n```',
            parsed_verdict={"verdict": "act"},
        ),
    ]

    async def fake_panel(
        *,
        idea: str,
        protocol: str,
        vertical: str = "dex",
        tier: str = "basic",
        top_k: int = 15,
        llm_config: dict | None = None,
        agent_factory: object | None = None,
        enable_backtest: bool = False,
        history_source: object | None = None,
    ) -> TradePanelVerdict:
        verdict = TradePanelVerdict(
            verdict="act",
            confidence=0.7,
            key_drivers=["technical alignment"],
            dissent_count=0,
            blocker_questions=[],
            turns=base_turns,
        )
        if enable_backtest:
            report = BacktestReport(
                pnl_pct=4.2,
                drawdown_pct=1.1,
                n_similar_setups=1,
                hit_rate=1.0,
                source="coingecko",
                unbacktestable=False,
            )
            verdict = verdict.model_copy(update={"backtest": report})
        return verdict

    with (
        patch(
            "gecko_core.orchestration.trade_panel.run_trade_panel_with_retrieval",
            new=AsyncMock(side_effect=fake_panel),
        ),
        TestClient(app) as c,
    ):
        yield c


_BODY = {"idea": "Should I open a JTO long around the next FOMC?", "protocol": "jito"}


def test_pro_envelope_carries_backtest_basic_does_not(client: TestClient) -> None:
    """The AC test from issue #14: pro and basic must differ on the wire."""
    basic_status, basic_body = _paid_post(client, path="/trade_research", body=_BODY)
    pro_status, pro_body = _paid_post(client, path="/trade_research/pro", body=_BODY)

    assert basic_status == 200, basic_body
    assert pro_status == 200, pro_body

    # AC #1: envelopes must differ at the top-level key set.
    assert set(pro_body.keys()) != set(basic_body.keys()), (
        f"pro and basic returned identical keys — issue #14 regression.\n"
        f"basic={sorted(basic_body.keys())!r}\n"
        f"pro={sorted(pro_body.keys())!r}"
    )

    # AC #2: backtest is present and non-null on pro.
    assert "backtest" in pro_body, f"pro envelope missing 'backtest': keys={sorted(pro_body)!r}"
    bt = pro_body["backtest"]
    assert bt is not None, "pro 'backtest' is null"
    assert isinstance(bt, dict)
    # The shape contract from BacktestReport — at minimum these keys must
    # be carried so callers can render either real PnL or the
    # unbacktestable degradation banner.
    for required in ("pnl_pct", "drawdown_pct", "source", "unbacktestable"):
        assert required in bt, f"backtest missing key {required!r}: {bt!r}"

    # AC #3: backtest stays off the basic envelope.
    assert "backtest" not in basic_body, (
        f"basic envelope leaked 'backtest': {basic_body['backtest']!r}"
    )


def test_pro_envelope_carries_unbacktestable_when_history_unavailable(
    client: TestClient,
) -> None:
    """Even when CoinGecko has no data, pro MUST still return a verdict.

    The ``unbacktestable=True`` + ``reason`` shape is the documented
    graceful-degradation contract from
    ``gecko_core.orchestration.trade_panel.backtest.models.BacktestReport``.
    The pro handler synthesizes this shape when the upstream backtest
    didn't run (e.g. strategist turn produced no parseable intent), so
    the pro wire envelope is observably different from basic regardless.
    """
    from gecko_core.orchestration.trade_panel import TradePanelTurn, TradePanelVerdict

    fallback_verdict = TradePanelVerdict(
        verdict="defer",
        confidence=0.4,
        key_drivers=[],
        dissent_count=0,
        blocker_questions=["uncertain"],
        turns=[
            TradePanelTurn(
                agent="coordinator", content="defer", parsed_verdict={"verdict": "defer"}
            ),
        ],
        # Note: no `backtest` attached — simulates the case where
        # backtest_intent silently failed or the strategist intent was
        # missing.
    )

    with patch(
        "gecko_core.orchestration.trade_panel.run_trade_panel_with_retrieval",
        new=AsyncMock(return_value=fallback_verdict),
    ):
        status, body = _paid_post(client, path="/trade_research/pro", body=_BODY)

    assert status == 200, body
    assert body["verdict"] == "defer"
    assert body.get("backtest") is not None, "pro must always carry a backtest payload"
    assert body["backtest"].get("unbacktestable") is True
    assert body["backtest"].get("reason"), "unbacktestable backtest must carry a reason token"
