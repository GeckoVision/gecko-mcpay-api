"""Per-model pricing + token/cost estimators (S3-05, S4-MATRIX-01).

The pricing table is now backed by the curated catalog (see
``gecko_core.routing.catalog``). The legacy ``MODEL_PRICING`` mapping survives
as a catalog-backed view so existing imports keep working, but new code should
prefer ``model_pricing_for(model_id)``.

Legacy entries (``gpt-4o-mini``, ``gpt-4o``, ``claude-sonnet-4-6``,
``claude-opus-4-7``) remain priced even though they're not in the new
catalog — these strings are still produced by the Sprint-3 ``MODELS_BY_ROUTER``
matrix and the routing matrix, and removing them would break unrelated tests.
Eventual cleanup belongs to a Sprint-5 catalog migration once those callers
have moved to catalog ids.
"""

from __future__ import annotations

from typing import Final

from typing_extensions import TypedDict  # py<3.12 + pydantic needs this variant

from gecko_core.routing.catalog import load_catalog


class _ModelPrice(TypedDict):
    """USD per 1M tokens, separate input/output rails."""

    input_per_m: float
    output_per_m: float


# Legacy hardcoded snapshot (2026-04-29). Kept to keep S3-vintage callers
# working while the catalog migration completes. DEPRECATED: edit the catalog
# JSON, not this dict.
_LEGACY_PRICING: Final[dict[str, _ModelPrice]] = {
    # OpenAI
    "gpt-4o-mini": {"input_per_m": 0.15, "output_per_m": 0.60},
    "gpt-4o": {"input_per_m": 2.50, "output_per_m": 10.00},
    # Anthropic — pre-Sprint-4 pricing card (note: legacy keys use dashes,
    # catalog ids use dots — both must work for backward compat).
    "claude-sonnet-4-6": {"input_per_m": 3.00, "output_per_m": 15.00},
    "claude-opus-4-7": {"input_per_m": 15.00, "output_per_m": 75.00},
}


def _strip_router_prefix(model: str) -> str:
    """Drop a leading ``provider/`` segment so OpenRouter-style names resolve.

    The catalog keys models by their full id (``openai/gpt-4o-mini``); the
    legacy table keys by the bare model name. We try both forms when looking
    up a price.
    """
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _build_view() -> dict[str, _ModelPrice]:
    """Compose legacy + catalog entries into a single read-only price view.

    Catalog entries are exposed under both their full id (e.g.
    ``anthropic/claude-opus-4.7``) and their bare suffix (``claude-opus-4.7``)
    so callers using either convention resolve correctly. Legacy entries
    take precedence on bare-name collisions to preserve existing test
    expectations.
    """
    out: dict[str, _ModelPrice] = {}
    for entry in load_catalog().values():
        price: _ModelPrice = {
            "input_per_m": float(entry.pricing.input),
            "output_per_m": float(entry.pricing.output),
        }
        out[entry.id] = price
        bare = _strip_router_prefix(entry.id)
        out.setdefault(bare, price)
    # Legacy wins on collision so callers expecting the pre-Sprint-4 numbers
    # (e.g. claude-opus-4-7 at $15/$75) keep getting them.
    out.update(_LEGACY_PRICING)
    return out


# Public read-only price view. Computed once at import time — the catalog
# loader is itself lru_cached so this stays cheap.
MODEL_PRICING: Final[dict[str, _ModelPrice]] = _build_view()


def price_for(model: str) -> _ModelPrice:
    """Return the price record for ``model`` or raise ``KeyError``.

    Tries the model string as-is first, then strips a leading ``provider/``
    segment so legacy callers passing ``openai/gpt-4o-mini`` still resolve.
    """
    if model in MODEL_PRICING:
        return MODEL_PRICING[model]
    bare = _strip_router_prefix(model)
    if bare in MODEL_PRICING:
        return MODEL_PRICING[bare]
    raise KeyError(
        f"no price entry for model {model!r}; add it to the catalog at "
        "gecko_core/routing/model_catalog.json"
    )


def model_pricing_for(model_id: str) -> tuple[float, float]:
    """Return ``(input_per_1m, output_per_1m)`` for ``model_id``.

    Catalog-backed alternative to ``price_for`` that returns a plain tuple —
    preferred for new code that doesn't need the TypedDict shape.
    """
    p = price_for(model_id)
    return p["input_per_m"], p["output_per_m"]


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
    "model_pricing_for",
    "price_for",
]
