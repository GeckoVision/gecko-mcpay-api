"""S20-FIX-01 — env-tunable per-voice timeout for pro tier orchestration.

The architect voice on DeepSeek V4 Pro legitimately exceeds 60s on deep
prompts. The 60s hardcode was clipping 1/5 of the panel. We bumped the
default to 120s and made it env-tunable via GECKO_PRO_VOICE_TIMEOUT_S.

These tests exercise constant resolution only — the actual AG2
GroupChat behavior is integration territory, covered elsewhere.
"""

from __future__ import annotations

import importlib
import logging

import pytest


def _reload_pro_module():
    """Reimport the pro orchestration module so the module-level constant
    re-resolves against the current process env."""
    import gecko_core.orchestration.pro as pro_mod

    return importlib.reload(pro_mod)


def test_default_timeout_is_120_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GECKO_PRO_VOICE_TIMEOUT_S", raising=False)
    pro_mod = _reload_pro_module()
    assert pro_mod._PER_VOICE_TIMEOUT_S == 120.0
    # Back-compat alias must track the resolved value.
    assert pro_mod._VOICE_TIMEOUT_SECONDS == 120.0


def test_env_override_applies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_PRO_VOICE_TIMEOUT_S", "180")
    pro_mod = _reload_pro_module()
    assert pro_mod._PER_VOICE_TIMEOUT_S == 180.0
    assert pro_mod._VOICE_TIMEOUT_SECONDS == 180.0


def test_invalid_env_falls_back_to_default_with_warn(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("GECKO_PRO_VOICE_TIMEOUT_S", "not_a_number")
    with caplog.at_level(logging.WARNING, logger="gecko_core.orchestration.pro"):
        pro_mod = _reload_pro_module()
    assert pro_mod._PER_VOICE_TIMEOUT_S == 120.0
    # The fallback path must surface a WARN log so operators can spot the
    # misconfiguration.
    warn_messages = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("not_a_number" in m for m in warn_messages), warn_messages


def test_resolver_helper_handles_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GECKO_PRO_VOICE_TIMEOUT_S", "")
    pro_mod = _reload_pro_module()
    assert pro_mod._PER_VOICE_TIMEOUT_S == 120.0


def teardown_module(_module: object) -> None:
    """Restore the module to its env-default state so we don't leak a
    test-set timeout into sibling tests sharing the same import."""
    import os

    os.environ.pop("GECKO_PRO_VOICE_TIMEOUT_S", None)
    _reload_pro_module()
