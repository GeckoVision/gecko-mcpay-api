"""Sprint 30 — flat_stall_exit refinement tests.

Three sub-features, all env-gated default OFF:

  S30-A: peak_pnl_pct + peak_pnl_ts tracked on the position dict, emitted
         on position_close so future autopsies can compute haircut
         (peak - close) without re-scanning OHLCV.

  S30-B: GECKO_STALL_TRIGGER_MODE=below_entry switches the stall trigger
         from "no new high for 30min" to "below entry for N min"
         (default 45). Wider tolerance for trades that dip then recover.

  S30-C: MFI shadow gate — every candidate's MFI logged; when
         GECKO_MFI_HARD_GATE=1 (default OFF), entries with MFI ≥ 70 are
         declined with reason "mfi_overbought_hard_gate" instead of
         opened. ai-ml's 2026-06-01 autopsy: 74% of stall bleed.

Tests use light fakes per `feedback_lighter_tests` — no monkeypatching
the bot module; just exercise the small pure helpers + env dispatch.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]
if str(_CONTEST_BOT_DIR) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT_DIR))


# ── Helpers ────────────────────────────────────────────────────────────


def _reload_bot(env: dict[str, str]) -> object:
    """Reload the bot module with the given env overrides so module-level
    constants pick up the env state. We never run the bot's main loop —
    just inspect the constants + small pure helpers."""
    for k, v in env.items():
        os.environ[k] = v
    os.environ.setdefault("OPENROUTER_API_KEY", "sk-dummy-test")
    if "jto_breakout_gecko_gated_contest_bot" in sys.modules:
        del sys.modules["jto_breakout_gecko_gated_contest_bot"]
    return importlib.import_module("jto_breakout_gecko_gated_contest_bot")


# ── S30-B: STALL_TRIGGER_MODE env dispatch ─────────────────────────────


def test_stall_trigger_mode_defaults_to_no_new_high() -> None:
    os.environ.pop("GECKO_STALL_TRIGGER_MODE", None)
    bot = _reload_bot({})
    assert bot.STALL_TRIGGER_MODE == "no_new_high"


def test_stall_trigger_mode_accepts_below_entry() -> None:
    bot = _reload_bot({"GECKO_STALL_TRIGGER_MODE": "below_entry"})
    assert bot.STALL_TRIGGER_MODE == "below_entry"


def test_stall_below_entry_min_defaults_to_45() -> None:
    os.environ.pop("GECKO_STALL_BELOW_ENTRY_MIN", None)
    bot = _reload_bot({})
    assert bot.STALL_BELOW_ENTRY_MIN == 45.0


def test_stall_below_entry_min_env_override() -> None:
    bot = _reload_bot({"GECKO_STALL_BELOW_ENTRY_MIN": "60"})
    assert bot.STALL_BELOW_ENTRY_MIN == 60.0


# ── S30-C: MFI shadow gate env constants ───────────────────────────────


def test_mfi_shadow_threshold_defaults_to_70() -> None:
    os.environ.pop("GECKO_MFI_SHADOW_THRESHOLD", None)
    bot = _reload_bot({})
    assert bot.MFI_SHADOW_THRESHOLD == 70.0


def test_mfi_hard_gate_defaults_to_off() -> None:
    os.environ.pop("GECKO_MFI_HARD_GATE", None)
    bot = _reload_bot({})
    assert bot.MFI_HARD_GATE is False


def test_mfi_hard_gate_truthy_values() -> None:
    for v in ("1", "true", "True", "YES", "yes"):
        bot = _reload_bot({"GECKO_MFI_HARD_GATE": v})
        assert bot.MFI_HARD_GATE is True, f"expected True for {v!r}"


def test_mfi_hard_gate_falsy_values() -> None:
    for v in ("0", "false", "", "no", "off"):
        bot = _reload_bot({"GECKO_MFI_HARD_GATE": v})
        assert bot.MFI_HARD_GATE is False, f"expected False for {v!r}"


# ── S30-A: peak_pnl_pct logic (pure helper exercise) ────────────────────


def test_peak_pnl_tracks_new_high() -> None:
    """First update populates peak; later higher pnl overwrites; lower
    pnl does NOT overwrite. Mirrors the inline logic in the monitor loop:

        if pnl_pct > pos.get("peak_pnl_pct", float("-inf")):
            pos["peak_pnl_pct"] = pnl_pct
            pos["peak_pnl_ts"] = now_iso
    """
    pos: dict = {}
    for pnl, ts, expected_peak in [
        (0.5, "2026-06-01T00:00:00Z", 0.5),
        (0.8, "2026-06-01T00:01:00Z", 0.8),
        (0.3, "2026-06-01T00:02:00Z", 0.8),  # lower; peak unchanged
        (1.2, "2026-06-01T00:03:00Z", 1.2),
        (-0.5, "2026-06-01T00:04:00Z", 1.2),  # negative; peak unchanged
    ]:
        if pnl > pos.get("peak_pnl_pct", float("-inf")):
            pos["peak_pnl_pct"] = pnl
            pos["peak_pnl_ts"] = ts
        assert pos["peak_pnl_pct"] == expected_peak


def test_below_entry_since_tracking() -> None:
    """S30-B prerequisite: below_entry_since is set when pnl crosses
    negative, cleared when it returns positive.
    """
    pos: dict = {}
    sequence = [
        (0.3, None),              # positive, no entry
        (-0.1, "ts-1"),           # turns negative → sets
        (-0.5, "ts-1"),           # still negative → keeps original
        (0.05, None),             # turns positive → clears
        (-0.2, "ts-4"),           # negative again → sets new ts
    ]
    timestamps = ["ts-0", "ts-1", "ts-2", "ts-3", "ts-4"]
    for (pnl, expected_below_since), ts in zip(sequence, timestamps):
        if pnl < 0:
            if not pos.get("below_entry_since"):
                pos["below_entry_since"] = ts
        else:
            if pos.get("below_entry_since"):
                pos["below_entry_since"] = None
        assert pos.get("below_entry_since") == expected_below_since, (
            f"step {ts}: expected {expected_below_since!r}, got {pos.get('below_entry_since')!r}"
        )


# ── S30-C: MFI shadow_gates dict shape ─────────────────────────────────


def test_mfi_overbought_field_uses_threshold() -> None:
    """The local_panel shadow_gates dict (added in S30-C) flags
    mfi_overbought when MFI ≥ MFI_SHADOW_THRESHOLD."""
    bot = _reload_bot({"GECKO_MFI_SHADOW_THRESHOLD": "65"})
    threshold = bot.MFI_SHADOW_THRESHOLD
    assert threshold == 65.0
    # Reproduce the inline expression literally
    for mfi, expected in [(50.0, False), (64.9, False), (65.0, True), (80.0, True), (None, False)]:
        actual = mfi is not None and mfi >= threshold
        assert actual is expected, f"mfi={mfi} → {actual!r}, expected {expected!r}"
