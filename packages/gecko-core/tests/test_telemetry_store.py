"""S33-#73 — tests for the telemetry store.

Light fakes only — no real Supabase. The fake client records every insert
payload so the test can assert the row shape directly, and serves canned
rows for the summary rollup. Covers:
  - record_event inserts the documented row shape
  - optional fields are omitted from the payload when None
  - unknown event_type still inserts (warning logged, no raise)
  - record_event swallows a DB failure (best-effort, never re-raises)
  - telemetry_summary rolls up counts + success rate + distinct counts
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from gecko_core.telemetry.store import KNOWN_TELEMETRY_EVENTS, TelemetryStore


class _FakeQuery:
    """Records insert payloads; serves canned data for select/count reads."""

    def __init__(self, table: _FakeTable) -> None:
        self._table = table
        self._is_count = False
        self._eq: dict[str, Any] = {}
        self._select_col: str | None = None

    # --- write path ---
    def insert(self, payload: dict[str, Any]) -> _FakeQuery:
        if self._table.raise_on_insert is not None:
            raise self._table.raise_on_insert
        self._table.inserted.append(payload)
        return self

    # --- read path ---
    def select(self, column: str, *, count: str | None = None, head: bool = False) -> _FakeQuery:
        self._is_count = count is not None
        self._select_col = column
        return self

    def eq(self, col: str, val: Any) -> _FakeQuery:
        self._eq[col] = val
        return self

    @property
    def not_(self) -> _FakeQuery:
        return self

    def is_(self, _col: str, _val: str) -> _FakeQuery:
        return self

    def execute(self) -> Any:
        if not self._table.inserted and not self._is_count and self._select_col is None:
            return _Result(data=[])
        if self._is_count:
            et = self._eq.get("event_type")
            n = sum(1 for r in self._table.rows if r.get("event_type") == et)
            return _Result(count=n)
        # distinct select
        rows = [
            {self._select_col: r.get(self._select_col)}
            for r in self._table.rows
            if r.get(self._select_col)
        ]
        return _Result(data=rows)


class _Result:
    def __init__(self, data: list[dict[str, Any]] | None = None, count: int | None = None) -> None:
        self.data = data
        self.count = count


class _FakeTable:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.inserted: list[dict[str, Any]] = []
        self.raise_on_insert: Exception | None = None


class _FakeClient:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self._table_obj = _FakeTable(rows or [])

    def table(self, _name: str) -> _FakeQuery:
        return _FakeQuery(self._table_obj)

    @property
    def inserted(self) -> list[dict[str, Any]]:
        return self._table_obj.inserted


@pytest.mark.asyncio
async def test_record_event_inserts_expected_shape() -> None:
    client = _FakeClient()
    store = TelemetryStore(client)  # type: ignore[arg-type]

    await store.record_event(
        "install_ok",
        wallet_address="So1aNaWa11et",
        email="dev@example.com",
        installer_tag="v1.2.3",
        metadata={"os": "linux"},
    )

    assert len(client.inserted) == 1
    row = client.inserted[0]
    assert row == {
        "event_type": "install_ok",
        "metadata": {"os": "linux"},
        "wallet_address": "So1aNaWa11et",
        "email": "dev@example.com",
        "installer_tag": "v1.2.3",
    }


@pytest.mark.asyncio
async def test_record_event_omits_none_fields() -> None:
    client = _FakeClient()
    store = TelemetryStore(client)  # type: ignore[arg-type]

    await store.record_event("install_started")

    row = client.inserted[0]
    assert row == {"event_type": "install_started", "metadata": {}}
    assert "wallet_address" not in row
    assert "email" not in row


@pytest.mark.asyncio
async def test_unknown_event_type_still_inserts_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeClient()
    store = TelemetryStore(client)  # type: ignore[arg-type]

    assert "skill_opened" not in KNOWN_TELEMETRY_EVENTS
    with caplog.at_level(logging.WARNING, logger="gecko_core.telemetry.store"):
        await store.record_event("skill_opened")

    assert len(client.inserted) == 1
    assert client.inserted[0]["event_type"] == "skill_opened"
    assert any("unknown event_type" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_record_event_swallows_db_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    client = _FakeClient()
    client._table_obj.raise_on_insert = RuntimeError("supabase down")
    store = TelemetryStore(client)  # type: ignore[arg-type]

    # Must NOT re-raise — telemetry is best-effort.
    with caplog.at_level(logging.ERROR, logger="gecko_core.telemetry.store"):
        await store.record_event("install_error")

    assert client.inserted == []
    assert any("insert failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_telemetry_summary_rollup() -> None:
    rows = [
        {"event_type": "install_started"},
        {"event_type": "install_started"},
        {"event_type": "install_started"},
        {"event_type": "install_started"},
        {"event_type": "install_ok", "wallet_address": "w1", "email": "a@x.com"},
        {"event_type": "install_ok", "wallet_address": "w2", "email": "b@x.com"},
        {"event_type": "install_ok", "wallet_address": "w2", "email": "a@x.com"},
        {"event_type": "install_error"},
        {"event_type": "register", "wallet_address": "w3", "email": "c@x.com"},
    ]
    store = TelemetryStore(_FakeClient(rows))  # type: ignore[arg-type]

    summary = await store.telemetry_summary()

    assert summary["install_started"] == 4
    assert summary["install_ok"] == 3
    assert summary["install_error"] == 1
    # 3 ok / 4 started
    assert summary["install_success_rate"] == 0.75
    # w1, w2, w3 distinct
    assert summary["distinct_registered_wallets"] == 3
    # a, b, c distinct
    assert summary["distinct_emails"] == 3


@pytest.mark.asyncio
async def test_telemetry_summary_empty_table() -> None:
    store = TelemetryStore(_FakeClient([]))  # type: ignore[arg-type]
    summary = await store.telemetry_summary()
    assert summary["install_started"] == 0
    assert summary["install_success_rate"] == 0.0
    assert summary["distinct_registered_wallets"] == 0
