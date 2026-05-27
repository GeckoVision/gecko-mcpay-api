"""Sprint 6 Phase B + Phase D — OHLCV loader (multi-venue).

Reads OHLCV files from either:
- Binance perps (Sprint 4 ingest):  ``data/perp/binance/<SYMBOL>_perp.json``
- Solana DEX (Phase D ingest):      ``data/solana/<SYMBOL>_dex.json``

Both files are JSON lists of ``{ts, open, high, low, close, volume}``.
Binance: ts in ms, 4h candles. Solana (CoinGecko): ts in ms, DAILY candles
when days>=30 (which is what we ingest for cohort derivation).

Returns pandas DataFrames with UTC-tz-aware DatetimeIndex; ohlcv columns
are float. Venue is selected via ``Venue`` enum / dataclass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from glob import glob
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]

OHLCV_COLS = ("open", "high", "low", "close", "volume")


@dataclass(frozen=True)
class Venue:
    """A data venue — where to find OHLCV files + filename suffix.

    Pre-canned via VENUE_BINANCE / VENUE_SOLANA constants; passable as kwarg
    to all loader functions. Custom venues can be constructed inline.
    """

    name: str
    data_dir: Path
    file_suffix: str  # e.g. "_perp" or "_dex"


VENUE_BINANCE = Venue(
    name="binance",
    data_dir=REPO_ROOT / "scripts" / "calibration" / "data" / "perp" / "binance",
    file_suffix="_perp",
)
VENUE_SOLANA = Venue(
    name="solana",
    data_dir=REPO_ROOT / "scripts" / "calibration" / "data" / "solana",
    file_suffix="_dex",
)

# Backwards-compat aliases (preserves existing callers in PR #54)
DEFAULT_PERP_DIR = VENUE_BINANCE.data_dir


def _resolve_venue(
    venue: Venue | None,
    perp_dir: Path | str | None,
) -> Venue:
    """Pick a venue. ``perp_dir`` is the legacy kwarg for back-compat."""
    if venue is not None:
        return venue
    if perp_dir is not None:
        # Legacy call: passing a custom dir. Assume binance-shape filenames.
        return Venue(name="custom", data_dir=Path(perp_dir), file_suffix="_perp")
    return VENUE_BINANCE


def available_symbols(
    perp_dir: Path | str | None = None,
    *,
    venue: Venue | None = None,
) -> list[str]:
    """Return sorted list of symbols present in the venue's data dir.

    Strips ``<file_suffix>.json`` to get the symbol. E.g. for VENUE_BINANCE
    'AAVE_perp.json' → 'AAVE'; for VENUE_SOLANA 'JTO_dex.json' → 'JTO'.
    """
    v = _resolve_venue(venue, perp_dir)
    base = Path(v.data_dir)
    if not base.exists():
        return []
    return sorted(
        Path(f).stem.replace(v.file_suffix, "")
        for f in glob(str(base / f"*{v.file_suffix}.json"))
    )


def load_ohlcv(
    symbol: str,
    perp_dir: Path | str | None = None,
    *,
    venue: Venue | None = None,
) -> pd.DataFrame:
    """Load one symbol's OHLCV into a DataFrame indexed by UTC ts.

    Returns empty DataFrame if the symbol's file is missing or malformed.
    Columns: open, high, low, close, volume (all float).
    """
    v = _resolve_venue(venue, perp_dir)
    f = Path(v.data_dir) / f"{symbol}{v.file_suffix}.json"
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
    perp_dir: Path | str | None = None,
    *,
    venue: Venue | None = None,
) -> dict[str, pd.DataFrame]:
    """Load every (or a subset of) symbol DataFrame into a dict.

    Symbols with missing/empty data are silently skipped.
    """
    v = _resolve_venue(venue, perp_dir)
    syms = symbols if symbols is not None else available_symbols(venue=v)
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        df = load_ohlcv(s, venue=v)
        if not df.empty:
            out[s] = df
    return out


__all__ = [
    "DEFAULT_PERP_DIR",
    "OHLCV_COLS",
    "VENUE_BINANCE",
    "VENUE_SOLANA",
    "Venue",
    "available_symbols",
    "load_ohlcv",
    "load_universe",
]
