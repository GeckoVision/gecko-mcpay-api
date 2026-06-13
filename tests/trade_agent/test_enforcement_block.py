"""EnforcementBlock reachability + provenance-not-retrieval invariants.

Pattern A: ``EnforcementProvider`` is the ONE canonical Literal for the
enforcement-provenance tag, and it is DELIBERATELY NOT a member of the
``chunks.provider_kind`` ``ProviderKind`` (that would make it a retrievable
Mongo chunk kind — Pattern F). This test pins both:

  1. ``EnforcementBlock`` rides the verdict envelope (reachability).
  2. ``bento_preflight`` is NOT in the retrieval ``ProviderKind`` (Pattern F).
"""

from __future__ import annotations

import pytest
from gecko_core.orchestration.trade_panel.models import (
    EnforcementBlock,
    TradePanelVerdict,
)
from gecko_core.sources.types import PROVIDER_KINDS
from pydantic import ValidationError


def test_enforcement_block_rides_the_envelope() -> None:
    """The block is reachable as a first-class, optional envelope field."""
    block = EnforcementBlock(
        checked=True,
        verdict="veto",
        reasons=["mint_substitution"],
        tx_hash="FAKETX",
    )
    env = TradePanelVerdict(verdict="pass", confidence=0.7, enforcement=block)
    assert env.enforcement is not None
    assert env.enforcement.verdict == "veto"
    assert env.enforcement.provider_kind == "bento_preflight"
    assert env.enforcement.fail_posture == "closed"
    # round-trips through the wire (model_dump → model_validate)
    again = TradePanelVerdict.model_validate(env.model_dump())
    assert again.enforcement is not None
    assert again.enforcement.reasons == ["mint_substitution"]


def test_enforcement_defaults_none_additive() -> None:
    """Additive + optional: omitting enforcement is the default, never required."""
    env = TradePanelVerdict(verdict="pass", confidence=0.5)
    assert env.enforcement is None


def test_unavailable_is_fail_closed() -> None:
    block = EnforcementBlock.unavailable()
    assert block.checked is False
    assert block.verdict == "unavailable"  # fail-CLOSED: caller must not broadcast
    assert block.fail_posture == "closed"


def test_provider_kind_rejects_non_bento() -> None:
    with pytest.raises(ValidationError):
        EnforcementBlock(checked=True, verdict="allow", provider_kind="quicknode")  # type: ignore[arg-type]


def test_bento_preflight_not_a_retrieval_provider_kind() -> None:
    """Pattern F guard: the enforcement provenance tag must NOT leak into the
    chunks-table ``ProviderKind`` (which would make it a retrievable chunk kind
    + force a Supabase migration). It lives in its own Literal."""
    assert "bento_preflight" not in PROVIDER_KINDS
