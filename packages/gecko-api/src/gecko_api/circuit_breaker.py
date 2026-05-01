"""S12-HARDEN-04 — cost circuit breaker for the public 402 surface.

Tracks LLM spend across all sessions in a rolling 60s window. When the
cumulative spend (in-flight + recently completed) exceeds the configured
threshold, ``is_open()`` returns True and new POST /research / POST /plan
requests should be served a 503 with ``Retry-After: 30`` until the window
slides.

Storage: in-memory deque of (timestamp, usd) entries. **This resets on
process restart and is single-process only.** Sprint 13+ should migrate
this to Redis (or similar shared store) so multi-replica deploys share a
single budget. For V1 / single-process behind ALB this is enough — the
goal is to cap a runaway cost spike (prompt-injection-driven LLM hammer,
buggy retry loop, etc.), not to enforce a strict org-wide quota.

In-flight calls are NOT killed when the breaker opens — only NEW calls
are rejected. Existing work completes normally.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Iterator

# Default budget: $5 / minute cumulative across all sessions. Tuned for the
# Bazaar-listed surface where /research is the dominant cost driver
# (~$3 LLM spend per session at basic tier, so the breaker opens after
# roughly 1-2 concurrent sessions burst — generous enough for legitimate
# traffic, tight enough to cap an abuse spike).
DEFAULT_BUDGET_USD_PER_MINUTE = 5.0
WINDOW_SECONDS = 60.0
RETRY_AFTER_SECONDS = 30


class CostCircuitBreaker:
    """Rolling-window cost tracker. Thread-safe; not async-aware (the
    operations are O(1) amortized so blocking the event loop is fine)."""

    def __init__(
        self,
        *,
        budget_usd_per_minute: float = DEFAULT_BUDGET_USD_PER_MINUTE,
        window_seconds: float = WINDOW_SECONDS,
    ) -> None:
        self._budget = float(budget_usd_per_minute)
        self._window = float(window_seconds)
        # (monotonic_timestamp, usd_amount) entries, oldest first.
        self._events: deque[tuple[float, float]] = deque()
        self._lock = threading.Lock()

    def _evict_locked(self, now: float) -> None:
        cutoff = now - self._window
        while self._events and self._events[0][0] < cutoff:
            self._events.popleft()

    def record_spend(self, usd: float) -> None:
        """Append a spend event to the window. Negative or zero is ignored."""
        if usd <= 0:
            return
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            self._events.append((now, float(usd)))

    def current_spend_per_minute(self) -> float:
        """Sum of all spend within the rolling window."""
        now = time.monotonic()
        with self._lock:
            self._evict_locked(now)
            return sum(usd for _, usd in self._events)

    def is_open(self) -> bool:
        """True iff cumulative recent spend exceeds the budget."""
        return self.current_spend_per_minute() > self._budget

    def reset(self) -> None:
        """Drop all tracked events. Test-only."""
        with self._lock:
            self._events.clear()

    def snapshot(self) -> Iterator[tuple[float, float]]:
        """Yield a copy of the current event list. Test/debug helper."""
        with self._lock:
            return iter(list(self._events))


# Module-level singleton. The API handlers call into this instance; tests
# import it directly to inject simulated spend.
_breaker = CostCircuitBreaker()


def get_breaker() -> CostCircuitBreaker:
    return _breaker


def reset_breaker() -> None:
    """Test hook — clears the global breaker's state."""
    _breaker.reset()
