"""Schema test for ``tests/eval/labels/holdout_chunk_truth.json``.

S20-RAG-EVAL-LABELS-01. Guards:

  * the labels file parses as JSON
  * every chunk_key in any bucket (must_cite / should_cite / must_not_cite)
    also appears in ``_candidates`` (no orphan labels)
  * ``_meta.labeling_status`` is one of {"candidates_only", "labeled"}
  * when status is "labeled", every idea has at least one ``must_cite`` entry

The file ships in "candidates_only" status — the test passes today, and
flips to enforce the labeled-mode invariant the moment a human moves
chunks out of ``_candidates`` and sets the status flag.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

LABELS_PATH = (
    Path(__file__).resolve().parents[1].parent
    / "tests"
    / "eval"
    / "labels"
    / "holdout_chunk_truth.json"
)

VALID_STATUSES = {"candidates_only", "labeled"}


@pytest.fixture(scope="module")
def labels_payload() -> dict:
    assert LABELS_PATH.exists(), f"labels file missing at {LABELS_PATH}"
    return json.loads(LABELS_PATH.read_text())


def test_labels_parse_as_json(labels_payload: dict) -> None:
    assert isinstance(labels_payload, dict)
    assert "ideas" in labels_payload
    assert "_meta" in labels_payload


def test_labels_status_is_known(labels_payload: dict) -> None:
    status = labels_payload["_meta"].get("labeling_status")
    assert status in VALID_STATUSES, f"unknown labeling_status={status!r}"


def test_no_orphan_labels(labels_payload: dict) -> None:
    """Every chunk_key in any bucket must appear in that idea's _candidates."""
    for idea_id, payload in labels_payload["ideas"].items():
        candidate_keys = {c["chunk_key"] for c in payload.get("_candidates") or []}
        for bucket in ("must_cite", "should_cite", "must_not_cite"):
            for key in payload.get(bucket) or []:
                assert key in candidate_keys, (
                    f"orphan label in idea={idea_id} bucket={bucket}: chunk_key={key!r} "
                    f"is not in _candidates. Either add it to _candidates or remove the label."
                )


def test_labeled_status_requires_must_cite_per_idea(labels_payload: dict) -> None:
    """When status='labeled', every idea has ≥1 must_cite entry. No-op for 'candidates_only'."""
    if labels_payload["_meta"].get("labeling_status") != "labeled":
        pytest.skip("labels_status is not 'labeled' yet; nothing to enforce")
    for idea_id, payload in labels_payload["ideas"].items():
        must = payload.get("must_cite") or []
        assert len(must) >= 1, (
            f"idea={idea_id} has empty must_cite under labeling_status='labeled'. "
            f"Either label it or revert status to 'candidates_only'."
        )


def test_chunk_key_format_documented(labels_payload: dict) -> None:
    fmt = labels_payload["_meta"].get("chunk_key_format")
    assert fmt, "_meta.chunk_key_format must document the chunk_key shape"
    assert "source_id" in fmt and "chunk_index" in fmt
