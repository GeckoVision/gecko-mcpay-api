"""Tests for V11-03 — bs4 parser dispatch on Content-Type."""

from __future__ import annotations

import pytest
from gecko_core.ingestion.web import _parser_for_content_type


@pytest.mark.parametrize(
    "content_type,expected",
    [
        ("application/xml", "lxml-xml"),
        ("application/rss+xml", "lxml-xml"),
        ("application/atom+xml", "lxml-xml"),
        ("text/xml", "lxml-xml"),
        ("application/rss+xml; charset=utf-8", "lxml-xml"),
        ("APPLICATION/XML", "lxml-xml"),
        ("text/html", "html.parser"),
        ("text/html; charset=utf-8", "html.parser"),
        ("application/json", "html.parser"),
        ("", "html.parser"),
    ],
)
def test_parser_dispatch(content_type: str, expected: str) -> None:
    assert _parser_for_content_type(content_type) == expected
