"""`bb refine <verdict_hash>` — V1.5 idea-refinement command.

Loads a saved verdict by content-addressed hash, asks the v5.5
``refine_idea`` prompt for a sharpened/narrowed/pivoted version, persists
the refinement back to the verdict, and renders it.

Pricing line in the footer is informational — V1.5 does NOT actually
paywall (the spec is explicit: "don't actually paywall in this PR").
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console

console = Console()


_HASH_VALID_LENGTHS = {12, 64}


def _normalise_hash(raw: str) -> str:
    """Accept ``verdict@<hex>`` or bare hex; return bare hex."""
    s = raw.strip()
    if s.startswith("verdict@"):
        s = s[len("verdict@") :]
    return s


@click.command("refine")
@click.argument("verdict_hash", type=str)
def refine_cmd(verdict_hash: str) -> None:
    """Refine the idea behind VERDICT_HASH (12-hex short or 64-hex full)."""
    from gecko_core.persistence import (
        VerdictNotFoundError,
        load_by_verdict_hash_async,
    )
    from gecko_core.refine import RefineError, persist_refinement, refine_idea

    from gecko_cli.render import _render_refine

    bare = _normalise_hash(verdict_hash)
    if len(bare) not in _HASH_VALID_LENGTHS:
        raise click.BadParameter(
            f"verdict hash must be 12 or 64 hex characters (got {len(bare)}). "
            "Run `bb research ...` first; the footer prints `verdict@<12hex>`."
        )

    async def _run() -> None:
        try:
            result, idea = await load_by_verdict_hash_async(bare)
        except VerdictNotFoundError as exc:
            raise click.ClickException(str(exc)) from exc

        try:
            refinement = await refine_idea(idea, result)
        except RefineError as exc:
            raise click.ClickException(str(exc)) from exc

        updated = await persist_refinement(result=result, refinement=refinement)
        short = (updated.verdict_hash or bare)[:12]
        _render_refine(refinement, short_hash=short, console=console)

    try:
        asyncio.run(_run())
    except click.ClickException:
        raise
    except Exception as exc:  # pragma: no cover — defensive
        raise click.ClickException(f"bb refine failed: {exc}") from exc


__all__ = ["refine_cmd"]
