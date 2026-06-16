"""ENV-gated NewsProvider factory — Phase 2.1 (context-engineering, 2026-06-15).

PROBLEM (the wedge gap this closes): the production trade-panel path
(`run_trade_panel_with_retrieval`) is called with ``news_provider=None`` in
every prod entry point (gecko-api routes + main.py, gecko-mcp server). With no
live news, the `sentiment_analyst` voice runs corpus-only and degrades to a
constant ``neutral`` band (no contemporary narrative chunks to read).

This module is the single, provider-NEUTRAL injection point: prod entry points
call :func:`build_news_provider` and pass the result straight into the panel.
The panel never imports OKX (or any source) — it only knows the NewsProvider
protocol shape (see ``news_provider.py``).

CONTRACT — ENV-gated + fail-OPEN:
  - ``GECKO_NEWS_PROVIDER`` unset / ``none`` / ``off`` (the default) → returns
    ``None`` → byte-identical to today's behavior. No news call.
  - ``GECKO_NEWS_PROVIDER=okx`` → attempt to build the OKX direct-HTTP news
    provider. It needs ``OKX_NEWS_API_URL`` + ``OKX_API_KEY``. If EITHER is
    unprovisioned (unset or the SSM ``__unset__`` sentinel), the factory
    fails-OPEN to ``None`` — the prod call is NEVER broken by a half-configured
    flag. Nothing is logged at WARNING with secret material.

DEPLOYMENT NOTE (founder): enabling OKX news in ECS requires provisioning
``OKX_NEWS_API_URL`` + ``OKX_API_KEY`` in SSM (sentinel ``__unset__`` shipped
today) AND setting ``GECKO_NEWS_PROVIDER=okx``. Until both land, the runtime
default stays OFF and the panel behaves exactly as before.
"""

from __future__ import annotations

import logging
import os
from typing import Any

_log = logging.getLogger(__name__)


def _env_clean(name: str) -> str:
    """Env value, stripped, treating the SSM ``__unset__`` sentinel as empty.

    House convention (mirrors ``safety_check._env_clean``): infra pushes a
    ``__unset__`` sentinel for not-yet-provisioned keys so ECS resolves
    ``secrets:`` at boot without error; runtime code treats it as truly unset.
    """
    value = os.environ.get(name, "").strip()
    return "" if value == "__unset__" else value


def build_news_provider() -> Any | None:
    """Construct the configured NewsProvider, or ``None`` (today's behavior).

    Provider-neutral: the only knob is ``GECKO_NEWS_PROVIDER``. The panel
    accepts any object satisfying the ``NewsProvider`` protocol; this factory
    decides which (if any) to inject in production. Always returns ``None`` on
    any misconfiguration — fail-OPEN is the contract, the prod call is sacred.
    """
    flag = _env_clean("GECKO_NEWS_PROVIDER").lower()
    if flag in {"", "none", "off", "0", "false"}:
        return None

    if flag == "okx":
        return _build_okx_http_provider()

    # Unknown flag value: fail-OPEN, don't guess. Surface at INFO so a typo is
    # visible in logs without breaking the call.
    _log.info("news_factory.unknown_provider flag=%r — falling back to no news", flag)
    return None


def _build_okx_http_provider() -> Any | None:
    """Build the OKX direct-HTTP news provider if fully provisioned, else None.

    The existing ``OKXNewsProvider`` (okx_news_adapter.py) requires an
    ``mcp_call`` transport that the ECS task does NOT have. For the deployed
    path we use a direct-HTTP adapter driven by ``OKX_NEWS_API_URL`` +
    ``OKX_API_KEY``. Both must be real (non-sentinel) or we fail-OPEN to None.
    """
    base_url = _env_clean("OKX_NEWS_API_URL")
    api_key = _env_clean("OKX_API_KEY")
    if not base_url or not api_key:
        # Default state today: keys are __unset__ in SSM → stay OFF, identical
        # to the pre-Phase-2.1 path. Never log the key (or its absence-by-name
        # in a way that implies a value); a plain INFO is enough.
        _log.info(
            "news_factory.okx_unprovisioned has_url=%s has_key=%s — news OFF",
            bool(base_url),
            bool(api_key),
        )
        return None

    from gecko_core.orchestration.trade_panel.okx_http_news_adapter import (
        OKXHttpNewsProvider,
    )

    return OKXHttpNewsProvider(base_url=base_url, api_key=api_key)


__all__ = ["build_news_provider"]
