---
description: Check whether a Solana token's LAUNCH is real or being botted — issuer/launchpad Block-Zero read. Usage: /launch-check <mint>
---

# /launch-check

Issuer-side safety read: is this token's launch authentic, or is it being
manipulated by bots in the first candles? Same oracle as `/safety-check`, framed
for a founder / launchpad rather than a trader.

**Argument:** a base58 SPL mint address.

## Steps

1. Take the mint from the argument; ask if missing.
2. Call the oracle (`gecko_safety` MCP tool if connected, else
   `POST https://api.geckovision.tech/safety` with `{"mint": "<mint>"}`).
3. Summarize for an **issuer**:
   - `block` + fired wash/bot signals → "your launch is being manipulated" — name
     the pattern (bot buy-loop / wash / sybil cluster / price bait) and advise
     action (investigate the buyer cluster, warn the community).
   - `block` with only static signals (fake mcap) → the token's market is air.
   - `caution` on a `< 1h`-old token → likely just early thinness, not a scam;
     advise re-checking as liquidity builds (see launch-check.md timing caveat).
   - `ok` → looks clean so far; recommend periodic re-checks during the launch.
4. Always surface `liquidity_to_mcap_pct`, `top_holder_pct`, and the `reasons[]`.
5. Remind the user this is a **live read** — re-run on a cadence through the
   launch, not once.

## Notes
- Free, keyless, fail-OPEN. `unknown` ≠ safe.
- Reads market integrity (is the volume/price real), not contract bytecode. For a
  full contract audit, use a dedicated auditor skill.
