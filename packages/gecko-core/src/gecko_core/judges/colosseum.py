"""Colosseum-judges calibration corpus loader.

Reads ``docs/judges/sources/judges_source_colosseum.json`` and writes
each judge profile + feedback post as a chunk into the existing
``gecko_rag.judge_corpus`` Mongo collection (created in
``gecko_core.judges.corpus``).

Two chunk kinds, both keyed by ``dataset="colosseum_judges"`` so the
calibration loader (``load_calibration_chunks``) can pull the full set
without similarity-search ranking — 42 chunks is small enough to fit
verbatim in the AG2 system messages.

Idempotent on re-run: dedupe key is
``(username, chunk_kind, post_id)`` where ``post_id`` is ``None`` for
profiles. The unique index for the legacy judge-tweet ingestion path
(``judge_handle, tweet_id``) does NOT collide with this set because
``judge_handle`` is null on calibration rows; we manage idempotency
via a separate index.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from gecko_core.db.mongo import _db, mongo_uri
from gecko_core.judges.corpus import EMBED_DIM, JUDGE_CORPUS_COLLECTION

logger = logging.getLogger(__name__)

# Single source of truth for the calibration dataset identifier — referenced
# in CLI, footer rendering, and the calibration loader.
COLOSSEUM_DATASET: str = "colosseum_judges"
WEB3_ACCELERATORS_DATASET: str = "web3_accelerators"

# Pattern A — canonical Literal, imported by every consumer. SQL/Mongo
# documents store this as a plain string but the Python side never
# redeclares.
#
# Six kinds total: ``profile`` + ``feedback_post`` come from the original
# profiles file (``judges_source_colosseum.json``); the four trailing
# kinds come from ``judges_feedback_posts.json``, which captures the
# real public X interactions (solicitation thread, reply chain, overall
# style synthesis, and lighter-activity notes for adjacent judges).
ChunkKind = Literal[
    "profile",
    "feedback_post",
    "feedback_interaction",
    "solicitation",
    "style_synthesis",
    "light_activity_note",
    # S21-CALIBRATION-WEB3-01 — web3 accelerator dataset chunks. Sister
    # ingestion path persists into the same Mongo collection but tags
    # rows with ``dataset="web3_accelerators"`` so the calibration loader
    # can opt in/out independently of the Colosseum set.
    "program_lens",
    "mentor_thread",
    "program_summary",
]


@dataclass
class CalibrationChunk:
    """One chunk in the calibration corpus.

    ``embedding`` is optional because the ingestion path embeds in a
    single batch; tests that don't have an OpenAI key still write the
    profile/feedback rows so the load path is exercisable.

    ``target_project`` and ``style`` are populated only for
    ``feedback_interaction`` chunks (parsed from the ``reply_to`` and
    ``style`` fields in ``judges_feedback_posts.json``).
    """

    username: str
    name: str
    affiliation: str
    region_superteam: str
    superteam_association: str
    chunk_kind: ChunkKind
    text: str
    post_id: str | None = None
    post_date: str | None = None
    related_to_colosseum: bool | None = None
    target_project: str | None = None
    style: str | None = None
    embedding: list[float] | None = None
    # S21-CALIBRATION-WEB3-01 — program metadata for web3-accelerator
    # chunks. Optional / None on Colosseum rows. Stored on the Mongo
    # doc so downstream filters (`--calibration web3` etc.) can group
    # by program/chain without re-parsing text.
    program: str | None = None
    chain: str | None = None


def _calibration_collection() -> Any | None:
    """Return the Mongo collection (shared with judge_corpus) or None."""
    if not mongo_uri():
        return None
    db = _db()
    if db is None:
        return None
    return db[JUDGE_CORPUS_COLLECTION]


async def _ensure_calibration_index() -> None:
    """Create the calibration dedup index if absent.

    Separate from the legacy ``judge_corpus_handle_tweet_id_uniq``
    index — calibration rows have ``judge_handle=None`` and the
    legacy index would collide on duplicate nulls. This index keys
    on ``dataset + username + chunk_kind + post_id`` so the same
    profile/post never lands twice.
    """
    coll = _calibration_collection()
    if coll is None:
        return
    try:
        await coll.create_index(
            [
                ("dataset", 1),
                ("username", 1),
                ("chunk_kind", 1),
                ("post_id", 1),
            ],
            name="judge_corpus_calibration_dedup",
        )
    except Exception as exc:  # pragma: no cover — best-effort
        logger.warning("calibration.index_create_failed: %s", exc)


def _read_source_file(path: str | Path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"calibration source file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("calibration JSON root must be an object")
    if not isinstance(data.get("judges"), list):
        raise ValueError("calibration JSON must have 'judges' array")
    return data


def _build_chunks(source: dict[str, Any]) -> list[CalibrationChunk]:
    """Walk the source dict and produce profile + feedback_post chunks."""
    out: list[CalibrationChunk] = []
    for judge in source.get("judges", []):
        if not isinstance(judge, dict):
            continue
        username = str(judge.get("username") or "").lstrip("@").strip()
        if not username:
            continue
        name = str(judge.get("name") or "").strip()
        affiliation = str(judge.get("affiliation") or "").strip()
        region = str(judge.get("region_superteam") or "").strip()
        association = str(judge.get("superteam_association") or "").strip()
        profile_summary = str(judge.get("profile_summary") or "").strip()

        if profile_summary:
            out.append(
                CalibrationChunk(
                    username=username,
                    name=name,
                    affiliation=affiliation,
                    region_superteam=region,
                    superteam_association=association,
                    chunk_kind="profile",
                    text=profile_summary,
                )
            )

        for post in judge.get("feedback_posts") or []:
            if not isinstance(post, dict):
                continue
            summary = str(post.get("summary") or "").strip()
            post_id = str(post.get("post_id") or "").strip() or None
            if not summary or not post_id:
                continue
            out.append(
                CalibrationChunk(
                    username=username,
                    name=name,
                    affiliation=affiliation,
                    region_superteam=region,
                    superteam_association=association,
                    chunk_kind="feedback_post",
                    text=summary,
                    post_id=post_id,
                    post_date=str(post.get("date") or "").strip() or None,
                    related_to_colosseum=bool(post.get("related_to_colosseum"))
                    if "related_to_colosseum" in post
                    else None,
                )
            )
    return out


def _read_feedback_posts_source_file(path: str | Path) -> dict[str, Any]:
    """Read the ``judges_feedback_posts.json`` file shape.

    Distinct from :func:`_read_source_file` because the root keys differ:
    the feedback-posts file has ``judges_with_public_feedback`` instead
    of ``judges``.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"feedback posts source file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("feedback posts JSON root must be an object")
    if not isinstance(data.get("judges_with_public_feedback"), list):
        raise ValueError("feedback posts JSON must have 'judges_with_public_feedback' array")
    return data


def _build_feedback_posts_chunks(source: dict[str, Any]) -> list[CalibrationChunk]:
    """Walk the feedback-posts source dict and produce calibration chunks.

    Produces four chunk_kinds: ``solicitation``, ``feedback_interaction``,
    ``style_synthesis``, ``light_activity_note``. See module docstring
    for the wire-shape contract.
    """
    out: list[CalibrationChunk] = []

    for judge in source.get("judges_with_public_feedback", []):
        if not isinstance(judge, dict):
            continue
        username = str(judge.get("username") or "").lstrip("@").strip()
        if not username:
            continue
        name = str(judge.get("name") or "").strip()
        association = str(judge.get("superteam_association") or "").strip()
        # affiliation/region aren't present in the feedback-posts source;
        # leave blank — the rendered block doesn't depend on them for
        # these chunk_kinds.
        affiliation = ""
        region = ""

        # 1. solicitation — one per main_solicitation_post.
        solicitation = judge.get("main_solicitation_post") or {}
        sol_post_id: str | None = None
        if isinstance(solicitation, dict):
            content = str(solicitation.get("content") or "").strip()
            purpose = str(solicitation.get("purpose") or "").strip()
            sol_post_id = str(solicitation.get("post_id") or "").strip() or None
            replies = solicitation.get("replies")
            if content or purpose:
                text = content
                if purpose:
                    text = f"{content}\n\nPurpose: {purpose}" if content else purpose
                out.append(
                    CalibrationChunk(
                        username=username,
                        name=name,
                        affiliation=affiliation,
                        region_superteam=region,
                        superteam_association=association,
                        chunk_kind="solicitation",
                        text=text,
                        post_id=sol_post_id,
                        post_date=str(solicitation.get("date") or "").strip() or None,
                        related_to_colosseum=True,
                        # Replies count is informative for downstream
                        # synth ranking; encoded in the text trailer to
                        # avoid widening the dataclass.
                    )
                )
                if isinstance(replies, int):
                    out[-1].text = f"{out[-1].text}\n\nReplies: {replies}"

        # 2. feedback_interaction — one per key_feedback_interactions[*].
        for interaction in judge.get("key_feedback_interactions") or []:
            if not isinstance(interaction, dict):
                continue
            content = str(interaction.get("content") or "").strip()
            if not content:
                continue
            style = str(interaction.get("style") or "").strip() or None
            reply_to = str(interaction.get("reply_to") or "").strip()
            target_project = reply_to or None
            raw_post_id = str(interaction.get("post_id") or "").strip()
            if raw_post_id:
                post_id: str = raw_post_id
            else:
                # Stable synthetic id when the source omits one — encodes
                # the parent solicitation + reply target so re-runs dedup.
                target_slug = reply_to.split()[0].lstrip("@") if reply_to else "unknown"
                base = sol_post_id or f"sol__{username}"
                post_id = f"{base}__{target_slug}"
            text = content
            if style:
                text = f"{content}\n\nStyle: {style}"
            out.append(
                CalibrationChunk(
                    username=username,
                    name=name,
                    affiliation=affiliation,
                    region_superteam=region,
                    superteam_association=association,
                    chunk_kind="feedback_interaction",
                    text=text,
                    post_id=post_id,
                    related_to_colosseum=True,
                    target_project=target_project,
                    style=style,
                )
            )

        # 3. style_synthesis — one per overall_style.
        overall_style = str(judge.get("overall_style") or "").strip()
        if overall_style:
            out.append(
                CalibrationChunk(
                    username=username,
                    name=name,
                    affiliation=affiliation,
                    region_superteam=region,
                    superteam_association=association,
                    chunk_kind="style_synthesis",
                    text=overall_style,
                    post_id=f"style_synthesis__{username}",
                    related_to_colosseum=True,
                )
            )

    # 4. light_activity_note — one per other_judges_with_light_public_activity[*].
    for note in source.get("other_judges_with_light_public_activity", []):
        if not isinstance(note, dict):
            continue
        username = str(note.get("username") or "").lstrip("@").strip()
        if not username:
            continue
        activity = str(note.get("activity") or "").strip()
        if not activity:
            continue
        name = str(note.get("name") or "").strip()
        out.append(
            CalibrationChunk(
                username=username,
                name=name,
                affiliation="",
                region_superteam="",
                superteam_association="",
                chunk_kind="light_activity_note",
                text=activity,
                post_id=f"light_activity__{username}",
                related_to_colosseum=True,
            )
        )

    return out


@dataclass
class CalibrationIngestResult:
    profile_count: int
    feedback_count: int
    new_inserted: int
    duplicates: int
    # New (non-breaking — defaulted) counts for the feedback-posts file.
    # Existing callers that build this dataclass positionally still work
    # because both new fields default; new callers should pass kwargs.
    feedback_interaction_count: int = 0
    solicitation_count: int = 0
    style_synthesis_count: int = 0
    light_activity_count: int = 0
    # S21-CALIBRATION-WEB3-01 — counts for the web3-accelerator dataset.
    # Defaulted so existing positional callers keep working.
    program_lens_count: int = 0
    mentor_thread_count: int = 0
    program_summary_count: int = 0


async def ingest_colosseum(
    source_path: str | Path,
    *,
    embed: bool = True,
) -> CalibrationIngestResult:
    """Ingest the Colosseum judges JSON into ``gecko_rag.judge_corpus``.

    Idempotent: re-running with the same source produces zero new rows.
    Returns counts for CLI rendering.
    """
    path = Path(source_path)
    source = _read_source_file(path)
    chunks = _build_chunks(source)
    profile_count = sum(1 for c in chunks if c.chunk_kind == "profile")
    feedback_count = sum(1 for c in chunks if c.chunk_kind == "feedback_post")

    coll = _calibration_collection()
    if coll is None:
        # No Mongo wired — surface a clear error so the operator notices
        # rather than silently no-oping.
        raise RuntimeError(
            "MongoDB not configured (MONGODB_URI unset); cannot persist calibration corpus."
        )

    await _ensure_calibration_index()

    if embed and chunks:
        try:
            from gecko_core.ingestion.embedder import embed as embed_texts

            vectors, _tokens = await embed_texts([c.text for c in chunks])
            for chunk, vec in zip(chunks, vectors, strict=False):
                if len(vec) == EMBED_DIM:
                    chunk.embedding = vec
        except Exception as exc:
            logger.warning("calibration.embed_failed: %s", exc)

    new_inserted, duplicates = await _persist_chunks(coll, chunks)

    return CalibrationIngestResult(
        profile_count=profile_count,
        feedback_count=feedback_count,
        new_inserted=new_inserted,
        duplicates=duplicates,
    )


async def _embed_chunks_in_place(chunks: list[CalibrationChunk]) -> None:
    """Embed all chunks in one batch. Best-effort — failure is logged."""
    if not chunks:
        return
    try:
        from gecko_core.ingestion.embedder import embed as embed_texts

        vectors, _tokens = await embed_texts([c.text for c in chunks])
        for chunk, vec in zip(chunks, vectors, strict=False):
            if len(vec) == EMBED_DIM:
                chunk.embedding = vec
    except Exception as exc:
        logger.warning("calibration.embed_failed: %s", exc)


async def _persist_chunks(
    coll: Any,
    chunks: list[CalibrationChunk],
    *,
    dataset: str = COLOSSEUM_DATASET,
) -> tuple[int, int]:
    """Insert chunks via the dedup tuple. Returns (new_inserted, duplicates).

    Note: ``light_activity_note`` and ``style_synthesis`` rely on a
    synthetic stable ``post_id`` so the dedup tuple
    ``(dataset, username, chunk_kind, post_id)`` never has a None
    collision across re-runs.
    """
    now = datetime.now(UTC)
    new_inserted = 0
    duplicates = 0
    for chunk in chunks:
        query: dict[str, Any] = {
            "dataset": dataset,
            "username": chunk.username,
            "chunk_kind": chunk.chunk_kind,
            "post_id": chunk.post_id,
        }
        existing = await coll.find_one(query)
        if existing is not None:
            duplicates += 1
            continue
        doc: dict[str, Any] = {
            "dataset": dataset,
            "username": chunk.username,
            "name": chunk.name,
            "affiliation": chunk.affiliation,
            "region_superteam": chunk.region_superteam,
            "superteam_association": chunk.superteam_association,
            "chunk_kind": chunk.chunk_kind,
            "post_id": chunk.post_id,
            "post_date": chunk.post_date,
            "related_to_colosseum": chunk.related_to_colosseum,
            "text": chunk.text,
            "captured_at": now,
            "provider_kind": "judge_corpus",
        }
        if chunk.target_project is not None:
            doc["target_project"] = chunk.target_project
        if chunk.style is not None:
            doc["style"] = chunk.style
        if chunk.program is not None:
            doc["program"] = chunk.program
        if chunk.chain is not None:
            doc["chain"] = chunk.chain
        if chunk.embedding is not None:
            doc["embedding"] = chunk.embedding
        await coll.insert_one(doc)
        new_inserted += 1
    return new_inserted, duplicates


async def ingest_colosseum_feedback_posts(
    source_path: str | Path,
    *,
    embed: bool = True,
) -> CalibrationIngestResult:
    """Ingest the ``judges_feedback_posts.json`` corpus into Mongo.

    Sister to :func:`ingest_colosseum`. Shares the same Mongo collection
    and dataset id (``colosseum_judges``) so the calibration loader sees
    a unified set. Idempotent on re-run (same dedup tuple). Per
    auto-mode default: embeds with the same model as profile chunks so
    downstream similarity search ranks them on equal footing.
    """
    path = Path(source_path)
    source = _read_feedback_posts_source_file(path)
    chunks = _build_feedback_posts_chunks(source)

    coll = _calibration_collection()
    if coll is None:
        raise RuntimeError(
            "MongoDB not configured (MONGODB_URI unset); cannot persist calibration corpus."
        )

    await _ensure_calibration_index()

    if embed:
        await _embed_chunks_in_place(chunks)

    new_inserted, duplicates = await _persist_chunks(coll, chunks)

    return CalibrationIngestResult(
        profile_count=0,
        feedback_count=0,
        new_inserted=new_inserted,
        duplicates=duplicates,
        feedback_interaction_count=sum(1 for c in chunks if c.chunk_kind == "feedback_interaction"),
        solicitation_count=sum(1 for c in chunks if c.chunk_kind == "solicitation"),
        style_synthesis_count=sum(1 for c in chunks if c.chunk_kind == "style_synthesis"),
        light_activity_count=sum(1 for c in chunks if c.chunk_kind == "light_activity_note"),
    )


def _slugify_program(name: str) -> str:
    """Stable slug for synthetic post_ids on web3-accelerator chunks.

    Lowercase, alnum + dashes, collapse runs. Keeps dedup tuple
    deterministic across re-runs.
    """
    out_chars: list[str] = []
    prev_dash = False
    for ch in name.lower():
        if ch.isalnum():
            out_chars.append(ch)
            prev_dash = False
        elif not prev_dash:
            out_chars.append("-")
            prev_dash = True
    return "".join(out_chars).strip("-") or "program"


def _read_web3_accelerators_source_file(path: str | Path) -> dict[str, Any]:
    """Read the ``web3_accelerator_dataset.json`` shape.

    Top-level requires a ``programs`` object keyed by program name.
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"web3 accelerators source file not found: {p}")
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("web3 accelerators JSON root must be an object")
    if not isinstance(data.get("programs"), dict):
        raise ValueError("web3 accelerators JSON must have 'programs' object")
    return data


def _build_web3_accelerators_chunks(source: dict[str, Any]) -> list[CalibrationChunk]:
    """Walk the web3-accelerator dict and produce calibration chunks.

    Three chunk_kinds: ``program_lens`` (one per program), ``mentor_thread``
    (one per thread inside ``key_mentors_with_threads[*].threads[*]``),
    ``program_summary`` (one per program with ``public_threads_summary``).
    """
    out: list[CalibrationChunk] = []
    programs = source.get("programs") or {}
    if not isinstance(programs, dict):
        return out

    for program_name, program in programs.items():
        if not isinstance(program, dict):
            continue
        name_clean = str(program_name).strip()
        if not name_clean:
            continue
        slug = _slugify_program(name_clean)
        chain = str(program.get("chain") or "").strip()
        description = str(program.get("description") or "").strip()
        lens = str(program.get("overall_opinion_lens") or "").strip()
        threads_summary = str(program.get("public_threads_summary") or "").strip()

        # 1. program_lens — one per program. ``username`` set to the
        # program name so the dedup tuple is unique across programs even
        # when post_id slugs collide (defensive).
        lens_text_parts = [name_clean]
        if chain:
            lens_text_parts.append(f"Chain: {chain}")
        if description:
            lens_text_parts.append(f"Description: {description}")
        if lens:
            lens_text_parts.append(f"Lens: {lens}")
        lens_text = "\n".join(lens_text_parts)
        out.append(
            CalibrationChunk(
                username=name_clean,
                name=name_clean,
                affiliation="",
                region_superteam="",
                superteam_association="",
                chunk_kind="program_lens",
                text=lens_text,
                post_id=f"program_lens__{slug}",
                program=name_clean,
                chain=chain or None,
            )
        )

        # 2. mentor_thread — per-thread inside each mentor.
        mentors = program.get("key_mentors_with_threads") or []
        if isinstance(mentors, list):
            for mentor in mentors:
                if not isinstance(mentor, dict):
                    continue
                mentor_name = str(mentor.get("name") or "").strip()
                mentor_handle = str(mentor.get("username") or "").lstrip("@").strip()
                role = str(mentor.get("role") or "").strip()
                threads = mentor.get("threads") or []
                if not isinstance(threads, list):
                    continue
                for thread in threads:
                    if not isinstance(thread, dict):
                        continue
                    post_id = str(thread.get("post_id") or "").strip()
                    if not post_id:
                        # Skip threads with no stable id rather than
                        # synthesizing — every shipped thread has one,
                        # so a missing id signals a malformed source row.
                        continue
                    content = str(thread.get("content") or "").strip()
                    summary = str(thread.get("summary") or "").strip()
                    style = str(thread.get("style") or "").strip() or None
                    text_parts: list[str] = []
                    if mentor_name:
                        prefix = mentor_name
                        if role:
                            prefix = f"{mentor_name} ({role})"
                        text_parts.append(prefix)
                    if content:
                        text_parts.append(content)
                    if summary:
                        text_parts.append(f"Summary: {summary}")
                    if style:
                        text_parts.append(f"Style: {style}")
                    out.append(
                        CalibrationChunk(
                            # Handle keeps the dedup tuple unique per
                            # mentor; if the source omits @handle we
                            # fall back to mentor_name then program.
                            username=mentor_handle or mentor_name or name_clean,
                            name=mentor_name,
                            affiliation=role,
                            region_superteam="",
                            superteam_association="",
                            chunk_kind="mentor_thread",
                            text="\n\n".join(text_parts),
                            post_id=post_id,
                            post_date=str(thread.get("date") or "").strip() or None,
                            style=style,
                            program=name_clean,
                            chain=chain or None,
                        )
                    )

        # 3. program_summary — one per program when public_threads_summary present.
        if threads_summary:
            out.append(
                CalibrationChunk(
                    username=name_clean,
                    name=name_clean,
                    affiliation="",
                    region_superteam="",
                    superteam_association="",
                    chunk_kind="program_summary",
                    text=threads_summary,
                    post_id=f"program_summary__{slug}",
                    program=name_clean,
                    chain=chain or None,
                )
            )

    return out


async def ingest_web3_accelerators(
    source_path: str | Path,
    *,
    embed: bool = True,
) -> CalibrationIngestResult:
    """Ingest the web3-accelerator dataset into Mongo.

    Sister to :func:`ingest_colosseum_feedback_posts`. Persists into the
    same Mongo collection but tags rows with
    ``dataset='web3_accelerators'`` so the calibration loader can opt
    in/out independently of the Colosseum corpus. Idempotent on re-run.
    """
    path = Path(source_path)
    source = _read_web3_accelerators_source_file(path)
    chunks = _build_web3_accelerators_chunks(source)

    coll = _calibration_collection()
    if coll is None:
        raise RuntimeError(
            "MongoDB not configured (MONGODB_URI unset); cannot persist calibration corpus."
        )

    await _ensure_calibration_index()

    if embed:
        await _embed_chunks_in_place(chunks)

    new_inserted, duplicates = await _persist_chunks(
        coll, chunks, dataset=WEB3_ACCELERATORS_DATASET
    )

    return CalibrationIngestResult(
        profile_count=0,
        feedback_count=0,
        new_inserted=new_inserted,
        duplicates=duplicates,
        program_lens_count=sum(1 for c in chunks if c.chunk_kind == "program_lens"),
        mentor_thread_count=sum(1 for c in chunks if c.chunk_kind == "mentor_thread"),
        program_summary_count=sum(1 for c in chunks if c.chunk_kind == "program_summary"),
    )


def _parse_reviewer_handle(reviewer: str) -> tuple[str, str]:
    """Extract (username, display_name) from 'Name (@handle)' strings.

    Falls back to the full string as display_name with empty handle when
    the pattern doesn't match (graceful on free-form reviewer strings).
    """
    import re as _re

    m = _re.search(r"@(\w+)", reviewer)
    handle = m.group(1) if m else ""
    # Name is everything before the first " (" or the whole string.
    name = _re.sub(r"\s*\(@\w+\)\s*$", "", reviewer).strip() or reviewer.strip()
    return handle, name


def _build_single_judge_chunks(source: dict[str, Any]) -> list[CalibrationChunk]:
    """Build calibration chunks from a single-judge JSON file.

    Handles three schema variants:
    - Adam/similar: ``key_replies_and_insights`` list of {project, reply}
    - Billy/similar: ``key_feedback_replies`` list of {project, reply}
    - GuiBibeau/similar: ``reviews`` list with richer {project, key_feedback,
      positive, critiques, style_notes} shape.

    Each variant emits ``feedback_interaction`` chunks (one per reply/review)
    plus one ``style_synthesis`` chunk from ``overall_judging_style`` or
    ``extracted_patterns_for_super_agent``.
    """
    out: list[CalibrationChunk] = []

    reviewer = str(source.get("reviewer") or "").strip()
    handle, name = _parse_reviewer_handle(reviewer)
    if not handle:
        handle = str(source.get("username") or "").lstrip("@").strip()
    if not handle:
        logger.warning("single_judge_chunks: no handle found in source, skipping")
        return out

    role = str(source.get("role") or "").strip()
    description = str(source.get("description") or "").strip()

    # --- feedback_interaction chunks ---
    # Normalise all three schema variants into a common {project, text, post_id} list.
    interactions_raw: list[dict[str, Any]] = []

    if source.get("key_replies_and_insights"):
        for item in source["key_replies_and_insights"]:
            if not isinstance(item, dict):
                continue
            interactions_raw.append(
                {
                    "project": str(item.get("project") or "").strip(),
                    "text": str(item.get("reply") or "").strip(),
                    "post_id": str(item.get("post_id") or "").strip() or None,
                    "date": None,
                    "style": None,
                }
            )

    elif source.get("key_feedback_replies"):
        for item in source["key_feedback_replies"]:
            if not isinstance(item, dict):
                continue
            interactions_raw.append(
                {
                    "project": str(item.get("project") or "").strip(),
                    "text": str(item.get("reply") or "").strip(),
                    "post_id": str(item.get("post_id") or "").strip() or None,
                    "date": None,
                    "style": None,
                }
            )

    elif source.get("reviews"):
        for item in source["reviews"]:
            if not isinstance(item, dict):
                continue
            project = str(item.get("project") or "").strip()
            key_feedback = str(item.get("key_feedback") or "").strip()
            positives = item.get("positive") or []
            critiques = item.get("critiques") or []
            style_notes = str(item.get("style_notes") or "").strip()
            parts = [key_feedback]
            if isinstance(positives, list) and positives:
                parts.append("Positives: " + "; ".join(str(p) for p in positives))
            if isinstance(critiques, list) and critiques:
                parts.append("Critiques: " + "; ".join(str(c) for c in critiques))
            if style_notes:
                parts.append(f"Style: {style_notes}")
            interactions_raw.append(
                {
                    "project": project,
                    "text": "\n".join(parts),
                    "post_id": str(item.get("post_id") or "").strip() or None,
                    "date": str(item.get("date") or "").strip() or None,
                    "style": style_notes or None,
                }
            )

    for i, ir in enumerate(interactions_raw):
        text = ir["text"]
        if not text:
            continue
        project = ir["project"]
        if project:
            text = f"{project}: {text}" if not text.startswith(project) else text
        post_id: str = ir["post_id"] or f"judge_review__{handle}__{i}"
        out.append(
            CalibrationChunk(
                username=handle,
                name=name,
                affiliation=role,
                region_superteam="",
                superteam_association="",
                chunk_kind="feedback_interaction",
                text=text,
                post_id=post_id,
                post_date=ir["date"],
                related_to_colosseum=True,
                target_project=project or None,
                style=ir["style"],
            )
        )

    # --- style_synthesis ---
    style_text = (
        str(source.get("overall_judging_style") or "").strip()
        or str(source.get("extracted_patterns_for_super_agent") or "").strip()
    )
    if not style_text and description:
        style_text = description
    if style_text:
        full_text = style_text
        if role:
            full_text = f"{role}\n\n{style_text}"
        out.append(
            CalibrationChunk(
                username=handle,
                name=name,
                affiliation=role,
                region_superteam="",
                superteam_association="",
                chunk_kind="style_synthesis",
                text=full_text,
                post_id=f"style_synthesis__{handle}",
                related_to_colosseum=True,
            )
        )

    return out


async def ingest_single_judge_file(
    source_path: str | Path,
    *,
    embed: bool = True,
) -> CalibrationIngestResult:
    """Ingest a single-judge JSON file into the calibration corpus.

    Handles adam_colosseum_judge.json, billy_colosseum_judge.json, and
    gui_bibeau_colosseum_reviews.json formats. Idempotent on re-run.
    """
    path = Path(source_path)
    if not path.is_file():
        raise FileNotFoundError(f"judge file not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"judge JSON root must be an object: {path}")

    chunks = _build_single_judge_chunks(data)

    coll = _calibration_collection()
    if coll is None:
        raise RuntimeError(
            "MongoDB not configured (MONGODB_URI unset); cannot persist calibration corpus."
        )

    await _ensure_calibration_index()

    if embed:
        await _embed_chunks_in_place(chunks)

    new_inserted, duplicates = await _persist_chunks(coll, chunks)

    return CalibrationIngestResult(
        profile_count=0,
        feedback_count=0,
        new_inserted=new_inserted,
        duplicates=duplicates,
        feedback_interaction_count=sum(1 for c in chunks if c.chunk_kind == "feedback_interaction"),
        style_synthesis_count=sum(1 for c in chunks if c.chunk_kind == "style_synthesis"),
    )


async def load_calibration_chunks(dataset: str = COLOSSEUM_DATASET) -> list[dict[str, Any]]:
    """Return all rows for ``dataset`` — small (42 chunks) so we don't rank.

    Empty list when Mongo isn't reachable; caller decides whether to
    error or silently skip injection.
    """
    coll = _calibration_collection()
    if coll is None:
        return []
    out: list[dict[str, Any]] = []
    cursor = coll.find({"dataset": dataset}).sort([("chunk_kind", 1), ("username", 1)])
    async for doc in cursor:
        out.append(dict(doc))
    return out


def render_calibration_block(rows: list[dict[str, Any]]) -> str:
    """Render rows into a compact text block for system-prompt injection.

    Format: one line per chunk, profile rows first, feedback_post rows
    after. Each line carries the user handle, name (when present), and
    the verbatim text — small enough to prepend to every system prompt
    without burning a noticeable token budget.
    """
    if not rows:
        return ""
    profiles = [r for r in rows if r.get("chunk_kind") == "profile"]
    posts = [r for r in rows if r.get("chunk_kind") == "feedback_post"]
    lines = [
        "CALIBRATION CORPUS — Colosseum hackathon judges (Solana ecosystem).",
        "Use this set to align verdict tone and criteria with the named-judge",
        "lens: what these judges weight, how they phrase critique, what they",
        "down-rate. Do NOT cite individual judges in the verdict; this is",
        "calibration context, not retrieved evidence.",
        "",
        # S21-CALIBRATION-FOUNDER-POSTURE-01 — second framework layered into
        # the same block, anonymised at the corpus level (no accelerator
        # name in panel-facing prose). Distilled from the broader
        # web3-accelerator dataset's founder-evaluation lens: in private
        # markets force-of-will turns average ideas into winning businesses,
        # so the calibrated panel evaluates the FOUNDER (contrarian framing,
        # shipping evidence, willingness to be wrong) in parallel to the
        # IDEA (greenfield vs iterative). The framework attribution stays
        # in the corpus, never in the verdict surface.
        "FOUNDER-EVALUATION FRAMEWORK (force-of-will lens). Parallel to the",
        "idea-evaluation lens above, founders evaluated as having strong",
        "force-of-will exhibit: contrarian framing of the wedge ('most",
        "people think X, but actually Y'), prior shipping with named",
        "users, public solicitation of pushback (DMs open, 'fire away",
        "here'), named time-to-pay urgency, and explicit falsifiers.",
        "Founders evaluated as weak default to polished decks with no",
        "named buyer, no contrarian frame, and no invitation to be wrong.",
        "When the idea text or any cited builder context surfaces strong-",
        "posture signals, let it tilt wedge confidence UP — even average",
        "ideas with strong-posture founders ship; the inverse rarely does.",
        "When NO founder context is present, name the gap rather than",
        "inferring posture from idea polish alone (polished pitches with",
        "no founder signal often indicate defensiveness, not strength).",
        "",
        f"Profiles ({len(profiles)}):",
    ]
    for r in profiles:
        handle = r.get("username") or ""
        name = r.get("name") or ""
        region = r.get("region_superteam") or ""
        text = r.get("text") or ""
        prefix = f"@{handle}"
        if name:
            prefix += f" ({name})"
        if region:
            prefix += f" — {region}"
        lines.append(f"- {prefix}: {text}")
    if posts:
        lines.append("")
        lines.append(f"Feedback posts ({len(posts)}):")
        for r in posts:
            handle = r.get("username") or ""
            date = r.get("post_date") or ""
            text = r.get("text") or ""
            lines.append(f"- @{handle} [{date}]: {text}")
    return "\n".join(lines)


def calibration_corpus_id(rows: list[dict[str, Any]], *, today: str | None = None) -> str:
    """Build the corpus identifier surfaced in ResearchResult / footer.

    Shape: ``colosseum:<N>_judges:<YYYY-MM-DD>``. ``N`` is the unique
    judge count in the row set; ``today`` defaults to today's date so
    the footer reflects when the calibration was loaded into the run.
    """
    today_s = today or datetime.now(UTC).date().isoformat()
    # Count judges as unique usernames in the colosseum-tagged subset
    # only; web3 program rows are name-keyed and would inflate the
    # judge count if mixed in.
    colosseum_rows = [r for r in rows if r.get("dataset") == COLOSSEUM_DATASET]
    if not colosseum_rows:
        # Back-compat: pre-tagged callers (tests) pass rows without a
        # ``dataset`` field — treat the whole set as colosseum.
        colosseum_rows = [r for r in rows if not r.get("dataset")]
    judges = {r.get("username") for r in colosseum_rows if r.get("username")}

    # Web3 accelerator rows: count distinct programs, not chunk rows.
    web3_rows = [r for r in rows if r.get("dataset") == WEB3_ACCELERATORS_DATASET]
    programs = {r.get("program") or r.get("username") for r in web3_rows}
    programs.discard(None)
    n_programs = len(programs)

    base = f"colosseum:{len(judges)}_judges:{today_s}"
    if n_programs > 0:
        # Extended shape carries program count between judges and date so
        # the footer can split the line into "N judges + M programs".
        return f"colosseum:{len(judges)}_judges:{n_programs}_programs:{today_s}"
    return base


__all__ = [
    "COLOSSEUM_DATASET",
    "WEB3_ACCELERATORS_DATASET",
    "CalibrationChunk",
    "CalibrationIngestResult",
    "ChunkKind",
    "calibration_corpus_id",
    "ingest_colosseum",
    "ingest_colosseum_feedback_posts",
    "ingest_web3_accelerators",
    "load_calibration_chunks",
    "render_calibration_block",
]
