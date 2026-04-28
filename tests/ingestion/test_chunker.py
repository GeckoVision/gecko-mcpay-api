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
