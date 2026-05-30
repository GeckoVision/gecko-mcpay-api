"""Targeted unit test for `decision_store.behavior_sink`.

Per the build brief and the `feedback_lighter_tests` directive — we test:

  1. `build_behavior_doc` produces the BSON shape the design doc specifies.
  2. `BehaviorSink.record()` calls `update_one` with the right filter, $set
     payload, and upsert semantics on a fake collection.
  3. `patch_embedding` / `patch_outcome` produce the documented $set deltas.

NO blind pytest sweep. Light fakes (no monkeypatch of imports, no live Mongo).
Synchronous mode (`async_writes=False`) so the assertion runs before the test
function returns.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))

from decision_store.behavior_sink import (  # noqa: E402
    DEFAULT_COUNTERFACTUAL_WINDOW_MIN,
    SCHEMA_V,
    BehaviorSink,
    build_behavior_doc,
)


class _FakeColl:
    """Capture-only collection. Mimics the slice of pymongo's Collection
    API the sink uses: `update_one(filter, update, upsert=...)`.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def update_one(self, flt, update, upsert: bool = False) -> None:
        self.calls.append({"filter": flt, "update": update, "upsert": upsert})


# ── Fixture decision (mirrors what `local_panel` artifact rows look like) ──
_FIXED_DECISION = {
    "decision_id": "dec-abc-123",
    "run_id": "run-xyz",
    "ts": "2026-05-30T01:30:48.110319+00:00",
    "symbol": "PYTH",
    "symbol_group": "majors",
    "signal": {"type": "volume_spike", "fired": True},
    "indicators": {
        "price": 0.0409,
        "regime": "TREND-UP",
        "regime_1h": "TREND-UP",
        "adx": 27.6,
        "rsi": 71.2,
    },
    "voices": [
        {"name": "chart_analyst", "verdict": "neutral", "confidence": 0.65},
        {"name": "memory_voice", "verdict": "abstain", "confidence": 0.0},
        {"name": "risk_voice", "verdict": "bullish", "confidence": 0.7},
        {"name": "regime_analyst", "verdict": "abstain", "confidence": 0.0},
        {"name": "strategist_voice", "verdict": "bearish", "confidence": 0.75},
    ],
    "oracle": None,
    "coordinator": {
        "action": "decline",
        "rule": "chart_below_threshold",
        "note": "1B/1S/1N/2A",
    },
    "market_context": {"net_flow_1h_usd": -3374.83, "btc_overlay_4h": "trend_up"},
}


# ── 1. build_behavior_doc — pure projection ─────────────────────────────


def test_build_behavior_doc_shape_matches_design():
    doc = build_behavior_doc(
        _FIXED_DECISION, run_id="run-xyz", code_commit="abc1234"
    )
    assert doc["decision_id"] == "dec-abc-123"
    assert doc["run_id"] == "run-xyz"
    assert doc["ts"] == "2026-05-30T01:30:48.110319+00:00"
    assert doc["symbol"] == "PYTH"
    assert doc["action"] == "decline"
    assert doc["schema_v"] == SCHEMA_V
    assert doc["code_commit"] == "abc1234"

    ms = doc["market_state"]
    assert ms["price"] == 0.0409
    assert ms["regime_4h"] == "TREND-UP"
    assert ms["regime_1h"] == "TREND-UP"
    assert ms["net_flow_1h_usd"] == -3374.83
    assert ms["btc_overlay_4h"] == "trend_up"
    assert ms["signal"]["type"] == "volume_spike"
    assert ms["indicators"]["adx"] == 27.6

    assert len(doc["voices"]) == 5
    assert doc["coordinator"]["rule"] == "chart_below_threshold"
    assert doc["oracle"] is None

    cf = doc["counterfactual"]
    assert cf["status"] == "pending"
    assert cf["window_min"] == DEFAULT_COUNTERFACTUAL_WINDOW_MIN
    assert cf["label"] is None
    assert cf["forward_max_pct"] is None

    # Embedding fields absent on a fresh build (the recorder patches later)
    assert "embedding" not in doc
    assert doc["embedding_model"] is None
    assert doc["embedded_at"] is None


def test_build_behavior_doc_carries_existing_embedding():
    enriched = dict(_FIXED_DECISION)
    enriched["embedding"] = [0.1] * 1024
    enriched["embedding_model"] = "voyage-finance-2"
    enriched["embedding_summary"] = "Symbol: PYTH ..."
    doc = build_behavior_doc(enriched, run_id="run-xyz")
    assert doc["embedding"] == [0.1] * 1024
    assert doc["embedding_model"] == "voyage-finance-2"
    assert doc["embedding_summary"] == "Symbol: PYTH ..."
    assert doc["embedded_at"] is not None  # stamped on carry-through


def test_build_behavior_doc_window_min_override():
    doc = build_behavior_doc(_FIXED_DECISION, counterfactual_window_min=60)
    assert doc["counterfactual"]["window_min"] == 60


def test_build_behavior_doc_handles_thin_input():
    """Backfill scripts pass partial dicts — must not raise."""
    doc = build_behavior_doc({"decision_id": "thin", "symbol": "WIF"})
    assert doc["decision_id"] == "thin"
    assert doc["symbol"] == "WIF"
    assert doc["action"] == "unknown"
    assert doc["voices"] == []
    assert doc["counterfactual"]["status"] == "pending"


# ── 2. BehaviorSink.record — upsert with the documented shape ────────


def test_sink_record_upserts_with_decision_id_filter():
    coll = _FakeColl()
    sink = BehaviorSink(coll, async_writes=False)
    sink.record(_FIXED_DECISION, run_id="run-xyz")

    assert len(coll.calls) == 1
    call = coll.calls[0]
    assert call["filter"] == {"decision_id": "dec-abc-123"}
    assert call["upsert"] is True
    assert "$set" in call["update"]
    assert "$setOnInsert" in call["update"]
    assert call["update"]["$set"]["symbol"] == "PYTH"
    assert call["update"]["$set"]["action"] == "decline"
    assert call["update"]["$set"]["counterfactual"]["status"] == "pending"
    assert "created_at" in call["update"]["$setOnInsert"]


def test_sink_record_skips_without_decision_id():
    coll = _FakeColl()
    sink = BehaviorSink(coll, async_writes=False)
    sink.record({"symbol": "WIF"})  # no decision_id
    assert coll.calls == []


def test_sink_record_swallows_mongo_failure():
    """Bot loop must not crash on Mongo unavailability."""

    class _BrokenColl:
        def update_one(self, *a, **kw):
            raise RuntimeError("simulated mongo timeout")

    sink = BehaviorSink(_BrokenColl(), async_writes=False)
    # Must not raise:
    sink.record(_FIXED_DECISION)


# ── 3. patch_embedding / patch_outcome — targeted $set deltas ───────


def test_patch_embedding_updates_vector_and_meta():
    coll = _FakeColl()
    sink = BehaviorSink(coll, async_writes=False)
    sink.patch_embedding(
        "dec-abc-123",
        vector=[0.5] * 1024,
        model="voyage-finance-2",
        summary="Symbol: PYTH ...",
    )
    assert len(coll.calls) == 1
    call = coll.calls[0]
    assert call["filter"] == {"decision_id": "dec-abc-123"}
    assert call["upsert"] is False
    s = call["update"]["$set"]
    assert s["embedding"] == [0.5] * 1024
    assert s["embedding_model"] == "voyage-finance-2"
    assert s["embedding_summary"] == "Symbol: PYTH ..."
    assert s["embedded_at"] is not None


def test_patch_embedding_with_none_vector_still_records_meta():
    coll = _FakeColl()
    sink = BehaviorSink(coll, async_writes=False)
    sink.patch_embedding("dec-abc-123", vector=None, model="voyage-finance-2", summary="x")
    s = coll.calls[0]["update"]["$set"]
    assert "embedding" not in s  # don't poison the field with None
    assert s["embedding_model"] == "voyage-finance-2"


def test_patch_outcome_sets_outcome_subdoc():
    coll = _FakeColl()
    sink = BehaviorSink(coll, async_writes=False)
    sink.patch_outcome(
        "dec-abc-123",
        {"pnl_pct": -3.07, "exit_reason": "stop_loss", "duration_min": 84.0},
    )
    call = coll.calls[0]
    assert call["filter"] == {"decision_id": "dec-abc-123"}
    assert call["update"] == {"$set": {"outcome": {
        "pnl_pct": -3.07, "exit_reason": "stop_loss", "duration_min": 84.0
    }}}
    assert call["upsert"] is False


# ── 4. from_env returns None when MONGODB_URI is absent ────────────────


def test_from_env_returns_none_without_uri(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MONGODB_URI", raising=False)
    assert BehaviorSink.from_env() is None


def test_from_env_returns_none_when_kill_switch_set(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MONGODB_URI", "mongodb://example")
    monkeypatch.setenv("GECKO_BEHAVIOR_SINK", "0")
    assert BehaviorSink.from_env() is None
