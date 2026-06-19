---
description: Gate every Solana token swap with a safety check first; never treat unknown as safe.
alwaysApply: false
---

# Rule: gate token swaps with safety

When an agent (or the user, via an agent) is about to **buy / swap into a Solana
SPL token it has not already cleared**, run a safety check BEFORE building or
signing the transaction.

1. Call the safety oracle for the target mint (`gecko_safety` MCP tool, else
   `POST https://api.geckovision.tech/safety`). Bound it (~8s); fail-OPEN.
2. Apply the gate:
   - `block` → **do not proceed.** Tell the user why (the `reasons[]`).
   - `caution` → proceed only with reduced size **and** explicit user confirmation.
   - `ok` → proceed (still not financial advice).
   - `unknown` → the check could not run; **do not assume safe** — abstain or ask.
3. Cache the verdict per mint (~30s) so a high-frequency loop stays cheap; re-check
   on a TTL, never whitelist a mint forever on one `ok`.

Applies to buy/swap-in on tokens the agent hasn't vetted this session. It does
NOT block selling/exiting an existing position (you must always be able to get
out). Skip for the native SOL ↔ major-stable legs.

This is a **pre-trade gate**, not a contract audit — it checks whether the
token's market is real, not the contract bytecode.
