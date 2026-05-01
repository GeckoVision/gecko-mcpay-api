"""Provider router — pure-function build of a per-session provider plan.

Sprint 14 S14-TWITSH-01: minimum viable router that takes a classifier's
``category`` output + the raw idea string and returns the list of
``SourceProvider`` instances the dispatcher should fan out across.

Today the only S14 routing rule we need is the Colosseum-judge filter:

  if category in {crypto, defi, hackathon-team}
       AND idea matches Solana keyword regex:
     plan += TwitshProvider(author_allowlist=COLOSSEUM_JUDGES)
  elif category in {crypto, defi, hackathon-team}:
     plan += TwitshProvider()      # unfiltered

The free Tavily-backed FreeProvider is always included (no router gate).
Other paid providers (ParagraphProvider, etc.) are wired in by their
respective tickets — this module's surface is intentionally tiny so the
addition of more rules stays a one-liner.

The ``TWITSH_RESEARCH_ENABLED`` flag is checked inside ``TwitshProvider``
itself (via ``health()`` and ``fetch()``); the router does not duplicate
the gate. The router's job is _shape_, not feature-flag enforcement.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from .free_provider import DEFAULT_FREE_PROVIDER

if TYPE_CHECKING:
    from . import SourceProvider


# Categories where twit.sh is worth paying for. Mirrors the source-side
# `_FIRES_FOR` constant; kept duplicated to avoid an ingestion → sources
# import back-edge from the router (sources/__init__.py is import-order
# sensitive; see the dispatcher.py docstring).
_TWITSH_CATEGORIES: frozenset[str] = frozenset({"crypto", "defi", "hackathon-team"})

# Solana-adjacent keyword regex. Matches whole tokens, case-insensitive.
# Word-boundary (\b) keeps "renaissance" from accidentally matching
# longer English words that happen to contain the substring.
_SOLANA_KEYWORD_RE = re.compile(
    r"\b(solana|colosseum|breakpoint|radar|cypherpunk|breakout|renaissance)\b",
    re.IGNORECASE,
)


def _matches_solana_keywords(idea: str) -> bool:
    return bool(_SOLANA_KEYWORD_RE.search(idea or ""))


def build_provider_plan(
    *,
    idea: str,
    category: str | None,
) -> list[SourceProvider]:
    """Return the ordered provider list for a session.

    FreeProvider is always first (cheapest, broadest); paid providers
    follow per the routing rules. Order matters for the dispatcher's
    budget-pre-check (S13+ Track F): cheaper providers run first so the
    per-session cap is consumed predictably.
    """
    plan: list[SourceProvider] = [DEFAULT_FREE_PROVIDER]

    cat = (category or "").strip().lower()
    if cat in _TWITSH_CATEGORIES:
        # Lazy import: keeps the router importable without forcing the
        # twit.sh deps (httpx/x402) into every Gecko import path.
        from .twitsh_provider import TwitshProvider, load_colosseum_judges

        if _matches_solana_keywords(idea):
            allowlist = load_colosseum_judges()
            # Empty allowlist (file missing or all cycles drained) →
            # fall through to unfiltered. Better to surface signal than
            # silently emit zero citations from the provider.
            if allowlist:
                plan.append(TwitshProvider(author_allowlist=allowlist))
            else:
                plan.append(TwitshProvider())
        else:
            plan.append(TwitshProvider())

    return plan


__all__ = ["build_provider_plan"]
