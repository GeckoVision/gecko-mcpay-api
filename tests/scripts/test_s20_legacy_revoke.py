"""Tests for ``scripts/mongo/s20_legacy_revoke.py`` (S20-A3).

Stubbed Mongo collection — no network. Mirrors the
``tests/db/test_mongo_chunks.py`` fake-collection pattern.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

# Load the script as a module — `scripts/` is not a package on sys.path.
_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "mongo" / "s20_legacy_revoke.py"
_spec = importlib.util.spec_from_file_location("s20_legacy_revoke", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
revoke_mod = importlib.util.module_from_spec(_spec)
sys.modules["s20_legacy_revoke"] = revoke_mod
_spec.loader.exec_module(revoke_mod)


# ---------------------------------------------------------------------------
# Fake async collection that supports the script's exact surface.
# ---------------------------------------------------------------------------


def _matches_or_exists(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    """Tiny matcher supporting $or + per-field $exists used by the script."""
    if "$or" in filt:
        return any(_matches_or_exists(doc, sub) for sub in filt["$or"])
    for key, val in filt.items():
        if isinstance(val, dict) and "$exists" in val:
            present = key in doc
            if present != bool(val["$exists"]):
                return False
        else:
            if doc.get(key) != val:
                return False
    return True


def _apply_set(doc: dict[str, Any], set_fields: dict[str, Any]) -> bool:
    """Apply a $set with dotted-path keys. Returns True if doc changed."""
    changed = False
    for key, val in set_fields.items():
        if "." in key:
            parts = key.split(".")
            cur = doc
            for p in parts[:-1]:
                nxt = cur.get(p)
                if not isinstance(nxt, dict):
                    nxt = {}
                    cur[p] = nxt
                cur = nxt
            if cur.get(parts[-1]) != val:
                cur[parts[-1]] = val
                changed = True
        else:
            if doc.get(key) != val:
                doc[key] = val
                changed = True
    return changed


class _UpdateResult:
    def __init__(self, modified: int) -> None:
        self.modified_count = modified


class _FakeColl:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs
        self.created_indexes: list[tuple[Any, dict[str, Any]]] = []

    async def count_documents(self, filt: dict[str, Any]) -> int:
        return sum(1 for d in self.docs if _matches_or_exists(d, filt))

    async def update_many(self, filt: dict[str, Any], update: dict[str, Any]) -> _UpdateResult:
        set_fields = update.get("$set", {})
        modified = 0
        for d in self.docs:
            if _matches_or_exists(d, filt) and _apply_set(d, set_fields):
                modified += 1
        return _UpdateResult(modified)

    async def create_index(self, keys: Any, **opts: Any) -> None:
        self.created_indexes.append((keys, opts))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _legacy_doc(idx: int, **overrides: Any) -> dict[str, Any]:
    """Pre-A2 chunk: missing category/vertical/source."""
    base = {
        "_id": f"legacy-{idx}",
        "session_id": "s",
        "source_id": f"src-{idx}",
        "chunk_index": idx,
        "text": "old chunk",
    }
    base.update(overrides)
    return base


def _canonical_doc(idx: int) -> dict[str, Any]:
    """Post-A2 chunk: has all the new fields."""
    return {
        "_id": f"new-{idx}",
        "session_id": "s",
        "source_id": f"src-{idx}",
        "chunk_index": idx,
        "text": "fresh chunk",
        "category": "ai_ml",
        "vertical": "b2b_saas",
        "source": "tavily",
        "metadata": {
            "confidence": 0.9,
            "usage_count": 0,
            "timestamp": datetime.now(UTC),
            "pioneer": False,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dry_run_counts_and_writes_nothing() -> None:
    docs = [_legacy_doc(0), _legacy_doc(1), _canonical_doc(2)]
    coll = _FakeColl(docs)

    summary = await revoke_mod.revoke_legacy_chunks(coll, dry_run=True)

    assert summary == {
        "matched": 2,
        "modified": 0,
        "dry_run": True,
        "index_built": False,
    }
    # No mutations: legacy docs still missing fields.
    assert "category" not in docs[0]
    assert "category" not in docs[1]
    # Canonical doc untouched.
    assert docs[2]["category"] == "ai_ml"
    # No index built in dry-run.
    assert coll.created_indexes == []


@pytest.mark.asyncio
async def test_apply_mutates_legacy_only_and_leaves_canonical_alone() -> None:
    legacy = _legacy_doc(0)
    canonical = _canonical_doc(1)
    coll = _FakeColl([legacy, canonical])

    summary = await revoke_mod.revoke_legacy_chunks(coll, dry_run=False)

    assert summary["matched"] == 1
    assert summary["modified"] >= 1
    assert summary["dry_run"] is False
    assert summary["index_built"] is True

    # Legacy doc stamped with all three fields + deprecated marker.
    assert legacy["category"] == "legacy_uncategorized"
    assert legacy["vertical"] == "unknown"
    assert legacy["source"] == "web"
    assert legacy["metadata"]["deprecated"] is True
    assert "legacy_revoked_at" in legacy["metadata"]

    # Canonical doc untouched.
    assert canonical["category"] == "ai_ml"
    assert canonical["vertical"] == "b2b_saas"
    assert canonical["source"] == "tavily"
    assert "deprecated" not in canonical["metadata"]


@pytest.mark.asyncio
async def test_idempotent_second_apply_matches_zero() -> None:
    coll = _FakeColl([_legacy_doc(0), _legacy_doc(1)])

    first = await revoke_mod.revoke_legacy_chunks(coll, dry_run=False)
    assert first["matched"] == 2
    assert first["modified"] >= 2

    second = await revoke_mod.revoke_legacy_chunks(coll, dry_run=False)
    assert second["matched"] == 0
    assert second["modified"] == 0
    # Index still asserted on the (zero-match) re-run.
    assert second["index_built"] is True


@pytest.mark.asyncio
async def test_each_field_only_stamped_when_missing() -> None:
    """A doc with category set but missing vertical+source gets only the
    missing fields patched — pre-existing values are preserved."""
    partial = {
        "_id": "partial-0",
        "category": "design_ux",  # already set: must NOT be overwritten
        # vertical, source missing
    }
    coll = _FakeColl([partial])

    summary = await revoke_mod.revoke_legacy_chunks(coll, dry_run=False)

    assert summary["matched"] == 1
    # category preserved.
    assert partial["category"] == "design_ux"
    # missing fields patched to legacy defaults.
    assert partial["vertical"] == "unknown"
    assert partial["source"] == "web"
    assert partial["metadata"]["deprecated"] is True


@pytest.mark.asyncio
async def test_mixed_collection_only_legacy_touched() -> None:
    docs: list[dict[str, Any]] = [
        _legacy_doc(0),
        _canonical_doc(1),
        _legacy_doc(2),
        _canonical_doc(3),
        _canonical_doc(4),
    ]
    coll = _FakeColl(docs)

    summary = await revoke_mod.revoke_legacy_chunks(coll, dry_run=False)

    assert summary["matched"] == 2
    # Two legacy docs stamped.
    assert docs[0]["category"] == "legacy_uncategorized"
    assert docs[2]["category"] == "legacy_uncategorized"
    # Three canonical docs unchanged.
    for canonical in (docs[1], docs[3], docs[4]):
        assert canonical["category"] != "legacy_uncategorized"
        assert "deprecated" not in canonical["metadata"]


@pytest.mark.asyncio
async def test_dry_run_default_via_main_args() -> None:
    """The CLI parser defaults to dry-run, --apply is opt-in."""
    parser = revoke_mod._build_parser()

    # No flags → dry-run wins.
    args = parser.parse_args([])
    assert args.dry_run is True
    assert args.apply is False

    # --apply flips it.
    args = parser.parse_args(["--apply"])
    assert args.apply is True
