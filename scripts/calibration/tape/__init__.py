"""Data-coverage historical tape (s46).

Persistent, regime-labeled, multi-TF, multi-symbol candle dataset so the Phase-V
validation harness has real multi-regime weather to evaluate against — replacing
the ephemeral, 5m-only, single-chop-window /tmp/cal_candles_*.json tapes.

Canonical raw-candle shape (matches contest_bot/onchainos.get_candles + what
scripts/calibration/exit_reconciliation.py --cached / chart_floor_calibration.enrich
read): a list of dicts {ts: float ms, open, high, low, close, volume}, ascending
by ts, with the forming (unconfirmed) bar dropped.

Sources:
  - okx_source : OKX public market REST (primary; deep, free, no auth)
  - birdeye_source : Birdeye on-chain DEX OHLCV (needs BIRDEYE_API_KEY)
"""
