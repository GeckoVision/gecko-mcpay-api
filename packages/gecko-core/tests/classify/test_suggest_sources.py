"""S13-COMMO-03 — `suggest_sources` returns recommended sources + weights."""

from __future__ import annotations

from gecko_core.classify import suggest_sources


def test_suggest_sources_always_includes_ungated_sources() -> None:
    # All-zero scores: only the always-on sources fire.
    suggested, weights = suggest_sources(
        {
            "crypto": 0.0,
            "defi": 0.0,
            "devtools": 0.0,
            "saas": 0.0,
            "regulated": 0.0,
            "hackathon-team": 0.0,
        }
    )
    assert "tavily" in suggested
    assert "hn" in suggested
    assert "reddit" in suggested
    assert "gecko_precedent" in suggested
    assert weights["tavily"] == 1.0
    # Category-gated sources sit out when scores are below threshold.
    assert "twit_sh" not in suggested
    assert "colosseum" not in suggested


def test_suggest_sources_includes_crypto_sources_when_classified_crypto() -> None:
    suggested, weights = suggest_sources(
        {
            "crypto": 0.71,
            "defi": 0.65,
            "devtools": 0.30,
            "saas": 0.20,
            "regulated": 0.10,
            "hackathon-team": 0.04,
        }
    )
    assert "twit_sh" in suggested
    assert "colosseum" in suggested
    # Priority should be the max of the gating categories' scores.
    assert weights["twit_sh"] == 0.71
    assert weights["colosseum"] == 0.71


def test_suggest_sources_keys_match_between_lists() -> None:
    """Every entry in `suggested` must have a `priority_weights` entry."""
    suggested, weights = suggest_sources(
        {c: 0.5 for c in ("crypto", "defi", "devtools", "saas", "regulated", "hackathon-team")}
    )
    assert set(suggested) == set(weights)
