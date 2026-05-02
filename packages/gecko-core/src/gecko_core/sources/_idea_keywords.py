"""Idea-aware keyword templating for stub fixtures (S19-STUB-FIXTURES-01).

Pure string templating — no LLM calls, no network. Used by Bazaar
discovery's stub backend and twit.sh's stub tweet synthesizer to
produce citations whose surface text references the idea-on-screen
rather than canned boilerplate (Lisbon hotel for every research run).

The bar this raises is *demo realism*, not retrieval quality. The
reach-CI test from S18 still owns "non-web chunks reach the ingest
seam"; this module owns "the chunk text doesn't read as fake when a
viewer screenshots the demo."

Lookup is intentionally tiny: a small fixed bucket table (crypto,
saas, hospitality, productivity, generic). New verticals just append a
bucket. The "no-keyword-matches" path falls through to the generic
bucket so reach-CI never sees an empty stub result.
"""

from __future__ import annotations

import re

# Stopwords intentionally broad — we want the *topical* tokens to win.
# Bucket category names — drop from idea tokenization so e.g. an idea
# "a focus tracker" with category={"productivity"} keys off "focus"
# rather than "productivity" (which is the bucket name, not a topical
# keyword from the user's idea string).
_BUCKET_NAME_STOPWORDS: frozenset[str] = frozenset(
    {"crypto", "saas", "hospitality", "productivity", "generic"}
)

_STOPWORDS: frozenset[str] = frozenset(
    {
        "the", "a", "an", "and", "or", "but", "for", "to", "of", "in",
        "on", "with", "is", "are", "was", "were", "be", "been", "by",
        "at", "from", "this", "that", "these", "those", "it", "its",
        "as", "into", "than", "new", "app", "apps", "tool", "tools",
        "platform", "service", "system", "build", "make", "create",
        "user", "users", "people", "team", "teams",
        "use", "using", "used", "via", "over", "about", "more", "less",
        "some", "any", "one", "two", "three", "many", "few", "all",
        "each", "every", "do", "does", "did", "doing", "done", "have",
        "has", "had", "having", "will", "would", "should", "could",
        "can", "may", "might", "must", "shall", "i", "you", "we",
        "they", "he", "she", "them", "us", "him", "her",
    }
)  # fmt: skip


# Bucket → (category_slug, [example service titles], [tweet hooks]).
# Buckets are matched in the order keys appear in `_BUCKET_KEYWORDS`;
# first hit wins. The trailing "generic" bucket is the fallback so we
# never return an empty stub.
_BUCKETS: dict[str, dict[str, list[str]]] = {
    "crypto": {
        "categories": ["crypto-onramp", "agentic-payments", "x402-tools"],
        "service_titles": [
            "{kw} onramp",
            "{kw} settlement API",
            "x402 {kw} oracle",
        ],
        "tweet_hooks": [
            "agentic markets are eating {kw}",
            "x402 makes {kw} pay-per-call viable for the first time",
            "the {kw} stack just got an HTTP-native settlement layer",
        ],
        "merchants": ["Coinbase", "Helius", "Pyth"],
    },
    "saas": {
        "categories": ["saas-onboarding", "developer-productivity"],
        "service_titles": [
            "{kw} onboarding API",
            "{kw} workflow automation",
            "{kw} analytics dashboard",
        ],
        "tweet_hooks": [
            "every {kw} team is rebuilding the same onboarding flow",
            "the {kw} tooling gap is bigger than people admit",
            "{kw} infra is undermonetized",
        ],
        "merchants": ["Linear", "Notion", "Vercel"],
    },
    "hospitality": {
        "categories": ["hotel-guides", "travel-onramps"],
        "service_titles": [
            "{kw} local guide API",
            "{kw} concierge content",
            "{kw} review aggregator",
        ],
        "tweet_hooks": [
            "the {kw} guidebook category is wide open for AI",
            "every {kw} on Booking has the same generic blurb",
            "{kw} content is the moat travel platforms forgot",
        ],
        "merchants": ["Tripadvisor", "Amadeus", "orbisapi"],
    },
    "productivity": {
        "categories": ["productivity-tools", "personal-knowledge"],
        "service_titles": [
            "{kw} note capture API",
            "{kw} focus tracker",
            "{kw} digest generator",
        ],
        "tweet_hooks": [
            "{kw} apps keep solving the wrong problem",
            "AI-native {kw} is finally clicking",
            "the {kw} space is overdue for a rewrite",
        ],
        "merchants": ["Linear", "Cron", "Readwise"],
    },
    "generic": {
        "categories": ["agentic-services"],
        "service_titles": [
            "{kw} discovery API",
            "agentic {kw} index",
            "{kw} signal feed",
        ],
        "tweet_hooks": [
            "agentic markets are eating {kw}",
            "{kw} buyers will be agents before humans",
            "the {kw} category is going pay-per-call",
        ],
        "merchants": ["Bazaar", "Agentic", "x402"],
    },
}


# Keyword → bucket. First match wins. Order matters (more-specific
# verticals listed before "saas" so e.g. "hotel" routes to hospitality
# rather than the generic SaaS bucket).
_BUCKET_KEYWORDS: list[tuple[str, str]] = [
    # crypto / web3
    ("crypto", "crypto"), ("defi", "crypto"), ("solana", "crypto"),
    ("ethereum", "crypto"), ("wallet", "crypto"), ("token", "crypto"),
    ("onchain", "crypto"), ("on-chain", "crypto"), ("x402", "crypto"),
    ("agentic", "crypto"), ("payment", "crypto"), ("payments", "crypto"),
    ("usdc", "crypto"), ("stablecoin", "crypto"),
    # hospitality / travel
    ("hotel", "hospitality"), ("hotels", "hospitality"),
    ("travel", "hospitality"), ("trip", "hospitality"),
    ("tourism", "hospitality"), ("guide", "hospitality"),
    ("guides", "hospitality"), ("airbnb", "hospitality"),
    ("booking", "hospitality"), ("city", "hospitality"),
    ("concierge", "hospitality"), ("local", "hospitality"),
    # saas / dev tools
    ("saas", "saas"), ("api", "saas"), ("developer", "saas"),
    ("devtool", "saas"), ("devtools", "saas"), ("onboarding", "saas"),
    ("dashboard", "saas"), ("analytics", "saas"), ("workflow", "saas"),
    # productivity
    ("productivity", "productivity"), ("notes", "productivity"),
    ("note", "productivity"), ("calendar", "productivity"),
    ("focus", "productivity"), ("knowledge", "productivity"),
    ("journal", "productivity"), ("habit", "productivity"),
]  # fmt: skip


def tokenize(idea: str) -> list[str]:
    """Lowercase tokenize, drop stopwords, dedupe, prefer longer tokens."""
    if not idea:
        return []
    raw = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{1,}", idea.lower())
    seen: set[str] = set()
    keep: list[str] = []
    for tok in sorted(raw, key=len, reverse=True):
        if tok in _STOPWORDS or tok in seen:
            continue
        seen.add(tok)
        keep.append(tok)
    return keep


def pick_bucket(idea: str, categories: set[str] | None = None) -> str:
    """Return the bucket name for an idea/category pair.

    Order: explicit category override (e.g. "crypto" in categories) wins,
    then idea tokens are scanned against `_BUCKET_KEYWORDS`. Fallback
    bucket is "generic" so the synthesizer always has something to emit.
    """
    cats = {c.lower() for c in (categories or set())}
    # Category override — keeps the classify_idea hint in the loop so
    # an idea like "a tool" under category {"crypto"} routes correctly.
    for c in cats:
        for kw, bucket in _BUCKET_KEYWORDS:
            if kw == c:
                return bucket
    tokens = set(tokenize(idea))
    for kw, bucket in _BUCKET_KEYWORDS:
        if kw in tokens:
            return bucket
    return "generic"


def top_keywords(idea: str, *, n: int = 3) -> list[str]:
    """The top-N topical tokens from the idea.

    Used to template service titles / tweet bodies. Filters bucket
    names ("productivity", "saas", ...) so the templated text reads
    as a quote of the user's idea, not a paraphrase of the bucket
    label. Always returns at least one keyword so callers never
    have to handle an empty list.
    """
    toks = [t for t in tokenize(idea) if t not in _BUCKET_NAME_STOPWORDS]
    toks = toks[:n]
    return toks or ["agentic"]


def bucket_payload(bucket: str) -> dict[str, list[str]]:
    """Return the bucket's templating dict."""
    return _BUCKETS.get(bucket) or _BUCKETS["generic"]


__all__ = [
    "bucket_payload",
    "pick_bucket",
    "tokenize",
    "top_keywords",
]
