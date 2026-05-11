"""Out-of-band scheduler — cadence + circuit-breaker timers.

APScheduler is overkill for v0.1; we run a single ``asyncio.Task`` per
scheduled job. Each job carries a ``next_fire_at`` monotonic timestamp;
the loop sleeps to the nearest deadline and dispatches expired jobs.

Owned by the runtime; one scheduler per :class:`AgentRuntime`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class _Job:
    name: str
    interval_s: float
    callback: Callable[[], Awaitable[None]]
    next_fire_at: float = field(default_factory=lambda: 0.0)
    one_shot: bool = False


class Scheduler:
    """Single-loop async scheduler. Not thread-safe."""

    def __init__(self) -> None:
        self._jobs: dict[str, _Job] = {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()

    def schedule(
        self,
        name: str,
        interval_s: float,
        callback: Callable[[], Awaitable[None]],
        *,
        fire_immediately: bool = False,
        one_shot: bool = False,
    ) -> None:
        """Register or replace a job. Idempotent on ``name``."""
        now = time.monotonic()
        self._jobs[name] = _Job(
            name=name,
            interval_s=interval_s,
            callback=callback,
            next_fire_at=now if fire_immediately else now + interval_s,
            one_shot=one_shot,
        )
        self._wake.set()

    def cancel(self, name: str) -> None:
        self._jobs.pop(name, None)
        self._wake.set()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="trade_agent.scheduler")

    async def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.monotonic()
            due: list[_Job] = [j for j in self._jobs.values() if j.next_fire_at <= now]
            for job in due:
                try:
                    await job.callback()
                except Exception:
                    logger.exception("scheduler.job_error name=%s", job.name)
                if job.one_shot:
                    self._jobs.pop(job.name, None)
                else:
                    job.next_fire_at = time.monotonic() + job.interval_s

            # Sleep to the next deadline (or 1s if no jobs).
            if not self._jobs:
                sleep_s = 1.0
            else:
                next_due = min(j.next_fire_at for j in self._jobs.values())
                sleep_s = max(0.05, next_due - time.monotonic())

            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=sleep_s)


__all__ = ["Scheduler"]
