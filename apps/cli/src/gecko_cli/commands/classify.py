"""`gecko classify` — show category scores for an idea.

Free, local introspection of the embedding-NN classifier. No payment, no
session created. Useful for debugging "why did this idea fire source X?"
"""

from __future__ import annotations

import asyncio

import click
from rich.console import Console
from rich.table import Table

console = Console()


@click.command("classify")
@click.option(
    "--idea",
    "idea_opt",
    default=None,
    help="Plain-language startup idea to classify (alternative to positional argument).",
)
@click.argument("idea_arg", required=False)
def classify_cmd(idea_opt: str | None, idea_arg: str | None) -> None:
    """Classify an idea and print per-category cosine scores.

    S13-COMMO-03: also prints the suggested-source list + per-source
    priority weights — the same JSON the paid `POST /classify` route
    returns. Free locally; only the HTTP surface charges.

    Accepts either positional (`bb classify "an idea"`) or
    `--idea "an idea"` for parity with the MCP/HTTP shape.
    """
    # Imported lazily so the CLI startup path doesn't load numpy / openai
    # for unrelated commands.
    from gecko_core.classify import classify_idea_with_scores, suggest_sources

    idea = idea_opt or idea_arg
    if not idea:
        raise click.UsageError("provide an idea either as positional argument or --idea")

    selected, scores = asyncio.run(classify_idea_with_scores(idea))
    selected_set = set(selected)

    table = Table(title="Idea classification")
    table.add_column("Category")
    table.add_column("Score", justify="right")
    table.add_column("Selected", justify="center")
    # Sort by score desc so the table reads top-down.
    for cat, sim in sorted(scores.items(), key=lambda kv: kv[1], reverse=True):
        marker = "yes" if cat in selected_set else ""
        table.add_row(cat, f"{sim:.3f}", marker)
    console.print(table)
    console.print(f"[dim]selected: {selected or '(none)'}[/dim]")

    # S13-COMMO-03 — also surface the suggested-source list. Mirrors the
    # paid /classify HTTP response so users can dry-run the SKU locally.
    suggested, weights = suggest_sources(scores)
    src_table = Table(title="Suggested sources (priority weights)")
    src_table.add_column("Source")
    src_table.add_column("Weight", justify="right")
    for s in suggested:
        src_table.add_row(s, f"{weights.get(s, 0.0):.3f}")
    console.print(src_table)
