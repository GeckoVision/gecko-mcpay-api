# Pegana peg-risk ingest — design (2026-06-10)

**Status:** scaffolding (overnight auto-mode). Founder reviews placement + gate-wiring before deep integration.

## What Pegana is
`api.pegana.xyz` — a **peg-risk oracle for Solana**. Real-time peg state, history, alerts, and delivery health across **21 active mainnet assets in 6 classes** (8 LSTs — jitoSOL/mSOL/bSOL/JupSOL/INF…; plus `stable_fiat`, `stable_cdp`, `stable_dn`, `stable_yield`, `synth_lev`). OpenAPI at `api.pegana.xyz/openapi.json` (v0.1.0, 34 paths).

This is **directly on-brand for the safety layer**: a depeg on a collateral or yield leg is exactly the risk the pre-trade gate and the vault safety-monitor should read. It is the structured, third-party, *independent* evidence the wedge is built on — not Gecko grading its own thesis.

## Why it's a *data-provider* source, not a corpus source
Pegana returns structured numeric risk state (`state`, `discount`, `intrinsic_usd` vs `market_usd`, `confidence`, `stale`), not prose. It must **not** be wired into the RAG dispatcher / embedding path. It is a market-data/risk provider in the Phase-4 ("external data-provider ingest") sense — closest existing kin: `contest_bot/market_temp.py` (risk-off context) and `hotpath/pyth.py` (typed httpx client house style).

## Public endpoints (no auth — verified 200)
| Endpoint | Use |
|---|---|
| `GET /v1/assets` | All tracked assets + current state (1 call = whole universe) |
| `GET /v1/assets/{symbol}/state` | Single peg state (state, discount, intrinsic/market usd, `stale`, `since`) |
| `GET /v1/assets/by-mint/{mint}/state` | Same, keyed by SPL mint (what the gate has at trade time) |
| `GET /v1/assets/{symbol}/history` | Peg-state history (for backtests / drift trends) |
| `GET /v1/alerts` | Recent peg alerts (list) |
| `GET /v1/stats` | Universe summary: `assets_tracked`, `assets_in_drift`, `by_state`, `delivery_health` |
| `GET /v1/methodology/current` | How peg state is computed (cite-able in verdicts) |
| `GET /healthz`,`/readyz` | Liveness/readiness. **NB:** `/health` 404s — the founder's "errored endpoint" was just the wrong path; correct path is `/healthz`. |

The `/v1/me/*`, `/v1/auth/*`, `/v1/me/webhooks/*` paths require `telegram_jwt` — **out of scope** (those are end-user subscription/webhook features, not data ingest).

## Data shapes (from live fixtures, captured to `tests/sources/fixtures/pegana_*.json`)
- **asset** (`/v1/assets[]`): `symbol, name, mint, class, peg_target, decimals, state, discount, intrinsic_usd, market_usd, updated_at, confidence, series_24h, sol_per_lst, thresholds, worst_abs_24h, jitter_bps_24h`
- **state** (`/v1/assets/{symbol}/state`): `asset, state, since, discount, intrinsic_usd, market_usd, updated_at, stale`
- `state` enum observed: `PEGGED`, `DRIFT` (1 asset live-drifting at capture time). Discounts are signed ratio strings (e.g. `"-0.013647"`).

## Integration: the depeg risk-off input
The reusable primitive is a normalized read the gate consumes:

```
depeg_risk(symbol_or_mint) -> {
  state: "PEGGED"|"DRIFT"|...,
  is_pegged: bool,
  discount_abs: float,      # |market-intrinsic| ratio
  stale: bool,
  confidence: float|None,
  risk_off: bool,           # True if state != PEGGED OR stale (Pegana's state is authoritative)
  as_of: datetime,
}
```

**Trust Pegana's `state` — do NOT impose a naive global discount cut.** Pegana
encodes *class-aware* thresholds (an LST's normal unstaking-delay discount is far
wider than a fiat stable's). Live proof from the fixtures: **INF** reads `PEGGED`
at a **−1.36%** raw discount (healthy LST), while **sUSD** reads `DRIFT` at
**+2.29%** (real depeg). A global 0.5% cut would wrongly flag INF. So
`risk_off = (state != PEGGED) OR stale`. A stricter `discount_threshold` is an
**opt-in** parameter, off by default.

**Gate rule (follow-up, founder-reviewed):** for any trade whose collateral / target asset is Pegana-tracked, if `risk_off` → the pre-trade safety gate **blocks or down-weights** (mirrors the `market_temp` risk-off pattern, S40/S41).

## This PR (scaffold) delivers
1. `gecko_core/sources/pegana.py` — typed async httpx client (`PeganaClient`) + pydantic models (`PeganaAsset`, `PeganaPegState`, `PeganaStats`) + the `depeg_risk()` helper. httpx+pydantic only; no DB/RAG/orchestration imports.
2. Recorded-fixture contract test (Pattern C) — parses the live fixtures, asserts the DRIFT asset reads `risk_off=True`. No network in CI.
3. This doc.

## Deliberately deferred (founder-gated / follow-up)
- Wiring `depeg_risk` into the actual pre-trade safety gate + the vault safety-monitor (changes live behavior → review first).
- Caching cadence + a refresh worker (the `/v1/stats` 1-call universe read makes a single periodic poll cheap).
- The other ~5 pay.sh providers (separate adapters, same pattern) — tracked under task #199.
- `methodology/current` as a citeable provenance string in the verdict envelope.
