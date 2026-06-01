# `market_news` — Mongo Atlas collection spec

**Source:** internal data-engineer design, derived from `private/strategy/2026-05-30-mongo-behavior-news-collections-DESIGN.md` and the 2026-05-31 ingestion audit (`private/strategy/2026-05-31-data-engineer-bot-behaviors-audit.md`).

**Why this lives in our docs:** the `market_news` collection backs the planned `market_researcher` voice (Sprint 28+) and retroactive analysis ("what news fired in the 6h before the worst WIF SL?"). Sister doc: `lopez-de-prado-pitfalls.md` (the rigor lens that guides every label/feature choice). Sub-agents should cite this when proposing news-ingestion work.

**Substrate:** Mongo Atlas, db `gecko_cache`, embed model `voyage-finance-2` (1024-dim) per `contest_bot/decision_store/embedder.py`. Mirrors the `bot_behaviors` collection layout — same `_FakeColl` test pattern, same best-effort sink, same `from_env` constructor.

---

## 1. Schema (BSON)

```
{
  _id: ObjectId,
  news_id: "sha256-of-dedupe-key",   // unique natural key (see §3)
  source: "cryptopanic" | "theblock_rss" | "coindesk_rss"
        | "fed_release" | "okx-news" | "tavily" | ...,
  source_id: "<provider's own id>" | null,
  url: "https://..." | null,
  fetched_at: ISO-8601 UTC,          // when WE retrieved the item
  published_at: ISO-8601 UTC | null, // when the SOURCE timestamped it
  headline: "<required>",
  body: "<cleaned, capped at 8000 chars>",
  tickers: ["BTC", "SOL", "PYTH"],   // upper-case, extracted by provider
  classification: {                  // patched by classifier pass (deferred)
    regime_impact: "risk_on" | "risk_off" | "neutral",
    bias_score: -1.0..+1.0,
    confidence: 0.0..1.0,
    rationale: "<= 240 chars",
    classified_at: ISO-8601 UTC,
    model: "openai/gpt-4o-mini"      // via OpenRouter per feedback_openrouter_not_openai_for_new_llm
  } | null,
  embedding: [1024 floats] | absent, // patched by Voyage batch (founder-gated)
  embedding_model: "voyage-finance-2" | null | absent,
  embedding_summary: "<headline>\n<tickers>\n<body[:1500]>" | null | absent,
  embedded_at: ISO-8601 UTC | null | absent,
  schema_v: 1,
  ingested_at: ISO-8601 UTC,         // set by NewsSink at write time
  created_at: ISO-8601 UTC           // set by $setOnInsert on first upsert
}
```

**Required at write:** `source`, `headline`. Everything else may be absent / null.

**Embedding fields are LEFT ABSENT (not set to None)** until a batch-embed pass runs. This lets the embedder query `{embedding: {$exists: false}}` to find unembedded rows. Same pattern as `bot_behaviors`.

---

## 2. Indexes

Regular (created by `scripts/data/init_market_news_collection.py`):

| Index | Purpose | Spec |
|---|---|---|
| `news_id_unique` | dedupe primary key | `{news_id: 1}`, unique |
| `published_at_desc` | `recent(N)` timeline scans | `{published_at: -1}` |
| `fetched_at_desc` | sort tiebreaker for null-`published_at` rows | `{fetched_at: -1}` |
| `tickers_published_at_desc` | per-symbol windowed lookups (multikey) | `{tickers: 1, published_at: -1}` |
| `source_fetched_at_desc` | operational ("did this provider fire?") | `{source: 1, fetched_at: -1}` |
| `classification_pending_partial` | classifier queue | `{classification: 1}`, partial `{classification: null}` |

Atlas Search vector (founder-gated, NOT created by the init script — DDL emitted only):

```json
{
  "name": "market_news_vec",
  "type": "vectorSearch",
  "definition": {
    "fields": [
      { "type": "vector", "path": "embedding", "numDimensions": 1024, "similarity": "cosine" },
      { "type": "filter", "path": "tickers" },
      { "type": "filter", "path": "source" },
      { "type": "filter", "path": "classification.regime_impact" },
      { "type": "filter", "path": "published_at" }
    ]
  }
}
```

**Index intentional:** every index has a query above it (per data-engineer principle #4). No "just-in-case" coverage. When a new query pattern shows up, the index is added in this doc + the init script in the same PR.

---

## 3. Dedupe key (`news_id`)

`news_id` is `sha256(...)` over a deterministic key, preferred in this order:

1. `(source, source_id, ts_iso)` — most providers (CryptoPanic, OKX news) expose a stable id.
2. `(source, url)` — RSS feeds with no separate id but a canonical URL.
3. `(source, headline, ts_iso)` — last-resort, for sources without either.

Computed in `contest_bot/decision_store/news_sink.compute_news_id`. **Same input → same id → idempotent re-record.** Re-fetching the same item updates in place; never duplicates.

---

## 4. Ingestion cadence

**Source provider taxonomy** (v1 scope):

| Provider | Class | Cadence | Status |
|---|---|---|---|
| `okx-news` | trade-panel live (Sprint 18-2) | per panel call | WIRED (in-process); sink fan-out PROPOSED (§7) |
| `cryptopanic` | broad aggregator | every 10 min (batch puller) | DEFERRED — Sprint 28 ingestion script |
| `fed_release` | macro RSS | every 60 min | DEFERRED — Sprint 28 |
| `theblock_rss`, `coindesk_rss` | crypto press | every 30 min | DEFERRED — v2 (only if CryptoPanic coverage gap shows) |

Recommendation per design doc §8 Q3: ship CryptoPanic + Fed RSS in v1, defer the rest to v2.

**Sink path (today, what's shippable now):** the `NewsProvider` adapters in `packages/gecko-core/src/gecko_core/orchestration/trade_panel/` already pull news chunks per panel call. The 3-line wire in §7 below adds a fan-out to `NewsSink.record(...)` so every chunk fetched by the trade panel also persists to Mongo. **Zero changes to trade-panel logic, zero added latency** (sink is async + best-effort).

---

## 5. Retention policy

**Keep forever.** Per design doc §8 Q4: storage is negligible (~6 KB/row × ~300 rows/day × 30 d = 54 MB/mo, well inside Atlas M0's 512 MB) and the entire point of the collection is retrospective "what was the news context 9 months ago when WIF blew up." No TTL index.

If/when storage pressure does land, the eviction policy is: drop rows where `published_at < now - 365d` AND `classification.bias_score ∈ (-0.2, +0.2)` (the neutral chatter is the cheap thing to lose; the high-conviction rows stay forever).

---

## 6. Cost model

**Embedding** (Voyage `voyage-finance-2`, $0.12 / 1M tokens):
- ~300 items/day × ~400 tokens/item = 120K tokens/day
- $0.014/day → **~$0.42/mo**

**LLM classification** (OpenRouter `openai/gpt-4o-mini`, ~$0.15 in + $0.60 out per 1M):
- 300 × (600 in + 80 out) = 180K in + 24K out per day
- $0.04/day → **~$1.20/mo**

**Total runtime cost for `market_news`: ~$1.60/mo.** Founder gates both the Voyage spend and the classifier spend; sink lands UNclassified + UNembedded rows by default. Patching is opt-in.

---

## 7. Wire from trade-panel `NewsProvider` (PROPOSAL — do not implement here)

The `NewsProvider` abstraction already exists at `packages/gecko-core/src/gecko_core/orchestration/trade_panel/news_provider.py` and is consumed by `merge_news_chunks(...)`. To fan out to Mongo without touching panel logic, the 3-line wire mirrors the `BehaviorSink` pattern at `contest_bot/jto_breakout_gecko_gated_contest_bot.py:2440`:

```python
# in packages/gecko-core/src/gecko_core/orchestration/trade_panel/news_provider.py
# inside merge_news_chunks, after `news = await provider.fetch_news_chunks(...)`:
try:
    from contest_bot.decision_store.news_sink import NewsSink  # lazy; sink optional
    _NEWS_SINK = getattr(merge_news_chunks, "_sink", None) or NewsSink.from_env()
    merge_news_chunks._sink = _NEWS_SINK  # cache; from_env once per process
    if _NEWS_SINK is not None:
        for c in news:
            _NEWS_SINK.record({
                "source": c.get("source", "okx-news"),
                "source_id": c.get("id"),
                "url": c.get("url"),
                "headline": (c.get("text") or "").split(".", 1)[0],
                "body": c.get("text"),
                "published_at": c.get("published_ts"),
                "tickers": [c.get("protocol", "").upper()] if c.get("protocol") else [],
            })
except Exception:
    pass  # best-effort; never blocks the panel
```

**This is a PROPOSAL.** The actual edit lands in a separate PR reviewed by `ai-ml-engineer` (owns the trade-panel call site) + `staff-engineer` (cross-package import — `gecko-core` importing from `contest_bot` reverses the dependency direction, may need to move `NewsSink` into `gecko-core` first). Flagged for the boundary discussion.

Alternative: place the fan-out in the OKX adapter (`okx_news_adapter.py`) rather than the generic `merge_news_chunks`, so the dependency goes adapter → sink (still bottom-up).

---

## 8. Code surfaces

| Path | Purpose |
|---|---|
| `contest_bot/decision_store/news_sink.py` | `NewsSink` class — write side, mirror of `BehaviorSink` |
| `contest_bot/decision_store/news_query.py` | `recent`, `by_symbol`, `by_source` — read helpers |
| `contest_bot/tests/test_news_sink.py` | 22 tests covering schema / idempotency / best-effort / queries |
| `scripts/data/init_market_news_collection.py` | one-shot collection + index creator (idempotent), prints vector DDL |

---

## 9. Boundary respect / non-negotiables

- Reuses existing `voyage-finance-2` / 1024-dim convention (per `decision_store/embedder.py`).
- LLM classification routes through OpenRouter (per `feedback_openrouter_not_openai_for_new_llm`).
- `MONGODB_DB` defaults to `gecko_cache` (matches founder's `.env`; design doc says `gecko` but the audit confirmed `gecko_cache` is in use — **divergence flagged**, follow env).
- Atlas Search vector index creation is **founder-gated** per `project_2026_05_26_session_endstate` — the init script emits DDL only.
- Sink is **best-effort**: every Mongo write failure is logged + swallowed. Caller (trade panel, future cron) never sees a sink exception. JSONL / in-process panel chunks remain the durable source of truth.
- No new dependencies. Uses `pymongo` already in the workspace.

---

## 10. Open questions for founder

These mirror design doc §8 Q3, Q4, Q6, restated against the current shipped surface:

1. **Wire path** — fan out from `merge_news_chunks` (generic, covers any future provider) or from `okx_news_adapter` (concrete, avoids the `gecko-core → contest_bot` import). Recommendation: **adapter-level**, then promote `NewsSink` into `gecko-core` if/when a second adapter lands.
2. **Embed cadence** — embed at ingestion time (sync per-record cost, immediate retrievability) or nightly batch (cheaper amortized cost, 24h lag on retrieval). Recommendation: **nightly batch** in v1; the market_researcher voice can run on the indexed-but-unembedded rows via ticker filter for the first 24h after a story breaks.
3. **CryptoPanic free tier** — confirm we accept their 60 req/h limit (gives us 6/min × 10-min cron = 60 calls per cycle, more than enough). If we pay $40/mo for the Pro tier we get unlimited + sentiment scores baked in (would replace our classifier). Recommendation: **start free, upgrade if classifier cost > $40/mo or if our LLM bias scores prove noisier than CryptoPanic's**.
