"""Single x402-gated dispatcher route for the 12-skill manifest (S20-B3).

One handler, twelve skills. The skill name is just a path parameter —
``Skill.dispatch_kind`` selects the per-kind stub today; B5 wires the
real ``gecko-core`` calls behind that same selector.

Feature-flagged on ``GECKO_SKILLS_DISPATCH_ENABLED`` (default ``false``)
so we can ship the route alongside the manifest at B2 without exposing
it to the pay.sh crawler before copy + flow review. When the flag is
off the route returns ``503`` + ``X-Gecko-Skills-Status: draft`` —
identical pattern to the B2 manifest endpoint.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Request, Response
from gecko_core.payments.dispatch import AuthResult, X402Dispatcher
from gecko_core.skills.registry import Skill, get_skill

logger = logging.getLogger(__name__)


router = APIRouter()


# Flag is read per-request so test fixtures can toggle without re-importing
# the module — same pattern as B2.
_FLAG_ENV: str = "GECKO_SKILLS_DISPATCH_ENABLED"


def _flag_enabled() -> bool:
    return os.environ.get(_FLAG_ENV, "false").strip().lower() in ("1", "true", "yes", "on")


def _draft_response() -> Response:
    """503 envelope returned when the dispatch flag is off.

    Mirrors the B2 manifest endpoint's draft shape so an external
    crawler that hits both surfaces sees one consistent gate.
    """
    body = json.dumps(
        {"detail": "Gecko skills dispatch is in DRAFT — flip GECKO_SKILLS_DISPATCH_ENABLED=true."}
    ).encode("utf-8")
    return Response(
        content=body,
        status_code=503,
        media_type="application/json",
        headers={"X-Gecko-Skills-Status": "draft"},
    )


def _payment_required_response(auth: AuthResult, skill: Skill) -> Response:
    """402 envelope — base64-JSON ``PAYMENT-REQUIRED`` header + body.

    Same encoding convention the existing x402 middleware uses for
    ``/research`` so an off-the-shelf payer-side decoder works against
    both surfaces unchanged.
    """
    accepts_block: dict[str, Any] = {
        "x402_version": 2,
        "accepts": auth.accepts or [],
        "skill": skill.name,
        "resource": skill.url_path,
    }
    body_payload: dict[str, Any] = {
        "x402_version": 2,
        "accepts": auth.accepts or [],
        "skill": skill.name,
    }
    if auth.error_detail:
        body_payload["detail"] = auth.error_detail
    encoded = base64.b64encode(json.dumps(accepts_block).encode("utf-8")).decode("utf-8")
    return Response(
        content=json.dumps(body_payload).encode("utf-8"),
        status_code=402,
        media_type="application/json",
        headers={"PAYMENT-REQUIRED": encoded},
    )


def _verify_failed_response(auth: AuthResult) -> Response:
    """402 envelope for an X-PAYMENT that failed verify.

    No ``PAYMENT-REQUIRED`` header — the client already supplied a
    payload; we surface the facilitator's verdict verbatim per CLAUDE.md.
    """
    body = json.dumps({"detail": auth.error_detail or "x402 verify failed"}).encode("utf-8")
    return Response(content=body, status_code=402, media_type="application/json")


# ---------------------------------------------------------------------------
# Per-dispatch-kind stub handlers.
#
# B5 wires real gecko-core calls inside this dict. B3 just gets the
# routing right — every kind returns the same envelope.
# ---------------------------------------------------------------------------


async def _stub_handler(skill: Skill, auth: AuthResult, request: Request) -> dict[str, Any]:
    return {
        "skill": skill.name,
        "dispatch_kind": skill.dispatch_kind,
        "tx_signature": auth.tx_signature,
        "chain": auth.chain,
        "status": "ok",
        "stub": "B5 will fill in real handlers",
    }


# ---------------------------------------------------------------------------
# The single route.
# ---------------------------------------------------------------------------


@router.post("/skills/{skill_name}")
async def dispatch_skill(skill_name: str, request: Request) -> Response:
    """Single x402-gated entry point for every skill in the registry.

    Flow:
      1. Flag check — 503 + ``X-Gecko-Skills-Status: draft`` if off.
      2. Skill lookup — 404 if unknown.
      3. ``X402Dispatcher.authorize`` — 402 + accepts on no payment;
         402 + error_detail on bad payment; pass-through on green.
      4. Dispatch by ``Skill.dispatch_kind`` (currently all stub) and
         return 200 with the ``X-Payment-Tx-Signature`` header set.
    """
    if not _flag_enabled():
        return _draft_response()

    try:
        skill = get_skill(skill_name)
    except KeyError:
        return Response(
            content=json.dumps({"detail": f"Unknown skill: {skill_name!r}"}).encode("utf-8"),
            status_code=404,
            media_type="application/json",
        )

    dispatcher = X402Dispatcher()
    auth = await dispatcher.authorize(skill_name, request.headers)

    if not auth.ok:
        if auth.accepts is not None:
            return _payment_required_response(auth, skill)
        return _verify_failed_response(auth)

    # Green path — every skill currently routes to the stub. B5 swaps
    # in the per-kind real handler against the same selector.
    payload = await _stub_handler(skill, auth, request)
    response_headers: dict[str, str] = {}
    if auth.tx_signature:
        response_headers["X-Payment-Tx-Signature"] = auth.tx_signature
    return Response(
        content=json.dumps(payload).encode("utf-8"),
        status_code=200,
        media_type="application/json",
        headers=response_headers,
    )


__all__ = ["router"]
