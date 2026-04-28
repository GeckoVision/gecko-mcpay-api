"""YouTube extraction — chains transcript providers."""

from __future__ import annotations

from .settings import get_ingestion_settings
from .transcript import (
    DeepgramTranscriptProvider,
    TranscriptProvider,
    YouTubeCaptionsProvider,
)


def default_providers() -> list[TranscriptProvider]:
    """Captions first (free); Deepgram audio-fallback only if key configured."""
    chain: list[TranscriptProvider] = [YouTubeCaptionsProvider()]
    try:
        settings = get_ingestion_settings()
    except Exception:
        # Settings can fail to construct in odd test envs; fall back to captions only.
        return chain
    if settings.deepgram_api_key is not None:
        chain.append(DeepgramTranscriptProvider())
    return chain


async def extract(
    url: str,
    providers: list[TranscriptProvider] | None = None,
) -> tuple[str | None, float]:
    """Try each provider in order; return (text, deepgram_seconds_billed).

    `deepgram_seconds_billed` is non-zero only when the Deepgram fallback was
    invoked successfully — the pipeline turns that into a per-session cost
    line. Free providers (YouTube captions) report 0.0.

    Returns (None, 0.0) if no provider has captions for this video — the
    pipeline treats that as a graceful skip, not a failure.
    """
    chain = providers if providers is not None else default_providers()
    for provider in chain:
        try:
            text = await provider.fetch(url)
        except Exception:
            continue
        if text:
            seconds = 0.0
            if isinstance(provider, DeepgramTranscriptProvider):
                seconds = provider.last_billable_seconds
            return text, seconds
    return None, 0.0


__all__ = ["default_providers", "extract"]
