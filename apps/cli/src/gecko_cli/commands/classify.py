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
@click.argument("idea")
def classify_cmd(idea: str) -> None:
    """Classify an idea and print per-category cosine scores."""
    # Imported lazily so the CLI startup path doesn't load numpy / openai
    # for unrelated commands.
    from gecko_core.classify import classify_idea_with_scores

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
