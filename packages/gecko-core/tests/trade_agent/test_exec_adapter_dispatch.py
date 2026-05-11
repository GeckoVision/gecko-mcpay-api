"""Exec adapter factory + stub/live mode behaviour."""

from __future__ import annotations

import pytest
from gecko_core.trade_agent.exec_adapters import (
    BackpackExecAdapter,
    ExecAdapterError,
    OKXExecAdapter,
    SendAIExecAdapter,
    get_adapter,
)


def test_factory_returns_okx_by_name():
    a = get_adapter("okx", mode="stub")
    assert isinstance(a, OKXExecAdapter)
    assert a.mode == "stub"


def test_factory_returns_sendai_by_name():
    a = get_adapter("sendai", mode="stub")
    assert isinstance(a, SendAIExecAdapter)


def test_factory_returns_backpack_by_name():
    a = get_adapter("backpack", mode="stub")
    assert isinstance(a, BackpackExecAdapter)


def test_factory_rejects_unknown_rail():
    with pytest.raises(ExecAdapterError, match="unknown execution rail"):
        get_adapter("ftx", mode="stub")


def test_factory_rejects_bad_mode_env(monkeypatch):
    monkeypatch.setenv("OKX_EXEC_MODE", "wild")
    with pytest.raises(ExecAdapterError, match="invalid"):
        get_adapter("okx")


def test_factory_defaults_to_stub_when_env_unset(monkeypatch):
    monkeypatch.delenv("OKX_EXEC_MODE", raising=False)
    a = get_adapter("okx")
    assert a.mode == "stub"


async def test_okx_stub_returns_intent_receipt():
    a = get_adapter("okx", mode="stub")
    receipt = await a.submit(mint="So11", side="long", size_usd=10)
    assert receipt["mode"] == "stub"
    assert receipt["intent"]["mint"] == "So11"


async def test_sendai_live_raises_not_implemented():
    a = SendAIExecAdapter(mode="live")
    with pytest.raises(NotImplementedError, match="contract test"):
        await a.submit(mint="So11", side="long", size_usd=10)


async def test_backpack_live_raises_not_implemented():
    a = BackpackExecAdapter(mode="live")
    with pytest.raises(NotImplementedError, match="contract test"):
        await a.submit(mint="So11", side="long", size_usd=10)
