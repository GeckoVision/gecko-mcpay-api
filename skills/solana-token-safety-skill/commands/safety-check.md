---
description: Check a Solana token's market safety before trading or listing it — returns a block/caution/ok gate with reasons. Usage: /safety-check <mint>
---

# /safety-check

Run a pre-trade / pre-launch safety check on a Solana SPL token.

**Argument:** a base58 SPL mint address.

## Steps

1. Take the mint from the user's argument. If none was given, ask for it.
2. Call the Gecko safety oracle (prefer the `gecko_safety` MCP tool if connected;
   otherwise `POST https://api.geckovision.tech/safety` with `{"mint": "<mint>"}`).
3. Read `gate` first, then summarize for the user:
   - `block` → ❌ state clearly NOT to trade/list, and quote the top `reasons[]`.
   - `caution` → ⚠️ allow only with reduced size + explicit confirmation; quote the reason.
   - `ok` → ✅ checked and clean (add: not financial advice).
   - `unknown` → ❓ the check couldn't run — do NOT assume safe; suggest re-trying or abstaining.
4. Always surface the human-readable `reasons[]` (from `information_mev` /
   `wash_risk` / `rug_flags`). A verdict with no reason is useless.
5. If the user asked in the context of an automated agent, point them at
   `skill/agent-integration.md` for the pre-trade gate pattern.

## Notes
- Free, keyless, fail-OPEN. Never treat `unknown` as `ok`.
- This checks **market-data integrity** (is the price/volume real). For contract
  bytecode rug risk or a full audit, use a dedicated auditor skill.
