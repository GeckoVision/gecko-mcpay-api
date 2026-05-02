"""Voyage rerank chunk-level A/B harness (S19 R3).

Scope:
    Retrieval-quality only. We hold the orchestration layer constant and
    flip ``GECKO_RERANKER`` between ``none`` (Arm A) and ``voyage`` (Arm B)
    around `gecko_core.rag.query.rag_query`. We measure:

      * citation_precision = |returned ∩ ideal| / |returned|
      * latency wall-clock per call
      * rerank_score presence (sanity check Voyage actually ran in arm B)

    Verdict-accuracy is a downstream synthesis property and is *not*
    measurable at this layer. The plan §2a R3 gate is therefore reduced
    here to retrieval precision + latency.

Ground truth:
    The holdout-live suite has no `must_cite_sources`. We use a top-K
    proxy: arm A's top-3 cosine results are treated as the "ideal"
    surrogate set per query. This biases the harness *against* arm B
    (B has to outperform A using A's own ranking as truth — a strict
    test). Memo flags this caveat.

Corpus:
    Reuses the existing rich Mongo session ``6cc0a982-...`` (59 chunks,
    web/bazaar/twitsh) populated by an earlier ``bb research`` run on
    agentic-payments / x402 content. Queries are crafted to match this
    corpus — the holdout-live suite ideas (comp-band diff, FAA AME
    intake, etc.) are off-topic and would yield zero retrieval signal
    for either arm. The methodology caveat is recorded in the memo.

Budget guard:
    Hard cap at $5. Voyage rerank-2 is ~$0.0005/call * 8 ideas * 1 arm
    = ~$0.004. OpenAI text-embedding-3-small for query encoding is
    ~$0.0001/idea * 16 calls = ~$0.0016. Expected total: <$0.01.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

# Force Mongo + hybrid path before any gecko_core import touches settings.
os.environ.setdefault("GECKO_CHUNK_STORE", "mongo")

# Load .env if present (script is invoked outside the FastAPI/CLI entrypoints
# that normally pick it up).
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_ID = UUID("6cc0a982-8e21-4517-9d9f-565a867ef58d")
TOP_K = 8
IDEAL_K = 3  # top-K proxy for the "ideal" surrogate set per query

# S20-RAG-EVAL-LABELS-01 — labels file path. When `_meta.labeling_status ==
# "labeled"`, real human labels supersede the top-3 proxy. When "candidates_only"
# (or the file is absent), we log a WARN and fall through to the proxy. The
# label-driven precision formula is documented inline in `_label_driven_precision`.
LABELS_PATH = REPO_ROOT / "tests" / "eval" / "labels" / "holdout_chunk_truth.json"

# Queries chosen to match the corpus (agentic payments / x402 / MCP).
# Eight queries: enough to smooth single-call noise, small enough that
# the spend stays well under the $5 cap.
QUERIES: list[dict[str, str]] = [
    {
        "id": "q-x402-protocol",
        "text": "How does the x402 payment protocol work end-to-end between agent and facilitator?",
    },
    {
        "id": "q-agent-pay-agent",
        "text": "Can autonomous AI agents pay each other for services without human approval?",
    },
    {
        "id": "q-mcp-payments",
        "text": "How do MCP servers integrate with agentic payments and what is the threat model?",
    },
    {
        "id": "q-l402-vs-x402",
        "text": "What is the difference between L402 and x402 for agentic commerce?",
    },
    {"id": "q-solana-x402", "text": "How does x402 work on Solana versus EVM chains?"},
    {
        "id": "q-facilitator-trust",
        "text": "What is the trust model of the x402 facilitator and what attacks does it mitigate?",
    },
    {
        "id": "q-bazaar-paid-context",
        "text": "What does Bazaar paid-context provide beyond Tavily search results?",
    },
    {
        "id": "q-agent-commerce-risk",
        "text": "What are the security risks of autonomous agents executing onchain payments?",
    },
]

# Pricing (current vendor cards, May 2026):
VOYAGE_RERANK2_USD_PER_1K = 0.05  # $0.05 / 1k queries (~ $0.00005/call before doc weighting)
EMBED_3_SMALL_USD_PER_1M_TOKENS = 0.02


def _clear_voyage_flag_cache() -> None:
    """Voyage's `_flag_enabled` is not lru_cache'd in source, but reimport-safe.

    Defensive: re-read env on every call by NOT caching anything ourselves.
    """
    # voyage_rerank._flag_enabled reads os.environ at call time (no cache).
    # Nothing to clear — the function is pure. Kept as a hook in case
    # future maintainers wrap it.
    return


async def run_arm(arm: str, query: dict[str, str]) -> dict[str, Any]:
    """Run a single rag_query under the given arm. Returns capture dict."""
    if arm == "A":
        os.environ["GECKO_RERANKER"] = "none"
    elif arm == "B":
        os.environ["GECKO_RERANKER"] = "voyage"
    else:
        raise ValueError(arm)
    _clear_voyage_flag_cache()

    from gecko_core.rag.query import rag_query

    t0 = time.perf_counter()
    chunks = await rag_query(SESSION_ID, query["text"], top_k=TOP_K)
    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "arm": arm,
        "query_id": query["id"],
        "latency_ms": round(latency_ms, 2),
        "n_returned": len(chunks),
        "chunks": [
            {
                "source_id": str(c.source_id),
                "chunk_index": c.chunk_index,
                "source_url": c.source_url,
                "provider_kind": c.provider_kind,
                "similarity": round(c.similarity, 4),
                "rerank_score": (round(c.rerank_score, 4) if c.rerank_score is not None else None),
            }
            for c in chunks
        ],
    }


def _chunk_key(c: dict[str, Any]) -> tuple[str, int]:
    return (c["source_id"], int(c["chunk_index"]))


def citation_precision(returned: list[dict[str, Any]], ideal: set[tuple[str, int]]) -> float:
    if not returned:
        return 0.0
    hit = sum(1 for c in returned if _chunk_key(c) in ideal)
    return hit / len(returned)


def _string_chunk_key(c: dict[str, Any]) -> str:
    """Match the labels file format: ``f"{source_id}#{chunk_index}"``."""
    return f"{c['source_id']}#{int(c['chunk_index'])}"


def load_labels() -> dict[str, Any] | None:
    """Read the labels file, if present. Returns the parsed payload or None."""
    if not LABELS_PATH.exists():
        return None
    try:
        return json.loads(LABELS_PATH.read_text())  # type: ignore[no-any-return]
    except json.JSONDecodeError as exc:
        print(f"WARN: labels file at {LABELS_PATH} is not valid JSON: {exc}")
        return None


def label_driven_precision(
    returned: list[dict[str, Any]],
    must_cite: set[str],
    should_cite: set[str],
    must_not_cite: set[str],
) -> float:
    """Citation precision against hand-labeled ground truth.

    Formula (cap in [0, 1]):
        score = (|returned ∩ must_cite| + 0.5 * |returned ∩ should_cite|
                 - 1.0 * |returned ∩ must_not_cite|) / |returned|

    must_cite hits are full credit, should_cite are bonus (+0.5 each),
    must_not_cite are penalties (−1.0 each). The denominator stays
    |returned| so the result is comparable to the proxy formula above.
    """
    if not returned:
        return 0.0
    keys = [_string_chunk_key(c) for c in returned]
    must_hit = sum(1 for k in keys if k in must_cite)
    should_hit = sum(1 for k in keys if k in should_cite)
    not_hit = sum(1 for k in keys if k in must_not_cite)
    raw = (must_hit + 0.5 * should_hit - 1.0 * not_hit) / float(len(returned))
    return max(0.0, min(1.0, raw))


async def main() -> int:
    print(f"[voyage_chunk_ab] session={SESSION_ID} queries={len(QUERIES)} top_k={TOP_K}")
    if not os.environ.get("VOYAGE_API_KEY"):
        print("ERROR: VOYAGE_API_KEY not set in env; aborting")
        return 2

    # S20-RAG-EVAL-LABELS-01 — decide whether to use real labels or fall through
    # to the top-3 proxy. The proxy is biased-against-arm-B by construction
    # (see module docstring); real labels remove that bias. We log loudly so
    # the operator knows which mode this run used.
    labels_payload = load_labels()
    labels_mode = "proxy"
    if labels_payload is not None:
        status = (labels_payload.get("_meta") or {}).get("labeling_status")
        if status == "labeled":
            labels_mode = "labels"
            print(
                f"[voyage_chunk_ab] labels file at {LABELS_PATH.name} is LABELED — using real ground truth"
            )
        elif status == "candidates_only":
            print(
                f"WARN: labels file is unlabeled (labeling_status='candidates_only'); "
                f"using top-3 proxy. Hand-label {LABELS_PATH.relative_to(REPO_ROOT)} "
                f"then flip status to 'labeled'."
            )
        else:
            print(
                f"WARN: labels file labeling_status={status!r} (expected 'labeled' or 'candidates_only'); using proxy"
            )
    else:
        print(f"WARN: no labels file at {LABELS_PATH.relative_to(REPO_ROOT)}; using top-3 proxy")

    # When real labels are live, drive the loop from the labels file
    # (one row per labeled idea) instead of the hard-coded QUERIES list.
    # The QUERIES list stays as the proxy-mode default because those queries
    # match the existing R3 corpus by design.
    if labels_mode == "labels":
        labeled_ideas = labels_payload.get("ideas") or {}  # type: ignore[union-attr]
        queries_iter: list[dict[str, str]] = [
            {"id": idea_id, "text": payload["idea_text"]}
            for idea_id, payload in labeled_ideas.items()
        ]
        # Per-idea label sets keyed by idea_id (== query_id in this mode).
        label_sets: dict[str, dict[str, set[str]]] = {
            idea_id: {
                "must_cite": set(payload.get("must_cite") or []),
                "should_cite": set(payload.get("should_cite") or []),
                "must_not_cite": set(payload.get("must_not_cite") or []),
            }
            for idea_id, payload in labeled_ideas.items()
        }
    else:
        queries_iter = QUERIES
        label_sets = {}

    per_query: list[dict[str, Any]] = []
    arm_a_lat: list[float] = []
    arm_b_lat: list[float] = []
    arm_a_prec: list[float] = []
    arm_b_prec: list[float] = []
    arm_b_rerank_populated_count = 0

    for q in queries_iter:
        a = await run_arm("A", q)
        b = await run_arm("B", q)

        if labels_mode == "labels":
            ls = label_sets.get(
                q["id"], {"must_cite": set(), "should_cite": set(), "must_not_cite": set()}
            )
            a_prec = label_driven_precision(
                a["chunks"], ls["must_cite"], ls["should_cite"], ls["must_not_cite"]
            )
            b_prec = label_driven_precision(
                b["chunks"], ls["must_cite"], ls["should_cite"], ls["must_not_cite"]
            )
            ideal: set[tuple[str, int]] = set()  # not used in labeled mode
        else:
            # Ideal proxy: arm A's top-3 chunks. (Caveat: biases against arm B.)
            ideal = {_chunk_key(c) for c in a["chunks"][:IDEAL_K]}
            a_prec = citation_precision(a["chunks"], ideal)
            b_prec = citation_precision(b["chunks"], ideal)

        arm_a_lat.append(a["latency_ms"])
        arm_b_lat.append(b["latency_ms"])
        arm_a_prec.append(a_prec)
        arm_b_prec.append(b_prec)

        if any(c["rerank_score"] is not None for c in b["chunks"]):
            arm_b_rerank_populated_count += 1

        per_query.append(
            {
                "query_id": q["id"],
                "query_text": q["text"],
                "ideal_keys": [list(k) for k in ideal],
                "arm_A": {
                    "latency_ms": a["latency_ms"],
                    "n_returned": a["n_returned"],
                    "citation_precision": round(a_prec, 4),
                    "chunks": a["chunks"],
                },
                "arm_B": {
                    "latency_ms": b["latency_ms"],
                    "n_returned": b["n_returned"],
                    "citation_precision": round(b_prec, 4),
                    "chunks": b["chunks"],
                },
                "delta": {
                    "citation_precision_pp": round((b_prec - a_prec) * 100.0, 2),
                    "latency_ms": round(b["latency_ms"] - a["latency_ms"], 2),
                },
            }
        )
        print(
            f"  {q['id']}: A_prec={a_prec:.2f} B_prec={b_prec:.2f}  "
            f"A_lat={a['latency_ms']:.0f}ms B_lat={b['latency_ms']:.0f}ms"
        )

    def _stats(xs: list[float]) -> dict[str, float]:
        return {
            "median": round(statistics.median(xs), 4),
            "mean": round(statistics.mean(xs), 4),
            "min": round(min(xs), 4),
            "max": round(max(xs), 4),
        }

    a_prec_med = statistics.median(arm_a_prec)
    b_prec_med = statistics.median(arm_b_prec)
    a_prec_mean = statistics.mean(arm_a_prec)
    b_prec_mean = statistics.mean(arm_b_prec)
    a_lat_med = statistics.median(arm_a_lat)
    b_lat_med = statistics.median(arm_b_lat)

    delta_prec_pp_mean = (b_prec_mean - a_prec_mean) * 100.0
    delta_prec_pp_median = (b_prec_med - a_prec_med) * 100.0
    delta_lat_p50_ms = b_lat_med - a_lat_med

    # Gate per S19 plan §2a R3 (chunk-level adapted):
    #   TRIP iff citation_precision lifts >= +10pp AND latency_p50 regression <= 300ms
    gate_prec_lift_ok = delta_prec_pp_mean >= 10.0
    gate_latency_ok = delta_lat_p50_ms <= 300.0
    gate_tripped = gate_prec_lift_ok and gate_latency_ok

    # Cost estimate (token-count basis):
    # - Voyage rerank-2: 1 call/query * 8 queries = 8 calls
    #   approximate $0.05 / 1k calls ~= $0.0004 total
    # - OpenAI embed: 1 call/query * 16 (8 queries * 2 arms)
    #   ~ avg 20 tokens/query => 320 tokens => ~$0.0000064
    voyage_calls = len(queries_iter)  # only arm B calls Voyage
    voyage_cost_est = voyage_calls * (VOYAGE_RERANK2_USD_PER_1K / 1000.0)
    embed_calls = len(queries_iter) * 2
    embed_tokens_est = embed_calls * 25  # ~25 tok/query incl framing
    embed_cost_est = embed_tokens_est * (EMBED_3_SMALL_USD_PER_1M_TOKENS / 1_000_000.0)
    total_cost_est = round(voyage_cost_est + embed_cost_est, 6)

    aggregate = {
        "n_queries": len(queries_iter),
        "top_k": TOP_K,
        "ideal_proxy_k": IDEAL_K if labels_mode == "proxy" else None,
        "labels_mode": labels_mode,
        "arm_A": {
            "citation_precision": _stats(arm_a_prec),
            "latency_ms": _stats(arm_a_lat),
        },
        "arm_B": {
            "citation_precision": _stats(arm_b_prec),
            "latency_ms": _stats(arm_b_lat),
            "rerank_score_populated_query_count": arm_b_rerank_populated_count,
        },
        "delta": {
            "citation_precision_pp_mean": round(delta_prec_pp_mean, 2),
            "citation_precision_pp_median": round(delta_prec_pp_median, 2),
            "latency_p50_ms": round(delta_lat_p50_ms, 2),
        },
        "gate": {
            "spec": "delta_prec_pp_mean >= 10 AND delta_lat_p50_ms <= 300",
            "prec_lift_ok": gate_prec_lift_ok,
            "latency_ok": gate_latency_ok,
            "tripped": gate_tripped,
        },
        "cost_est_usd": {
            "voyage_calls": voyage_calls,
            "voyage_usd": round(voyage_cost_est, 6),
            "embed_calls": embed_calls,
            "embed_tokens_est": embed_tokens_est,
            "embed_usd": round(embed_cost_est, 6),
            "total_usd": total_cost_est,
        },
    }

    out = {
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "session_id": str(SESSION_ID),
        "ground_truth": (
            "hand-labeled (S20-RAG-EVAL-LABELS-01)"
            if labels_mode == "labels"
            else "top-K proxy (arm A top-3) — NOT real ground truth"
        ),
        "labels_mode": labels_mode,
        "aggregate": aggregate,
        "per_query": per_query,
    }

    out_path = REPO_ROOT / "tests" / "eval" / "live_runs" / "2026-05-02-s19-r3-chunk-ab.json"
    out_path.write_text(json.dumps(out, indent=2, sort_keys=False) + "\n")
    print(f"\n[voyage_chunk_ab] wrote {out_path.relative_to(REPO_ROOT)}")
    print(json.dumps(aggregate, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
