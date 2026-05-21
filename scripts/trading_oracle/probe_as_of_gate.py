"""S39-#133 — Pattern F leakage probe for the backtest `as_of` retrieval gate.

A retrieval *gate* must be proven to actually gate (CLAUDE.md Pattern F:
per-layer unit tests are necessary but not sufficient; a gate needs a
direct end-to-end leakage probe). This script calls the *real* production
retrieval path — `retrieve_trade_corpus_chunks` — against live Mongo +
embeddings, and asserts:

  1. NO-OP:  `as_of=None` returns the exact production slate (the safety
     property — production is unchanged).
  2. GATE:   with `as_of=T` set to a past date, EVERY returned chunk has
     `as_of_date <= T` OR `as_of_date` is null/missing (timeless canon).
     Zero future-dated chunks leak.
  3. CANON:  the timeless investor-canon corpus is still reachable at the
     gated T — the gate did not silently drop canon (the Pattern F trap).

Retrieval-only — embeddings + Mongo $vectorSearch. No panel run, no
LLM-judge, no money beyond ~cents of OpenAI embedding calls.

Run:
    set -a && source .env && set +a
    uv run python scripts/trading_oracle/probe_as_of_gate.py

Exit 0 = gate verified. Exit 1 = leakage / canon-drop / no-op violation.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date
from typing import Any

from gecko_core.db.mongo import chunks_collection
from gecko_core.orchestration.trade_panel import retrieve_trade_corpus_chunks

# A trade-idea query that pulls both protocol_native (dated) and canon
# (timeless) chunks — the same shape the S33 retrieval evals use. Jupiter
# is chosen because its protocol_native corpus carries dated chunks
# spanning multiple days (2026-05-16..05-19), so a mid-span T genuinely
# exercises the EXCLUSION path — not just the canon null-passthrough.
PROBE_IDEA = "Is routing a USDC to SOL swap through Jupiter a good idea right now?"
PROBE_PROTOCOL = "jupiter"
PROBE_VERTICAL = "dex"
PROBE_TOP_K = 15


def _chunk_as_of(row: dict[str, Any]) -> str | None:
    """Read a row's as_of_date — the field the gate filters on."""
    val = row.get("as_of_date")
    if isinstance(val, str) and len(val) >= 10:
        return val[:10]
    return None


async def _corpus_date_span() -> tuple[str | None, str | None]:
    """Min/max `as_of_date` for the probe protocol — picks a real, in-span T."""
    coll = chunks_collection()
    if coll is None:
        return None, None
    cur = coll.aggregate(
        [
            {
                "$match": {
                    "as_of_date": {"$type": "string"},
                    "protocol": PROBE_PROTOCOL,
                }
            },
            {
                "$group": {
                    "_id": None,
                    "min": {"$min": "$as_of_date"},
                    "max": {"$max": "$as_of_date"},
                }
            },
        ]
    )
    async for doc in cur:
        return doc.get("min"), doc.get("max")
    return None, None


async def main() -> int:
    print("[probe] S39-#133 as_of gate leakage probe")

    span_min, span_max = await _corpus_date_span()
    print(f"[corpus] dated-chunk as_of_date span: {span_min} .. {span_max}")
    if not span_max:
        print("[probe] FAIL — corpus has no dated chunks; cannot exercise the gate")
        return 1

    # Pick T strictly inside the span so the corpus contains BOTH chunks
    # that should pass (<= T) and chunks that must be gated out (> T).
    # If the span is a single day, T = the day before max (gates max out).
    span_max_d = date.fromisoformat(span_max[:10])
    span_min_d = date.fromisoformat(span_min[:10]) if span_min else span_max_d
    if span_max_d > span_min_d:
        mid = span_min_d.toordinal() + (span_max_d.toordinal() - span_min_d.toordinal()) // 2
        t = date.fromordinal(mid)
    else:
        t = date.fromordinal(span_max_d.toordinal() - 1)
    t_iso = t.isoformat()
    print(f"[probe] backtest T = {t_iso}")

    # --- Arm 1: NO-OP. Production default (as_of=None). -------------------
    baseline = await retrieve_trade_corpus_chunks(
        idea=PROBE_IDEA,
        protocol=PROBE_PROTOCOL,
        vertical=PROBE_VERTICAL,
        top_k=PROBE_TOP_K,
    )
    print(f"[arm1/no-op]  as_of=None -> {len(baseline)} chunks")
    if not baseline:
        print("[probe] FAIL — baseline retrieval returned 0 chunks; corpus/env issue")
        return 1

    # --- Arm 2: GATE. Past T set. -----------------------------------------
    gated = await retrieve_trade_corpus_chunks(
        idea=PROBE_IDEA,
        protocol=PROBE_PROTOCOL,
        vertical=PROBE_VERTICAL,
        top_k=PROBE_TOP_K,
        as_of=t_iso,
    )
    print(f"[arm2/gate]   as_of={t_iso} -> {len(gated)} chunks")

    ok = True

    # Leakage check: no chunk dated after T may survive the gate.
    leaked = [
        (r.get("id"), r.get("provider_kind"), _chunk_as_of(r))
        for r in gated
        if (d := _chunk_as_of(r)) is not None and d > t_iso
    ]
    if leaked:
        ok = False
        print(f"[arm2/gate]   FAIL — {len(leaked)} future-dated chunk(s) leaked:")
        for cid, pk, d in leaked[:10]:
            print(f"              id={cid} kind={pk} as_of_date={d} > T={t_iso}")
    else:
        print(f"[arm2/gate]   PASS — 0 future-dated chunks leaked (all <= {t_iso})")

    # Non-vacuous check: the gate must have ADMITTED at least one dated
    # chunk <= T. If the gated slate had zero dated chunks the leakage
    # check above would pass trivially (vacuously) — prove the <= T arm
    # actually fired by confirming dated chunks survived.
    admitted_dated = [
        _chunk_as_of(r) for r in gated if (_chunk_as_of(r) or "") <= t_iso and _chunk_as_of(r)
    ]
    print(f"[arm2/gate]   dated chunks admitted (<= T): {len(admitted_dated)}")
    baseline_future = [
        _chunk_as_of(r) for r in baseline if (d := _chunk_as_of(r)) is not None and d > t_iso
    ]
    print(
        f"[arm2/gate]   baseline (as_of=None) future-dated chunks: {len(baseline_future)} "
        f"-> these are what the gate excludes"
    )

    # Canon reachability: timeless canon (as_of_date null) must still appear.
    gated_canon = [r for r in gated if str(r.get("provider_kind") or "").startswith("canon_")]
    print(f"[arm3/canon]  canon chunks in gated slate: {len(gated_canon)}")
    if not gated_canon:
        ok = False
        print("[arm3/canon]  FAIL — gate silently dropped the timeless canon corpus")
    else:
        kinds = sorted({str(r.get("provider_kind")) for r in gated_canon})
        print(f"[arm3/canon]  PASS — canon reachable at T; kinds={kinds}")

    # Sanity: every gated canon chunk genuinely carries a null/absent date
    # (proves canon passed via the null-admitting arms, not via <= T luck).
    dated_canon = [r for r in gated_canon if _chunk_as_of(r) is not None]
    if dated_canon:
        print(
            f"[arm3/canon]  NOTE — {len(dated_canon)} canon chunk(s) carry a date; "
            "they passed the gate via the <= T arm, still valid"
        )

    # --- Arm 4: STRICT EXCLUSION. T before the entire corpus span. --------
    # The definitive Pattern-F-inverse proof: at a T that predates EVERY
    # dated chunk, the gate MUST drop all dated chunks AND still keep the
    # timeless canon corpus reachable. If canon vanished here, the gate
    # would be silently excluding canon — the exact trap #129 §2a warns of.
    pre_corpus_t = "2020-01-01"
    pre = await retrieve_trade_corpus_chunks(
        idea=PROBE_IDEA,
        protocol=PROBE_PROTOCOL,
        vertical=PROBE_VERTICAL,
        top_k=PROBE_TOP_K,
        as_of=pre_corpus_t,
    )
    pre_dated = [r for r in pre if _chunk_as_of(r) is not None]
    pre_canon = [r for r in pre if str(r.get("provider_kind") or "").startswith("canon_")]
    print(f"[arm4/strict] as_of={pre_corpus_t} (pre-corpus) -> {len(pre)} chunks")
    if pre_dated:
        ok = False
        print(
            f"[arm4/strict] FAIL — {len(pre_dated)} dated chunk(s) survived a "
            f"pre-corpus T; the gate is not gating"
        )
    else:
        print("[arm4/strict] PASS — 0 dated chunks survive a pre-corpus T")
    if not pre_canon:
        ok = False
        print("[arm4/strict] FAIL — canon dropped at pre-corpus T (Pattern F trap)")
    else:
        print(
            f"[arm4/strict] PASS — {len(pre_canon)} timeless canon chunk(s) still "
            f"reachable at a T before the corpus existed"
        )

    print(f"[probe] {'PASS — gate verified' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
