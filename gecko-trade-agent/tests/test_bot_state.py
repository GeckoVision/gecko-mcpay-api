"""Tests for contest_bot.bot_state — light fakes only (per feedback_lighter_tests).

We exercise:
- BotState schema validation
- BotStateStore.load / save (round-trip, atomic, missing, corrupt)
- BotStateStore.rebuild_from_artifact across the correlation matrix
- A "restart" simulation that confirms the bot's load path picks up
  state that a previous instance persisted.

No real network, no real bot import, no asyncio.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Match test_gecko_wrap.py — contest_bot isn't a workspace package, so
# splice its parent dir onto sys.path before importing the module.
_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from bot_state import BotState, BotStateStore  # noqa: E402

# ── Schema ─────────────────────────────────────────────────────────


def test_botstate_defaults() -> None:
    s = BotState()
    assert s.version == 1
    assert s.positions == []
    assert s.daily_trades == 0
    assert s.consec_losses == 0
    assert s.total_spent_usd == 0.0
    assert s.last_reset_day == ""
    assert s.saved_at == ""


def test_botstate_roundtrip_pydantic() -> None:
    s = BotState(
        positions=[{"token": "X", "status": "open"}],
        daily_trades=2,
        consec_losses=1,
        total_spent_usd=50.0,
        last_reset_day="2026-05-20",
        saved_at="2026-05-20T00:00:00+00:00",
    )
    blob = s.model_dump_json()
    s2 = BotState.model_validate_json(blob)
    assert s2 == s


# ── load / save ────────────────────────────────────────────────────


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    store = BotStateStore(tmp_path / "nope.json")
    s = store.load()
    assert s == BotState()


def test_load_corrupt_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    p.write_text("{ not valid json")
    store = BotStateStore(p)
    s = store.load()
    assert s == BotState()


def test_load_wrong_shape_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    # daily_trades typed as str — pydantic still coerces, so use an
    # unambiguously broken shape (positions as int).
    p.write_text(json.dumps({"positions": 42}))
    store = BotStateStore(p)
    s = store.load()
    assert s == BotState()


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    store = BotStateStore(p)
    state = BotState(
        positions=[{"token": "abc", "symbol": "ABC-USDC", "status": "open"}],
        daily_trades=3,
        consec_losses=1,
        total_spent_usd=75.0,
        last_reset_day="2026-05-20",
        saved_at="2026-05-20T01:00:00+00:00",
    )
    store.save(state)
    assert p.exists()
    loaded = store.load()
    assert loaded == state


def test_save_is_atomic_no_tmp_left(tmp_path: Path) -> None:
    p = tmp_path / "bot_state.json"
    store = BotStateStore(p)
    store.save(BotState(daily_trades=1))
    # .tmp must not survive a successful save
    leftovers = [x for x in tmp_path.iterdir() if x.name.endswith(".tmp")]
    assert leftovers == []


# ── rebuild_from_artifact ──────────────────────────────────────────


def _write_artifact(path: Path, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_rebuild_missing_artifact_returns_empty(tmp_path: Path) -> None:
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(tmp_path / "no_such.jsonl")
    assert s.positions == []
    assert s.daily_trades == 0


def test_rebuild_empty_artifact(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    art.write_text("")
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert s.positions == []
    assert s.daily_trades == 0


def test_rebuild_single_open_no_close(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    _write_artifact(
        art,
        [
            {
                "decision_id": "d1",
                "kind": "position_open",
                "ts": "2026-05-20T10:00:00+00:00",
                "payload": {
                    "token": "TOK1",
                    "symbol": "TOK1-USDC",
                    "entry_price": 1.5,
                    "usd": 25,
                    "mode": "paper",
                },
            }
        ],
    )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert len(s.positions) == 1
    assert s.positions[0]["token"] == "TOK1"
    assert s.positions[0]["status"] == "open"
    assert s.positions[0]["entry_price"] == 1.5
    assert s.positions[0]["recovered_from_artifact"] is True
    assert s.daily_trades == 1
    # paper trade doesn't count toward live spend
    assert s.total_spent_usd == 0.0


def test_rebuild_live_open_counts_spend(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    _write_artifact(
        art,
        [
            {
                "decision_id": "d1",
                "kind": "position_open",
                "ts": "2026-05-20T10:00:00+00:00",
                "payload": {
                    "token": "TOK1",
                    "symbol": "TOK1-USDC",
                    "entry_price": 1.5,
                    "usd": 25,
                    "mode": "live",
                },
            }
        ],
    )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert s.total_spent_usd == 25.0


def test_rebuild_open_then_close_by_decision_id(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    _write_artifact(
        art,
        [
            {
                "decision_id": "d1",
                "kind": "position_open",
                "ts": "2026-05-20T10:00:00+00:00",
                "payload": {"token": "TOK1", "usd": 25, "mode": "paper"},
            },
            {
                "decision_id": "d1",
                "kind": "position_close",
                "ts": "2026-05-20T11:00:00+00:00",
                "payload": {"token": "TOK1", "exit_reason": "take_profit"},
            },
        ],
    )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert s.positions == []
    assert s.daily_trades == 1  # the open still counts toward the daily cap


def test_rebuild_legacy_stub_decision_id_falls_back_to_token(tmp_path: Path) -> None:
    """Early artifact rows use decision_id='stub'. Fallback to token match."""
    art = tmp_path / "artifact.jsonl"
    _write_artifact(
        art,
        [
            {
                "decision_id": "stub",
                "kind": "position_open",
                "ts": "2026-05-20T10:00:00+00:00",
                "payload": {"token": "TOK1", "usd": 25, "mode": "paper"},
            },
            {
                "decision_id": "stub",
                "kind": "position_close",
                "ts": "2026-05-20T11:00:00+00:00",
                "payload": {"token": "TOK1"},
            },
        ],
    )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert s.positions == []


def test_rebuild_mixed_open_close_keeps_unclosed(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    _write_artifact(
        art,
        [
            {
                "decision_id": "dA",
                "kind": "position_open",
                "ts": "2026-05-20T10:00:00+00:00",
                "payload": {"token": "A", "usd": 25, "mode": "paper"},
            },
            {
                "decision_id": "dB",
                "kind": "position_open",
                "ts": "2026-05-20T10:05:00+00:00",
                "payload": {"token": "B", "usd": 25, "mode": "paper"},
            },
            {
                "decision_id": "dC",
                "kind": "position_open",
                "ts": "2026-05-20T10:10:00+00:00",
                "payload": {"token": "C", "usd": 25, "mode": "paper"},
            },
            {
                "decision_id": "dB",
                "kind": "position_close",
                "ts": "2026-05-20T11:00:00+00:00",
                "payload": {"token": "B"},
            },
        ],
    )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    tokens = sorted(p["token"] for p in s.positions)
    assert tokens == ["A", "C"]
    assert s.daily_trades == 3


def test_rebuild_skips_malformed_lines(tmp_path: Path) -> None:
    art = tmp_path / "artifact.jsonl"
    with open(art, "w", encoding="utf-8") as f:
        f.write("not json at all\n")
        f.write(
            json.dumps(
                {
                    "decision_id": "d1",
                    "kind": "position_open",
                    "ts": "2026-05-20T10:00:00+00:00",
                    "payload": {"token": "TOK1", "usd": 25, "mode": "paper"},
                }
            )
            + "\n"
        )
    store = BotStateStore(tmp_path / "state.json")
    s = store.rebuild_from_artifact(art)
    assert len(s.positions) == 1


# ── Restart simulation ────────────────────────────────────────────


def test_restart_simulation_preserves_state(tmp_path: Path) -> None:
    """Write via one store, instantiate a fresh store on the same path,
    confirm state is identical. Mirrors what the bot does on reboot."""
    path = tmp_path / "bot_state.json"
    a = BotStateStore(path)
    a.save(
        BotState(
            positions=[
                {
                    "token": "RAY",
                    "symbol": "RAY-USDC",
                    "entry_price": 0.7368,
                    "status": "open",
                }
            ],
            daily_trades=5,
            consec_losses=0,
            total_spent_usd=25.0,
            last_reset_day="2026-05-20",
            saved_at="2026-05-20T07:49:05+00:00",
        )
    )
    b = BotStateStore(path)
    loaded = b.load()
    assert loaded.daily_trades == 5
    assert loaded.total_spent_usd == 25.0
    assert len(loaded.positions) == 1
    assert loaded.positions[0]["token"] == "RAY"
