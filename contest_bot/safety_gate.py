"""Tier-1 fast safety veto — `POST /safety` against gecko-api.

This is the FAST deterministic pre-trade veto (PR #140). It runs on EVERY
entry candidate, before the considered oracle/cached-verdict tier (tier 2).
It is sub-second class: a few RPC/market calls + math on the API side, no
LLM panel, no retrieval.

Gate semantics (mirrors gecko_api.main._safety_gate):
  - ``block``   — hard stop: honeypot, fake market cap, depeg, manipulated.
  - ``caution`` — elevated manipulation / thin liquidity / concentration /
    un-renounced authority. The caller logs + proceeds (size-down is a
    future refinement).
  - ``ok``      — checked and clean → proceed to tier 2.
  - ``unknown`` — the check could not run → proceed (fail-OPEN).

FAIL-OPEN is non-negotiable: a `/safety` network error, timeout, or any
unexpected response must NEVER block the trading loop. On any failure this
returns ``SafetyGateResult(gate="unknown", ...)`` so the caller proceeds to
the considered tier — never a hard stop on infrastructure flakiness.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

# Base URL for the gecko-api service exposing POST /safety. Local-first
# default targets a locally-running gecko-api; flip via env for the
# parallel-ECS deploy (P3). Trailing slashes are stripped at call time.
_DEFAULT_API_URL = "http://127.0.0.1:8000"


def _api_url() -> str:
    return os.environ.get("GECKO_API_URL", _DEFAULT_API_URL).strip().rstrip("/")


def _timeout_s() -> float:
    # Sub-second class endpoint; the API itself caps the on-chain read at 4s
    # and fails-open. We give a little headroom over that, then fail-open here.
    return float(os.environ.get("GECKO_SAFETY_TIMEOUT_S", "5.0"))


def _enabled() -> bool:
    # Default ON. Set GECKO_SAFETY_GATE=0 to bypass the tier-1 call entirely
    # (e.g. fully-offline smoke runs); a bypass is recorded as gate="unknown".
    return os.environ.get("GECKO_SAFETY_GATE", "1").strip().lower() in ("1", "true", "yes")


@dataclass
class SafetyGateResult:
    """Outcome of the tier-1 `/safety` call for one candidate mint.

    ``gate`` is the one-glance recommendation. ``should_skip`` is True ONLY
    for a hard ``block``; ``caution``/``ok``/``unknown`` all proceed. ``raw``
    carries the full SafetyBlock dict for the decision record (may be empty
    on a fail-open path).
    """

    gate: str
    should_skip: bool
    reason: str
    raw: dict[str, Any] = field(default_factory=dict)

    def for_record(self) -> dict[str, Any]:
        """Compact projection for the decision/artifact ledger."""
        rec: dict[str, Any] = {"gate": self.gate, "reason": self.reason}
        # Surface the discriminating flags without dumping the whole block.
        if self.raw:
            rec["honeypot"] = self.raw.get("honeypot")
            rec["rug_flags"] = self.raw.get("rug_flags")
            imev = self.raw.get("information_mev")
            if isinstance(imev, dict):
                rec["information_mev_label"] = imev.get("label")
        return rec


def check_safety(mint: str) -> SafetyGateResult:
    """Call `POST /safety {mint}` and map the response to a gate decision.

    FAIL-OPEN on every error path: returns ``gate="unknown", should_skip=False``
    so the caller proceeds to the considered tier. Never raises.
    """
    if not _enabled():
        return SafetyGateResult(gate="unknown", should_skip=False, reason="safety_gate_disabled")

    url = f"{_api_url()}/safety"
    try:
        resp = httpx.post(url, json={"mint": mint}, timeout=_timeout_s())
        resp.raise_for_status()
        body = resp.json()
    except Exception as exc:
        return SafetyGateResult(
            gate="unknown",
            should_skip=False,
            reason=f"safety_call_error:{type(exc).__name__}",
        )

    gate = str(body.get("gate", "unknown"))
    if gate == "block":
        return SafetyGateResult(
            gate="block",
            should_skip=True,
            reason="safety_block",
            raw=body,
        )
    if gate == "caution":
        return SafetyGateResult(
            gate="caution",
            should_skip=False,
            reason="safety_caution",
            raw=body,
        )
    # ok / unknown / any unexpected value → proceed to tier 2 (fail-open).
    return SafetyGateResult(
        gate=gate if gate in ("ok", "unknown") else "unknown",
        should_skip=False,
        reason=f"safety_{gate}",
        raw=body,
    )
