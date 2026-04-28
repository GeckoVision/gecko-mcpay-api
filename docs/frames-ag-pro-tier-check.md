# frames.ag $0.75 Pro-tier confirm-flow check (D2)

Owner: web3-engineer · Date: 2026-04-27

## Findings

**Per-tx cap (frames.ag side):** Unknown / not publicly documented. `frames.ag/skill.md` lists `POLICY_DENIED (403)` as "Policy check failed (amount too high, etc.)" but does not state a default ceiling. The cap is policy-controlled per-wallet via `PATCH /wallets/{username}/policy { max_per_tx_usd }`.

**Per-tx cap (gecko-mcp side — REAL FRICTION):** Yes. `packages/gecko-mcp/src/gecko_mcp/api_client.py:49` sets `DEFAULT_MAX_PAYMENT_USD = "0.50"`. This is sent as `maxPayment` in every `/x402/fetch` body (`wallet.py:387`). At $0.75, frames.ag will refuse the payment with `POLICY_DENIED` (or our `maxPayment` check will short-circuit before the proxy even tries). Override is `GECKO_MAX_PAYMENT=0.80` env or `GeckoAPIClient(max_payment_usd=...)`.

**Rate limit:** Unknown — `frames.ag/skill.md` does not document a 429 surface for `/x402/fetch`. The only rate limit mentioned is the Solana devnet faucet (3 req / 24h). No mention of per-hour or per-day x402 caps. Demo flow of 3-5 Pro sessions in 10 min is *probably* safe but unverified — escalate to frames.ag team if observed.

**Confirmation UI threshold:** None documented. `skill.md` says "human confirmation required" generally for write ops but lists no dollar-amount threshold. The user shouldn't need to do anything different at $0.75 vs $0.10 in the UI flow itself.

## Recommended follow-up (do NOT implement in this turn)

1. **Bump `DEFAULT_MAX_PAYMENT_USD` to `"1.00"`** in `gecko-mcp/api_client.py` so Pro-tier ($0.75) clears the client-side cap with headroom for future small price moves. One-line change — staff-engineer should sequence with the Pro tier ship. Without this, `/research/pro` calls fail before they even hit frames.ag.
2. **Surface a `gecko-mcp wallet policy --show` hint** in `skill.md` so users with restrictive personal policies (`max_per_tx_usd < 0.75`) get a clear pointer before their first Pro call.
3. **Smoke test 5 Pro calls in 10 min** on devnet before the demo, watching for any 429 from frames.ag's gateway. If observed, file with frames.ag + add SSE-poll fallback to `gecko-mcp`.

## Sources

- `packages/gecko-mcp/src/gecko_mcp/api_client.py:24-27,49` — local cap doc + constant
- `packages/gecko-mcp/src/gecko_mcp/wallet.py:386-387` — `maxPayment` send-site
- `frames.ag/skill.md` (fetched 2026-04-27) — error codes, policy field, no published rate limit / threshold
