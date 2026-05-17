# S33-#75 — Protocol-native endpoint curation: market data over documentation

**Date:** 2026-05-16
**Author:** trading-strategist (research half of S33-#75)
**Status:** research complete — handoff to `data-engineer` for implementation
**Scope:** `packages/gecko-core/src/gecko_core/sources/protocol_native.py` curation. No code changed by this ticket.

---

## 1. The finding restated

N=10 rubric measurement after re-ingesting 524 `protocol_native` chunks: `citation_relevance` flat at ~0.20 (target 0.50), `overall_pass_rate` 0.0.

Per-endpoint audit:

| Protocol | What ingested | Fixture citRel |
|---|---|---|
| kamino | `kamino-vaults`, `kamino-staking-yields`, `kamino-strategies`, `kamino-markets` — **market data** (APY, TVL, mints, caps) | 0.20–0.55 |
| drift | `drift-glossary`, `drift-account-model`, `drift-trading-fees`, `drift-github-readme`, `drift-market-specs` (a doc page) — **documentation pages** | **0.00** |
| jito | `jito-rust-rpc-readme`, `jito-js-rpc-readme`, `jito-solana-security`, `jito-restaking-readme` — **developer READMEs** | **0.00** |
| jupiter | mix: `jupiter-sol-price`/`jupiter-lst-prices`/token-tag lists are data; ~25 `dev.jup.ag/docs/...` entries are doc prose | 0.35–0.55 |

Root cause is **not** tagging or retrieval — chunks are correctly tagged `protocol_native` and reach the panel. The problem: a glossary page or a Rust client README cannot ground a verdict on "should I short JTO perp" or "is SOL-PERP funding rich." Documentation explains *mechanism*; a verdict needs *current tradeable numbers*. drift and jito ingest almost exclusively documentation. They score 0.00 because there is no number to cite.

**The fix is a corpus-content fix, not a pipeline fix.** Replace doc URLs with live market-data API endpoints. The pipeline already proves it works when fed data (kamino 0.20–0.55).

---

## 2. DRIFT — replace docs with the Drift Data API

Drift runs a public, no-key Data API at `https://data.api.drift.trade` (the "Velocity Data API"). OpenAPI spec is live and machine-readable at `https://data.api.drift.trade/openapi.json` — 92 paths. Interactive playground at `/playground`. This is the canonical source of *tradeable* Drift numbers and it is what the current `drift-*` doc endpoints should be replaced with.

**Probe results (2026-05-16, no API key, `User-Agent: gecko/1.0`):**

| Endpoint | Status | Returns |
|---|---|---|
| `GET /market/{symbol}/fundingRates?limit=N` | ✅ real data | Funding-rate records: `fundingRate`, `fundingRateLong/Short`, `cumulativeFundingRateLong/Short`, `oraclePriceTwap`, `markPriceTwap`, `periodRevenue`, `ts`, `slot`. Verified SOL-PERP + BTC-PERP. |
| `GET /stats/markets/prices` | ✅ real data | Per-market `price24hAgo`, `marketIndex`, `marketType` for all perps (SOL/BTC/ETH/APT/BONK/POL/ARB/...). Note: `currentPrice`/`priceChange` fields came back empty at probe time — `price24hAgo` is reliably populated. |
| `GET /stats/markets` | ⚠️ `{markets:[]}` | Empty at probe time — do NOT ingest until verified non-empty. |
| `GET /stats/fundingRates` | ⚠️ `{success:true}` only | No `markets` payload at probe time. Skip until verified. |
| `GET /stats/insuranceFund` | ⚠️ `{data:{}}` | Empty at probe time. Skip until verified. |
| `GET /amm/openInterest`, `/amm/oraclePrice` | ⚠️ `{data:[]}` | Returned empty for the probed window. Date-windowed; see caveat §5. |
| `GET /market/{symbol}/candles/{resolution}` | ⚠️ `{records:[]}` | Empty at probe time for SOL-PERP/60. See caveat §5. |
| `GET /external/coingecko/contracts` | ⚠️ `{contracts:[]}` | Empty — would be ideal (CoinGecko-shaped contract metadata incl. OI) if populated. Re-probe before relying on it. |

**Caveat (§5 detail):** the Drift Data API indexer appears stale/paused — funding-rate records carry `ts≈1775066400` (≈early-Apr 2026), and the windowed endpoints returned empty for a *current* time window. The `fundingRates` history endpoint nonetheless returns substantive, real records (mark vs oracle TWAP spread, signed funding) — that is exactly the data a trade panel needs to reason about funding richness, even if a few days stale. `freshness_tier='daily'` already signals "not real-time" so this is acceptable for v0.1. The `data-engineer` should pass `start`/`end` as a wide trailing window (e.g. last 30d) rather than "last 7d" so windowed endpoints have a chance to hit indexed data.

### DRIFT — KEEP / ADD / DROP

**ADD (market-data endpoints — these are the fix):**

| Slug | URL | Data | Trade relevance |
|---|---|---|---|
| `drift-funding-sol-perp` | `https://data.api.drift.trade/market/SOL-PERP/fundingRates?limit=30` | 30 funding-rate records: signed rate, long/short, cumulative, mark/oracle TWAP, period revenue | Directly grounds "is SOL-PERP funding rich / should I carry / pay-to-hold" verdicts |
| `drift-funding-btc-perp` | `https://data.api.drift.trade/market/BTC-PERP/fundingRates?limit=30` | same shape, BTC-PERP | Same, BTC perp carry |
| `drift-funding-eth-perp` | `https://data.api.drift.trade/market/ETH-PERP/fundingRates?limit=30` | same shape, ETH-PERP | Same, ETH perp carry |
| `drift-market-prices` | `https://data.api.drift.trade/stats/markets/prices` | All perp markets: `price24hAgo`, marketIndex, marketType | Live-ish market catalog + 24h reference price; grounds "which markets exist + where price sits" |

(Optional, gate on a non-empty re-probe before ingest — see §5: `drift-stats-markets` = `/stats/markets`, `drift-coingecko-contracts` = `/external/coingecko/contracts` for open interest. Do NOT ingest while empty — an empty payload re-creates the `{"data":[]}` poison-chunk bug.)

**KEEP (1 doc endpoint — funding mechanics is genuinely needed as the *interpretation layer* for the numbers):**

| Slug | Why keep |
|---|---|
| `drift-funding-rates` (`docs.drift.trade/.../funding-rates`) | The panel needs the formula to interpret a raw `fundingRate` string — the docs say "divide by `oraclePriceTwap` to get a percentage." Keep exactly this one doc page as the interpretation key. |

**DROP (29 documentation endpoints — they score 0.00, they are dead corpus weight):**

Drop every `_drift(...)` entry in `DRIFT_ENDPOINTS` **except** `drift-funding-rates`, and add the 4 ADD endpoints above. Concretely, drop: `drift-docs-root`, `drift-perps-trading`, `drift-auction-parameters`, `drift-liquidations`, `drift-liquidation-engine`, `drift-liquidators`, `drift-oracles`, `drift-risk-parameters`, `drift-risks`, `drift-safety-module`, `drift-insurance-fund-staking`, `drift-margin`, `drift-margin-account-health`, `drift-margin-per-market-leverage`, `drift-jit-auctions-mm`, `drift-amm`, `drift-matching-engine`, `drift-decentralized-orderbook`, `drift-borrow-lend-faq`, `drift-borrow-interest-rate`, `drift-isolated-pools`, `drift-amplify-risk`, `drift-market-specs` (a doc page, not live specs), `drift-trading-fees`, `drift-profit-loss`, `drift-profit-loss-pool`, `drift-revenue-pool`, `drift-glossary`, `drift-account-model`, `drift-github-readme`. Also drop `drift-dlob-markets` (`dlob.drift.trade/markets`) — it is superseded by the Data API endpoints above and its shape is unverified.

Net: drift goes from 32 endpoints (31 docs + 1 stale DLOB) to **5 endpoints (4 data + 1 mechanics doc)**.

---

## 3. JITO — wire in the MEV data, drop the READMEs

### 3a. The decision: run `ingest_jito_mev.py`, do NOT merge it into the main path

A separate tracked script `scripts/protocol_native/ingest_jito_mev.py` + its source catalog `gecko_core/sources/jito_mev.py` already exist (S31-#50). They target the MEV-side endpoints and tag chunks `metadata.subkind="mev_tip_data"`. **Recommendation: keep `ingest_jito_mev.py` as a separate script and run it; do NOT fold its endpoints into `protocol_native.py`.**

Justification:
- It already carries the correct `provider_kind="protocol_native"`, `protocol=("jito",)`, `vertical="dex"` — chunks land in the same retrieval slice the main path uses. There is no retrieval benefit to merging.
- The `subkind="mev_tip_data"` disambiguator is a real debugging asset; merging into the generic path would lose the dedicated `metadata_extra` tag unless the main script grows special-casing.
- `chunk_size=1000` is intentionally tuned for tip-floor JSON; the main path's default chunker is 512.
- Merging is a code change that touches the ingest path; this ticket is curation, not refactor.

**However** — the MEV script's own catalog (`jito_mev.py`) still ships 9 doc/README endpoints (`_DOCS_ENDPOINTS` + `_CLIENT_ENDPOINTS`). Those have the same 0.00 problem. See §3c.

### 3b. JITO MEV data — verified live

Probe results (2026-05-16):

| Endpoint | Status | Returns |
|---|---|---|
| `https://bundles.jito.wtf/api/v1/bundles/tip_floor` | ✅ real data | `[{landed_tips_25th/50th/75th/95th/99th_percentile, ema_landed_tips_50th_percentile, time}]` — the percentile tip ladder in SOL. Probe: P25 3.3e-6, P50 7.6e-6, P75 1.66e-5, P95 4.3e-5, P99 6.1e-3 SOL. |
| `https://kobe.mainnet.jito.network/api/v1/mev_rewards` | ✅ real data | `{epoch, total_network_mev_lamports, jito_stake_weight_lamports, mev_reward_per_lamport}` — epoch-level MEV magnitude. Probe: epoch 971, 2871.6 SOL network MEV. |
| `https://kobe.mainnet.jito.network/api/v1/validators` | ✅ real data | 722 validators: `mev_commission_bps`, `mev_rewards`, `priority_fee_commission_bps`, `active_stake`, `running_jito`, `running_bam`, `jito_directed_stake_lamports`. |
| `https://kobe.mainnet.jito.network/api/v1/recent_blocks` | ❌ **HTTP 404** | Endpoint is dead (content-length 0, status 404). DROP it. |

### 3c. JITO — KEEP / ADD / DROP

**KEEP (3 live MEV data endpoints in `jito_mev.py`'s `_LIVE_ENDPOINTS`):**
`jito-mev-tip-floor-live`, `jito-mev-rewards-snapshot`, `jito-mev-validators-telemetry` — all verified returning real numbers. The existing `_render_tip_floor_payload` renderer in `protocol_native.py` already flattens the tip ladder to prose; confirm the MEV script's `render_chunk` produces citable prose for `mev_rewards`/`validators` too (it currently wraps body verbatim — acceptable since these are small flat JSON objects).

**DROP from `jito_mev.py`:**
- `jito-mev-recent-blocks` — HTTP 404, dead endpoint.
- All of `_DOCS_ENDPOINTS` (`jito-mev-docs-low-latency-txn-send`, `jito-mev-docs-low-latency-txn-feed`, `jito-mev-docs-root`, `jito-mev-searchers-product`) — doc/marketing prose, 0.00 class.
- All of `_CLIENT_ENDPOINTS` (`jito-mev-protos-readme`, `jito-mev-js-rpc-readme`, `jito-mev-py-rpc-readme`, `jito-mev-rust-rpc-readme`, `jito-mev-go-rpc-readme`) — developer READMEs, the exact 0.00 class the audit flagged.

**DROP from `protocol_native.py`'s `JITO_ENDPOINTS` (the staking-side catalog):**
The 4 live `kobe`/`bundles` quote endpoints in `JITO_ENDPOINTS` (`jito-tip-floor`, `jito-mev-rewards`, `jito-validators`, `jito-recent-blocks`) **duplicate** the MEV script. Drop them from `protocol_native.py` and let `ingest_jito_mev.py` own all Jito live data — single owner, no double-ingest. Also drop `jito-recent-blocks` (404).
Drop all 15 doc/README/product-page endpoints: `jito-docs-root`, `jito-docs-low-latency-txn-send`, `jito-docs-low-latency-txn-feed`, `jito-wtf-searchers`, `jito-wtf-stakers`, `jito-wtf-validators`, `jito-wtf-blog-index`, `jito-stakenet-readme`, `jito-stakenet-keeper-quickstart`, `jito-stakenet-docs-index`, `jito-restaking-readme`, `jito-restaking-docs-index`, `jito-solana-readme`, `jito-solana-security`, `jito-mev-protos-readme`, `jito-js-rpc-readme`, `jito-py-rpc-readme`, `jito-go-rpc-readme`, `jito-rust-rpc-readme`.

**JitoSOL staking/yield data worth keeping:** there is no first-party Jito *staking-yield* JSON endpoint that returns a real APY (the `kobe` API is MEV-side; `recent_blocks` is dead). JitoSOL APY is already covered indirectly — `kamino-staking-yields` tracks JitoSOL APY, and `jupiter-lst-prices` includes the JitoSOL mint. **Recommendation: do not add a separate Jito staking endpoint.** If a dedicated JitoSOL APY number is wanted later, the StakeWiz API (`https://api.stakewiz.com`) or Jito's own stake-pool on-chain account are options for v0.2 — flagged, not in scope here.

Net: Jito goes from 23 doc-heavy endpoints (19 in `protocol_native.py` + the MEV script's 9 minus the 4 live) to **3 live MEV data endpoints, all owned by `ingest_jito_mev.py`**.

---

## 4. KAMINO + JUPITER — sanity check

### Kamino — KEEP ALL, no change

`kamino-markets`, `kamino-vaults`, `kamino-strategies`, `kamino-staking-yields` all return substantive market JSON (vault APY/TVL/mints/caps, market catalog). citRel 0.20–0.55 confirms the pipeline works on this content. The `_render_kamino_payload` per-entity renderer is already in place. **No drops, no adds.** Kamino is the proof the fix is content, not pipeline.

### Jupiter — KEEP the 5 data endpoints, DROP most doc endpoints

Jupiter scored 0.35–0.55 — the floor is held up by 5 real data endpoints; the 25 doc-prose endpoints drag the average.

**KEEP (5 data endpoints — verified `lite-api.jup.ag` JSON):**
`jupiter-sol-price`, `jupiter-lst-prices`, `jupiter-tokens-verified-list`, `jupiter-tokens-lst-list`. These return live price + token-universe data and have structured renderers (`_render_jupiter_payload`).

**DROP (25 `dev.jup.ag/docs/...` documentation endpoints):**
All `_jup(...)` entries whose URL resolves under `dev.jup.ag/docs/` — `jupiter-docs-root`, `jupiter-swap-root`, `jupiter-swap-order-execute`, `jupiter-swap-slippage`, `jupiter-swap-reduce-latency`, `jupiter-swap-compute-units`, `jupiter-swap-routing-dex-integration`, `jupiter-swap-routing-market-listing`, `jupiter-swap-routing-rfq`, `jupiter-perps-root`, `jupiter-perps-pool-account`, `jupiter-perps-custody-account`, `jupiter-perps-position-account`, `jupiter-perps-position-request`, `jupiter-tokens-root`, `jupiter-tokens-verification`, `jupiter-tokens-token-information`, `jupiter-price-doc`, `jupiter-lend-architecture`, `jupiter-lend-oracles`, `jupiter-lend-liquidation`, `jupiter-lend-advanced-multiply`, `jupiter-lend-advanced-unwind`, `jupiter-trigger-best-practices`, `jupiter-recurring-best-practices`, `jupiter-portal-rate-limits`, `jupiter-resources-audits`.

These are the same 0.00 class as drift/jito docs — they just got averaged up by the 5 data endpoints. Dropping them is low-risk and lifts the Jupiter average. This is the "don't over-invest, but flag it" item from the brief: do the drop, don't research further.

(Optional ADD for a future pass — Jupiter perps has a public stats surface; not researched here, out of scope.)

Net: Jupiter goes from 32 endpoints (5 data + 27 docs) to **5 data endpoints**.

---

## 5. Caveats — paid / unreachable / unstable

- **Drift Data API indexer is stale.** Funding-rate records carry `ts≈1775066400` (early-Apr 2026); windowed endpoints (`/amm/openInterest`, `/amm/oraclePrice`, `/candles`) returned empty for a current 7-day window at probe time. The history endpoints still return real records — usable but date-stale. `freshness_tier='daily'` already signals this. Implementer: use a **wide trailing window (30d+)** for windowed endpoints, and verify non-empty before ingest.
- **Empty-payload guard is mandatory.** `/stats/markets`, `/stats/fundingRates`, `/stats/insuranceFund`, `/external/coingecko/contracts` all returned empty/skeleton JSON at probe time. The ingest script's existing empty-body guard (`{"data":[]}`, `[]`, `{}` → skip) must catch these. Do NOT ingest an empty payload — it re-creates the `paysh_live {"data":[]}` poison-chunk bug that is the literal origin story of this module (see file docstring lines 3–8).
- **`recent_blocks` is dead** — `kobe.mainnet.jito.network/api/v1/recent_blocks` returns HTTP 404. Drop it everywhere.
- **No paid access required** — every recommended endpoint is free, public, no API key. Drift Data API, Jito `bundles.jito.wtf` and `kobe.mainnet.jito.network`, Jupiter `lite-api.jup.ag`, Kamino `api.kamino.finance` are all keyless.
- **No JitoSOL APY first-party JSON** — flagged §3c; deferred to v0.2.

---

## 6. Implementation handoff — `data-engineer`

Concrete, executable against `packages/gecko-core/src/gecko_core/sources/protocol_native.py` and `.../jito_mev.py`.

### 6.1 `protocol_native.py` — `DRIFT_ENDPOINTS`

1. Delete all 32 current `DRIFT_ENDPOINTS` entries **except** `drift-funding-rates`.
2. Add 4 new entries (`content_kind="quote"`, full `https://` URLs so the `_drift` helper passes them through):
   - `drift-funding-sol-perp` → `https://data.api.drift.trade/market/SOL-PERP/fundingRates?limit=30`
   - `drift-funding-btc-perp` → `https://data.api.drift.trade/market/BTC-PERP/fundingRates?limit=30`
   - `drift-funding-eth-perp` → `https://data.api.drift.trade/market/ETH-PERP/fundingRates?limit=30`
   - `drift-market-prices` → `https://data.api.drift.trade/stats/markets/prices`
3. **New renderer needed.** The Drift funding-rate payload is `{"success":true,"records":[{...}]}` — a dict-wrapping-a-list, not a bare list, so `_render_fallback` would JSON-flatten it into low-value prose. Add a `_render_drift_funding_payload(ep, body, as_of_iso)` that reads `body["records"]`, and per record emits one prose sentence: e.g. `"Drift SOL-PERP funding at <ts>: rate -0.001025 (quote/base), mark TWAP 84.65, oracle TWAP 84.69, period revenue -2063.30."` Register it in `_RENDERERS` for the three `drift-funding-*` slugs. For `drift-market-prices` (`{"success":true,"markets":[...]}`), add a small renderer that emits one line per market: `"Drift SOL-PERP (index 0): 24h-ago price 83.68."` — or extend `_render_jupiter_payload`-style entity logic to read `body["markets"]`.
4. Coordinate the funding-rate interpretation: the renderer should state "divide rate by oracle TWAP for percentage" once so the panel can convert.

### 6.2 `jito_mev.py` — `JITO_MEV_ENDPOINTS`

1. In `_LIVE_ENDPOINTS`: delete `jito-mev-recent-blocks` (404). Keep `jito-mev-tip-floor-live`, `jito-mev-rewards-snapshot`, `jito-mev-validators-telemetry`.
2. Delete `_DOCS_ENDPOINTS` entirely (4 entries).
3. Delete `_CLIENT_ENDPOINTS` entirely (5 entries).
4. `JITO_MEV_ENDPOINTS` becomes just the 3 surviving `_LIVE_ENDPOINTS`.
5. Optional polish: `render_chunk` in `jito_mev.py` wraps the body verbatim. For `mev_rewards` and `validators` that is acceptable (small flat JSON). The tip-floor endpoint is better served by `protocol_native.py`'s `_render_tip_floor_payload` — if feasible, route tip-floor through that renderer; otherwise verbatim is tolerable since the JSON is tiny.

### 6.3 `protocol_native.py` — `JITO_ENDPOINTS`

Delete the entire `JITO_ENDPOINTS` tuple (all 23 entries) — the 4 live quote endpoints duplicate `jito_mev.py`, the other 19 are docs/READMEs. Remove `"jito"` from the `endpoints_for_protocol` catalog dict OR point it at an empty tuple. Jito live data is owned solely by `ingest_jito_mev.py` going forward. Remove `JITO_ENDPOINTS` from `ALL_PROTOCOL_ENDPOINTS` and from `__all__`.

### 6.4 `protocol_native.py` — `JUPITER_ENDPOINTS`

Delete all 27 `dev.jup.ag/docs/...` doc entries. Keep the 4 `lite-api.jup.ag` data entries: `jupiter-sol-price`, `jupiter-lst-prices`, `jupiter-tokens-verified-list`, `jupiter-tokens-lst-list`.

### 6.5 `protocol_native.py` — `KAMINO_ENDPOINTS`

No change.

### 6.6 Run order

1. Apply the catalog edits above.
2. `uv run python scripts/protocol_native/ingest_jito_mev.py --dry-run` then without `--dry-run`.
3. `uv run python scripts/protocol_native/ingest_protocol_native.py --dry-run` then live (kamino + drift + jupiter, ~14 endpoints).
4. Before each live run, confirm the empty-body guard skips any endpoint returning empty JSON (drift `/stats/*` may still be empty).
5. Re-run the N=10 defi-trade rubric suite. Expectation: drift + jito fixtures move off 0.00 because there is now a number to cite; `citation_relevance` should rise toward the 0.50 target.

### 6.7 Net corpus shape after this ticket

| Protocol | Before | After |
|---|---|---|
| kamino | 4 (all data) | 4 (unchanged) |
| drift | 32 (31 doc + 1 stale DLOB) | 5 (4 data + 1 mechanics doc) |
| jupiter | 32 (5 data + 27 doc) | 4 (all data) |
| jito | 23 in `protocol_native` + 13 in MEV script | 3 (all live MEV data, MEV script only) |
| sanctum | 20 (docs, S33-#65) | unchanged — out of scope; see note |

Sanctum is out of scope for this ticket but carries the same disease (20 doc endpoints, no live quote source — its APY API returns structural 0.0 per S33-#65). Flag for a follow-up ticket: sanctum needs a live LST-APY data source or it should be cut.

---

## 7. The one-line summary

The pipeline is fine. drift and jito ingested **documentation**; documentation has no number to cite, so the panel scores 0.00. Replace 51 doc/README URLs with **12 live market-data endpoints** (Drift Data API funding rates + prices, Jito MEV tip-floor + rewards + validators, plus the already-good Kamino + Jupiter data endpoints). Run `ingest_jito_mev.py` as-is — don't merge it. Then re-measure.
