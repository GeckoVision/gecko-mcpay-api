"""Shared interactive-prompt helpers.

Top-level CLI flags `--yes/-y` and `--non-interactive` are stashed on the
Click context (`ctx.obj`). Anything that wants to prompt the user should go
through `confirm()` here so the bypass propagates uniformly.
"""

from __future__ import annotations

import click
from rich.prompt import Confirm


class NonInteractiveError(click.ClickException):
    """Raised when a prompt fires under --non-interactive."""

    exit_code = 2


def _flags(ctx: click.Context | None) -> tuple[bool, bool]:
    """Return (yes, non_interactive) from the root context, defaulting to False."""
    if ctx is None:
        return False, False
    root = ctx.find_root()
    obj = root.obj or {}
    return bool(obj.get("yes")), bool(obj.get("non_interactive"))


def is_non_interactive(ctx: click.Context | None = None) -> bool:
    ctx = ctx or click.get_current_context(silent=True)
    _, ni = _flags(ctx)
    return ni


def assume_yes(ctx: click.Context | None = None, *, local: bool = False) -> bool:
    """True if any of: command-local --yes, top-level --yes, --non-interactive."""
    ctx = ctx or click.get_current_context(silent=True)
    yes, ni = _flags(ctx)
    return local or yes or ni


def confirm(
    message: str,
    *,
    default: bool = True,
    ctx: click.Context | None = None,
    local_yes: bool = False,
) -> bool:
    """Ask y/n, honoring top-level --yes / --non-interactive.

    - `local_yes=True` mirrors a per-command --yes flag.
    - Under --non-interactive, returns `default` without prompting; if `default`
      is False, errors out (the caller wanted a real answer).
    """
    ctx = ctx or click.get_current_context(silent=True)
    yes, ni = _flags(ctx)
    # Strict mode wins: a destructive prompt (default=False) must not be
    # silently auto-confirmed even if --yes is also set.
    if ni and not default:
        raise NonInteractiveError(f"Refusing to prompt under --non-interactive: {message!r}")
    if local_yes or yes or ni:
        return True
    return Confirm.ask(message, default=default)
