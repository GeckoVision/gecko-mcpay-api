"""Boot-time provider-status resolution from the secrets manifest + live env.

WHY: a provider can be *enabled* (its flag says ON) yet *DARK* (a required cred
is the ``__unset__`` sentinel or absent), in which case it silently fail-OPENs
to ``[]`` / a fallback default — the exact class of bug that left OKX news dark
in prod (PR #150). This module computes, per provider, whether it is::

    LIVE      enabled AND every required cred is real
    DARK      enabled BUT a required cred is sentinel/missing (the footgun)
    disabled  not enabled (the intended default for un-provisioned providers)

:func:`resolve_all` returns one :class:`ProviderStatus` per manifest provider.
The gecko-api lifespan logs one line each (WARNING for DARK, INFO otherwise) so
a misconfigured deploy is visible in CloudWatch at boot, not on the first call.

SECRET-SAFETY (non-negotiable): this module NEVER reads or returns a secret
VALUE. It only ever asks "is this env var real, sentinel, or unset" via
:func:`_env_state`, mirroring the house ``_env_clean`` sentinel convention used
across the codebase (news_factory / safety_check / dune / okx_onchainos_market).
Reasons reference env-var NAMES only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

# The SSM placeholder the infra pushes for not-yet-provisioned creds so ECS can
# resolve `secrets:` at boot. Runtime code (and this module) treats it as unset.
SENTINEL = "__unset__"

StatusLiteral = Literal["LIVE", "DARK", "disabled"]
EnvState = Literal["real", "sentinel", "unset"]


def _env_state(name: str) -> EnvState:
    """Classify an env var as real / sentinel / unset WITHOUT returning its value.

    Mirrors the house ``_env_clean`` convention: the ``__unset__`` SSM sentinel
    counts as unset. The value itself never leaves this function.
    """
    raw = os.environ.get(name)
    if raw is None:
        return "unset"
    value = raw.strip()
    if value == "" or value == SENTINEL:
        return "sentinel" if value == SENTINEL else "unset"
    return "real"


def _is_real(name: str) -> bool:
    return _env_state(name) == "real"


@dataclass(frozen=True)
class ProviderStatus:
    """One provider's resolved boot status. Carries NO secret values."""

    name: str
    enabled: bool
    status: StatusLiteral
    reason: str
    fail_mode: str

    @property
    def is_dark(self) -> bool:
        return self.status == "DARK"


def _default_manifest_path() -> Path:
    """Locate ``infra/secrets-manifest.yml`` relative to the repo root.

    This file lives at
    ``packages/gecko-core/src/gecko_core/config/provider_status.py`` — four
    ``parents`` up from ``src`` reaches the package root, then four more to the
    repo root. We walk upward looking for ``infra/secrets-manifest.yml`` so the
    resolution is robust to worktrees and editable installs.
    """
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "infra" / "secrets-manifest.yml"
        if candidate.is_file():
            return candidate
    # Fall back to the conventional location; load will raise a clear error.
    return here.parents[5] / "infra" / "secrets-manifest.yml"


@lru_cache(maxsize=4)
def _load_manifest(path: str) -> dict[str, Any]:
    # Lazy import: PyYAML is a declared gecko-core dep, but keeping the import
    # local avoids paying it on every gecko_core import for callers that never
    # touch provider status.
    import yaml

    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or "providers" not in data:
        raise ValueError(f"secrets manifest at {path} is missing a `providers:` block")
    return data


def _is_enabled(enabled_when: dict[str, Any]) -> bool:
    """Evaluate a manifest ``enabled_when`` clause against the live env.

    Supported shapes (see secrets-manifest.yml header):
      {always: true}              -> always enabled
      {flag: NAME, value: V}      -> env[NAME] (sentinel-clean, lower) == V.lower()
      {flag: NAME, present: true} -> env[NAME] holds any real (non-sentinel) value
    """
    if enabled_when.get("always") is True:
        return True
    flag = enabled_when.get("flag")
    if not isinstance(flag, str):
        return False
    if enabled_when.get("present") is True:
        return _is_real(flag)
    expected = enabled_when.get("value")
    if expected is None:
        return False
    raw = os.environ.get(flag, "").strip()
    if raw == SENTINEL:
        raw = ""
    return raw.lower() == str(expected).lower()


def _resolve_one(name: str, spec: dict[str, Any]) -> ProviderStatus:
    enabled_when = spec.get("enabled_when") or {}
    fail_mode = str(spec.get("fail_mode", "open"))
    requires: list[str] = list(spec.get("requires") or [])
    requires_any_of: list[str] = list(spec.get("requires_any_of") or [])
    requires_together = bool(spec.get("requires_together", False))

    enabled = _is_enabled(enabled_when)
    if not enabled:
        return ProviderStatus(
            name=name,
            enabled=False,
            status="disabled",
            reason="not enabled (flag off / cred absent)",
            fail_mode=fail_mode,
        )

    missing = [v for v in requires if not _is_real(v)]

    # requires_any_of: at least one must be real (Helius OR QuickNode).
    any_of_ok = True
    if requires_any_of:
        any_of_ok = any(_is_real(v) for v in requires_any_of)

    if requires_together and missing:
        # A partial set is worse than none — it looks live and returns 401/[].
        return ProviderStatus(
            name=name,
            enabled=True,
            status="DARK",
            reason=(
                f"enabled but required cred SET incomplete: {missing} "
                f"sentinel/unset (fail_mode={fail_mode})"
            ),
            fail_mode=fail_mode,
        )
    if missing or not any_of_ok:
        if not any_of_ok:
            detail = f"none of {requires_any_of} is real"
        else:
            detail = f"{missing} sentinel/unset"
        return ProviderStatus(
            name=name,
            enabled=True,
            status="DARK",
            reason=f"enabled but {detail} (fail_mode={fail_mode})",
            fail_mode=fail_mode,
        )

    return ProviderStatus(
        name=name,
        enabled=True,
        status="LIVE",
        reason="enabled and all required creds present",
        fail_mode=fail_mode,
    )


def resolve_all(manifest_path: str | Path | None = None) -> list[ProviderStatus]:
    """Resolve every manifest provider against the current environment.

    Returns one :class:`ProviderStatus` per provider, in manifest order. Reads
    only env-var PRESENCE (never values). Pass ``manifest_path`` to override the
    auto-located ``infra/secrets-manifest.yml`` (used in tests).
    """
    path = str(manifest_path) if manifest_path is not None else str(_default_manifest_path())
    data = _load_manifest(path)
    providers: dict[str, Any] = data["providers"]
    return [_resolve_one(name, spec or {}) for name, spec in providers.items()]
