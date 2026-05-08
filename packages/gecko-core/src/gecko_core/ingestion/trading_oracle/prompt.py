"""Curated prompt + listing filter for the trading-oracle ingest run.

Scope: Solana DeFi only. Multi-chain and CEX-news scope deliberately
excluded — see docs/superpowers/specs/2026-05-08-trading-oracle-reference-skill-design.md §4.
"""

from __future__ import annotations

from collections.abc import Mapping

SOLANA_DEFI_PROTOCOLS: tuple[str, ...] = (
    "Jupiter",
    "Kamino",
    "Jito",
    "Pyth",
    "Drift",
    "Orca",
    "Raydium",
    "Meteora",
    "MarginFi",
    "Sanctum",
)

TRADING_ORACLE_PROTOCOLS_V1: tuple[str, ...] = (
    "Jupiter",
    "Kamino",
    "Pyth",
    "Drift",
    "Jito",
)


def prompt_for_protocol(protocol: str) -> str:
    """Single-protocol variant of TRADING_ORACLE_PROMPT.

    Used by the per-protocol ingest loop so each call's response is
    scoped to one protocol's facts. The returned string has the same
    shape as TRADING_ORACLE_PROMPT but names ONE protocol — so the
    answer LLM stays focused and the resulting chunks are unambiguously
    taggable with protocol=[<name>].
    """
    p = protocol.strip()
    if not p:
        raise ValueError("protocol cannot be empty")
    return (
        f"Acting as a Solana DeFi trading research oracle: for the protocol "
        f"{p}, retrieve and summarize current operational facts that affect "
        f"a trader's decision-making — pool TVL trends, fee tiers, oracle "
        f"staleness windows, recent governance / parameter changes, audit "
        f"status, known incident history within the last 90 days, and "
        f"integration partners. Cite source per fact. Do not produce trade "
        f"recommendations; produce parameters a trader's agent needs to reason."
    )


TRADING_ORACLE_PROMPT: str = (
    "Acting as a Solana DeFi trading research oracle: for the protocols "
    + ", ".join(SOLANA_DEFI_PROTOCOLS)
    + ", retrieve and summarize current operational facts that affect a trader's "
    "decision-making — pool TVL trends, fee tiers, oracle staleness windows, "
    "recent governance / parameter changes, audit status, known incident history "
    "within the last 90 days, and integration partners. Cite source per fact. "
    "Do not produce trade recommendations; produce parameters a trader's agent "
    "needs to reason."
)

_SOLANA_TOKENS = ("solana", "spl", "anchor")
_DEFI_TOKENS = (
    "defi",
    "dex",
    "lending",
    "lst",
    "perp",
    "perps",
    "oracle",
    "liquidity",
    "amm",
    "staking",
    "yield",
)
_EVM_REJECT_TOKENS = (
    "ethereum",
    "evm",
    "arbitrum",
    "base",
    "polygon",
    "bsc",
    "optimism",
    "avalanche",
)

# Bazaar/paysh service IDs that are research-LLMs — they take free-text and
# return grounded answers, which is exactly what TRADING_ORACLE_PROMPT
# wants. Bypass the Solana-DeFi listing filter for these. The filter was
# designed for *data-feed* listings; research-LLMs are a different category
# better-judged by their *output*, not their *metadata*.
TRADING_ORACLE_RESEARCH_LLM_FQNS: frozenset[str] = frozenset(
    {
        "docs-perplexity-ai",  # Perplexity, Base, $0.01-$0.10
        "docs-anthropic-com",  # Claude, Base, $0.001-$10
        "deepseek-com",  # DeepSeek, Base, $0.001-$10
        "exa-ai",  # Exa AI search, Base, $0.001-$0.015
        "platform-openai-com",  # ChatGPT, Base, $0.001-$10
        "paysponge/perplexity",  # paysh's Perplexity wrapper
    }
)


# Known false-positive tokens. These listings substring-match the DeFi
# token list (e.g. AirQuality "AQI" + tag "oracle") but have nothing to
# do with Solana DeFi. Anything matching here short-circuits to reject
# before the DeFi-substring path runs.
_REJECT_TOKENS = (
    "email",
    "inbox",
    "smtp",
    "air quality",
    "weather",
    "captcha",
    "screenshot",
    "domain",
)


def _haystack(listing: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in ("name", "description"):
        v = listing.get(key)
        if isinstance(v, str):
            parts.append(v)
    tags = listing.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    proto_match = any(p.lower() in " ".join(parts).lower() for p in SOLANA_DEFI_PROTOCOLS)
    if proto_match:
        parts.append("__protocol_match__")
    return " ".join(parts).lower()


def is_solana_defi_relevant(listing: Mapping[str, object]) -> bool:
    # Research-LLM allowlist: these services take free-text and return
    # grounded answers, which fits TRADING_ORACLE_PROMPT directly. Skip
    # the metadata-based Solana-DeFi filter for them.
    fqn = listing.get("fqn")
    if isinstance(fqn, str) and fqn in TRADING_ORACLE_RESEARCH_LLM_FQNS:
        return True
    h = _haystack(listing)
    # Reject known false-positives BEFORE the DeFi-substring path runs.
    # AgentMail (email) matches "oracle" via vendor description; AirQuality
    # API matches via "AQI"-adjacent description. Both are paysh-only and
    # irrelevant to Solana DeFi trading.
    if any(t in h for t in _REJECT_TOKENS):
        return False
    if any(t in h for t in _EVM_REJECT_TOKENS) and not any(s in h for s in _SOLANA_TOKENS):
        return False
    if "__protocol_match__" in h:
        return True
    has_solana = any(t in h for t in _SOLANA_TOKENS)
    has_defi = any(t in h for t in _DEFI_TOKENS)
    return has_solana and has_defi
