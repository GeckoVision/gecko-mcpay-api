from __future__ import annotations

import json
import pathlib

from .models import DecisionDoc, Outcome, SimulationDoc
from .mongo import best_effort_upsert, get_collections


class DecisionRecorder:
    def __init__(self, run_dir: pathlib.Path, decs_coll=None):
        self._path = run_dir / "decisions.jsonl"
        self._coll = decs_coll

    def record(self, decision: DecisionDoc) -> str:
        d = decision.to_dict()
        self._append(d)
        if self._coll is not None:
            best_effort_upsert(self._coll, {"decision_id": d["decision_id"]}, d)
        return d["decision_id"]

    def attach_outcome(self, decision_id: str, outcome: Outcome) -> None:
        patch = {"decision_id": decision_id, "outcome": outcome.to_dict()}
        self._append(patch)  # immutable: a new patch row
        if self._coll is not None:
            best_effort_upsert(
                self._coll, {"decision_id": decision_id}, {"outcome": outcome.to_dict()}
            )

    def _append(self, obj: dict) -> None:
        with self._path.open("a") as fh:
            fh.write(json.dumps(obj) + "\n")


class SimulationRegistry:
    def __init__(self, root: pathlib.Path | str | None = None, sims_coll=None, decs_coll=None):
        self._root = (
            pathlib.Path(root)
            if root
            else pathlib.Path(__file__).parent.parent / "decision_runs"
        )
        if sims_coll is None and decs_coll is None:
            sims_coll, decs_coll = get_collections()
        self._sims, self._decs = sims_coll, decs_coll
        self._run_dir: pathlib.Path | None = None

    def start(self, sim: SimulationDoc) -> str:
        if not sim.run_id:
            import uuid

            sim.run_id = uuid.uuid4().hex
        self._run_dir = self._root / sim.run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        d = sim.to_dict()
        (self._run_dir / "simulation.json").write_text(json.dumps(d, indent=2))
        if self._sims is not None:
            best_effort_upsert(self._sims, {"run_id": sim.run_id}, d)
        return sim.run_id

    def start_from_config(self) -> str:
        import os
        import subprocess

        try:
            sha = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001 — never block startup on git
            sha = ""
        # TAKE_PROFIT_PCT / STOP_LOSS_PCT / PAPER_TRADE live in the bot module; the bot
        # passes them in via env or this method reads sensible env-overridable defaults.
        return self.start(
            SimulationDoc(
                run_id="",
                strategy_id="jto_breakout",
                agent_group=os.environ.get("AGENT_GROUP", "default"),
                symbol_universe=os.environ.get("INSTRUMENTS", "PYTH,WIF,JUP,RAY,JTO").split(","),
                universe_label=os.environ.get("UNIVERSE_LABEL", "no-tax-majors"),
                config={
                    "chart_min_conf": os.environ.get("GECKO_CHART_MIN_CONF", "0.85"),
                    "max_daily_trades": os.environ.get("MAX_DAILY_TRADES", "3"),
                    "max_concurrent": os.environ.get("MAX_CONCURRENT", "2"),
                    "tp_pct": os.environ.get("TAKE_PROFIT_PCT", ""),
                    "sl_pct": os.environ.get("STOP_LOSS_PCT", ""),
                },
                mode="paper" if os.environ.get("PAPER_TRADE", "true").lower() != "false" else "live",
                code_commit=sha,
            )
        )

    def recorder(self) -> DecisionRecorder:
        assert self._run_dir is not None, "call start() first"
        return DecisionRecorder(self._run_dir, self._decs)
