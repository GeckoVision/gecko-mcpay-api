"""Unit tests for the pure metric helpers in scripts/eval/finance_embed_ab.

Live Voyage calls, Mongo sampling, and the cost estimate are NOT exercised
here — those need a network + key and are the measurement, not a unit under
test. We only pin the deterministic ranking metrics so a refactor cannot
silently break recall/nDCG/coverage math.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

# scripts/ is not an installed package; add the repo root so the standalone
# measurement module is importable under --import-mode=importlib.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.eval.finance_embed_ab import (  # noqa: E402
    cosine,
    ndcg_at_k,
    provider_kind_coverage,
    recall_at_k,
)


def test_cosine_identical_is_one() -> None:
    assert cosine([1.0, 0.0, 0.0], [1.0, 0.0, 0.0]) == 1.0


def test_cosine_orthogonal_is_zero() -> None:
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_unnormalized_matches_normalized() -> None:
    # scaling a vector must not change cosine
    assert math.isclose(cosine([2.0, 0.0], [1.0, 0.0]), 1.0)


def test_cosine_zero_vector_safe() -> None:
    assert cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_recall_full_hit() -> None:
    ranked = ["a", "b", "c", "d"]
    assert recall_at_k(ranked, {"a", "b"}, 2) == 1.0


def test_recall_partial() -> None:
    ranked = ["a", "x", "b", "y"]
    # relevant {a,b}; top-2 = {a,x} -> 1 of 2
    assert recall_at_k(ranked, {"a", "b"}, 2) == 0.5


def test_recall_empty_relevant_is_zero() -> None:
    assert recall_at_k(["a"], set(), 3) == 0.0


def test_ndcg_perfect_order_is_one() -> None:
    rel_gain = {"a": 1.0, "b": 0.5}
    # ranked exactly in ideal order
    assert math.isclose(ndcg_at_k(["a", "b", "c"], rel_gain, 3), 1.0)


def test_ndcg_inverted_order_below_one() -> None:
    rel_gain = {"a": 1.0, "b": 0.5}
    perfect = ndcg_at_k(["a", "b"], rel_gain, 2)
    inverted = ndcg_at_k(["b", "a"], rel_gain, 2)
    assert inverted < perfect


def test_ndcg_no_relevant_is_zero() -> None:
    assert ndcg_at_k(["a", "b"], {}, 3) == 0.0


def test_pk_coverage_full() -> None:
    ranked = ["a", "b"]
    id_to_pk = {"a": "canon_marks", "b": "protocol_native"}
    relevant = {"canon_marks", "protocol_native"}
    assert provider_kind_coverage(ranked, id_to_pk, relevant, 2) == 1.0


def test_pk_coverage_partial() -> None:
    ranked = ["a", "z"]
    id_to_pk = {"a": "canon_marks", "z": "web"}
    relevant = {"canon_marks", "protocol_native"}
    # top-2 surfaces only canon_marks of the 2 relevant kinds
    assert provider_kind_coverage(ranked, id_to_pk, relevant, 2) == 0.5


def test_pk_coverage_empty_relevant_is_zero() -> None:
    assert provider_kind_coverage(["a"], {"a": "web"}, set(), 2) == 0.0
