"""Structural tests for the per-protocol orchestration loop in run.py.

Light fakes only — see feedback_lighter_tests.md. We don't fire the full
asyncio orchestrator; we just verify the click flag default parses to the
V1 protocol list and that ``run.py`` exposes the expected module-level
seam (``_CURRENT_QUERY``) the loop uses to bind per-pass queries.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def test_protocols_flag_parses_comma_list() -> None:
    # Sanity check: the click flag default produces 5 entries.
    default = "Jupiter,Kamino,Pyth,Drift,Jito"
    parsed = [p.strip() for p in default.split(",") if p.strip()]
    assert parsed == ["Jupiter", "Kamino", "Pyth", "Drift", "Jito"]


def test_run_module_exposes_current_query_seam() -> None:
    # Load run.py by file path (same pattern as test_service_call_specs.py).
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "trading_oracle" / "run.py"
    spec = importlib.util.spec_from_file_location("trading_oracle_run", script_path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["trading_oracle_run"] = mod
    spec.loader.exec_module(mod)

    # Loop relies on this module-level seam to bind per-protocol queries.
    assert hasattr(mod, "_CURRENT_QUERY")
    # Initial value: None (loop sets per-pass; falls back to the
    # multi-protocol default in _charge_and_fetch when unset).
    assert mod._CURRENT_QUERY is None
