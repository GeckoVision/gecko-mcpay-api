"""Pegana peg-risk feed (S48) — an ADD-ON depeg signal for the profit-vault.

Pegana (https://pegana.xyz) is an independent peg-risk oracle for Solana LSTs and
stables. We do NOT reinvent it — we CONSUME its `state` as a sharp depeg signal so
the vault can de-leverage / exit a collateral leg BEFORE a depeg blows it up. A
depeg is catastrophic regardless of APY, so this signal OVERRIDES the yield-based
monitor verdict (see `kamino/monitor.py`).

Design rules (the same discipline as `net_flow.py` / `shared_feed.py`):
  - **Best-effort, fail-open.** This is an ADDITIVE signal. If Pegana is down,
    slow, or returns garbage, `peg_states` returns `{}` (everything treated as
    UNKNOWN → no override) and the existing market-temp monitor still runs. We
    NEVER freeze the loop on an availability problem with an add-on.
  - **One call, not N.** `GET /v1/assets` returns every tracked asset in one
    response; we fetch it once and filter, rather than hitting the per-asset
    `/state` endpoint per leg. Per-asset is the fallback only.
  - **Throttle/cache.** The assets list barely changes intra-minute; a short TTL
    cache dedups fetches across the monitor cadence (reuses the basedbid_feed
    throttle idea — keep it simple).
  - **Injectable client.** `http_client=` lets tests run with NO real network.

REST shapes (public, no key — confirmed live 2026-06-06):
  GET /v1/assets
    → [{symbol, name, mint, class, peg_target, state, discount, intrinsic_usd,
        market_usd, confidence, thresholds:{critical_bps,depeg_bps,drift_bps}, ...}]
  GET /v1/assets/{SYMBOL}/state
    → {asset, state, since, discount, intrinsic_usd, market_usd}
  state ∈ PEGGED | DRIFT | DEPEG | CRITICAL | UNKNOWN
  discount is signed (negative = trading below intrinsic).
"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger("pegana_feed")

_PEGANA_BASE = "https://api.pegana.xyz/v1"
_HTTP_TIMEOUT = 8.0

# Peg states, most-severe first. UNKNOWN = no signal (fail-open default).
PEGGED = "PEGGED"
DRIFT = "DRIFT"
DEPEG = "DEPEG"
CRITICAL = "CRITICAL"
UNKNOWN = "UNKNOWN"

# ── Asset map: our vault legs → Pegana symbols ──────────────────────────────
# Keyed by `yield_source` (the monitor keys off this). A leg with no tracked
# asset → None → no depeg signal, leg unaffected. JLP is not currently tracked
# by Pegana; its USDC sleeve is, so the jlp_fees leg maps to USDC (the part we
# can actually watch) — if Pegana adds JLP, add it here.
#   conservative  stable_spread (USDC lend)      → USDC
#   moderate/aggr lst_staking   (JitoSOL/SOL)    → jitoSOL
#   aggressive    jlp_fees      (JLP/USDC)       → USDC
VAULT_LEG_TO_PEGANA: dict[str, str | None] = {
    "stable_spread": "USDC",
    "lst_staking": "jitoSOL",
    "jlp_fees": "USDC",  # JLP not tracked; watch the USDC sleeve
    "rwa_credit": None,  # off-chain credit — not a peg-tracked asset
    "equity": None,  # directional tokenized equity — no peg
}


def pegana_symbol_for(yield_source: str) -> str | None:
    """Pegana symbol for a vault leg's collateral asset, or None if untracked."""
    return VAULT_LEG_TO_PEGANA.get(yield_source)


class PeganaClient:
    """Best-effort client over the Pegana peg-risk REST API.

    `peg_states(symbols)` is the one method the vault calls. Everything is wrapped
    so ANY failure returns an empty/partial dict rather than raising — Pegana is an
    add-on, never a hard dependency.
    """

    def __init__(
        self,
        *,
        base_url: str = _PEGANA_BASE,
        http_client: httpx.Client | None = None,
        timeout: float = _HTTP_TIMEOUT,
        cache_ttl: float = 30.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client = http_client  # injectable for tests; None = real network
        self._timeout = timeout
        # Short TTL cache of the full /v1/assets list, keyed "_all". The list
        # barely changes intra-minute; this dedups fetches across the monitor
        # cadence and the gate within one tick window.
        self._cache_ttl = cache_ttl
        self._cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    # ── HTTP (best-effort) ───────────────────────────────────────────────────
    def _get(self, path: str) -> Any:
        url = f"{self._base}{path}"
        headers = {"Accept": "application/json", "User-Agent": "gecko-vault/0.1"}
        if self._client is not None:
            return self._client.get(url, headers=headers, timeout=self._timeout).json()
        with httpx.Client(timeout=self._timeout) as c:
            return c.get(url, headers=headers).json()

    def _fetch_all(self, now: float | None = None) -> list[dict[str, Any]]:
        """Fetch (and cache) the full /v1/assets list. Returns [] on any error."""
        t = now if now is not None else time.time()
        hit = self._cache.get("_all")
        if hit and (t - hit[0]) < self._cache_ttl:
            return hit[1]
        try:
            data = self._get("/assets")
            if not isinstance(data, list):
                raise ValueError(f"unexpected /assets payload: {type(data).__name__}")
            self._cache["_all"] = (t, data)
            return data
        except Exception as exc:  # fail-open: keep last-good if any, else []
            logger.warning("pegana _fetch_all swallow: %s", exc)
            return hit[1] if hit else []

    def _fetch_one(self, symbol: str) -> dict[str, Any] | None:
        """Per-asset fallback: GET /v1/assets/{SYMBOL}/state. None on any error."""
        try:
            data = self._get(f"/assets/{symbol}/state")
            if not isinstance(data, dict):
                return None
            return data
        except Exception as exc:
            logger.warning("pegana _fetch_one(%s) swallow: %s", symbol, exc)
            return None

    # ── public API ───────────────────────────────────────────────────────────
    def peg_states(
        self, symbols: list[str], *, now: float | None = None
    ) -> dict[str, dict[str, Any]]:
        """Map requested symbols → `{state, discount, confidence}`.

        Strategy: fetch /v1/assets ONCE and filter (one call covers every leg). If
        a requested symbol is missing from that list, fall back to the per-asset
        /state endpoint for just that symbol. On ANY error the result is empty or
        partial — a missing symbol simply has no signal (treated as UNKNOWN by the
        monitor). Symbol matching is case-insensitive (Pegana uses `jitoSOL`).
        """
        wanted = [s for s in (symbols or []) if s]
        if not wanted:
            return {}
        out: dict[str, dict[str, Any]] = {}
        try:
            all_assets = self._fetch_all(now=now)
            by_sym = {str(a.get("symbol", "")).lower(): a for a in all_assets if isinstance(a, dict)}
            for sym in wanted:
                row = by_sym.get(sym.lower())
                if row is not None:
                    out[sym] = self._normalize(row)
            # per-asset fallback for anything the list didn't cover (or empty list)
            for sym in wanted:
                if sym not in out:
                    row = self._fetch_one(sym)
                    if row is not None:
                        out[sym] = self._normalize(row)
        except Exception as exc:  # belt-and-suspenders fail-open
            logger.warning("pegana peg_states swallow: %s", exc)
            return out  # whatever we got before the error
        return out

    @staticmethod
    def _normalize(row: dict[str, Any]) -> dict[str, Any]:
        """Reduce a Pegana asset/state row to the fields the vault needs. Coerces a
        missing/garbage state to UNKNOWN (fail-open) and discount/confidence to
        float-or-None — never raises."""
        state = str(row.get("state") or UNKNOWN).upper()
        if state not in (PEGGED, DRIFT, DEPEG, CRITICAL, UNKNOWN):
            state = UNKNOWN
        return {
            "state": state,
            "discount": _as_float(row.get("discount")),
            "confidence": _as_float(row.get("confidence")),
        }


def _as_float(v: Any) -> float | None:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def peg_states_for_sources(
    yield_sources: list[str], client: PeganaClient | None = None
) -> dict[str, dict[str, Any]]:
    """Convenience for the orchestrator: given vault `yield_source` keys, resolve
    each to its Pegana symbol, fetch all peg states in ONE call, and return a map
    keyed by `yield_source` (so callers don't re-do the symbol mapping).

    Best-effort: a None client constructs a default one; ANY failure → {}. Legs
    with no tracked asset are simply absent from the result.
    """
    try:
        pairs = [(src, pegana_symbol_for(src)) for src in (yield_sources or [])]
        symbols = sorted({sym for _, sym in pairs if sym})
        if not symbols:
            return {}
        cli = client or PeganaClient()
        states = cli.peg_states(symbols)
        out: dict[str, dict[str, Any]] = {}
        for src, sym in pairs:
            if sym and sym in states:
                out[src] = states[sym]
        return out
    except Exception as exc:  # fail-open — never break the vault loop
        logger.warning("pegana peg_states_for_sources swallow: %s", exc)
        return {}
