"""Config-parity + provider-status surface.

The secrets manifest (``infra/secrets-manifest.yml``) is the single source of
truth for which providers exist, how each is enabled, and which creds it needs.
:mod:`gecko_core.config.provider_status` reads it + the live env to compute a
boot-time LIVE / DARK / disabled status per provider — used by the gecko-api
startup banner and (via shared logic) the pre-deploy preflight script.
"""

from __future__ import annotations

from gecko_core.config.provider_status import (
    ProviderStatus,
    resolve_all,
)

__all__ = ["ProviderStatus", "resolve_all"]
