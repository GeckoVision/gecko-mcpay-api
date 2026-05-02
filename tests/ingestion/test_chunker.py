"""Chunker invariants: cap, overlap, determinism."""

from __future__ import annotations

import tiktoken
from gecko_core.ingestion.chunker import chunk

_enc = tiktoken.get_encoding("cl100k_base")


def _ntoks(s: str) -> int:
    return len(_enc.encode(s))


def test_empty_input_returns_empty_list() -> None:
    assert chunk("") == []
    assert chunk("   \n\t  ") == []


def test_short_text_one_chunk() -> None:
    text = "the quick brown fox jumps over the lazy dog."
    out = chunk(text, size=512, overlap=50)
    assert len(out) == 1
    assert _ntoks(out[0]) <= 512


def test_chunks_under_size_cap() -> None:
    # ~3000 tokens of repeated content
    text = ("Solana is a high-performance blockchain. " * 400).strip()
    out = chunk(text, size=512, overlap=50)
    assert len(out) > 1
    for c in out:
        assert _ntoks(c) <= 512


def test_overlap_is_present_between_consecutive_chunks() -> None:
    text = (f"paragraph {i} about builders and ideas. " for i in range(500))
    big = " ".join(text)
    out = chunk(big, size=200, overlap=40)
    assert len(out) >= 2
    # Last 40 tokens of chunk N should match first 40 tokens of chunk N+1.
    a_tail = _enc.encode(out[0])[-40:]
    b_head = _enc.encode(out[1])[:40]
    assert a_tail == b_head


def test_deterministic() -> None:
    text = "Builder bootstrap ingests sources. " * 200
    assert chunk(text) == chunk(text)


# ---------------------------------------------------------------------------
# S16-INGEST-05 — Postgres 22P05 (NUL byte / invalid Unicode escape)
# defense. Sanitization happens at the chunk-creation boundary so the
# upsert never sees a byte sequence Postgres rejects.
# ---------------------------------------------------------------------------


def test_nul_byte_is_stripped_from_chunk_output() -> None:
    """A scraped document with embedded NUL bytes must not surface the
    bytes in any output chunk; otherwise the downstream upsert hits
    SQLSTATE 22P05 and the whole batch dies."""
    text = "valid prefix\x00\x00 valid suffix \x01\x02 more text."
    out = chunk(text, size=512, overlap=50)
    assert len(out) == 1
    for piece in out:
        assert "\x00" not in piece
        # All other C0-forbidden chars are stripped too. \t \n \r are
        # preserved (they are valid in Postgres TEXT).
        for c in range(0x00, 0x20):
            if c in {0x09, 0x0A, 0x0D}:
                continue
            assert chr(c) not in piece


def test_only_nul_bytes_yields_no_chunks() -> None:
    """Pure-garbage input → empty list, same as empty/whitespace."""
    assert chunk("\x00\x00\x00") == []


def test_clean_text_passes_through_unchanged() -> None:
    """Fast path: no NUL / no forbidden C0 means we don't pay for the
    replacement loop. Sanity-check that clean inputs still chunk
    identically to pre-S16-INGEST-05."""
    text = "a perfectly normal sentence with\ttabs and\nnewlines."
    out = chunk(text)
    assert out == [text]


def test_sanitization_logs_warning(caplog: object) -> None:
    """One warning per call (not per chunk) so log volume stays bounded
    even on aggressive pages. The `bytes_removed` extra field is what
    the operator reads to gauge severity."""
    import logging as _logging

    cap = caplog  # type: ignore[assignment]
    # caplog is a pytest LogCaptureFixture; the `object` annotation is
    # only there so this module doesn't pull pytest into its type graph.
    cap.set_level(_logging.WARNING, logger="gecko_core.ingestion.chunker")  # type: ignore[attr-defined]
    chunk("hello\x00world\x00again")
    records = [r for r in cap.records if r.name == "gecko_core.ingestion.chunker"]  # type: ignore[attr-defined]
    assert any(r.message == "chunker.text_sanitized" for r in records)
    sanitized = next(r for r in records if r.message == "chunker.text_sanitized")
    assert getattr(sanitized, "bytes_removed", 0) == 2
    assert getattr(sanitized, "error_kind", None) == "text_sanitized"
