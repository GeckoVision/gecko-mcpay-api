"""Trade research panel — 7-agent AG2 GroupChat (Phase 8a).

Public surface:

    from gecko_core.orchestration.trade_panel import run_trade_panel

    verdict = await run_trade_panel(
        idea="Should I open a long on JTO around the next FOMC?",
        protocol="jito",
        retrieved_chunks=[{"text": "...", "source": "exa", "ts": "..."}, ...],
        tier="basic",
    )
    assert verdict.verdict in {"act", "pass", "defer"}

The panel does NOT do retrieval — Phase 8b's caller passes pre-fetched
chunks in. The panel does NOT have its own eval harness in v1 — the Pro
calibration block / falsifier infra is intentionally not cloned.

Speaker order is canonical and round-robin. The driver below walks
REQUIRED_AGENTS in order, dispatches each agent's reply, parses the
closing line, and assembles a TradePanelVerdict from the coordinator's
last turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import re
from collections.abc import Callable
from typing import Any, Protocol, cast

from gecko_core.orchestration.trade_panel.agents import build_groupchat
from gecko_core.orchestration.trade_panel.models import (
    Citation,
    TradePanelTurn,
    TradePanelVerdict,
    TradeVerdictLiteral,
)
from gecko_core.orchestration.trade_panel.personas import (
    BULL_BEAR_DEBATER,
    CLOSING_LINE_PATTERNS,
    COORDINATOR,
    FUNDAMENTAL_ANALYST,
    REQUIRED_AGENTS,
    RISK_MANAGER,
    SENTIMENT_ANALYST,
    STRATEGIST,
    TECHNICAL_ANALYST,
)
from gecko_core.orchestration.trade_panel.prompts import (
    TradePanelPromptsConfigError,
    load_prompts,
)
from gecko_core.sources.types import (
    FRESHNESS_TIER_VALUES,
    PROVIDER_KINDS,
    FreshnessTier,
    ProviderKind,
)

_log = logging.getLogger(__name__)

__all__ = [
    "BULL_BEAR_DEBATER",
    "COORDINATOR",
    "FUNDAMENTAL_ANALYST",
    "REQUIRED_AGENTS",
    "RISK_MANAGER",
    "SENTIMENT_ANALYST",
    "STRATEGIST",
    "TECHNICAL_ANALYST",
    "Citation",
    "TradePanelPromptsConfigError",
    "TradePanelTurn",
    "TradePanelVerdict",
    "TradeVerdictLiteral",
    "build_citations_from_chunks",
    "build_groupchat",
    "load_prompts",
    "retrieve_trade_corpus_chunks",
    "run_trade_panel",
    "run_trade_panel_with_retrieval",
]

# Pre-compiled closing-line regexes — case-insensitive, multiline-friendly.
_CLOSING_RE: dict[str, re.Pattern[str]] = {
    name: re.compile(pat, re.IGNORECASE | re.MULTILINE)
    for name, pat in CLOSING_LINE_PATTERNS.items()
}

# Per-voice timeout. Trade-panel v1 keeps the same default as Pro to start;
# tune separately when we have eval data.
_PER_VOICE_TIMEOUT_S: float = 120.0
_RAG_CONTEXT_CHAR_CAP: int = 8000


class _LLMReplier(Protocol):
    """Minimal interface tests can satisfy without AG2.

    Real AG2 ConversableAgent implements ``a_generate_reply(messages=...)``.
    Tests inject a fake replier with the same shape — no autogen install
    required.
    """

    async def a_generate_reply(
        self, messages: list[dict[str, Any]]
    ) -> str | dict[str, Any] | None:  # pragma: no cover - protocol
        ...


def _format_chunks(chunks: list[dict[str, Any]]) -> str:
    """Render retrieved chunks as a numbered context block.

    Indexed so the personas can cite by chunk index in their bodies.
    Each chunk is rendered as ``[idx] (source) text``. Truncated to
    ``_RAG_CONTEXT_CHAR_CAP`` total characters to keep round-1 cheap.
    """
    if not chunks:
        return "(no retrieved chunks — corpus empty for this protocol)"
    lines: list[str] = []
    for idx, chunk in enumerate(chunks, start=1):
        source = chunk.get("source") or chunk.get("provider_kind") or "unknown"
        text = (chunk.get("text") or chunk.get("content") or "").strip()
        if not text:
            continue
        lines.append(f"[{idx}] ({source}) {text}")
    block = "\n\n".join(lines)
    if len(block) > _RAG_CONTEXT_CHAR_CAP:
        block = block[:_RAG_CONTEXT_CHAR_CAP] + "\n\n[context truncated for budget]"
    return block


def _opening_prompt(idea: str, protocol: str, chunks: list[dict[str, Any]]) -> str:
    """Seed message for the panel — stable shape across all 7 personas."""
    return (
        f"Research question: {idea}\n\n"
        f"Protocol in scope: {protocol}\n\n"
        f"Retrieved corpus chunks (numbered for citation):\n{_format_chunks(chunks)}\n\n"
        "Each persona contributes once, in this order: "
        "technical_analyst → sentiment_analyst → fundamental_analyst → "
        "risk_manager → strategist → bull_bear_debater → coordinator. "
        "End your turn with the exact closing line specified by your role."
    )


def _reply_text(reply: Any) -> str:
    if isinstance(reply, dict):
        content = reply.get("content")
        return str(content) if content is not None else ""
    if reply is None:
        return ""
    return str(reply)


def _last_nonempty_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_json_block(text: str) -> dict[str, Any] | None:
    """Pull the ```json ... ``` fenced block from the coordinator turn."""
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL | re.IGNORECASE)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_closing_line(agent: str, text: str) -> dict[str, Any] | None:
    """Match the agent's closing-line regex against the last non-empty line.

    Returns a structured dict like ``{"trend_verdict": "bullish"}`` keyed by
    a stable name per persona. ``None`` when the line is missing or doesn't
    match — caller should treat as a soft parse failure.
    """
    pattern = _CLOSING_RE.get(agent)
    if pattern is None:
        return None
    line = _last_nonempty_line(text)
    if not line:
        return None
    m = pattern.match(line)
    if not m:
        return None
    captured = m.group(1).strip()
    key_map = {
        TECHNICAL_ANALYST: "trend_verdict",
        SENTIMENT_ANALYST: "sentiment_band",
        FUNDAMENTAL_ANALYST: "protocol_health",
        RISK_MANAGER: "risk_band",
        STRATEGIST: "strategic_intent",
        BULL_BEAR_DEBATER: "decisive_question",
        COORDINATOR: "verdict",
    }
    return {key_map[agent]: captured}


# Maps each non-coordinator persona's parsed verdict value to the
# "directional bias" we compare against the coordinator's act/pass call.
# 'act' aligns with bullish/greed/growing/acceptable/<intent present>;
# 'pass' aligns with bearish/fear/degraded/unacceptable.
# Ambiguous values (mixed/neutral/stable/elevated) count as no-vote.
_VERDICT_ALIGNS_ACT = {
    TECHNICAL_ANALYST: {"bullish"},
    SENTIMENT_ANALYST: {"greed"},
    FUNDAMENTAL_ANALYST: {"growing"},
    RISK_MANAGER: {"acceptable"},
}
_VERDICT_ALIGNS_PASS = {
    TECHNICAL_ANALYST: {"bearish"},
    SENTIMENT_ANALYST: {"fear"},
    FUNDAMENTAL_ANALYST: {"degraded"},
    RISK_MANAGER: {"unacceptable"},
}


def _voice_directional(agent: str, parsed: dict[str, Any] | None) -> str | None:
    """Return 'act', 'pass', or None for a non-coordinator voice."""
    if parsed is None:
        return None
    if agent in _VERDICT_ALIGNS_ACT:
        # Only the four primary analysts vote directionally; strategist and
        # debater outputs are free-text and don't map cleanly.
        key = next(iter(parsed.keys()))
        val = parsed.get(key)
        if isinstance(val, str):
            v = val.strip().lower()
            if v in _VERDICT_ALIGNS_ACT[agent]:
                return "act"
            if v in _VERDICT_ALIGNS_PASS[agent]:
                return "pass"
    return None


def _count_dissent(turns: list[TradePanelTurn], final_verdict: str) -> int:
    """How many primary analysts pointed AGAINST the coordinator's call."""
    if final_verdict not in {"act", "pass"}:
        # 'defer' has no clean opposite — return 0 rather than guess.
        return 0
    opposite = "pass" if final_verdict == "act" else "act"
    count = 0
    for turn in turns:
        if turn.agent == COORDINATOR:
            continue
        directional = _voice_directional(turn.agent, turn.parsed_verdict)
        if directional == opposite:
            count += 1
    return count


def _coerce_verdict_token(raw: Any) -> TradeVerdictLiteral:
    """Squash a free-form verdict string into the Literal — strict whitelist."""
    if isinstance(raw, str):
        v = raw.strip().lower()
        if v in {"act", "pass", "defer"}:
            return cast(TradeVerdictLiteral, v)
    # Fallback: defer is the safest unknown-state.
    return "defer"


def _coerce_confidence(raw: Any) -> float:
    try:
        val = float(raw)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, val))


def _coerce_str_list(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _build_verdict_from_coordinator(
    turns: list[TradePanelTurn],
) -> TradePanelVerdict:
    """Assemble the final TradePanelVerdict from the coordinator's last turn.

    Prefers the JSON-fenced block (richer structure); falls back to the
    closing-line capture for the verdict token alone.
    """
    coord_turn = next((t for t in turns if t.agent == COORDINATOR), None)
    if coord_turn is None:
        # No coordinator turn at all — defer with empty drivers, dissent 0.
        return TradePanelVerdict(
            verdict="defer",
            confidence=0.0,
            key_drivers=[],
            dissent_count=0,
            blocker_questions=["coordinator turn missing"],
            turns=turns,
        )

    block = _extract_json_block(coord_turn.content) or {}
    closing = coord_turn.parsed_verdict or {}

    verdict = _coerce_verdict_token(block.get("verdict") or closing.get("verdict"))
    confidence = _coerce_confidence(block.get("confidence", 0.5))
    key_drivers = _coerce_str_list(block.get("key_drivers"))
    blocker_questions = _coerce_str_list(block.get("blocker_questions"))

    # Dissent count: trust the coordinator's self-report when present and
    # non-negative-int; otherwise compute from analyst turns.
    raw_dissent = block.get("dissent_count")
    if isinstance(raw_dissent, int) and raw_dissent >= 0:
        dissent_count = raw_dissent
    else:
        dissent_count = _count_dissent(turns, verdict)

    return TradePanelVerdict(
        verdict=verdict,
        confidence=confidence,
        key_drivers=key_drivers,
        dissent_count=dissent_count,
        blocker_questions=blocker_questions,
        turns=turns,
    )


# Type alias for the agent-factory callback tests inject. Production
# callers don't pass this — build_groupchat is used by default.
AgentFactory = Callable[[dict[str, Any]], dict[str, _LLMReplier]]


async def run_trade_panel(
    idea: str,
    protocol: str,
    retrieved_chunks: list[dict[str, Any]],
    *,
    tier: str = "basic",
    llm_config: dict[str, Any] | None = None,
    agent_factory: AgentFactory | None = None,
) -> TradePanelVerdict:
    """Run the 7-agent trade research panel.

    Args:
        idea: The user's research question.
        protocol: Protocol in scope (e.g. ``"kamino"``, ``"jito"``).
        retrieved_chunks: Pre-fetched corpus chunks. Phase 8b's caller does
            the retrieval; this function does NOT touch the vector store.
        tier: ``"basic"`` (default) or ``"pro"``. Currently only used by
            Phase 8b's caller for routing/cost; v1 panel logic is identical
            across tiers.
        llm_config: AG2 llm_config. Required for production paths. Tests
            pass ``agent_factory`` and may omit this.
        agent_factory: Test-only hook. Given the llm_config, returns a
            ``{persona_name: replier}`` mapping. When provided, the AG2
            GroupChat is bypassed entirely — useful for fakes that don't
            require autogen installed.

    Returns:
        :class:`TradePanelVerdict` with all 7 turns + the coordinator's
        final verdict shape.
    """
    if not agent_factory and llm_config is None:
        raise ValueError(
            "run_trade_panel requires either llm_config (production) or "
            "agent_factory (tests). Got neither."
        )

    seed = _opening_prompt(idea, protocol, retrieved_chunks)

    # Resolve the per-agent replier map.
    if agent_factory is not None:
        repliers = agent_factory(llm_config or {})
        missing = [n for n in REQUIRED_AGENTS if n not in repliers]
        if missing:
            raise ValueError(f"agent_factory returned no replier for required personas: {missing}")
    else:
        manager = build_groupchat(llm_config or {})
        repliers = {a.name: cast(_LLMReplier, a) for a in manager.groupchat.agents}

    # Round-robin: each agent sees the seed + all prior turns. We append
    # turns into a shared message list as we go so the coordinator (last)
    # gets the full panel context.
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": seed},
    ]
    turns: list[TradePanelTurn] = []

    for agent_name in REQUIRED_AGENTS:
        replier = repliers[agent_name]
        try:
            reply = await asyncio.wait_for(
                replier.a_generate_reply(messages=list(messages)),
                timeout=_PER_VOICE_TIMEOUT_S,
            )
        except TimeoutError:
            content = f"(voice failed: timeout after {int(_PER_VOICE_TIMEOUT_S)}s)"
            _log.warning("trade_panel.voice_timeout agent=%s", agent_name)
            turns.append(TradePanelTurn(agent=agent_name, content=content, parsed_verdict=None))
            messages.append({"role": "assistant", "content": content})
            continue
        except Exception as exc:  # pragma: no cover - defensive
            content = f"(voice failed: {type(exc).__name__})"
            _log.warning("trade_panel.voice_error agent=%s err=%s", agent_name, exc)
            turns.append(TradePanelTurn(agent=agent_name, content=content, parsed_verdict=None))
            messages.append({"role": "assistant", "content": content})
            continue

        text = _reply_text(reply)
        parsed = _parse_closing_line(agent_name, text)
        turns.append(TradePanelTurn(agent=agent_name, content=text, parsed_verdict=parsed))
        messages.append({"role": "assistant", "content": text})

    return _build_verdict_from_coordinator(turns)


# ---------------------------------------------------------------------------
# Phase 8b — retrieval glue
#
# The panel itself stays retrieval-agnostic (Phase 8a contract). This
# convenience wrapper is the public entry point the MCP tool + REST endpoint
# call: it embeds the question once, reads top-K chunks scoped to
# (vertical, protocol) from the trading-oracle corpus, and forwards into
# run_trade_panel.
#
# Why filter shape: the `vertical` field IS declared as a filterable path on
# the chunks_vector index (see CHUNKS_VECTOR_FILTER_FIELDS); `protocol` is
# NOT. We push `vertical` into $vectorSearch.filter (Atlas pre-filters before
# the ANN graph traversal) and post-$match on `protocol` after the kNN. This
# keeps round trips at one and avoids a noisy index migration just for the
# trade-research surface.
# ---------------------------------------------------------------------------

_DEFAULT_TRADE_TOP_K: int = 15

# S33-#82 — canon retrieval floor. The trade-idea query embeds ~0.55 cosine
# to protocol_native API text and only ~0.38-0.41 to canon investor-canon
# prose, so canon loses the single-pool ANN race outright (0/75 every
# fixture — see docs/eval/2026-05-16-s33-retrieval-pipeline-validation.md).
# A single $vectorSearch can never surface canon for these queries. The fix
# is a structural floor: a SECOND $vectorSearch leg pre-filtered to canon
# provider_kinds (an indexed filterable path) guarantees N canon chunks
# reach the panel alongside protocol_native. The two slates are merged
# BEFORE the Voyage reranker so the cross-encoder reorders a slate that
# actually contains canon. This mirrors rag_query's _rerank_by_provider
# per-kind quota rescue, which the trade-panel path previously lacked.
_CANON_PROVIDER_KINDS: tuple[str, ...] = tuple(
    pk for pk in PROVIDER_KINDS if pk.startswith("canon_")
)
# Floor of canon chunks guaranteed in the final top_k slate. The canon leg
# fetches a per-kind-balanced pool (see _retrieve_canon_floor) and the
# post-rerank quota reserves this many slots for it. 6 of top_k=15 keeps
# protocol_native the majority voice while guaranteeing the panel sees a
# diverse canon mix.
_CANON_FLOOR_COUNT: int = 6
# Per-canon-kind fetch cap for the canon leg. A single canon $vectorSearch
# is monopolised by whichever canon kind sits closest in embedding space —
# measured: canon_macro (Fed/BIS papers) wins the canon ANN race for trade
# queries and a single pooled leg returns 6/6 canon_macro, starving the
# canon_marks / canon_damodaran the fixtures actually demand. So the canon
# leg issues ONE $vectorSearch PER canon kind, capped at this many each,
# then round-robin merges — guaranteeing kind diversity by construction.
_CANON_PER_KIND_CAP: int = 4


async def _retrieve_canon_floor(
    *,
    query_vector: list[float],
    vertical: str,
    floor: int,
) -> list[dict[str, Any]]:
    """Second $vectorSearch leg, pre-filtered to canon ``provider_kind``s.

    S33-#82. The main leg's slate is monoculture ``protocol_native`` because
    a trade-idea query is far closer to API text than to investor-canon
    prose. This leg filters the ANN search to the canon kinds via the
    ``provider_kind`` indexed filterable path, so canon chunks are ranked
    only against *each other* and a guaranteed ``floor`` of them survives.

    Returns up to ``floor`` plain dicts shaped identically to the main
    leg's rows (same ``$project`` keys). Canon chunks carry ``protocol=[]``
    so they need no protocol ``$match`` — they are cross-cutting frameworks
    valid for every protocol. Degrades to ``[]`` on any error; a canon-leg
    failure must never break retrieval.
    """
    if floor <= 0 or not _CANON_PROVIDER_KINDS:
        return []

    from gecko_core.db.mongo import VECTOR_INDEX_NAME, chunks_collection

    coll = chunks_collection()
    if coll is None:
        return []

    def _row_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": str(doc.get("_id", "")),
            "text": doc.get("text") or "",
            "source_url": doc.get("source_url") or "",
            "source": (doc.get("source") or doc.get("provider_kind") or "unknown"),
            "provider_kind": doc.get("provider_kind") or "web",
            "freshness_tier": doc.get("freshness_tier") or "static",
            "protocol": doc.get("protocol") or [],
            "vertical": doc.get("vertical") or vertical,
            "score": float(doc.get("score") or 0.0),
        }

    project_stage: dict[str, Any] = {
        "$project": {
            "_id": 1,
            "source_url": 1,
            "text": 1,
            "vertical": 1,
            "protocol": 1,
            "provider_kind": 1,
            "freshness_tier": 1,
            "source": 1,
            "metadata": 1,
            "score": {"$meta": "vectorSearchScore"},
        }
    }

    # One $vectorSearch PER canon kind, capped at _CANON_PER_KIND_CAP each.
    # A single pooled canon leg is monopolised by the canon kind closest in
    # embedding space (canon_macro for trade queries); per-kind legs
    # guarantee canon_marks / canon_damodaran candidates exist before the
    # round-robin merge. Each leg is small (cap ~4) so the extra Atlas round
    # trips are cheap. A per-kind leg failure degrades that kind only.
    per_kind: dict[str, list[dict[str, Any]]] = {}
    for kind in _CANON_PROVIDER_KINDS:
        pipeline: list[dict[str, Any]] = [
            {
                "$vectorSearch": {
                    "index": VECTOR_INDEX_NAME,
                    "path": "embedding",
                    "queryVector": query_vector,
                    "numCandidates": max(200, _CANON_PER_KIND_CAP * 40),
                    "limit": _CANON_PER_KIND_CAP,
                    "exact": False,
                    "filter": {
                        "vertical": {"$eq": vertical},
                        "provider_kind": {"$eq": kind},
                        "metadata.deprecated": {"$ne": True},
                    },
                }
            },
            project_stage,
        ]
        kind_rows: list[dict[str, Any]] = []
        try:
            async for doc in coll.aggregate(pipeline):
                kind_rows.append(_row_from_doc(doc))
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("trade_panel.retrieve.canon_leg_error kind=%s err=%s", kind, exc)
            continue
        if kind_rows:
            per_kind[kind] = kind_rows

    if not per_kind:
        return []

    # Round-robin across canon kinds so the returned pool is kind-balanced:
    # take the top chunk of each kind, then the 2nd of each, etc. The
    # post-rerank quota downstream re-scores this pool, but a balanced pool
    # in means a balanced (canon_marks + canon_damodaran + ...) set survives.
    merged: list[dict[str, Any]] = []
    rank = 0
    while True:
        added_this_round = False
        for kind in _CANON_PROVIDER_KINDS:
            rows_for_kind = per_kind.get(kind, [])
            if rank < len(rows_for_kind):
                merged.append(rows_for_kind[rank])
                added_this_round = True
        if not added_this_round:
            break
        rank += 1
    return merged


async def retrieve_trade_corpus_chunks(
    *,
    idea: str,
    protocol: str,
    vertical: str = "dex",
    top_k: int = _DEFAULT_TRADE_TOP_K,
) -> list[dict[str, Any]]:
    """Embed ``idea`` and read top-K chunks scoped to ``(vertical, protocol)``.

    Returns a list of plain dicts shaped for ``run_trade_panel`` (``text`` +
    ``source`` keys are the only contract). Returns ``[]`` when the chunk
    store is not configured for Mongo, when the embedder yields no vector,
    or when the corpus has no matching rows. Production-only — no Supabase
    fallback because the trading-oracle corpus is Mongo-native.
    """
    if top_k <= 0 or not idea.strip():
        return []
    proto_norm = protocol.strip().lower()
    if not proto_norm:
        return []

    # Issue #12 — diagnostic instrumentation. Log entry to retrieval so we
    # can disambiguate "handler never called retrieval" from "retrieval was
    # called but Atlas returned 0 hits". Protocol/vertical are echoed
    # verbatim so we can spot casing / whitespace / vertical drift between
    # ingest tagging and read-side filter.
    _log.info(
        "trade_panel.retrieve.entry protocol=%s vertical=%s top_k=%d question_len=%d",
        proto_norm,
        vertical,
        top_k,
        len(idea),
    )

    # Lazy imports keep gecko_core's startup cost off the trade_panel package
    # import path (the in-process MCP server imports this module at boot).
    from gecko_core.db import get_chunk_store
    from gecko_core.db.mongo import VECTOR_INDEX_NAME, chunks_collection
    from gecko_core.ingestion.embedder import embed
    from gecko_core.rag.voyage_rerank import voyage_rerank_dicts

    if get_chunk_store() != "mongo":
        _log.warning(
            "trade_panel.retrieve.skip reason=non_mongo_store store=%s",
            get_chunk_store(),
        )
        return []
    coll = chunks_collection()
    if coll is None:
        _log.warning("trade_panel.retrieve.skip reason=no_collection")
        return []

    # S33-#82 — query embed input_type. S33-#79 set input_type="query" on
    # the asymmetric-retrieval assumption. The S33-#81 diagnosis measured
    # the opposite: vs a fixed canon chunk, query-side "query" embedding
    # gives cos 0.38 while symmetric None gives 0.41 and "document" 0.53 —
    # "query" *widens* the query<->canon gap. The live $vectorSearch band
    # (~0.55 true cosine) matches the document-style pairing, not the
    # query-style one. Reverted to symmetric None: it ranks canon strictly
    # higher than "query" and needs no corpus re-embed (the corpus was
    # re-embedded "document" in #80; None query vs document corpus is the
    # closest available pairing without a re-embed). This is a query-side
    # code-only change. NOTE: the structural canon fix is the canon-floor
    # leg below — input_type alone moves cosine ~0.03 but canon still loses
    # the single-pool ANN race outright (0/75 at every input_type).
    vectors, _tokens = await embed([idea], input_type=None)
    if not vectors:
        _log.warning("trade_panel.retrieve.skip reason=empty_embed_vector")
        return []
    query_vector = vectors[0]

    # numCandidates oversized vs. top_k — Atlas's ANN graph needs slack to
    # land good rows after the post-$match on protocol filters out chunks
    # that survive the vertical pre-filter but are tagged for a different
    # protocol. 20x is the same shape `build_filterable_pipeline` uses.
    pipeline: list[dict[str, Any]] = [
        {
            "$vectorSearch": {
                "index": VECTOR_INDEX_NAME,
                "path": "embedding",
                "queryVector": query_vector,
                "numCandidates": max(200, top_k * 20),
                "limit": top_k * 5,
                "exact": False,
                "filter": {
                    "vertical": {"$eq": vertical},
                    "metadata.deprecated": {"$ne": True},
                },
            }
        },
        # Protocol-tagged chunks (paysh_live, bazaar_live) match exact;
        # general investor-canon chunks (canon_marks/berkshire/damodaran,
        # tagged protocol=[]) surface for ALL protocols since they're
        # cross-cutting frameworks. See docs/strategy/2026-05-11-
        # retrieval-wedge-sprint.md — this is the wedge: canon corpus
        # must reach the panel regardless of named protocol.
        {
            "$match": {
                "$or": [
                    {"protocol": proto_norm},
                    {"protocol": {"$size": 0}},
                    {"protocol": {"$exists": False}},
                ]
            }
        },
        # S33-#79 — keep the full over-fetch slate (top_k * 5) here so the
        # Voyage cross-encoder reranker downstream has a wide candidate set
        # to re-score. The true top_k truncation happens *after* rerank
        # (see voyage_rerank_dicts below); on the legacy / flag-off path the
        # reranker no-ops and returns the vector-order slate[:top_k].
        {"$limit": top_k * 5},
        {
            "$project": {
                "_id": 1,
                "source_url": 1,
                "text": 1,
                "vertical": 1,
                "protocol": 1,
                "provider_kind": 1,
                "freshness_tier": 1,
                "source": 1,
                "metadata": 1,
                "score": {"$meta": "vectorSearchScore"},
            }
        },
    ]

    rows: list[dict[str, Any]] = []
    try:
        async for doc in coll.aggregate(pipeline):
            rows.append(
                {
                    "id": str(doc.get("_id", "")),
                    "text": doc.get("text") or "",
                    "source_url": doc.get("source_url") or "",
                    # Prefer the catalog-named `source` (e.g. "exa", "zerion",
                    # "paysh"); fall back to the legacy provider_kind tag.
                    "source": (doc.get("source") or doc.get("provider_kind") or "unknown"),
                    "provider_kind": doc.get("provider_kind") or "web",
                    "freshness_tier": doc.get("freshness_tier") or "static",
                    "protocol": doc.get("protocol") or proto_norm,
                    "vertical": doc.get("vertical") or vertical,
                    "score": float(doc.get("score") or 0.0),
                }
            )
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("trade_panel.retrieve.error err=%s", exc)
        return []

    # S33-#82 — canon retrieval floor with a POST-rerank quota.
    #
    # An earlier shape merged canon into a single pre-rerank slate, but the
    # cross-encoder scores protocol_native API text above canon prose for a
    # trade-idea query, so a single rerank still truncated canon down to ~1
    # of top_k and, worse, kept whichever canon chunk happened to score
    # highest (often canon_macro) rather than a balanced canon mix. The
    # structural fix is a quota that bites AFTER rerank: rerank the two
    # legs INDEPENDENTLY, then assemble the final top_k as
    # `(top_k - quota)` protocol rows + `quota` canon rows. Each canon
    # slot is still the most query-relevant canon chunk per the
    # cross-encoder — the rerank does the ordering, the quota does the
    # structural guarantee. Mirrors rag_query's _rerank_by_provider
    # reserve_quota, which the trade-panel path previously lacked.
    pre_rerank_count = len(rows)
    canon_rows = await _retrieve_canon_floor(
        query_vector=query_vector,
        vertical=vertical,
        floor=_CANON_FLOOR_COUNT,
    )
    seen_ids = {r["id"] for r in rows if r.get("id")}
    canon_rows = [r for r in canon_rows if r.get("id") not in seen_ids]

    # S33-#79 — semantic rerank. $vectorSearch returns a flat cosine band;
    # cosine alone cannot separate on-target from loosely-related chunks at
    # that resolution. A Voyage rerank-2 cross-encoder re-scores each leg by
    # true query relevance. Flag-gated on GECKO_RERANKER=voyage; graceful-
    # degrades to the vector-order slate on flag-off, missing key, timeout,
    # or any API error — retrieval never breaks on a rerank failure.
    canon_quota = min(_CANON_FLOOR_COUNT, top_k) if canon_rows else 0
    protocol_slots = max(0, top_k - canon_quota)
    protocol_reranked = await voyage_rerank_dicts(idea, rows, top_n=top_k)
    canon_reranked: list[dict[str, Any]] = []
    if canon_rows:
        # Rerank the whole balanced canon pool, then pick the quota by
        # round-robin across canon kinds so the cross-encoder cannot
        # re-collapse the slate onto one canon kind. The rerank still
        # orders WITHIN each kind by query relevance; the round-robin
        # preserves the kind diversity the canon leg built in.
        canon_pool = await voyage_rerank_dicts(idea, canon_rows, top_n=len(canon_rows))
        by_kind: dict[str, list[dict[str, Any]]] = {}
        for r in canon_pool:
            by_kind.setdefault(str(r.get("provider_kind") or ""), []).append(r)
        rr = 0
        while len(canon_reranked) < canon_quota:
            added = False
            for kind_rows in by_kind.values():
                if rr < len(kind_rows):
                    canon_reranked.append(kind_rows[rr])
                    added = True
                    if len(canon_reranked) >= canon_quota:
                        break
            if not added:
                break
            rr += 1

    # Assemble: protocol head fills the non-quota slots, canon fills the
    # quota, then any spare capacity (canon leg returned fewer than quota)
    # is back-filled from the protocol tail. dedup by id throughout.
    final_rows: list[dict[str, Any]] = []
    final_ids: set[str] = set()
    for r in protocol_reranked[:protocol_slots]:
        rid = str(r.get("id") or "")
        if rid and rid in final_ids:
            continue
        final_rows.append(r)
        final_ids.add(rid)
    for r in canon_reranked[:canon_quota]:
        rid = str(r.get("id") or "")
        if rid and rid in final_ids:
            continue
        final_rows.append(r)
        final_ids.add(rid)
    for r in protocol_reranked:
        if len(final_rows) >= top_k:
            break
        rid = str(r.get("id") or "")
        if rid and rid in final_ids:
            continue
        final_rows.append(r)
        final_ids.add(rid)
    rows = final_rows[:top_k]

    reranked = bool(rows) and any(r.get("rerank_score") is not None for r in rows)
    canon_in_slate = sum(1 for r in rows if str(r.get("provider_kind") or "").startswith("canon_"))
    _log.info(
        "trade_panel.retrieve.rerank candidates=%d returned=%d reranked=%s "
        "canon_leg=%d canon_in_slate=%d canon_quota=%d",
        pre_rerank_count,
        len(rows),
        reranked,
        len(canon_rows),
        canon_in_slate,
        canon_quota,
    )

    # Issue #12 — exit log. hit_count + top_score disambiguate "Atlas returned
    # nothing" (likely filter-shape / ingest-tag drift) from "Atlas returned
    # rows but the post-$match on protocol filtered them out". The mongo_filter
    # echo lets the founder grep prod logs and replay the exact pipeline shape
    # against Atlas Compass.
    top_score = rows[0]["score"] if rows else 0.0
    _log.info(
        "trade_panel.retrieve.exit protocol=%s vertical=%s hit_count=%d "
        "top_score=%.4f mongo_filter=vertical=%s,protocol=%s",
        proto_norm,
        vertical,
        len(rows),
        top_score,
        vertical,
        proto_norm,
    )
    return rows


# Strategist closing-line: "Strategic intent: open small long, normal stop,
# weeks horizon — falsifier: ...". v1 best-effort regex over the free-form
# sentence. When the panel adopts the structured Phase 9 prompt addendum
# (entry_window/exit_horizon/direction/size_band) we'll prefer those keys
# directly on the parsed_verdict.
_STRATEGIST_DIRECTION_RE = re.compile(r"\b(long|short|neutral)\b", re.IGNORECASE)
_STRATEGIST_HORIZON_RE = re.compile(r"\b(intraday|days|weeks|months|\d+\s*[dwhm])\b", re.IGNORECASE)
_STRATEGIST_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def _strategist_intent_from_turn(turn: TradePanelTurn | None, protocol: str) -> dict[str, Any]:
    """Best-effort extraction of a backtestable intent from the strategist turn.

    Pulls direction (long/short/neutral), a horizon hint, and an optional
    size band out of the closing line. Returns a dict shaped for
    :func:`backtest_intent`. Always populates ``protocol`` so the caller
    has a routable key even when the rest is thin.
    """
    intent: dict[str, Any] = {"protocol": protocol.strip().lower()}
    if turn is None:
        return intent
    line = (turn.parsed_verdict or {}).get("strategic_intent") or ""
    if not line:
        return intent
    if dm := _STRATEGIST_DIRECTION_RE.search(line):
        intent["direction"] = dm.group(1).lower()
    if hm := _STRATEGIST_HORIZON_RE.search(line):
        token = hm.group(1).lower()
        # Map qualitative tokens to representative day counts.
        mapped = {
            "intraday": "1d",
            "days": "3d",
            "weeks": "14d",
            "months": "60d",
        }.get(token, token)
        intent["exit_horizon"] = mapped
    if sm := _STRATEGIST_SIZE_RE.search(line):
        with contextlib.suppress(ValueError):
            intent["size_pct"] = float(sm.group(1))
    return intent


_CITATION_SNIPPET_LIMIT: int = 240


def _coerce_provider_kind(raw: Any) -> ProviderKind:
    """Whitelist a chunk's provider_kind to the canonical Literal.

    Pattern A: anything not in PROVIDER_KINDS falls back to ``"web"`` so
    we don't leak adapter-internal tags (e.g. ``"bazaar:dataset"``) onto
    the wire. The ingest path is responsible for translating those at
    write time; this is the read-side defensive backstop.
    """
    if isinstance(raw, str) and raw in PROVIDER_KINDS:
        return cast(ProviderKind, raw)
    return "web"


def _coerce_freshness_tier(raw: Any) -> FreshnessTier:
    if isinstance(raw, str) and raw in FRESHNESS_TIER_VALUES:
        return raw
    return "static"


def build_citations_from_chunks(chunks: list[dict[str, Any]]) -> list[Citation]:
    """Project retrieved chunks into the wire-shape :class:`Citation` list.

    Issue #15. The 1-indexed ``id`` matches the inline ``[N]`` markers
    that ``_format_chunks`` injects into the opening prompt — that's the
    contract callers rely on to link prose to the cite array.

    URL fallback: when ``source_url`` is empty (e.g. live-only chunks
    with no canonical URL), we synthesize ``gecko://chunk/<sha256[:16]>``
    keyed off ``chunk_id``. This keeps the wire field non-empty and
    deterministic without inventing a fake http URL.
    """
    out: list[Citation] = []
    for idx, chunk in enumerate(chunks, start=1):
        chunk_id = str(chunk.get("id") or "")
        url = str(chunk.get("source_url") or "").strip()
        if not url:
            digest = hashlib.sha256(chunk_id.encode("utf-8")).hexdigest()[:16]
            url = f"gecko://chunk/{digest}"
        snippet = (chunk.get("text") or chunk.get("content") or "").strip()
        if len(snippet) > _CITATION_SNIPPET_LIMIT:
            snippet = snippet[:_CITATION_SNIPPET_LIMIT]
        out.append(
            Citation(
                id=idx,
                source=str(chunk.get("source") or chunk.get("provider_kind") or "unknown"),
                url=url,
                chunk_id=chunk_id,
                provider_kind=_coerce_provider_kind(chunk.get("provider_kind")),
                freshness_tier=_coerce_freshness_tier(chunk.get("freshness_tier")),
                snippet=snippet,
            )
        )
    return out


async def run_trade_panel_with_retrieval(
    idea: str,
    protocol: str,
    *,
    vertical: str = "dex",
    tier: str = "basic",
    top_k: int = _DEFAULT_TRADE_TOP_K,
    llm_config: dict[str, Any] | None = None,
    agent_factory: AgentFactory | None = None,
    enable_backtest: bool = False,
    history_source: Any | None = None,
) -> TradePanelVerdict:
    """Convenience wrapper — fetch corpus chunks, then run the 7-agent panel.

    Phase 8b's public entry point for the MCP tool + REST endpoint. The panel
    itself does NOT touch the vector store (that contract is locked by Phase
    8a). This wrapper does the retrieval up front and forwards into
    :func:`run_trade_panel`.

    Phase 9 addendum: when ``enable_backtest=True``, the strategist turn's
    intent is extracted and replayed against historical price data via
    :func:`backtest_intent`. The resulting :class:`BacktestReport` is
    attached to the returned verdict. Default False keeps existing callers
    on the Phase 8 contract.
    """
    chunks = await retrieve_trade_corpus_chunks(
        idea=idea, protocol=protocol, vertical=vertical, top_k=top_k
    )

    # Issue #12 — panel kickoff log. Truthy chunks here but empty
    # `citations` on the response would point at hypothesis 3 (prompt-drop):
    # retrieval landed rows but the panel's _format_chunks / opening prompt
    # isn't injecting them. chunk_ids are bounded to 15 by _DEFAULT_TRADE_TOP_K
    # so this stays cheap.
    chunk_ids = [c.get("id", "") for c in chunks]
    _log.info(
        "trade_panel.kickoff protocol=%s vertical=%s tier=%s "
        "chunks_passed_to_panel=%d chunk_ids=%s",
        protocol.strip().lower(),
        vertical,
        tier,
        len(chunks),
        chunk_ids,
    )

    verdict = await run_trade_panel(
        idea=idea,
        protocol=protocol,
        retrieved_chunks=chunks,
        tier=tier,
        llm_config=llm_config,
        agent_factory=agent_factory,
    )

    # Issue #15: attach the structured citation list sourced from the same
    # chunks the panel saw. The 1-indexed ids match the inline [N] markers
    # the personas cite in their turns, so consumers can render cite chips
    # without regex-extracting from prose.
    citations = build_citations_from_chunks(chunks)
    if citations:
        verdict = verdict.model_copy(update={"citations": citations})

    if not enable_backtest:
        return verdict

    # Lazy import keeps the backtest sub-package off the trade_panel hot path
    # when callers leave the flag at its default.
    from gecko_core.orchestration.trade_panel.backtest import (
        backtest_intent as _backtest_intent,
    )

    # Phase 9.5: default history source flipped from Pyth to CoinGecko.
    # Pyth Hermes does not expose OHLCV; CoinGecko's free `/coins/{id}/ohlc`
    # does. Callers that explicitly pass `history_source=PythHermesHistorySource()`
    # still get the cache-only path — only the implicit default changed.
    from gecko_core.orchestration.trade_panel.backtest.history_source import (
        CoinGeckoOhlcHistorySource,
    )

    strategist_turn = next((t for t in verdict.turns if t.agent == STRATEGIST), None)
    intent_dict = _strategist_intent_from_turn(strategist_turn, protocol)
    source = history_source if history_source is not None else CoinGeckoOhlcHistorySource()
    try:
        report = await _backtest_intent(intent_dict, source)
    except Exception as exc:  # pragma: no cover - defensive; backtest never raises
        _log.warning("trade_panel.backtest.error err=%s", exc)
        return verdict
    return verdict.model_copy(update={"backtest": report})
