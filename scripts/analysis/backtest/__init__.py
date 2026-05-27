"""Sprint 6 Phase B — counterfactual backtest of the bot strategy.

Goal: port the bot's deterministic entry + exit logic into a vectorized
simulator over the Binance 730d 4h OHLCV substrate already ingested for
Sprint 4. Produces synthetic trades that match the schema of Phase A's
``decisions_clean.parquet`` so downstream analysis (autopsy, memory_voice v2
feature rules) can read them identically.

Scope (v1):

- Entry: ``price_breakout`` only — 4h close breaks the prior N-bar high.
  (volume_spike is gated by Fix 4 to require breakout co-confirmation, so a
  pure breakout backtest is an upper bound on bot's entry rate.)
- Trend filter: ``close > sma(W)`` proxy for Fix 5's regime_1h TREND-UP gate.
  (The bot's autopsy showed 19/19 acted trades were in TREND-UP. Restricting
  the backtest to trend-up bars matches the bot's behavior.)
- Exits: Sprint 7's pure ``_evaluate_stop_exits`` helper verbatim, plus
  the take_profit / stall_green_exit / flat_stall_exit rules ported from
  ``monitor_positions``. No voice/coordinator panel calls (deterministic-only).
- NO voice/panel/LLM calls. Pure CPU. Zero $$.

Sub-modules:
- ``loader``     — read scripts/calibration/data/perp/binance/*.json into DataFrames
- ``signals``    — entry detection (breakout + trend filter)
- ``simulator``  — forward-simulate exits per Sprint 7 helper
- ``runner``     — orchestrator: walk every bar × symbol → synthetic trades → Parquet
"""
