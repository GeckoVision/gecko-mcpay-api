"""FundamentalsOracle — slow-cadence PRD verdict per instrument.

A parallel layer to the local panel. The local panel still gates trade
decisions on short-horizon TA. This oracle layer queries Gecko-PRD with
a *fundamentals / macro-regime / risk* prompt per instrument (NOT a
per-candidate momentum question) and caches the verdict per instrument
with a TTL. The bot's ``open_position`` does a SYNC cache lookup before
firing a trade and logs the cached verdict to the artifact ledger; the
fundamentals verdict is INFORMATIONAL and never blocks.

Why this exists
---------------
The PRD 7-voice panel cannot structurally grade short-horizon momentum
spot (no ``chart_analyst`` voice; ``technical_analyst`` was reframed at
S24 WS-A as ``macro_regime_analyst``). See
``docs/strategy/2026-05-20-panel-act-rate-on-momentum-spot.md`` for the
diagnosis. The fix is to ask the panel a question it CAN ground:
protocol fundamentals + macro regime + risk vectors, on a 24-48h
horizon. We cache aggressively (default 6h TTL) because the call is
~76s end-to-end — way too slow for per-candidate evaluation.

The x402 stub-payment dance mirrors ``GeckoGate._call_oracle`` in
``contest_bot/gecko_wrap.py`` (which mirrors the canonical
``gecko_core.trade_agent.oracle_client``). Stub-mode-only by contract;
the live flip is founder-only per ``project_x402_stub_then_live``.

Memory: ``project-local-lab-strategy-2026-05-20``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)

# ── Module constants ───────────────────────────────────────────────────
DEFAULT_API_BASE = "https://api.geckovision.tech"
DEFAULT_TTL_S = 6 * 60 * 60  # 6 hours
DEFAULT_TIMEOUT_S = 120.0  # PRD panel is genuinely ~76s; old 45s caused ReadTimeout

# Vertical mapping. Memes might be recognized by future vertical taxonomy;
# for v0.1 we route them through "dex" with a note. DEX/yield protocols
# all go through "dex" (canon per S38-#132 fix: vertical "defi" was
# silently dropped → "dex" is the canonical value).
_DEX_SYMBOLS = {"JTO", "JUP", "RAY", "ORCA", "PYTH", "HNT"}
_MEME_SYMBOLS = {"BONK", "WIF"}


# ── Data model ─────────────────────────────────────────────────────────
class FundamentalsVerdict(BaseModel):
    """Cached fundamentals + macro + risk read for one instrument."""

    model_config = ConfigDict(extra="allow")

    instrument: str
    protocol: str
    verdict: Literal["act", "pass", "defer"]
    confidence: float
    key_drivers: list[str] = Field(default_factory=list)
    blocker_questions: list[str] = Field(default_factory=list)
    citations_count: int = 0
    # Sprint 20 #3 (2026-05-28) — structured dissent surface from the L1
    # Oracle. Each entry: {"voice": str, "stance": "oppose"|"abstain",
    # "verbatim": str, "on_topic": str}. Default [] when the Oracle is
    # pre-Sprint-18 OR the panel was unanimous (consensus IS the signal).
    # Consumed by the bot's [ORACLE] log line + dashboard Oracle panel
    # to render the Dissent: line Marina sees on every trade decision.
    dissent: list[dict[str, Any]] = Field(default_factory=list)
    dissent_count: int = 0
    ts: datetime
    ttl_seconds: int = DEFAULT_TTL_S
    raw_envelope: dict[str, Any] = Field(default_factory=dict)

    def is_fresh(self, now: datetime | None = None) -> bool:
        now = now or datetime.now(UTC)
        return (now - self.ts) < timedelta(seconds=self.ttl_seconds)


# ── Errors ─────────────────────────────────────────────────────────────
class _OracleCallError(Exception):
    """Internal — raised on any call-path failure. Never leaks past the
    public API; callers see ``None`` (cache miss / degraded mode)."""


# ── Helpers ────────────────────────────────────────────────────────────
def _vertical_for(symbol: str) -> tuple[str, str | None]:
    """Return ``(vertical, note)``. Note is non-None when we fell through
    to ``dex`` because the requested vertical isn't recognized."""
    sym = symbol.upper()
    if sym in _DEX_SYMBOLS:
        return "dex", None
    if sym in _MEME_SYMBOLS:
        # The trade vertical may recognize "meme" in future. For v0.1 we
        # default to "dex" but emit a note so the artifact log shows we
        # consciously fell through.
        return "dex", f"vertical=meme not yet wired; routing {sym} through 'dex'"
    return "dex", f"unknown symbol {sym}; defaulting to 'dex'"


def _build_idea(instrument: str, protocol: str) -> str:
    """Build the fundamentals/regime/risk prompt.

    The framing tells the panel explicitly NOT to grade short-horizon TA
    (which they cannot ground) and TO grade fundamentals + risk + macro
    (which they can). Honest-abstain (defer) on ungrounded fundamentals
    is correct behavior, not failure.
    """
    return (
        f"Evaluate the Solana protocol {protocol} ({instrument}) for long-position "
        f"suitability over the next 24-48 hours.\n\n"
        f"Context: an automated trading bot evaluates short-horizon TA setups on this "
        f"token using a separate chart-grading layer. Your job is NOT to grade chart "
        f"patterns or 5m breakouts.\n\n"
        f"Your job is to assess long-position suitability from a VALUE + RISK + REGIME "
        f"perspective:\n"
        f"- Protocol fundamentals: TVL trend, fee/revenue trajectory, dev activity, "
        f"governance state, ecosystem position.\n"
        f"- Risk vectors: audit status, known security incidents, smart-contract risk, "
        f"oracle/liquidity dependencies.\n"
        f"- Macro regime: BTC cycle position, risk-on vs risk-off, broader market "
        f"context, capital flows.\n"
        f"- Narrative/sentiment: ecosystem momentum, competitive position, recent "
        f"news/governance.\n\n"
        f"Issue a verdict (act / pass / defer) reflecting whether long positions in "
        f"{protocol} are *reasonable* given the above. Do NOT grade short-horizon TA. "
        f"If the canon does not ground a confident view on fundamentals/regime/risk, "
        f"abstain (defer) honestly — that is correct behavior, not failure."
    )


def _safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        parsed = response.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise _OracleCallError(f"response was not valid JSON: {response.text[:160]!r}") from exc
    if not isinstance(parsed, dict):
        raise _OracleCallError(f"response was not a JSON object: {type(parsed).__name__}")
    return parsed


def _coerce_verdict(raw: Any) -> Literal["act", "pass", "defer"]:
    v = str(raw or "").strip().lower()
    if v in ("act", "pass", "defer"):
        return v  # type: ignore[return-value]
    # Map common synonyms onto our 3-token taxonomy. Anything we can't
    # parse becomes "defer" — the safe, honest default.
    if v in ("ship", "build", "buy", "yes", "allow"):
        return "act"
    if v in ("kill", "no", "block", "reject"):
        return "pass"
    return "defer"


# ── FundamentalsOracle ─────────────────────────────────────────────────
class FundamentalsOracle:
    """PRD fundamentals/regime/risk oracle with per-instrument cache.

    Calls are EXPENSIVE (~76s wall) — we fire them at session start in
    parallel via ``preload_for_instruments`` and on-demand via
    ``refresh_if_stale``. Never per-candidate.
    """

    def __init__(
        self,
        *,
        api_base: str = DEFAULT_API_BASE,
        stub_mode: bool = True,
        ttl_seconds: int = DEFAULT_TTL_S,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not stub_mode:
            # Mirrors GeckoGate's contract — live x402 signing is a
            # founder-only flip and isn't wired in the contest layer.
            raise ValueError(
                "FundamentalsOracle v0.1 requires stub_mode=True; live x402 "
                "signing is not wired (founder-only flip)."
            )
        self._stub_mode = stub_mode
        self._api_base = api_base.rstrip("/")
        self._ttl_seconds = ttl_seconds
        self._timeout_s = timeout_s
        self._http_client = http_client
        self._owns_client = http_client is None
        self._cache: dict[str, FundamentalsVerdict] = {}

    # ── HTTP client lifecycle ─────────────────────────────────────────
    def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(timeout=self._timeout_s)
        return self._http_client

    async def close(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    # ── Public API ────────────────────────────────────────────────────
    async def preload_for_instruments(
        self, instruments: list[dict[str, Any]]
    ) -> dict[str, FundamentalsVerdict]:
        """Fire one call per instrument in PARALLEL via ``asyncio.gather``.

        Each call takes ~76s but they run concurrently — total wall is
        ~80-100s for 8 instruments. Per-call failures are isolated: a
        single 500 doesn't poison the batch. The returned dict only
        contains successful verdicts; failed instruments are absent
        (lookup later → ``None`` → degraded mode).
        """
        tasks = [self._fetch_one(inst) for inst in instruments]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        out: dict[str, FundamentalsVerdict] = {}
        for inst, result in zip(instruments, results, strict=False):
            sym = str(inst.get("symbol") or "").upper()
            if isinstance(result, BaseException):
                logger.warning(
                    "fundamentals: preload failed for %s: %s",
                    sym,
                    result,
                )
                continue
            if result is None:
                continue
            out[sym] = result
            self._cache[sym] = result
        return out

    def get_for_instrument(self, instrument: str) -> FundamentalsVerdict | None:
        """SYNC lookup. Returns the cached verdict if fresh, else ``None``.

        ``None`` means "no fundamentals data" — caller treats it as
        degraded mode and proceeds without the side note.
        """
        sym = instrument.upper()
        cached = self._cache.get(sym)
        if cached is None:
            return None
        if not cached.is_fresh():
            return None
        return cached

    async def refresh_if_stale(self, instrument: str, protocol: str) -> FundamentalsVerdict | None:
        """If cached verdict is stale (or missing), fire a fresh PRD call.
        Otherwise return the cached value untouched."""
        sym = instrument.upper()
        cached = self._cache.get(sym)
        if cached is not None and cached.is_fresh():
            return cached
        verdict = await self._fetch_one({"symbol": sym, "protocol": protocol})
        if verdict is not None:
            self._cache[sym] = verdict
        return verdict

    # ── Internal: one-shot fetch ──────────────────────────────────────
    async def _fetch_one(self, instrument: dict[str, Any]) -> FundamentalsVerdict | None:
        sym = str(instrument.get("symbol") or "").upper()
        if not sym:
            return None
        # Allow caller to pre-specify a protocol name; default to the
        # lowercased symbol (matches the trade-vertical canon norm).
        protocol = str(instrument.get("protocol") or sym).lower()
        vertical, note = _vertical_for(sym)
        if note:
            logger.info("fundamentals: %s", note)

        idea = _build_idea(sym, protocol)
        body = {"idea": idea, "vertical": vertical, "protocol": protocol}
        url = f"{self._api_base}/trade_research"
        try:
            envelope = await self._call_oracle(url, body)
        except _OracleCallError as exc:
            logger.warning("fundamentals: oracle call failed for %s (%s)", sym, exc)
            return None

        verdict_raw = envelope.get("verdict")
        verdict = _coerce_verdict(verdict_raw)
        try:
            confidence = float(envelope.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        drivers_raw = envelope.get("key_drivers") or []
        key_drivers = [str(x) for x in drivers_raw] if isinstance(drivers_raw, list) else []
        # Sprint 20 #3: blocker_questions and dissent are NOW DISTINCT surfaces
        # on the L1 envelope (Sprint 18 #3 made dissent a structured list of
        # DissentEntry dicts, NOT a fallback for blockers). The old fallback
        # `or envelope.get("dissent")` would str()-ify those dicts into
        # blockers, polluting the artifact log. Read each from its own key.
        blockers_raw = envelope.get("blocker_questions") or envelope.get("blockers") or []
        blocker_questions = [str(x) for x in blockers_raw] if isinstance(blockers_raw, list) else []
        cites = envelope.get("evidence_citations") or envelope.get("citations") or []
        citations_count = len(cites) if isinstance(cites, list) else 0

        # Sprint 20 #3 — structured dissent surface. Pass dict-shape through
        # unchanged (the bot reads voice/stance/verbatim/on_topic at render
        # time); skip non-dict entries defensively so a malformed server-side
        # entry doesn't crash the verdict construction.
        dissent_raw = envelope.get("dissent") or []
        if isinstance(dissent_raw, list):
            dissent = [d for d in dissent_raw if isinstance(d, dict) and d.get("voice")]
        else:
            dissent = []
        dissent_count_raw = envelope.get("dissent_count")
        try:
            dissent_count = (
                int(dissent_count_raw) if dissent_count_raw is not None else len(dissent)
            )
        except (TypeError, ValueError):
            dissent_count = len(dissent)

        return FundamentalsVerdict(
            instrument=sym,
            protocol=protocol,
            verdict=verdict,
            confidence=confidence,
            key_drivers=key_drivers,
            blocker_questions=blocker_questions,
            citations_count=citations_count,
            dissent=dissent,
            dissent_count=dissent_count,
            ts=datetime.now(UTC),
            ttl_seconds=self._ttl_seconds,
            raw_envelope=envelope,
        )

    # ── Internal: x402 stub-payment dance ─────────────────────────────
    async def _call_oracle(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """Mirrors ``GeckoGate._call_oracle`` — async variant.

        402 probe → decode payment-required → base64 stub payload →
        retry with ``PAYMENT-SIGNATURE`` + ``X-PAYMENT`` headers → 200.
        """
        client = self._client()
        try:
            probe = await client.post(url, json=body, headers={"Content-Type": "application/json"})
        except httpx.HTTPError as exc:
            raise _OracleCallError(f"probe transport error: {type(exc).__name__}: {exc}") from exc

        if probe.status_code == 200:
            return _safe_json(probe)

        if probe.status_code != 402:
            raise _OracleCallError(
                f"probe returned {probe.status_code} (expected 402): {probe.text[:160]!r}"
            )

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

        stub_payload = {
            "x402Version": 2,
            "payload": {"signature": "stub-sig", "transaction": "stub-tx"},
            "accepted": accepts[0],
        }
        sig = base64.b64encode(
            json.dumps(stub_payload, separators=(",", ":")).encode("utf-8")
        ).decode("ascii")

        try:
            paid = await client.post(
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


__all__ = [
    "DEFAULT_API_BASE",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_TTL_S",
    "FundamentalsOracle",
    "FundamentalsVerdict",
]
