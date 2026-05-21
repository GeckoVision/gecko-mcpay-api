"""S39-#133 — unit tests for the backtest point-in-time retrieval gate.

Pure-function tests over `_as_of_match_clause` and `_normalize_as_of`. No
Mongo, no LLM, no autogen — the lighter-tests pattern per CLAUDE.md: test
the helpers that build the `$match` body directly, not the full retrieval
orchestration.

Why these matter: a backtest at time T must see only chunks that existed
at T (no lookahead). The gate is a retrieval *gate*, so Pattern F applies
— the most dangerous failure is the gate silently dropping the timeless
investor-canon corpus (canon chunks carry no `as_of_date`). The safety
property the whole feature rests on: `as_of=None` (production) is a strict
no-op — the helper returns None and the caller appends nothing.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pytest
from gecko_core.orchestration.trade_panel import (
    _as_of_match_clause,
    _normalize_as_of,
)

# --------------------------------------------------------------------------
# _as_of_match_clause — the $match body builder.
# --------------------------------------------------------------------------


def test_clause_is_none_when_as_of_is_none() -> None:
    """as_of=None is the production default — strict no-op, returns None.

    This is THE safety property: the caller appends nothing, so the
    production pipeline is byte-identical to today.
    """
    assert _as_of_match_clause(None) is None


def test_clause_is_none_for_empty_string() -> None:
    """A falsy/empty as_of also no-ops — never builds a degenerate $match."""
    assert _as_of_match_clause("") is None


def test_clause_gates_on_as_of_date_lte() -> None:
    """A real as_of builds an $or whose first arm is `as_of_date <= as_of`."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    arms = clause["$or"]
    assert {"as_of_date": {"$lte": "2026-03-01"}} in arms


def test_clause_admits_null_as_of_date_for_canon() -> None:
    """Pattern F — the gate MUST admit null `as_of_date` (timeless canon).

    Mongo's $lte does not match null/missing fields; without these arms the
    gate would silently drop every Marks/Damodaran/Berkshire chunk.
    """
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    arms = clause["$or"]
    assert {"as_of_date": None} in arms
    assert {"as_of_date": {"$exists": False}} in arms


def test_clause_has_exactly_three_arms() -> None:
    """Gated chunks + null + missing — no fourth arm leaks the gate open."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert len(clause["$or"]) == 3


def _passes(clause: dict[str, Any], as_of_date_value: object, present: bool = True) -> bool:
    """Light fake of Mongo $or evaluation against the three gate arms.

    Mirrors how Atlas would evaluate `_as_of_match_clause` output against a
    single chunk doc — no Mongo needed to prove the gate's truth table.
    """
    for arm in clause["$or"]:
        spec = arm["as_of_date"]
        if isinstance(spec, dict):
            if (
                "$lte" in spec
                and present
                and as_of_date_value is not None
                and str(as_of_date_value) <= spec["$lte"]
            ):
                return True
            if "$exists" in spec and spec["$exists"] is False and not present:
                return True
        else:  # {"as_of_date": None}
            if present and as_of_date_value is None:
                return True
    return False


def test_truth_table_past_chunk_passes() -> None:
    """A protocol chunk dated before T survives the gate."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert _passes(clause, "2026-01-15") is True


def test_truth_table_same_day_chunk_passes() -> None:
    """A chunk dated exactly on T survives (<= is inclusive)."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert _passes(clause, "2026-03-01") is True


def test_truth_table_future_chunk_dropped() -> None:
    """A chunk dated after T is dropped — this is the no-lookahead property."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert _passes(clause, "2026-06-30") is False


def test_truth_table_canon_null_date_passes() -> None:
    """A timeless canon chunk (as_of_date=None) survives at any T."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert _passes(clause, None) is True


def test_truth_table_canon_missing_field_passes() -> None:
    """A chunk with no as_of_date field at all survives — Pattern F."""
    clause = _as_of_match_clause("2026-03-01")
    assert clause is not None
    assert _passes(clause, None, present=False) is True


def test_truth_table_canon_passes_at_an_early_t() -> None:
    """Canon stays reachable even at a T before the corpus ingest date.

    #129 doc §2c — canon is anachronistic but timeless; it must never be
    gated out by an early backtest T.
    """
    clause = _as_of_match_clause("2020-01-01")
    assert clause is not None
    assert _passes(clause, None) is True
    assert _passes(clause, None, present=False) is True
    # ...and a 2026-dated protocol chunk is correctly excluded at that T.
    assert _passes(clause, "2026-05-01") is False


# --------------------------------------------------------------------------
# _normalize_as_of — coerce date / datetime / str to a YYYY-MM-DD bucket.
# --------------------------------------------------------------------------


def test_normalize_none_stays_none() -> None:
    """None in -> None out — preserves the no-op production path."""
    assert _normalize_as_of(None) is None


def test_normalize_empty_string_is_none() -> None:
    """A blank string normalizes to None — also a no-op."""
    assert _normalize_as_of("   ") is None


def test_normalize_date() -> None:
    assert _normalize_as_of(date(2026, 3, 1)) == "2026-03-01"


def test_normalize_datetime_takes_date_portion() -> None:
    assert _normalize_as_of(datetime(2026, 3, 1, 14, 30, 0)) == "2026-03-01"


def test_normalize_iso_string_passthrough() -> None:
    assert _normalize_as_of("2026-03-01") == "2026-03-01"


def test_normalize_iso_string_truncates_time() -> None:
    assert _normalize_as_of("2026-03-01T09:15:00Z") == "2026-03-01"


def test_normalize_rejects_garbage() -> None:
    """A malformed backtest date raises — fail loud, never a silent gate."""
    with pytest.raises(ValueError):
        _normalize_as_of("not-a-date")
