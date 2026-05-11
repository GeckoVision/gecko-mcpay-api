"""REST client for the deployed ``gecko_trade_research`` oracle.

The trade-agent runtime runs on the user's machine (standalone, no
in-process MCP server) so the verdict caller is a REST client that
hits the deployed ``api.geckovision.tech`` endpoints with the x402
v2 buyer dance.

Wire flow per ``call()``:

  1. POST ``/trade_research`` (or ``/trade_research/pro``) with
     ``{"idea", "protocol", "vertical"}`` body, no payment header.
  2. Server returns 402 with the x402 v2 challenge in the
     ``payment-required`` response header (base64 JSON).
  3. Decode the challenge, pick the first ``accepts`` entry.
  4. Build a stub payment payload (``X402_MODE=stub``) — the deployed
     surface runs stub-mode today so the stub signature passes
     verification without funds moving. Live mode raises
     :class:`OraclePaymentRequired` until a real EVM/SVM signing path
     is wired (separate ticket).
  5. Re-POST with ``PAYMENT-SIGNATURE: <b64>`` header → expect 200.
  6. Parse JSON into :class:`VerdictPayload`.

The buyer dance mirrors ``scripts/trading_oracle/run.py`` and
``gecko-mcpay-app/public/test.sh`` — same 402 challenge dance, same
stub-mode header construction. Do NOT re-invent.
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)

Tier = Literal["basic", "pro"]
X402Mode = Literal["stub", "live"]


class OracleError(Exception):
    """Base for oracle-client errors."""


class OracleNotReachable(OracleError):
    """Network/transport failure or unexpected non-{200,402} status."""


class OraclePaymentRequired(OracleError):
    """Live x402 signing not yet wired; caller must run with stub mode."""


class OracleResponseInvalid(OracleError):
    """200 response did not parse as a verdict payload."""


class Citation(BaseModel):
    """Mirror the trade-oracle wire citation shape (commit f5055ae)."""

    model_config = ConfigDict(extra="allow")

    id: str | int | None = None
    source: str | None = None
    url: str | None = None
    chunk_id: str | None = None
    provider_kind: str | None = None
    freshness_tier: str | None = None
    snippet: str | None = None


class VerdictPayload(BaseModel):
    """Parsed verdict envelope. ``extra='allow'`` so the model survives
    additive wire changes (e.g. SHED-01 ``shed`` field, FREE-04 freshness
    block) without a code bump on every server-side enrichment."""

    model_config = ConfigDict(extra="allow")

    verdict: Literal["act", "pass", "defer"]
    confidence: float = Field(ge=0.0, le=1.0)
    citations: list[Citation] = Field(default_factory=list)
    turns: list[dict[str, Any]] = Field(default_factory=list)
    dissent_count: int | None = None
    backtest: dict[str, Any] | None = None


class AcceptsEntry(BaseModel):
    """One ``accepts[]`` entry from the x402 v2 challenge.

    Only the fields the buyer reads to build the stub payload are
    typed; everything else passes through via ``extra='allow'`` so we
    don't break when sellers add new attributes.
    """

    model_config = ConfigDict(extra="allow")

    scheme: str | None = None
    network: str | None = None
    payTo: str | None = None
    asset: str | None = None
    maxAmountRequired: str | None = None
    resource: str | None = None
    maxTimeoutSeconds: int | None = None


def _decode_payment_required(response: httpx.Response) -> dict[str, Any]:
    """Decode the base64 ``payment-required`` header into a dict.

    Returns ``{}`` (rather than raising) when the header is missing or
    malformed — the caller checks ``accepts`` truthiness and raises.
    """
    headers: Any = response.headers or {}
    for key in (
        "payment-required",
        "PAYMENT-REQUIRED",
        "Payment-Required",
        "X-Payment-Required",
        "x-payment-required",
    ):
        raw = headers.get(key)
        if not raw:
            continue
        try:
            decoded = base64.b64decode(raw).decode("utf-8")
            parsed = json.loads(decoded)
        except (ValueError, json.JSONDecodeError):
            continue
        if isinstance(parsed, dict):
            return parsed
    # Fallback: some legacy servers put the challenge in the JSON body.
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


def _build_stub_payment_header(accepts_entry: dict[str, Any]) -> str:
    """Build the stub-mode ``PAYMENT-SIGNATURE`` header value.

    Wire shape mirrors ``test.sh``::

        {
          "x402Version": 2,
          "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
          "accepted": <first accepts entry>
        }

    Base64-encode the JSON. Server-side stub verification accepts any
    well-formed payload with this shape.
    """
    payload = {
        "x402Version": 2,
        "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
        "accepted": accepts_entry,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


class GeckoOracleClient:
    """REST client for ``/trade_research`` and ``/trade_research/pro``.

    One instance per agent. The underlying ``httpx.AsyncClient`` may be
    injected (for tests using ``httpx.MockTransport``) or constructed
    lazily on first ``call()``.
    """

    def __init__(
        self,
        *,
        api_base: str,
        x402_mode: X402Mode,
        timeout_s: float = 60.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_base = api_base.rstrip("/")
        self._x402_mode = x402_mode
        self._timeout_s = timeout_s
        self._http_client = http_client
        self._owns_client = http_client is None

    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._http_client

    async def aclose(self) -> None:
        """Close the underlying httpx client when this client owns it."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def call(
        self,
        *,
        idea: str,
        protocol: str,
        vertical: str = "dex",
        tier: Tier = "basic",
    ) -> VerdictPayload:
        """Run the 402 challenge dance and return a parsed verdict."""
        path = "/trade_research/pro" if tier == "pro" else "/trade_research"
        url = f"{self._api_base}{path}"
        body = {"idea": idea, "protocol": protocol, "vertical": vertical}

        client = self._client()

        # Step 1 — probe for 402.
        try:
            probe = await client.post(
                url,
                json=body,
                headers={"Content-Type": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OracleNotReachable(
                f"transport error probing {url}: {type(exc).__name__}: {exc}"
            ) from exc

        if probe.status_code == 200:
            # Free-mode passthrough (unlikely on the production surface,
            # but handle gracefully so the smoke path works in any env).
            return _parse_verdict(probe)

        if probe.status_code != 402:
            raise OracleNotReachable(
                f"{url} returned {probe.status_code} on probe (expected 402): {probe.text[:256]!r}"
            )

        # Step 2 — decode challenge.
        challenge = _decode_payment_required(probe)
        accepts_raw = challenge.get("accepts") or []
        if not accepts_raw or not isinstance(accepts_raw, list):
            raise OracleNotReachable(f"402 from {url} carried empty/invalid accepts[]")
        first_accepts_raw = accepts_raw[0]
        if not isinstance(first_accepts_raw, dict):
            raise OracleNotReachable(f"402 from {url} carried non-dict accepts[0]")

        # Lenient parse so we surface useful warnings, but pass the raw
        # dict (not the parsed model) into the stub payload — the server
        # echoes ``accepted`` and rejects shape-narrowed payloads.
        try:
            parsed_accepts = AcceptsEntry.model_validate(first_accepts_raw)
        except ValidationError:
            parsed_accepts = AcceptsEntry()

        if parsed_accepts.scheme == "upto":
            # Issue #17: stub-sig can't satisfy an ``upto``-scheme accepts
            # entry by construction. Warn but keep going — the deployed
            # stub-mode server still accepts the payload.
            logger.warning(
                "oracle_client: accepts[0].scheme='upto' is not "
                "satisfiable by stub-sig; payload built anyway "
                "(stub-mode server will accept)."
            )

        # Step 3 — build payment header.
        if self._x402_mode == "live":
            raise OraclePaymentRequired(
                "live x402 signing path not wired in oracle_client; "
                "set GECKO_X402_MODE=stub or wire a real signer in a "
                "follow-up ticket."
            )
        sig_header = _build_stub_payment_header(first_accepts_raw)

        # Step 4 — paid retry.
        try:
            paid = await client.post(
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "PAYMENT-SIGNATURE": sig_header,
                    # Send X-PAYMENT too for v1-server compat; identical
                    # bytes, only header name differs.
                    "X-PAYMENT": sig_header,
                },
            )
        except httpx.HTTPError as exc:
            raise OracleNotReachable(
                f"transport error on paid retry {url}: {type(exc).__name__}: {exc}"
            ) from exc

        if paid.status_code != 200:
            raise OracleNotReachable(
                f"paid POST {url} returned {paid.status_code}: {paid.text[:256]!r}"
            )

        return _parse_verdict(paid)


def _parse_verdict(response: httpx.Response) -> VerdictPayload:
    """Parse a 200 verdict response, wrapping all errors as
    :class:`OracleResponseInvalid`."""
    try:
        raw = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise OracleResponseInvalid(
            f"verdict response was not valid JSON: {response.text[:256]!r}"
        ) from exc
    try:
        return VerdictPayload.model_validate(raw)
    except ValidationError as exc:
        raise OracleResponseInvalid(f"verdict payload failed validation: {exc}") from exc


__all__ = [
    "AcceptsEntry",
    "Citation",
    "GeckoOracleClient",
    "OracleError",
    "OracleNotReachable",
    "OraclePaymentRequired",
    "OracleResponseInvalid",
    "Tier",
    "VerdictPayload",
    "X402Mode",
]
