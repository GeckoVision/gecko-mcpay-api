"""Shared fixtures for the gecko test suite."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
import pytest_asyncio


@pytest.fixture(scope="session", autouse=True)
def _load_test_env() -> None:
    """Load .env if present. Tests run in stub mode by default."""
    from dotenv import load_dotenv

    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    os.environ.setdefault("X402_MODE", "stub")
    # S12-HARDEN-03 — disable production transcript capture under pytest by
    # default so the suite doesn't litter $TMP. Tests that exercise the
    # capture path (e.g. tests/orchestration/test_transcripts.py) flip this
    # back on with monkeypatch.setenv + GECKO_TRANSCRIPT_DIR.
    os.environ.setdefault("GECKO_TRANSCRIPT_CAPTURE", "false")


@pytest.fixture
def demo_idea() -> str:
    """The PRD's canonical demo idea."""
    return "a hotel guide for Brazil that highlights local hosts"


@pytest.fixture
def sample_youtube_with_captions() -> str:
    """A YouTube URL known to have captions. Replace with a stable one for your tests."""
    return "https://www.youtube.com/watch?v=REPLACE_ME"


@pytest.fixture
def sample_youtube_without_captions() -> str:
    """A YouTube URL known to lack captions. Used to exercise the graceful-skip path."""
    return "https://www.youtube.com/watch?v=REPLACE_ME"


@pytest.fixture
def sample_web_article() -> str:
    """A web article URL for the web extractor."""
    return "https://www.paulgraham.com/ds.html"


@pytest_asyncio.fixture
async def session_id() -> AsyncIterator[str]:
    """Create a session, yield its ID, clean up after.

    Once Phase 1 is done, this should call SessionStore().create() instead of mocking.
    """
    sid = str(uuid4())
    yield sid
    # TODO: cleanup once SessionStore exists
