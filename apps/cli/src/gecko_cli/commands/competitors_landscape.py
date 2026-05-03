"""`bb competitors_landscape <verdict_hash>` — V1.5 standalone landscape view.

Re-renders the persisted ``ResearchResult.market_landscape`` for a saved
verdict, or re-calls the post-processor with deeper retrieval when
``--refresh`` is set (or when the verdict has no recorded landscape).

Pricing line in the footer is informational — V1.5 does NOT actually
paywall.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import click
from rich.console import Console

if TYPE_CHECKING:
    from gecko_core.models import MarketLandscape

console = Console()


_HASH_VALID_LENGTHS = {12, 64}


def _normalise_hash(raw: str) -> str:
    s = raw.strip()
    if s.startswith("verdict@"):
        s = s[len("verdict@") :]
    return s


@click.command("competitors_landscape")
@click.argument("verdict_hash", type=str)
@click.option(
    "--refresh",
    is_flag=True,
    default=False,
    help=(
        "Re-call the market_landscape post-processor with deeper retrieval "
        "instead of re-rendering the persisted landscape. Required when no "
        "landscape was recorded at research time."
    ),
)
def competitors_landscape_cmd(verdict_hash: str, refresh: bool) -> None:
    """Show the market landscape behind a saved verdict."""
    from gecko_core.persistence import (
        VerdictNotFoundError,
        load_by_verdict_hash_async,
    )

    from gecko_cli.render import _landscape_section, _short_hash

    bare = _normalise_hash(verdict_hash)
    if len(bare) not in _HASH_VALID_LENGTHS:
        raise click.BadParameter(f"verdict hash must be 12 or 64 hex characters (got {len(bare)}).")

    async def _run() -> None:
        try:
            result, idea = await load_by_verdict_hash_async(bare)
        except VerdictNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

        landscape: MarketLandscape | None = result.market_landscape

        if landscape is None and not refresh:
            raise click.ClickException(
                f"No landscape recorded for verdict@{bare[:12]}. "
                f"Re-run with: bb competitors_landscape {bare[:12]} --refresh"
            )

        if refresh:
            # Re-call path. Default behaviour per the dispatch note: try the
            # `market_landscape_standalone` prompt if ai-ml-engineer shipped
            # it, otherwise reuse the existing `market_landscape` post-
            # processor on the persisted transcript.
            new_landscape = await _refresh_landscape(idea=idea, result=result)
            if new_landscape is not None:
                landscape = new_landscape

        if landscape is None or not landscape.competitors:
            raise click.ClickException(
                f"No landscape available for verdict@{bare[:12]} even after refresh."
            )

        # Reuse the existing landscape renderer.
        console.print(_landscape_section(landscape))
        short = _short_hash(result) if result.verdict_hash else bare[:12]
        console.print()
        console.print(f"[dim]  Landscape from verdict@{short}  ·  $1.00 (V1.5 paywall)[/dim]")

    try:
        asyncio.run(_run())
    except click.ClickException:
        raise
    except Exception as exc:  # pragma: no cover — defensive
        raise click.ClickException(f"bb competitors_landscape failed: {exc}") from exc


async def _refresh_landscape(
    *,
    idea: str,
    result: object,
) -> MarketLandscape | None:
    """Re-call market_landscape (or _standalone variant when present).

    Falls back to ``None`` on any failure so the caller surfaces the
    "no landscape available" error rather than a stack trace.
    """
    import json
    import logging

    from gecko_core.models import MarketLandscape, ResearchResult
    from gecko_core.orchestration.pro.post_processors import _build_client
    from gecko_core.orchestration.pro.prompts import (
        _BUNDLED_VERSIONS,
        load_post_processors,
    )

    logger = logging.getLogger(__name__)

    if not isinstance(result, ResearchResult):
        return None

    # Prefer the standalone variant if ai-ml-engineer shipped it; else fall
    # back to the in-debate `market_landscape` post-processor.
    bundle = json.loads(_BUNDLED_VERSIONS["v5.5"].read_text(encoding="utf-8"))
    standalone = bundle.get("market_landscape_standalone")
    if isinstance(standalone, str) and standalone.strip():
        system = standalone.strip()
    else:
        try:
            system = load_post_processors()["market_landscape"]
        except Exception as exc:
            logger.warning("market_landscape prompt unavailable: %s", exc)
            return None

    transcript_text = ""
    if isinstance(result.transcript, dict):
        turns = result.transcript.get("turns")
        if isinstance(turns, list):
            transcript_text = "\n\n".join(
                f"### {t.get('agent')}\n{t.get('content')}" for t in turns if isinstance(t, dict)
            )

    user = (
        f"Idea: {idea}\n\n"
        f"Verdict: {result.verdict.value}\n\n"
        f"Debate transcript:\n{transcript_text or '(none)'}\n\n"
        "Respond with the JSON object specified in the system message."
    )

    client = _build_client()
    try:
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
    except Exception as exc:
        logger.warning("competitors_landscape refresh call failed: %s", exc)
        await client.close()
        return None
    await client.close()

    content = resp.choices[0].message.content
    if not content:
        return None
    try:
        raw = json.loads(content)
        landscape = MarketLandscape.model_validate(raw)
    except Exception as exc:
        logger.warning("competitors_landscape refresh validation failed: %s", exc)
        return None

    # Best-effort persistence — same pattern as refine.persist_refinement.
    try:
        from uuid import UUID

        from gecko_core.persistence import update_result_payload

        updated = result.model_copy(update={"market_landscape": landscape})
        await update_result_payload(
            UUID(updated.session_id),
            updated.model_dump(mode="json"),
        )
    except Exception as exc:
        logger.warning("competitors_landscape refresh persistence failed: %s", exc)

    return landscape


__all__ = ["competitors_landscape_cmd"]
