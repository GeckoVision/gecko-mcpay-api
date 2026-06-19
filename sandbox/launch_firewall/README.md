# Launch Firewall — Attack vs Defense sandbox

Free, mainnet-spend-free proving ground for the Launch Firewall. Replays scripted
manipulation attacks through the **real** detection engine
(`gecko_core.trade_agent.hotpath`) and shows the verdict it would serve.

Per the architecture synthesis
(`private/strategy/2026-06-18-launch-firewall-architecture-synthesis.md`):
the Defense is already our shipped engine — the only genuinely new build is the
Attack. The sandbox is where we falsify the firewall before any live wire.

## Layout

| File | What |
|---|---|
| `scenarios.py` | Pure fixture generators (BrCA inflate-then-drain, organic fair launch). Reused by the real-validator path. |
| `defense_harness.py` | Fixture-fed demo — replays scenarios through the real `LaunchMonitor` + `HotpathCache`, prints the served verdict. **Step 3.** |
| `validator.sh` *(step 6)* | Spin `solana-test-validator` + a mock pool — the live-fidelity path. |
| `attack_bot.py` *(step 7)* | On-chain wash/MEV bot that drives a scenario against the mock pool. |
| `latency_harness.py` *(step 5)* | Measures warm-serve / cold-serve / detection latency. |

## Run the fixture demo

```bash
uv run python sandbox/launch_firewall/defense_harness.py
```

Expected: the BrCA attack is **blocked** (wash `manipulated`, signals
`thin_pool_buy_loop` + `multi_pool_price_bait`); the organic launch is **not**.

The CI gate for this is
`packages/gecko-core/tests/trade_agent/hotpath/test_launch_monitor.py`
(`test_brca_attack_reaches_cache_as_block`) — the harness is the human-facing
demo of the same path.

## Honesty guardrails

- The claim is **"detect-and-veto within N events of the pattern forming,"** not
  "block the tx in-block." The sandbox measures *detection* (events → gate flip).
- The gate is **fail-OPEN**: `unknown` is never reported as safe.
- Local simulation first (Pattern B); live mainnet smoke is the final check, never
  the debug tool.
