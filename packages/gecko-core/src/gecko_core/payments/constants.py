"""Single source of truth for shared payment sentinels (Pattern A).

This module is a leaf: zero intra-package imports, so anything in the
codebase — including ``gecko-api`` settings — can import from it without
triggering circular imports.

Why this exists
---------------
The Sprint-12 ``PaymentMode`` saga (`gecko_core.payments.modes`) showed
what happens when the same conceptual constant is redeclared in parallel
across modules: each fix flips one copy and misses the others. The same
class of bug surfaced in S16 with the stub-wallet sentinel — the
``payTo`` validator in ``gecko_api.main`` knew about
``STUB_WALLET_ADDRESS_NOT_FOR_LIVE``, but ~21 test fixtures in the API
suite seeded ``GECKO_WALLET_ADDRESS=STUB_TEST_WALLET``. After S15
tightened the base58 regex, every one of those tests collapsed at app
import.

The fix: every consumer (production code AND tests) imports
``STUB_WALLET_ADDRESS_NOT_FOR_LIVE`` from here. New stub strings get
added once, in this module, and everywhere else picks them up.
"""

from __future__ import annotations

from typing import Final

STUB_WALLET_ADDRESS_NOT_FOR_LIVE: Final[str] = "STUB_WALLET_ADDRESS_NOT_FOR_LIVE"
"""Canonical sentinel for the stub-mode ``payTo``/``GECKO_WALLET_ADDRESS``.

Allowed only when ``X402_MODE=stub``. The ``payTo`` validator in
``gecko_api.main`` whitelists exactly this string and rejects anything
else that doesn't match the EVM/base58 shape for its declared network.
Live/CDP/frames modes refuse this value at the settings layer before any
route is advertised.
"""

__all__ = ["STUB_WALLET_ADDRESS_NOT_FOR_LIVE"]
