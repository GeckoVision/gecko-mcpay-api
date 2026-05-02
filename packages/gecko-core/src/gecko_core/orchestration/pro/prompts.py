"""Pro tier system-prompt loader.

Overview
--------

The 5 system prompts the AG2 GroupChat uses are loaded here, not hardcoded in
``agents.py``. This decouples the prompt content from the orchestration code so
the public OSS repo can ship working defaults while production runs a
privately-tuned set without code changes.

Resolution order:

1. ``GECKO_PROMPTS_PATH`` env var → JSON file at that path. Used in production
   to point at a privately-tuned prompts file (mounted via SSM, downloaded at
   container boot, etc.).
2. The bundled ``_default_prompts.json`` next to this module. Used in dev,
   tests, and the OSS install path. These are the prompts that public users
   get; they're real and tuned, not stubs.

The file format is::

    {
      "version": "v1",
      "agents": {
        "analyst":  "...",
        "critic":   "...",
        "architect":"...",
        "scoper":   "...",
        "judge":    "..."
      }
    }

Schema is enforced at load time — missing keys, empty strings, or wrong types
raise loudly so a bad override fails fast at boot rather than mid-debate.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

REQUIRED_AGENTS = ("analyst", "critic", "architect", "scoper", "judge")

# Bundled prompt versions. v5.4 is the current default — Judge + Critic
# rewrite to flip recency bias and stop quota-driven kill seeding after the
# v5.0→v5.3 accuracy slide (0.55 → 0.65 → 0.65 → 0.50 on
# tests/eval/live_runs/2026-04-28-general*.json). v5.4 collapses the brittle
# 12-entry STEP 2 keyword-trigger list to a single named-buyer + named-artifact
# rule, reorders the pipeline so STEP 3 is the DEFAULT SHIP (KILL becomes the
# last block read by gpt-4o-mini), trims STEP 4 from 13 triggers to 4 hard-kill
# triggers, and caps the Critic's kill-criteria quota. See
# docs/prompts/v5_4-changelog.md. v5.3 (Judge keyword-trigger structural fix —
# docs/prompts/v5_3-changelog.md), v5.2 (numbered execution pipeline —
# docs/prompts/v5_2-changelog.md), v5.1 (2026-04-28 regression fix —
# docs/prompts/v5_1-changelog.md), v5 (S2X-11 source weighting), and v4 are
# retained on disk as rollback targets — set GECKO_PRO_PROMPTS_VERSION=v5.3
# (or v5.2, v5.1, v5, v4) to pin a prior bundle without code changes.
_PROMPTS_DIR = Path(__file__).parent
_BUNDLED_VERSIONS: dict[str, Path] = {
    "v4": _PROMPTS_DIR / "_default_prompts.json",
    "v5": _PROMPTS_DIR / "_default_prompts_v5.json",
    "v5.1": _PROMPTS_DIR / "_default_prompts_v5_1.json",
    "v5.2": _PROMPTS_DIR / "_default_prompts_v5_2.json",
    "v5.3": _PROMPTS_DIR / "_default_prompts_v5_3.json",
    "v5.4": _PROMPTS_DIR / "_default_prompts_v5_4.json",
}
_DEFAULT_VERSION = "v5.4"
_DEFAULT_PROMPTS_PATH = _BUNDLED_VERSIONS[_DEFAULT_VERSION]


class PromptsConfigError(ValueError):
    """Raised when prompts JSON is missing keys, empty, or malformed."""


def _validate(data: dict[str, object]) -> dict[str, str]:
    agents = data.get("agents")
    if not isinstance(agents, dict):
        raise PromptsConfigError("prompts JSON must have a top-level 'agents' object")
    out: dict[str, str] = {}
    for name in REQUIRED_AGENTS:
        val = agents.get(name)
        if not isinstance(val, str) or not val.strip():
            raise PromptsConfigError(
                f"prompts JSON is missing or empty for required agent '{name}'"
            )
        out[name] = val.strip()
    return out


@lru_cache(maxsize=1)
def load_prompts() -> dict[str, str]:
    """Resolve and validate the system prompts.

    Returns a ``{agent_name: system_message}`` dict containing exactly the 5
    required entries. Caches the result so re-imports don't re-parse the file.

    Resolution order:

    1. ``GECKO_PROMPTS_PATH`` (full path override) — wins when set.
    2. ``GECKO_PRO_PROMPTS_VERSION`` (``v4``, ``v5``, ``v5.1``, ``v5.2``,
       ``v5.3``, or ``v5.4``) — selects which bundled file to load. Default is
       ``v5.4`` (Judge + Critic rewrite: STEP 2 collapsed to a named-buyer +
       named-artifact rule, STEP 3 is now the DEFAULT SHIP, STEP 4 trimmed to
       4 hard-kill triggers, Critic kill-criteria quota capped at 1-3 risks +
       one Change-my-mind clause). ``v5.3``, ``v5.2``, ``v5.1``, ``v5``, and
       ``v4`` are rollback targets.
    3. Bundled default (``v5.4``).
    """
    override = os.environ.get("GECKO_PROMPTS_PATH")
    if override:
        path = Path(override).expanduser()
    else:
        version = os.environ.get("GECKO_PRO_PROMPTS_VERSION", _DEFAULT_VERSION).strip()
        if version not in _BUNDLED_VERSIONS:
            raise PromptsConfigError(
                f"GECKO_PRO_PROMPTS_VERSION={version!r} is not a known bundled version "
                f"(known: {sorted(_BUNDLED_VERSIONS)})"
            )
        path = _BUNDLED_VERSIONS[version]

    if not path.is_file():
        if override:
            raise PromptsConfigError(
                f"GECKO_PROMPTS_PATH={override} does not point to a readable file"
            )
        # The bundled default should always exist; the package would be malformed otherwise.
        raise PromptsConfigError(f"bundled prompts file is missing: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PromptsConfigError(f"prompts JSON at {path} is not valid JSON: {exc}") from exc

    return _validate(data)


# ---------------------------------------------------------------------------
# Runtime-conditional prompt fragments (S20-FEATURE-NOT-PRODUCT-CRITIC-01)
# ---------------------------------------------------------------------------
# These fragments live in code (not the version-pinned JSON bundles) because
# they are *conditional on runtime data* (the basic-tier gap_classification
# label). A static JSON entry would be awkward — every prompt version would
# need to ship a parallel "if mature, also say this" branch. Instead we keep
# the JSON system messages clean and append a fragment at agent-build time
# when the gating condition fires.
#
# Trigger mapping (see ticket §1):
#   ticket label "crowded-but-differentiable" → ``Partial:UX``,
#                                                ``Partial:pricing``,
#                                                ``Partial:integration``
#   ticket label "mature"                     → ``Full``
#
# The ticket's labels are aspirational; the canonical
# :data:`gecko_core.models.GapClassification` Literal does not (yet) include
# "crowded-but-differentiable" or "mature". We map onto the existing taxonomy
# so the fragment fires whenever the basic-tier judge says a competitor
# already covers the wedge in full or differs on a single facet — which is
# exactly the "is this a feature or a product" risk surface.

FEATURE_NOT_PRODUCT_FRAGMENT: str = (
    "GAP CONTEXT: this idea sits in a crowded or mature space — the basic "
    "tier already classified the competitive landscape as either Full coverage "
    "or differentiation on a single facet (UX/pricing/integration). Before "
    "concluding GO, answer one question explicitly in your turn: is this a "
    "defensible product, or a feature that any incumbent could ship in a "
    "quarter? If feature, name the specific incumbent and the time horizon. "
    "If product, name the moat (data, distribution, switching cost, network "
    "effect, regulatory) that prevents that copy."
)

# The gap_classification labels that should trigger the fragment. Kept as a
# frozenset so the membership check is O(1) and the set is immutable across
# the module's lifetime.
FEATURE_NOT_PRODUCT_GAP_TRIGGERS: frozenset[str] = frozenset(
    {
        "Full",
        "Partial:UX",
        "Partial:pricing",
        "Partial:integration",
    }
)


def feature_not_product_fragment_for(gap_classification: str | None) -> str | None:
    """Return the fragment string when the gap label triggers it, else None.

    Pure function — no I/O, no caching needed. Called once per ``build_groupchat``
    invocation. Returning ``None`` (not empty string) lets the caller cleanly
    skip the append step when the fragment doesn't apply.
    """
    if gap_classification is None:
        return None
    if gap_classification in FEATURE_NOT_PRODUCT_GAP_TRIGGERS:
        return FEATURE_NOT_PRODUCT_FRAGMENT
    return None


# ---------------------------------------------------------------------------
# Distribution / GTM critic fragment (S20-DISTRIBUTION-CRITIC-01)
# ---------------------------------------------------------------------------
# Stress-matrix #3 from docs/sprint-reviews/2026-05-02-s18-s19-review.md §5
# ("a new app for hotels — generate local guides personally built for them")
# showed the 5-voice debate nailing PMF and missing the actual blocker:
# B2B distribution into hotel chains. Same failure mode applies to any
# 2-sided marketplace idea — the model rates "is the product good?" and
# never asks "can we acquire side A cheaply enough to attract side B?".
#
# This is a SIBLING fragment to FEATURE_NOT_PRODUCT_FRAGMENT, not a 6th
# voice. Adding a 6th voice would expand REQUIRED_AGENTS, the V1
# consistency test, the AG2 max_round budget, the SSE event ordering, and
# the eval rubric — that's L scope. Appending a fragment is S scope and
# composes cleanly with the existing feature-not-product gating.
#
# Detection is heuristic substring matching on idea + ICP, NOT an LLM
# call: cheap, deterministic, replayable. A typed B2B/2-sided field on
# ValidationReport is the cleaner long-term path (S21 follow-up); for
# S20 we stay narrow.

DISTRIBUTION_CRITIC_FRAGMENT: str = (
    "GTM CONTEXT: this idea has B2B or two-sided dynamics. "
    "Before concluding GO, name the distribution moat explicitly: "
    "(a) what's the wedge into the first 10 customers, (b) does "
    "selling to one side of the marketplace get the other side "
    "cheaper or more expensive, (c) is the buyer the user, and if "
    "not, who pays first? If you can't answer (a) concretely, "
    "REFINE — product-market fit doesn't matter without distribution-fit."
)

# Curated B2B keyword set. Cuts from the draft list to avoid false
# positives:
#   - "saas", "api", "platform" — appear in nearly every modern tech
#     idea ("AI platform for X"), would overfire on consumer SaaS.
#   - "agency", "agencies" — too ambiguous (agency-as-autonomy vs.
#     agency-as-firm); the named verticals below cover the B2B
#     services case more precisely.
# What stays: explicit B2B markers ("b2b", "enterprise"), procurement
# language ("vendor", "wholesale", "distributor", "supplier",
# "procurement", "channel sales"), and named B2B verticals where the
# distribution problem is the well-known blocker ("hotels", "hospitals",
# "law firms", "insurance"). "Marketplace" stays under the 2-sided set
# below where it belongs semantically.
_B2B_KEYWORDS: frozenset[str] = frozenset(
    {
        "b2b",
        "enterprise",
        "vendor",
        "wholesale",
        "distributor",
        "supplier",
        "hotels",
        "hospitals",
        "law firms",
        "insurance",
        "procurement",
        "channel sales",
    }
)

# 2-sided / marketplace hints. Cuts:
#   - bare "match" — fires on prose ("match the user's needs"). The
#     more specific "buyer and seller" / role-pair phrases catch real
#     marketplace intent without prose collisions.
#   - bare "platform" — see above.
# What stays: explicit role-pair phrases (high precision) plus
# "marketplace" itself (high recall on the canonical case).
_TWO_SIDED_HINTS: frozenset[str] = frozenset(
    {
        "buyer and seller",
        "creator and viewer",
        "host and guest",
        "driver and rider",
        "marketplace",
        "two-sided",
        "two sided",
    }
)


def distribution_critic_fragment_for(idea: str, icp: str | None = "") -> str | None:
    """Return the fragment when the idea/ICP triggers B2B or 2-sided detection.

    Pure substring match on a lowercased ``idea + " " + icp`` haystack — no
    LLM call, no I/O. Returns ``None`` (parallel to
    ``feature_not_product_fragment_for``) when no trigger fires so the
    caller can cleanly skip the append step.
    """
    if not idea and not icp:
        return None
    text = f"{idea or ''} {icp or ''}".lower()
    if any(k in text for k in _B2B_KEYWORDS):
        return DISTRIBUTION_CRITIC_FRAGMENT
    if any(k in text for k in _TWO_SIDED_HINTS):
        return DISTRIBUTION_CRITIC_FRAGMENT
    return None


__all__ = [
    "DISTRIBUTION_CRITIC_FRAGMENT",
    "FEATURE_NOT_PRODUCT_FRAGMENT",
    "FEATURE_NOT_PRODUCT_GAP_TRIGGERS",
    "REQUIRED_AGENTS",
    "PromptsConfigError",
    "distribution_critic_fragment_for",
    "feature_not_product_fragment_for",
    "load_prompts",
]
