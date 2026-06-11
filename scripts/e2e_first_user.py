"""End-to-end validator for ONE first-user profile (the "Profile 0" golden path).

Walks the exact loop a tester takes — onboard -> grant -> watch -> verdict — and
asserts each step, so you can configure a single profile and confirm the whole
stack is healthy (local or prod) before inviting the 10 users.

    BASE_URL=https://api.geckovision.tech \
    TEST_WALLET=<a 32-64 char wallet address> \
    uv run python scripts/e2e_first_user.py

Stub mode is free — no payment needed. The script is read-mostly + idempotent
(onboarding a wallet again just returns a fresh session); it never spends money.
Exits non-zero with a clear reason on any failure.
"""

from __future__ import annotations

import os
import sys
import time
from typing import Any

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")
# A default demo wallet (devnet-shaped); override with TEST_WALLET for a real profile.
TEST_WALLET = os.environ.get("TEST_WALLET", "8QURsrdasWeiLM9FXYkRgLUTG6J1nPi9rqGkx9tNQxV")
DEMO_IDEA = os.environ.get("DEMO_IDEA", "deposit USDC into Kamino")
DEMO_PROTOCOL = os.environ.get("DEMO_PROTOCOL", "kamino")
TIMEOUT = httpx.Timeout(90.0, connect=10.0)


def _fail(msg: str) -> None:
    print(f"FAIL  {msg}", file=sys.stderr)
    raise SystemExit(1)


def _ok(label: str, extra: str = "") -> None:
    print(f"OK    {label}{(' — ' + extra) if extra else ''}")


def main() -> int:
    print(f"Profile 0 → {BASE_URL}  (wallet {TEST_WALLET[:6]}…{TEST_WALLET[-4:]})\n")
    with httpx.Client(base_url=BASE_URL, timeout=TIMEOUT) as client:
        # 1. Link — mint a session.
        r = client.post("/v1/onboarding/link", json={"wallet_address": TEST_WALLET})
        if r.status_code // 100 != 2:
            _fail(f"POST /v1/onboarding/link → HTTP {r.status_code}\n{r.text[:300]}")
        body: dict[str, Any] = r.json()
        token = body.get("session_token")
        if not token:
            _fail(f"link returned no session_token: {body!r}")
        user_id = body.get("user_id", "?")
        _ok("link", f"user_id={user_id} custody={body.get('custody')}")
        auth = {"Authorization": f"Bearer {token}"}

        # 2. Grant — scope + (best-effort) bind an agent.
        r = client.post("/v1/onboarding/grant", headers=auth)
        if r.status_code // 100 != 2:
            _fail(f"POST /v1/onboarding/grant → HTTP {r.status_code}\n{r.text[:300]}")
        scope = r.json()
        _ok("grant", f"allowed={scope.get('allowed_actions')} revoked={scope.get('revoked')}")

        # 3. Agent state — retry on 404 (~10s; the bind is best-effort).
        deadline = time.time() + 12
        state: dict[str, Any] | None = None
        while time.time() < deadline:
            r = client.get("/v1/agent/state", headers=auth)
            if r.status_code == 404:
                time.sleep(2)
                continue
            if r.status_code // 100 != 2:
                _fail(f"GET /v1/agent/state → HTTP {r.status_code}\n{r.text[:300]}")
            state = r.json()
            break
        if state is None:
            _fail("GET /v1/agent/state stayed 404 for ~12s (no agent bound to this profile)")
        st = state.get("state")
        _ok(
            "agent/state",
            f"agent={state.get('agent_id')} strategy={state.get('strategy')} "
            f"state={'warming-up' if st is None else 'live'}",
        )

        # 4. Verdict — THE product. (In stub mode this is free.)
        r = client.post(
            "/v1/research",
            headers=auth,
            json={"idea": DEMO_IDEA, "protocol": DEMO_PROTOCOL, "vertical": "dex"},
        )
        if r.status_code == 402:
            _fail(
                "POST /v1/research → 402 (x402 not in stub, or no credits). Run prod in stub for the test."
            )
        if r.status_code // 100 != 2:
            _fail(f"POST /v1/research → HTTP {r.status_code}\n{r.text[:300]}")
        v = r.json()
        verdict = v.get("verdict")
        if verdict not in {"act", "pass", "defer"}:
            _fail(f"verdict not in act/pass/defer: {verdict!r}")
        dissent = v.get("dissent") or []
        cites = (v.get("evidence_citations") or []) + (v.get("framework_context") or [])
        _ok(
            "research/verdict",
            f"verdict={verdict} conf={v.get('confidence')} dissent={len(dissent)} citations={len(cites)}",
        )
        # The wedge: a real verdict should carry dissent + at least one citation.
        if not dissent:
            print(
                "WARN  verdict carried no surviving dissent (acceptable, but the wedge is the dissent).",
                file=sys.stderr,
            )
        if not cites:
            print(
                "WARN  verdict carried no citations — check the corpus is reaching the panel.",
                file=sys.stderr,
            )

    print("\nProfile 0: PASS — onboard → grant → watch → verdict all healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
