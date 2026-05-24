"""Persistent storage for the historical tape (s46).

Layout (committed):
  scripts/calibration/data/tape/<SYMBOL>_<tf>.json   one file per (symbol, tf)
  scripts/calibration/data/tape/tape_index.json      manifest

Each per-(symbol, tf) file is a JSON list of canonical candle dicts
  [{"ts": ms, "open": .., "high": .., "low": .., "close": .., "volume": ..}, ...]
ascending by ts — the EXACT shape that
  scripts/calibration/exit_reconciliation.py --cached  /  chart_floor_calibration.enrich
read. (exit_reconciliation --cached expects {sym: [candle...]}; load_tape_as_cached
assembles that mapping from per-file tapes.)

Writes are atomic (tmp + rename). Appends de-dupe by ts and re-sort ascending so
the forward-collector is idempotent — re-running never duplicates or reorders bars.
"""

from __future__ import annotations

import json
import os
from typing import Any

TAPE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "tape")
TAPE_DIR = os.path.normpath(TAPE_DIR)
INDEX_PATH = os.path.join(TAPE_DIR, "tape_index.json")

CANDLE_KEYS = ("ts", "open", "high", "low", "close", "volume")
# Valid tf suffixes — guards list_tapes against non-candle JSON files in TAPE_DIR
# (e.g. tape_index.json, regime_windows.json) being mis-parsed as a (sym, tf) tape.
VALID_TFS = ("5m", "15m", "1H", "4H")
RESERVED_FILES = ("tape_index.json", "regime_windows.json")


def tape_path(symbol: str, tf: str) -> str:
    return os.path.join(TAPE_DIR, f"{symbol.upper()}_{tf}.json")


def ensure_dir() -> None:
    os.makedirs(TAPE_DIR, exist_ok=True)


def _atomic_write(path: str, obj: Any) -> None:
    ensure_dir()
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=0, separators=(",", ":"))
    os.replace(tmp, path)


def normalize(candles: list[dict[str, float]]) -> list[dict[str, float]]:
    """De-dupe by ts (last write wins) and sort ascending. Keeps only the
    canonical keys in a stable order so files diff cleanly."""
    by_ts: dict[float, dict[str, float]] = {}
    for c in candles:
        by_ts[float(c["ts"])] = {k: float(c[k]) for k in CANDLE_KEYS}
    return [by_ts[t] for t in sorted(by_ts)]


def load_tape(symbol: str, tf: str) -> list[dict[str, float]]:
    path = tape_path(symbol, tf)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data: list[dict[str, float]] = json.load(f)
    return data


def write_tape(symbol: str, tf: str, candles: list[dict[str, float]]) -> int:
    """Overwrite a (symbol, tf) tape with normalised candles. Returns bar count."""
    norm = normalize(candles)
    _atomic_write(tape_path(symbol, tf), norm)
    return len(norm)


def append_tape(symbol: str, tf: str, new_candles: list[dict[str, float]]) -> tuple[int, int]:
    """Idempotently merge new bars into an existing tape (dedupe by ts).

    Returns (added, total). added is the count of ts not previously present.
    """
    existing = load_tape(symbol, tf)
    existing_ts = {float(c["ts"]) for c in existing}
    merged = normalize(existing + new_candles)
    added = sum(1 for c in merged if c["ts"] not in existing_ts)
    _atomic_write(tape_path(symbol, tf), merged)
    return added, len(merged)


def tape_meta(candles: list[dict[str, float]]) -> dict[str, Any]:
    if not candles:
        return {"bars": 0, "ts_start": None, "ts_end": None}
    return {
        "bars": len(candles),
        "ts_start": candles[0]["ts"],
        "ts_end": candles[-1]["ts"],
    }


def write_index(entries: dict[str, dict[str, Any]], generated: str) -> None:
    """entries keyed by '<SYMBOL>_<tf>' -> {symbol, tf, source, bars, ts_start, ts_end}."""
    _atomic_write(
        INDEX_PATH,
        {"generated": generated, "tapes": entries},
    )


def load_index() -> dict[str, Any]:
    if not os.path.exists(INDEX_PATH):
        return {"generated": None, "tapes": {}}
    with open(INDEX_PATH) as f:
        data: dict[str, Any] = json.load(f)
    return data


def load_tape_as_cached(symbols: list[str], tf: str) -> dict[str, list[dict[str, float]]]:
    """Assemble the {sym: [candle...]} mapping that exit_reconciliation --cached and
    chart_floor_calibration --cached read, for one timeframe across symbols."""
    out: dict[str, list[dict[str, float]]] = {}
    for sym in symbols:
        candles = load_tape(sym, tf)
        if candles:
            out[sym] = candles
    return out


def list_tapes() -> list[tuple[str, str]]:
    """All (symbol, tf) tapes present on disk."""
    if not os.path.isdir(TAPE_DIR):
        return []
    out: list[tuple[str, str]] = []
    for fn in sorted(os.listdir(TAPE_DIR)):
        if not fn.endswith(".json") or fn in RESERVED_FILES or "_" not in fn:
            continue
        stem = fn[:-5]
        sym, _, tf = stem.rpartition("_")
        if sym and tf in VALID_TFS:
            out.append((sym, tf))
    return out
