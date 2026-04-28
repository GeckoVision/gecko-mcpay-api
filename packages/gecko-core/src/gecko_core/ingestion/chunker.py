"""Token-aware chunker. Hard cap: 512 tokens/chunk, 50-token overlap.

Uses tiktoken cl100k_base (the encoding for both gpt-4o and the
text-embedding-3 family) so embedding inputs stay deterministic.
"""

from __future__ import annotations

import tiktoken

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50

_enc = tiktoken.get_encoding("cl100k_base")


def chunk(
    text: str,
    size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> list[str]:
    """Split text into <=`size`-token chunks with `overlap` token overlap.

    Returns an empty list on empty/whitespace input. Deterministic.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    if overlap < 0 or overlap >= size:
        raise ValueError("overlap must be in [0, size)")

    cleaned = text.strip()
    if not cleaned:
        return []

    tokens = _enc.encode(cleaned)
    if not tokens:
        return []

    chunks: list[str] = []
    start = 0
    n = len(tokens)
    step = size - overlap
    while start < n:
        end = min(start + size, n)
        piece = _enc.decode(tokens[start:end])
        chunks.append(piece)
        if end == n:
            break
        start += step
    return chunks


__all__ = ["DEFAULT_CHUNK_OVERLAP", "DEFAULT_CHUNK_SIZE", "chunk"]
