# S39 Backtest Phase 2 — `reconstruction.py` design

**Date:** 2026-05-19 · **Owner:** `data-engineer` (+ `trading-strategist` on
adverse-event curation, later). **Depends on:** Phase 1 `as_of` gate (`fd082c8`,
branch `s39/backtest-phase1`). **Companion:** `2026-05-19-backtesting-scoping-plan.md`
§2b — this doc resolves that section's open design question.

## 0. The settled design question

> Reconstructed historical chunks must be usable by the panel during a
> backtest at time T, but must NOT leak into live production retrieval.
> Where do they live?

**Decision — Option C: reconstruct in-memory, inject; never persist to the
`chunks` corpus, never vector-index.**

The panel entry point `run_trade_panel(retrieved_chunks=...)` is contractually
retrieval-free (Phase 8a lock) — it consumes a pre-fetched chunk list. Phase 2
uses that existing seam:

- **Reconstructed market chunks** for the pool-under-test are built per
  backtest run and passed straight into `run_trade_panel` as `retrieved_chunks`.
  They never touch the production `chunks` collection and are never indexed.
- **Canon** stays in the production corpus, retrieved via
  `retrieve_trade_corpus_chunks(as_of=T)` — the Phase 1 gate. Canon is timeless
  (`as_of_date` null) so the gate admits it at any T and it is leak-safe.
- **The backtest slate** = canon (gated vector search) ∪ reconstructed market
  chunks (injected in-memory). The harness merges the two and calls
  `run_trade_panel` directly.
- **Production is byte-identical:** `as_of=None`, no injected slate. Phase 1's
  verified no-op holds unchanged.

**Rejected alternatives:**

- **Option B — tag chunks `corpus_scope:backtest`, exclude in the production
  `$match`.** Makes production retrieval correctness depend on a never-forget
  exclusion filter on the hot path — exactly Pattern A / Pattern F (a filter
  that must be replicated across every retrieval path or it silently leaks).
  Rejected.
- **Option A — separate `backtest_chunks` collection + a second Atlas vector
  index.** Over-engineering: reconstructed facts are a small, deterministic,
  *known* set for one chosen pool at one T — there is nothing to vector-rank.
  A second index + collection-switching retrieval logic buys nothing.
  Rejected.

Caches are not corpora: raw immutable DeFiLlama/Pyth fetches may be persisted
in dedicated `backtest_*` collections (the existing `protocol_price_history`
collection is precedent). A cache that the production `$vectorSearch` path
never queries carries zero leak risk.

## 1. Scope of `reconstruction.py`

Lives at `packages/gecko-core/src/gecko_core/orchestration/trade_panel/backtest/reconstruction.py`
(alongside `history_source.py`, `storage.py`, `simulator.py`).

Public surface — one async function:

```python
async def reconstruct_pool_chunks(
    pool: str,            # DeFiLlama pool id / protocol-pool key
    *,
    as_of: str,           # YYYY-MM-DD — the point-in-time T
    protocol: str,        # normalized protocol name (for chunk tagging)
) -> list[dict[str, Any]]:
    """Fetch DeFiLlama APY/TVL history, truncate at T, render to chunk
    dicts. Returns an in-memory chunk slate — NEVER written to `chunks`."""
```

Pipeline:

1. **Fetch** — DeFiLlama `https://yields.llama.fi/chart/{pool}` (APY + TVL
   series per pool; free, no key). Pyth historical is optional/secondary —
   Hermes has no OHLCV endpoint (see `history_source.py` reality check), so
   v1 is DeFiLlama-only for the yield series. SSRF/httpx caps from CLAUDE.md
   apply: validate the URL, block private ranges, cap response size, timeout.
2. **Truncate at T** — drop every series point with timestamp `> as_of`.
   This is the no-lookahead guarantee. A point-in-time render must see only
   `<= T` data. Fail loud if truncation leaves zero points.
3. **Cache** — raw fetched series cached on `(pool, fetch-window)` in a
   dedicated `backtest_reconstruction_cache` collection. Historical data is
   immutable → cache hit re-runs cost $0. Truncation happens AFTER cache read
   (cache the full series, truncate per-T) so one fetch serves many T values.
4. **Render** — feed the truncated series through the *existing*
   `sources/market_data.py` renderers. Do NOT fork the renderer — a forked
   renderer tests a different system (Pattern E). Output: chunk dicts in the
   standard shape, each carrying `as_of_date = as_of`, `provider_kind`
   (`market_data` / `protocol_native`), `freshness_tier`.
5. **Return** the list. Caller (harness) merges with gated canon.

## 2. Harness wiring

The Phase 0 harness (`trade_agent/backtest/harness.py`) and the trade-panel
backtest path call `reconstruct_pool_chunks(pool, as_of=T, protocol=...)`,
then build the panel slate as:

```
canon = await retrieve_trade_corpus_chunks(idea, protocol, as_of=T, ...)
        # gate admits timeless canon + any dated chunk <= T
market = await reconstruct_pool_chunks(pool, as_of=T, protocol=protocol)
slate  = canon + market
verdict = await run_trade_panel(idea, protocol, retrieved_chunks=slate, ...)
```

`retrieve_trade_corpus_chunks` at `as_of=T` still vector-searches the
production corpus — that is intended for canon. The reconstructed market
chunks are the injected half. Production callers pass neither `as_of` nor a
reconstructed slate and are unaffected.

## 3. Verification (Pattern B + Pattern F)

- **Pattern B** — first deliverable is a free local simulation: a recorded
  DeFiLlama `/chart` fixture (vcr-style) so the fetch+truncate+render path is
  falsifiable with no network and no spend. Live fetch is the final smoke,
  not the debug tool.
- **No-lookahead probe** — reconstruct a pool at T, assert every returned
  chunk's underlying series timestamp is `<= T`; assert a point known to be
  `> T` is absent. This is the reconstruction analogue of the Phase 1
  leakage probe.
- **Corpus-isolation probe** — after a full backtest run, assert the
  production `chunks` collection count is unchanged (reconstructed chunks
  never persisted) and a production retrieval (`as_of=None`) returns zero
  chunks with the backtest run's `as_of_date`.
- Light fakes over heavy simulation (per `feedback_lighter_tests`): test
  truncation, the URL guard, the cache key, and the render mapping as pure
  units; one integration test over the recorded fixture.

## 4. Out of scope for Phase 2

- Pyth OHLCV reconstruction (Hermes has no bars endpoint — Phase 9.5).
- The contamination-controlled cycle (Phase 3 — `quant-analyst`).
- `bb backtest` CLI polish, multi-protocol sweeps, any `gecko-mcpay-app`
  surface (deferred beyond S39).
