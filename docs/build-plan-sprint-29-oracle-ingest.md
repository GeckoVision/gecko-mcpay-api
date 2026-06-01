# Sprint 29 — On-chain Oracle Ingestion into the Vector Substrate

**Status:** PLANNED — decisions locked 2026-06-01, implementation pending.
**Author:** founder + ai-ml-engineer pairing, 2026-06-01.
**Goal:** add cross-source on-chain price verification alongside the OKX OnchainOS primary, persist snapshots to a new Mongo collection, embed them for semantic-similarity retrieval, and add a 7th deterministic voice that gates on cross-source agreement.

**Not in this sprint:** swapping OKX out as the primary OHLCV source. OKX keeps being the bot's eyes; Pyth + Jupiter become the bot's second + third pair of eyes.

## Decisions locked 2026-06-01

| Question | Locked answer | Why |
|---|---|---|
| Which second source(s)? | **Pyth Hermes + Jupiter aggregator** (both in Phase 1) | Pyth = "fair value" reference; Jupiter = "executable price". Different signal classes; 3-way OKX/Pyth/Jupiter check is the desired risk gate. |
| Phase 1 scope | **Ingest + new `oracle_voice` as 7th voice** (vs augmenting regime_analyst) | Founder pick: 7th voice gives a cleaner architectural surface than overloading regime_analyst. Bigger blast radius accepted (panel cardinality changes 6→7, S24-V `GECKO_QUORUM_VETO_BEARISH` will need bump to 5 to preserve 60% bar). |
| Chainlink in v1? | **No** | Coverage gap on Solana for our meme + small-cap universe. See `docs/methodology/oracle-stack.md`. |
| Switchboard in v1? | **No, defer to Phase 3** | Pyth + Jupiter + OKX already gives 3-way independence; Switchboard is political diversification with marginal coverage gain. |
| Helius role | **Rail, not source** | Helius is the RPC we'd read Pyth's on-chain account THROUGH. For Phase 1, the Hermes REST API is simpler and sufficient. |

---

## 1. Oracle landscape (decide which sources)

| Source | What it gives | Latency | Cost | Solana-native | Why pick |
|---|---|---|---|---|---|
| **Pyth Hermes** | Multi-publisher aggregated price + spread + confidence | sub-second | free public API | ✅ | Best signal-per-dollar; most-used by Solana DeFi |
| **Switchboard** | Alternative oracle, on-chain pull | seconds | gas-only | ✅ | Cross-check on Pyth; political diversification |
| **Jupiter aggregator price** | Cross-DEX best-bid-ask routing | sub-second | free | ✅ | Real executable price (vs Pyth's "fair value") |
| **Raydium/Orca pool TWAP** | Pool-derived spot from on-chain reserves | seconds | RPC-only via Helius | ✅ | What spot traders ACTUALLY see |
| **Helius (RPC)** | NOT a price oracle — Solana RPC + DAS | n/a | $99/mo for our tier | ✅ | The RAIL we read Pyth/Switchboard/DEX accounts THROUGH |
| **Chainlink** | Cross-chain feeds | seconds | gas-only | partial | Coverage on Solana is thin; skip for v1 |

**Recommendation:**
- **Phase 1: Pyth Hermes only** (free, sub-second, no infra cost) for SOL + PYTH + WIF + USDC.
- **Phase 2: add Jupiter aggregator** — gives EXECUTABLE price (Pyth says "fair value $0.041", Jupiter says "you can actually buy at $0.0411 right now"). The delta is the slippage we'd have eaten.
- **Phase 3 (skip unless needed): Switchboard** as political-diversification cross-check on Pyth.

---

## 2. What "ingest oracle data into vector store" can mean (pick the use-cases)

Three distinct value paths. We can do them in order, not all at once.

### Use-case A — **Price snapshots** (the base substrate)
Persist every N-second price + spread + confidence per symbol. Embeddable as `"SOL at $148.32 ± 0.04, spread 0.03%, regime TREND-UP, age 200ms"` — Voyage can semantic-match "find moments when SOL was tight-spread at trend-up reversal."

**Volume estimate:** 4 symbols × 60-second polling × 86,400 sec/day = **5,760 snapshots/day**.

### Use-case B — **Cross-source divergence events** (the high-signal one)
When OKX OnchainOS and Pyth disagree on the same symbol by > some threshold for > some duration, write a `divergence_event` row. These are RARE but HIGH-SIGNAL — they correlate with: depeg events, oracle outages, low-liquidity manipulation, breaking-news price discovery lag.

**Volume estimate:** ~5-20/day across our universe at a 0.3% threshold. Cheap to embed.

**Why this is the wedge:** none of the 7 voices currently see oracle disagreement. Adding it gives `risk_voice` (or a new `oracle_voice`) a structurally NEW input — defensible per the LdP rigor doc.

### Use-case C — **Regime fingerprints** (the compositional one)
Every panel call already snapshots indicators (ADX, RSI, MFI, etc.). Add the multi-source price-cluster — "OKX says X, Pyth says Y, Jupiter says Z, spread between them, confidence" — to the existing decision-vector embedding. The substrate gets richer without a new collection.

**Volume estimate:** ZERO additional rows; just enriches existing `bot_behaviors` embeddings.

**Recommendation:** ship A + C in Phase 1. B is a follow-up sprint that builds on A.

---

## 3. Storage: new collection or extend existing

### Option 1 (recommended) — **New `oracle_snapshots` collection**
```
gecko_cache.oracle_snapshots
  _id, symbol, ts, source, price, spread, confidence, slot,
  publishers_count, regime_hint, embedding (Voyage-1024), embedding_summary
```

Mirrors the `market_news` / `bot_behaviors` pattern. Sink + query helpers follow that exact template (`oracle_sink.py` + `oracle_query.py`).

**Pros:** clean isolation; easy to drop if Phase 1 doesn't earn its keep.
**Cons:** another collection to monitor.

### Option 2 — Extend `bot_behaviors`
Add `oracle_snapshot: {pyth_price, okx_price, spread, divergence_pct}` to every existing DecisionDoc.

**Pros:** zero new infra; voice queries already work.
**Cons:** couples oracle ingestion cadence to decision cadence (you only get an oracle row when the bot makes a decision — misses the times between).

**Pick Option 1** for Phase 1 because Use-case B (divergence events) demands its own write cadence independent of decision events.

---

## 4. Embedding strategy

Each `oracle_snapshot` row gets a one-sentence text summary, embedded with the same Voyage-finance-2 / 1024-dim model `bot_behaviors` already uses:

```
embedding_summary: "SOL @ $148.32 (Pyth, spread 0.03%, 14 publishers, conf 0.99)
                    at 2026-06-01T05:00:00Z; regime hint TREND-UP."
```

For divergence events (Use-case B), the summary is longer:

```
embedding_summary: "DIVERGENCE: WIF — Pyth $0.191 vs OKX $0.193 (1.05% gap)
                    sustained 90s starting 2026-06-01T05:00:00Z;
                    Pyth confidence 0.97; lower-volume OKX side suspect."
```

Why these shapes:
- Symbol + price + source = obvious retrieval key
- Spread + confidence = "how reliable was the oracle at this moment"
- Regime hint = lets the panel cross-correlate to the 1h regime feature
- Voyage's finance-tuned model handles these structured-text shapes well per our existing `bot_behaviors` experience

---

## 5. Voice integration (who consumes this?)

### Phase 1 — Augment `regime_analyst` (deterministic voice)
The current `regime_analyst.py` computes a regime score from ADX + EMA stack on OKX OHLCV only. Add a deterministic feature:

```python
oracle_cross_source_spread = abs(pyth_price - okx_price) / okx_price
oracle_cross_source_spread > 0.005  # 50bp gap
  → regime confidence cap at 0.6 (= "I don't trust this regime call")
```

Zero LLM impact, ZERO anchor-snap risk (deterministic), drops `regime_analyst` confidence to neutral on bad-data moments. Mirrors the S24-S "deterministic confidence" pattern.

### Phase 2 — New `oracle_voice` (deterministic)
A 7th voice (or 8th if `market_researcher` is also enabled). Reads `oracle_snapshots`, returns:
- `bullish` only if all three sources (OKX + Pyth + Jupiter) agree to within 30bp AND price is rising
- `bearish` on the same agreement with falling price
- `abstain` whenever sources disagree by > 50bp — "data quality too low to grade"

### Phase 3 — Analyst queries
Quant + strategist agents can `gecko_oracle_query "when was SOL spread > 50bp"` and get a list of timestamps with citation-grade context. Powers the autopsy workflows we already do post-bleed.

---

## 6. Phases (concrete ship plan)

### Phase 1 (1-2 days, env-gated default OFF)
- `contest_bot/oracle/pyth_client.py` — Pyth Hermes REST client (Hermes is REST-over-HTTP; no SDK needed)
- `contest_bot/oracle/snapshot_sink.py` — writes to `gecko_cache.oracle_snapshots`. Mirror `behavior_sink.py` exactly.
- `contest_bot/oracle/snapshot_query.py` — read helpers (mirror `behavior_query.py`)
- `scripts/oracle/init_oracle_snapshots_collection.py` — idempotent collection + index creator (mirror `init_market_news_collection.py`)
- `scripts/oracle/ingest_pyth_snapshots.py` — one-shot or cron'd poller; writes a snapshot per symbol per minute
- `regime_analyst.py` — add the cross-source spread gate
- **Tests:** ≥8 (Pyth client, sink idempotency, query helpers, regime_analyst gate)
- **Env gate:** `GECKO_ORACLE_INGEST=1`. Default OFF.

### Phase 2 (after Phase 1 has 7d of data)
- `gecko_core.orchestration.oracle_voice` — the 7th voice
- Divergence detector — separate cron'd job that scans `oracle_snapshots`, flags sustained gaps, writes `divergence_event` rows
- Voice integration into bootstrap (env-gated default OFF, mirror S28 pattern)

### Phase 3 (after Phase 2 ships + we have divergence event data)
- Atlas Search vector index on `oracle_snapshots.embedding` (founder-gated, same as the DATA-1 pending ticket)
- Voyage classification of regime_hint at ingest time
- Quant + strategist agent skills that query the substrate

---

## 7. Cost

| Item | Cost | Notes |
|---|---|---|
| Pyth Hermes API | **$0** | Free public API, no key required |
| Mongo storage | ~$0.05/mo Phase 1 | 5,760 rows/day × 1KB × 30 days = 170MB |
| Voyage embeddings | ~$0.30/mo Phase 1 | 5,760 × 30 × 1024-dim @ $0.0001/text = small |
| Helius RPC | $0 marginal | already paying $99/mo for the existing tier |
| Jupiter aggregator | $0 | free public API |
| **Total Phase 1** | **~$0.35/mo** | basically free |

If Phase 1 proves out and we 10x the universe (40 symbols, 10s polling), Phase 2 cost stays under $10/mo.

---

## 8. Falsifier (when do we kill this)

After 7 days of Phase 1 running:

- If `regime_analyst` confidence-cap fires < 5 times across 7 days → spread gate threshold too tight; tune to 30bp.
- If `regime_analyst` confidence-cap fires > 50 times across 7 days → too sensitive; tune to 100bp.
- If retroactive query "find moments when oracle disagreed with executed trade outcome" finds < 3 cases → no signal, kill the ingest, revert.

After 14 days, run a quant autopsy: does `regime_analyst` calibration improve when the spread gate is wired vs not? If Brier score doesn't improve by at least 5%, the feature isn't load-bearing — keep ingesting for the analyst-query use case but drop the voice gate.

---

## 9. Out of scope (deferred)

- **Switching the primary OHLCV source** — we're augmenting, not replacing.
- **On-chain Pyth account reading via Helius** — Hermes REST is simpler and sufficient. Reading the on-chain account is for the day we want trustless verification (likely never for our use case; Hermes is operated by Pyth itself).
- **Chainlink** — coverage gap on Solana, low value-add.
- **Real-time WebSocket subscription to Pyth** — Phase 1 uses HTTP polling at 60s cadence; WebSocket is Phase 2+ if we move to faster decision cadence.
- **Vector-similarity-driven trade decisions** — Phase 3 enables this for ANALYSTS first (humans querying); the bot uses deterministic gates only.
- **Predictive divergence (forecasting future divergence)** — out of scope. We only DETECT divergence retroactively.

---

## 10. Decision points to lock with the founder before kicking off

1. **Phase 1 universe** — start with [SOL, USDC, PYTH, WIF] (matches current bot) or broader [SOL, USDC, JLP, BONK, JTO, ...]?
2. **Polling cadence** — 60s (cheap, matches bot poll) or 10s (richer divergence detection, more rows)?
3. **Spread gate threshold** for `regime_analyst` — start at 50bp or 100bp?
4. **New voice vs feature-of-existing** — augment `regime_analyst` (Phase 1) OR ship a new `oracle_voice` directly (Phase 1+2 collapsed)?
5. **Mongo collection name** — `oracle_snapshots` (clear) or `price_snapshots` (broader if we add CEX prices later)?

---

## Cross-references

- `docs/methodology/lopez-de-prado-pitfalls.md` — why cross-source data quality is binding for Pitfall #3 (sampling) + #4 (labeling)
- `docs/methodology/data-pipeline.md` — current state of what we model vs what we don't (oracle ingestion is the §5 transformation gap)
- `docs/methodology/market-news-collection.md` — template the new `oracle_snapshots` collection follows
- `contest_bot/decision_store/news_sink.py` — code pattern for the new `oracle_sink.py`
- `packages/gecko-core/src/gecko_core/trade_agent/hotpath/pyth.py` — existing `PythHermesClient` we can reuse instead of writing a new one
- `packages/gecko-core/src/gecko_core/sources/market_data.py` — pinned Pyth feed IDs for SOL, USDC, PYTH, etc.
