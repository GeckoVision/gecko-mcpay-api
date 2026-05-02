"""Gecko core SDK — Builder Bootstrap Platform business logic.

Public API:
    research(idea: str, *, tier: Tier = "basic", urls: list[str] | None = None) -> ResearchResult
    ask(session_id: str, question: str) -> AskResult
    sources(session_id: str) -> list[SourceInfo]

Everything else is internal — CLI, MCP, and API call only these three functions.
"""

# S17-WEDGE-WIRE-02 — repair the ``gecko_core.sources`` parent-attribute
# binding. The ``from gecko_core.workflows import ... sources`` above
# rebinds the name ``sources`` on this package to the *function*
# ``workflows.sources`` (kept for backward compat: callers do
# ``await gecko_core.sources(session_id)``). That shadows the
# ``gecko_core.sources`` *package* attribute, which Python's import
# machinery uses to resolve ``import gecko_core.sources.X`` —
# everything blew up with ``ImportError: cannot import name 'X' from
# 'list_sources'`` once data-eng's S17-WEDGE-DATA-01 forced the package
# to load early via ``from gecko_core.sources.types import ProviderKind``.
#
# Fix: explicitly hang the live submodules off the function so the
# parent-attribute lookup finds them. ``import gecko_core.sources.arxiv``
# now resolves ``arxiv`` via ``getattr(gecko_core.sources, 'arxiv')``,
# which we satisfy by attaching the actual sub-module objects to the
# function. The function still works as ``gecko_core.sources(session_id)``.
# When data-eng commits the migration this hack can move out — the
# right end-state is renaming the workflow function to e.g.
# ``list_session_sources`` and exporting the package directly.
import importlib as _importlib
import sys as _sys

from gecko_core.models import (
    AskResult,
    ResearchResult,
    SourceInfo,
    Tier,
)
from gecko_core.workflows import ask, list_sources, research, sources

# Force the canonical ``sources`` package into sys.modules — note we
# don't bind it as a name in this module (that's the whole point: keep
# ``gecko_core.sources`` as the function for backward compat).
_importlib.import_module("gecko_core.sources")
_sources_pkg = _sys.modules["gecko_core.sources"]

# Hang every direct submodule of the sources package off the
# ``sources`` *function* so Python's submodule-resolution
# (``getattr(parent, attr)`` during ``import a.b.c``) finds them.
for _short in (
    "_catalog",
    "arxiv",
    "bazaar",
    "dispatcher",
    "gecko_precedent",
    "github",
    "hn",
    "pdf",
    "reddit",
    "twit_sh",
    "twitsh_circuit",
    "types",
    "v1_block",
):
    try:
        _mod = _importlib.import_module(f"gecko_core.sources.{_short}")
    except ImportError:
        continue
    setattr(sources, _short, _mod)
del _importlib, _sys, _sources_pkg, _mod, _short

__all__ = [
    "AskResult",
    "ResearchResult",
    "SourceInfo",
    "Tier",
    "ask",
    "list_sources",
    "research",
    "sources",
]
