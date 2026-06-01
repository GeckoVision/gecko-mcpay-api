# Sprint 28 — `market_researcher` Voice (Build Plan)

**Ticket(s):** S28-AI-1 (voice), S28-AI-2 (sentiment cache field), S28-AI-3 (panel wire)
**Mode:** read-only against `market_news` Mongo collection (DATA-2, commit `780cbf9`)
**Default state:** `GECKO_MARKET_RESEARCHER_ENABLED=0` (OFF). Founder flips per-launcher.
**Bot impact when flag OFF:** zero. Voice not constructed, not added to panel.

---

## 1. Job in one sentence

`market_researcher` is the only voice that reads *exogenous text* — it grades whether RECENT NEWS on the current symbol **supports / opposes / is silent on** a candidate long entry, an axis the other five voices structurally cannot see (chart = price, regime = ADX, risk = ops floor, memory = our own PnL, strategist = falsifier on chart).

## 2. Inputs

From `market_state`:
- `instrument` (preferred) or `symbol.split("-")[0]` — the symbol to filter news to (same resolution as `memory_voice.py:151-154`).
- `ts_iso` if present (poll wall-clock); otherwise `datetime.now(UTC)`.

From `decision_store/news_query.by_symbol(symbol, since=now-K_hours, limit=N)`:
- Returns `list[dict]` with `headline`, `body`, `published_at`, `source`, `tickers`, and (once S28-AI-2 ships) `classification.bias_score` / `classification.regime_impact`.
- Embedding field already stripped by `_trim()` (`news_query.py:64-66`). Good.

**No memory ledger read.** This voice's substrate is the news collection, not the JSONL.

## 3. Output contract

Standard `VoiceOpinion` (`voices/base.py:35-60`). Verdict semantics:

| Verdict | Meaning for this voice |
|---|---|
| `bullish` | ≥1 fresh same-symbol news row in window with net-positive aggregated bias (weighted-avg bias_score > +0.2). News supports the entry. |
| `bearish` | ≥1 fresh same-symbol news row with net-negative bias (weighted-avg < −0.2). News opposes — e.g. exploit, depeg, exchange delist, regulatory hit. |
| `neutral` | ≥`_COLD_START_MIN_ROWS` rows in window, aggregated bias inside ±0.2. News is present but uninformative. |
| `abstain` | Cold-start (rows < floor) OR all rows older than `K_hours` OR Mongo unavailable. |

## 4. Architecture — **Hybrid (deterministic confidence + cached LLM sentiment)**

**Pick: hybrid.** Justification grounded in `private/strategy/2026-05-31-s24-s-voice-fix-plan.md`:
- `regime_analyst.py:124-159` (pure-deterministic) gets 37 unique confidence values; `chart_analyst` / `memory_voice` (LLM-graded at temp=0) collapse to 3 anchor values. The S24-S anchor-snap bug is real and applies to ANY voice whose confidence comes from `gpt-4o-mini` reading printed numbers.
- Sentiment interpretation of a headline IS where LLM adds value — `regime_analyst`'s deterministic template can't read "Jito unlocks $40M to insiders" vs "Jito treasury increases USDC reserves."
- Solution: do the sentiment classification **once, at ingest time**, persist `classification.bias_score` on the news row (the schema already reserves the field, see `docs/methodology/market-news-collection.md` §1). The voice itself becomes pure-Python aggregation over precomputed scores. **Voice grade path = zero LLM calls.**

Confidence formula (deterministic, in code):

```
n        = number of rows in window
weights  = exp(-age_hours / HALF_LIFE_HOURS)   # 6h half-life default
agg_bias = sum(w_i * bias_i) / sum(w_i)
conf     = clip( 0.45 + 0.35 * min(n, 5)/5 + 0.20 * abs(agg_bias), 0.0, 0.90 )
```

37+ unique conf values guaranteed by `agg_bias` continuum + recency weighting.

## 5. Cold-start behavior

`market_news` is **empty today** (sink wire pending). Voice MUST degrade gracefully.

| Rows in window | Behavior |
|---|---|
| 0 | `abstain`, conf 0.0, reasoning `"no_news_in_window"`, observations `["window=Kh", "symbol=PYTH"]` |
| 1–2 | `abstain`, conf 0.0, reasoning `"cold_start_insufficient_news"` (mirror `memory_voice.py:166-177`) |
| ≥`_COLD_START_MIN_ROWS=3` | Grade as §3 |

Cold-start floor `_COLD_START_MIN_ROWS=3` matches `memory_voice._COLD_START_MIN_ROWS`. Single sensational headline must not move the panel.

Mongo unavailable (URI unset, connection error): `news_query.by_symbol` returns `[]`, voice abstains via the 0-row branch. Best-effort, never raises.

## 6. Cross-instrument bleed guard

Already enforced by `news_query.by_symbol(symbol, ...)` which filters `{tickers: symbol.upper()}`. The voice MUST:

1. Resolve `instrument` exactly as `memory_voice.py:151-154` does (handles `instrument` field + `symbol` fallback + uppercase normalization).
2. Pass that resolved symbol to `by_symbol(...)`. Never call `recent()` from inside this voice — `recent()` is universe-wide and would re-create the memory_voice S24-S 2b bug.
3. On empty `instrument` string: abstain immediately with reasoning `"symbol_unresolved"`. Don't fall back to universe.

A dedicated test (§10) asserts a JTO-tagged row never appears in a PYTH grade.

## 7. Time window

Default: `K_hours = 6`, env-overridable via `GECKO_MARKET_RESEARCHER_WINDOW_HOURS`.

Rationale:
- 5m scalp horizon: news >24h old is fully priced in and noise.
- Half-life inside the window is 6h (so a row 3h old gets weight ~0.71, a row at the 6h boundary ~0.37). Lets a fresh-breaking story dominate stale background chatter.
- 1h would be too tight given current ingestion cadences (CryptoPanic 10min, Fed RSS 60min — `docs/methodology/market-news-collection.md` §4).

Half-life env: `GECKO_MARKET_RESEARCHER_HALF_LIFE_HOURS=6`.

## 8. Coordinator integration

**Standard voice weights, counts as non-risk.** No special casing.

- `_VOICE_SCORE_WEIGHTS` (`coordinator_rules.py:140-145`) applies as-is: bullish +2, neutral +1, abstain 0, bearish −1.
- Counts toward S24-V Gate 1 `non_risk_bullish` quorum (`coordinator_rules.py:480-491`). With `market_researcher` shipped, the non-risk bullish pool grows from 3 (chart/memory/regime — strategist never bullish by design) to 4. **Default `GECKO_QUORUM_NON_RISK_BULLISH_MIN=2` stays the right bar** — raising it would lock out events where market_researcher abstains (frequent in cold-start).
- Counts toward `bearish_quorum_veto` (`coordinator_rules.py:495-497`). Default 3 of 5 → now 3 of 6. **Bump default to `GECKO_QUORUM_VETO_BEARISH=4`** so adding a sixth voice doesn't soften the existing veto bar (3/6 ≈ 50%, was 3/5 = 60%). Document this as the only behavior shift.

Legacy coordinator mode (`_coordinator_legacy`): voice is silently ignored — legacy is anchored on chart/memory/risk/regime only. No rule additions to legacy this sprint.

## 9. Sentiment provider

**Pick: cached per-news-row sentiment, computed at ingest time, stored as `classification.bias_score` on the news row.**

- The schema already reserves it (`docs/methodology/market-news-collection.md` §1 `classification` block) and the cost model accounts for it (§6: ~$1.20/mo).
- Voice-grade path = **zero LLM calls**. Per the S24-S finding, this is the only way to escape anchor-snap on a numeric confidence.
- Inline-LLM-per-grade was rejected: at 6 voices × 5–10 news rows × poll cadence, costs multiply with no quality gain over the cached path.
- VADER/TextBlob lexicons rejected: crypto-specific terms ("unlock", "depeg", "delist", "exploit") aren't in general lexicons; would underperform a finance-tuned LLM by an unknown margin without measurement.

**Flag for implementer:** S28-AI-2 ships a separate classifier worker (`scripts/data/classify_news_rows.py`) that finds `{classification: null}` rows, calls `openai/gpt-4o-mini` via OpenRouter (per `feedback_openrouter_not_openai_for_new_llm`) for a {bias_score, regime_impact, confidence, rationale}, and patches the row. No schema change required — fields already exist. Sink continues to land rows un-classified (per §1 doc).

**Fallback when row is unclassified:** voice treats `classification = null` rows as missing — they don't count toward the cold-start floor and don't contribute to `agg_bias`. After a fresh row lands and the classifier hasn't run yet, the voice abstains. Acceptable: classifier batch runs every ~15 min.

## 10. Tests (≥8, pattern `contest_bot/tests/test_local_voices.py`)

1. `test_market_researcher_cold_start_zero_rows_abstains` — empty window → abstain 0.0 + `"no_news_in_window"`.
2. `test_market_researcher_cold_start_under_floor_abstains` — 2 rows → abstain + `"cold_start_insufficient_news"`.
3. `test_market_researcher_bullish_majority_returns_bullish` — 4 rows, weighted bias +0.5 → `bullish`, conf in (0.6, 0.9).
4. `test_market_researcher_bearish_majority_returns_bearish` — 4 rows, weighted bias −0.6 → `bearish`, conf in (0.6, 0.9).
5. `test_market_researcher_mixed_returns_neutral` — 4 rows, weighted bias +0.1 → `neutral`.
6. `test_market_researcher_filters_to_symbol_no_bleed` — fake collection with PYTH+JTO rows, grade PYTH → JTO rows MUST NOT contribute (assert on observations).
7. `test_market_researcher_recency_weighting` — same bias_score, two rows 1h vs 5h old: confidence higher when fresh-weighted is dominant.
8. `test_market_researcher_skips_unclassified_rows` — row missing `classification` field → does not count toward floor; voice abstains.
9. `test_market_researcher_mongo_unavailable_abstains` — `by_symbol` returns `[]` (mocked) → abstain, no exception.
10. `test_market_researcher_window_env_override` — `GECKO_MARKET_RESEARCHER_WINDOW_HOURS=1` shrinks the `since=` arg passed to `by_symbol`.
11. `test_market_researcher_confidence_has_variance` — 10 synthetic snapshots with varied n + bias → ≥5 unique conf values (anti-anchor-snap regression).
12. `test_market_researcher_unresolved_symbol_abstains` — empty `instrument` + missing `symbol` → abstain + `"symbol_unresolved"`.

Use injected fake collection (mirror `_FakeColl` pattern from `test_news_sink.py`). No live Mongo.

## 11. Falsifier (first 50 polls post-deploy)

Mirror the S24-S falsifier (`private/strategy/2026-05-31-s24-s-voice-fix-plan.md`):

The voice is **broken** if, across the first 50 polls where `market_news` has ≥3 same-symbol rows in window:
- Fewer than **5 unique confidence values** observed (anchor-snap), OR
- Fewer than **2 distinct verdicts** across the 50 polls (constant-output regression), OR
- Verdict distribution is >95% any single value (probable bug, not signal).

Log telemetry per grade so this can be audited from the artifact JSONL without re-running. If the falsifier trips, roll back with `GECKO_MARKET_RESEARCHER_ENABLED=0` and open an S29 follow-up.

## 12. What this voice CANNOT do (non-goals)

- **Cannot read prices, ADX, MFI, candles, or any indicators.** That's chart/regime.
- **Cannot read the JSONL ledger or `position_close` events.** That's memory_voice.
- **Cannot vector-search news.** Atlas Search vector index `market_news_vec` is founder-gated (`docs/methodology/market-news-collection.md` §2). v1 is ticker-filter + windowed sort only.
- **Cannot wire the okx_news_adapter → NewsSink fan-out.** That's a separate ticket reviewed by `staff-engineer` (cross-package import direction; `docs/methodology/market-news-collection.md` §7).
- **Cannot run its own LLM classifier inline.** Sentiment is precomputed by the S28-AI-2 batch worker. The voice's hot path is pure Python over Mongo reads.
- **Cannot fetch news.** Read-only consumer of the collection.
- **Cannot modify rows.** `news_query` is read-only; the voice never opens a writer.
- **Cannot replace any existing voice.** Additive sixth voice. No edits to the other five voices in this sprint.

---

## Out of scope (deferred to S29+)

- Vector-similarity search ("find the most relevant news to current setup") — needs Atlas Search index.
- Source-trust weighting (Bloomberg vs unverified Twitter scrape) — needs provider trust table.
- Multi-language news (only English in v1; ticker filter is language-agnostic but `bias_score` is computed off English prompts).
- Cross-asset spillover (BTC news affecting PYTH) — v1 is strict same-symbol; correlation-based fanout is a v2 design question.
- Promoting `market_researcher` into the legacy coordinator chain — weighted_quorum only in v1.
