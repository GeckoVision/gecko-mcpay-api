"""pay.sh v1.0-compatible manifest builder (S20-B1).

Serializes :data:`gecko_core.skills.registry.SKILLS` into the JSON shape
crawled by pay.sh's catalog at
``/.well-known/agent-skills/index.json``. Required pay.sh fields
(``name``, ``title``, ``description``, ``url``) sit at the top of each
skill entry; ``pricing``, ``category``, and ``gecko_knowledge_category``
are extension fields — pay.sh's crawler ignores unknown keys, so we use
them to surface our pricing floors and the knowledge-noun taxonomy.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from gecko_core.skills.registry import SKILLS, Skill

_GECKO_BASE_URL = "https://app.geckovision.tech"

_DESCRIPTION = (
    "Categorized build-context layer for AI builders. We pre-load the full "
    "domain knowledge for your app vertical (neobank, DEX, marketplace, ...), "
    "index it across 7 dimensions, and serve it to your build agent on every "
    "step — paid per call via x402. The base compounds: every builder makes "
    "the next one cheaper."
)


def _money(value: Decimal | None) -> float | None:
    """Convert a :class:`Decimal` to a JSON-safe float at the manifest
    boundary. ``None`` (e.g. credit-pack overage) round-trips as null.

    We accept the float lossiness here because the on-the-wire manifest
    is a discovery artifact, not the authoritative price; the dispatch
    path always re-reads :class:`Decimal` from the registry.
    """
    if value is None:
        return None
    return float(value)


def _skill_to_entry(skill: Skill) -> dict[str, Any]:
    return {
        "name": skill.name,
        "title": skill.title,
        "description": skill.description,
        "url": f"{_GECKO_BASE_URL}{skill.url_path}",
        "pricing": {
            "flat_usd": _money(skill.price_usd),
            "bundled_output_tokens": skill.bundled_output_tokens,
            "overage_per_1m_output_usd": _money(skill.overage_per_1m_output_usd),
            "currency": "USD",
        },
        "category": skill.category,
        "gecko_knowledge_category": skill.gecko_knowledge_category,
    }


def build_manifest() -> dict[str, Any]:
    """Return the full manifest dict ready for ``json.dumps``.

    Shape conforms to pay.sh v1.0 (verified 2026-05-06): ``version``,
    ``name``, ``description``, ``skills``. Every entry in ``skills``
    carries the four pay.sh-required fields plus Gecko extensions.
    """
    return {
        "version": "1.0",
        "name": "Gecko",
        "description": _DESCRIPTION,
        "skills": [_skill_to_entry(s) for s in SKILLS],
    }


__all__ = ["build_manifest"]
