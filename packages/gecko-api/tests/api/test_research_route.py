"""V1 verdict-loop — session-gated POST /v1/research.

First-user validation surface: a signed-in user requests a Gecko verdict and the
web app renders pass/defer + surviving dissent + citations. This is the basic
($0.25 list-price) panel, but in X402_MODE=stub it runs free and returns the
verdict envelope unchanged.

CRITICAL: the real panel is 30-100s and spends LLM tokens. These tests NEVER run
it — `run_trade_panel_with_retrieval` is monkeypatched on the route module to an
async fake that returns a hand-built (but real-model) TradePanelVerdict. The whole
file must run in well under 2s with no network.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from gecko_api.routes._session import issue, user_id_for
from gecko_core.orchestration.trade_panel.models import (
    Citation,
    DissentEntry,
    TradePanelVerdict,
)

WALLET = "USERaddr1111111111111111111111111111111111"

# A real TradePanelVerdict so the response shape is validated by the same model
# the route serializes. verdict="defer" + one dissent + one citation exercises
# all three surfaces the web app renders.
_FAKE_VERDICT = TradePanelVerdict(
    verdict="defer",
    confidence=0.7,
    key_drivers=["liquidity thin", "regime unclear"],
    dissent_count=1,
    dissent=[
        DissentEntry(
            voice="technical_analyst",
            stance="oppose",
            verbatim="trend is intact on the 4h",
            on_topic="trend read",
        )
    ],
    evidence_citations=[
        Citation(
            id=1,
            source="paysh",
            url="https://example.com/chunk",
            chunk_id="deadbeef",
            provider_kind="paysh_live",
            freshness_tier="daily",
            snippet="cited evidence snippet",
        )
    ],
)


@pytest.fixture
def call_recorder() -> dict:
    return {}


@pytest.fixture
def client(monkeypatch, call_recorder) -> TestClient:
    from gecko_api.routes import research

    async def _fake_panel(*, idea, protocol, vertical, tier, **kwargs):
        # Record the args the route passed through so the test can assert the
        # request body reached the core function unchanged.
        call_recorder["idea"] = idea
        call_recorder["protocol"] = protocol
        call_recorder["vertical"] = vertical
        call_recorder["tier"] = tier
        call_recorder["kwargs"] = kwargs
        return _FAKE_VERDICT

    monkeypatch.setattr(research, "run_trade_panel_with_retrieval", _fake_panel)
    # Don't build a real LLM config (needs router env); the fake ignores it.
    monkeypatch.setattr(research, "_research_llm_config", lambda: {"_stub": True})

    from gecko_api.main import app

    return TestClient(app)


def _token(wallet: str = WALLET) -> str:
    return issue(user_id_for(wallet), wallet)


def _auth(wallet: str = WALLET) -> dict:
    return {"Authorization": f"Bearer {_token(wallet)}"}


def test_valid_session_returns_verdict_envelope(client, call_recorder):
    r = client.post(
        "/v1/research",
        headers=_auth(),
        json={"idea": "long WIF on the breakout", "protocol": "drift"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["verdict"] == "defer"
    assert j["confidence"] == 0.7
    # surviving dissent present and structured
    assert len(j["dissent"]) == 1
    assert j["dissent"][0]["voice"] == "technical_analyst"
    # citations present
    assert len(j["evidence_citations"]) == 1
    assert j["evidence_citations"][0]["source"] == "paysh"


def test_request_body_passes_through_to_core(client, call_recorder):
    r = client.post(
        "/v1/research",
        headers=_auth(),
        json={"idea": "long WIF on the breakout", "protocol": "drift"},
    )
    assert r.status_code == 200, r.text
    # the idea/protocol from the body reached the core function
    assert call_recorder["idea"] == "long WIF on the breakout"
    assert call_recorder["protocol"] == "drift"
    # vertical defaults to dex; tier defaults to basic (sync viability)
    assert call_recorder["vertical"] == "dex"
    assert call_recorder["tier"] == "basic"


def test_pro_tier_is_coerced_to_basic(client, call_recorder):
    # The route forces basic regardless of the request body — the pro panel
    # (80-100s) exceeds the sync HTTP timeout, so a caller can't trigger a 504.
    r = client.post(
        "/v1/research",
        headers=_auth(),
        json={
            "idea": "long WIF on the breakout",
            "protocol": "drift",
            "tier": "pro",
        },
    )
    assert r.status_code == 200, r.text
    # even though the body sent tier="pro", core was called with basic
    assert call_recorder["tier"] == "basic"


def test_missing_bearer_returns_401(client):
    r = client.post(
        "/v1/research",
        json={"idea": "long WIF on the breakout", "protocol": "drift"},
    )
    assert r.status_code == 401


def test_non_bearer_scheme_returns_401(client):
    r = client.post(
        "/v1/research",
        headers={"Authorization": "Basic abc123"},
        json={"idea": "long WIF on the breakout", "protocol": "drift"},
    )
    assert r.status_code == 401


def _first_option(cfg):
    accepts = cfg.accepts if isinstance(cfg.accepts, list) else [cfg.accepts]
    return accepts[0]


def test_v1_research_wired_into_x402_middleware_in_live():
    # Regression guard: routes absent from _routes_config bypass the payment
    # middleware entirely — the original hole let /v1/research run the
    # expensive panel FREE even in live mode. In live, POST /v1/research MUST
    # be registered at the same basic-tier price/payTo/network as the
    # /trade_research basic surface (same heavy 7-agent panel).
    from gecko_api.main import _build_routes, _settings

    live_settings = _settings.model_copy(update={"x402_mode": "live"})
    routes = _build_routes(live_settings)

    assert "POST /v1/research" in routes
    v1 = _first_option(routes["POST /v1/research"])
    basic = _first_option(routes["POST /trade_research"])
    assert v1.price == basic.price
    assert v1.pay_to == basic.pay_to
    assert v1.network == basic.network


def test_v1_research_free_in_stub():
    # Stub stays free for first-user validation: the route is NOT registered in
    # the payment middleware under X402_MODE=stub (mirrors /review + /scaffold),
    # so a plain valid-session call returns 200 + verdict with no 402 challenge.
    # The existing test_valid_session_returns_verdict_envelope already asserts
    # the 200 path; this asserts the *reason* it stays free.
    from gecko_api.main import _build_routes, _settings

    stub_settings = _settings.model_copy(update={"x402_mode": "stub"})
    routes = _build_routes(stub_settings)
    assert "POST /v1/research" not in routes
