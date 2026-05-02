"""Self-citation guard (S20-SELF-CITATION-GUARD-01).

When Gecko researches an idea on its own roadmap (e.g. "tradeable judgment as
product — paid x402 paywall on verdict URLs"), the corpus is biased toward
Gecko's own writing. The verdict comes back GO with circular citations:
Gecko cites Gecko cites Gecko. Stress-matrix #5 in
``docs/sprint-reviews/2026-05-02-s18-s19-review.md`` §5 caught this.

This module:
  1. Identifies "is the idea about Gecko's own product space?" via a
     deterministic substring keyword match. No LLM call — cheap, stable,
     auditable.
  2. Identifies "is this chunk a self-citation?" via case-insensitive
     substring match on the chunk's source URL host against a known set of
     Gecko-owned domains and repos.

The guard is a *down-weight*, not a filter. A small minority of
self-references is fine and may be the only relevant prior art; we just
strip the structural advantage of self-citation circularity by halving
the post-boost similarity when the idea-side trigger fires.

Downstream identity implication: down-weighting self-citation chunks
changes which chunks survive into the final slate, which changes the
``sources`` field on ``ResearchResult``, which changes the verdict-hash
fingerprint. That is *correct* behavior — same idea producing a different
citation set should produce a different hash. No change required to
``verdict_hash.py``.
"""

from __future__ import annotations

# Gecko-owned domains and repository paths. Match is case-insensitive
# substring on the URL string, so subdomains and path prefixes both hit.
# Sourced from `git remote -v` (origin = github.com/ernanibmurtinho/gecko-mcpay-api)
# plus the sister repos referenced in CLAUDE.md and the production domain.
GECKO_SELF_DOMAINS: frozenset[str] = frozenset(
    {
        "app.geckovision.tech",
        "geckovision.tech",
        "github.com/ernanibmurtinho/gecko-mcpay-api",
        "github.com/ernanibmurtinho/gecko-mcpay-app",
        "github.com/ernanibmurtinho/gecko-claude",
        "github.com/ernanibmurtinho/gecko-mcpay-skills",
    }
)

# Multiplicative down-weight applied to the boosted similarity of any chunk
# whose source URL resolves to a Gecko-owned domain when the idea is itself
# about Gecko's product space. 0.5 chosen to neutralize the largest provider
# boost (bazaar 1.15) and still leave self-citations as a tiebreaker rather
# than a top-of-slate fixture.
SELF_CITATION_DOWNWEIGHT: float = 0.5

# Curated keyword set. Trade-off: recall (false-positive trigger on adjacent
# topics) vs precision (don't down-weight legitimate research). We err on
# the side of precision — these are phrases distinctive enough to Gecko's
# product space that a non-Gecko idea is unlikely to use them in passing.
#   - "gecko"               — direct mention of the product name
#   - "tradeable judgment"  — wedge phrase from the v5.x thesis
#   - "tradeable verdict"   — variant
#   - "verdict url"         — references the paywalled-verdict surface
#   - "x402 paywall on verdict" — distinctive Gecko-roadmap phrase
#   - "judgment as product" — wedge framing
#   - "paywall research"    — "paid research outputs" is Gecko's wedge
# Substring + case-insensitive. Single-word triggers like "verdict" alone
# are deliberately NOT in the set — too many legitimate ideas mention
# verdicts without being about Gecko.
_SELF_REFERENTIAL_KEYWORDS: tuple[str, ...] = (
    "gecko",
    "tradeable judgment",
    "tradeable verdict",
    "verdict url",
    "x402 paywall on verdict",
    "judgment as product",
    "paywall research",
)


def is_self_citation(source_url: str) -> bool:
    """Return True if ``source_url`` resolves to a Gecko-owned domain or repo.

    Case-insensitive substring match on the URL. Non-https schemes (e.g.
    ``bazaar://``, ``twitsh://``) cannot be Gecko-owned by definition —
    those are external structured-provider URIs whose authority is owned
    by the respective network, not Gecko. Returns False for them without
    further inspection.
    """
    if not source_url:
        return False
    lowered = source_url.lower()
    if not (lowered.startswith("http://") or lowered.startswith("https://")):
        return False
    return any(domain in lowered for domain in GECKO_SELF_DOMAINS)


def is_self_referential_idea(idea: str) -> bool:
    """Return True if the idea string mentions Gecko's own product space.

    Pure substring, case-insensitive. Returns True if at least one keyword
    from ``_SELF_REFERENTIAL_KEYWORDS`` hits. See module docstring and
    keyword-set comment for the precision/recall trade-off.
    """
    if not idea:
        return False
    lowered = idea.lower()
    return any(kw in lowered for kw in _SELF_REFERENTIAL_KEYWORDS)


__all__ = [
    "GECKO_SELF_DOMAINS",
    "SELF_CITATION_DOWNWEIGHT",
    "is_self_citation",
    "is_self_referential_idea",
]
