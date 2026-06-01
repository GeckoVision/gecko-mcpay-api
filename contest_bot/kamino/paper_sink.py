"""Sprint 25 (#117, #141): Kamino paper-sink orchestrator.

Best-effort: every public method that the bot loop calls into is wrapped
so an exception NEVER escapes back into the close_position path. The bot
must keep trading even if Kamino's REST endpoint is down, our env is
malformed, or the JSONL ledger can't be written.

Disabled by default. Flip via `GECKO_KAMINO_PAPER_SINK=1` per launcher.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from kamino.apy_cache import KaminoAPYCache
from kamino.paper_ledger import DuplicateEventError, PaperLedger, default_ledger_path

logger = logging.getLogger("kamino.paper_sink")

_ENV_FLAG = "GECKO_KAMINO_PAPER_SINK"
_ENV_DEPOSIT_THRESHOLD = "GECKO_KAMINO_DEPOSIT_THRESHOLD_USD"
_ENV_DEPOSIT_RESERVE = "GECKO_KAMINO_DEPOSIT_RESERVE_USD"

_DEFAULT_THRESHOLD = 10.00
_DEFAULT_RESERVE = 5.00


@dataclass
class KaminoPaperSink:
    """Stateful, idempotent paper sink.

    Construct ONCE per bot process (see `get_default_sink`). The sink
    holds the apy-cache + ledger. Call `on_position_close(...)` from the
    bot's close-position site; that method is best-effort and never
    raises.
    """

    ledger: PaperLedger
    apy_cache: KaminoAPYCache
    deposit_threshold_usd: float = _DEFAULT_THRESHOLD
    deposit_reserve_usd: float = _DEFAULT_RESERVE
    enabled: bool = True

    # diagnostics — non-load-bearing
    last_action: str = field(default="none", init=False)
    last_error: str | None = field(default=None, init=False)

    # ── Public, best-effort entry points ───────────────────────────────

    def on_position_close(
        self,
        *,
        idle_usdc: float,
        decision_id: str,
        now: float | None = None,
    ) -> dict | None:
        """Called from contest_bot.close_position after `report_close`.

        - `idle_usdc`: the wallet's currently-available USDC AFTER the close
          settled (i.e. the close's proceeds are included). The sink decides
          how much of this to sweep into Kamino.
        - `decision_id`: the closing position's decision_id; doubles as
          the idempotency key so re-invocation on the same close is a no-op.

        Returns the ledger event on success, or None if no deposit was made
        (sink disabled, below threshold, duplicate event, error).
        """
        if not self.enabled:
            self.last_action = "skipped:disabled"
            return None
        try:
            return self._safe_deposit(
                idle_usdc=idle_usdc,
                decision_id=decision_id,
                now=now,
            )
        except Exception as exc:
            self.last_action = "error"
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "kamino paper_sink swallow on close (%s): %s",
                type(exc).__name__,
                exc,
            )
            return None

    def withdraw_for_entry(
        self,
        *,
        amount_usd: float,
        decision_id: str,
        now: float | None = None,
    ) -> dict | None:
        """Documented v2 hook — NOT wired in S25. Withdraws `amount_usd`
        from the simulated Kamino position to fund an entry. Returns the
        ledger event or None on no-op/error.
        """
        if not self.enabled:
            self.last_action = "skipped:disabled"
            return None
        try:
            apy = self.apy_cache.get_apy(now=now)
            available = self.ledger.current_principal
            take = min(amount_usd, available)
            if take <= 0:
                self.last_action = "skipped:no_principal"
                return None
            event = self.ledger.withdraw(
                take,
                apy=apy,
                idempotency_key=f"withdraw:{decision_id}",
                now=now,
            )
            self.last_action = "withdraw"
            return event
        except DuplicateEventError:
            self.last_action = "skipped:duplicate"
            return None
        except Exception as exc:
            self.last_action = "error"
            self.last_error = f"{type(exc).__name__}: {exc}"
            logger.warning("kamino withdraw_for_entry swallow: %s", exc)
            return None

    def accrue(self, now: float | None = None) -> float:
        """Cheap explicit accrual tick. Safe to call on any cadence;
        called automatically inside deposit/withdraw. Returns delta."""
        try:
            apy = self.apy_cache.get_apy(now=now)
            return self.ledger.accrue(apy=apy, now=now)
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"
            return 0.0

    def snapshot(self) -> dict:
        """Cheap diagnostic dump for the dashboard / debug logging."""
        return {
            "enabled": self.enabled,
            "principal": self.ledger.current_principal,
            "total_accrued": self.ledger.total_accrued,
            "apy_status": self.apy_cache.last_fetch_status,
            "last_action": self.last_action,
            "last_error": self.last_error,
            "ledger_path": str(self.ledger.path),
        }

    # ── Internals ──────────────────────────────────────────────────────

    def _safe_deposit(
        self,
        *,
        idle_usdc: float,
        decision_id: str,
        now: float | None,
    ) -> dict | None:
        if idle_usdc <= self.deposit_threshold_usd:
            self.last_action = "skipped:below_threshold"
            return None
        deposit_amount = round(idle_usdc - self.deposit_reserve_usd, 4)
        if deposit_amount <= 0:
            self.last_action = "skipped:reserve_covers_all"
            return None
        apy = self.apy_cache.get_apy(now=now)
        try:
            event = self.ledger.deposit(
                deposit_amount,
                apy=apy,
                idempotency_key=f"deposit:{decision_id}",
                now=now,
            )
        except DuplicateEventError:
            self.last_action = "skipped:duplicate"
            return None
        self.last_action = "deposit"
        return event


# ── Process-singleton helpers (kept lazy so import is side-effect-free) ──

_SINGLETON: KaminoPaperSink | None = None


def get_default_sink() -> KaminoPaperSink:
    """Lazy process-singleton. Reads env on first call; subsequent calls
    return the same instance. Bot calls this from close_position.

    Env vars consulted (all optional):
        GECKO_KAMINO_PAPER_SINK         — "1" to enable; anything else = OFF
        GECKO_KAMINO_DEPOSIT_THRESHOLD_USD
        GECKO_KAMINO_DEPOSIT_RESERVE_USD
        GECKO_KAMINO_APY_TTL_SEC
        GECKO_KAMINO_APY_FALLBACK
        GECKO_KAMINO_APY_OVERRIDE
        GECKO_STATE_DIR                 — already used by the rest of the bot
    """
    global _SINGLETON
    if _SINGLETON is not None:
        return _SINGLETON
    enabled = os.environ.get(_ENV_FLAG, "0").strip() == "1"
    threshold = _safe_float(_ENV_DEPOSIT_THRESHOLD, _DEFAULT_THRESHOLD)
    reserve = _safe_float(_ENV_DEPOSIT_RESERVE, _DEFAULT_RESERVE)
    ledger = PaperLedger(path=default_ledger_path())
    apy_cache = KaminoAPYCache.from_env()
    _SINGLETON = KaminoPaperSink(
        ledger=ledger,
        apy_cache=apy_cache,
        deposit_threshold_usd=threshold,
        deposit_reserve_usd=reserve,
        enabled=enabled,
    )
    return _SINGLETON


def reset_default_sink_for_tests() -> None:
    """Test-only escape hatch — the singleton is process-global and we
    need to rebuild it across env-var perturbations in pytest."""
    global _SINGLETON
    _SINGLETON = None


def _safe_float(env_var: str, default: float) -> float:
    raw = os.environ.get(env_var)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("invalid %s=%r; using default %.4f", env_var, raw, default)
        return default


# Expose paths for the dashboard layer if it ever wants to read.
def default_ledger_dir() -> Path:
    return default_ledger_path().parent
