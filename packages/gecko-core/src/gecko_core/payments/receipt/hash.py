r"""Canonical Decision-Receipt hash — the load-bearing serialization spec.

A Decision Receipt anchors ``h = sha256(canonical_json(envelope))`` on-chain.
A third-party verifier MUST be able to recompute ``h`` from the same logical
verdict envelope and get the identical hex string — otherwise the on-chain
memo proves nothing. This module is therefore a *frozen contract*, not an
implementation detail. Changing any rule below is a breaking version bump
(``gecko:v1:`` → ``gecko:v2:``) and requires a new test vector.

================================  THE SPEC  ================================

A verdict envelope is projected to a canonical object with EXACTLY these four
top-level keys, in this order (json.dumps with sort_keys handles ordering, but
we enumerate for the human reader):

    {
      "citations":  [ <citation>, ... ],   # see citation projection below
      "confidence":  <float>,              # the raw envelope confidence
      "dissent":     [ <dissent>, ... ],   # see dissent projection below
      "verdict":     "<string>"            # the raw envelope verdict token
    }

No other top-level keys are included. Enrichment fields (``turns``,
``backtest``, ``key_drivers``, ``shed``, freshness blocks, ``dissent_count``,
etc.) are DELIBERATELY EXCLUDED — they drift across deploys and tiers and would
make the hash unstable. The receipt commits to the *decision surface* the four
spec fields define, nothing more.

Field projections
-----------------
* ``verdict``    — coerced to ``str``. ("act"/"pass"/"defer" or basic-tier
  "bullish"/"bearish"/... — whatever token the envelope carries, verbatim.)
* ``confidence`` — coerced to ``float``. Serialized by ``json.dumps`` with no
  rounding (see "Float note" below). ``None`` → ``0.0``.
* each ``citation`` — projected to EXACTLY ``{"id", "source", "url"}``:
    - ``id``     → ``str`` (str/int ids both stringified; ``None`` → ``""``).
    - ``source`` → ``str`` (``None`` → ``""``).
    - ``url``    → ``str`` (``None`` → ``""``).
  Order of the citation list is PRESERVED (not sorted) — citation order is
  meaningful (matches the inline ``[N]`` markers). chunk_id / snippet /
  provider_kind / freshness_tier are EXCLUDED: they are storage-internal and
  vary by retrieval backend, so they must not enter the commitment.
* each ``dissent`` — projected to EXACTLY ``{"on_topic", "stance", "verbatim",
  "voice"}``, all coerced to ``str`` (``None`` → ``""``). Dissent list order
  is PRESERVED. ``stance`` absent → ``""``.

Serialization
-------------
    json.dumps(canonical_obj, sort_keys=True, separators=(",", ":"),
               ensure_ascii=False).encode("utf-8")

* ``sort_keys=True``        — keys sorted lexicographically at every level.
* ``separators=(",",":")``  — no whitespace.
* ``ensure_ascii=False``    — UTF-8 bytes, so non-ASCII source names / verbatim
  text hash identically regardless of escaping. (A verifier in another language
  MUST emit UTF-8, not ``\uXXXX`` escapes.)

Then ``h = hashlib.sha256(bytes).hexdigest()`` — lowercase 64-char hex.

Float note (load-bearing for verifiers)
---------------------------------------
``confidence`` is serialized via Python's ``json.dumps`` float ``repr`` (e.g.
``0.7`` → ``"0.7"``, ``0.65`` → ``"0.65"``). This matches JavaScript's
``JSON.stringify`` for the same IEEE-754 double in the common case. To stay
safe, CALLERS SHOULD pass confidence already rounded to 2 decimals (the wedge
surfaces only 2-dp confidence anyway). The spec does NOT round for you — it
commits to exactly the bytes you pass. If you pass ``0.7000000001`` you get a
different ``h`` than ``0.7``; round before anchoring.

The on-chain memo string is ``gecko:v1:{h}`` — see :data:`RECEIPT_MEMO_PREFIX`.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Versioned memo prefix. The ``v1`` is the RECEIPT-SCHEMA version (this spec),
# independent of the gecko API version. Bump only if the canonical projection
# above changes. Verifiers match on this exact prefix.
RECEIPT_MEMO_PREFIX = "gecko:v1:"

__all__ = [
    "RECEIPT_MEMO_PREFIX",
    "canonical_envelope_json",
    "memo_string",
    "receipt_hash",
]


def _as_mapping(envelope: Any) -> dict[str, Any]:
    """Accept a pydantic model, a TypedDict, or a plain dict.

    We read the four spec fields by attribute first, then by key, so both
    ``VerdictPayload`` (pydantic) and a raw wire dict project identically.
    """
    if isinstance(envelope, dict):
        return envelope
    # pydantic v2 models expose model_dump; anything else, fall back to getattr.
    dump = getattr(envelope, "model_dump", None)
    if callable(dump):
        result: dict[str, Any] = dump()
        return result
    return {
        k: getattr(envelope, k, None) for k in ("verdict", "confidence", "citations", "dissent")
    }


def _get(item: Any, key: str) -> Any:
    """Read ``key`` from a dict OR an object attribute — citations/dissent
    entries may be pydantic models or plain dicts depending on the caller."""
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _str_or_empty(value: Any) -> str:
    return "" if value is None else str(value)


def _project_citation(item: Any) -> dict[str, str]:
    """Project ONE citation to the frozen ``{id, source, url}`` shape."""
    return {
        "id": _str_or_empty(_get(item, "id")),
        "source": _str_or_empty(_get(item, "source")),
        "url": _str_or_empty(_get(item, "url")),
    }


def _project_dissent(item: Any) -> dict[str, str]:
    """Project ONE dissent entry to the frozen 4-key shape."""
    return {
        "on_topic": _str_or_empty(_get(item, "on_topic")),
        "stance": _str_or_empty(_get(item, "stance")),
        "verbatim": _str_or_empty(_get(item, "verbatim")),
        "voice": _str_or_empty(_get(item, "voice")),
    }


def _canonical_obj(envelope: Any) -> dict[str, Any]:
    """Build the canonical projection object (pre-serialization)."""
    src = _as_mapping(envelope)

    confidence_raw = src.get("confidence")
    confidence = 0.0 if confidence_raw is None else float(confidence_raw)

    citations_raw = src.get("citations") or []
    dissent_raw = src.get("dissent") or []

    return {
        "verdict": _str_or_empty(src.get("verdict")),
        "confidence": confidence,
        # Order PRESERVED — do not sort the lists.
        "citations": [_project_citation(c) for c in citations_raw],
        "dissent": [_project_dissent(d) for d in dissent_raw],
    }


def canonical_envelope_json(envelope: Any) -> str:
    """Return the canonical JSON STRING for ``envelope`` per the module spec.

    Accepts a pydantic verdict model (``VerdictPayload`` /
    ``TradePanelVerdict``), a TypedDict, or a plain dict carrying the four spec
    fields. Extra fields are ignored. This is the exact text whose UTF-8 bytes
    are sha256'd.
    """
    return json.dumps(
        _canonical_obj(envelope),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )


def receipt_hash(envelope: Any) -> str:
    """Return ``h`` — lowercase 64-char hex sha256 of the canonical JSON."""
    return hashlib.sha256(canonical_envelope_json(envelope).encode("utf-8")).hexdigest()


def memo_string(envelope_or_hash: Any) -> str:
    """Return the on-chain memo string ``gecko:v1:{h}``.

    Accepts either a verdict envelope (hashes it) or a precomputed 64-char hex
    ``h`` string (used verbatim). This keeps the anchor and verifier reading
    the prefix from ONE place.
    """
    if isinstance(envelope_or_hash, str) and len(envelope_or_hash) == 64:
        h = envelope_or_hash.lower()
    else:
        h = receipt_hash(envelope_or_hash)
    return f"{RECEIPT_MEMO_PREFIX}{h}"
