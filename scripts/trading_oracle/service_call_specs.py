"""Per-service request-shape registry for x402 calls.

Most Bazaar/paysh endpoints follow one of a small number of families:
  - chat_completions: POST with {"model": ..., "messages": [...]}
  - rest_query:       GET with ?q=... (today's default)
  - exa_search:       POST with {"query": ..., "numResults": ...}
  - graphql:          POST with {"query": "...", "variables": {...}}

A spec maps a service_id (or pattern) to:
  - which endpoint index (or selector) to use
  - HTTP method
  - body template (callable that takes the prompt + ctx and returns dict | None)
  - content type (default application/json for POST)
  - url_override (optional): per-call URL rewriter. When set, its return
    value REPLACES the chosen endpoint's URL before the request fires.
    Used by paysh providers whose catalog URL points at a non-routable
    base (paysponge gateway redirect, CoinGecko's templated path, etc.).

If a service has no spec, fall back to the legacy GET-with-?q= behavior.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

HttpMethod = Literal["GET", "POST"]

# A body builder takes (prompt, context) and returns a dict to JSON-encode,
# or None for no body (GET).
BodyBuilder = Callable[[str, Mapping[str, Any]], dict[str, Any] | None]

# A URL override takes (prompt, context) and returns the final URL string
# to call. Used to rewrite paysh provider URLs that don't match the
# catalog's advertised path (gateway redirects, templated placeholders).
UrlOverride = Callable[[str, Mapping[str, Any]], str]


@dataclass(frozen=True)
class CallSpec:
    """How to call one specific service via x402."""

    service_id_pattern: str  # exact id like "exa-ai" or wildcard "*chat_completions*"
    endpoint_predicate: Callable[[Mapping[str, Any]], bool]  # filter endpoints to pick one
    method: HttpMethod
    body_builder: BodyBuilder | None  # None means no body (GET)
    content_type: str = "application/json"
    # Optional URL rewriter. When set, the requester MUST use the returned
    # URL instead of the chosen endpoint's url. Default None preserves
    # legacy behavior (use endpoints[0].url verbatim).
    url_override: UrlOverride | None = None


def _coingecko_url_override(prompt: str, ctx: Mapping[str, Any]) -> str:
    """Rewrite paysh CoinGecko calls to /x402/onchain/search/pools.

    The catalog advertises a templated URL (``:solana_address`` placeholder)
    on the bare ``/x402/onchain`` path that 404s. The cleanest x402 endpoint
    for our protocol-name query is ``/onchain/search/pools`` which takes no
    path placeholders and accepts ``?query=<term>&network=<chain>``. We pin
    ``network=solana`` for the trading-oracle vertical and pass the prompt
    (or a ``protocol`` from ``ctx``) as ``query``.

    Confirmed against pro-api.coingecko.com on 2026-05-08 — returns 402
    with a v2 ``payment-required`` header (Base USDC 0.01, Solana USDC
    0.01 — pick whichever matches X402_NETWORK).
    """
    ctx_d = dict(ctx) if ctx else {}
    protocol = str(ctx_d.get("protocol") or "").strip()
    network = str(ctx_d.get("network") or "solana").strip() or "solana"
    query_term = protocol or (prompt.strip().split()[0] if prompt.strip() else "usdc")
    return (
        "https://pro-api.coingecko.com/api/v3/x402/onchain/search/pools"
        f"?query={quote(query_term)}&network={quote(network)}"
    )


def _perplexity_url_override(prompt: str, ctx: Mapping[str, Any]) -> str:
    """Rewrite paysh Perplexity calls to ``/v1/sonar`` on paysponge.

    The catalog URL is the bare host ``https://pplx.x402.paysponge.com``,
    which 302-redirects to the paysponge dashboard (HTML, not x402). The
    actual x402-bearing endpoint — confirmed via probe on 2026-05-08 —
    is ``POST /v1/sonar`` (chat-completions-style body) which returns 402
    with a v2 ``payment-required`` header.

    We don't carry path templates here; the rewrite is an unconditional
    suffix swap.
    """
    return "https://pplx.x402.paysponge.com/v1/sonar"


# Registry. Order matters — first matching pattern wins.
_REGISTRY: tuple[CallSpec, ...] = (
    # Exa search — POST /search with {"query": ...}
    CallSpec(
        service_id_pattern="exa-ai",
        endpoint_predicate=lambda ep: ep.get("method") == "POST" and "/search" in ep.get("url", ""),
        method="POST",
        body_builder=lambda prompt, ctx: {"query": prompt, "numResults": 5, "type": "auto"},
    ),
    # OpenAI-compatible chat completions (Venice, Bankr, BlockRun, OpenAI itself).
    # Matched primarily on the endpoint URL substring "chat/completions".
    CallSpec(
        service_id_pattern="*chat/completions*",
        endpoint_predicate=lambda ep: (
            ep.get("method") == "POST" and "chat/completions" in ep.get("url", "")
        ),
        method="POST",
        body_builder=lambda prompt, ctx: {
            "model": ctx.get("model", "gpt-4o-mini"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500,
        },
    ),
    # Anthropic-compatible messages (Bankr's /v1/messages).
    CallSpec(
        service_id_pattern="*messages*",
        endpoint_predicate=lambda ep: (
            ep.get("method") == "POST" and "/messages" in ep.get("url", "")
        ),
        method="POST",
        body_builder=lambda prompt, ctx: {
            "model": ctx.get("model", "claude-3-5-sonnet-latest"),
            "max_tokens": 1500,
            "messages": [{"role": "user", "content": prompt}],
        },
    ),
    # Paysh — CoinGecko Onchain DEX. Catalog URL templates a placeholder we
    # don't substitute; rewrite to /x402/onchain/search/pools (a real x402
    # endpoint) and pin network=solana for the trading-oracle vertical.
    # GET, no body — query goes in the rewritten URL.
    CallSpec(
        service_id_pattern="paysponge/coingecko",
        endpoint_predicate=lambda ep: True,  # url_override replaces it anyway
        method="GET",
        body_builder=None,
        url_override=_coingecko_url_override,
    ),
    # Paysh — Perplexity (paysponge gateway). Catalog URL is the bare host
    # which 302s to paysponge's dashboard; rewrite to /v1/sonar (the actual
    # x402-bearing path, confirmed via probe). POST with chat-completions
    # body shape.
    CallSpec(
        service_id_pattern="paysponge/perplexity",
        endpoint_predicate=lambda ep: True,  # url_override replaces it anyway
        method="POST",
        body_builder=lambda prompt, ctx: {
            "model": ctx.get("model", "sonar"),
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1500,
        },
        url_override=_perplexity_url_override,
    ),
)


def _matches(pattern: str, value: str) -> bool:
    """Simple glob match: '*' = any, exact otherwise."""
    if pattern == "*":
        return True
    if pattern.startswith("*") and pattern.endswith("*"):
        return pattern.strip("*") in value
    if pattern.startswith("*"):
        return value.endswith(pattern.lstrip("*"))
    if pattern.endswith("*"):
        return value.startswith(pattern.rstrip("*"))
    return pattern == value


def find_spec_for(
    service_id: str, endpoints: list[Mapping[str, Any]]
) -> tuple[CallSpec | None, Mapping[str, Any] | None]:
    """Return (spec, chosen_endpoint) or (None, None) if no spec matches.

    Tries each spec in order; for the first whose service_id_pattern matches
    AND for which at least one endpoint passes endpoint_predicate, returns
    that spec + that endpoint.
    """
    for spec in _REGISTRY:
        if not (
            _matches(spec.service_id_pattern, service_id)
            or any(_matches(spec.service_id_pattern, str(ep.get("url", ""))) for ep in endpoints)
        ):
            continue
        for ep in endpoints:
            if spec.endpoint_predicate(ep):
                return spec, ep
    return None, None


def registry_size() -> int:
    """Count of registered specs (used for diagnostics / status reporting)."""
    return len(_REGISTRY)
