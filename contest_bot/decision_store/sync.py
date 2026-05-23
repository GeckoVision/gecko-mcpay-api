from __future__ import annotations

import json
import pathlib

from .mongo import best_effort_upsert, get_collections


def sync_run(run_dir: pathlib.Path, sims_coll, decs_coll) -> int:
    """Backfill one run's simulation.json + decisions.jsonl into Mongo. Returns #decisions synced."""
    sim = json.loads((run_dir / "simulation.json").read_text())
    best_effort_upsert(sims_coll, {"run_id": sim["run_id"]}, sim)
    merged: dict[str, dict] = {}
    for line in (run_dir / "decisions.jsonl").read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        merged.setdefault(row["decision_id"], {}).update(
            row
        )  # fold outcome patches onto the decision
    for did, doc in merged.items():
        best_effort_upsert(decs_coll, {"decision_id": did}, doc)
    return len(merged)


def main() -> None:
    sims, decs = get_collections()
    root = pathlib.Path(__file__).parent.parent / "decision_runs"
    total = sum(sync_run(d, sims, decs) for d in root.iterdir() if (d / "simulation.json").exists())
    print(f"synced {total} decisions across {len(list(root.iterdir()))} runs")


if __name__ == "__main__":
    main()
