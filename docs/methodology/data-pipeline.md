# Data Pipeline — what we model, what we don't

Companion to `lopez-de-prado-pitfalls.md`. That doc names the academic rigor pitfalls; this one walks the actual bytes from raw market source → voice consumption and names where each transformation happens (or doesn't).

**Audience:** sub-agents proposing feature engineering, data sourcing, or model-validation work; founder triaging "is the input clean?" questions; future contributors deciding whether a new feature needs a new pipeline stage or fits into an existing one.

**Honest framing:** Gecko's edge is "judgment layer that says no," not "alpha-extracting feature factory." We model data **minimally** on the live path — raw indicators on raw 5m time bars feed the LLM voices. This is consistent with the architecture but it's exactly where the LdP pitfalls land hardest. The backtest harness applies more rigor than the live path; the gap is intentional but should be revisited when learned models touch the substrate (Sprint 28+).

---

## 1. Sources (raw bytes in)

| Source | What we read | Where it's wired |
|---|---|---|
| **OKX onchainOS** (MCP) | OHLCV 5m + 1h, order book depth, funding rate, smart-money trader signals, news headlines | `contest_bot/jto_breakout_*.py` (live), `packages/gecko-core/.../orchestration/trade_panel/okx_news_adapter.py` (news) |
| **Helius** (Solana RPC + DAS) | On-chain account state, token metadata, transaction parse, asset holders | `packages/gecko-core/.../execution/` and skill manifests |
| **CoinGecko** (free tier) | Hourly OHLCV → resampled to 4h for the swing harness | `scripts/calibration/data/solana_4h_180d/` |
| **Binance** (ccxt) | Perp funding history, OHLCV for the carry-universe Sprint 4 backtest | `scripts/calibration/ccxt_spine.py` |
| **Pyth, Birdeye** | Available but inactive in the live bot today | env keys present, not wired |
| **paysh, twit.sh, Bazaar, arxiv, github, hn, reddit** | Knowledge / signal corpora, not OHLCV | `packages/gecko-core/.../sources/` |

**Provenance discipline:** every persisted row in `bot_behaviors` carries `code_commit`, `run_id`, `ts`. We can re-derive the version of the indicator math that produced any historical decision. **Source identity** (which OKX endpoint, which provider) is captured at the artifact-log level but NOT formalized as a structured `provider` field on the row — that's a Sprint 28+ gap if cross-source disagreement starts mattering.

---

## 2. Cleaning + sanity (gap layer today)

| Step | Live path | Backtest path |
|---|---|---|
| Candle ordering check | ❌ trust the source | ✅ `ccxt_spine.py` sorts by timestamp |
| Dedupe on (ts, symbol) | ❌ trust the source | ✅ Phase B loader dedupes |
| Out-of-bound spike removal | ❌ none | ✅ explicit guards in calibration scripts |
| Missing-bar interpolation | ❌ none | ⚠️ partial — uses last-known forward-fill |
| Time-zone normalization | ✅ all stored as ISO-8601 UTC | ✅ same |
| Unit normalization (USDC vs USD) | ⚠️ assumed equivalent | ✅ tracked separately in `quote_currency` field |

**Known live-path failure mode (Sprint 15 incident):** OKX once returned bars out of chronological order; the bot used the latest received bar as "the current bar" but it was actually 5min stale. **Fix shipped:** the bot validates that the latest bar's `ts` is monotonically increasing per symbol — if not, it logs `candidate_blocked: stale_candle` and re-polls. Not a full re-sort; just a freshness check.

---

## 3. Sampling

**Live path:** **5m time bars exclusively.** Every voice consumes the same `_LAST_INDEX[symbol]` snapshot computed from the latest 30 OHLCV bars. The bot polls every 30s and re-computes on each poll.

**Backtest path:** also 5m time bars for the scalp class. Sprint 9 swing harness uses 4h bars; Sprint 4 carry-universe used 1d funding events.

**LdP Pitfall #3 violation:** we don't use information-driven bars (dollar / volume / tick / dollar-imbalance). Mitigation: our entry primitive is `breakout+volume` which requires BOTH a price break and a volume spike — a coarse approximation of dollar-imbalance gating within the time-bar framework. Better than pure price-breakout, worse than true dollar bars.

**Why we get away with it today:** voices are LLM-graded, not classifiers. An LLM reading 30 bars of OHLCV can implicitly handle the "this bar matters more than that bar" judgment that information-driven bars would make structural.

**When this binds:** the moment a learned model trains on `bot_behaviors`, the sampling regime becomes a feature-engineering constraint. Pre-Sprint-28 ticket: pilot a dollar-bar pipeline for one symbol and compare feature distributions vs the time-bar baseline.

---

## 4. Feature extraction (indicators)

**Code:** `contest_bot/indicators.py`.

| Indicator | Computation | Bars needed |
|---|---|---|
| ADX | Wilder smoothing, period 14 | ≥28 (2×N for smoothing convergence) |
| +DI / −DI | directional movement, period 14 | ≥28 |
| RSI | Wilder smoothing, period 14 | ≥14 |
| MFI | money flow, period 14 | ≥14 |
| Chop index | log10(ATR sum / range), period 14 | ≥14 |
| BB-width | (upper − lower) / middle, period 20, σ=2 | ≥20 |
| EMA stack | EMA9 > EMA21 > EMA50 → `up`; reverse → `down`; else → `flat` | ≥50 |
| Range_24h_pct | (high24h − low24h) / mid_price × 100 | ≥288 (24h of 5m bars) |
| Volume median, mean | last 24 bars | ≥24 |
| 1h regime | composed from above: `TREND-UP` / `TREND-DOWN` / `CHOP` | ≥30 1h bars (≈30h) |
| Adx_slope, adx_distance, chop_distance | derived features computed at the panel call site | depends on parent |

**Bar-budget discipline:** the bot fetches `limit=30` 5m bars per poll. ADX needs 28; we have 30; consistent. The shadow-log in artifact files uses `limit=24` (computed in `evaluate_breakout`) which is below ADX's 28-bar threshold — hence the `indicators: {adx: null}` you'll see in artifact rows. **This is a logging artifact, NOT a voice-input issue.** Voices' own snapshot uses `limit=30` (line ~2216 of `jto_breakout_*.py`) and DOES have ADX populated. The S24-S diagnosis caught this — the abstain pattern was LLM behavior, not missing-indicator behavior.

**What we don't extract** (but the data is available):
- **Order-flow features**: VPIN (volume-synchronized probability of informed trading), OFI (order-flow imbalance), Kyle's λ. OKX MCP exposes order book + smart-money signals; we use the smart-money signal as a binary `net_flow_verdict`, not as a continuous feature.
- **Microstructure features**: bid-ask spread, depth at top of book, queue position.
- **Cross-asset features**: SOL-relative returns, BTC overlay (`BTC_OVERLAY` constant is `None` per iter-3.3 disable — see line ~394 of bot main file).
- **Time-of-day / day-of-week**: weekend cap on chart_analyst is the only one (S24-S fix 2a), and it's prompt-side not feature-side.

---

## 5. Transformation (the LdP layer)

This is where the LdP pitfalls #2, #4, #5 live. Brutally honest current state:

| Transformation | LdP pitfall | Status |
|---|---|---|
| **Fractional differentiation** (stationarity-preserving) | #2 | ❌ NOT applied. We feed raw price values + raw indicator values. The voices read absolute price `0.04138` instead of frac-diff-d∈(0,1). |
| **Triple-barrier labels** | #4 | ⚠️ PARTIAL. We capture `exit_reason ∈ {take_profit, stop_loss, trailing_stop, flat_stall_exit}` which IS the barrier-that-fired categorically. But we don't label NEW trades during evaluation as "this trade would have hit upper / lower / time" pre-fact. Outcome is realized, not predicted-via-barrier. |
| **Sample-uniqueness weights** | #5 | N/A — no classifier to weight. |
| **Z-score per symbol** (cross-asset normalization) | adjacent | ❌ raw price scales. PYTH at $0.04 and WIF at $0.19 look "different sizes" to the LLM. The 1.5% breakout-confirm threshold IS percentage-based, but the raw-price-in-prompt for chart_analyst is absolute. |
| **Log returns** | adjacent | ❌ we feed price levels, not log(p[t]/p[t-1]). |
| **Detrending** | adjacent | ⚠️ implicit via the rolling EMA stack but no explicit detrend transform. |

**Why this is OK for now:** the voices are LLMs. An LLM reading "PYTH 0.04138 → 0.04015, -3.07%" reasons about the percentage just fine. The frac-diff / log-return / z-score transforms matter most when a numerical model would otherwise weight raw-price magnitudes incorrectly.

**Why this stops being OK at Sprint 28+:** the moment a model trains on the decision-vector substrate, raw-price features bias toward higher-priced assets. Frac-diff + log-returns + per-symbol z-score are all prerequisite.

---

## 6. Substrate (persistent storage)

Three layers, all populated:

| Layer | Where | What lands | Throughput today |
|---|---|---|---|
| **Artifact JSONL** | `contest_bot/artifact_<date>.jsonl` | every event (heartbeat, local_panel, position_open/close, candidate_blocked, fundamentals_check, oracle_reject) | ~10k events/day |
| **Mongo `decisions`** | `gecko_cache.decisions` | act-path DecisionDocs with Voyage-1024 embeddings | 11 acts/day (post-S24-U: same), ~52 docs total today |
| **Mongo `bot_behaviors`** | `gecko_cache.bot_behaviors` | act + decline DecisionDocs (S24-U wire), embeddings absent on declines today | 45 docs today (37 declines + 8 acts), 11,439 historical from backfill |
| **Mongo `market_news`** | `gecko_cache.market_news` | NEW (DATA-2 just shipped) — okx-news headlines + bodies | 0 docs (sink ready, wire to okx_news_adapter pending staff-engineer review) |

**What the substrate ALLOWS us to do retroactively:** reconstruct the full panel state at any past decision — voices, oracle, indicators, signal, coordinator rule, outcome (for acts). This is what `bot_behaviors` was built for; this is what `quant-analyst` and `trading-strategist` query when they autopsy a bleed (like this morning).

**What we CAN'T do today:** vector-similarity search on the substrate. The Atlas Search vector index DDL exists in `private/strategy/2026-05-31-data-engineer-bot-behaviors-audit.md` and `scripts/data/init_market_news_collection.py` but creation is founder-gated (DATA-1 task #154).

---

## 7. Voice consumption

Voices read the `market_state` dict that the bot builds at poll time. Shape:

```python
{
    "instrument": "PYTH",
    "symbol": "PYTH-USDC",
    "spot_price": 0.04138,
    "change_1h_pct": 0.5,
    "change_24h_pct": 3.2,
    "range_24h_pct": 4.5,
    "volume_24h": 5_000_000.0,
    "ohlcv_5m": [...30 bars...],  # raw OHLCV — voice computes its own indicators if needed
    "regime_1h": "TREND-UP",       # composed feature
    "net_flow_verdict": "accumulation",  # binary smart-money signal
    "daily_trades": 2,             # for risk_voice
    "max_daily_trades": 20,
    "consec_losses": 0,
    "total_spent_usd": 90.0,
    "max_budget_usd": 100.0,
    "open_position_count": 1,
    "max_concurrent": 2,
    ...
}
```

Each voice picks the fields it needs. `chart_analyst` reads `ohlcv_5m` + the derived indicators. `memory_voice` reads `instrument` + queries the JSONL ledger for that symbol's prior closes. `risk_voice` reads the risk-floor block (daily_trades, total_spent_usd, etc.). `regime_analyst` reads `ohlcv_5m` + computes a deterministic regime score. `strategist_voice` reads the indicators block + applies the falsifier prompt.

**Critical detail:** the snapshot is built ONCE per poll and shared across all 5 voices. Voices don't re-fetch. So if the source returned stale data, every voice sees the same staleness.

---

## Scorecard vs the LdP pitfalls

Same scorecard as `lopez-de-prado-pitfalls.md` but from the data-pipeline lens:

| Pitfall | Live path | Backtest path |
|---|---|---|
| #2 Integer differentiation | ❌ raw values | ❌ same |
| #3 Inefficient sampling | ❌ 5m time bars (mitigated by breakout+volume primitive) | ❌ same |
| #4 Wrong labeling | ⚠️ exit_reason captured, not pre-fact triple-barrier | ⚠️ same |
| #5 Non-IID weights | N/A — no model | N/A |
| #6 CV leakage | N/A live | ✅ CPCV + purge + embargo applied |
| #7 Backtest overfitting | N/A live | ✅ DSR ≥ 0.95, PBO < 0.2, MinTRL enforced |

**Live path is 0/4 on the feature-engineering pitfalls, 100% on the no-model pitfalls.**
**Backtest path is 2/2 on the validation pitfalls, 0/3 on the feature-engineering pitfalls (it just shares the live pipeline's feature extraction).**

---

## Sprint 28+ action items (when learned models touch the substrate)

In recommended order:

1. **Pilot a dollar-bar pipeline** on one symbol (PYTH or WIF). Compare distributions of all 10 indicators time-bars vs dollar-bars vs volume-bars. Pick the bar type whose RSI / ADX / MFI distributions show the cleanest separation between winning and losing trades in the existing `bot_behaviors` substrate.
2. **Frac-diff layer**: wrap `mlfinlab.features.fracdiff_FFD` and add a `frac_diff_d` column to the indicator output. Find the lowest `d` (typically 0.3–0.5) that achieves stationarity per ADF test. Ship it as an optional feature first, not a replacement.
3. **Triple-barrier label pre-fact**: at trade entry time, write the upper/lower/time barrier triple alongside the decision. The realized exit_reason becomes the label after close. Stores the categorical outcome the way LdP §3.2 wants.
4. **Per-symbol z-score**: normalize price + volume features per asset before feeding to any model. Keep raw values for the LLM prompts (they handle scale natively).
5. **Order-flow extraction**: VPIN + OFI from OKX order-book MCP. Start as observational features in the snapshot before any voice consumes.
6. **Multi-timeframe stack**: formalize 5m + 1h + 4h as a single feature vector. Today the bot has 1h regime as a separate signal; promote to feature-stack peer.

Until that sprint, voices keep reading raw indicators on raw time bars. The architecture works; the gap is honest.

---

## See also

- `docs/methodology/lopez-de-prado-pitfalls.md` — academic frame
- `contest_bot/indicators.py` — feature-extraction code
- `contest_bot/jto_breakout_gecko_gated_contest_bot.py` — live pipeline orchestration (line ~2216 for the snapshot construction)
- `scripts/calibration/ccxt_spine.py` — backtest data path (with cleansing)
- `private/strategy/2026-05-31-data-engineer-bot-behaviors-audit.md` — substrate health audit
- `feedback_dogfood_loop` memory — null-first discipline that compensates for the feature-engineering minimalism
