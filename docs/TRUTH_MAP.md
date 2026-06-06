# Gecko — Truth Map

_The internal, test-backed inventory of **what actually works vs what doesn't.** A capability is `✅ live` **only** if a passing automated test proves it (Pattern E: "wired ≠ reaches"). `scripts/verify_truth_map.py` parses this file and fails if any `✅`/`🟢` row's test is missing or failing — so this map **cannot lie**._

Last verified: run `uv run python scripts/verify_truth_map.py --run`.

## Status legend
| Badge | Meaning | Bar |
|---|---|---|
| `✅ live` | Works, on `main`, automated test-backed | a referenced test passes |
| `🟢 pending` | Test-backed, in an open PR (not yet on main) | a referenced test passes |
| `🟡 partial` | Built but **not** automated-test-backed: paper/dry-run only, founder-gated real-money, or manually validated once | honest note required |
| `⬜ planned` | Not built | — |

> External user docs (Mintlify) are derived **only** from `✅ live` rows. We publish what's proven.

---

## Control plane API (`contest_bot/agent_api.py`)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| `GET /healthz` | ✅ live | `contest_bot/tests/test_e2e_app_surface.py` | |
| `GET /market-temp` | ✅ live | `contest_bot/tests/test_market_temp.py` `contest_bot/tests/test_e2e_app_surface.py` | risk-on/off read |
| `GET /vault` | ✅ live | `contest_bot/tests/test_vault_flow.py` `contest_bot/tests/test_e2e_app_surface.py` | |
| `GET /arena/board` | ✅ live | `contest_bot/tests/test_arena_score.py` `contest_bot/tests/test_e2e_app_surface.py` | bucketed, no raw floats |
| `POST /backtest` | ✅ live | `contest_bot/tests/test_agent_api.py` `contest_bot/tests/test_e2e_app_surface.py` | rigor verdict |
| `POST/GET /agents` (+ `/{id}`, start/stop/kill) | ✅ live | `contest_bot/tests/test_agent_api.py` `contest_bot/tests/test_e2e_app_surface.py` | |
| `GET /orchestrator` | ✅ live | `contest_bot/tests/test_e2e_app_surface.py` | |
| `POST/GET /kill` (global) | ✅ live | `contest_bot/tests/test_e2e_app_surface.py` | |
| `GET /wallet` · `/wallet/balance` · `/receipts` | ✅ live | `contest_bot/tests/test_wallet_receipts_endpoints.py` `contest_bot/tests/test_e2e_app_surface.py` | no-secret-leak asserted |
| Typed `response_model` on all endpoints (OpenAPI codegen) | ✅ live | `contest_bot/tests/test_agent_api_response_models.py` | app client codegen |

## Safety / verification (the wedge)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Pre-trade safety gate (`check_order` + notional/daily caps) | ✅ live | `contest_bot/tests/test_trade_safety.py` | |
| Global kill-switch covers Kamino + based.bid paths | ✅ live | `contest_bot/tests/test_basedbid_exec.py` `contest_bot/tests/test_live_executor.py` | |

## Execution adapters (build unsigned tx → gate → OKX TEE)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Jupiter swap adapter | ✅ live | `contest_bot/tests/test_trade_safety.py` | dry-run/gated; **real-money 🟡 gated** |
| based.bid lbp-buy/sell adapter | ✅ live | `contest_bot/tests/test_basedbid_exec.py` | devnet-testable; double-gated |
| Kamino live-executor (tx-build sidecar) | ✅ live | `contest_bot/tests/test_live_executor.py` `contest_bot/tests/test_kamino_sidecar.py` | dry-run; **real 🟡 gated** |
| Kamino paper sink | ✅ live | `contest_bot/tests/test_kamino_paper.py` | |
| **Real-money execution at scale** | 🟡 partial | — | OKX-TEE $10 Kamino round-trip validated once, manual; not automated; founder-gated |

## Profit vault
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Multiply economics (net_apy, liquidation buffer) | ✅ live | `contest_bot/tests/test_kamino_multiply.py` | |
| Yield-safety monitor (EXIT/DELEVERAGE/ROTATE/HOLD) | ✅ live | `contest_bot/tests/test_vault_flow.py` | hurdle + predicted-downside |
| Vault deposit gate (deny-default) | ✅ live | `contest_bot/tests/test_vault_flow.py` | |
| Profile baskets + orchestrator | ✅ live | `contest_bot/tests/test_vault_flow.py` | conservative/moderate/aggressive |
| Vault live-executor injection (paper) | ✅ live | `contest_bot/tests/test_vault_live_injection.py` | |
| **Pegana depeg-risk → monitor + gate** | ✅ live | `contest_bot/tests/test_pegana_feed.py` | compose independent oracles (PR #92, merged) |

## Arena (based.bid)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| Survival board (bucketed bands) | ✅ live | `contest_bot/tests/test_arena_score.py` | no public raw floats |
| based.bid candle feed (GeckoTerminal) | ✅ live | `contest_bot/tests/test_basedbid_feed.py` | post-graduation OHLCV |
| Read API over real based.bid tokens | ⬜ planned | — | needs based.bid discovery endpoints (Sprint 1) |

## Rigor harness (the credibility moat)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| CPCV / PBO / DSR / block-bootstrap gate | ✅ live | `scripts/calibration/test_acceptance_gate.py` | default-REJECT |
| Strategy validations (carry x-sectional, realistic, universe) | ✅ live | `scripts/calibration/test_carry_xsectional_validation.py` `scripts/calibration/test_carry_realistic_validation.py` | the nulls |

## Custody / distribution (honest gaps)
| Capability | Status | Proof | Notes |
|---|---|---|---|
| OKX Agentic Wallet TEE signing | 🟡 partial | — | validated manually ($10 mainnet); non-exportable; not automated here |
| Privy embedded server-wallet (S26) | 🟡 partial | — | built; no e2e test in this repo |
| Mintlify docs + llms.txt + skills manifest | 🟡 partial | — | shipped in `gecko-claude` (PR #15), external repo |
| Trustable + private autonomy (Cloak compose) | ⬜ planned | — | the positive-enabler bet |
