"""Append-only JSONL ledger for the Kamino paper-mode sink.

Each line is a single event:

    {"type":"deposit", "ts":..., "amount":..., "principal_after":..., "apy":..., "idempotency_key":...}
    {"type":"withdraw", "ts":..., "amount":..., "principal_after":..., "apy":..., "idempotency_key":...}
    {"type":"accrue", "ts":..., "elapsed_sec":..., "delta":..., "principal_after":..., "apy":...}

Reading the JSONL on construction rebuilds the in-memory state so a bot
restart resumes the simulated position correctly.

Invariant (asserted on every read in `current_principal`):
    principal == sum(deposits) - sum(withdrawals) + sum(accruals)   (± 1e-6)

Idempotency: deposits + withdrawals carry an `idempotency_key`. The
ledger refuses a second event with the same key. This lets the sink fire
"on close" without worrying about the bot's close-path being invoked
twice for the same decision_id.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("kamino.paper_ledger")

_EPSILON = 1e-6
_SECONDS_PER_YEAR = 365.25 * 86_400.0


@dataclass
class _State:
    principal: float = 0.0
    deposits_total: float = 0.0
    withdraws_total: float = 0.0
    accrual_total: float = 0.0
    last_accrue_ts: float | None = None
    seen_keys: set[str] = field(default_factory=set)


class DuplicateEventError(Exception):
    """Raised when an idempotency_key has already been recorded.

    The sink swallows this — duplicates are a no-op for the caller.
    """


@dataclass
class PaperLedger:
    """Stateful JSONL ledger. Construct with the path you want; events
    append on each write. Recovers on construction by re-reading the file.
    """

    path: Path
    _state: _State = field(default_factory=_State, init=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.exists():
            self._replay()

    # ── Public read API ────────────────────────────────────────────────

    @property
    def current_principal(self) -> float:
        # Invariant check: paranoid, cheap.
        derived = (
            self._state.deposits_total - self._state.withdraws_total + self._state.accrual_total
        )
        if not math.isclose(derived, self._state.principal, abs_tol=_EPSILON):
            logger.error(
                "ledger invariant violated: derived=%.8f principal=%.8f at %s",
                derived,
                self._state.principal,
                self.path,
            )
        return self._state.principal

    @property
    def total_accrued(self) -> float:
        return self._state.accrual_total

    @property
    def last_accrue_ts(self) -> float | None:
        return self._state.last_accrue_ts

    def has_seen(self, idempotency_key: str) -> bool:
        return idempotency_key in self._state.seen_keys

    # ── Public mutate API ──────────────────────────────────────────────

    def deposit(
        self,
        amount: float,
        *,
        apy: float,
        idempotency_key: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        self._guard_key(idempotency_key)
        if amount <= 0:
            raise ValueError(f"deposit amount must be positive; got {amount}")
        ts = now if now is not None else time.time()
        # accrue first so the new principal carries fresh interest
        self._accrue_to(ts, apy)
        self._state.principal = round(self._state.principal + amount, 8)
        self._state.deposits_total = round(self._state.deposits_total + amount, 8)
        self._state.seen_keys.add(idempotency_key)
        if self._state.last_accrue_ts is None:
            self._state.last_accrue_ts = ts
        event = {
            "type": "deposit",
            "ts": ts,
            "amount": amount,
            "principal_after": self._state.principal,
            "apy": apy,
            "idempotency_key": idempotency_key,
        }
        self._append(event)
        return event

    def withdraw(
        self,
        amount: float,
        *,
        apy: float,
        idempotency_key: str,
        now: float | None = None,
    ) -> dict[str, Any]:
        self._guard_key(idempotency_key)
        if amount <= 0:
            raise ValueError(f"withdraw amount must be positive; got {amount}")
        ts = now if now is not None else time.time()
        self._accrue_to(ts, apy)
        if amount > self._state.principal + _EPSILON:
            raise ValueError(f"insufficient principal: want {amount}, have {self._state.principal}")
        self._state.principal = round(self._state.principal - amount, 8)
        self._state.withdraws_total = round(self._state.withdraws_total + amount, 8)
        self._state.seen_keys.add(idempotency_key)
        event = {
            "type": "withdraw",
            "ts": ts,
            "amount": amount,
            "principal_after": self._state.principal,
            "apy": apy,
            "idempotency_key": idempotency_key,
        }
        self._append(event)
        return event

    def accrue(self, *, apy: float, now: float | None = None) -> float:
        """Apply interest up to `now` at `apy`, append an accrue row.
        Returns the delta added.
        """
        ts = now if now is not None else time.time()
        return self._accrue_to(ts, apy, write=True)

    # ── Internals ──────────────────────────────────────────────────────

    def _accrue_to(self, ts: float, apy: float, *, write: bool = True) -> float:
        if self._state.last_accrue_ts is None:
            self._state.last_accrue_ts = ts
            return 0.0
        if self._state.principal <= 0:
            self._state.last_accrue_ts = ts
            return 0.0
        elapsed = max(0.0, ts - self._state.last_accrue_ts)
        if elapsed <= 0:
            return 0.0
        # Continuous-compound approximation: principal * (e^(apy*elapsed/year) - 1)
        # Faster + closer to per-second compounding than the discrete form at
        # tiny elapsed_sec. At small apy*dt this is numerically identical to
        # (1+apy/N)^(elapsed*N) for large N.
        growth = math.expm1(apy * elapsed / _SECONDS_PER_YEAR)
        delta = round(self._state.principal * growth, 8)
        self._state.principal = round(self._state.principal + delta, 8)
        self._state.accrual_total = round(self._state.accrual_total + delta, 8)
        self._state.last_accrue_ts = ts
        if write and delta != 0.0:
            self._append(
                {
                    "type": "accrue",
                    "ts": ts,
                    "elapsed_sec": elapsed,
                    "delta": delta,
                    "principal_after": self._state.principal,
                    "apy": apy,
                }
            )
        return delta

    def _guard_key(self, idempotency_key: str) -> None:
        if not idempotency_key or not isinstance(idempotency_key, str):
            raise ValueError("idempotency_key must be a non-empty string")
        if idempotency_key in self._state.seen_keys:
            raise DuplicateEventError(idempotency_key)

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def _replay(self) -> None:
        with open(self.path, encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                line = raw.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("skipping malformed ledger line %d in %s", lineno, self.path)
                    continue
                self._apply_replay(ev)

    def _apply_replay(self, ev: dict[str, Any]) -> None:
        etype = ev.get("type")
        principal_after = ev.get("principal_after")
        if etype == "deposit":
            self._state.deposits_total = round(self._state.deposits_total + float(ev["amount"]), 8)
            self._state.seen_keys.add(ev.get("idempotency_key", ""))
        elif etype == "withdraw":
            self._state.withdraws_total = round(
                self._state.withdraws_total + float(ev["amount"]), 8
            )
            self._state.seen_keys.add(ev.get("idempotency_key", ""))
        elif etype == "accrue":
            self._state.accrual_total = round(self._state.accrual_total + float(ev["delta"]), 8)
        else:
            logger.warning("unknown ledger event type=%r; ignoring", etype)
            return
        if isinstance(principal_after, (int, float)):
            self._state.principal = float(principal_after)
        ts = ev.get("ts")
        if isinstance(ts, (int, float)):
            self._state.last_accrue_ts = float(ts)


def default_ledger_path() -> Path:
    """Resolve the JSONL path the bot will use, mirroring `_STATE_BASE`."""
    base = os.environ.get("GECKO_STATE_DIR")
    if base:
        return Path(base) / "kamino_paper_ledger.jsonl"
    # default to the contest_bot dir, same as the bot's other artifacts
    return Path(__file__).resolve().parents[1] / "kamino_paper_ledger.jsonl"
