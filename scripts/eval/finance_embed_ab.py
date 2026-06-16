"""Sampled A/B: ``voyage-finance-2`` vs the live default embedding model.

Phase 2.3 measurement (founder-approved). DECIDES whether a full-corpus
re-embed to the finance-tuned model is worth the spend. It does NOT re-embed
the production corpus and does NOT change the embedder default — both are
separate, founder-gated steps.

------------------------------------------------------------------------------
Why a *self-contained* sample rather than the live Atlas index
------------------------------------------------------------------------------
The live ``chunks`` collection is embedded in the baseline model's vector
space (``EMBED_MODEL`` in env — currently ``voyage-3-large``). A true A/B of
``voyage-finance-2`` needs BOTH the query AND the corpus in finance-2's space.
Re-embedding 24k chunks is exactly the cost we are trying to decide on, so we
cannot use the live index for the finance-2 arm.

Instead we pull a small fixed SAMPLE of trade-relevant chunks (text only) and
embed that sample fresh with each model. The A/B is then a self-contained
ranking problem on the sample::

    for each query:
        rank the sampled chunks by cosine(query_vec, chunk_vec)
        compare that ranking to a model-INDEPENDENT relevance ground truth

------------------------------------------------------------------------------
Ground truth: Voyage ``rerank-2`` cross-encoder
------------------------------------------------------------------------------
A bi-encoder embedding model cannot be its own judge (self-referential top-K
proxies bias toward whichever arm you anchor on). We use the Voyage
``rerank-2`` cross-encoder — a *different* model class that reads the
(query, chunk) pair jointly — to label each sampled chunk's relevance to each
query. The top-R cross-encoder chunks per query are the "relevant" set.
Both embedding arms are then scored by how well their cosine ranking recovers
that cross-encoder ground truth (recall@k, nDCG@k) plus a provider_kind
coverage proxy (does the arm's top-k surface the same canon/protocol mix the
cross-encoder considers relevant).

This is the same "model-independent judge" discipline as the cross-family
rubric judge in ``tests/eval/rubric.py`` (Claude judging GPT debates).

------------------------------------------------------------------------------
Rigor
------------------------------------------------------------------------------
House rule: no single-run "win". ``--runs`` defaults to 2; the sample of
chunks is RE-DRAWN per run (different random seed) so the variance reported
is real sampling variance, not a fixed-sample artifact. We report per-run
deltas and the spread. A win is claimed only if the mean lift exceeds the
spread.

------------------------------------------------------------------------------
Cost
------------------------------------------------------------------------------
Bounded + logged. Per run we embed (~Q + S) short texts twice and rerank
Q*S pairs once. With Q=10, S=120 that is ~260 embeds + ~1200 rerank pairs per
run — single-digit cents. A hard budget guard aborts above ``--budget-usd``.

Graceful degrade: if ``VOYAGE_API_KEY`` is unset / ``__unset__``, the live
A/B is skipped and the script emits ONLY the full-corpus re-embed cost
estimate (which needs the Atlas corpus count, not the key) plus a "needs key"
note.

Usage::

    uv run python -m scripts.eval.finance_embed_ab --runs 2 --sample 120
    uv run python -m scripts.eval.finance_embed_ab --cost-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Force Mongo before any gecko_core import resolves settings.
os.environ.setdefault("GECKO_CHUNK_STORE", "mongo")

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[2]
SUITE_PATH = REPO_ROOT / "tests" / "eval" / "suites" / "defi_trade_suite.json"
OUT_DIR = REPO_ROOT / "tests" / "eval" / "live_runs"

# Provider kinds that the trade panel can actually retrieve (canon + protocol
# + market data + protocol manifests). `web` chunks are general-research and
# are excluded from the trade-relevant cost basis below — but see the
# "full corpus" line in the cost estimate, which re-embeds everything because
# the Atlas index is shared across verticals.
TRADE_PROVIDER_KINDS = [
    "canon_damodaran",
    "canon_berkshire",
    "canon_marks",
    "canon_mauboussin",
    "canon_macro",
    "protocol_native",
    "market_data",
    "paysh_manifest",
    "paysh_live",
    "bazaar_live",
    "bazaar",
    "bazaar_manifest",
]

# Voyage list price per 1M tokens (mirrors embedder._EMBED_RATES_USD_PER_1M).
FINANCE2_RATE_USD_PER_1M = 0.12
# rough chars/token for English prose; Voyage tokenizer ~ 3.8-4.2 chars/tok.
CHARS_PER_TOKEN = 4.0

# Ground-truth knobs.
RELEVANT_R = 5  # top-R cross-encoder chunks per query are "relevant"
EVAL_KS = (3, 5, 10)


# ---------------------------------------------------------------------------
# Pure metric helpers (unit-tested in tests/eval/test_finance_embed_ab.py)
# ---------------------------------------------------------------------------
def cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity. Voyage vectors are L2-normalized so this is a dot,
    but we normalize defensively to stay correct for any caller."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def recall_at_k(ranked_ids: list[str], relevant_ids: set[str], k: int) -> float:
    """Fraction of the relevant set that appears in the top-k ranking."""
    if not relevant_ids:
        return 0.0
    topk = set(ranked_ids[:k])
    return len(topk & relevant_ids) / len(relevant_ids)


def ndcg_at_k(ranked_ids: list[str], rel_gain: dict[str, float], k: int) -> float:
    """nDCG@k with graded gains. ``rel_gain`` maps chunk_id -> gain (0 if
    absent). Ideal DCG sorts gains descending."""
    dcg = 0.0
    for i, cid in enumerate(ranked_ids[:k]):
        g = rel_gain.get(cid, 0.0)
        dcg += g / math.log2(i + 2)
    ideal = sorted(rel_gain.values(), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    if idcg == 0.0:
        return 0.0
    return dcg / idcg


def provider_kind_coverage(
    ranked_ids: list[str],
    id_to_pk: dict[str, str],
    relevant_pks: set[str],
    k: int,
) -> float:
    """Proxy: fraction of the relevant provider_kinds (per the cross-encoder
    ground truth) that the arm's top-k surfaces at all. Rewards an arm that
    keeps the canon/protocol/market-data MIX, not just raw hit count."""
    if not relevant_pks:
        return 0.0
    topk_pks = {id_to_pk.get(cid, "") for cid in ranked_ids[:k]}
    return len(topk_pks & relevant_pks) / len(relevant_pks)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------
@dataclass
class ArmMetrics:
    model: str
    recall_at_k: dict[int, float]
    ndcg_at_k: dict[int, float]
    pk_coverage_at_k: dict[int, float]

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "recall_at_k": {str(k): v for k, v in self.recall_at_k.items()},
            "ndcg_at_k": {str(k): v for k, v in self.ndcg_at_k.items()},
            "pk_coverage_at_k": {str(k): v for k, v in self.pk_coverage_at_k.items()},
        }


# ---------------------------------------------------------------------------
# Voyage calls (live)
# ---------------------------------------------------------------------------
# Voyage caps a single embed batch at 120k tokens. We sub-batch by count so a
# large `sample` never exceeds it (mirrors embedder.EMBED_BATCH_SIZE). Order is
# preserved across sub-batches.
_EMBED_SUB_BATCH = 64


async def _voyage_embed(
    texts: list[str], *, model: str, api_key: str, input_type: str | None
) -> tuple[list[list[float]], int]:
    import voyageai  # type: ignore[import-not-found]
    from voyageai.error import RateLimitError  # type: ignore[import-not-found]

    client = voyageai.AsyncClient(api_key=api_key)
    vectors: list[list[float]] = []
    total = 0
    for start in range(0, len(texts), _EMBED_SUB_BATCH):
        batch = texts[start : start + _EMBED_SUB_BATCH]
        for attempt in range(1, 5):
            try:
                resp = await client.embed(texts=batch, model=model, input_type=input_type)
                vectors.extend(list(resp.embeddings))
                total += int(resp.total_tokens)
                break
            except RateLimitError as exc:
                if attempt >= 4:
                    raise exc
                await asyncio.sleep(random.uniform(0.0, min(20.0, 5.0 * attempt)))
    return vectors, total


async def _voyage_rerank_scores(query: str, docs: list[str], *, api_key: str) -> list[float]:
    """Cross-encoder relevance scores for (query, doc) pairs, doc-order preserved.

    rerank-2 has a per-minute token cap (the project TPM); a large
    ``sample`` * ``n_queries`` slate can trip it. We retry on RateLimitError
    with bounded full-jitter backoff (mirrors the embedder's Voyage path) so
    the measurement degrades to "slower" rather than crashing mid-run.
    """
    import voyageai  # type: ignore[import-not-found]
    from voyageai.error import RateLimitError  # type: ignore[import-not-found]

    client = voyageai.AsyncClient(api_key=api_key)
    last: Exception | None = None
    for attempt in range(1, 5):
        try:
            resp = await client.rerank(
                query=query, documents=docs, model="rerank-2", top_k=len(docs)
            )
            scores = [0.0] * len(docs)
            for r in resp.results:
                scores[r.index] = float(r.relevance_score)
            return scores
        except RateLimitError as exc:
            last = exc
            if attempt >= 4:
                break
            # TPM resets on a 60s window; back off long enough to clear it.
            await asyncio.sleep(random.uniform(0.0, min(20.0, 5.0 * attempt)))
    assert last is not None
    raise last


# ---------------------------------------------------------------------------
# Corpus sampling
# ---------------------------------------------------------------------------
async def _sample_corpus(sample_n: int, seed: int) -> list[dict[str, Any]]:
    """Random sample of trade-relevant chunks (text + provider_kind + id).

    Uses $sample for a fresh draw per seed-run. $sample is non-deterministic;
    we additionally shuffle with the run seed so two runs differ even if Atlas
    returns overlapping draws."""
    from gecko_core.db.mongo import chunks_collection  # type: ignore[import-not-found]

    coll = chunks_collection()
    if coll is None:
        return []
    pipeline = [
        {"$match": {"provider_kind": {"$in": TRADE_PROVIDER_KINDS}, "text": {"$type": "string"}}},
        {"$sample": {"size": sample_n}},
        {"$project": {"_id": 1, "text": 1, "provider_kind": 1}},
    ]
    out: list[dict[str, Any]] = []
    async for d in coll.aggregate(pipeline):
        txt = (d.get("text") or "").strip()
        if not txt:
            continue
        out.append(
            {
                "id": str(d["_id"]),
                "text": txt[:4000],  # cap per-chunk tokens; keeps spend bounded
                "provider_kind": d.get("provider_kind") or "unknown",
            }
        )
    rng = random.Random(seed)
    rng.shuffle(out)
    return out


async def _corpus_cost_estimate() -> dict[str, Any]:
    """Full-corpus re-embed cost for finance-2: count + chars -> tokens -> $."""
    from gecko_core.db.mongo import chunks_collection  # type: ignore[import-not-found]

    coll = chunks_collection()
    if coll is None:
        return {"available": False, "reason": "mongo_collection_unavailable"}

    async def _agg(match: dict[str, Any]) -> tuple[int, int]:
        pipe = [
            {"$match": match},
            {
                "$group": {
                    "_id": None,
                    "n": {"$sum": 1},
                    "chars": {"$sum": {"$strLenCP": {"$ifNull": ["$text", ""]}}},
                }
            },
        ]
        async for d in coll.aggregate(pipe):
            return int(d["n"]), int(d["chars"])
        return 0, 0

    full_n, full_chars = await _agg({})
    trade_n, trade_chars = await _agg({"provider_kind": {"$in": TRADE_PROVIDER_KINDS}})

    def _cost(chars: int) -> dict[str, Any]:
        tokens = chars / CHARS_PER_TOKEN
        usd = tokens * FINANCE2_RATE_USD_PER_1M / 1_000_000
        return {"chars": chars, "est_tokens": round(tokens), "est_usd": round(usd, 4)}

    return {
        "available": True,
        "rate_usd_per_1m": FINANCE2_RATE_USD_PER_1M,
        "chars_per_token_assumed": CHARS_PER_TOKEN,
        "full_corpus": {"chunks": full_n, **_cost(full_chars)},
        "trade_relevant_corpus": {"chunks": trade_n, **_cost(trade_chars)},
    }


# ---------------------------------------------------------------------------
# Budget guard
# ---------------------------------------------------------------------------
class _Budget:
    """Token + rerank-pair accounting with a hard abort ceiling."""

    def __init__(self, ceiling_usd: float) -> None:
        self.ceiling_usd = ceiling_usd
        self.embed_tokens = 0
        self.rerank_pairs = 0

    def add_tokens(self, n: int) -> None:
        self.embed_tokens += n
        self._check()

    def add_rerank_pairs(self, n: int) -> None:
        self.rerank_pairs += n
        self._check()

    def est_usd(self) -> float:
        # both arms embedded at finance-2 / 3-large rate ($0.12-0.18/1M); use
        # the higher rate as the conservative embed estimate. rerank-2 ~
        # $0.05/1M tokens; pairs are short so ~$0.00005/pair is generous.
        embed_usd = self.embed_tokens * 0.18 / 1_000_000
        rerank_usd = self.rerank_pairs * 0.00005
        return embed_usd + rerank_usd

    def _check(self) -> None:
        if self.est_usd() > self.ceiling_usd:
            raise RuntimeError(
                f"voyage budget guard tripped: est ${self.est_usd():.4f} > "
                f"${self.ceiling_usd:.2f} (embed_tokens={self.embed_tokens}, "
                f"rerank_pairs={self.rerank_pairs})"
            )


# ---------------------------------------------------------------------------
# A/B core
# ---------------------------------------------------------------------------
async def _score_arm(
    model: str,
    queries: list[dict[str, Any]],
    sample: list[dict[str, Any]],
    ground_truth: dict[str, dict[str, Any]],
    *,
    api_key: str,
    budget: _Budget,
) -> ArmMetrics:
    sample_texts = [c["text"] for c in sample]
    sample_ids = [c["id"] for c in sample]
    id_to_pk = {c["id"]: c["provider_kind"] for c in sample}

    doc_vecs, dt = await _voyage_embed(
        sample_texts, model=model, api_key=api_key, input_type="document"
    )
    budget.add_tokens(dt)
    q_texts = [q["question"] for q in queries]
    q_vecs, qt = await _voyage_embed(q_texts, model=model, api_key=api_key, input_type="query")
    budget.add_tokens(qt)

    rec: dict[int, list[float]] = {k: [] for k in EVAL_KS}
    ndc: dict[int, list[float]] = {k: [] for k in EVAL_KS}
    pkc: dict[int, list[float]] = {k: [] for k in EVAL_KS}

    for qi, q in enumerate(queries):
        qv = q_vecs[qi]
        scored = sorted(
            ((cosine(qv, doc_vecs[di]), sample_ids[di]) for di in range(len(sample_ids))),
            key=lambda t: t[0],
            reverse=True,
        )
        ranked_ids = [cid for _, cid in scored]
        gt = ground_truth[q["id"]]
        relevant_ids: set[str] = gt["relevant_ids"]
        rel_gain: dict[str, float] = gt["rel_gain"]
        relevant_pks: set[str] = gt["relevant_pks"]
        for k in EVAL_KS:
            rec[k].append(recall_at_k(ranked_ids, relevant_ids, k))
            ndc[k].append(ndcg_at_k(ranked_ids, rel_gain, k))
            pkc[k].append(provider_kind_coverage(ranked_ids, id_to_pk, relevant_pks, k))

    return ArmMetrics(
        model=model,
        recall_at_k={k: statistics.mean(rec[k]) for k in EVAL_KS},
        ndcg_at_k={k: statistics.mean(ndc[k]) for k in EVAL_KS},
        pk_coverage_at_k={k: statistics.mean(pkc[k]) for k in EVAL_KS},
    )


async def _build_ground_truth(
    queries: list[dict[str, Any]],
    sample: list[dict[str, Any]],
    *,
    api_key: str,
    budget: _Budget,
) -> dict[str, dict[str, Any]]:
    """Cross-encoder relevance per query over the sample. top-R = relevant."""
    sample_texts = [c["text"] for c in sample]
    sample_ids = [c["id"] for c in sample]
    id_to_pk = {c["id"]: c["provider_kind"] for c in sample}
    gt: dict[str, dict[str, Any]] = {}
    for q in queries:
        scores = await _voyage_rerank_scores(q["question"], sample_texts, api_key=api_key)
        budget.add_rerank_pairs(len(sample_texts))
        order = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)
        relevant_idx = order[:RELEVANT_R]
        relevant_ids = {sample_ids[i] for i in relevant_idx}
        # graded gain = normalized cross-encoder score (only for the relevant set)
        max_s = max((scores[i] for i in relevant_idx), default=1.0) or 1.0
        rel_gain = {sample_ids[i]: scores[i] / max_s for i in relevant_idx}
        relevant_pks = {id_to_pk[sample_ids[i]] for i in relevant_idx}
        gt[q["id"]] = {
            "relevant_ids": relevant_ids,
            "rel_gain": rel_gain,
            "relevant_pks": relevant_pks,
        }
    return gt


def _key_available() -> str | None:
    key = os.environ.get("VOYAGE_API_KEY")
    if not key or key.strip() in {"", "__unset__"}:
        return None
    return key.strip()


def _baseline_model() -> str:
    return os.environ.get("EMBED_MODEL", "voyage-3-large").strip()


def _load_queries() -> list[dict[str, Any]]:
    data = json.loads(SUITE_PATH.read_text())
    return [{"id": d["id"], "question": d["question"], "protocol": d["protocol"]} for d in data]


async def _run_once(
    run_idx: int,
    *,
    sample_n: int,
    api_key: str,
    budget: _Budget,
    baseline_model: str,
) -> dict[str, Any]:
    queries = _load_queries()
    sample = await _sample_corpus(sample_n, seed=1000 + run_idx)
    if len(sample) < 10:
        raise RuntimeError(
            f"corpus sample too small ({len(sample)}); is the trade corpus populated?"
        )
    gt = await _build_ground_truth(queries, sample, api_key=api_key, budget=budget)
    arm_base = await _score_arm(baseline_model, queries, sample, gt, api_key=api_key, budget=budget)
    arm_fin = await _score_arm(
        "voyage-finance-2", queries, sample, gt, api_key=api_key, budget=budget
    )

    def _delta(a: dict[int, float], b: dict[int, float]) -> dict[str, float]:
        return {str(k): round(b[k] - a[k], 4) for k in EVAL_KS}

    return {
        "run": run_idx,
        "sample_size": len(sample),
        "n_queries": len(queries),
        "baseline": arm_base.to_json(),
        "finance2": arm_fin.to_json(),
        "delta_finance2_minus_baseline": {
            "recall_at_k": _delta(arm_base.recall_at_k, arm_fin.recall_at_k),
            "ndcg_at_k": _delta(arm_base.ndcg_at_k, arm_fin.ndcg_at_k),
            "pk_coverage_at_k": _delta(arm_base.pk_coverage_at_k, arm_fin.pk_coverage_at_k),
        },
    }


def _summarize_variance(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-metric mean delta + spread (max-min) across runs at each k."""
    out: dict[str, Any] = {}
    for metric in ("recall_at_k", "ndcg_at_k", "pk_coverage_at_k"):
        out[metric] = {}
        for k in EVAL_KS:
            vals = [r["delta_finance2_minus_baseline"][metric][str(k)] for r in runs]
            mean = statistics.mean(vals)
            spread = max(vals) - min(vals) if len(vals) > 1 else 0.0
            out[metric][str(k)] = {
                "mean_delta": round(mean, 4),
                "spread": round(spread, 4),
                "per_run": vals,
                # honest gate: a "win" requires mean lift > spread (signal>noise)
                "win_signal": mean > 0 and mean > spread,
            }
    return out


async def main_async(args: argparse.Namespace) -> int:
    cost = await _corpus_cost_estimate()
    key = _key_available()

    report: dict[str, Any] = {
        "kind": "finance_embed_ab",
        "generated_at": datetime.now(UTC).isoformat(),
        "baseline_model": _baseline_model(),
        "candidate_model": "voyage-finance-2",
        "full_reembed_cost_estimate": cost,
    }

    if args.cost_only or key is None:
        report["live_ab"] = {
            "ran": False,
            "reason": "cost_only_flag" if args.cost_only else "voyage_key_unset",
        }
        if key is None and not args.cost_only:
            report["note"] = (
                "VOYAGE_API_KEY unset/__unset__ — live A/B skipped. "
                "Cost estimate only. Set the key to run the sampled lift measurement."
            )
        _emit(report, args)
        return 0

    budget = _Budget(args.budget_usd)
    baseline_model = _baseline_model()
    runs: list[dict[str, Any]] = []
    for i in range(args.runs):
        t0 = time.monotonic()
        run = await _run_once(
            i, sample_n=args.sample, api_key=key, budget=budget, baseline_model=baseline_model
        )
        run["wall_s"] = round(time.monotonic() - t0, 2)
        runs.append(run)

    report["live_ab"] = {
        "ran": True,
        "runs": runs,
        "variance_summary": _summarize_variance(runs),
        "spend": {
            "embed_tokens": budget.embed_tokens,
            "rerank_pairs": budget.rerank_pairs,
            "est_usd": round(budget.est_usd(), 4),
            "budget_ceiling_usd": args.budget_usd,
        },
        "ground_truth": {"judge": "voyage/rerank-2 cross-encoder", "relevant_top_r": RELEVANT_R},
    }
    _emit(report, args)
    return 0


def _emit(report: dict[str, Any], args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d")
    path = OUT_DIR / f"{stamp}-finance-embed-ab.json"
    path.write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    print(f"\n[finance_embed_ab] wrote {path}", file=sys.stderr)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Sampled A/B: voyage-finance-2 vs baseline embedder")
    p.add_argument(
        "--runs", type=int, default=2, help="A/B passes (re-drawn sample each); >=2 for variance"
    )
    p.add_argument("--sample", type=int, default=120, help="corpus chunks sampled per run")
    p.add_argument("--budget-usd", type=float, default=2.0, help="hard Voyage spend ceiling")
    p.add_argument("--cost-only", action="store_true", help="emit only the re-embed cost estimate")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return asyncio.run(main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
