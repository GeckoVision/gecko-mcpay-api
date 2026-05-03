"""`bb judges` — judge corpus ingest + skill.md draft synthesis.

S21-JUDGE-CORPUS-01. Two subcommands:

- ``bb judges ingest --handle <h>`` — fetch tweets from twit.sh and
  persist as judge_corpus rows in Mongo. Idempotent.
- ``bb judges synth --handle <h>`` — synthesize a draft skill.md from
  the stored corpus and write to ``docs/judges/<h>.skill.md`` (or the
  ``--out`` path).

Thin wrapper — all business logic lives in ``gecko_core.judges``.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console

console = Console()


@click.group("judges")
def judges_cmd() -> None:
    """Judge corpus + skill.md draft (program-judges wedge supply side)."""


@judges_cmd.command("ingest")
@click.option("--handle", required=True, help="Twitter/X handle (no @ prefix).")
@click.option(
    "--max-calls",
    type=int,
    default=5,
    show_default=True,
    help=(
        "Hard ceiling on twit.sh /users/tweets calls. Each call is ~$0.01 "
        "and returns up to 10 tweets. Bypasses the per-session $0.05 cap."
    ),
)
def ingest(handle: str, max_calls: int) -> None:
    """Ingest tweets for HANDLE into the judge corpus."""
    from gecko_core.judges import ingest_judge

    new_count, total, spent = asyncio.run(ingest_judge(handle, max_calls=max_calls))
    clean = handle.lstrip("@").lower()
    console.print(
        f"Ingested {new_count} new tweets for @{clean} (corpus total: {total}). Spent ${spent:.2f}."
    )


@judges_cmd.command("synth")
@click.option("--handle", required=True, help="Twitter/X handle (no @ prefix).")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    default=None,
    help="Output path. Default: docs/judges/<handle>.skill.md.",
)
def synth(handle: str, out: Path | None) -> None:
    """Synthesize a draft skill.md from the stored corpus for HANDLE."""
    from gecko_core.judges import synth_skill_md

    clean = handle.lstrip("@").lower()
    try:
        md, n = asyncio.run(synth_skill_md(clean))
    except RuntimeError as exc:
        raise click.ClickException(str(exc)) from exc

    target = out or Path("docs/judges") / f"{clean}.skill.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(md, encoding="utf-8")

    # Token / cost printout uses a rough estimate; we don't surface model
    # names per CLAUDE.md.
    approx_tokens = max(1, len(md) // 4)
    approx_cost = approx_tokens * 0.000_000_15  # gpt-4o-mini blended ~$0.15/M
    console.print(
        f"Drafted: {target} ({n} tweets, ~{approx_tokens // 1000}K tokens, "
        f"${approx_cost:.2f}). Show this to @{clean} for review."
    )


@judges_cmd.command("ingest-colosseum")
@click.option(
    "--source-profiles",
    "source_profiles",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("docs/judges/sources/judges_source_colosseum.json"),
    show_default=True,
    help="Path to the Colosseum judges profile dataset (legacy + per-judge feedback summaries).",
)
@click.option(
    "--source-feedback",
    "source_feedback",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("docs/judges/sources/judges_feedback_posts.json"),
    show_default=True,
    help="Path to the Colosseum public feedback interactions dataset.",
)
@click.option(
    "--source-accelerators",
    "source_accelerators",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("docs/judges/sources/web3_accelerator_dataset.json"),
    show_default=True,
    help=(
        "Path to the multi-program web3-accelerator dataset. Tagged with "
        "dataset='web3_accelerators' so it loads independently of the "
        "Colosseum corpus. Skipped silently when the file is absent."
    ),
)
@click.option(
    "--source-judge-review",
    "source_judge_reviews",
    type=click.Path(dir_okay=False, path_type=Path),
    multiple=True,
    help=(
        "Path to a single-judge JSON file (e.g. adam_colosseum_judge.json, "
        "gui_bibeau_colosseum_reviews.json). Repeatable — pass once per file."
    ),
)
@click.option(
    "--no-embed",
    "no_embed",
    is_flag=True,
    default=False,
    help="Skip embedding generation (test-only path; live runs embed).",
)
def ingest_colosseum(
    source_profiles: Path,
    source_feedback: Path,
    source_accelerators: Path,
    source_judge_reviews: tuple[Path, ...],
    no_embed: bool,
) -> None:
    """Ingest the Colosseum judges calibration corpus into Mongo.

    Reads both the profiles dataset and the public-feedback-interactions
    dataset (when present). Either flag can be skipped by pointing it at
    a non-existent path or omitting the file from disk — missing files
    are logged and skipped, not fatal. Idempotent — re-runs produce zero
    new rows. The corpus is written into ``gecko_rag.judge_corpus`` under
    ``dataset='colosseum_judges'`` and consumed by
    ``bb research --calibration colosseum``.
    """
    from gecko_core.judges import (
        CalibrationIngestResult,
    )
    from gecko_core.judges import (
        ingest_colosseum as _ingest_profiles,
    )
    from gecko_core.judges import (
        ingest_colosseum_feedback_posts as _ingest_feedback,
    )
    from gecko_core.judges import (
        ingest_single_judge_file as _ingest_judge_review,
    )
    from gecko_core.judges import (
        ingest_web3_accelerators as _ingest_accelerators,
    )

    profile_count = 0
    feedback_count = 0
    new_inserted = 0
    duplicates = 0
    interaction_count = 0
    solicitation_count = 0
    style_count = 0
    light_count = 0
    program_lens_count = 0
    mentor_thread_count = 0
    program_summary_count = 0
    judge_review_interaction_count = 0
    judge_review_style_count = 0

    # Single asyncio.run so the Mongo motor client (cached on first
    # call) doesn't get torn down between profile + feedback ingests
    # ("Event loop is closed" on the second call otherwise).
    async def _run_all() -> tuple[
        CalibrationIngestResult | None,
        CalibrationIngestResult | None,
        CalibrationIngestResult | None,
        list[CalibrationIngestResult],
    ]:
        r1_local: CalibrationIngestResult | None = None
        r2_local: CalibrationIngestResult | None = None
        r3_local: CalibrationIngestResult | None = None
        r_reviews: list[CalibrationIngestResult] = []
        if source_profiles.is_file():
            r1_local = await _ingest_profiles(str(source_profiles), embed=not no_embed)
        if source_feedback.is_file():
            r2_local = await _ingest_feedback(str(source_feedback), embed=not no_embed)
        if source_accelerators.is_file():
            r3_local = await _ingest_accelerators(str(source_accelerators), embed=not no_embed)
        for review_path in source_judge_reviews:
            if Path(review_path).is_file():
                r_reviews.append(await _ingest_judge_review(str(review_path), embed=not no_embed))
            else:
                console.print(
                    f"[yellow]Skip:[/yellow] judge review file not found at {review_path}"
                )
        return r1_local, r2_local, r3_local, r_reviews

    try:
        r1, r2, r3, r_reviews = asyncio.run(_run_all())
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise click.ClickException(str(exc)) from exc

    if r1 is not None:
        profile_count = r1.profile_count
        feedback_count = r1.feedback_count
        new_inserted += r1.new_inserted
        duplicates += r1.duplicates
    else:
        console.print(f"[yellow]Skip:[/yellow] profiles source not found at {source_profiles}")

    if r2 is not None:
        new_inserted += r2.new_inserted
        duplicates += r2.duplicates
        interaction_count = r2.feedback_interaction_count
        solicitation_count = r2.solicitation_count
        style_count = r2.style_synthesis_count
        light_count = r2.light_activity_count
    else:
        console.print(f"[yellow]Skip:[/yellow] feedback source not found at {source_feedback}")

    if r3 is not None:
        new_inserted += r3.new_inserted
        duplicates += r3.duplicates
        program_lens_count = r3.program_lens_count
        mentor_thread_count = r3.mentor_thread_count
        program_summary_count = r3.program_summary_count
    else:
        console.print(
            f"[yellow]Skip:[/yellow] accelerators source not found at {source_accelerators}"
        )

    for rr in r_reviews:
        new_inserted += rr.new_inserted
        duplicates += rr.duplicates
        judge_review_interaction_count += rr.feedback_interaction_count
        judge_review_style_count += rr.style_synthesis_count

    new_chunks = interaction_count + solicitation_count + style_count + light_count
    web3_chunks = program_lens_count + mentor_thread_count + program_summary_count
    judge_review_chunks = judge_review_interaction_count + judge_review_style_count
    total = profile_count + feedback_count + new_chunks + web3_chunks + judge_review_chunks
    console.print(
        f"Ingested {profile_count} profile chunks + "
        f"{feedback_count} feedback chunks (legacy) + "
        f"{new_chunks} feedback-interaction chunks (new) + "
        f"{web3_chunks} web3-accelerator chunks "
        f"({program_lens_count} lens / {mentor_thread_count} threads / "
        f"{program_summary_count} summaries) + "
        f"{judge_review_chunks} judge-review chunks "
        f"({judge_review_interaction_count} interactions / {judge_review_style_count} style) — "
        f"{total} total, {duplicates} duplicates "
        f"across datasets 'colosseum_judges' + 'web3_accelerators'."
    )


__all__ = ["judges_cmd"]
