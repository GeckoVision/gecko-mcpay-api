"""Unit tests for the Colosseum calibration corpus loader (S21-CALIBRATION-01)."""

from __future__ import annotations

import json
from pathlib import Path

from gecko_core.judges.colosseum import (
    COLOSSEUM_DATASET,
    WEB3_ACCELERATORS_DATASET,
    _build_chunks,
    _build_feedback_posts_chunks,
    _build_web3_accelerators_chunks,
    _read_feedback_posts_source_file,
    _read_source_file,
    _read_web3_accelerators_source_file,
    _slugify_program,
    calibration_corpus_id,
    render_calibration_block,
)


def test_build_chunks_counts_match_source() -> None:
    """The shipped dataset produces 34 profile + 8 feedback = 42 chunks."""
    src = _read_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_source_colosseum.json"
    )
    chunks = _build_chunks(src)
    profiles = [c for c in chunks if c.chunk_kind == "profile"]
    feedback = [c for c in chunks if c.chunk_kind == "feedback_post"]
    assert len(profiles) == 34
    assert len(feedback) == 8
    assert len(chunks) == 42


def test_build_chunks_metadata_present() -> None:
    """Every chunk carries the per-judge metadata the loader expects."""
    src = _read_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_source_colosseum.json"
    )
    chunks = _build_chunks(src)
    sample = chunks[0]
    assert sample.username
    assert sample.text
    # profile chunks carry no post_id; feedback rows carry one.
    feedback = [c for c in chunks if c.chunk_kind == "feedback_post"]
    assert all(c.post_id for c in feedback)


def test_calibration_corpus_id_shape() -> None:
    """Identifier has the documented `colosseum:N_judges:YYYY-MM-DD` shape."""
    rows = [
        {"username": "a", "chunk_kind": "profile"},
        {"username": "b", "chunk_kind": "profile"},
        {"username": "a", "chunk_kind": "feedback_post"},
    ]
    cid = calibration_corpus_id(rows, today="2026-05-03")
    assert cid == "colosseum:2_judges:2026-05-03"


def test_render_calibration_block_returns_empty_for_empty_rows() -> None:
    assert render_calibration_block([]) == ""


def test_render_calibration_block_includes_handles_and_text() -> None:
    rows = [
        {
            "chunk_kind": "profile",
            "username": "twentyOne2x",
            "name": "Billy",
            "region_superteam": "Global / US",
            "text": "Former Colosseum winner + DeFi/HFT background.",
        },
        {
            "chunk_kind": "feedback_post",
            "username": "milianstx",
            "post_date": "2026-05-02",
            "text": "Offered to review any pitch deck/blurb via DM",
        },
    ]
    block = render_calibration_block(rows)
    assert "@twentyOne2x" in block
    assert "Billy" in block
    assert "Former Colosseum winner" in block
    assert "@milianstx" in block
    assert "2026-05-02" in block


def test_dataset_constant_matches_documented_value() -> None:
    assert COLOSSEUM_DATASET == "colosseum_judges"


def test_feedback_posts_chunks_counts_match_source() -> None:
    """The feedback-posts file produces the documented chunk distribution.

    Expected: 2 solicitation + 7 feedback_interaction + 2 style_synthesis
    + 3 light_activity_note = 14 chunks total.
    """
    src = _read_feedback_posts_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_feedback_posts.json"
    )
    chunks = _build_feedback_posts_chunks(src)
    by_kind: dict[str, int] = {}
    for c in chunks:
        by_kind[c.chunk_kind] = by_kind.get(c.chunk_kind, 0) + 1
    assert by_kind.get("solicitation") == 2
    assert by_kind.get("feedback_interaction") == 7
    assert by_kind.get("style_synthesis") == 2
    assert by_kind.get("light_activity_note") == 3
    assert len(chunks) == 14


def test_feedback_posts_chunks_carry_dedup_ready_post_ids() -> None:
    """Synthetic post_ids ensure no None collisions in the dedup tuple."""
    src = _read_feedback_posts_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_feedback_posts.json"
    )
    chunks = _build_feedback_posts_chunks(src)
    assert all(c.post_id for c in chunks), "every feedback chunk needs a post_id"
    style_rows = [c for c in chunks if c.chunk_kind == "style_synthesis"]
    light_rows = [c for c in chunks if c.chunk_kind == "light_activity_note"]
    assert all(c.post_id == f"style_synthesis__{c.username}" for c in style_rows)
    assert all(c.post_id == f"light_activity__{c.username}" for c in light_rows)


def test_feedback_interaction_chunks_carry_target_and_style() -> None:
    src = _read_feedback_posts_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_feedback_posts.json"
    )
    chunks = _build_feedback_posts_chunks(src)
    interactions = [c for c in chunks if c.chunk_kind == "feedback_interaction"]
    assert interactions, "expected at least one feedback_interaction"
    assert all(c.target_project for c in interactions)
    assert all(c.style for c in interactions)


def test_web3_accelerators_dataset_constant() -> None:
    assert WEB3_ACCELERATORS_DATASET == "web3_accelerators"


def test_slugify_program_stable() -> None:
    assert (
        _slugify_program("Colosseum Arena / Frontier (Solana)") == "colosseum-arena-frontier-solana"
    )
    assert (
        _slugify_program("Alliance DAO (Multi-chain / Crypto)") == "alliance-dao-multi-chain-crypto"
    )
    # Idempotent — same input → same slug.
    assert _slugify_program("Solaris Accelerator (Solana)") == _slugify_program(
        "Solaris Accelerator (Solana)"
    )


def test_web3_accelerators_chunks_counts_match_source() -> None:
    """Dataset produces 10 program_lens + 8 mentor_thread + 10 program_summary = 28 chunks."""
    src = _read_web3_accelerators_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "web3_accelerator_dataset.json"
    )
    chunks = _build_web3_accelerators_chunks(src)
    by_kind: dict[str, int] = {}
    for c in chunks:
        by_kind[c.chunk_kind] = by_kind.get(c.chunk_kind, 0) + 1
    assert by_kind.get("program_lens") == 10
    assert by_kind.get("mentor_thread") == 8
    assert by_kind.get("program_summary") == 10
    assert len(chunks) == 28


def test_web3_accelerators_chunks_carry_dedup_ready_post_ids() -> None:
    """Every web3 chunk has a stable post_id so the dedup tuple is unique."""
    src = _read_web3_accelerators_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "web3_accelerator_dataset.json"
    )
    chunks = _build_web3_accelerators_chunks(src)
    assert all(c.post_id for c in chunks)
    lens_rows = [c for c in chunks if c.chunk_kind == "program_lens"]
    summary_rows = [c for c in chunks if c.chunk_kind == "program_summary"]
    assert all(c.post_id and c.post_id.startswith("program_lens__") for c in lens_rows)
    assert all(c.post_id and c.post_id.startswith("program_summary__") for c in summary_rows)
    # mentor_thread post_ids come from the source — non-empty digits.
    thread_rows = [c for c in chunks if c.chunk_kind == "mentor_thread"]
    assert all(c.post_id and c.post_id.isdigit() for c in thread_rows)


def test_web3_mentor_thread_carries_program_and_chain() -> None:
    src = _read_web3_accelerators_source_file(
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "web3_accelerator_dataset.json"
    )
    chunks = _build_web3_accelerators_chunks(src)
    threads = [c for c in chunks if c.chunk_kind == "mentor_thread"]
    assert threads, "expected mentor_thread chunks"
    # Every thread row carries program + chain metadata for downstream filters.
    assert all(c.program for c in threads)
    assert all(c.chain for c in threads)
    # At least one Billy / Adam / Qiao thread present (sanity on usernames).
    handles = {c.username for c in threads}
    assert "twentyOne2x" in handles
    assert "QwQiao" in handles


def test_calibration_corpus_id_with_programs() -> None:
    """Mixed dataset produces the extended `N_judges:M_programs:date` shape."""
    rows = [
        {"username": "a", "chunk_kind": "profile", "dataset": COLOSSEUM_DATASET},
        {"username": "b", "chunk_kind": "profile", "dataset": COLOSSEUM_DATASET},
        {
            "username": "Colosseum",
            "chunk_kind": "program_lens",
            "dataset": WEB3_ACCELERATORS_DATASET,
            "program": "Colosseum",
        },
        {
            "username": "Alliance",
            "chunk_kind": "program_lens",
            "dataset": WEB3_ACCELERATORS_DATASET,
            "program": "Alliance",
        },
    ]
    cid = calibration_corpus_id(rows, today="2026-05-03")
    assert cid == "colosseum:2_judges:2_programs:2026-05-03"


def test_source_file_is_valid_json_with_judges_array() -> None:
    """Defence-in-depth: the source file shape is what we ingest."""
    path = (
        Path(__file__).parents[3] / "docs" / "judges" / "sources" / "judges_source_colosseum.json"
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    assert isinstance(data["judges"], list)
    assert data["total_judges"] == 34
