"""Tests for the secret-safe HTTP-error diagnostics in okx_http_news_adapter.

The adapter must surface OKX's HTTP status + error code/msg on fetch_failed so
prod logs say "401 / 50104" instead of a bare exception class — while NEVER
leaking creds, headers, or the signed URL.
"""

from __future__ import annotations

import httpx
from gecko_core.orchestration.trade_panel.okx_http_news_adapter import (
    _diagnose_http_error,
)


def _status_error(status: int, body: object) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://www.okx.com/api/v5/orbit/news-search")
    response = httpx.Response(status, json=body, request=request)
    return httpx.HTTPStatusError("boom", request=request, response=response)


def test_parses_okx_401_code_and_msg() -> None:
    exc = _status_error(401, {"code": "50104", "msg": "Invalid passphrase"})
    status, code, msg = _diagnose_http_error(exc)
    assert status == 401
    assert code == "50104"
    assert msg == "Invalid passphrase"


def test_non_http_error_returns_all_none() -> None:
    status, code, msg = _diagnose_http_error(httpx.ConnectTimeout("slow"))
    assert (status, code, msg) == (None, None, None)


def test_non_json_body_yields_status_only() -> None:
    request = httpx.Request("GET", "https://www.okx.com/api/v5/orbit/news-search")
    response = httpx.Response(401, text="<html>unauthorized</html>", request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)
    status, code, msg = _diagnose_http_error(exc)
    assert status == 401
    assert code is None and msg is None


def test_long_msg_is_capped() -> None:
    exc = _status_error(400, {"code": "1", "msg": "x" * 500})
    _status, _code, msg = _diagnose_http_error(exc)
    assert msg is not None and len(msg) == 200
