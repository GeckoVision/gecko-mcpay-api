"""SSRF guard for the web extractor."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest
from gecko_core.ingestion.web import UnsafeURLError, validate_url


def _stub_dns(addr: str) -> object:
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (addr, 0))]


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://172.16.0.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://router.local/",
    ],
)
def test_blocks_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsafeURLError):
        validate_url(url)


def test_allows_public_url() -> None:
    with patch(
        "gecko_core.ingestion.web.socket.getaddrinfo", return_value=_stub_dns("93.184.216.34")
    ):
        assert validate_url("https://example.com/article") == "https://example.com/article"


def test_blocks_public_hostname_resolving_to_private() -> None:
    # Attacker-controlled hostname that resolves to a private IP.
    with (
        patch("gecko_core.ingestion.web.socket.getaddrinfo", return_value=_stub_dns("10.0.0.1")),
        pytest.raises(UnsafeURLError),
    ):
        validate_url("https://evil.example.com/")


def test_dns_failure_is_treated_as_unsafe() -> None:
    with (
        patch(
            "gecko_core.ingestion.web.socket.getaddrinfo",
            side_effect=socket.gaierror("nope"),
        ),
        pytest.raises(UnsafeURLError),
    ):
        validate_url("https://nonexistent.invalid/")
