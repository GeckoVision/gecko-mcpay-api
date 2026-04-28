"""Typed settings for gecko-api.

Reads x402 + wallet configuration from the environment. Defaults to
``X402_MODE=stub`` so local dev and CI never accidentally talk to a real
facilitator. Live mode (`mode != "stub"`) requires the facilitator URL and
the receiving wallet address — we fail fast at startup rather than at the
first 402.
"""

from __future__ import annotations

import os
from typing import Literal

from pydantic import BaseModel

X402Mode = Literal["stub", "live", "frames"]


class Settings(BaseModel):
    """Runtime settings derived from the process environment."""

    x402_mode: X402Mode = "stub"
    x402_facilitator_url: str | None = None
    gecko_wallet_address: str | None = None
    x402_network: str = "solana-devnet"

    # Pricing — basic and pro tiers exposed as separate routes.
    research_basic_price: str = "$20.00"
    research_pro_price: str = "$0.75"

    # Per-instance secret used to HMAC-sign session-scoped events tokens for
    # the SSE endpoint. Defaults to a derived value at process start so devs
    # don't need to set anything; production deploys MUST set EVENTS_SECRET so
    # tokens survive restarts and load-balanced replicas. 32+ bytes recommended.
    events_secret: str = "dev-events-secret-not-for-production"

    model_config = {"frozen": True}

    @classmethod
    def from_env(cls) -> Settings:
        mode = os.environ.get("X402_MODE", "stub")
        if mode not in ("stub", "live", "frames"):
            raise ValueError(f"unknown X402_MODE: {mode!r}")

        facilitator_url = os.environ.get("X402_FACILITATOR_URL")
        wallet = os.environ.get("GECKO_WALLET_ADDRESS")
        network = os.environ.get("X402_NETWORK", "solana-devnet")

        if mode != "stub":
            missing: list[str] = []
            if not facilitator_url:
                missing.append("X402_FACILITATOR_URL")
            if not wallet:
                missing.append("GECKO_WALLET_ADDRESS")
            if missing:
                raise RuntimeError(f"X402_MODE={mode!r} requires env vars: {', '.join(missing)}")

        # Pricing overrides — useful on devnet where we want cheap demo runs.
        # Format: "$N.NN" (the x402 SDK parses the leading $).
        basic_price = os.environ.get("RESEARCH_BASIC_PRICE", "$20.00")
        pro_price = os.environ.get("RESEARCH_PRO_PRICE", "$0.75")
        events_secret = os.environ.get("EVENTS_SECRET", "dev-events-secret-not-for-production")

        # In stub mode we still need a non-empty pay_to for the route catalog.
        # Use a clearly-fake placeholder so it's obvious in /.well-known/x402.
        return cls(
            x402_mode=mode,  # type: ignore[arg-type]
            x402_facilitator_url=facilitator_url,
            gecko_wallet_address=wallet or "STUB_WALLET_ADDRESS_NOT_FOR_LIVE",
            x402_network=network,
            research_basic_price=basic_price,
            research_pro_price=pro_price,
            events_secret=events_secret,
        )


__all__ = ["Settings", "X402Mode"]
