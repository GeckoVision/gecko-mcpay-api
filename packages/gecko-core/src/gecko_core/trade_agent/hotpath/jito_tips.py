"""Jito tip-floor baseline — the live priority-fee/tip percentile market.

LEVERAGE item L2 from the Jito build map (the jito-mev-architect deep dive): the
public, keyless ``bundles.jito.wtf/api/v1/bundles/tip_floor`` endpoint returns the
current landed-tip percentiles (p25–p99 + EMA p50). It turns the firewall's
fee-outlier signal from a hardcoded threshold into a *dynamic* one — "is this tip
in the top 5% of what searchers are paying RIGHT NOW" — which cuts false positives
in high-MEV regimes (where everyone pays high fees) and catches urgency in calm
ones.

Tips are in **SOL** (e.g. 1e-6 SOL = 1000 lamports). High-confidence only in
combination (a p95 tip + same-slot co-buy + fresh wallet), low-value alone — see
the snipe-gate (B1).

Hotpath-clean: ``httpx`` + ``pydantic`` + stdlib. ``parse_tip_floor`` is pure
(testable against the recorded shape); the client is fail-OPEN to ``None`` so a
tip-floor outage never sinks a verdict.
"""

from __future__ import annotations

from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

TIP_FLOOR_URL = "https://bundles.jito.wtf/api/v1/bundles/tip_floor"


class TipFloor(BaseModel):
    """Current landed-tip percentiles (SOL)."""

    model_config = ConfigDict(extra="forbid")

    p25: float = Field(..., ge=0.0)
    p50: float = Field(..., ge=0.0)
    p75: float = Field(..., ge=0.0)
    p95: float = Field(..., ge=0.0)
    p99: float = Field(..., ge=0.0)
    ema_p50: float = Field(..., ge=0.0)
    time: str | None = None

    def tier(self, tip_sol: float) -> str:
        """Where ``tip_sol`` sits in the current market: p99+ / p95 / p75 / p50 / below."""
        if tip_sol >= self.p99:
            return "p99+"
        if tip_sol >= self.p95:
            return "p95"
        if tip_sol >= self.p75:
            return "p75"
        if tip_sol >= self.p50:
            return "p50"
        return "below"

    def is_outlier(self, tip_sol: float, *, at: str = "p95") -> bool:
        """True when ``tip_sol`` is at/above the given percentile — the urgency tell."""
        threshold = {"p50": self.p50, "p75": self.p75, "p95": self.p95, "p99": self.p99}.get(
            at, self.p95
        )
        return tip_sol >= threshold


def _f(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def parse_tip_floor(data: Any) -> TipFloor | None:
    """Decode the tip_floor response (a 1-element list) into :class:`TipFloor`.

    Returns ``None`` on any unexpected shape (fail-OPEN). Field names match the
    live endpoint: ``landed_tips_<n>th_percentile`` + ``ema_landed_tips_50th_percentile``.
    """
    row = data[0] if isinstance(data, list) and data else data
    if not isinstance(row, dict):
        return None
    p25 = _f(row.get("landed_tips_25th_percentile"))
    p50 = _f(row.get("landed_tips_50th_percentile"))
    p75 = _f(row.get("landed_tips_75th_percentile"))
    p95 = _f(row.get("landed_tips_95th_percentile"))
    p99 = _f(row.get("landed_tips_99th_percentile"))
    ema = _f(row.get("ema_landed_tips_50th_percentile"))
    if None in (p25, p50, p75, p95, p99, ema):
        return None
    return TipFloor(
        p25=p25,  # type: ignore[arg-type]
        p50=p50,  # type: ignore[arg-type]
        p75=p75,  # type: ignore[arg-type]
        p95=p95,  # type: ignore[arg-type]
        p99=p99,  # type: ignore[arg-type]
        ema_p50=ema,  # type: ignore[arg-type]
        time=row.get("time") if isinstance(row.get("time"), str) else None,
    )


class JitoTipsClient:
    """Keyless client for the Jito tip-floor REST endpoint. Fail-OPEN."""

    def __init__(
        self,
        *,
        url: str = TIP_FLOOR_URL,
        timeout: float = 6.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._timeout = timeout
        self._client = client

    async def fetch_tip_floor(self) -> TipFloor | None:
        """GET the current tip floor; ``None`` on any failure (never raises)."""
        try:
            if self._client is not None:
                resp = await self._client.get(self._url, timeout=self._timeout)
            else:
                async with httpx.AsyncClient(timeout=self._timeout) as c:
                    resp = await c.get(self._url)
            resp.raise_for_status()
            return parse_tip_floor(resp.json())
        except Exception:
            return None


__all__ = ["TIP_FLOOR_URL", "JitoTipsClient", "TipFloor", "parse_tip_floor"]
