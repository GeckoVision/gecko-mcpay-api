"""Smoke for ``scripts/evict_academic_gecko_chunks.py`` (CORPUS-EVICT-01).

Stubbed Mongo collection — no network. Asserts:
  - dry-run prints per-pattern matched counts + samples and does NOT
    mutate the collection,
  - ``--apply`` actually deletes the matching docs (and only those).
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import Any

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "evict_academic_gecko_chunks.py"
_spec = importlib.util.spec_from_file_location("evict_academic_gecko_chunks", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
evict_mod = importlib.util.module_from_spec(_spec)
sys.modules["evict_academic_gecko_chunks"] = evict_mod
_spec.loader.exec_module(evict_mod)


# ---------------------------------------------------------------------------
# Tiny in-memory async collection that supports just the surface the script
# uses: ``count_documents``, ``find().limit()`` (async iter), ``delete_many``.
# ---------------------------------------------------------------------------


class _DeleteResult:
    def __init__(self, deleted: int) -> None:
        self.deleted_count = deleted


class _Cursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._limit: int | None = None

    def limit(self, n: int) -> _Cursor:
        self._limit = n
        return self

    def __aiter__(self) -> _Cursor:
        self._iter = iter(self._docs if self._limit is None else self._docs[: self._limit])
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as e:  # pragma: no cover — async iter end
            raise StopAsyncIteration from e


def _match_regex(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    """Match the exact filter shape the script uses: ``{"source_url": {"$regex": ..., "$options": "i"}}``."""
    spec = filt.get("source_url")
    if not isinstance(spec, dict):
        return False
    pattern = spec["$regex"]
    flags = re.IGNORECASE if "i" in spec.get("$options", "") else 0
    url = doc.get("source_url") or ""
    return bool(re.search(pattern, url, flags))


class _FakeColl:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self.docs = docs

    async def count_documents(self, filt: dict[str, Any]) -> int:
        return sum(1 for d in self.docs if _match_regex(d, filt))

    def find(self, filt: dict[str, Any], projection: dict[str, Any] | None = None) -> _Cursor:
        del projection  # script only projects _id + source_url; we ignore it
        return _Cursor([d for d in self.docs if _match_regex(d, filt)])

    async def delete_many(self, filt: dict[str, Any]) -> _DeleteResult:
        before = len(self.docs)
        self.docs = [d for d in self.docs if not _match_regex(d, filt)]
        return _DeleteResult(before - len(self.docs))


def _seed_docs() -> list[dict[str, Any]]:
    return [
        # Two academic-Gecko hits — should match `arxiv-gecko-2602`.
        {"_id": "a1", "source_url": "https://arxiv.org/abs/2602.19218"},
        {"_id": "a2", "source_url": "http://arxiv.org/pdf/2602.19218v3"},
        # One broad-arxiv-gecko hit — should match `arxiv-gecko-broad`.
        {"_id": "b1", "source_url": "https://arxiv.org/abs/1901.00001/gecko-paper"},
        # Canonical / unrelated chunks — must NOT be touched.
        {"_id": "k1", "source_url": "https://app.geckovision.tech/skill.md"},
        {"_id": "k2", "source_url": "https://example.com/some-saas-blog"},
        {"_id": "k3", "source_url": "https://news.ycombinator.com/item?id=42"},
    ]


@pytest.mark.asyncio
async def test_dry_run_reports_matches_without_mutating(
    capsys: pytest.CaptureFixture[str],
) -> None:
    docs = _seed_docs()
    coll = _FakeColl(list(docs))

    summary = await evict_mod.evict_academic_gecko_chunks(coll, dry_run=True)
    evict_mod._print_report(summary)

    # Nothing deleted in dry-run.
    assert summary["dry_run"] is True
    assert summary["total_deleted"] == 0
    assert len(coll.docs) == len(docs)

    # Per-pattern counts: 2 for arxiv-gecko-2602, 1 for arxiv-gecko-broad.
    by_name = {row["name"]: row for row in summary["per_pattern"]}
    assert by_name["arxiv-gecko-2602"]["matched"] == 2
    assert by_name["arxiv-gecko-broad"]["matched"] == 1
    # Samples include up to 5 docs per pattern.
    assert all(
        len(row["samples"]) <= evict_mod.DRY_RUN_SAMPLE_SIZE for row in summary["per_pattern"]
    )

    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "arxiv-gecko-2602" in out
    assert "matched=2" in out
    # Sample URLs surfaced in the report.
    assert "2602.19218" in out


@pytest.mark.asyncio
async def test_apply_deletes_only_blocklisted_docs() -> None:
    coll = _FakeColl(_seed_docs())

    summary = await evict_mod.evict_academic_gecko_chunks(coll, dry_run=False)

    assert summary["dry_run"] is False
    # 2 (arxiv-gecko-2602) + 1 (arxiv-gecko-broad) = 3 deletions total.
    assert summary["total_deleted"] == 3
    # Survivors: only the canonical / unrelated chunks remain.
    surviving_ids = sorted(d["_id"] for d in coll.docs)
    assert surviving_ids == ["k1", "k2", "k3"]
