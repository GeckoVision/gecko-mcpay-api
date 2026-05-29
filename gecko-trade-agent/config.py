"""All bot tunables in one place. Paper-safe defaults.

Flipping PAPER_TRADE to False is the only thing standing between this and
real money — do it deliberately, never by accident.
"""
import os

# ── execution mode ─────────────────────────────────────────────────────
PAPER_TRADE = True            # NEVER auto-flip. Real money requires editing this.
CHAIN = "solana"
POLL_SEC = 30
TIMEFRAME = "5m"
ENTRY_TYPE = "price_breakout"

# ── sizing + risk ──────────────────────────────────────────────────────
USD_PER_TRADE = 45
STOP_LOSS_PCT = 3
TAKE_PROFIT_PCT = 4
MAX_DAILY_TRADES = 3
MAX_CONCURRENT = 2
SESSION_LOSS_PAUSE = 2
MAX_BUDGET_USD = 100          # GLOBAL cap across all INSTRUMENTS

# ── exit overlays ──────────────────────────────────────────────────────
STALL_GREEN_EXIT_AGE_MIN = 60
STALL_GREEN_EXIT_MIN_PCT = 2.0
FLAT_STALL_AGE_MIN = 90
FLAT_STALL_PNL_LO = -0.5
FLAT_STALL_PNL_HI = 2.0
FLAT_STALL_NO_NEW_HIGH_MIN = 30
TRAIL_STOP_PCT = 1
TRAIL_ACTIVATE_AFTER_PCT = 2

# ── filters ────────────────────────────────────────────────────────────
VOL_SPIKE_MULTIPLIER = 1.5
VOL_SPIKE_AVG_BARS = 24
BTC_OVERLAY = None            # coarse BTC belt off; the voices are the gate
BTC_WBTC_MINT = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"
SAFETY = {"honeypot_check": True, "phishing_exclude": True}

# ── feature flags ──────────────────────────────────────────────────────
# Off by default — the fundamentals layer calls the hosted (waitlist-gated)
# x402 oracle, which is a v2 feature. v1 runs the gate locally.
FUNDAMENTALS_ORACLE_ENABLED = False

# ── infra ──────────────────────────────────────────────────────────────
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8265"))
WALLET_ADDRESS = ""          # resolved at runtime from onchainos if empty

INSTRUMENTS: list[dict] = [
    # iter-3 2026-05-20: trimmed to high-vol candidates only. Dropped MEW
    # (today's loser) + JTO/JUP/RAY/ORCA/HNT (low-vol established) per
    # quant's memes-only recommendation. PYTH kept (today's winner via
    # momentum-lens fire). DRIFT/TNSR kept (newer infra, more vol than
    # major DeFi).
    {"symbol": "PYTH", "mint": "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3", "chain": "solana"},
    # Memes (high-vol)
    # BONK removed 2026-05-21 (founder call): two BONK positions stalled in
    # the +1-1.6% no-man's-land for 3h+ each without reaching TP/trail/stall
    # triggers. Dropping it from rotation — it kept binding a slot at low conviction.
    {"symbol": "WIF", "mint": "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm", "chain": "solana"},
    {"symbol": "POPCAT", "mint": "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr", "chain": "solana"},
    {"symbol": "BOME", "mint": "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82", "chain": "solana"},
    # Newer infra (more volatile than major DeFi)
    {"symbol": "DRIFT", "mint": "DriFtupJYLTosbwoN8koMbEYSx54aFAVLddWsbksjwg7", "chain": "solana"},
    {"symbol": "TNSR", "mint": "TNSRxcUxoT9xBG3de7PiJyTDYu7kskLqcpddxnEJAS6", "chain": "solana"},
]

ENTRY_PARAMS = {
    "direction": "up",
    "lookback_bars": 24,
    "confirm_pct": 1.5,
}  # iter-3.10 2026-05-21: REVERTED the test-mode loosening that was wrongly shipped live (was 4, 0.2 — a 0.2% breakout over a 20-min high = noise; we were buying micro-pops that immediately mean-reverted, which is why entries kept stalling — BONK/BOME both peaked within minutes of entry then faded). Now: close must clear the prior 2-HOUR high (24×5m bars) by ≥1.5% — a real breakout, not a noise wiggle. Founder caught this by observing we enter at exhausted micro-tops. Stronger than the original 1.0 confirm per founder. Fewer, higher-conviction entries.
