"""Embedding-NN idea classifier.

Multi-label top-2 cosine similarity over a hand-labeled seed set. Returns
the set of categories whose nearest seed exceeds `threshold`. An empty set
means "unknown" — the orchestrator should fall back to the safe baseline
(Tavily + HN + Reddit + flywheel).

The classifier is deliberately *cheap*: one embedding call (~1k tokens at
$0.02/M = ~$0.00002) and a 50xN cosine in numpy. We don't need ML-grade
accuracy — the dispatcher swallows non-applicable sources anyway.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from openai import AsyncOpenAI

from gecko_core.ingestion.embedder import embed

CATEGORIES: tuple[str, ...] = (
    "crypto",
    "defi",
    "devtools",
    "saas",
    "regulated",
    "hackathon-team",
)

_SEEDS_PATH = Path(__file__).parent / "seeds.json"
_EMBEDDINGS_PATH = Path(__file__).parent / "seeds.npz"

# Lazy-loaded module-level cache: (categories, unit-normalized embeddings)
_seeds_cache: tuple[list[str], np.ndarray] | None = None


def _load_seeds() -> tuple[list[str], np.ndarray]:
    global _seeds_cache
    if _seeds_cache is not None:
        return _seeds_cache
    if not _EMBEDDINGS_PATH.exists():
        raise RuntimeError(
            f"Seeds embeddings not built at {_EMBEDDINGS_PATH}. "
            "Run: python -m gecko_core.classify.build_seeds"
        )
    data = np.load(_EMBEDDINGS_PATH, allow_pickle=False)
    categories = [str(c) for c in data["categories"]]
    embeddings = data["embeddings"]
    _seeds_cache = (categories, embeddings)
    return _seeds_cache


async def classify_idea(
    idea: str,
    *,
    threshold: float = 0.40,
    client: AsyncOpenAI | None = None,
) -> set[str]:
    """Classify `idea` into 0-2 categories from `CATEGORIES`.

    Multi-label: returns up to top-2 categories whose max cosine similarity
    to any seed in that category exceeds `threshold`. Empty set if nothing
    clears the bar — caller should treat as "unknown" and run the safe
    baseline source set.

    `threshold` default (0.40) was tuned on a held-out 20-idea set against
    `text-embedding-3-small`. That model produces relatively low absolute
    cosines (typical in-domain top-1 lands 0.40-0.65; clearly off-domain
    ideas sit at 0.30-0.38). The original 0.62 spec value was calibrated
    for `text-embedding-3-large` and would reject most in-domain ideas
    here. We pay for that with a slim margin against unknowns — the
    dispatcher's per-source `applies_to` is the second line of defense.
    """
    seed_cats, seed_embs = _load_seeds()
    idea_vecs, _tokens = await embed([idea], client=client)
    idea_emb = np.array(idea_vecs[0], dtype=np.float32)
    idea_norm = float(np.linalg.norm(idea_emb))
    if idea_norm < 1e-12:
        return set()
    idea_unit = idea_emb / idea_norm

    # seed_embs are unit-normalized at build time; matmul gives cosine.
    sims = seed_embs @ idea_unit

    max_per_cat: dict[str, float] = {}
    for cat, sim in zip(seed_cats, sims, strict=True):
        s = float(sim)
        if s > max_per_cat.get(cat, -1.0):
            max_per_cat[cat] = s

    ranked = sorted(max_per_cat.items(), key=lambda kv: kv[1], reverse=True)
    return {cat for cat, sim in ranked[:2] if sim >= threshold}


__all__ = ["CATEGORIES", "classify_idea"]
