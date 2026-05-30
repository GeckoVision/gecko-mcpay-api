"""Fan-out sink from DecisionRecorder → Mongo `bot_behaviors` collection.

Design ref:
    private/strategy/2026-05-30-mongo-behavior-news-collections-DESIGN.md
    private/strategy/2026-05-30-tasks-4-7-design-decisions-locked.md

Why a SINK, not an EDIT to the recorder:

The founder's `recorder.py` is WIP this sprint. Touching it risks lost work or
silent regressions. Per the design doc §4 + §8 ("zero changes to bot loop,
zero added latency"), we add a *fan-out* layer the bot can opt into.

Shape:

    sink = BehaviorSink.from_env()           # None if MONGODB_URI unset
    sink.record(decision_doc_dict, run_id=run_id, run_config=cfg)

Idempotent: keyed on `decision_id` (unique). Re-emission patches in place.
Best-effort: NEVER raises into the bot loop (mirrors `mongo.py:best_effort_upsert`).
Async fire-and-forget: writes happen on the existing decision-embed thread pool
so the bot loop returns immediately.

Counterfactual fields land as `status="pending"` — the standalone labeler
(`scripts/labeler/counterfactual_labeler.py`) patches them later.

NOT in v1 (deferred to v2 roadmap):
    * Auto-trigger of Voyage embedding (we let the existing recorder handle that
      on the `decisions` collection; the sink simply mirrors the embedding once
      it arrives via `patch_embedding()`).
    * Real-time stream / pub-sub. Today the bot calls `sink.record()` directly
      next to `recorder.record()`. A tailer-on-JSONL variant is documented in v2.

Env:
    MONGODB_URI        — Atlas connection string (required to enable)
    MONGODB_DB         — defaults to "gecko"
    GECKO_BEHAVIOR_SINK — "0" disables even if URI is set (kill switch)
    GECKO_BEHAVIOR_COUNTERFACTUAL_WINDOW_MIN — default 240 (locked decision)
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("decision_store.behavior_sink")

DEFAULT_COUNTERFACTUAL_WINDOW_MIN = 240  # locked in 2026-05-30 (Sprint 9 swing class)
DEFAULT_DB = "gecko"
DEFAULT_COLLECTION = "bot_behaviors"
SCHEMA_V = 1

_EXECUTOR: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _EXECUTOR
    if _EXECUTOR is None:
        _EXECUTOR = ThreadPoolExecutor(
            max_workers=int(os.environ.get("GECKO_BEHAVIOR_SINK_WORKERS", "2")),
            thread_name_prefix="behavior-sink",
        )
    return _EXECUTOR


def _sink_enabled() -> bool:
    return os.environ.get("GECKO_BEHAVIOR_SINK", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )


def _now_dt() -> datetime:
    return datetime.now(UTC)


def build_behavior_doc(
    decision: dict,
    *,
    run_id: str | None = None,
    run_config: dict | None = None,
    code_commit: str | None = None,
    counterfactual_window_min: int | None = None,
) -> dict:
    """Project a `DecisionDoc.to_dict()` payload into the `bot_behaviors` BSON shape.

    Pure function. No I/O. Deterministic. Safe to call from tests.

    The decision dict can be partial — missing keys default to neutral values
    so backfill scripts working off thinner artifact rows still produce a
    valid doc. We never raise from this function; downstream upsert is what
    enforces shape strictness.
    """
    window_min = int(
        counterfactual_window_min
        if counterfactual_window_min is not None
        else os.environ.get(
            "GECKO_BEHAVIOR_COUNTERFACTUAL_WINDOW_MIN",
            DEFAULT_COUNTERFACTUAL_WINDOW_MIN,
        )
    )

    coordinator = decision.get("coordinator") or {}
    action = coordinator.get("action") or decision.get("action") or "unknown"

    # market_state collapses the indicator + signal snapshot at decision time
    # so analytics queries don't need to rejoin DecisionDoc.indicators.
    indicators = decision.get("indicators") or {}
    signal = decision.get("signal") or {}
    market_state = {
        "price": indicators.get("price"),
        "regime_4h": indicators.get("regime") or indicators.get("regime_4h"),
        "regime_1h": indicators.get("regime_1h"),
        "indicators": indicators,
        "net_flow_1h_usd": (decision.get("market_context") or {}).get("net_flow_1h_usd"),
        "btc_overlay_4h": (decision.get("market_context") or {}).get("btc_overlay_4h"),
        "signal": signal,
    }

    doc = {
        "decision_id": decision.get("decision_id"),
        "run_id": run_id or decision.get("run_id"),
        "ts": decision.get("ts"),
        "symbol": decision.get("symbol"),
        "symbol_group": decision.get("symbol_group"),
        "action": action,
        "market_state": market_state,
        "voices": decision.get("voices") or [],
        "oracle": decision.get("oracle"),
        "coordinator": coordinator,
        "counterfactual": {
            "status": "pending",
            "window_min": window_min,
            "forward_max_pct": None,
            "forward_min_pct": None,
            "forward_close_pct": None,
            "label": None,
            "labeled_at": None,
        },
        "outcome": decision.get("outcome"),
        # Embedding is patched in by `patch_embedding()` once the recorder's
        # background embed thread resolves. We leave the field absent (not
        # None) so the labeler/queries can $exists-check it.
        "embedding_model": None,
        "embedding_summary": None,
        "embedded_at": None,
        "code_commit": code_commit or (run_config or {}).get("code_commit"),
        "schema_v": SCHEMA_V,
        "ingested_at": _now_dt(),
    }
    # If the recorder already attached an embedding before the sink ran
    # (e.g. backfill calling build_behavior_doc directly), carry it through.
    if decision.get("embedding"):
        doc["embedding"] = decision["embedding"]
        doc["embedding_model"] = decision.get("embedding_model")
        doc["embedding_summary"] = decision.get("embedding_summary")
        doc["embedded_at"] = _now_dt()
    return doc


class BehaviorSink:
    """Best-effort writer to Mongo `bot_behaviors`.

    The bot calls `record()` next to its existing `recorder.record()` call.
    All Mongo I/O happens on the sink's own thread pool — the bot loop never
    blocks on Atlas latency.
    """

    def __init__(
        self,
        collection: Any,
        *,
        counterfactual_window_min: int = DEFAULT_COUNTERFACTUAL_WINDOW_MIN,
        async_writes: bool = True,
    ) -> None:
        self._coll = collection
        self._window_min = counterfactual_window_min
        self._async = async_writes

    @classmethod
    def from_env(cls, **kwargs: Any) -> BehaviorSink | None:
        """Construct from MONGODB_URI. Returns None if Mongo is unreachable
        or the sink is disabled. Callers treat None as 'JSONL is enough'.
        """
        if not _sink_enabled():
            logger.info("behavior_sink: disabled via GECKO_BEHAVIOR_SINK=0")
            return None
        uri = os.environ.get("MONGODB_URI")
        if not uri:
            logger.info("behavior_sink: MONGODB_URI unset; sink not enabled")
            return None
        try:
            from pymongo import MongoClient

            db = MongoClient(uri, serverSelectionTimeoutMS=3000)[
                os.environ.get("MONGODB_DB", DEFAULT_DB)
            ]
            coll = db[os.environ.get("MONGODB_BEHAVIOR_COLL", DEFAULT_COLLECTION)]
        except Exception as exc:
            logger.warning("behavior_sink: Mongo unavailable (%s); sink disabled", exc)
            return None
        return cls(coll, **kwargs)

    def record(
        self,
        decision: dict,
        *,
        run_id: str | None = None,
        run_config: dict | None = None,
        code_commit: str | None = None,
    ) -> None:
        """Project + upsert. Fire-and-forget. Never raises."""
        try:
            doc = build_behavior_doc(
                decision,
                run_id=run_id,
                run_config=run_config,
                code_commit=code_commit,
                counterfactual_window_min=self._window_min,
            )
        except Exception as exc:
            logger.warning("behavior_sink: build failed (%s); skipping", exc)
            return
        decision_id = doc.get("decision_id")
        if not decision_id:
            logger.debug("behavior_sink: skip — no decision_id")
            return

        if self._async:
            try:
                _get_executor().submit(self._do_upsert, decision_id, doc)
            except Exception as exc:
                logger.warning("behavior_sink: submit failed (%s); falling back sync", exc)
                self._do_upsert(decision_id, doc)
        else:
            self._do_upsert(decision_id, doc)

    def patch_embedding(
        self,
        decision_id: str,
        vector: list[float] | None,
        model: str,
        summary: str,
    ) -> None:
        """Mirror the embedder's patch onto `bot_behaviors`.

        Called by the recorder's existing `_on_embed_done` callback or by a
        future tailer. Vector may be None — we still store the model + summary
        so the labeler can see "embed was attempted, returned nothing".
        """
        if not decision_id:
            return
        patch: dict[str, Any] = {
            "embedding_model": model,
            "embedding_summary": summary,
            "embedded_at": _now_dt(),
        }
        if vector is not None:
            patch["embedding"] = vector

        def _do() -> None:
            try:
                self._coll.update_one({"decision_id": decision_id}, {"$set": patch}, upsert=False)
            except Exception as exc:
                logger.warning("behavior_sink: embed patch failed (%s)", exc)

        if self._async:
            try:
                _get_executor().submit(_do)
            except Exception:
                _do()
        else:
            _do()

    def patch_outcome(self, decision_id: str, outcome: dict) -> None:
        """Patch the `outcome` block after a position closes."""
        if not decision_id:
            return

        def _do() -> None:
            try:
                self._coll.update_one(
                    {"decision_id": decision_id},
                    {"$set": {"outcome": outcome}},
                    upsert=False,
                )
            except Exception as exc:
                logger.warning("behavior_sink: outcome patch failed (%s)", exc)

        if self._async:
            try:
                _get_executor().submit(_do)
            except Exception:
                _do()
        else:
            _do()

    def _do_upsert(self, decision_id: str, doc: dict) -> None:
        try:
            self._coll.update_one(
                {"decision_id": decision_id},
                {"$set": doc, "$setOnInsert": {"created_at": _now_dt()}},
                upsert=True,
            )
        except Exception as exc:
            logger.warning(
                "behavior_sink: upsert failed (%s); JSONL + decisions coll remain source of truth",
                exc,
            )


def shutdown(*, wait: bool = True) -> None:
    """Drain the sink executor. Idempotent."""
    global _EXECUTOR
    if _EXECUTOR is None:
        return
    try:
        _EXECUTOR.shutdown(wait=wait)
    except Exception as exc:
        logger.warning("behavior_sink: shutdown raised (%s)", exc)
    _EXECUTOR = None
