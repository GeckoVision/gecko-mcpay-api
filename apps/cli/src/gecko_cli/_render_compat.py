"""Render-symbol shim.

The Phase 7 renderer (`gecko_cli.render`) is owned by the product-designer
agent. We import its symbols here so command modules don't have to deal with
the try/except dance, and so a partial / missing renderer doesn't break the
CLI for the demo.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from rich.console import Console

from gecko_cli.render import (
    render_ask_result as _render_ask_result,
)
from gecko_cli.render import (
    render_research_result as _render_research_result,
)
from gecko_cli.render import (
    render_sources_table as _render_sources_table,
)

# TODO Phase 7: replace this with `from gecko_cli.render import progress_context`
# once the renderer agent ships it. Until then we fall back to a tiny shim so
# the CLI still renders progress lines.
_progress_context: Any = None
HAS_PROGRESS = False


def render_research_result(console: Console, result: Any) -> None:
    _render_research_result(result, console)


def render_ask_result(console: Console, result: Any) -> None:
    _render_ask_result(result, console)


def render_sources_table(console: Console, sources: Any) -> None:
    _render_sources_table(sources, console)


@contextmanager
def progress_context(console: Console, label: str) -> Any:
    # TODO Phase 7: replace with the renderer's real progress context.
    if HAS_PROGRESS and _progress_context is not None:
        with _progress_context(console, label) as p:
            yield p
        return

    class _Fallback:
        def update(self, msg: str) -> None:
            console.print(f"[dim]· {msg}[/dim]")

    console.print(f"[bold]{label}[/bold]")
    yield _Fallback()


__all__ = [
    "progress_context",
    "render_ask_result",
    "render_research_result",
    "render_sources_table",
]
