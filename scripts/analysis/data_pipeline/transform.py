"""Sprint 6 Phase A — cleansing + annotation.

Turns raw extracted DataFrames into analysis-ready canonical tables:

- ``collapse_decision_pairs``: each acted decision writes TWO rows in decisions.jsonl
  (entry with voices+indicators+NaN outcome; close with NaN voices/indicators + filled
  outcome). Collapse the pair by decision_id so each acted trade becomes ONE row with
  both entry-context and outcome populated.
- ``label_outcome``: derive W/S/L using MIN_REALIZED_WIN_PCT threshold (matches bot
  ``MIN_REALIZED_WIN_PCT`` = 0.5 default from bot-honesty Fix 2).
- ``annotate_regime``: extract regime-at-entry from indicator_regime_1h + indicator_regime.
- ``classify_voice_consensus``: B / S / N / A counts per row.
- ``join_with_outcome``: take cleaned decisions + bot_state positions; left-join on
  decision_id; surfaces "decisions with an outcome on file".

Reasoning for the threshold: per ``private/strategy/2026-05-26-bot-honesty-sprint-log.md``
Fix 2, a "win" requires a realized PnL above the dust threshold (0.5% by default). Below
it = "scratch" (broke-even on noise). True losses are signed-negative.
"""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

# Default per bot-honesty Fix 2 + GECKO_MIN_WIN_PCT env contract.
DEFAULT_MIN_REALIZED_WIN_PCT = 0.5

OutcomeLabel = Literal["win", "scratch", "loss", "open", "unknown"]


def collapse_decision_pairs(decisions: pd.DataFrame) -> pd.DataFrame:
    """Collapse entry/close paired rows by decision_id.

    Per the data-pipeline finding: decisions.jsonl writes two rows per acted trade
    sharing decision_id. The entry row has voices + indicators + signal info; the
    close row has the outcome_* fields. ``collapse`` merges by combining non-null
    values across the pair (last-non-null wins, but the entry row is always written
    first so its context wins on ties).

    Decision rows that DIDN'T act (coordinator_action != 'act') stay as single rows
    untouched. Returns one row per unique decision_id.
    """
    if decisions.empty:
        return decisions
    df = decisions.copy()

    # Group by decision_id; combine via first-non-null per column (preserves entry
    # context + folds in outcome cells).
    def _combine(group: pd.DataFrame) -> pd.Series:
        return group.bfill().ffill().iloc[0]

    if "decision_id" not in df.columns:
        return df
    collapsed = (
        df.groupby("decision_id", dropna=False, sort=False)
        .apply(_combine, include_groups=False)
        .reset_index()
    )
    # Drop the synthetic level-index column the groupby adds if present.
    if "level_1" in collapsed.columns:
        collapsed = collapsed.drop(columns="level_1")
    return collapsed


def label_outcome(
    df: pd.DataFrame,
    pnl_col: str = "outcome_pnl_pct",
    min_win_pct: float = DEFAULT_MIN_REALIZED_WIN_PCT,
) -> pd.DataFrame:
    """Add an ``outcome_label`` column with W/S/L/open/unknown classification.

    - ``win``: pnl_pct >= +min_win_pct
    - ``loss``: pnl_pct <= -min_win_pct
    - ``scratch``: -min_win_pct < pnl_pct < +min_win_pct  (noise / dust)
    - ``open``: status known but outcome missing
    - ``unknown``: outcome col not present / NaN
    """
    df = df.copy()
    if pnl_col not in df.columns:
        df["outcome_label"] = "unknown"
        return df

    def _cls(v) -> str:
        if pd.isna(v):
            return "unknown"
        if v >= min_win_pct:
            return "win"
        if v <= -min_win_pct:
            return "loss"
        return "scratch"

    df["outcome_label"] = df[pnl_col].apply(_cls)
    return df


def annotate_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Add a normalized ``regime_at_entry`` column derived from indicator_regime_1h.

    Order: prefer indicator_regime_1h if present + non-null; else fall back to
    indicator_regime; else ``None``. Standardizes case ('TREND-UP' -> 'trend_up' etc.)
    so groupby keys are stable.
    """
    df = df.copy()

    def _normalize(v) -> str | None:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip().lower().replace("-", "_")
        if not s or s in {"none", "nan", "null"}:
            return None
        return s

    raw_1h = df["indicator_regime_1h"].tolist() if "indicator_regime_1h" in df.columns else [None] * len(df)
    raw_base = df["indicator_regime"].tolist() if "indicator_regime" in df.columns else [None] * len(df)
    out: list[str | None] = []
    for h, b in zip(raw_1h, raw_base, strict=False):
        v = _normalize(h)
        if v is None:
            v = _normalize(b)
        out.append(v)
    df["regime_at_entry"] = pd.Series(out, dtype="object", index=df.index)
    return df


def classify_voice_consensus(df: pd.DataFrame) -> pd.DataFrame:
    """Add columns counting voice verdicts per row.

    ``voice_bull_count``, ``voice_bear_count``, ``voice_neutral_count``,
    ``voice_abstain_count``, ``voice_total_count``. Pure roll-up; doesn't change
    the source per-voice columns.
    """
    df = df.copy()
    voice_cols = [c for c in df.columns if c.startswith("voice_") and c.endswith("_verdict")]
    if not voice_cols:
        for c in (
            "voice_bull_count",
            "voice_bear_count",
            "voice_neutral_count",
            "voice_abstain_count",
            "voice_total_count",
        ):
            df[c] = 0
        return df

    def _count(row: pd.Series, target: str) -> int:
        return int(sum(1 for c in voice_cols if str(row.get(c, "")).lower() == target))

    df["voice_bull_count"] = df.apply(lambda r: _count(r, "bullish"), axis=1)
    df["voice_bear_count"] = df.apply(lambda r: _count(r, "bearish"), axis=1)
    df["voice_neutral_count"] = df.apply(lambda r: _count(r, "neutral"), axis=1)
    df["voice_abstain_count"] = df.apply(lambda r: _count(r, "abstain"), axis=1)
    df["voice_total_count"] = df[
        ["voice_bull_count", "voice_bear_count", "voice_neutral_count", "voice_abstain_count"]
    ].sum(axis=1)
    return df


def join_with_outcome(
    decisions_clean: pd.DataFrame,
    bot_state_positions: pd.DataFrame,
) -> pd.DataFrame:
    """Left-join the collapsed-decisions table with the bot_state position ledger.

    The decision row's outcome_* columns are already authoritative when present
    (post-collapse). bot_state adds independent fields the decision row doesn't
    have: entry_price, exit_price, exit_reason as authoritative ground-truth (the
    ledger is the source of truth for actual fills), entry_ts, exit_ts, peak_price.

    Returns the decision row + ``ledger_*``-prefixed columns from bot_state.
    """
    if decisions_clean.empty:
        return decisions_clean
    if bot_state_positions.empty:
        return decisions_clean

    ledger_cols = [
        c
        for c in (
            "decision_id",
            "symbol",
            "entry_price",
            "exit_price",
            "peak_price",
            "entry_ts",
            "exit_ts",
            "exit_reason",
            "pnl_pct",
            "pnl_usd",
            "status",
            "mode",
        )
        if c in bot_state_positions.columns
    ]
    ledger = bot_state_positions[ledger_cols].copy()
    ledger.columns = [c if c == "decision_id" else f"ledger_{c}" for c in ledger.columns]
    return decisions_clean.merge(ledger, on="decision_id", how="left")


def derive_entry_timing_features(
    df: pd.DataFrame,
    poll_telemetry: pd.DataFrame,
    *,
    lookback_minutes: int = 60,
) -> pd.DataFrame:
    """Derive entry-timing features per trade by joining poll telemetry.

    For each row with a (ledger_entry_ts, symbol) pair, look back ``lookback_minutes``
    in poll_telemetry and compute: ``entry_pre_lookback_max_price``,
    ``entry_pre_lookback_min_price``, ``entry_dist_from_pre_high_pct`` (how far
    below the recent peak the entry was — small = chasing a top, larger = entry
    on pullback / breakout).
    """
    df = df.copy()
    if df.empty or poll_telemetry.empty:
        df["entry_pre_lookback_max_price"] = np.nan
        df["entry_pre_lookback_min_price"] = np.nan
        df["entry_dist_from_pre_high_pct"] = np.nan
        return df

    out_max: list[float] = []
    out_min: list[float] = []
    out_dist: list[float] = []
    window = pd.Timedelta(minutes=lookback_minutes)
    tele_by_sym = {sym: g.sort_values("ts") for sym, g in poll_telemetry.groupby("symbol")} if "symbol" in poll_telemetry.columns else {}

    for _, r in df.iterrows():
        entry_ts = r.get("ledger_entry_ts")
        symbol = r.get("ledger_symbol") or r.get("symbol")
        entry_px = r.get("ledger_entry_price")
        if pd.isna(entry_ts) or symbol is None or entry_px is None or pd.isna(entry_px):
            out_max.append(np.nan)
            out_min.append(np.nan)
            out_dist.append(np.nan)
            continue
        # ledger_symbol may be "JUP-USDC"; telemetry symbol is "JUP" → strip suffix.
        sym_key = str(symbol).split("-")[0]
        tele = tele_by_sym.get(sym_key)
        if tele is None or tele.empty or "price" not in tele.columns:
            out_max.append(np.nan)
            out_min.append(np.nan)
            out_dist.append(np.nan)
            continue
        mask = (tele["ts"] >= entry_ts - window) & (tele["ts"] < entry_ts)
        window_px = tele.loc[mask, "price"].dropna()
        if window_px.empty:
            out_max.append(np.nan)
            out_min.append(np.nan)
            out_dist.append(np.nan)
            continue
        max_px = float(window_px.max())
        min_px = float(window_px.min())
        out_max.append(max_px)
        out_min.append(min_px)
        dist = (max_px - float(entry_px)) / max_px * 100.0 if max_px > 0 else np.nan
        out_dist.append(dist)

    df["entry_pre_lookback_max_price"] = out_max
    df["entry_pre_lookback_min_price"] = out_min
    df["entry_dist_from_pre_high_pct"] = out_dist
    return df


def annotate_full(
    decisions: pd.DataFrame,
    bot_state_positions: pd.DataFrame | None = None,
    poll_telemetry: pd.DataFrame | None = None,
    *,
    min_win_pct: float = DEFAULT_MIN_REALIZED_WIN_PCT,
) -> pd.DataFrame:
    """One-call pipeline: collapse pairs + label + regime + voices + ledger join + timing.

    Used by the autopsy script. Each step is also exposed individually for unit tests.
    """
    collapsed = collapse_decision_pairs(decisions)
    if bot_state_positions is not None and not bot_state_positions.empty:
        collapsed = join_with_outcome(collapsed, bot_state_positions)
        # Prefer ledger pnl when present (authoritative).
        if "ledger_pnl_pct" in collapsed.columns:
            collapsed["outcome_pnl_pct"] = collapsed["outcome_pnl_pct"].combine_first(collapsed["ledger_pnl_pct"])
    collapsed = label_outcome(collapsed, min_win_pct=min_win_pct)
    collapsed = annotate_regime(collapsed)
    collapsed = classify_voice_consensus(collapsed)
    if poll_telemetry is not None and not poll_telemetry.empty:
        collapsed = derive_entry_timing_features(collapsed, poll_telemetry)
    return collapsed


__all__ = [
    "DEFAULT_MIN_REALIZED_WIN_PCT",
    "annotate_full",
    "annotate_regime",
    "classify_voice_consensus",
    "collapse_decision_pairs",
    "derive_entry_timing_features",
    "join_with_outcome",
    "label_outcome",
]
