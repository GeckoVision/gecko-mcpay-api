"""S16-INGEST-01 — schema-drift guard for ErrorKind.

Mirrors `test_payment_mode_consistency.py` (Pattern A from CLAUDE.md). The
`error_kind` column on `chunks_write_audit` carries a CHECK constraint
that must agree with `gecko_core.ingestion.audit.ErrorKind`. Adding a
bucket = touch one Python file + one migration. If they drift, this test
fails at PR review with a clear "X is in ErrorKind but not in the SQL CHECK".
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import get_args

from gecko_core.ingestion.audit import ERROR_KINDS, ErrorKind

_REPO_ROOT = Path(__file__).resolve().parents[3]
_MIGRATIONS_DIR = _REPO_ROOT / "infra" / "supabase" / "migrations"


def test_error_kind_literal_matches_runtime_tuple() -> None:
    """Static type alias and runtime tuple cannot drift inside audit.py."""
    assert get_args(ErrorKind) == ERROR_KINDS


def _latest_error_kind_check_values() -> tuple[str, ...]:
    """Walk migrations in name order; the last file that sets a CHECK on
    chunks_write_audit.error_kind wins. Returns the parsed value tuple.

    S16-INGEST-02 broadened this beyond the original
    `*chunks_write_audit*.sql` glob: a follow-up migration may ALTER the
    CHECK without including the table name in its own file name (e.g.
    `*_drop_partial_batch.sql`). The matching window is now "any
    migration that mentions both `chunks_write_audit` and an
    `error_kind IN (...)` clause" — last-write-wins by file name order.
    """
    pattern = re.compile(
        r"error_kind\s+IN\s*\(\s*((?:'[a-z_0-9]+'(?:\s*,\s*)?)+)\s*\)",
        re.IGNORECASE,
    )
    last_values: tuple[str, ...] | None = None
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        sql = path.read_text(encoding="utf-8")
        if "chunks_write_audit" not in sql:
            continue
        for raw in pattern.findall(sql):
            values = tuple(v.strip().strip("'") for v in raw.split(","))
            last_values = values
    if last_values is None:  # pragma: no cover
        raise RuntimeError("no error_kind CHECK constraint found in any migration")
    return last_values


def test_sql_check_constraint_matches_error_kinds() -> None:
    sql_values = _latest_error_kind_check_values()
    assert set(sql_values) == set(ERROR_KINDS), (
        f"SQL CHECK values {sql_values} drifted from ErrorKind {ERROR_KINDS}. "
        "Update audit.py and ship a new migration that ALTERs the CHECK "
        "(never edit the original migration in place)."
    )
