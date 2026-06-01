#!/usr/bin/env python3
"""Sprint 28 (S28-AI-2) — News-row sentiment classifier worker.

Reads `market_news` rows that are missing `classification.bias_score`
and fills the field via a single LLM call per row. Idempotent — skips
rows that already have a `classification` block.

Runs as a one-shot batch (designed to be cron'd every ~15 min). Never
blocks the bot's hot path; the market_researcher voice degrades to
abstain on unclassified rows, so a delay just means the voice abstains
slightly longer.

Schema field filled (already reserved in `market_news` per
`docs/methodology/market-news-collection.md` §1):

    classification: {
        bias_score: float in [-1.0, +1.0],   # -1 = strong bearish, +1 = strong bullish
        regime_impact: "bullish" | "bearish" | "neutral" | "ambiguous",
        confidence: float in [0.0, 1.0],     # model's self-reported confidence
        rationale: str,                       # one-sentence why
        classifier_model: str,                # the model id used
        classified_at: ISO-8601 UTC timestamp
    }

Per `feedback_openrouter_not_openai_for_new_llm`: routes through
OpenRouter. Default model `openai/gpt-4o-mini`. Override via
`GECKO_NEWS_CLASSIFIER_MODEL`. No new dependencies.

Usage:
    python3 scripts/data/classify_news_rows.py
    python3 scripts/data/classify_news_rows.py --limit 50 --dry-run

Exit codes:
    0 — success or no unclassified rows
    1 — Mongo unavailable / OpenRouter unconfigured (logged)
    2 — partial: some rows classified, some failed (count printed)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# Make contest_bot/ importable when run from the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTEST_BOT = _REPO_ROOT / "contest_bot"
if str(_CONTEST_BOT) not in sys.path:
    sys.path.insert(0, str(_CONTEST_BOT))

logger = logging.getLogger("classify_news_rows")

DEFAULT_MODEL = "openai/gpt-4o-mini"


_SYSTEM_PROMPT = """\
You are a financial-news sentiment classifier for a Solana trading bot.

For each news row you receive, return a STRICT JSON object with these
fields:

  bias_score      : float in [-1.0, +1.0]
                    -1.0 = strong bearish for the symbol's price
                       0 = neutral / no directional read
                    +1.0 = strong bullish for the symbol's price
  regime_impact   : one of "bullish" / "bearish" / "neutral" / "ambiguous"
  confidence      : float in [0.0, 1.0] — your confidence in the call
  rationale       : ONE sentence, ≤ 140 chars

Calibration anchors (for the bot's traceability — actual score is
continuous, not snapped to these):
  +0.7 to +1.0 : major partnership, listing, integration, on-chain TVL win
  +0.3 to +0.7 : positive product update, fundamentals improvement
  -0.3 to +0.3 : maintenance, generic market commentary, unclear impact
  -0.7 to -0.3 : negative product update, regulatory pressure, FUD
  -1.0 to -0.7 : exploit, depeg, delisting, criminal-grade event

Bias to NEUTRAL on ambiguous headlines. The bot uses your score as
direct input to a deterministic voice — do NOT inflate bias scores
to seem decisive.

Return ONLY the JSON object. No prose, no markdown."""


def _user_prompt(symbol: str, headline: str, body: str) -> str:
    """Build the per-row user message. Cap body to keep tokens predictable."""
    body_excerpt = (body or "")[:1200]
    return (
        f"Symbol: {symbol}\n"
        f"Headline: {headline}\n"
        f"Body: {body_excerpt}\n"
    )


def _parse_response(raw: str) -> dict[str, Any]:
    """Extract the JSON dict from the model's response.

    The model is instructed to return strict JSON. If it adds prose,
    we try a best-effort extraction. Returns the parsed dict or raises
    ValueError so the caller can skip-and-continue.
    """
    raw = (raw or "").strip()
    # Try direct parse first
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Try to find a {...} substring
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"could not parse JSON from response: {raw[:200]}")


def _normalize_classification(d: dict[str, Any], model_id: str) -> dict[str, Any]:
    """Coerce + clamp the model's response into the schema shape.

    Defensive — model may return floats as strings, out-of-range values,
    missing fields. We clamp + default rather than raising.
    """
    try:
        bias = float(d.get("bias_score", 0.0))
    except (TypeError, ValueError):
        bias = 0.0
    bias = max(-1.0, min(1.0, bias))
    try:
        conf = float(d.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    conf = max(0.0, min(1.0, conf))
    regime = str(d.get("regime_impact", "neutral")).lower().strip()
    if regime not in ("bullish", "bearish", "neutral", "ambiguous"):
        regime = "neutral"
    rationale = str(d.get("rationale", "")).strip()[:140]
    return {
        "bias_score": bias,
        "regime_impact": regime,
        "confidence": conf,
        "rationale": rationale,
        "classifier_model": model_id,
        "classified_at": datetime.now(UTC).isoformat(),
    }


def classify_row(client: Any, row: dict[str, Any], model: str) -> dict[str, Any] | None:
    """Classify one row. Returns the classification dict or None on failure."""
    # Pick a representative symbol (rows can have multiple tickers).
    tickers = row.get("tickers") or []
    symbol = tickers[0] if tickers else "?"
    headline = row.get("headline") or ""
    body = row.get("body") or ""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": _user_prompt(symbol, headline, body)},
    ]
    try:
        resp = client.chat(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=200,
        )
    except Exception as exc:
        logger.warning("classify_row: OpenRouter call failed: %s", exc)
        return None
    try:
        parsed = _parse_response(resp.content)
    except ValueError as exc:
        logger.warning("classify_row: parse failed: %s", exc)
        return None
    return _normalize_classification(parsed, model_id=model)


def _connect_mongo():
    """Return (collection, db) or (None, None) on failure."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        logger.error("MONGODB_URI not set")
        return None, None
    try:
        from pymongo import MongoClient

        db = MongoClient(uri, serverSelectionTimeoutMS=4000)[
            os.environ.get("MONGODB_DB", "gecko_cache")
        ]
        coll = db[os.environ.get("MONGODB_NEWS_COLL", "market_news")]
        # Light ping
        db.command("ping")
        return coll, db
    except Exception as exc:
        logger.error("Mongo unavailable: %s", exc)
        return None, None


def run(limit: int = 100, dry_run: bool = False) -> int:
    """Find unclassified rows + classify + patch. Returns exit code."""
    coll, _db = _connect_mongo()
    if coll is None:
        return 1
    model = os.environ.get("GECKO_NEWS_CLASSIFIER_MODEL", DEFAULT_MODEL)

    # Find rows missing classification.bias_score (the load-bearing field).
    # `$exists: false` matches both "no classification field" and "field is
    # null" via $or for robustness.
    flt = {
        "$or": [
            {"classification": {"$exists": False}},
            {"classification": None},
            {"classification.bias_score": {"$exists": False}},
            {"classification.bias_score": None},
        ]
    }
    try:
        cursor = coll.find(flt).limit(int(limit))
        rows = list(cursor)
    except Exception as exc:
        logger.error("Mongo find failed: %s", exc)
        return 1

    if not rows:
        print("No unclassified rows.")
        return 0

    print(f"Found {len(rows)} unclassified rows. Model: {model}")
    if dry_run:
        for r in rows[:5]:
            sym = (r.get("tickers") or ["?"])[0]
            print(f"  [{sym}] {r.get('headline', '')[:80]}")
        print(f"  ... + {max(0, len(rows) - 5)} more")
        print("Dry-run; no LLM calls, no patches.")
        return 0

    # Lazy import — only construct the LLM client when actually classifying.
    try:
        from llm_client import OpenRouterClient

        client = OpenRouterClient()
    except Exception as exc:
        logger.error("OpenRouter client init failed: %s", exc)
        return 1

    ok = 0
    failed = 0
    for r in rows:
        classification = classify_row(client, r, model=model)
        if classification is None:
            failed += 1
            continue
        try:
            coll.update_one(
                {"_id": r["_id"]},
                {"$set": {"classification": classification}},
            )
            ok += 1
        except Exception as exc:
            logger.warning("Mongo update_one failed for %s: %s", r.get("_id"), exc)
            failed += 1

    print(f"Done. ok={ok} failed={failed} of {len(rows)} total.")
    return 0 if failed == 0 else 2


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--limit", type=int, default=100, help="max rows per run")
    parser.add_argument("--dry-run", action="store_true", help="don't call LLM or patch")
    args = parser.parse_args()
    return run(limit=args.limit, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
