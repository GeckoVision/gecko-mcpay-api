"""Shared Helius RPC helper — getTransaction fetcher (free-tier path).

The snipe gate needs signer-level parsed swaps. The *paid* way is
``transactionSubscribe`` (a Helius extension; Developer+). The **free** way —
which this enables — is the standard pair every plan has:

    logsSubscribe(pool)  →  signature  →  getTransaction(sig)  →  parsed tx

i.e. a self-hosted equivalent of ``transactionSubscribe`` built from free
primitives, so the firewall runs at $0 until volume justifies the $49 Developer
flip. This module is the ``getTransaction`` half — a small ``httpx`` wrapper used
by BOTH the launch runner (swap ingest) and pool discovery (init-tx resolve), in
one place to avoid a circular import (discovery imports the runner).

Hotpath-clean: ``httpx`` + stdlib only. Fail-OPEN — any error returns ``None``.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# signature -> parsed tx dict (or None). Injectable so tests pass a fake.
TxFetcher = Callable[[str], Awaitable[dict[str, Any] | None]]

DEFAULT_HTTP_BASE = "https://mainnet.helius-rpc.com"


def make_tx_fetcher(api_key: str, *, http_base: str = DEFAULT_HTTP_BASE) -> TxFetcher:
    """Build a ``getTransaction`` fetcher (jsonParsed, confirmed). Free-tier call."""
    url = f"{http_base}/?api-key={api_key}"

    async def _fetch(signature: str) -> dict[str, Any] | None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                resp = await http.post(
                    url,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "getTransaction",
                        "params": [
                            signature,
                            {
                                "encoding": "jsonParsed",
                                "commitment": "confirmed",
                                "maxSupportedTransactionVersion": 0,
                            },
                        ],
                    },
                )
            result = resp.json().get("result")
            return result if isinstance(result, dict) else None
        except Exception as exc:  # fail-OPEN: a fetch error just skips this tx
            logger.warning(
                "helius_rpc.fetch_failed sig=%s err=%s", signature[:16], type(exc).__name__
            )
            return None

    return _fetch


__all__ = ["DEFAULT_HTTP_BASE", "TxFetcher", "make_tx_fetcher"]
