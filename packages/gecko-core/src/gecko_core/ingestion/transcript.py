"""Transcript provider abstraction for YouTube extraction.

Splitting providers from the YouTube adapter lets us add Whisper/Apify
fallbacks later without touching the call site.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Protocol

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from .settings import get_ingestion_settings

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})")


def parse_video_id(url: str) -> str | None:
    """Extract YouTube video id from a URL, or None if not recognized."""
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


class TranscriptProvider(Protocol):
    """Returns transcript text for a YouTube URL, or None if unavailable.

    Implementations MUST NOT raise on "no captions" — return None instead.
    They MAY raise on transport errors so the chain can fall through.
    """

    async def fetch(self, url: str) -> str | None: ...


class YouTubeCaptionsProvider:
    """Provider backed by youtube-transcript-api (free, no API key)."""

    def __init__(self) -> None:
        self._api = YouTubeTranscriptApi()

    def _fetch_sync(self, video_id: str) -> str | None:
        try:
            fetched = self._api.fetch(video_id)
        except (NoTranscriptFound, TranscriptsDisabled, VideoUnavailable):
            return None
        entries = fetched.to_raw_data()
        text = " ".join(e.get("text", "") for e in entries).strip()
        return text or None

    async def fetch(self, url: str) -> str | None:
        vid = parse_video_id(url)
        if not vid:
            return None
        return await asyncio.to_thread(self._fetch_sync, vid)


def _ytdlp_extract_audio(url: str, out_dir: str) -> tuple[Path, float] | None:
    """Download smallest audio-only stream for `url` into `out_dir`.

    Returns (audio_path, duration_seconds) on success, or None if yt-dlp
    cannot retrieve the video (private, deleted, region-locked, age-gated).

    This is blocking — call via `asyncio.to_thread`.
    """
    try:
        from yt_dlp import YoutubeDL  # type: ignore[import-untyped]
    except ImportError:  # pragma: no cover
        return None

    ydl_opts: dict[str, Any] = {
        "format": "bestaudio[ext=m4a]/bestaudio",
        "outtmpl": os.path.join(out_dir, "%(id)s.%(ext)s"),
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        # Don't write any sidecar files (descriptions, info json, thumbnails).
        "writeinfojson": False,
        "writethumbnail": False,
        "writesubtitles": False,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        # yt-dlp raises a sprawling family of DownloadError subclasses; treat
        # any of them as "audio not retrievable" and let the caller return None.
        logger.info("yt-dlp failed to extract audio: %s", type(exc).__name__)
        return None

    if not isinstance(info, dict):
        return None
    duration = float(info.get("duration") or 0.0)
    # yt-dlp records the final filename via prepare_filename; but with our
    # outtmpl we can reconstruct it from id + ext.
    vid = info.get("id")
    ext = info.get("ext")
    if not vid or not ext:
        return None
    candidate = Path(out_dir) / f"{vid}.{ext}"
    if not candidate.exists():
        # Fallback: scan the temp dir for the only audio file.
        files = [p for p in Path(out_dir).iterdir() if p.is_file()]
        if len(files) != 1:
            return None
        candidate = files[0]
    return candidate, duration


class DeepgramTranscriptProvider:
    """Audio-fallback provider: yt-dlp -> Deepgram nova-3.

    Used when YouTube captions are absent. Requires `DEEPGRAM_API_KEY`.
    Returns None (never raises) on graceful failures so the provider chain
    can fall through.
    """

    # Deepgram nova-3 pre-recorded with `language=multi` is ~$0.0043/minute
    # ($0.000072/second) per their public pricing. Surfaced on the per-session
    # economics view; recomputed if Deepgram changes pricing.
    NOVA_3_USD_PER_SECOND: float = 0.0043 / 60.0

    def __init__(self, api_key: str | None = None, max_audio_minutes: int = 30) -> None:
        if api_key is None:
            settings = get_ingestion_settings()
            secret = settings.deepgram_api_key
            api_key = secret.get_secret_value() if secret is not None else None
            max_audio_minutes = settings.deepgram_max_audio_minutes
        self._api_key = api_key
        self._max_audio_minutes = max_audio_minutes
        # Set inside `fetch` when Deepgram was actually invoked. Read by the
        # pipeline to attribute cost to the session.
        self.last_billable_seconds: float = 0.0

    async def fetch(self, url: str) -> str | None:
        self.last_billable_seconds = 0.0
        if not self._api_key:
            return None
        if parse_video_id(url) is None:
            return None

        with tempfile.TemporaryDirectory(prefix="gecko-dg-") as tmp:
            extracted = await asyncio.to_thread(_ytdlp_extract_audio, url, tmp)
            if extracted is None:
                return None
            audio_path, duration_s = extracted
            if duration_s and duration_s > self._max_audio_minutes * 60:
                logger.info(
                    "deepgram: skipping video over duration cap (%.0fs > %dm)",
                    duration_s,
                    self._max_audio_minutes,
                )
                return None
            try:
                audio_bytes = audio_path.read_bytes()
            except OSError:
                return None
            transcript = await self._transcribe(audio_bytes)
            if transcript is not None:
                self.last_billable_seconds = float(duration_s or 0.0)
            return transcript

    async def _transcribe(self, audio_bytes: bytes) -> str | None:
        """POST audio to Deepgram /listen, return transcript or None.

        Uses Deepgram SDK v6 surface: `client.listen.v1.media.transcribe_file`
        with kwargs (no PrerecordedOptions class in v6).
        """
        try:
            from deepgram import DeepgramClient  # type: ignore[import-not-found]
        except ImportError:  # pragma: no cover
            return None

        try:
            client = DeepgramClient(api_key=self._api_key)
            response = await asyncio.to_thread(
                lambda: client.listen.v1.media.transcribe_file(
                    request=audio_bytes,
                    model="nova-3",
                    language="multi",
                    smart_format=True,
                    punctuate=True,
                )
            )
        except Exception as exc:
            # Transport / auth errors: log redacted type, return None so the
            # chain falls through rather than crashing the pipeline.
            logger.info("deepgram transcribe failed: %s: %s", type(exc).__name__, exc)
            return None

        transcript = _extract_first_transcript(response)
        if not transcript:
            return None
        return transcript.strip() or None


def _extract_first_transcript(response: object) -> str | None:
    """Pull `results.channels[0].alternatives[0].transcript` defensively.

    Deepgram's SDK returns either a typed object or a dict-shaped payload
    depending on version; handle both.
    """
    try:
        results = getattr(response, "results", None)
        if results is None and isinstance(response, dict):
            results = response.get("results")
        channels = getattr(results, "channels", None)
        if channels is None and isinstance(results, dict):
            channels = results.get("channels")
        if not channels:
            return None
        first = channels[0]
        alternatives = getattr(first, "alternatives", None)
        if alternatives is None and isinstance(first, dict):
            alternatives = first.get("alternatives")
        if not alternatives:
            return None
        alt = alternatives[0]
        transcript = getattr(alt, "transcript", None)
        if transcript is None and isinstance(alt, dict):
            transcript = alt.get("transcript")
        if isinstance(transcript, str):
            return transcript
        return None
    except (AttributeError, IndexError, TypeError, KeyError):
        return None


__all__ = [
    "DeepgramTranscriptProvider",
    "TranscriptProvider",
    "YouTubeCaptionsProvider",
    "parse_video_id",
]
