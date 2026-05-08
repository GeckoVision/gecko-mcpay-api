"""Tests for the per-service x402 call-spec registry.

Light fakes only — see feedback_lighter_tests.md. We exercise the pure
matcher + body builders directly; no network, no httpx.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

# Load the spec module by file path — scripts/ isn't on sys.path by default.
# Same pattern as tests/scripts/trading_oracle/test_probe_service.py.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "trading_oracle" / "service_call_specs.py"
)
_spec = importlib.util.spec_from_file_location("trading_oracle_service_call_specs", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
specs_mod = importlib.util.module_from_spec(_spec)
sys.modules["trading_oracle_service_call_specs"] = specs_mod
_spec.loader.exec_module(specs_mod)

find_spec_for = specs_mod.find_spec_for


def test_finds_exa_spec() -> None:
    endpoints = [
        {"url": "https://api.exa.ai/contents", "method": "POST"},
        {"url": "https://api.exa.ai/search", "method": "POST"},
    ]
    spec, ep = find_spec_for("exa-ai", endpoints)
    assert spec is not None
    assert ep is not None
    assert ep["url"] == "https://api.exa.ai/search"
    assert spec.body_builder is not None
    body = spec.body_builder("hello", {})
    assert body is not None
    assert body["query"] == "hello"


def test_finds_chat_completions_for_venice() -> None:
    endpoints = [{"url": "https://api.venice.ai/api/v1/chat/completions", "method": "POST"}]
    spec, _ep = find_spec_for("docs-anthropic-com", endpoints)
    assert spec is not None
    assert spec.method == "POST"
    assert spec.body_builder is not None
    body = spec.body_builder("solana defi prompt", {})
    assert body is not None
    assert "messages" in body
    assert body["messages"][0]["content"] == "solana defi prompt"


def test_no_spec_returns_none_none() -> None:
    endpoints = [{"url": "https://random.example/foo", "method": "GET"}]
    spec, ep = find_spec_for("random-service", endpoints)
    assert spec is None and ep is None


def test_anthropic_messages_for_bankr() -> None:
    endpoints = [{"url": "https://llm.bankr.bot/v1/messages", "method": "POST"}]
    spec, _ep = find_spec_for("docs-anthropic-com", endpoints)
    assert spec is not None
    assert spec.body_builder is not None
    body = spec.body_builder("p", {})
    assert body is not None
    assert "max_tokens" in body


def test_coingecko_url_override_pins_solana_search_pools() -> None:
    """paysh CoinGecko: catalog URL is bare /x402/onchain (404). Spec must
    rewrite to /x402/onchain/search/pools with ?query=<protocol>&network=solana.
    Confirmed against pro-api.coingecko.com 2026-05-08 — 402 challenge."""
    spec, ep = find_spec_for(
        "paysponge/coingecko",
        [{"url": "https://pro-api.coingecko.com/api/v3/x402/onchain", "method": "GET"}],
    )
    assert spec is not None
    assert ep is not None
    assert spec.url_override is not None
    url = spec.url_override("ignored prompt", {"protocol": "kamino"})
    assert "x402/onchain/search/pools" in url
    assert "query=kamino" in url
    assert "network=solana" in url


def test_coingecko_url_override_default_network_solana() -> None:
    """Network defaults to solana when not in ctx — trading-oracle vertical."""
    spec, _ = find_spec_for(
        "paysponge/coingecko",
        [{"url": "https://pro-api.coingecko.com/api/v3/x402/onchain", "method": "GET"}],
    )
    assert spec is not None and spec.url_override is not None
    url = spec.url_override("p", {"protocol": "jupiter"})
    assert "network=solana" in url
    assert "query=jupiter" in url


def test_perplexity_url_override_targets_v1_sonar() -> None:
    """paysh Perplexity: catalog URL is bare host that 302s to paysponge's
    dashboard. Probe on 2026-05-08 confirmed POST /v1/sonar returns 402.
    Spec must rewrite to that path."""
    spec, _ = find_spec_for(
        "paysponge/perplexity",
        [{"url": "https://pplx.x402.paysponge.com", "method": "POST"}],
    )
    assert spec is not None
    assert spec.url_override is not None
    url = spec.url_override("test prompt", {"protocol": "drift"})
    assert "pplx.x402.paysponge.com" in url
    assert url.endswith("/v1/sonar")
    assert url != "https://pplx.x402.paysponge.com"  # must be a fuller path
    # Perplexity is POST chat-completions-shape — body builder must produce
    # a messages[] payload so the requester's POST branch fires.
    assert spec.method == "POST"
    assert spec.body_builder is not None
    body = spec.body_builder("hello sonar", {})
    assert body is not None
    assert body["messages"][0]["content"] == "hello sonar"


def test_callspec_url_override_default_none_keeps_legacy_path() -> None:
    """Existing specs (exa-ai, chat-completions, /messages) must NOT carry
    a url_override — preserves the legacy ep["url"] code path."""
    spec, _ = find_spec_for("exa-ai", [{"url": "https://api.exa.ai/search", "method": "POST"}])
    assert spec is not None
    assert spec.url_override is None


def test_venice_filter_routes_to_bankr_when_both_present() -> None:
    """When the run.py Venice blocklist filters out Venice URLs, the
    registry should route the call to a sibling endpoint (Bankr) instead.

    The blocklist lives in run.py, not in service_call_specs (the spec
    registry is intentionally hostname-agnostic). This test mirrors the
    filter and asserts find_spec_for picks Bankr.
    """
    # Load run.py's _is_blocked_endpoint_url via the same importlib path
    # the test module uses for service_call_specs — run.py imports
    # gecko_core which is fine in this env, but we only need the helper
    # so we replicate the (tiny, pure) substring check here to avoid the
    # heavy import. Keep this in sync with _VENICE_BLOCKLIST in run.py.
    _BLOCK = ("venice.ai",)

    def _blocked(url: str) -> bool:
        return any(host in url for host in _BLOCK)

    endpoints = [
        {"url": "https://api.venice.ai/api/v1/chat/completions", "method": "POST"},
        {"url": "https://llm.bankr.bot/v1/messages", "method": "POST"},
        {"url": "https://blockrun.ai/v1/chat/completions", "method": "POST"},
    ]
    filtered = [ep for ep in endpoints if not _blocked(ep["url"])]
    spec, ep = find_spec_for("docs-anthropic-com", filtered)
    assert spec is not None
    assert ep is not None
    assert "venice.ai" not in ep["url"]
    # Either Bankr (matches /messages spec) or BlockRun (matches
    # chat/completions spec) is acceptable — both are reachable via
    # standard x402 per-call.
    assert ep["url"] in {
        "https://llm.bankr.bot/v1/messages",
        "https://blockrun.ai/v1/chat/completions",
    }
