"""`gecko route` — route an LLM call through the Gecko x402 router (S3-05).

CLI mirror of the `gecko_route` MCP tool. Prints the response plus a
Rich-formatted cost panel showing the savings vs the premium tier so the
demo lands every invocation.
"""

from __future__ import annotations

import asyncio
import os

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()

_VALID_HINTS = ("reasoning", "code", "extraction", "summary", "default")


@click.command("route")
@click.argument("prompt")
@click.option(
    "--task-hint",
    type=click.Choice(_VALID_HINTS),
    default="default",
    show_default=True,
    help="Bias model selection for this kind of task.",
)
@click.option(
    "--max-cost",
    type=float,
    default=0.05,
    show_default=True,
    help="Per-call hard cap (USD). Downshifts to a cheaper model if needed.",
)
@click.option(
    "--prefer-premium",
    is_flag=True,
    default=False,
    help="Prefer the premium-tier column of the routing matrix.",
)
def route_cmd(prompt: str, task_hint: str, max_cost: float, prefer_premium: bool) -> None:
    """Route an LLM call through Gecko's cost-aware x402 router."""
    # Lazy import — keeps `gecko --help` fast and avoids pulling openai
    # for unrelated commands.
    from gecko_core.routing import RouteBudgetError, RoutePaymentError, route
    from gecko_core.routing.matrix import TaskHint  # noqa: F401  (annotation-only)

    # Enable the one-line demo log on stdout when invoked from the CLI.
    os.environ["GECKO_ROUTE_LOG"] = "1"

    try:
        result = asyncio.run(
            route(
                prompt,
                task_hint=task_hint,  # type: ignore[arg-type]
                max_cost_usd=max_cost,
                prefer_premium=prefer_premium,
            )
        )
    except RouteBudgetError as exc:
        console.print(f"[red]budget exceeded:[/red] {exc}")
        raise SystemExit(2) from exc
    except RoutePaymentError as exc:
        console.print(f"[red]payment failed:[/red] {exc}")
        raise SystemExit(3) from exc

    # Response body first, then the cost panel.
    console.print(Panel(result.response or "[dim](empty response)[/dim]", title="response"))

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("k", style="dim")
    table.add_column("v")
    table.add_row("model_used", result.model_used)
    table.add_row("cost_usd", f"${result.cost_usd:.4f}")
    table.add_row("tokens_in", str(result.tokens_in))
    table.add_row("tokens_out", str(result.tokens_out))
    table.add_row("savings_vs_premium", f"${result.savings_vs_premium:.4f}")
    console.print(Panel(table, title="cost"))
