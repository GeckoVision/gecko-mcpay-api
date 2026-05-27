"""Sprint 6 Phase A — readers for bot-substrate data sources.

Every reader returns a pandas DataFrame with normalized columns + UTC-tz-aware
timestamps. Readers are pure: pass in a path / glob, get back a DataFrame. No
side effects, no filesystem mutation.

Sources:
- decision_runs/{run_id}/decisions.jsonl  → per-acted-decision rows w/ voices + indicators + outcome
- artifact_*.jsonl                        → per-event rows by kind (local_panel, candidate_blocked, position_open/close, heartbeat, ...)
- bot_state.json                          → closed-position ledger (entry/exit/pnl)
- eval_telemetry_*.jsonl                  → per-poll-per-symbol context snapshots
"""

from __future__ import annotations

import json
import os
from glob import glob
from pathlib import Path
from typing import Iterable

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
BOT_DIR = REPO_ROOT / "contest_bot"
DEFAULT_DECISION_RUNS_DIR = BOT_DIR / "decision_runs"
DEFAULT_BOT_STATE_PATH = BOT_DIR / "bot_state.json"
DEFAULT_ARTIFACT_GLOB = str(BOT_DIR / "artifact_*.jsonl")
DEFAULT_TELEMETRY_GLOB = str(BOT_DIR / "eval_telemetry_*.jsonl")


def _to_utc(s: pd.Series) -> pd.Series:
    """UTC-coerce a timestamp Series; mixed tz-aware/naive handled."""
    return pd.to_datetime(s, utc=True, errors="coerce")


def _flatten_decision_row(r: dict) -> dict:
    """Flatten one decision_runs row to a wide record.

    Voices unnest to voice_{name}_{verdict,confidence,reasoning}.
    Indicators unnest to indicator_{name}. Oracle/coordinator/signal/outcome
    nested keys flatten with their natural prefix.
    """
    rec: dict = {
        "decision_id": r.get("decision_id"),
        "run_id": r.get("run_id"),
        "symbol": r.get("symbol"),
        "symbol_group": r.get("symbol_group"),
        "ts": r.get("ts"),
        "signal_fired": (r.get("signal") or {}).get("fired"),
        "signal_type": (r.get("signal") or {}).get("type"),
        "coordinator_action": (r.get("coordinator") or {}).get("action"),
        "coordinator_rule": (r.get("coordinator") or {}).get("rule"),
        "oracle_verdict": (r.get("oracle") or {}).get("verdict"),
        "oracle_confidence": (r.get("oracle") or {}).get("confidence"),
        "oracle_citations": (r.get("oracle") or {}).get("citations"),
        "oracle_grounded": (r.get("oracle") or {}).get("grounded"),
    }
    for k, v in (r.get("indicators") or {}).items():
        rec[f"indicator_{k}"] = v
    for voice in r.get("voices") or []:
        name = voice.get("name", "unknown")
        rec[f"voice_{name}_verdict"] = voice.get("verdict")
        rec[f"voice_{name}_confidence"] = voice.get("confidence")
        rec[f"voice_{name}_reasoning"] = voice.get("reasoning")
    for k, v in (r.get("outcome") or {}).items():
        rec[f"outcome_{k}"] = v
    return rec


def read_decisions(decision_runs_dir: Path | str = DEFAULT_DECISION_RUNS_DIR) -> pd.DataFrame:
    """Read every decision_runs/*/decisions.jsonl into a flattened DataFrame.

    Empty / missing run directories are skipped silently. Malformed JSON lines are
    skipped (logged via stderr is overkill here; the loader is best-effort).
    """
    base = Path(decision_runs_dir)
    if not base.exists():
        return pd.DataFrame()
    rows: list[dict] = []
    for run_dir in sorted(base.iterdir()):
        if not run_dir.is_dir():
            continue
        f = run_dir / "decisions.jsonl"
        if not f.exists():
            continue
        with f.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(_flatten_decision_row(json.loads(line)))
                except json.JSONDecodeError:
                    continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = _to_utc(df["ts"])
    return df


def read_artifacts(
    artifact_glob: str | Iterable[str] = DEFAULT_ARTIFACT_GLOB,
    kinds: list[str] | None = None,
) -> pd.DataFrame:
    """Concat every artifact_*.jsonl into one DataFrame.

    Each row has {decision_id, kind, ts, source_file, payload_*}. ``kinds`` filters
    to only the listed kinds (e.g. ['local_panel', 'candidate_blocked']) — None
    returns everything. Payload keys flatten with payload_ prefix.
    """
    files = sorted(glob(artifact_glob)) if isinstance(artifact_glob, str) else sorted(
        f for pat in artifact_glob for f in glob(pat)
    )
    rows: list[dict] = []
    for f in files:
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if kinds and d.get("kind") not in kinds:
                    continue
                rec: dict = {
                    "decision_id": d.get("decision_id"),
                    "kind": d.get("kind"),
                    "ts": d.get("ts"),
                    "source_file": os.path.basename(f),
                }
                for k, v in (d.get("payload") or {}).items():
                    rec[f"payload_{k}"] = v
                rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = _to_utc(df["ts"])
    return df


def read_bot_state(path: Path | str = DEFAULT_BOT_STATE_PATH) -> pd.DataFrame:
    """Extract the closed-position trade ledger from bot_state.json.

    Returns one row per position (closed or open). ``signal_data`` nested keys
    flatten to signal_{name}. ts columns coerced to UTC.
    """
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return pd.DataFrame()
    rows: list[dict] = []
    for pos in data.get("positions") or []:
        rec = dict(pos)
        sd = rec.pop("signal_data", None) or {}
        for k, v in sd.items():
            rec[f"signal_{k}"] = v
        rows.append(rec)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    for c in ("entry_ts", "exit_ts", "last_new_high_ts"):
        if c in df.columns:
            df[c] = _to_utc(df[c])
    return df


def read_eval_telemetry(
    telemetry_glob: str | Iterable[str] = DEFAULT_TELEMETRY_GLOB,
) -> pd.DataFrame:
    """Concat every eval_telemetry_*.jsonl into one DataFrame.

    Rows are already flat (per-poll-per-symbol snapshots). source_file recorded
    for provenance. ts coerced to UTC.
    """
    files = sorted(glob(telemetry_glob)) if isinstance(telemetry_glob, str) else sorted(
        f for pat in telemetry_glob for f in glob(pat)
    )
    rows: list[dict] = []
    for f in files:
        bn = os.path.basename(f)
        with open(f) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                d["source_file"] = bn
                rows.append(d)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" in df.columns:
        df["ts"] = _to_utc(df["ts"])
    return df


__all__ = [
    "DEFAULT_ARTIFACT_GLOB",
    "DEFAULT_BOT_STATE_PATH",
    "DEFAULT_DECISION_RUNS_DIR",
    "DEFAULT_TELEMETRY_GLOB",
    "read_artifacts",
    "read_bot_state",
    "read_decisions",
    "read_eval_telemetry",
]
