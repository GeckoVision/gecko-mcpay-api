"""Query-time category + vertical classifier (S20-C-CLASSIFIER-01).

The front door of the categorized retrieval pipeline. Every incoming
user query is routed to one or more ``(vertical, category)`` cells before
vector search is dispatched against the Mongo chunk store. Per the S20
strategy doc, the classifier targets:

- Cost ≤ $0.001 per call (gpt-4o-mini, ~150 in / 50 out tokens).
- Top-1 vertical accuracy ≥ 0.75, top-3 category recall ≥ 0.92.
- Honest ``unknown`` signal when vertical confidence < 0.6 — surfacing
  candidate verticals to the user is the *caller*'s responsibility, not
  the classifier's. The classifier never silently guesses.

This module is the QUERY-TIME classifier. The CHUNK-LEVEL classifier
(A2 ticket) lives at ``gecko_core.knowledge.classifier`` — a different
surface with different latency/cost budgets. Don't merge them.

Per Pattern A in CLAUDE.md, ``Category`` and ``Vertical`` are imported
from the canonical taxonomy module. We never redeclare the literal
values here.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI
from pydantic import BaseModel, Field, ValidationError

from gecko_core.ingestion.settings import get_ingestion_settings
from gecko_core.knowledge.taxonomy import CATEGORIES, VERTICALS, Category, Vertical

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module flags / budgets
# ---------------------------------------------------------------------------

_DEBUG_BUDGET_ASSERT: bool = False
"""When True, ``classify_query`` asserts (tokens_in + tokens_out) < 1000.

Tests flip this to enforce the sub-cent cost target deterministically.
Production leaves it False so a single noisy call never throws."""

_MODEL: str = "gpt-4o-mini"
_MAX_OUTPUT_TOKENS: int = 300
_MAX_INPUT_CHARS: int = 6000  # rough proxy for ~1.5K tokens (4 chars/token).
_VERTICAL_CONFIDENCE_THRESHOLD: float = 0.6


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


class QueryClassification(BaseModel):
    """Structured prediction from ``classify_query``.

    ``categories`` is ordered top-first and contains 1-3 items drawn from
    the canonical ``CATEGORIES`` tuple. ``vertical`` is exactly one
    member of ``VERTICALS``; the literal value ``"unknown"`` is returned
    whenever ``vertical_confidence`` falls below the module threshold.
    """

    categories: list[Category] = Field(..., min_length=1, max_length=3)
    vertical: Vertical
    category_confidence: float = Field(..., ge=0.0, le=1.0)
    vertical_confidence: float = Field(..., ge=0.0, le=1.0)


class ClassifierParseError(RuntimeError):
    """Raised when the LLM returns JSON that fails pydantic validation.

    The raw model output is captured on the exception (``raw_output``)
    so logs/traces can diagnose schema drift without re-querying.
    """

    def __init__(self, message: str, *, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------


_FEW_SHOT = """Examples:
Query: "I want to build a neobank in São Paulo with PIX rails"
{"categories":["business_financial","technical_engineering"],"vertical":"neobank","category_confidence":0.9,"vertical_confidence":0.95}

Query: "What's the latest funding round for prediction markets?"
{"categories":["investment_signals","market_intelligence"],"vertical":"prediction_market","category_confidence":0.88,"vertical_confidence":0.82}

Query: "How do I evaluate a RAG pipeline?"
{"categories":["ai_ml","technical_engineering"],"vertical":"unknown","category_confidence":0.92,"vertical_confidence":0.2}
"""


def _build_prompt(query: str) -> str:
    cats = ", ".join(CATEGORIES)
    verts = ", ".join(VERTICALS)
    return (
        "You are a routing classifier for a categorized retrieval system. "
        "Classify the user query along TWO axes and return STRICT JSON.\n\n"
        f"Allowed categories (pick 1-3, top first): {cats}\n"
        f"Allowed verticals (pick exactly one; use 'unknown' if unsure): {verts}\n\n"
        f"{_FEW_SHOT}\n"
        "Return JSON with exactly these keys: categories (array of 1-3 strings), "
        "vertical (string), category_confidence (0-1 float), vertical_confidence (0-1 float). "
        "No prose, no markdown.\n\n"
        f'Query: "{query}"'
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def classify_query(
    query: str,
    *,
    client: AsyncOpenAI | None = None,
) -> QueryClassification:
    """Classify ``query`` into ``(categories, vertical)`` with confidences.

    Cheap by construction: ``gpt-4o-mini``, deterministic temperature,
    capped output. Truncates input above ``_MAX_INPUT_CHARS`` so a runaway
    paste never burns budget. Empty queries raise ``ValueError`` *before*
    any LLM call — no wasted spend.

    The vertical is forced to ``"unknown"`` when ``vertical_confidence``
    is below ``_VERTICAL_CONFIDENCE_THRESHOLD``. We do NOT guess; the
    caller is responsible for surfacing candidate verticals.
    """
    if not query or not query.strip():
        raise ValueError("query must be non-empty")

    if len(query) > _MAX_INPUT_CHARS:
        query = query[:_MAX_INPUT_CHARS]

    if client is None:
        settings = get_ingestion_settings()
        if settings.openai_api_key is None:
            raise ValueError("OPENAI_API_KEY must be set to call classify_query")
        client = AsyncOpenAI(api_key=settings.openai_api_key.get_secret_value())

    prompt = _build_prompt(query)
    completion: Any = await client.chat.completions.create(
        model=_MODEL,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        max_tokens=_MAX_OUTPUT_TOKENS,
        temperature=0.0,
    )

    raw_output = completion.choices[0].message.content or ""
    usage = getattr(completion, "usage", None)
    tokens_in = int(getattr(usage, "prompt_tokens", 0) or 0)
    tokens_out = int(getattr(usage, "completion_tokens", 0) or 0)

    if _DEBUG_BUDGET_ASSERT:
        assert tokens_in + tokens_out < 1000, (
            f"classify_query budget exceeded: in={tokens_in} out={tokens_out}"
        )

    try:
        payload = json.loads(raw_output)
        prediction = QueryClassification.model_validate(payload)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ClassifierParseError(
            f"classifier returned invalid JSON / shape: {exc}",
            raw_output=raw_output,
        ) from exc

    # Honest unknown — never silently guess a vertical.
    if prediction.vertical_confidence < _VERTICAL_CONFIDENCE_THRESHOLD:
        prediction = prediction.model_copy(update={"vertical": "unknown"})

    logger.info(
        "routing.classify",
        extra={
            "query_len": len(query),
            "categories": list(prediction.categories),
            "vertical": prediction.vertical,
            "category_confidence": prediction.category_confidence,
            "vertical_confidence": prediction.vertical_confidence,
            "tokens_in": tokens_in,
            "tokens_out": tokens_out,
        },
    )

    return prediction


__all__ = [
    "ClassifierParseError",
    "QueryClassification",
    "classify_query",
]
