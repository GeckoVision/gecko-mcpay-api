"""Unit tests for `DeepgramTranscriptProvider`.

We never make a real network call — yt-dlp is patched at the module helper
boundary, and the Deepgram client is replaced with a fake.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from gecko_core.ingestion import transcript as transcript_mod
from gecko_core.ingestion.transcript import DeepgramTranscriptProvider

YOUTUBE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


class _FakeDeepgramResponse:
    def __init__(self, text: str) -> None:
        self.results = type(
            "R",
            (),
            {
                "channels": [
                    type(
                        "C",
                        (),
                        {"alternatives": [type("A", (), {"transcript": text})()]},
                    )()
                ]
            },
        )()


class _FakeMedia:
    def __init__(self, text: str) -> None:
        self._text = text
        self.calls: list[Any] = []

    def transcribe_file(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return _FakeDeepgramResponse(self._text)


class _FakeListenV1:
    def __init__(self, media: _FakeMedia) -> None:
        self.media = media


class _FakeListen:
    def __init__(self, v1: _FakeListenV1) -> None:
        self.v1 = v1


class _FakeDeepgramClient:
    last_api_key: str | None = None

    def __init__(self, api_key: str, text: str = "hello world") -> None:
        type(self).last_api_key = api_key
        self._media = _FakeMedia(text)
        self.listen = _FakeListen(_FakeListenV1(self._media))


def _patch_deepgram(monkeypatch: pytest.MonkeyPatch, text: str = "hello world") -> None:
    """Inject a fake Deepgram SDK module so import inside _transcribe succeeds.

    Mocks the SDK v6 surface: client.listen.v1.media.transcribe_file(request=..., **kwargs).
    """
    import sys
    import types

    fake = types.ModuleType("deepgram")

    def _client(api_key: str | None = None, **kwargs: Any) -> _FakeDeepgramClient:
        return _FakeDeepgramClient(api_key or kwargs.get("api_key", ""), text=text)

    fake.DeepgramClient = _client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepgram", fake)


async def test_happy_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    audio = tmp_path / "vid.m4a"
    audio.write_bytes(b"\x00\x01fakeaudio")

    def fake_extract(url: str, out_dir: str) -> tuple[Path, float]:
        return audio, 60.0

    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", fake_extract)
    _patch_deepgram(monkeypatch, text="  the transcript  ")

    provider = DeepgramTranscriptProvider(api_key="dg-test-key", max_audio_minutes=30)
    result = await provider.fetch(YOUTUBE_URL)
    assert result == "the transcript"
    assert _FakeDeepgramClient.last_api_key == "dg-test-key"


async def test_missing_api_key_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def fake_extract(url: str, out_dir: str) -> Any:
        called["n"] += 1
        return None

    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", fake_extract)
    # Pass empty string explicitly — the constructor only falls back to settings
    # when api_key is None, so we bypass the env-read path that would pick up
    # a real DEEPGRAM_API_KEY in the test environment.
    provider = DeepgramTranscriptProvider(api_key="", max_audio_minutes=30)
    assert await provider.fetch(YOUTUBE_URL) is None
    assert called["n"] == 0


async def test_unknown_url_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def fake_extract(url: str, out_dir: str) -> Any:
        called["n"] += 1
        return None

    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", fake_extract)
    provider = DeepgramTranscriptProvider(api_key="dg-x", max_audio_minutes=30)
    assert await provider.fetch("https://example.com/not-youtube") is None
    assert called["n"] == 0


async def test_ytdlp_failure_returns_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", lambda url, out: None)
    provider = DeepgramTranscriptProvider(api_key="dg-x", max_audio_minutes=30)
    assert await provider.fetch(YOUTUBE_URL) is None


async def test_empty_transcript_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "vid.m4a"
    audio.write_bytes(b"\x00")
    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", lambda url, out: (audio, 30.0))
    _patch_deepgram(monkeypatch, text="   ")
    provider = DeepgramTranscriptProvider(api_key="dg-x", max_audio_minutes=30)
    assert await provider.fetch(YOUTUBE_URL) is None


async def test_over_duration_cap_skips_deepgram(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    audio = tmp_path / "vid.m4a"
    audio.write_bytes(b"\x00")
    monkeypatch.setattr(
        transcript_mod,
        "_ytdlp_extract_audio",
        lambda url, out: (audio, 31 * 60.0),  # 31 minutes, over the 30m cap
    )

    deepgram_calls = {"n": 0}

    def boom(*args: Any, **kwargs: Any) -> Any:
        deepgram_calls["n"] += 1
        raise AssertionError("deepgram should not be called when over cap")

    with patch.object(DeepgramTranscriptProvider, "_transcribe", side_effect=boom):
        provider = DeepgramTranscriptProvider(api_key="dg-x", max_audio_minutes=30)
        assert await provider.fetch(YOUTUBE_URL) is None
    assert deepgram_calls["n"] == 0


async def test_deepgram_transport_error_returns_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Unexpected SDK errors are swallowed inside the provider so the chain
    can fall through cleanly. The provider returns None instead of raising.
    """
    audio = tmp_path / "vid.m4a"
    audio.write_bytes(b"\x00")
    monkeypatch.setattr(transcript_mod, "_ytdlp_extract_audio", lambda url, out: (audio, 30.0))

    import sys
    import types

    fake = types.ModuleType("deepgram")

    class _BoomClient:
        def __init__(self, api_key: str) -> None:
            raise RuntimeError("auth blew up")

    fake.DeepgramClient = _BoomClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "deepgram", fake)

    provider = DeepgramTranscriptProvider(api_key="dg-x", max_audio_minutes=30)
    assert await provider.fetch(YOUTUBE_URL) is None
