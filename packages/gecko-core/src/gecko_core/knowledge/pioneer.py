"""S20-A7 — Pioneer-cell signal for the categorized chunk store.

A ``(vertical, category)`` pair is a "cell". When fewer than
``PIONEER_THRESHOLD`` non-deprecated chunks live in a cell, the next
batch landing in that cell is marked ``metadata.pioneer = True`` and a
``pioneer_call`` boolean is surfaced via structured logs so the
upstream x402 dispatcher (B3, future ticket) can apply the
pricing-surcharge logic post-hoc.

Design choices:

- The cell-density check runs ONCE per ``mark_pioneer_chunks`` call,
  not per chunk. The whole batch is either pioneer-or-not based on the
  pre-call cell count. This keeps the signal stable for the caller —
  splitting a 20-chunk batch into 4-chunk-then-pioneer / 16-chunk-then-
  not-pioneer would be a behavioural mess.
- Read-only against the existing cell state; safe to re-run. Repeated
  identical inserts produce identical pioneer flags as long as the
  underlying cell density hasn't crossed the threshold between calls.
- The threshold is overridable via ``GECKO_PIONEER_THRESHOLD`` env var.
  The constant is read at call time (not import time) so pytest's
  ``monkeypatch.setenv`` works without re-importing the module.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from gecko_core.knowledge.taxonomy import Category, Vertical

logger = logging.getLogger(__name__)

PIONEER_THRESHOLD: int = 5
"""Default cell-density threshold. A cell with fewer than this many
non-deprecated chunks is "pioneer" — its next insert batch is marked
and the dispatcher may apply a pricing surcharge.

Override at runtime via ``GECKO_PIONEER_THRESHOLD``. Read at call time
so env changes between tests / requests are honored.
"""


def _effective_threshold() -> int:
    raw = os.environ.get("GECKO_PIONEER_THRESHOLD")
    if raw is None or raw == "":
        return PIONEER_THRESHOLD
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "knowledge.pioneer.bad_threshold_env",
            extra={"raw": raw, "fallback": PIONEER_THRESHOLD},
        )
        return PIONEER_THRESHOLD


def _resolve_collection(collection: Any | None) -> Any | None:
    if collection is not None:
        return collection
    # Lazy import — avoid a hard dep on the mongo client at import time
    # (pioneer.py is imported by mongo_chunks.py, which already imports
    # the collection getter; we just call into it on demand).
    from gecko_core.db.mongo import chunks_collection

    return chunks_collection()


async def count_cell_chunks(
    vertical: Vertical,
    category: Category,
    *,
    collection: Any | None = None,
) -> int:
    """Count non-deprecated chunks in a ``(vertical, category)`` cell.

    Returns 0 when the collection is unavailable (e.g. dev without a
    Mongo URI). The pioneer signal degrades gracefully — an absent
    cell is treated as empty, which is consistent with "first writer
    wins" semantics.
    """
    coll = _resolve_collection(collection)
    if coll is None:
        return 0
    query: dict[str, Any] = {
        "vertical": vertical,
        "category": category,
        "metadata.deprecated": {"$ne": True},
    }
    return int(await coll.count_documents(query))


async def is_pioneer_cell(
    vertical: Vertical,
    category: Category,
    *,
    collection: Any | None = None,
) -> bool:
    """True iff the cell currently has fewer than the threshold of chunks."""
    threshold = _effective_threshold()
    count = await count_cell_chunks(vertical, category, collection=collection)
    pioneer = count < threshold
    logger.info(
        "knowledge.pioneer.check",
        extra={
            "vertical": vertical,
            "category": category,
            "count": count,
            "threshold": threshold,
            "is_pioneer": pioneer,
        },
    )
    return pioneer


async def mark_pioneer_chunks(
    chunks: list[dict[str, Any]],
    vertical: Vertical,
    category: Category,
    *,
    collection: Any | None = None,
) -> list[dict[str, Any]]:
    """Stamp ``metadata.pioneer = True`` on every chunk if the cell is sparse.

    Runs the cell-count check ONCE per call, not per chunk. Mutates
    each dict in place and also returns the list for chaining.
    Leaves ``metadata.pioneer`` untouched when the cell is dense — the
    insert path pre-seeds it to ``False``.
    """
    if not chunks:
        return chunks
    pioneer = await is_pioneer_cell(vertical, category, collection=collection)
    if not pioneer:
        return chunks
    for doc in chunks:
        meta = doc.setdefault("metadata", {})
        meta["pioneer"] = True
    return chunks


__all__ = [
    "PIONEER_THRESHOLD",
    "count_cell_chunks",
    "is_pioneer_cell",
    "mark_pioneer_chunks",
]
