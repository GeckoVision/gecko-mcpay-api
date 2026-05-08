"""Trading-oracle live ingest CLI.

This is the **scaffolding** for the one-shot live ingest run. The live
invocation step is operator-gated (founder must fund a buyer wallet on
Solana for paysh and on Base for bazaar — see
``memory/project_buyer_wallet_blocker_2026_05_08.md``). This script is
"ready to fire once funds land": you can dry-run today, and flip to live
the moment the buyer wallet is funded and a concrete ``PaidRequester``
implementation is wired into ``_build_paid_requester`` below.

Usage:

    # Plan-only against a recorded listings fixture (zero network I/O,
    # zero Mongo writes):
    uv run python scripts/trading_oracle/run.py \\
        --dry-run --listings-json path/to/listings.json

    # Live (after operator funds the buyer wallets — DO NOT run blindly):
    GECKO_X402_MODE=live \\
    uv run python scripts/trading_oracle/run.py \\
        --cap-usd 5.00 --source paysh

Flags:
    --cap-usd FLOAT   Hard $ cap per run. Default $5.00 (founder funds
                      $5 per network — paysh on Solana, bazaar on Base).
    --dry-run         Plan only. No catalog fetch, no charges, no writes.
                      Pair with --listings-json to plan against fixtures.
    --source CHOICE   ``paysh`` (Solana) | ``bazaar`` (Base) | ``both``.
                      Default ``both``. Use this to run one network at a
                      time since each is funded independently.
    --listings-json PATH  Optional JSON file containing pre-loaded
                      listings (planner shape — see ``_to_planner_listing``).
                      When set, the catalog fetch is skipped entirely;
                      the planner runs against the file. Required for
                      dry-run if you want non-empty output.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

import click
from gecko_core.ingestion.trading_oracle.run_live_ingest import (
    PlannedCall,
    execute_plan,
    plan_ingest,
)

log = logging.getLogger("trading_oracle.run")


# ---------------------------------------------------------------------------
# Buyer-side per-call cap helper.
#
# Per the x402 spec, ``accepts[].maxAmountRequired`` is a MAXIMUM the seller
# might charge — not a guaranteed amount. Sellers like Venice quote a per-1M-
# token cap (e.g. $10) but settle a tiny fraction per call. The buyer should
# protect itself with an explicit per-call hard limit and accept any
# advertised max <= that limit. Actual settlement is tracked separately from
# the response (X-Payment-Receipt header) and only that amount is charged
# against the session budget.
# ---------------------------------------------------------------------------


def _check_advertised_within_limit(
    accepts: Sequence[Mapping[str, Any]],
    per_call_limit_usd: Decimal,
) -> Decimal:
    """Validate the seller's advertised max against the buyer's hard limit.

    Returns the advertised max in USD when within limit. Raises
    ``RuntimeError`` with a clear message when the seller's advertised
    ``maxAmountRequired`` exceeds the buyer's per-call cap.

    USDC has 6 decimals — atomic units are divided by 1e6.
    """
    if not accepts:
        raise RuntimeError("402 carried empty accepts[]")
    chosen = accepts[0]
    advertised_atomic = int(chosen.get("maxAmountRequired") or chosen.get("amount") or "0")
    advertised_usd = Decimal(advertised_atomic) / Decimal(10**6)
    if advertised_usd > per_call_limit_usd:
        raise RuntimeError(
            f"x402 advertised maxAmount ${advertised_usd:.4f} exceeds "
            f"buyer per-call hard limit ${per_call_limit_usd:.4f}"
        )
    return advertised_usd


def _extract_settled_amount(
    headers: Mapping[str, str],
    *,
    fallback_usd: Decimal,
) -> Decimal:
    """Parse the actual settled amount from response headers.

    Looks for (in priority): ``X-Payment-Receipt`` (USDC atomic),
    ``X-Settled-Amount`` (USDC atomic). Falls back to ``fallback_usd``
    (the advertised max) when no usable header is present.
    """
    for key in ("X-Payment-Receipt", "X-Settled-Amount", "x-payment-receipt", "x-settled-amount"):
        raw = headers.get(key)
        if not raw:
            continue
        try:
            return Decimal(int(raw)) / Decimal(10**6)
        except (TypeError, ValueError):
            # Header present but not a plain atomic int (could be a JSON
            # blob); ignore and try the next variant.
            continue
    return fallback_usd


# ---------------------------------------------------------------------------
# URL template substitution.
#
# Bazaar listings often have endpoint URLs like
# https://api.zerion.io/v1/wallets/{address}/portfolio. Without
# substitution they 402 with empty accepts[]. We substitute the buyer's
# own wallet address so the call shape is at least valid.
# ---------------------------------------------------------------------------

import contextlib  # noqa: E402
import re as _re  # noqa: E402  (kept local to module concern)


def _substitute_url_template(url: str, *, wallet_address: str) -> str:
    """Replace {address} placeholders in bazaar endpoint URLs with the buyer wallet.

    Bazaar listings often have endpoint URLs like
    https://api.zerion.io/v1/wallets/{address}/portfolio. Without
    substitution they 402 with empty accepts[]. We substitute the buyer's
    own wallet address so the call shape is at least valid.
    """
    substituted = url.replace("{address}", wallet_address)
    leftover = _re.findall(r"\{[^}]+\}", substituted)
    if leftover:
        log.warning(
            "URL %r still contains unresolved placeholders %s after substitution; issuing as-is",
            substituted,
            leftover,
        )
    return substituted


# ---------------------------------------------------------------------------
# Listing-shape adapters.
#
# paysh_manifest / bazaar_manifest emit catalog rows whose shapes don't match
# the planner's expected ``{name, tags, price_usd, provider_kind, fqn, ...}``
# directly — so map at the CLI layer (per the task scope: do NOT modify the
# source modules).
# ---------------------------------------------------------------------------


# Buyer-side URL blocklist: hostnames whose x402 implementation is known
# non-standard and that our buyer cannot settle against. Venice uses
# ``X-Sign-In-With-X`` SIWE auth + a top-up flow rather than per-call
# EIP-3009 in ``X-PAYMENT``, so we skip any of its gateway URLs and let
# the registry fall through to a sibling endpoint (Bankr / BlockRun /...).
_VENICE_BLOCKLIST: tuple[str, ...] = ("venice.ai",)


def _is_blocked_endpoint_url(url: str) -> bool:
    """True if ``url`` matches any host in ``_VENICE_BLOCKLIST``."""
    return any(host in url for host in _VENICE_BLOCKLIST)


def _to_planner_listing_paysh(provider: Any) -> dict[str, Any]:
    """Map a ``PayshCatalogProvider`` to the planner's listing dict.

    Pulls min_price, fqn, category, and synthesizes a tag list so the
    Solana-DeFi filter can match. paysh providers are Solana-native by
    construction; we tag them as such.

    Emits an ``endpoints`` list (1+ entries) so the per-service-call
    registry can pick a working endpoint when a manifest exposes more
    than one. paysh providers historically expose a single ``service_url``;
    when their manifest carries an ``endpoints`` collection we surface
    each entry's url + method.
    """
    name = getattr(provider, "title", None) or getattr(provider, "fqn", "<unknown>")
    description = getattr(provider, "description", "") or ""
    category = getattr(provider, "category", "") or ""
    tags = ["solana", category] if category else ["solana"]
    min_price = float(getattr(provider, "min_price_usd", 0.0))
    service_url = getattr(provider, "service_url", "") or ""
    raw_endpoints = list(getattr(provider, "endpoints", []) or [])
    endpoints: list[dict[str, Any]] = []
    for ep in raw_endpoints:
        ep_url = getattr(ep, "path", None) or getattr(ep, "url", None) or ""
        ep_method = (getattr(ep, "method", None) or "GET").upper()
        if ep_url:
            endpoints.append({"url": ep_url, "method": ep_method})
    if not endpoints and service_url:
        endpoints = [{"url": service_url, "method": "GET"}]
    return {
        "name": name,
        "description": description,
        "tags": tags,
        "price_usd": Decimal(str(min_price)),
        "provider_kind": "paysh_live",
        "fqn": getattr(provider, "fqn", ""),
        "service_url": service_url,
        "endpoints": endpoints,
    }


def _to_planner_listing_bazaar(service: Any) -> dict[str, Any]:
    """Map a ``BazaarService`` to the planner's listing dict.

    Bazaar services often expose 3-6 alternate gateway endpoints for the
    same logical service (e.g. Claude is reachable via Venice, Bankr,
    BlockRun). Carry the full ``endpoints`` list — each entry as
    ``{"url", "method"}`` — so the per-service-call registry can pick the
    first compatible endpoint instead of being starved by a single-URL
    listing. ``service_url`` is preserved (= ``endpoints[0].url``) for
    backward compatibility with callers that haven't been updated.

    ``price_usd`` is the MIN across all endpoints (cheapest path wins).
    """
    name = getattr(service, "name", None) or getattr(service, "id", "<unknown>")
    description = getattr(service, "description", "") or ""
    category = getattr(service, "category", "") or ""
    networks = list(getattr(service, "networks", []) or [])
    tags = list(networks)
    if category:
        tags.append(category)
    raw_endpoints = list(getattr(service, "endpoints", []) or [])
    endpoints: list[dict[str, Any]] = []
    prices: list[float] = []
    for ep in raw_endpoints:
        ep_url = getattr(ep, "url", "") or ""
        ep_method = (getattr(ep, "method", None) or "GET").upper()
        if ep_url:
            endpoints.append({"url": ep_url, "method": ep_method})
        pricing = getattr(ep, "pricing", None)
        if pricing is not None:
            candidate = getattr(pricing, "minAmount", None) or getattr(pricing, "amount", None)
            if candidate:
                with contextlib.suppress(TypeError, ValueError):
                    prices.append(float(candidate))
    min_price = min(prices) if prices else 0.0
    endpoint_url = endpoints[0]["url"] if endpoints else ""
    return {
        "name": name,
        "description": description,
        "tags": tags,
        "price_usd": Decimal(str(min_price)),
        "provider_kind": "bazaar_live",
        "fqn": getattr(service, "id", ""),
        "service_url": endpoint_url,
        "endpoints": endpoints,
    }


# ---------------------------------------------------------------------------
# Catalog fetch (live-only; dry-run never touches the network).
# ---------------------------------------------------------------------------


async def _load_listings_from_catalogs(source: str) -> list[dict[str, Any]]:
    """Fetch live catalogs and adapt to planner shape.

    NOTE: this is the only function that touches the network in live mode.
    Dry-run skips it entirely (--listings-json is the dry-run input path).
    """
    listings: list[dict[str, Any]] = []
    if source in ("paysh", "both"):
        from gecko_core.sources.paysh_manifest import fetch_catalog as fetch_paysh_catalog

        paysh_result = await fetch_paysh_catalog()
        providers = (paysh_result.payload or {}).get("providers", []) if paysh_result else []
        listings.extend(_to_planner_listing_paysh(p) for p in providers)
    if source in ("bazaar", "both"):
        from gecko_core.sources.bazaar_manifest import fetch_catalog as fetch_bazaar_catalog

        bazaar_result = await fetch_bazaar_catalog()
        services = (bazaar_result.payload or {}).get("services", []) if bazaar_result else []
        listings.extend(_to_planner_listing_bazaar(s) for s in services)
    return listings


def _load_listings_from_file(path: Path) -> list[dict[str, Any]]:
    """Load planner-shaped listings from a JSON fixture (no network I/O)."""
    raw = json.loads(path.read_text())
    if not isinstance(raw, list):
        raise click.ClickException(f"--listings-json {path} must contain a JSON array")
    out: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        d = dict(entry)
        # Coerce price_usd to Decimal — JSON has no Decimal type.
        if "price_usd" in d and not isinstance(d["price_usd"], Decimal):
            d["price_usd"] = Decimal(str(d["price_usd"]))
        # Synthesize endpoints[] when an older fixture only carries
        # service_url. Each entry needs at minimum {"url", "method"}.
        eps = d.get("endpoints")
        if not isinstance(eps, list) or not eps:
            su = d.get("service_url") or ""
            d["endpoints"] = [{"url": su, "method": "GET"}] if su else []
        else:
            normalized: list[dict[str, Any]] = []
            for ep in eps:
                if not isinstance(ep, Mapping):
                    continue
                url_v = ep.get("url") or ""
                method_v = (ep.get("method") or "GET").upper()
                if url_v:
                    normalized.append({"url": url_v, "method": method_v})
            d["endpoints"] = normalized
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Live charge + write seams.
#
# These are the I/O legs. Both are constructed lazily so importing this
# module (and the dry-run code path) never loads them.
# ---------------------------------------------------------------------------


# Module-level memo so _build_paid_requester returns the same object every
# time within a run (the underlying httpx client is reusable, and the buyer
# nonce semantics are intent-id scoped, not requester-instance scoped).
_PAID_REQUESTER_SINGLETON: Any | None = None

# Buyer-side per-call hard limit in USD. Set by ``main`` from the CLI flag
# ``--max-per-call-usd`` (default $0.10) and read by ``_LiveX402PaidRequester``
# when it inspects the seller's advertised maxAmount.
_PER_CALL_HARD_LIMIT_USD: Decimal = Decimal("0.10")


def _build_paid_requester() -> Any:
    """Construct a live x402 ``PaidRequester`` from env. Raises if config missing.

    Reads (in priority order):
        TWITSH_WALLET_ADDRESS, TWITSH_WALLET_PRIVATE_KEY  (existing prod path)
        GECKO_BUYER_WALLET_ADDRESS, GECKO_BUYER_WALLET_PRIVATE_KEY  (new path)
        X402_NETWORK            (default base-mainnet)
        GECKO_X402_MODE         (must be 'live')

    Returns a ``_LiveX402PaidRequester`` — the concrete adapter that
    conforms to ``gecko_core.sources.paysh_live.PaidRequester`` /
    ``bazaar_live.PaidRequester``. The adapter performs the x402 v2 buyer
    dance (GET → 402 → sign X-PAYMENT → GET) using
    ``cdp_x402_client._build_payment_payload`` so the EIP-3009 vs Permit2
    signing path matches the seller-side fix in 19d0a83.
    """
    global _PAID_REQUESTER_SINGLETON
    if _PAID_REQUESTER_SINGLETON is not None:
        return _PAID_REQUESTER_SINGLETON

    mode = os.environ.get("GECKO_X402_MODE", "stub")
    if mode != "live":
        raise click.ClickException(
            f"GECKO_X402_MODE={mode!r}; live x402 requester requires "
            "GECKO_X402_MODE=live. Aborting before any network call."
        )

    private_key = os.environ.get("TWITSH_WALLET_PRIVATE_KEY") or os.environ.get(
        "GECKO_BUYER_WALLET_PRIVATE_KEY"
    )
    address = os.environ.get("TWITSH_WALLET_ADDRESS") or os.environ.get(
        "GECKO_BUYER_WALLET_ADDRESS"
    )
    if not private_key or not address:
        raise click.ClickException(
            "buyer wallet env not set. Export one of these pairs before "
            "running live: "
            "(TWITSH_WALLET_ADDRESS + TWITSH_WALLET_PRIVATE_KEY) or "
            "(GECKO_BUYER_WALLET_ADDRESS + GECKO_BUYER_WALLET_PRIVATE_KEY)."
        )

    network = os.environ.get("X402_NETWORK", "base-mainnet")

    _PAID_REQUESTER_SINGLETON = _LiveX402PaidRequester(
        payer_private_key=private_key,
        payer_address=address,
        network=network,
        per_call_hard_limit_usd=_PER_CALL_HARD_LIMIT_USD,
    )
    return _PAID_REQUESTER_SINGLETON


class _LiveX402PaidRequester:
    """Adapter: ``PaidRequester`` Protocol over the x402 v2 buyer dance.

    Why this lives here and not in ``gecko-core``: there is exactly one
    consumer (this CLI) and the buyer dance is a few dozen lines once you
    reuse ``cdp_x402_client._build_payment_payload``. Promoting it to core
    can wait until a second caller appears (per CLAUDE.md "split when there
    are 2 callers").

    Wire flow per ``request(url, query, max_cost_usd, timeout_seconds)``:

      1. GET url with query as ``?q=`` — expect 402.
      2. Parse ``accepts[]`` from the 402 body. Pick the first whose
         ``maxAmountRequired`` (USDC atomic) is ≤ ``max_cost_usd``.
      3. Build a signed X-PAYMENT header via ``_build_payment_payload``.
      4. Re-issue the GET with X-PAYMENT. Resource server settles via its
         own facilitator and returns 200 + body + ``X-PAYMENT-RESPONSE``.
      5. Wrap in ``PaidResponse`` for the caller.
    """

    def __init__(
        self,
        *,
        payer_private_key: str,
        payer_address: str,
        network: str,
        per_call_hard_limit_usd: Decimal = Decimal("0.10"),
    ) -> None:
        self._payer_private_key = payer_private_key
        self._payer_address = payer_address
        self._network = network
        self._per_call_hard_limit_usd = per_call_hard_limit_usd
        # Per-call context: full endpoints[] from the active listing,
        # plus the service_id (fqn) used for registry lookup. Set by
        # ``set_listing_context`` before each ``request`` call so the
        # registry can pick the right endpoint when multiple gateways
        # exist for one service.
        self._current_endpoints: list[Mapping[str, Any]] = []
        self._current_service_id: str = ""

    def set_listing_context(
        self,
        *,
        service_id: str,
        endpoints: Sequence[Mapping[str, Any]],
    ) -> None:
        """Stash the active listing's endpoints + service_id for the next call.

        ``request`` is invoked by gecko-core's ``fetch_paid`` with a single
        URL — but the registry needs the full endpoints[] to pick the
        compatible one. This is the seam that threads the listing context
        through without modifying core.
        """
        self._current_endpoints = [dict(ep) for ep in endpoints]
        self._current_service_id = service_id

    def _build_request_for_service(
        self,
        *,
        url: str,
        prompt: str,
    ) -> tuple[str, str, dict[str, Any] | None]:
        """Resolve (url, method, body) for this listing.

        Consults ``service_call_specs.find_spec_for`` against the active
        listing's full endpoints list (set by ``set_listing_context``).
        Endpoints whose URL hits ``_VENICE_BLOCKLIST`` are filtered out
        before lookup — Venice's x402 is non-standard SIWE and our buyer
        cannot settle there, so we prefer Bankr / BlockRun siblings.

        Falls back to a synthetic single-endpoint list when no listing
        context was stashed, and to ``(url, "GET", None)`` when no spec
        matches — the legacy paysh-style REST behavior.
        """
        from urllib.parse import urlparse

        # Sibling-module import: run.py is executed as a script, so
        # scripts/trading_oracle/ is on sys.path[0]. The test suite loads
        # service_call_specs directly via importlib.
        from service_call_specs import find_spec_for  # type: ignore[import-not-found]

        if self._current_endpoints:
            endpoints_for_lookup: list[Mapping[str, Any]] = [
                ep
                for ep in self._current_endpoints
                if not _is_blocked_endpoint_url(str(ep.get("url", "")))
            ]
            service_id = self._current_service_id or (urlparse(url).hostname or "")
        else:
            endpoints_for_lookup = [{"url": url, "method": "POST"}]
            service_id = urlparse(url).hostname or ""

        if not endpoints_for_lookup:
            # Every endpoint blocklisted — caller will fall back to GET.
            return url, "GET", None

        spec, ep = find_spec_for(service_id, endpoints_for_lookup)
        if spec is None or ep is None or spec.body_builder is None:
            return url, "GET", None
        chosen_url = str(ep.get("url") or url)
        # Substitute {address} on the chosen URL — the caller already did
        # this on the original ``url``, but if the registry routed us to
        # a sibling endpoint with its own template, re-apply.
        chosen_url = _substitute_url_template(chosen_url, wallet_address=self._payer_address)
        body = spec.body_builder(prompt, {})
        return chosen_url, spec.method, body

    async def request(
        self,
        *,
        url: str,
        query: str,
        max_cost_usd: float,
        timeout_seconds: float,
    ) -> Any:
        # Lazy imports — keep this module importable in dry-run mode
        # without dragging in the x402 SDK.
        import base64

        import httpx
        from gecko_core.payments.cdp_x402_client import (
            _build_payment_payload,
            _build_payment_requirements,
        )
        from gecko_core.sources.paysh_live import PaidResponse

        # Substitute {address} (and warn on other unresolved placeholders) so
        # bazaar wallet-portfolio listings (e.g. Zerion) get a valid URL shape
        # before the 402 probe. Without this, the seller returns 402 with an
        # empty accepts[] and the buyer dance aborts before any payment fires.
        url = _substitute_url_template(url, wallet_address=self._payer_address)

        # Resolve method + body from the per-service registry. Default is
        # GET-with-?q= (legacy paysh REST). POST listings (chat completions,
        # Exa search, Anthropic /v1/messages) get a JSON body shaped per the
        # service.
        url, method, body = self._build_request_for_service(url=url, prompt=query)

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            # Step 1: probe for 402.
            params: dict[str, str] = {"q": query} if method == "GET" else {}
            if method == "GET":
                probe = await client.get(url, params=params)
            else:
                probe = await client.post(
                    url,
                    json=body,
                    headers={"Content-Type": "application/json"},
                )
            if probe.status_code == 200:
                # Free endpoint — should not happen for a paid listing,
                # but degrade gracefully by returning the body unpaid.
                text = probe.text
                content_type = probe.headers.get("content-type", "text/plain")
                body: Any = probe.json() if "json" in content_type else text
                return PaidResponse(
                    status_code=200,
                    cost_usd=0.0,
                    response_body=body,
                    response_text=text,
                    content_type=content_type,
                    tx_signature=None,
                    response_sha=hashlib.sha256(text.encode()).hexdigest(),
                    headers=dict(probe.headers),
                )
            if probe.status_code != 402:
                raise RuntimeError(
                    f"expected 402 challenge from {url!r}, got {probe.status_code}: "
                    f"{probe.text[:256]!r}"
                )

            challenge = probe.json()
            accepts = challenge.get("accepts") or []
            if not accepts:
                raise RuntimeError(f"402 from {url!r} carried empty accepts[]")
            # Treat advertised maxAmountRequired as a SELLER-side cap, not a
            # guaranteed charge. Reject only if it exceeds the buyer's
            # per-call hard limit; ``max_cost_usd`` (planner-listing posted
            # price) is informational here and feeds the BudgetGuard at the
            # session level via the actual settled amount returned below.
            advertised_usd = _check_advertised_within_limit(accepts, self._per_call_hard_limit_usd)
            log.info(
                "x402 402 from %s: advertised max $%.4f (within buyer per-call limit $%.4f)",
                url,
                float(advertised_usd),
                float(self._per_call_hard_limit_usd),
            )
            chosen = accepts[0]

            sdk_requirements = _build_payment_requirements(
                amount_usd=advertised_usd,
                pay_to=chosen["payTo"],
                network=chosen.get("network", self._network),
                asset=chosen["asset"],
                resource_url=url,
                max_timeout_seconds=int(chosen.get("maxTimeoutSeconds", 60)),
            )
            from uuid import uuid4

            intent_id = f"trading-oracle-{uuid4().hex[:16]}"
            sdk_payload = _build_payment_payload(
                intent_id=intent_id,
                requirements=sdk_requirements,
                payer_private_key=self._payer_private_key,
                resource_url=url,
            )
            payload_bytes = json.dumps(
                sdk_payload.model_dump(by_alias=True, mode="json"),
                separators=(",", ":"),
            ).encode("utf-8")
            x_payment = base64.b64encode(payload_bytes).decode("ascii")

            # Step 4: re-issue with X-PAYMENT, preserving the original
            # method and body so signed requirements still bind to the
            # exact request shape the seller authorized.
            paid_headers = {"X-PAYMENT": x_payment, "Accept": "application/json"}
            if method == "GET":
                paid = await client.get(url, params=params, headers=paid_headers)
            else:
                paid = await client.post(
                    url,
                    json=body,
                    headers={**paid_headers, "Content-Type": "application/json"},
                )
            if paid.status_code != 200:
                raise RuntimeError(
                    f"paid {method} {url!r} returned {paid.status_code}: {paid.text[:256]!r}"
                )
            tx_signature: str | None = None
            settle_header = paid.headers.get("X-PAYMENT-RESPONSE")
            if settle_header:
                try:
                    decoded = base64.b64decode(settle_header).decode("utf-8")
                    settle = json.loads(decoded)
                    tx_signature = settle.get("transaction") or settle.get("txHash")
                except Exception:
                    tx_signature = None

            text = paid.text
            content_type = paid.headers.get("content-type", "text/plain")
            try:
                body = paid.json() if "json" in content_type else text
            except Exception:
                body = text

            # Settlement amount: prefer X-Payment-Receipt / X-Settled-Amount
            # (actual atomic USDC settled). Fall back to the advertised max
            # when no header is present.
            #
            # Invariant: by the time we get here, we already accepted the
            # advertised max as <= per-call hard limit (raised in
            # ``_check_advertised_within_limit`` otherwise), so falling back
            # to advertised_usd is bounded.
            assert advertised_usd <= self._per_call_hard_limit_usd, (
                "advertised_usd should already be capped by the per-call "
                "hard limit before we get here"
            )
            settled_usd = _extract_settled_amount(paid.headers, fallback_usd=advertised_usd)
            log.info(
                "x402 settled %s: actual=$%.6f advertised_max=$%.4f (header_present=%s)",
                url,
                float(settled_usd),
                float(advertised_usd),
                settled_usd != advertised_usd,
            )
            return PaidResponse(
                status_code=200,
                cost_usd=float(settled_usd),
                response_body=body,
                response_text=text,
                content_type=content_type,
                tx_signature=tx_signature,
                response_sha=hashlib.sha256(text.encode()).hexdigest(),
                headers=dict(paid.headers),
            )


async def _charge_and_fetch(call: PlannedCall) -> dict[str, Any]:
    """Issue one paid x402 call against the listing's source.

    Routes to ``paysh_live.fetch_paid`` or ``bazaar_live.fetch_paid`` based
    on ``provider_kind``. Both accept a ``PaidRequester`` for the wire
    seam; we build it lazily once per run via ``_build_paid_requester``.

    Returns the dict shape ``execute_plan`` expects:
    ``{"body": <text>, "fqn": <fqn>}``. On a non-text response or
    upstream error, raises — ``execute_plan`` collects into the failure
    list rather than crashing the run.
    """
    # Import the planner-listing lookup helpers + the prompt lazily so
    # dry-run never drags them into the import path.
    from gecko_core.ingestion.trading_oracle.prompt import TRADING_ORACLE_PROMPT

    pk = call.listing.get("provider_kind", "paysh_live")
    fqn = call.listing.get("fqn", "")
    service_url = call.listing.get("service_url", "")
    listing_endpoints = call.listing.get("endpoints") or []
    # If endpoints[0] is on the blocklist (Venice) but a sibling is not,
    # promote the first non-blocked endpoint so gecko-core's
    # ``_select_endpoint`` (which always picks index 0) issues the probe
    # against the working gateway.
    if listing_endpoints:
        non_blocked = [
            ep for ep in listing_endpoints if not _is_blocked_endpoint_url(str(ep.get("url", "")))
        ]
        if non_blocked:
            service_url = str(non_blocked[0].get("url") or service_url)
    requester = _build_paid_requester()
    # Stash the full endpoints[] on the requester so its ``find_spec_for``
    # call sees siblings (Bankr/BlockRun) and can route around blocked
    # gateways (Venice). Falls back to legacy synthetic-single-endpoint
    # behavior when the listing has no endpoints[] field (older fixtures).
    if hasattr(requester, "set_listing_context"):
        requester.set_listing_context(
            service_id=fqn,
            endpoints=listing_endpoints,
        )

    if pk == "paysh_live":
        from gecko_core.sources.paysh_live import fetch_paid as paysh_fetch_paid
        from gecko_core.sources.paysh_manifest import PayshCatalogProvider

        # Reconstruct the minimum PayshCatalogProvider the live module
        # expects, from the planner-listing dict (we drop the catalog
        # passthrough from CLI → dispatcher).
        provider = PayshCatalogProvider(
            fqn=fqn,
            title=str(call.listing.get("name", "")),
            description=str(call.listing.get("description", "")),
            category=str(call.listing.get("category", "")),
            min_price_usd=float(call.listing.get("price_usd", 0.0)),
            service_url=service_url,
        )
        result = await paysh_fetch_paid(
            fqn,
            TRADING_ORACLE_PROMPT,
            x402_client=requester,
            catalog_providers=[provider],
        )
    elif pk == "bazaar_live":
        from gecko_core.sources.bazaar_live import fetch_paid as bazaar_fetch_paid
        from gecko_core.sources.bazaar_manifest import (
            BazaarEndpoint,
            BazaarPricing,
            BazaarService,
        )

        price = Decimal(str(call.listing.get("price_usd", 0.0)))
        endpoint = BazaarEndpoint(
            url=service_url,
            pricing=BazaarPricing(amount=str(price)),
        )
        service = BazaarService(
            id=fqn,
            name=str(call.listing.get("name", "")),
            description=str(call.listing.get("description", "")),
            category=str(call.listing.get("category", "")),
            networks=[],
            endpoints=[endpoint],
        )
        result = await bazaar_fetch_paid(
            fqn,
            TRADING_ORACLE_PROMPT,
            x402_client=requester,
            catalog_services=[service],
        )
    else:
        raise ValueError(f"unknown provider_kind {pk!r}")

    chunks = (result.payload or {}).get("chunks", []) if result else []
    if not chunks:
        raise RuntimeError(f"{pk} fetch_paid for {fqn!r} returned 0 chunks")
    body = chunks[0].get("text") if isinstance(chunks[0], dict) else None
    if not isinstance(body, str) or not body:
        raise RuntimeError(f"{pk} fetch_paid for {fqn!r} returned non-text first chunk")
    return {"body": body, "fqn": fqn}


async def _write_chunk(
    *,
    text: str,
    provider_kind: str,
    vertical: str,
    freshness_tier: str,
    source_url: str,
) -> None:
    """Embed and persist one chunk to MongoDB with the trading-oracle axes.

    Wraps ``insert_chunks_mongo``. Embedding is computed via the standard
    ingestion embedder so the dim matches the Atlas Vector Search index.
    """
    # Lazy imports keep this leg out of the dry-run code path entirely.
    from uuid import uuid4

    from gecko_core.db.mongo_chunks import insert_chunks_mongo
    from gecko_core.ingestion.embedder import embed

    vectors, _tokens = await embed([text])
    embedding = vectors[0] if vectors else []
    await insert_chunks_mongo(
        session_id=uuid4(),
        source_id=uuid4(),
        chunks=[(0, text, list(embedding))],
        category="market_intelligence",
        vertical=vertical,  # type: ignore[arg-type]
        source="paysh" if provider_kind == "paysh_live" else "bazaar",  # type: ignore[arg-type]
        provider_kind=provider_kind,  # type: ignore[arg-type]
        source_url=source_url,
        freshness_tier=freshness_tier,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# CLI entry.
# ---------------------------------------------------------------------------


def _log_plan(plan_calls: Sequence[PlannedCall], skipped: Sequence[Any]) -> None:
    for s in skipped:
        log.info("  SKIP %-50s reason=%s", s.name, s.reason)
    for c in plan_calls:
        log.info("  CALL %-50s price=$%s", c.name, c.price_usd)


@click.command()
@click.option("--cap-usd", default="5.00", show_default=True, help="Hard spend cap in USD.")
@click.option("--dry-run", is_flag=True, help="Plan only — no network I/O, no Mongo writes.")
@click.option(
    "--source",
    type=click.Choice(["paysh", "bazaar", "both"]),
    default="both",
    show_default=True,
    help="Which marketplace to ingest from.",
)
@click.option(
    "--listings-json",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help="Pre-loaded planner-shaped listings (skips catalog fetch).",
)
@click.option(
    "--max-per-call-usd",
    default="0.10",
    show_default=True,
    help=(
        "Buyer-side hard limit per call in USD. Sellers advertise a MAX "
        "(maxAmountRequired) in x402 accepts[] that may be far larger than "
        "actual settlement (e.g. Venice quotes $10 max for chat-completions "
        "billed per-token). We reject any listing whose advertised max "
        "exceeds this limit. Default $0.10 is conservative; pass e.g. "
        "10.00 if you accept Claude/Anthropic listings whose advertised max "
        "is $10."
    ),
)
def main(
    cap_usd: str,
    dry_run: bool,
    source: str,
    listings_json: Path | None,
    max_per_call_usd: str,
) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    global _PER_CALL_HARD_LIMIT_USD
    _PER_CALL_HARD_LIMIT_USD = Decimal(max_per_call_usd)

    async def _run() -> int:
        # Listings: file-loaded fixture (no network) or live catalog fetch.
        if listings_json is not None:
            listings = _load_listings_from_file(listings_json)
            log.info(
                "loaded %d listings from fixture %s (no network I/O)",
                len(listings),
                listings_json,
            )
        elif dry_run:
            log.info(
                "dry-run with no --listings-json: skipping catalog fetch "
                "(zero network I/O contract). Pass --listings-json to plan "
                "against a fixture."
            )
            listings = []
        else:
            log.info("fetching live catalogs (source=%s)", source)
            listings = await _load_listings_from_catalogs(source)
            log.info("fetched %d listings", len(listings))

        # Filter by source AFTER loading so --source narrows file fixtures
        # too.
        if source != "both":
            wanted_pk = "paysh_live" if source == "paysh" else "bazaar_live"
            listings = [le for le in listings if le.get("provider_kind") == wanted_pk]

        plan = plan_ingest(listings, cap_usd=Decimal(cap_usd))
        log.info(
            "planned %d calls (skip %d, projected $%s, cap $%s)",
            len(plan.calls),
            len(plan.skipped),
            plan.projected_total_usd,
            cap_usd,
        )
        _log_plan(plan.calls, plan.skipped)

        if dry_run:
            log.info("DRY RUN — no charges, no writes.")
            return 0

        report = await execute_plan(
            plan,
            charge_and_fetch=_charge_and_fetch,
            write_chunk=_write_chunk,
            vertical="dex",
        )
        log.info(
            "DONE: spent $%s, wrote %d chunks, %d failures",
            report.spent_usd,
            report.chunks_written,
            len(report.failures),
        )
        for f in report.failures:
            log.warning("  FAIL %s", f)
        return 1 if report.failures else 0

    sys.exit(asyncio.run(_run()))


if __name__ == "__main__":
    main()
