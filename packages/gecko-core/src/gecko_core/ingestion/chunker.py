"""Token-aware chunker. Hard cap: 512 tokens/chunk, 50-token overlap.

Uses tiktoken cl100k_base (the encoding for both gpt-4o and the
text-embedding-3 family) so embedding inputs stay deterministic.
"""

from __future__ import annotations

import logging

import tiktoken

logger = logging.getLogger(__name__)

DEFAULT_CHUNK_SIZE = 512
DEFAULT_CHUNK_OVERLAP = 50

_enc = tiktoken.get_encoding("cl100k_base")

# S16-INGEST-05 — Postgres rejects strings containing NUL bytes (\x00) on
# any TEXT/VARCHAR write with SQLSTATE 22P05 ("unsupported Unicode
# escape sequence"). Smoke runs on 2026-05-01 lost three full chunk
# batches because a single scraped HTML page from each source contained
# embedded NULs (typically null-padded UTF-16 garbage from a misencoded
# response, or sentinel bytes from a failed PDF extract). The whole
# upsert fails because we batch — one bad byte poisons hundreds of rows.
# Strip these (plus the rest of C0 except the harmless tab/newline/CR)
# at chunk-creation time so downstream consumers (cache write, chunks
# insert) never see them.
_C0_FORBIDDEN: tuple[str, ...] = tuple(
    chr(c) for c in range(0x00, 0x20) if c not in {0x09, 0x0A, 0x0D}
)


def _sanitize_for_postgres(text: str) -> tuple[str, int]:
    """Strip NUL bytes + other invalid C0 control chars Postgres rejects.

    Returns (cleaned_text, num_bytes_removed). The byte count is what we
    log when sanitization fires — a non-zero value means the source had
    at least one byte that would have tripped 22P05 on insert. We keep
    `\\t \\n \\r` because those are valid in TEXT and chunkers may rely
    on them; everything else in U+0000..U+001F is dropped.
    """
    if not text:
        return text, 0
    # Fast path: no NUL byte and no other C0-forbidden char → return as-is.
    # `"\x00" in text` is the dominant case in practice; the broader
    # check is cheap and only runs when the fast path missed.
    if "\x00" not in text and not any(c in text for c in _C0_FORBIDDEN):
        return text, 0
    cleaned = text
    for ch in _C0_FORBIDDEN:
        cleaned = cleaned.replace(ch, "")
    return cleaned, len(text) - len(cleaned)


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

    # S16-INGEST-05 — sanitize at the chunk-creation boundary. Done
    # BEFORE tokenization because tiktoken happily round-trips NULs
    # (cl100k_base maps \x00 to a real token), so without this step the
    # bad byte would make it all the way to the upsert. We log a single
    # warning per call (not per chunk) to keep volume bounded; the
    # `bytes_removed` count tells the operator how aggressive the
    # input was.
    sanitized, bytes_removed = _sanitize_for_postgres(text)
    if bytes_removed > 0:
        logger.warning(
            "chunker.text_sanitized",
            extra={
                "bytes_removed": bytes_removed,
                "input_chars": len(text),
                "error_kind": "text_sanitized",
            },
        )

    cleaned = sanitized.strip()
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
