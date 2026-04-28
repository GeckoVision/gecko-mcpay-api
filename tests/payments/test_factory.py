"""get_client() factory — mode dispatch only, never charges."""

from __future__ import annotations

import pytest
from gecko_core.payments import (
    FramesX402Client,
    LiveX402Client,
    StubX402Client,
    get_client,
)


def test_stub_mode_returns_stub() -> None:
    assert isinstance(get_client("stub"), StubX402Client)


def test_live_mode_returns_live_skeleton() -> None:
    # Skeleton constructor must succeed even without env so import paths
    # stay green; charge() is what raises NotImplementedError.
    assert isinstance(get_client("live"), LiveX402Client)


def test_frames_mode_returns_frames_skeleton() -> None:
    assert isinstance(get_client("frames"), FramesX402Client)


def test_unknown_mode_raises() -> None:
    with pytest.raises(ValueError, match="unknown X402_MODE"):
        get_client("paypal")
