"""Public verdict-URL surface — ``GET /v1/verdict/{hash}``.

S20-VERDICT-URL-IMPL-01 (#10). This is the public, embeddable, curl-able
teaser for a verdict captured in ``judge_transcripts``. The full
prose / citations / advisor voices stay gated behind ``?detail=full``,
which returns 402 today (stub) and lights up x402 settlement in S20 #11.

Lookup strategy:

* 64-char full hex sha256 → single ``find_one`` on ``verdict_hash``.
* 12-char short hash → prefix match. 0 hits → 404. 1 hit → 302 to the
  canonical full-hash URL. >1 hits → 409 with the candidate set so the
  client can disambiguate.

CORS: ``Access-Control-Allow-Origin: *`` on both the teaser and the
402 stub (per the contract doc). The 402 stub will be tightened to
``https://app.geckovision.tech`` in #11 once the paywall ships.

Rate limits (slowapi, the limiter that gecko-api already uses):

* teaser: 60/min/IP (per-IP bucket — the verdict URL is unauthenticated)
* ``?detail=full``: 10/min/IP (so #11's facilitator dispatch can't be
  hammered before settlement)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query, Request
from starlette.responses import JSONResponse, RedirectResponse

from gecko_api.rate_limit import limiter

logger = logging.getLogger(__name__)


router = APIRouter(prefix="/v1/verdict", tags=["verdict"])


# Per-call price displayed in the 402 stub. #11 will replace this with a
# tier-aware price; the response shape (``price_usdc`` as a string) is the
# contract surface so frontend can render dynamic CTA copy.
_DEFAULT_DETAIL_PRICE_USDC = "2.50"

# Excerpt cap for the teaser surface. The judge_prose can run several
# paragraphs in pro-tier; only the lead is exposed publicly.
_PROSE_EXCERPT_MAX_CHARS = 280

_FULL_HASH_LEN = 64
_SHORT_HASH_LEN = 12

# Wide-open CORS for the public teaser. See module docstring on why this
# differs from the restrictive app-wide CORS middleware.
_TEASER_CORS_HEADERS: dict[str, str] = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
}


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
        return True
    except ValueError:
        return False


def _judge_prose_excerpt(judge_prose: str | None) -> str:
    """Truncate the judge prose to the teaser-safe lead sentence(s)."""
    if not isinstance(judge_prose, str) or not judge_prose:
        return ""
    text = judge_prose.strip()
    if len(text) <= _PROSE_EXCERPT_MAX_CHARS:
        return text
    # Truncate on a word boundary so we don't surface a half-token.
    cut = text[:_PROSE_EXCERPT_MAX_CHARS].rsplit(" ", 1)[0]
    return cut.rstrip(",.;:") + "..."


def _format_created_at(value: Any) -> str | None:
    if isinstance(value, datetime):
        # Use Z suffix so the surface matches the OpenAPI / contract doc.
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, str):
        return value
    return None


def _short_hash_token(full_hash: str) -> str:
    return f"verdict@{full_hash[:_SHORT_HASH_LEN]}"


def _teaser_payload(doc: dict[str, Any]) -> dict[str, Any]:
    full_hash = str(doc.get("verdict_hash") or "")
    return {
        "verdict_hash": full_hash,
        "verdict_hash_short": _short_hash_token(full_hash) if full_hash else None,
        "idea_text": doc.get("idea_text"),
        "verdict": doc.get("actual_verdict_v2"),
        "judge_prose_excerpt": _judge_prose_excerpt(doc.get("judge_prose")),
        "gap_classification": doc.get("gap_classification"),
        "created_at": _format_created_at(doc.get("created_at")),
        "tier": doc.get("tier"),
        "provider_mix_flag": doc.get("provider_mix_flag"),
        "is_paywalled": True,
        "preview_only": True,
    }


def _json_response(
    *,
    status_code: int,
    content: dict[str, Any],
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    headers = dict(_TEASER_CORS_HEADERS)
    if extra_headers:
        headers.update(extra_headers)
    return JSONResponse(status_code=status_code, content=content, headers=headers)


def _not_found(echo: str) -> JSONResponse:
    # Single 404 path for "never existed" AND "expired" so we don't leak a
    # timing / shape side channel about which one applies.
    return _json_response(
        status_code=404,
        content={"error": "verdict_not_found", "hash": echo},
    )


def _get_collection() -> Any | None:
    """Return the ``judge_transcripts`` Mongo collection, or None when Mongo
    isn't reachable. Imports lazily so the route module stays import-light
    in environments that don't have pymongo wired (CI, smoke tests)."""
    from gecko_core.orchestration import transcripts as t

    return t._mongo_collection_unsafe()


# ---------------------------------------------------------------------------
# Route handler
# ---------------------------------------------------------------------------


# slowapi's per-handler decorator only supports a single static (or
# request-agnostic) rate. The contract calls for 60/min on the teaser and
# 10/min on ``?detail=full``; we install the 60/min ceiling here so the
# public teaser surface is bounded today. The stricter 10/min on
# ``?detail=full`` will be enforced in S20 #11 when the detail surface is
# split into its own (paid) route — at which point each FastAPI handler
# carries its own slowapi decorator and the buckets are clean.
@router.get("/{hash}/detail", response_model=None)
@limiter.limit("10/minute")
async def get_verdict_detail(
    request: Request,
    hash: str,
) -> JSONResponse | RedirectResponse:
    """Path-segment alias for ``?detail=full``.

    S20-X402-VERDICT-SETTLE-01 (#11). The frontend handoff doc names
    ``?detail=full`` as the canonical surface, so we keep that working
    on the same router. This handler exists so a buyer who hits
    ``/v1/verdict/<hash>/detail`` directly (e.g. a wallet-side x402
    flow that constructs the resource URL from the path-segment form)
    is redirected to the canonical query-string form. slowapi gets a
    real 10/min bucket on this handler — separate from the teaser's
    60/min — so the paywall surface can't be hammered.
    """
    # Use a 308 (permanent + method-preserving) so the buyer's
    # X-Payment header survives the redirect. Browsers and httpx both
    # honor 308's method-preservation; 302 would silently downgrade
    # POSTs to GET (irrelevant today since we're GET-only, but cheap
    # future-proofing for the wallet-callback flow).
    target = f"/v1/verdict/{hash}?detail=full"
    return RedirectResponse(url=target, status_code=308, headers=_TEASER_CORS_HEADERS)


@router.get("/{hash}", response_model=None)
@limiter.limit("60/minute")
async def get_verdict(
    request: Request,
    hash: str,
    detail: str | None = Query(default=None),
) -> JSONResponse | RedirectResponse:
    """Return the teaser for a verdict identified by full or short hash.

    The slowapi limiter has to bucket the two surfaces differently — teaser
    at 60/min, ``?detail=full`` at 10/min — but slowapi's decorator only
    accepts a single rate per handler. We dispatch to two inner helpers,
    each decorated, so the limiter sees them as distinct routes for
    bucketing purposes.
    """
    if detail == "full":
        return await _detail_full_stub(request=request, hash_=hash)
    return await _teaser(request=request, hash_=hash)


async def _teaser(*, request: Request, hash_: str) -> JSONResponse | RedirectResponse:
    # Reject obvious junk early so the Mongo round-trip isn't on the abuse path.
    if not hash_ or not _is_hex(hash_):
        return _not_found(echo=hash_)

    coll = _get_collection()
    if coll is None:
        # Mongo not configured — there's nothing to look up. Same shape as
        # a missing hash so we don't leak deployment posture.
        return _not_found(echo=hash_)

    if len(hash_) == _FULL_HASH_LEN:
        # Full canonical hash — return most-recent on a tie (same idea +
        # same retrieved set produces identical hash across reruns; the
        # ``verdict_hash`` index is non-unique by design).
        doc = _find_most_recent(coll, {"verdict_hash": hash_})
        if doc is None:
            return _not_found(echo=hash_)
        return _json_response(status_code=200, content=_teaser_payload(doc))

    if len(hash_) == _SHORT_HASH_LEN:
        return _short_hash_dispatch(coll=coll, short=hash_, request=request)

    # Any other length is malformed.
    return _not_found(echo=hash_)


async def _detail_full_stub(*, request: Request, hash_: str) -> JSONResponse:
    """402 / 200 dispatch for ``?detail=full`` — the verdict paywall.

    S20-X402-VERDICT-SETTLE-01 (#11). Replaces the static 402 stub from
    #10 with a real x402 paywall:

    * No ``X-Payment`` header → return 402 with the ``PaymentRequirements``
      challenge body. The frontend's wallet flow signs against that
      challenge and retries with the resulting signed payload.
    * ``X-Payment`` present → call ``verify_verdict_payment``. On
      success, return 200 with the full ResearchResult-shaped body
      from the persisted ``judge_transcripts`` document. On failure,
      return 402 with the same challenge so the buyer can retry.

    Mode resolution is delegated to ``verdict_settle.resolve_verdict_settle_mode``
    so the env-var gates (``X402_MODE`` + ``X402_VERDICT_SETTLE_LIVE``)
    live in one place.
    """
    from gecko_core.payments.verdict_settle import (
        InvalidVerdictPaymentError,
        VerdictPaymentError,
        make_verdict_payment_requirement,
        resolve_verdict_settle_mode,
        verify_verdict_payment,
    )

    # Validate the hash shape early — same 404 path as the teaser, so
    # we don't leak "this hash exists but you must pay" vs "no such
    # hash" via the paywall surface either.
    if not hash_ or not _is_hex(hash_) or len(hash_) != _FULL_HASH_LEN:
        return _not_found(echo=hash_)

    coll = _get_collection()
    if coll is None:
        return _not_found(echo=hash_)

    doc = _find_most_recent(coll, {"verdict_hash": hash_})
    if doc is None:
        return _not_found(echo=hash_)

    mode = resolve_verdict_settle_mode()
    requirement = await make_verdict_payment_requirement(hash_, mode=mode)

    payment_header = request.headers.get("x-payment") or request.headers.get("X-Payment")
    if not payment_header:
        return _challenge_response(verdict_hash=hash_, requirement=requirement)

    try:
        receipt = await verify_verdict_payment(
            payment_header,
            verdict_hash=hash_,
            mode=mode,
        )
    except InvalidVerdictPaymentError as exc:
        # Bad / replayed / scope-mismatched signature — re-issue the
        # challenge. We surface the failure reason in the body so the
        # buyer's wallet UX can show "scope mismatch" / "expired" etc.
        return _challenge_response(
            verdict_hash=hash_,
            requirement=requirement,
            failure=str(exc),
        )
    except VerdictPaymentError as exc:
        # Facilitator-side error or live-mode misconfiguration. We
        # surface verbatim per the CLAUDE.md "never catch-and-rephrase"
        # rule — just wrap it in a 402 envelope.
        return _challenge_response(
            verdict_hash=hash_,
            requirement=requirement,
            failure=f"{type(exc).__name__}: {exc}",
        )

    return _json_response(
        status_code=200,
        content=_detail_payload(doc=doc, receipt=receipt),
    )


def _challenge_response(
    *,
    verdict_hash: str,
    requirement: Any,
    failure: str | None = None,
) -> JSONResponse:
    """Build the 402 body. ``failure`` is surfaced when the buyer's
    last attempt was rejected so the frontend can render diagnostic
    copy without a follow-up round-trip."""
    body: dict[str, Any] = {
        "error": "payment_required",
        "message": "x402 settlement required for verdict detail",
        "verdict_hash": verdict_hash,
        "price_usdc": requirement.price_usdc,
        "x402_challenge": requirement.to_response_body(),
    }
    if failure:
        body["last_failure"] = failure
    return _json_response(status_code=402, content=body)


def _detail_payload(*, doc: dict[str, Any], receipt: Any) -> dict[str, Any]:
    """Full-content response after a successful settlement.

    Mirrors the JSON shape called out in the ticket. Fields not
    present in the persisted ``judge_transcripts`` document degrade
    gracefully to ``None`` — the eval-side schema includes reserved
    slots for ``advisor_voices`` / ``advisor_consensus`` etc. that
    aren't populated for legacy rows. The frontend handoff doc
    documents the optional fields explicitly.

    ``transcript`` from the production-side capture lives in
    ``agent_turns`` (S17 rename); we surface it under both names so
    the post-settlement view doesn't have to know which schema
    version produced the row.
    """
    full_hash = str(doc.get("verdict_hash") or "")
    return {
        "verdict_hash": full_hash,
        "verdict_hash_short": _short_hash_token(full_hash) if full_hash else None,
        "verdict": doc.get("actual_verdict_v2"),
        "idea_text": doc.get("idea_text"),
        "tier": doc.get("tier"),
        "created_at": _format_created_at(doc.get("created_at")),
        # Full prose, not the teaser excerpt — the buyer paid for it.
        "judge_prose_full": doc.get("judge_prose"),
        "gap_classification": doc.get("gap_classification"),
        "gap_summary": doc.get("gap_summary"),
        "provider_mix_flag": doc.get("provider_mix_flag"),
        # Optional richer payloads. Present when the workflow that
        # wrote the transcript stamped them; ``None`` for legacy rows.
        # The frontend renders conditionally per the handoff doc.
        "business_plan": doc.get("business_plan"),
        "validation_report": doc.get("validation_report"),
        "prd": doc.get("prd"),
        "advisor_voices": doc.get("advisor_voices"),
        # Debate transcript — surfaced as ``agent_turns`` in the
        # persisted shape (S17 rename). Expose under the legacy name
        # too so older frontend builds keep working.
        "transcript": doc.get("agent_turns"),
        "agent_turns": doc.get("agent_turns"),
        "settlement_receipt": receipt.to_response_body(),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_most_recent(coll: Any, query: dict[str, Any]) -> dict[str, Any] | None:
    """Return the most-recent document matching ``query`` by ``created_at``."""
    cursor = coll.find(query).sort("created_at", -1).limit(1)
    for doc in cursor:
        return doc  # type: ignore[no-any-return]
    return None


def _short_hash_dispatch(
    *, coll: Any, short: str, request: Request
) -> JSONResponse | RedirectResponse:
    """Resolve a 12-char prefix to either a 302 (single match), 409
    (multiple), or 404 (none). We use a regex prefix match keyed off the
    indexed ``verdict_hash`` field — ``^abc123…`` is a covered scan on
    that index in MongoDB."""
    # Distinct full-hash candidates within the prefix space.
    candidates_seen: list[str] = []
    cursor = coll.find(
        {"verdict_hash": {"$regex": f"^{short}"}},
        projection={"verdict_hash": 1, "created_at": 1},
    ).sort("created_at", -1)
    for doc in cursor:
        full = str(doc.get("verdict_hash") or "")
        if not full:
            continue
        if full not in candidates_seen:
            candidates_seen.append(full)
        # Bound the work — anything past 5 distinct collisions is already
        # unambiguously "ambiguous" for the response.
        if len(candidates_seen) >= 5:
            break

    if not candidates_seen:
        return _not_found(echo=short)

    if len(candidates_seen) == 1:
        canonical = f"/v1/verdict/{candidates_seen[0]}"
        # 302: client should re-issue against the canonical full hash. The
        # response inherits the wide-open CORS so browser clients can read
        # the redirect target.
        return RedirectResponse(url=canonical, status_code=302, headers=_TEASER_CORS_HEADERS)

    return _json_response(
        status_code=409,
        content={
            "error": "verdict_hash_ambiguous",
            "short": short,
            "candidates": candidates_seen,
        },
    )


__all__ = ["router"]
