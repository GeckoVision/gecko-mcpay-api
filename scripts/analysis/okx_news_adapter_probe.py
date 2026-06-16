"""Local repro of the PROD news path + raw-response introspection.

Reproduces what deployed gecko-api does (real OKXHttpNewsProvider via the
factory) AND dumps the raw OKX response shape so we can tell whether the empty
result is "no data returned" vs "data returned but field-name mismatch in the
article->chunk mapping". NEVER prints secrets (only public article fields +
non-sensitive code/msg).

Run:  set -a; source .env; set +a; GECKO_NEWS_PROVIDER=okx \
      uv run python scripts/analysis/okx_news_adapter_probe.py
"""

from __future__ import annotations

import asyncio

import httpx
from gecko_core.orchestration.trade_panel import okx_http_news_adapter as A
from gecko_core.orchestration.trade_panel.news_factory import build_news_provider

INPUTS = ["jupiter", "JUP", "SOL", "BTC", "ETH"]


async def _raw_dump(provider: A.OKXHttpNewsProvider, ccy: str) -> None:
    """Replicate the adapter's exact signed request and print the raw shape."""
    params = {"sortBy": "latest", "ccyList": ccy.upper(), "limit": 3}
    req = httpx.Request("GET", provider._base_url + A._NEWS_SEARCH_PATH, params=params)
    request_path = req.url.raw_path.decode("ascii")
    headers = provider._auth_headers("GET", request_path, body="")
    async with httpx.AsyncClient(timeout=6.0) as client:
        resp = await client.get(
            provider._base_url + A._NEWS_SEARCH_PATH, params=params, headers=headers
        )
    print(f"  [raw {ccy}] HTTP {resp.status_code} signed_path={request_path}")
    try:
        body = resp.json()
    except Exception:
        print(f"    non-JSON body: {resp.text[:200]!r}")
        return
    if isinstance(body, dict):
        data = body.get("data")
        n = len(data) if isinstance(data, list) else "n/a"
        print(f"    code={body.get('code')!r} msg={body.get('msg')!r} data_len={n}")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            print(f"    data[0] keys: {sorted(data[0].keys())}")
            details = data[0].get("details")
            if isinstance(details, list) and details and isinstance(details[0], dict):
                d0 = details[0]
                print(f"    details_len={len(details)}  details[0] keys: {sorted(d0.keys())}")
                for k in (
                    "title",
                    "headline",
                    "name",
                    "content",
                    "summary",
                    "fullText",
                    "body",
                    "description",
                    "url",
                    "link",
                    "publishTime",
                ):
                    if k in d0:
                        print(f"      {k!r}: {str(d0[k])[:80]!r}")
    else:
        print(f"    payload type={type(body).__name__}: {str(body)[:200]!r}")


async def main() -> None:
    provider = build_news_provider()
    print(f"provider built: {type(provider).__name__ if provider else None}")
    if provider is None:
        print("  -> news OFF. Stop.")
        return
    print("\n--- adapter fetch_news_chunks (the prod path) ---")
    for proto in INPUTS:
        chunks = await provider.fetch_news_chunks(proto, max_results=3)
        print(f"  {proto:9s} -> {len(chunks)} chunk(s)")
    print("\n--- raw OKX response introspection ---")
    for ccy in ("BTC", "JUP", "SOL"):
        await _raw_dump(provider, ccy)


if __name__ == "__main__":
    asyncio.run(main())
