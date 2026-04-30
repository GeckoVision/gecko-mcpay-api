"""S7-CI-03 — guard against `gecko_core.sources` package shadowing.

Sprint 6 Track D flagged a re-export collision where the
`gecko_core.workflows.sources` shim could shadow the canonical
`gecko_core.sources` package on cold imports — an ordering bug that
disappears once another module pre-imports the package, so it slipped
past the existing pytest run (where conftest pulls in half the world
before any test resolves `discover_adapter`).

The fix is a fresh interpreter that imports the dispatcher cold, so any
future refactor that re-introduces the shadow trips this test on the
first PR rather than at runtime in the ingestion pipeline.
"""

from __future__ import annotations

import subprocess
import sys

_PROBE = (
    "from gecko_core.sources.dispatcher import discover_adapter; "
    "r = discover_adapter('https://reddit.com/r/x/comments/abc/'); "
    "assert r is not None"
)


def test_dispatcher_imports_cleanly_in_fresh_subprocess() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _PROBE],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, (
        f"fresh-subprocess import failed (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )

    # Belt-and-braces: even if the subprocess exited 0 (e.g. the assert
    # were ever softened), make sure no silent shadowing surfaced as a
    # warning-on-stderr import error.
    forbidden = ("ImportError", "AttributeError", "ModuleNotFoundError")
    for needle in forbidden:
        assert needle not in result.stderr, (
            f"unexpected {needle} in dispatcher cold-import stderr:\n{result.stderr}"
        )
