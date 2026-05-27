"""Sprint 6 Phase B — OHLCV loader.

Reads the Binance perp 4h OHLCV files Sprint 4 ingested into
``scripts/calibration/data/perp/binance/<SYMBOL>_perp.json``. Each file is a
JSON list of ``{ts, open, high, low, close, volume}`` (ts in ms epoch UTC).

Returns pandas DataFrames with a UTC-tz-aware DatetimeIndex; ohlcv columns
are float.
"""

from __future__ import annotations

import json
from glob import glob
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PERP_DIR = REPO_ROOT / "scripts" / "calibration" / "data" / "perp" / "binance"

OHLCV_COLS = ("open", "high", "low", "close", "volume")


def available_symbols(perp_dir: Path | str = DEFAULT_PERP_DIR) -> list[str]:
    """Return sorted list of symbols present in the perp dir.

    E.g. ['AAVE', 'ADA', 'ARB', ...] (the ``_perp.json`` suffix stripped).
    """
    base = Path(perp_dir)
    if not base.exists():
        return []
    return sorted(
        Path(f).stem.replace("_perp", "")
        for f in glob(str(base / "*_perp.json"))
    )


def load_ohlcv(symbol: str, perp_dir: Path | str = DEFAULT_PERP_DIR) -> pd.DataFrame:
    """Load one symbol's 4h OHLCV into a DataFrame indexed by UTC ts.

    Returns empty DataFrame if the symbol's file is missing or malformed.
    Columns: open, high, low, close, volume (all float).
    """
    f = Path(perp_dir) / f"{symbol}_perp.json"
    if not f.exists():
        return pd.DataFrame()
    try:
        rows = json.loads(f.read_text())
    except json.JSONDecodeError:
        return pd.DataFrame()
    if not isinstance(rows, list) or not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    if "ts" not in df.columns:
        return pd.DataFrame()
    df["ts"] = pd.to_datetime(df["ts"], unit="ms", utc=True)
    df = df.set_index("ts").sort_index()
    for c in OHLCV_COLS:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    # Drop any rows with missing core OHLC (volume can be zero on illiquid bars)
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def load_universe(
    symbols: list[str] | None = None,
    perp_dir: Path | str = DEFAULT_PERP_DIR,
) -> dict[str, pd.DataFrame]:
    """Load every (or a subset of) symbol DataFrame into a dict.

    Symbols with missing/empty data are silently skipped.
    """
    syms = symbols if symbols is not None else available_symbols(perp_dir)
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        df = load_ohlcv(s, perp_dir)
        if not df.empty:
            out[s] = df
    return out


__all__ = [
    "DEFAULT_PERP_DIR",
    "OHLCV_COLS",
    "available_symbols",
    "load_ohlcv",
    "load_universe",
]
