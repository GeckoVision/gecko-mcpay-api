"""S19-VOYAGE-DOCTOR-LIVE-01 — verify the --live doctor flag.

Stubs the `voyageai` async client so we can assert green/red rows without
hitting the real preview API. Mirrors the sys.modules injection pattern
from `tests/ingestion/test_voyage_embedder_contract.py`.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

import pytest


class _StubEmbedResp:
    def __init__(self, dim: int, count: int = 1, total_tokens: int = 4) -> None:
        self.embeddings = [[0.0] * dim for _ in range(count)]
        self.total_tokens = total_tokens


class _StubRerankResp:
    def __init__(self, n: int = 2) -> None:
        self.results = [object() for _ in range(n)]


class _StubVoyageClient:
    """Configurable async client. Each method either returns canned data,
    raises a configured exception, or sleeps past the timeout."""

    def __init__(
        self,
        *,
        api_key: str,
        embed_dim: int = 1024,
        embed_count: int = 1,
        embed_exc: Exception | None = None,
        embed_sleep: float = 0.0,
        rerank_n: int = 2,
        rerank_exc: Exception | None = None,
        rerank_sleep: float = 0.0,
    ) -> None:
        self.api_key = api_key
        self.embed_dim = embed_dim
        self.embed_count = embed_count
        self.embed_exc = embed_exc
        self.embed_sleep = embed_sleep
        self.rerank_n = rerank_n
        self.rerank_exc = rerank_exc
        self.rerank_sleep = rerank_sleep

    async def embed(self, **_: Any) -> _StubEmbedResp:
        if self.embed_sleep:
            await asyncio.sleep(self.embed_sleep)
        if self.embed_exc is not None:
            raise self.embed_exc
        return _StubEmbedResp(self.embed_dim, self.embed_count)

    async def rerank(self, **_: Any) -> _StubRerankResp:
        if self.rerank_sleep:
            await asyncio.sleep(self.rerank_sleep)
        if self.rerank_exc is not None:
            raise self.rerank_exc
        return _StubRerankResp(self.rerank_n)


def _install_module(monkeypatch: pytest.MonkeyPatch, **client_kwargs: Any) -> None:
    """Register a fake `voyageai` module whose AsyncClient builds a configured stub."""

    class _FakeModule:
        def AsyncClient(self, *, api_key: str) -> _StubVoyageClient:
            return _StubVoyageClient(api_key=api_key, **client_kwargs)

    monkeypatch.setitem(sys.modules, "voyageai", _FakeModule())


@pytest.mark.asyncio
async def test_voyage_live_green_when_embed_and_rerank_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_module(monkeypatch)
    from gecko_mcp.doctor import check_voyage_live

    rows = await check_voyage_live(
        environ={
            "VOYAGE_API_KEY": "pa-test-redacted",
            "EMBED_PROVIDER": "voyage",
            "GECKO_RERANKER": "voyage",
        }
    )
    by_name = {r.name: r for r in rows}
    assert by_name["voyage:embed:live"].ok is True
    assert "dim=1024" in by_name["voyage:embed:live"].detail
    assert by_name["voyage:rerank:live"].ok is True


@pytest.mark.asyncio
async def test_voyage_live_red_when_embed_dim_wrong(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Voyage account silently downgraded to a different model → wrong dim."""
    _install_module(monkeypatch, embed_dim=512)
    from gecko_mcp.doctor import check_voyage_live

    rows = await check_voyage_live(
        environ={
            "VOYAGE_API_KEY": "pa-test",
            "EMBED_PROVIDER": "voyage",
            "GECKO_RERANKER": "none",
        }
    )
    by_name = {r.name: r for r in rows}
    assert by_name["voyage:embed:live"].ok is False
    assert "dim=512" in by_name["voyage:embed:live"].detail
    assert "expected=1024" in by_name["voyage:embed:live"].detail
    assert "voyage:rerank:live" not in by_name  # rerank disabled, skipped


@pytest.mark.asyncio
async def test_voyage_live_red_on_auth_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Auth401(Exception):
        status_code = 401

    _install_module(monkeypatch, embed_exc=_Auth401("unauthorized: revoked key"))
    from gecko_mcp.doctor import check_voyage_live

    rows = await check_voyage_live(
        environ={
            "VOYAGE_API_KEY": "pa-revoked",
            "EMBED_PROVIDER": "voyage",
            "GECKO_RERANKER": "none",
        }
    )
    by_name = {r.name: r for r in rows}
    assert by_name["voyage:embed:live"].ok is False
    assert "unauthorized" in by_name["voyage:embed:live"].detail


@pytest.mark.asyncio
async def test_voyage_live_red_on_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the configured timeout to a tiny value so the test stays fast."""
    _install_module(monkeypatch, embed_sleep=0.5)
    from gecko_mcp import doctor as doctor_module

    monkeypatch.setattr(doctor_module, "VOYAGE_LIVE_TIMEOUT_S", 0.05)

    rows = await doctor_module.check_voyage_live(
        environ={
            "VOYAGE_API_KEY": "pa-test",
            "EMBED_PROVIDER": "voyage",
            "GECKO_RERANKER": "none",
        }
    )
    by_name = {r.name: r for r in rows}
    assert by_name["voyage:embed:live"].ok is False
    assert "timeout" in by_name["voyage:embed:live"].detail


@pytest.mark.asyncio
async def test_voyage_live_skipped_when_key_unset() -> None:
    from gecko_mcp.doctor import check_voyage_live

    rows = await check_voyage_live(environ={"EMBED_PROVIDER": "voyage", "GECKO_RERANKER": "voyage"})
    by_name = {r.name: r for r in rows}
    assert "voyage:live" in by_name
    assert by_name["voyage:live"].info is True
    assert "skipped" in by_name["voyage:live"].detail
    assert "voyage:embed:live" not in by_name
    assert "voyage:rerank:live" not in by_name


@pytest.mark.asyncio
async def test_voyage_live_skipped_when_provider_not_voyage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the operator runs on OpenAI embeddings, no Voyage embed ping fires."""
    _install_module(monkeypatch)
    from gecko_mcp.doctor import check_voyage_live

    rows = await check_voyage_live(
        environ={
            "VOYAGE_API_KEY": "pa-test",
            "EMBED_PROVIDER": "openai",
            "GECKO_RERANKER": "none",
        }
    )
    by_name = {r.name: r for r in rows}
    assert "voyage:embed:live" not in by_name
    assert "voyage:rerank:live" not in by_name


def test_run_doctor_does_not_invoke_live_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_doctor() with no --live must not call check_voyage_live."""
    from gecko_mcp import doctor as doctor_module

    called = {"value": False}

    async def _fail_if_called(_environ: Any = None) -> list[Any]:
        called["value"] = True
        return []

    monkeypatch.setattr(doctor_module, "check_voyage_live", _fail_if_called)
    # Run with thin-client env so we don't try to import supabase etc.
    doctor_module.run_doctor(environ={"GECKO_API_URL": "https://api.geckovision.tech"})
    assert called["value"] is False


def test_run_doctor_invokes_live_when_flag_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_doctor(live=True) in server-stack mode triggers check_voyage_live."""
    from gecko_mcp import doctor as doctor_module

    called = {"value": False}

    async def _track(_environ: Any = None) -> list[Any]:
        called["value"] = True
        return []

    monkeypatch.setattr(doctor_module, "check_voyage_live", _track)
    doctor_module.run_doctor(
        environ={
            # server-stack signal (SUPABASE_URL set) → not thin client
            "SUPABASE_URL": "https://stub.supabase.co",
            "SUPABASE_SERVICE_ROLE_KEY": "stub",
            "TAVILY_API_KEY": "stub",
            "VOYAGE_API_KEY": "pa-stub",
            "EMBED_PROVIDER": "voyage",
            "GECKO_RERANKER": "none",
        },
        live=True,
    )
    assert called["value"] is True
