"""Per-model pricing table + token/cost estimators (S3-05).

Prices are USD per 1M tokens, snapshotted 2026-04-29. Update by editing
``MODEL_PRICING`` — no other code change needed (the matrix references
models by string, prices are looked up here at cost time).

Token estimation uses tiktoken when available; falls back to the
characters/4 heuristic for unsupported models (e.g. Anthropic strings).
"""

from __future__ import annotations

from typing import Final, TypedDict

# Sentinel for unknown-model lookup. We never silently assume zero cost —
# an unpriced model raises so the matrix stays in sync with the price book.


class _ModelPrice(TypedDict):
    """USD per 1M tokens, separate input/output rails."""

    input_per_m: float
    output_per_m: float


# Snapshot 2026-04-29. Sources: OpenAI public pricing page, Anthropic
# public pricing page. Anthropic Sonnet 4.6 / Opus 4.7 numbers reflect
# the post-2026-Q1 price card.
MODEL_PRICING: Final[dict[str, _ModelPrice]] = {
    # OpenAI
    "gpt-4o-mini": {"input_per_m": 0.15, "output_per_m": 0.60},
    "gpt-4o": {"input_per_m": 2.50, "output_per_m": 10.00},
    # Anthropic
    "claude-sonnet-4-6": {"input_per_m": 3.00, "output_per_m": 15.00},
    "claude-opus-4-7": {"input_per_m": 15.00, "output_per_m": 75.00},
}


def price_for(model: str) -> _ModelPrice:
    """Return the price record for ``model`` or raise ``KeyError``."""
    if model not in MODEL_PRICING:
        raise KeyError(
            f"no price entry for model {model!r}; add it to MODEL_PRICING in "
            "gecko_core.routing.costs"
        )
    return MODEL_PRICING[model]


def estimate_tokens(text: str) -> int:
    """Estimate token count for ``text``.

    Uses tiktoken's cl100k_base encoder (close enough for OpenAI + a safe
    upper-bound for Anthropic). Falls back to len(text) // 4 if tiktoken
    misbehaves so this function never raises.
    """
    if not text:
        return 0
    try:
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except Exception:
        # Heuristic: ~4 chars/token for English. Slightly conservative
        # (overestimates for code, underestimates for CJK).
        return max(1, len(text) // 4)


def estimate_cost_usd(model: str, *, tokens_in: int, tokens_out: int) -> float:
    """USD cost for ``(tokens_in, tokens_out)`` on ``model``.

    Pure arithmetic — used both for pre-call budget gating (with estimated
    output) and post-call surfacing (with real usage from the API response).
    """
    p = price_for(model)
    return (tokens_in / 1_000_000.0) * p["input_per_m"] + (tokens_out / 1_000_000.0) * p[
        "output_per_m"
    ]


__all__ = [
    "MODEL_PRICING",
    "estimate_cost_usd",
    "estimate_tokens",
    "price_for",
]
