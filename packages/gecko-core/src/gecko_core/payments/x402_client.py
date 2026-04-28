"""x402 client implementations and the mode factory.

Three modes, identical return shape:
- stub:   in-memory; sleeps briefly; always succeeds. Default for dev/tests.
- live:   direct facilitator + Solana wallet. Skeleton only — wired post-demo.
- frames: frames.ag wallet API. V2.

`get_client()` reads `X402_MODE` from env (defaulting to 'stub') via
`PaymentSettings`.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from functools import lru_cache
from typing import Literal, Protocol, runtime_checkable

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from gecko_core.payments.models import PaymentIntent, PaymentResult

logger = logging.getLogger(__name__)

X402Mode = Literal["stub", "live", "frames"]


class PaymentSettings(BaseSettings):
    """Payment-related env config. Defaults are dev-safe."""

    mode: X402Mode = Field(default="stub", alias="X402_MODE")
    facilitator_url: str | None = Field(default=None, alias="X402_FACILITATOR_URL")
    wallet_secret: SecretStr | None = Field(default=None, alias="X402_WALLET_SECRET")
    frames_api_key: SecretStr | None = Field(default=None, alias="FRAMES_API_KEY")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def _settings() -> PaymentSettings:
    return PaymentSettings()


@runtime_checkable
class X402Client(Protocol):
    """The contract every mode honors. Same return shape, same error shape."""

    async def charge(self, intent: PaymentIntent) -> PaymentResult: ...


class StubX402Client:
    """No-op client for dev/tests. Always succeeds. Never hits the network."""

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        await asyncio.sleep(0.1)
        logger.debug("stub charge ok intent_id=%s", intent.intent_id)
        return PaymentResult(
            intent_id=intent.intent_id,
            status="success",
            tx_signature=None,
            error=None,
        )


class LiveX402Client:
    """Direct x402 facilitator + Solana wallet. Skeleton — wired post-demo."""

    def __init__(
        self,
        facilitator_url: str,
        wallet_secret: SecretStr,
    ) -> None:
        self._facilitator_url = facilitator_url
        self._wallet_secret = wallet_secret

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        raise NotImplementedError(
            "live mode wiring is post-demo: configure X402_FACILITATOR_URL "
            "and X402_WALLET_SECRET, then implement on-chain settlement here."
        )


class FramesX402Client:
    """frames.ag wallet API. V2 stub."""

    def __init__(self, api_key: SecretStr) -> None:
        self._api_key = api_key

    async def charge(self, intent: PaymentIntent) -> PaymentResult:
        raise NotImplementedError("frames.ag integration is V2: see web3-engineer agent notes.")


def get_client(mode: str | None = None) -> X402Client:
    """Build the client for the requested mode (or env default).

    `mode=None` reads X402_MODE from env, defaulting to 'stub'.
    """
    s = _settings()
    selected = mode if mode is not None else s.mode

    if selected == "stub":
        return StubX402Client()
    if selected == "live":
        if not s.facilitator_url or s.wallet_secret is None:
            # Skeleton constructor still works without env so import-paths and
            # factory tests stay green; charge() will raise NotImplementedError.
            return LiveX402Client(
                facilitator_url=s.facilitator_url or "",
                wallet_secret=s.wallet_secret or SecretStr(""),
            )
        return LiveX402Client(
            facilitator_url=s.facilitator_url,
            wallet_secret=s.wallet_secret,
        )
    if selected == "frames":
        return FramesX402Client(api_key=s.frames_api_key or SecretStr(""))
    raise ValueError(f"unknown X402_MODE: {selected!r}")


def new_intent_id() -> str:
    """Mint a fresh idempotency key. Client-side uuid4."""
    return str(uuid.uuid4())


__all__ = [
    "FramesX402Client",
    "LiveX402Client",
    "PaymentSettings",
    "StubX402Client",
    "X402Client",
    "X402Mode",
    "get_client",
    "new_intent_id",
]
