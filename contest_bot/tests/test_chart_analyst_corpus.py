"""Corpus-lens wiring tests for chart_analyst (S40 lab #6).

We test the *seam* — does the voice call ``retrieve_trade_corpus_chunks``,
does its return shape land in the user prompt, and does the voice degrade
gracefully when retrieval fails. We do NOT exercise real Mongo, real
OpenRouter, or the actual ``gecko_core`` retrieval logic.

Light fakes per ``feedback_lighter_tests``: monkeypatch the corpus
retrieval function, MockTransport the OpenRouter HTTP call, capture the
user prompt off the request body.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from llm_client import OpenRouterClient  # noqa: E402
from local_memory import LocalMemory  # noqa: E402
from voices import chart_analyst as chart_analyst_mod  # noqa: E402
from voices.chart_analyst import ChartAnalystVoice  # noqa: E402


# ── Helpers ───────────────────────────────────────────────────────────
class _PromptCapture:
    """Holds the last user-prompt string the OpenRouter handler observed."""

    def __init__(self) -> None:
        self.user_prompt: str | None = None
        self.calls: int = 0


def _make_or_client(handler: Any) -> OpenRouterClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return OpenRouterClient(api_key="sk-test", http_client=http_client)


def _make_response(content: str, cost: float = 0.00012) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "openai/gpt-4o-mini",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 250,
                "completion_tokens": 80,
                "cost": cost,
            },
        },
    )


def _capturing_handler(
    capture: _PromptCapture,
    content: str,
) -> Any:
    def handler(request: httpx.Request) -> httpx.Response:
        capture.calls += 1
        body = json.loads(request.content.decode("utf-8"))
        for msg in body.get("messages", []):
            if msg.get("role") == "user":
                capture.user_prompt = msg.get("content", "")
        return _make_response(content)

    return handler


def _healthy_market_state(**overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "instrument": "JTO",
        "symbol": "JTO-USDC",
        "spot_price": 2.50,
        "change_1h_pct": 0.5,
        "change_24h_pct": 3.2,
        "range_24h_pct": 4.5,
        "volume_24h": 5_000_000.0,
        "ohlcv_5m": [
            {
                "ts": f"2026-05-20T12:{i:02d}:00Z",
                "open": 2.40 + i * 0.001,
                "high": 2.42 + i * 0.001,
                "low": 2.39 + i * 0.001,
                "close": 2.41 + i * 0.001,
                "volume": 12_000.0 + i * 100,
            }
            for i in range(30)
        ],
    }
    state.update(overrides)
    return state


_LLM_BULLISH = json.dumps(
    {
        "verdict": "bullish",
        "confidence": 0.7,
        "reasoning": "trend up + breakout w/ vol",
        "observations": ["6-bar trend up", "vol > 6-bar median"],
    }
)


def _install_mongo_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wire MONGO_URI so the corpus path is taken."""
    monkeypatch.setenv("MONGO_URI", "mongodb://fake-for-tests/")


def _patch_retrieval(
    monkeypatch: pytest.MonkeyPatch,
    *,
    returns: Any = None,
    raises: type[BaseException] | None = None,
    spy: list[dict[str, Any]] | None = None,
) -> None:
    """Replace ``retrieve_trade_corpus_chunks`` with an async stub.

    Importing ``gecko_core.orchestration.trade_panel`` happens lazily inside
    the voice, so we ensure a fake module is on ``sys.modules`` before the
    voice runs. This keeps tests independent of ``gecko_core`` import
    availability.
    """

    async def fake(
        *,
        idea: str,
        protocol: str,
        vertical: str = "dex",
        top_k: int = 5,
        as_of_date: str | None = None,
        as_of: Any = None,
    ) -> list[dict[str, Any]]:
        if spy is not None:
            spy.append(
                {
                    "idea": idea,
                    "protocol": protocol,
                    "vertical": vertical,
                    "top_k": top_k,
                }
            )
        if raises is not None:
            raise raises("retrieval failed")
        return list(returns or [])

    import types

    pkg_name = "gecko_core.orchestration.trade_panel"
    fake_mod = types.ModuleType(pkg_name)
    fake_mod.retrieve_trade_corpus_chunks = fake  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, pkg_name, fake_mod)
    # Parents need to exist so ``from x.y.z import ...`` resolves.
    for parent in ("gecko_core", "gecko_core.orchestration"):
        if parent not in sys.modules:
            monkeypatch.setitem(sys.modules, parent, types.ModuleType(parent))


# ── Tests ─────────────────────────────────────────────────────────────


def test_corpus_chunks_land_in_prompt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mongo_env(monkeypatch)
    chunks = [
        {
            "provider_kind": "canon_marks",
            "source": "oaktree.com",
            "text": "An above-market yield is the market quoting you a priced risk.",
        },
        {
            "provider_kind": "protocol_native",
            "source": "api.kamino.finance",
            "text": "Pool utilization above 80% historically precedes drawdowns.",
        },
        {
            "provider_kind": "canon_damodaran",
            "source": "pages.stern.nyu.edu",
            "text": "Discount rates rise with perceived risk; ignore that and you mis-price.",
        },
    ]
    _patch_retrieval(monkeypatch, returns=chunks)

    capture = _PromptCapture()
    client = _make_or_client(_capturing_handler(capture, _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_lens.jsonl")

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert capture.user_prompt is not None
    assert "Corpus lens" in capture.user_prompt
    assert "oaktree.com" in capture.user_prompt
    assert "api.kamino.finance" in capture.user_prompt
    assert "pages.stern.nyu.edu" in capture.user_prompt
    # Observation line records what was consulted.
    assert any(o.startswith("corpus: 3 chunks") for o in op.observations)
    client.aclose()


def test_corpus_retrieval_failure_degrades_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mongo_env(monkeypatch)
    _patch_retrieval(monkeypatch, raises=RuntimeError)

    capture = _PromptCapture()
    client = _make_or_client(_capturing_handler(capture, _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_fail.jsonl")

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert op.verdict == "bullish"
    assert op.confidence == pytest.approx(0.7)
    assert capture.user_prompt is not None
    assert "Corpus lens" not in capture.user_prompt
    # No corpus observation emitted on retrieval failure.
    assert not any(o.startswith("corpus:") for o in op.observations)
    client.aclose()


def test_corpus_empty_result_is_silent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mongo_env(monkeypatch)
    _patch_retrieval(monkeypatch, returns=[])

    capture = _PromptCapture()
    client = _make_or_client(_capturing_handler(capture, _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_empty.jsonl")

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert capture.user_prompt is not None
    assert "Corpus lens" not in capture.user_prompt
    assert "--- End corpus lens ---" not in capture.user_prompt
    assert not any(o.startswith("corpus:") for o in op.observations)
    client.aclose()


def test_corpus_enabled_false_skips_retrieval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_mongo_env(monkeypatch)
    spy: list[dict[str, Any]] = []
    _patch_retrieval(monkeypatch, returns=[{"text": "x"}], spy=spy)

    capture = _PromptCapture()
    client = _make_or_client(_capturing_handler(capture, _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client, corpus_enabled=False)
    mem = LocalMemory(path=tmp_path / "corpus_disabled.jsonl")

    asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert spy == [], "retrieval must NOT be called when corpus_enabled=False"
    assert capture.user_prompt is not None
    assert "Corpus lens" not in capture.user_prompt
    client.aclose()


def test_corpus_skipped_when_mongo_uri_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No MONGO_URI in env → retrieval is not attempted."""
    monkeypatch.delenv("MONGO_URI", raising=False)
    spy: list[dict[str, Any]] = []
    _patch_retrieval(monkeypatch, returns=[{"text": "x"}], spy=spy)

    capture = _PromptCapture()
    client = _make_or_client(_capturing_handler(capture, _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_no_mongo.jsonl")

    asyncio.run(voice.grade(_healthy_market_state(), mem))

    assert spy == []
    assert capture.user_prompt is not None
    assert "Corpus lens" not in capture.user_prompt
    client.aclose()


def test_observations_include_corpus_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _install_mongo_env(monkeypatch)
    chunks = [
        {"provider_kind": "canon_marks", "source": "oaktree.com", "text": "a"},
        {
            "provider_kind": "protocol_native",
            "source": "kamino.finance",
            "text": "b",
        },
        {"provider_kind": "canon_marks", "source": "oaktree.com", "text": "c"},
    ]
    _patch_retrieval(monkeypatch, returns=chunks)

    client = _make_or_client(_capturing_handler(_PromptCapture(), _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_obs.jsonl")

    op = asyncio.run(voice.grade(_healthy_market_state(), mem))

    corpus_lines = [o for o in op.observations if o.startswith("corpus:")]
    assert len(corpus_lines) == 1
    line = corpus_lines[0]
    assert line.startswith("corpus: 3 chunks")
    assert "canon_marks×2" in line  # noqa: RUF001
    assert "protocol_native×1" in line  # noqa: RUF001
    client.aclose()


def test_synthetic_zero_vol_still_overrides_corpus(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even with bullish-flavoured canon chunks, thin-liquidity still wins."""
    _install_mongo_env(monkeypatch)
    chunks = [
        {
            "provider_kind": "canon_marks",
            "source": "oaktree.com",
            "text": "Bull markets reward conviction at the inflection.",
        }
        for _ in range(5)
    ]
    _patch_retrieval(monkeypatch, returns=chunks)

    bars: list[dict[str, Any]] = []
    for i in range(30):
        bars.append(
            {
                "ts": f"2026-05-20T12:{i:02d}:00Z",
                "open": 0.001 + i * 0.0001,
                "high": 0.0011 + i * 0.0001,
                "low": 0.001 + i * 0.0001,
                "close": 0.0011 + i * 0.0001,
                "volume": 0.0 if i < 24 else 5_000.0,
            }
        )
    state = _healthy_market_state(ohlcv_5m=bars, range_24h_pct=15.0)

    client = _make_or_client(_capturing_handler(_PromptCapture(), _LLM_BULLISH))
    voice = ChartAnalystVoice(client=client)
    mem = LocalMemory(path=tmp_path / "corpus_thin_liq.jsonl")

    op = asyncio.run(voice.grade(state, mem))

    assert op.verdict == "abstain", "thin-liquidity must override corpus lens"
    assert "thin_liquidity_override" in op.reasoning
    # Observations still carry the corpus tag — useful diagnostic that
    # retrieval ran even though the override fired.
    assert any(o.startswith("corpus: 5 chunks") for o in op.observations)
    client.aclose()


def test_module_import_smoke() -> None:
    """Imports cleanly; defaults match the brief."""
    assert chart_analyst_mod.DEFAULT_MODEL == "openai/gpt-4o-mini"
