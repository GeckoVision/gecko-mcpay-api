"""Build the seed embeddings cache.

Reads `seeds.json`, embeds each idea via the project's `embed()` helper,
unit-normalizes the vectors, and writes `seeds.npz` with parallel
`categories` (list[str]) and `embeddings` (float32 NxD) arrays.

Run once on seed-set updates; commit the resulting `seeds.npz` so
production containers don't have to call OpenAI on every cold start.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import numpy as np

from gecko_core.classify import _EMBEDDINGS_PATH, _SEEDS_PATH, CATEGORIES
from gecko_core.ingestion.embedder import embed


async def _build() -> None:
    raw = json.loads(Path(_SEEDS_PATH).read_text())
    if not isinstance(raw, list) or not raw:
        raise RuntimeError(f"{_SEEDS_PATH} is empty or malformed")

    ideas: list[str] = []
    cats: list[str] = []
    for row in raw:
        idea = row["idea"]
        cat = row["category"]
        if cat not in CATEGORIES:
            raise RuntimeError(f"Unknown category {cat!r} in seed: {idea!r}")
        ideas.append(idea)
        cats.append(cat)

    print(f"Embedding {len(ideas)} seeds...")
    vectors, tokens = await embed(ideas)
    print(f"  used {tokens} tokens")

    arr = np.array(vectors, dtype=np.float32)
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms < 1e-12, 1.0, norms)
    unit = arr / norms

    np.savez(_EMBEDDINGS_PATH, categories=np.array(cats), embeddings=unit)
    print(f"Wrote {_EMBEDDINGS_PATH} ({unit.shape[0]} x {unit.shape[1]})")


def main() -> None:
    asyncio.run(_build())


if __name__ == "__main__":
    main()
