"""S12-HARDEN — synthetic load smoke against the production-hardening surface.

Acceptance per Sprint 12 Track I: 50 rps for 60s with mixed payloads
shows the expected 429 / 400 / 503 rejection mix without any 500s,
unhandled exceptions, or runaway memory growth.

We compress the spec to ~5s of synthetic traffic in CI (full 60s x 50rps
is ~3000 requests, doable but slow against TestClient's blocking shim).
The shape — 429s / 400s / 503s appear, no 500s — is what we assert; the
duration is just enough to exercise all three guards.

This test does NOT spin up a network port; it uses Starlette's TestClient
which calls the ASGI app in-process. Concurrency is bounded by
ThreadPoolExecutor because TestClient is sync.
"""

from __future__ import annotations

import gc
import os
import sys
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> Iterator[TestClient]:
    os.environ.setdefault("X402_MODE", "stub")
    os.environ.setdefault("GECKO_WALLET_ADDRESS", "STUB_WALLET_ADDRESS_NOT_FOR_LIVE")
    for mod in [m for m in sys.modules if m.startswith("gecko_api")]:
        sys.modules.pop(mod, None)
    from gecko_api.main import app

    with TestClient(app) as c:
        yield c


def _measure_resident_memory_kb() -> int:
    """Best-effort RSS in KB. Returns 0 when /proc isn't available."""
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    parts = line.split()
                    return int(parts[1])
    except (FileNotFoundError, ValueError, IndexError):
        pass
    return 0


def test_synthetic_load_smoke_no_500s_memory_stable(client: TestClient) -> None:
    """Mixed-payload burst: 429s appear (rate), 400s appear (size cap),
    503s appear (breaker), zero 500s, no unhandled exceptions, RSS stable.

    The breaker check is the trickiest — we prime it explicitly so we
    don't have to pump enough estimated spend through the handlers to
    trip it organically (each /research adds $0.10 estimate; the handler
    rejection happens BEFORE the spend is recorded once the breaker is
    already open, so we need to pre-load the budget via the public hook).
    """
    from gecko_api.circuit_breaker import get_breaker, reset_breaker

    reset_breaker()

    valid_idea = "valid market validation idea " * 3  # ~90 chars
    huge_idea = "x" * 100_000  # triggers 400 from body-size middleware

    payloads = [
        # Valid 9KB (large but under cap) — first ~30 land as 402, rest 429.
        {
            "idea": valid_idea,
            "tier": "basic",
            "_padding": "x" * 8000,
        },
        # Invalid 100KB — must be 400 from body-size cap.
        {"idea": huge_idea, "tier": "basic"},
        # Valid no-payment — initial 402, then 429 once rate cap hit.
        {"idea": valid_idea, "tier": "basic"},
        # Valid with stub payment header — bypasses rate limit, hits x402 verify
        # which rejects bogus payloads with a 402; never 500.
        ({"idea": valid_idea, "tier": "basic"}, {"X-Payment": "bogus-bypass"}),
    ]

    rss_before = _measure_resident_memory_kb()

    def _one_request(idx: int) -> int:
        item = payloads[idx % len(payloads)]
        if isinstance(item, tuple):
            body, headers = item
            r = client.post("/research", json=body, headers=headers)
        else:
            r = client.post("/research", json=item)
        return r.status_code

    # 250 mixed requests — enough to exercise all three guards in <5s.
    total_requests = 250

    statuses: list[int] = []
    # Mid-burst, prime the cost breaker so 503 appears in the mix.
    breaker = get_breaker()
    for _ in range(60):
        breaker.record_spend(0.10)  # cumulative $6 → breaker opens

    with ThreadPoolExecutor(max_workers=8) as ex:
        for status in ex.map(_one_request, range(total_requests)):
            statuses.append(status)

    counts: dict[int, int] = {}
    for s in statuses:
        counts[s] = counts.get(s, 0) + 1

    # Hard assertions — no 5xx that isn't the breaker's intentional 503.
    bad_5xx = {code: n for code, n in counts.items() if 500 <= code < 600 and code != 503}
    assert not bad_5xx, f"unexpected 5xx in mix: {bad_5xx}; full mix: {counts}"

    # The three expected rejections must all appear at least once.
    assert counts.get(400, 0) > 0, f"no 400 (body-size) in mix: {counts}"
    assert counts.get(429, 0) > 0, f"no 429 (rate-limit) in mix: {counts}"
    assert counts.get(503, 0) > 0, f"no 503 (breaker) in mix: {counts}"

    # Memory: RSS shouldn't have ballooned. Allow 50MB headroom for the
    # buffered request bodies + Python GC churn. /proc not being available
    # falls back to skipping this check.
    gc.collect()
    rss_after = _measure_resident_memory_kb()
    if rss_before and rss_after:
        delta_kb = rss_after - rss_before
        assert delta_kb < 50_000, (
            f"RSS grew {delta_kb} KB during 250-request burst — {rss_before} → {rss_after}"
        )

    reset_breaker()
