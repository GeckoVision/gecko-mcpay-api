"""Agent orchestrator — Phase 3 of the hosted agent flow.

Turns a deployed StrategySpec into a RUNNING paper process: allocates a port,
spawns `launch_agent.sh <agent_id> <port>` (which reads the registry spec → env
→ runs the monolith with the Mongo state backend), tracks it, and stops it.

The spawner is INJECTABLE (default = real subprocess; tests use a fake), so the
orchestration logic is fully tested without spawning OS processes. Per-user agent
caps are enforced here. Capacity/admission by book depth + abuse detection (Spec
B/D) are deferred to a later phase.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
from typing import Any

from agent_store import AgentRegistry

PORT_LO = int(os.environ.get("GECKO_AGENT_PORT_LO", "8280"))
PORT_HI = int(os.environ.get("GECKO_AGENT_PORT_HI", "8299"))
MAX_AGENTS_PER_USER = int(os.environ.get("GECKO_MAX_AGENTS_PER_USER", "3"))


class SubprocessSpawner:
    """Real spawner — starts/kills `launch_agent.sh` processes. Used in prod;
    NOT exercised by tests (which inject a FakeSpawner)."""

    def spawn(self, cmd: list[str], cwd: str | None = None) -> Any:
        return subprocess.Popen(cmd, cwd=cwd)  # fixed argv, no shell

    def is_alive(self, handle: Any) -> bool:
        return handle.poll() is None

    def kill(self, handle: Any) -> None:
        with contextlib.suppress(Exception):  # already gone
            handle.terminate()


class AgentOrchestrator:
    def __init__(self, registry: AgentRegistry | None = None, spawner: Any = None, contest_dir: str | None = None) -> None:
        self._reg = registry or AgentRegistry()
        self._sp = spawner or SubprocessSpawner()
        self._dir = contest_dir or os.path.dirname(os.path.abspath(__file__))
        self._running: dict[str, dict] = {}  # agent_id -> {"handle", "port"}

    def _prune(self) -> None:
        for aid, r in list(self._running.items()):
            if not self._sp.is_alive(r["handle"]):
                self._running.pop(aid, None)
                self._reg.set_status(aid, "stopped")

    def _alloc_port(self) -> int:
        used = {r["port"] for r in self._running.values()}
        for p in range(PORT_LO, PORT_HI + 1):
            if p not in used:
                return p
        raise RuntimeError(f"no free agent port in [{PORT_LO},{PORT_HI}]")

    def count_for_user(self, user_id: str) -> int:
        self._prune()
        running = set(self._running)
        return sum(1 for a in self._reg.list_agents(user_id) if a["agent_id"] in running)

    def start(self, agent_id: str) -> dict:
        self._prune()
        if agent_id in self._running:
            return {"agent_id": agent_id, "port": self._running[agent_id]["port"], "status": "running", "already": True}
        doc = self._reg.get(agent_id)
        if not doc:
            raise KeyError(f"no deployed agent {agent_id!r}")
        if doc.get("status") == "stopped":
            # a stopped agent can be restarted; just proceed
            pass
        n = self.count_for_user(doc.get("user_id", "local"))
        if n >= MAX_AGENTS_PER_USER:
            raise PermissionError(f"user {doc.get('user_id')!r} at agent cap ({MAX_AGENTS_PER_USER})")
        port = self._alloc_port()
        cmd = ["bash", os.path.join(self._dir, "launch_agent.sh"), agent_id, str(port)]
        handle = self._sp.spawn(cmd, cwd=self._dir)
        self._running[agent_id] = {"handle": handle, "port": port}
        self._reg.set_status(agent_id, "running")
        return {"agent_id": agent_id, "port": port, "status": "running"}

    def stop(self, agent_id: str) -> bool:
        r = self._running.pop(agent_id, None)
        if r is not None:
            self._sp.kill(r["handle"])
        self._reg.set_status(agent_id, "stopped")
        return r is not None

    def list_running(self) -> list[dict]:
        self._prune()
        return [{"agent_id": aid, "port": r["port"]} for aid, r in self._running.items()]
