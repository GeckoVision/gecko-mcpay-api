"""S12-BAZAAR-02 — guard against Bazaar route consolidation.

Bazaar collapses paths with bare-UUID segments (``/research/{session_id}``)
into a single catalog entry. Any *paid* route in ``_routes_config`` must
keep its path segments either constant or constant-prefixed
(``/research/session-{session_id}``) so each surface stays distinct in
discovery.

This test runs against the actual ``_routes_config`` shared between the
x402 middleware and ``/.well-known/x402``. Free read-after-pay routes
(e.g. ``GET /sessions/{session_id}/result``) are out of scope today
because Bazaar only catalogs after settle — but the helper itself is
exposed for callers that want to audit free routes too.
"""

from __future__ import annotations

import os
import sys

import pytest

os.environ.setdefault("X402_MODE", "stub")
os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_TEST_WALLET")


@pytest.fixture(autouse=True)
def _reset_modules() -> None:
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)


def test_helper_flags_bare_uuid_segments() -> None:
    """Sanity check the helper before relying on it."""
    from gecko_api.bazaar import has_bare_uuid_segment

    # Bare UUIDs — should flag.
    assert has_bare_uuid_segment("POST /research/{session_id}")
    assert has_bare_uuid_segment("GET /economics/{session_id}")
    assert has_bare_uuid_segment("/projects/{project_id}/audit")
    assert has_bare_uuid_segment("POST /things/{id}")
    assert has_bare_uuid_segment("POST /things/{uuid}")

    # Constant prefix glued to the param — safe.
    assert not has_bare_uuid_segment("POST /research/session-{session_id}")
    assert not has_bare_uuid_segment("POST /projects/project-{project_id}/audit")
    assert not has_bare_uuid_segment("POST /research")
    assert not has_bare_uuid_segment("GET /healthz")
    # Param with non-id name (e.g. tier_preset) — also safe.
    assert not has_bare_uuid_segment("POST /route/{tier_preset}")


def test_no_paid_route_has_bare_uuid_segment() -> None:
    """Every entry in ``_routes_config`` is paid — none may be bare-UUID.

    A failure here means Bazaar would collapse multiple sessions into one
    catalog row when listing the route. Fix by adding a constant prefix
    (``/research/session-{session_id}``) and following the migration
    steps in ``docs/runbooks/cdp-bazaar.md``.
    """
    from gecko_api.bazaar import has_bare_uuid_segment
    from gecko_api.main import _routes_config

    offenders = [r for r in _routes_config if has_bare_uuid_segment(r)]
    assert not offenders, (
        "Paid routes with bare-UUID segments would consolidate in CDP Bazaar. "
        f"Offenders: {offenders}. See docs/runbooks/cdp-bazaar.md §3."
    )
