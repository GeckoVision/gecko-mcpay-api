# Scope — Choppiness Index + Multi-Timeframe Regime (s42)

*2026-05-22. Triggered by the founder's 4h BOME read: CHOP rose 40→60 and called
the stall before ADX did; and the bot reads only 5m, blind to the 4h chop it was
entering into. These two upgrades are the mechanical version of that eyeball read.*

## The gap (proven by the founder's chart)
1. The bot uses ADX for regime, but ADX **lags** (it stayed at 38 on 4h while the
   move was already consolidating). The **Choppiness Index (CHOP)** measures
   range-vs-trend *directly* and is more responsive — CHOP 40→60 flagged the stall first.
2. The bot reads **one timeframe (5m)**. The founder reads **4h**. A 5m breakout
   *into* 4h chop (exactly BOME) is low-quality; a 5m breakout *aligned* with a
   non-choppy higher timeframe is the real setup. The bot has no higher-TF context.

## Upgrade 1 — add the Choppiness Index to the indicator set
- Formula (n=14): `CHOP = 100 * log10( sum(TR, n) / (maxHigh(n) - minLow(n)) ) / log10(n)`.
  TR = true range (already have ATR plumbing in `indicators.py`).
- Bands: **> 61.8 = max chop** (consolidation), **< 38.2 = trending**, between = neutral.
- Add `chop` to `compute_latest()` output + the `_LAST_INDEX` studio snapshot (the s41 bundle).
- CHOP complements ADX (don't replace): ADX = trend strength/direction (lagging),
  CHOP = range-vs-trend (responsive). Two orthogonal regime reads.

## Upgrade 2 — multi-timeframe regime gate
- Fetch a **higher-timeframe** candle series per instrument (1h primary — responsive;
  optionally 4h for macro). **Low-frequency + cached** — higher-TF candles change
  slowly; fetch once per N polls (e.g. every 12 polls ≈ 6 min), never per-poll.
- Compute higher-TF CHOP + ADX. Add a **coordinator modulator** (in CODE, not prompt,
  per `feedback_prompt_iteration_plateau`): if the higher TF is max-chop (CHOP > ~61.8
  or ADX < ~18), **raise the entry bar** (like the existing 0.92 chop floor) or block.
  Mirror the existing regime-modulator pattern in `coordinator_rules.py`.
- Net effect: stop taking 5m signals the bigger picture will chop to death (BOME).

## Validation gate (mandatory — don't trust thresholds on feel)
Extend the calibration harness (`scripts/calibration/`) with CHOP + higher-TF features:
- Recompute the floor/EV study WITH the multi-TF + CHOP filter. Question: would it have
  **avoided losers** and **kept any of the 4 winners** the base study found? The base
  study found would-have-won 0% — so the bar is "does adding these filters change the
  decline set in a way that improves realized EV, with adequate N + bootstrap CI?"
- Risk to check: the bot is ALREADY very selective. More gates → even fewer trades.
  Validate it doesn't over-block to ~zero. If CHOP/multi-TF only removes trades that
  were break-even anyway, it's a wash — keep it only if it removes net losers.

## Studio
- Add CHOP to the s41 Indexes panel (color: red >61.8, green <38.2).
- Show **5m regime vs higher-TF regime** side by side so the conflict (5m setup into
  4h chop) is visible at a glance — the exact thing the founder spotted by eye.

## Sequencing
- Build in **s42**, AFTER the s41 bundle deploys (next clean restart) and BOME closes.
- Indicator (Upgrade 1) is cheap + low-risk → land first, surface in studio, observe.
- Multi-TF gate (Upgrade 2) is a behavior change → build behind the calibration gate;
  ship only if the harness shows it improves realized EV.

## Open questions
1. Higher-TF choice: 1h (responsive, closer to 5m timing) vs 4h (macro, what the founder
   reads) vs both. Let the calibration pick; default 1h.
2. Modulator vs hard veto: raise the floor (selective) or block outright in higher-TF
   max-chop? Start with raise-the-floor (consistent with the existing chop modulator).
3. Connection to multi-strategy: a 4h-chop regime is where a **grid bot** belongs — so
   "higher-TF is chop" could eventually *route to grid* instead of just blocking momentum
   (ties to the roadmap's regime→strategy routing).
