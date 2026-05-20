"""Gecko wrap layer for the OKX Agentic Trading Contest baseline bot.

Three self-contained components wrapped around the bot's entry path:

1. :class:`GeckoGate` — calls ``/trade_research`` via the canonical x402
   stub-payment dance (mirrors
   ``packages/gecko-core/src/gecko_core/trade_agent/oracle_client.py``)
   and returns a binary allow/block decision plus the raw envelope.

2. :class:`HourlyCircuitBreaker` — disk-persisted rolling-60m PnL
   tracker. Pauses entries when cumulative PnL over the last hour
   drops below ``-$3`` (per the EV-analysis brief). Survives bot
   restarts via ``circuit_breaker_state.json``.

3. :class:`ArtifactLogger` — append-only JSONL ledger for every
   decision-point / verdict / position-open / position-close /
   breaker-fire. Rows are immutable; outcome patches append a NEW
   row referencing the original by ``decision_id``.

The wrap is fully self-contained under ``contest_bot/``. It does not
import from ``gecko_core``, does not touch the deployed
``api.geckovision.tech`` config, and hard-defaults to ``stub_mode=True``
per the founder's intentional ``X402_MODE=stub`` posture
(``project_x402_stub_then_live``).

Style/pattern notes
-------------------
* The 402-then-paid handshake is copied verbatim in spirit from
  ``oracle_client.py`` — same accepted echo, same base64 JSON
  envelope, same dual header (``PAYMENT-SIGNATURE`` + ``X-PAYMENT``).
* Live x402 signing is intentionally NOT wired here (the contest
  baseline must run stub).
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import time
import uuid
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ── Module constants ───────────────────────────────────────────────────
DEFAULT_API_BASE = "https://api.geckovision.tech"
DEFAULT_GATE_CACHE_TTL_S = 5 * 60  # 5 minutes
DEFAULT_GATE_TIMEOUT_S = 45.0
DEFAULT_GATE_MIN_CONFIDENCE = 0.6

DEFAULT_BREAKER_THRESHOLD_USD = -3.0
DEFAULT_BREAKER_WINDOW_S = 60 * 60  # 60-minute rolling window
DEFAULT_BREAKER_PAUSE_S = 60 * 60  # 60-minute pause after trip

_STATE_DIR = Path(__file__).parent
DEFAULT_BREAKER_STATE_PATH = _STATE_DIR / "circuit_breaker_state.json"

X402Mode = Literal["stub", "live"]
DecisionKind = Literal[
    "gate_call",
    "gate_allow",
    "gate_block",
    "gate_error",
    "breaker_check",
    "breaker_trip",
    "position_open",
    "position_close",
    "outcome_patch",
]


# ── Data models ────────────────────────────────────────────────────────
class GateDecision(BaseModel):
    """Binary allow/block decision plus the supporting verdict envelope."""

    model_config = ConfigDict(extra="allow")

    allow: bool
    verdict: str
    confidence: float
    key_drivers: list[str] = Field(default_factory=list)
    citations_count: int = 0
    decision_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    cached: bool = False
    error: str | None = None
    raw_envelope: dict[str, Any] = Field(default_factory=dict)


# ── Helpers ────────────────────────────────────────────────────────────
def _utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _round_market_state_for_hash(market_state: dict[str, Any]) -> dict[str, Any]:
    """Round market state floats so trivially-different ticks share a
    cache entry. Spot rounded to 0.5%, deltas/range to 0.5%."""
    out: dict[str, Any] = {}
    spot = market_state.get("spot_price")
    if isinstance(spot, (int, float)) and spot:
        # round to 0.5% buckets
        bucket = float(spot) * 0.005
        out["spot_bucket"] = round(float(spot) / bucket) if bucket else 0
    for k in ("change_24h_pct", "change_1h_pct", "range_24h_pct"):
        v = market_state.get(k)
        if isinstance(v, (int, float)):
            out[k] = round(float(v) * 2) / 2  # 0.5% buckets
    vol = market_state.get("volume_24h")
    if isinstance(vol, (int, float)) and vol:
        out["vol_oom"] = round(float(vol), -3)  # round to nearest 1000
    return out


def _build_idea(instrument: str, market_state: dict[str, Any]) -> str:
    """Build the verdict-prompt idea string from a poll snapshot.

    Mirrors the shape used in ``/tmp/gecko_demo_poll.py`` — keep this
    structure so the panel sees consistent prompts across calls.
    """
    spot = market_state.get("spot_price")
    d24 = market_state.get("change_24h_pct")
    d1h = market_state.get("change_1h_pct")
    rng = market_state.get("range_24h_pct")

    def _fmt(v: Any, fmt: str = "{:.4f}") -> str:
        return fmt.format(float(v)) if isinstance(v, (int, float)) else "n/a"

    def _pct(v: Any) -> str:
        if not isinstance(v, (int, float)):
            return "n/a"
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.2f}%"

    return (
        f"Should I open a long position in {instrument.upper()} on Solana right now? "
        f"Spot ${_fmt(spot)}, 24h Δ {_pct(d24)}, last 1h Δ {_pct(d1h)}, "
        f"24h range {_fmt(rng, '{:.2f}')}%. "
        f"Strict gate: act only on high-confidence trend confirmation. "
        f"Target +5% TP, -3% SL, 12h time-stop."
    )


# ── GeckoGate ──────────────────────────────────────────────────────────
class GeckoGate:
    """Verdict-gated entry filter.

    The bot calls :meth:`check_entry` BEFORE firing ``swap_execute``.
    Block is the safe default — every error path returns ``allow=False``
    so a transient oracle outage cannot accidentally green-light a bad
    entry.
    """

    def __init__(
        self,
        *,
        stub_mode: bool = True,
        api_base: str = DEFAULT_API_BASE,
        timeout_s: float = DEFAULT_GATE_TIMEOUT_S,
        min_confidence: float = DEFAULT_GATE_MIN_CONFIDENCE,
        cache_ttl_s: float = DEFAULT_GATE_CACHE_TTL_S,
        http_client: httpx.Client | None = None,
    ) -> None:
        # Hardcoded contract for v1: stub-mode only. Param exposed for
        # future flexibility; raise loudly if anyone tries to flip.
        if not stub_mode:
            raise ValueError(
                "GeckoGate v1 requires stub_mode=True; live x402 signing "
                "is not wired in the contest wrap (founder-only flip)."
            )
        self._stub_mode = stub_mode
        self._api_base = api_base.rstrip("/")
        self._timeout_s = timeout_s
        self._min_confidence = min_confidence
        self._cache_ttl_s = cache_ttl_s
        self._http_client = http_client
        self._owns_client = http_client is None
        self._cache: dict[str, tuple[float, GateDecision]] = {}

    def _client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=self._timeout_s)
        return self._http_client

    def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def _cache_key(self, instrument: str, market_state: dict[str, Any]) -> str:
        rounded = _round_market_state_for_hash(market_state)
        payload = json.dumps(
            {"i": instrument.lower(), "m": rounded},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]

    async def check_entry(
        self,
        instrument: str,
        market_state: dict[str, Any],
    ) -> GateDecision:
        """Return a :class:`GateDecision`. Never raises; errors → block."""
        cache_key = self._cache_key(instrument, market_state)
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached is not None and (now - cached[0]) < self._cache_ttl_s:
            decision = cached[1].model_copy(update={"cached": True})
            return decision

        idea = _build_idea(instrument, market_state)
        body = {
            "idea": idea,
            "vertical": "dex",
            "protocol": instrument.lower(),
        }
        url = f"{self._api_base}/trade_research"

        try:
            envelope = self._call_oracle(url, body)
        except _OracleCallError as exc:
            logger.warning("gecko_gate: oracle call failed (%s); blocking entry", exc)
            return GateDecision(
                allow=False,
                verdict="error",
                confidence=0.0,
                key_drivers=[],
                citations_count=0,
                error=str(exc),
                raw_envelope={},
            )

        verdict = str(envelope.get("verdict") or "unknown")
        try:
            confidence = float(envelope.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        key_drivers_raw = envelope.get("key_drivers") or []
        key_drivers = [str(x) for x in key_drivers_raw] if isinstance(key_drivers_raw, list) else []
        cites = envelope.get("evidence_citations") or envelope.get("citations") or []
        citations_count = len(cites) if isinstance(cites, list) else 0

        allow = verdict == "act" and confidence >= self._min_confidence

        decision = GateDecision(
            allow=allow,
            verdict=verdict,
            confidence=confidence,
            key_drivers=key_drivers,
            citations_count=citations_count,
            raw_envelope=envelope,
        )
        self._cache[cache_key] = (now, decision)
        return decision

    # ── Internal: x402 stub-payment dance ──────────────────────────────
    def _call_oracle(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """Replicates ``oracle_client._build_stub_payment_header`` flow.

        Synchronous (httpx.Client) so the polling-loop bot can call it
        from inside an ``asyncio.run(...)`` without dragging an async
        client across the sync boundary.
        """
        client = self._client()
        try:
            probe = client.post(url, json=body, headers={"Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise _OracleCallError(f"probe transport error: {type(exc).__name__}: {exc}") from exc

        if probe.status_code == 200:
            return _safe_json(probe)

        if probe.status_code != 402:
            raise _OracleCallError(
                f"probe returned {probe.status_code} (expected 402): {probe.text[:160]!r}"
            )

        # Decode the x402 challenge.
        raw_header = (
            probe.headers.get("payment-required")
            or probe.headers.get("PAYMENT-REQUIRED")
            or probe.headers.get("X-Payment-Required")
        )
        if not raw_header:
            raise _OracleCallError("402 response missing payment-required header")
        try:
            challenge = json.loads(base64.b64decode(raw_header).decode("utf-8"))
        except (ValueError, json.JSONDecodeError) as exc:
            raise _OracleCallError(f"could not decode payment-required header: {exc}") from exc
        accepts = challenge.get("accepts") if isinstance(challenge, dict) else None
        if not isinstance(accepts, list) or not accepts or not isinstance(accepts[0], dict):
            raise _OracleCallError("402 challenge had empty/invalid accepts[]")

        # Build stub payment payload — verbatim shape from
        # gecko_core.trade_agent.oracle_client._build_stub_payment_header.
        stub_payload = {
            "x402Version": 2,
            "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
            "accepted": accepts[0],
        }
        sig = base64.b64encode(
            json.dumps(stub_payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

        try:
            paid = client.post(
                url,
                json=body,
                headers={
                    "Content-Type": "application/json",
                    "PAYMENT-SIGNATURE": sig,
                    "X-PAYMENT": sig,
                },
            )
        except httpx.HTTPError as exc:
            raise _OracleCallError(
                f"paid-retry transport error: {type(exc).__name__}: {exc}"
            ) from exc

        if paid.status_code != 200:
            raise _OracleCallError(f"paid-retry returned {paid.status_code}: {paid.text[:160]!r}")
        return _safe_json(paid)


class _OracleCallError(Exception):
    """Internal — raised by ``_call_oracle`` on any failure path. Never
    leaks to the caller; ``check_entry`` converts to ``allow=False``."""


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise _OracleCallError(f"response was not valid JSON: {response.text[:160]!r}") from exc
    if not isinstance(parsed, dict):
        raise _OracleCallError(f"response was not a JSON object: {type(parsed).__name__}")
    return parsed


# ── HourlyCircuitBreaker ──────────────────────────────────────────────
class HourlyCircuitBreaker:
    """Rolling-60m PnL tracker with 60m pause on trip.

    Persisted to a JSON file so a bot restart doesn't reset the
    rolling window or the pause-until timestamp.
    """

    def __init__(
        self,
        *,
        threshold_usd: float = DEFAULT_BREAKER_THRESHOLD_USD,
        window_s: float = DEFAULT_BREAKER_WINDOW_S,
        pause_s: float = DEFAULT_BREAKER_PAUSE_S,
        state_path: Path | str = DEFAULT_BREAKER_STATE_PATH,
    ) -> None:
        self._threshold_usd = threshold_usd
        self._window_s = window_s
        self._pause_s = pause_s
        self._state_path = Path(state_path)
        self._deltas: deque[tuple[float, float]] = deque()  # (ts, delta)
        self._paused_until: float = 0.0
        self._load()

    # ── Persistence ────────────────────────────────────────────────────
    def _load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            raw = json.loads(self._state_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("circuit_breaker: could not load state (%s); starting clean", exc)
            return
        deltas = raw.get("deltas") or []
        for entry in deltas:
            if (
                isinstance(entry, list)
                and len(entry) == 2
                and isinstance(entry[0], (int, float))
                and isinstance(entry[1], (int, float))
            ):
                self._deltas.append((float(entry[0]), float(entry[1])))
        paused_until = raw.get("paused_until")
        if isinstance(paused_until, (int, float)):
            self._paused_until = float(paused_until)

    def _save(self) -> None:
        try:
            payload = {
                "deltas": [[ts, d] for ts, d in self._deltas],
                "paused_until": self._paused_until,
                "updated_at": _utc_iso(),
            }
            self._state_path.write_text(json.dumps(payload, separators=(",", ":")))
        except OSError as exc:
            logger.warning("circuit_breaker: could not persist state: %s", exc)

    # ── Public API ─────────────────────────────────────────────────────
    def _prune(self, now: float | None = None) -> None:
        cutoff = (now if now is not None else time.time()) - self._window_s
        while self._deltas and self._deltas[0][0] < cutoff:
            self._deltas.popleft()

    def record_pnl_delta(self, delta_usd: float, ts: float | None = None) -> None:
        """Append a PnL delta to the rolling window. Called on every
        mark-to-market tick AND every realized close (with the realized
        delta). Triggers the trip evaluation eagerly."""
        if ts is None:
            ts = time.time()
        self._deltas.append((ts, float(delta_usd)))
        self._prune(ts)
        cumulative = sum(d for _, d in self._deltas)
        if cumulative <= self._threshold_usd and ts >= self._paused_until:
            self._paused_until = ts + self._pause_s
            logger.warning(
                "circuit_breaker: tripped — rolling 60m PnL %.2f USD <= %.2f; pausing %.0fs",
                cumulative,
                self._threshold_usd,
                self._pause_s,
            )
        self._save()

    def check(self) -> tuple[bool, str]:
        """Return ``(paused, reason)``. Cheap — read-only side effects."""
        now = time.time()
        self._prune(now)
        if now < self._paused_until:
            remaining = self._paused_until - now
            cumulative = sum(d for _, d in self._deltas)
            return (
                True,
                f"hourly_circuit_breaker tripped: rolling PnL "
                f"{cumulative:+.2f} USD; pause {remaining:.0f}s remaining",
            )
        return False, "ok"

    def cumulative_pnl(self) -> float:
        self._prune()
        return float(sum(d for _, d in self._deltas))


# ── ArtifactLogger ─────────────────────────────────────────────────────
class ArtifactLogger:
    """Append-only JSONL ledger.

    Rows are immutable. To patch an outcome, append a NEW
    ``outcome_patch`` row that references the original by ``decision_id``.
    """

    def __init__(self, *, directory: Path | str | None = None) -> None:
        self._dir = Path(directory) if directory is not None else _STATE_DIR

    @property
    def current_path(self) -> Path:
        day = datetime.now(UTC).strftime("%Y%m%d")
        return self._dir / f"artifact_{day}.jsonl"

    def log(
        self,
        kind: DecisionKind,
        payload: dict[str, Any],
        *,
        decision_id: str | None = None,
    ) -> str:
        """Append one row. Returns the row's ``decision_id`` for later
        outcome-patch references."""
        row_id = decision_id or uuid.uuid4().hex
        row = {
            "decision_id": row_id,
            "kind": kind,
            "ts": _utc_iso(),
            "payload": payload,
        }
        path = self.current_path
        path.parent.mkdir(parents=True, exist_ok=True)
        # Open in append-text mode; one row = one line; never rewrite.
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
        return row_id

    def patch_outcome(self, original_decision_id: str, outcome: dict[str, Any]) -> str:
        """Append an outcome-patch row referencing the original."""
        return self.log(
            "outcome_patch",
            {"references": original_decision_id, "outcome": outcome},
        )


__all__ = [
    "DEFAULT_API_BASE",
    "DEFAULT_BREAKER_PAUSE_S",
    "DEFAULT_BREAKER_STATE_PATH",
    "DEFAULT_BREAKER_THRESHOLD_USD",
    "DEFAULT_BREAKER_WINDOW_S",
    "DEFAULT_GATE_CACHE_TTL_S",
    "DEFAULT_GATE_MIN_CONFIDENCE",
    "DEFAULT_GATE_TIMEOUT_S",
    "ArtifactLogger",
    "DecisionKind",
    "GateDecision",
    "GeckoGate",
    "HourlyCircuitBreaker",
    "X402Mode",
]
