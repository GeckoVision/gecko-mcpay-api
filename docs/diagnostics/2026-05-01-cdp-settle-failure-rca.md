# CDP /settle "transfer amount exceeds balance" — RCA + Fix

**Date:** 2026-05-01
**Severity:** P0 — blocks all live CDP/Base settlements (Sprint 12 Track A/C, Sprint 12 Bazaar listing).
**Status:** Root cause identified. Minimal fix landed in this commit.

## Symptom

`CDPX402Client.charge()` against Base mainnet USDC fails with HTTP 500 from
the CDP facilitator `/v2/x402/settle` endpoint:

```
failed to send transaction: error (status 400): invalid_request:
ERC20: transfer amount exceeds balance
```

Every prior protocol-level signal looked clean:

| Signal | Status |
|---|---|
| Buyer (TWITSH) USDC balance on Base | 5.000000 USDC (50× the $0.10 charge) |
| CDP `/v2/x402/verify` response | `isValid: true, payer=0x7cc3...` (right signer recovered) |
| Treasury `payTo` resolution | correct (`0x0429...`, distinct from buyer) |
| `.well-known/x402` advertisement | correct price, network, payTo |
| Recent fixes wired | EIP-3009 buyer signing (`a13c65e`), ResourceInfo (`2e93b27`), EIP-712 domain in `extra` (`2ca40b9`), `payTo` env wiring (`cae61ed`) |

So the revert message was generic — emitted from the on-chain ERC20 layer
but **routed through the wrong contract path**.

## Diagnostic procedure

Spent zero USDC. Script: `scripts/diagnose_cdp_settle.py`. It rebuilds
the exact wire payload `CDPX402Client._build_payment_payload` produces,
then independently:

1. Confirms the on-chain USDC contract identity matches our EIP-712
   domain (`name="USD Coin"`, `version="2"`, decimals=6).
2. Reads buyer balance via `balanceOf` against Base public RPC.
3. Recovers the EIP-712 signer from the produced signature and asserts
   it equals `TWITSH_WALLET_ADDRESS` (no key-handling drift).
4. Checks `authorizationState(from, nonce)` to confirm the nonce isn't
   replayed.
5. **`eth_call`-simulates `transferWithAuthorization(...)` with the
   exact (from, to, value, validAfter, validBefore, nonce, v, r, s)
   we produce locally.** `eth_call` is free, runs the full contract
   logic, and surfaces the real revert string (vs the facilitator's
   generalized 500 body).

### Result

```
STEP 1 — Contract identity .................. OK (USD Coin / "2" / 6 decimals)
STEP 2 — Buyer balance ...................... 5,000,000 raw units (5 USDC)
STEP 3 — Build & sign authorization ......... value=100000, from=TWITSH, to=treasury
STEP 4 — Recover signer from signature ...... TWITSH (matches env)
STEP 5 — Authorization replay state ......... fresh nonce, not used
STEP 6 — eth_call simulation ................ SUCCESS, return=[]
```

The signed authorization that `CDPX402Client` builds executes
**successfully** on Base mainnet under direct simulation. The bug is
**not on chain**, it is in the dispatch path the CDP facilitator
selects when settling our payload.

## Root cause

Per the x402 spec at
[`specs/schemes/exact/scheme_exact_evm.md`](https://github.com/coinbase/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md),
`PaymentRequirements.extra` for the `exact` scheme on EVM **MUST** contain
`assetTransferMethod`. Allowed values are `"eip3009"` and `"permit2"`.

Our `_build_payment_requirements` was setting only:

```python
extra = {
    "name": "USD Coin",
    "version": "2",
    "verifyingContract": asset,
}
```

Missing `assetTransferMethod`. CDP's facilitator, faced with an
ambiguous `extra`, falls back to its **Permit2 dispatch path**. In that
path the facilitator calls `permit2.transferFrom(buyer → treasury)`,
which internally executes `usdc.transferFrom(buyer, permit2, value)` —
and that requires a *prior on-chain `approve()` from the buyer to the
Permit2 contract*. TWITSH has never approved Permit2, so the inner
`transferFrom` reverts with the standard ERC-20 message:

> `ERC20: transfer amount exceeds balance`

(More precisely: "transfer from balance" of the Permit2 allowance, which
is zero — but the FiatTokenV2 `_transfer` doesn't distinguish between
"balance" and "allowance-derived available balance" in its revert
string.)

This explains why **verify passes but settle fails**: verify is a pure
signature/state check that doesn't care which transfer mechanism the
facilitator will eventually use. Settle is where the path branch
matters, and our missing field forced the wrong branch.

## The fix

Single-line change in
`packages/gecko-core/src/gecko_core/payments/cdp_x402_client.py`:

```diff
 extra = {
     "name": "USD Coin",
     "version": "2",
     "verifyingContract": asset,
+    "assetTransferMethod": "eip3009",
 }
```

Now the facilitator dispatches directly to `usdc.transferWithAuthorization(...)`
using the buyer's signed EIP-3009 authorization — no allowance needed,
no Permit2 hop. This matches the path that succeeds under our local
`eth_call` simulation.

### Why this didn't break the buyer-side signing

Upstream `ExactEvmScheme.create_payment_payload` only branches into the
Permit2 *signing* path when `extra.assetTransferMethod == "permit2"`.
Any other value (including `"eip3009"`) routes through the EIP-3009
signing branch, which is what we want and what was already working.
Verified: re-running `scripts/diagnose_cdp_settle.py` after the fix
still yields a valid signature, recovers TWITSH, and simulates
successfully via `eth_call`.

## Pre-flight before re-attempting live settle

Run, in order:

1. `uv run python scripts/diagnose_cdp_settle.py` — should print all
   six STEPs with no `!!` warnings and STEP 6 = SUCCESS.
2. `uv run pytest tests/payments/` — full suite green.
3. One real settle on Base mainnet for `$0.10`. If this succeeds the
   tx hash returns; if it still fails, the next suspect is the
   `max_timeout_seconds=60` validity window (currently `validAfter =
   now-600s`, `validBefore = now+60s` due to the SDK's 600s clock-skew
   buffer plus our short `max_timeout_seconds`). Bump to 300+ if so.

## Latent issues spotted during this RCA (filed for follow-up, NOT in this commit)

1. **Validity window too short.** `max_timeout_seconds=60` produces a
   60-second forward window. CDP's settle round-trip + Base block time
   can eat that. Recommend defaulting to `300` (5 min) like
   publish.new and the dev.to writeups suggest.

2. **Well-known x402 advertisement omits `extra` entirely.** Our
   server's 402 challenge advertises `price=$0.10`, `network`, `payTo`
   but no `extra`. Buyers using a strict client implementation may not
   know the on-chain `name`/`version`/`assetTransferMethod` and will
   build the same broken `extra` we just fixed in our own client. The
   server should advertise the full `extra` shape so cross-vendor
   buyers don't repeat this bug.

3. **`pay_to` checksum.** We currently send `pay_to` exactly as set in
   `GECKO_WALLET_ADDRESS_BASE` env (lowercased). Some EIP-712 strict
   facilitators reject non-checksummed `to` addresses inside the signed
   message. Worth normalizing through `eth_utils.to_checksum_address`
   at requirements-build time.

## References

- Diagnostic script: `scripts/diagnose_cdp_settle.py`
- Spec source: <https://github.com/coinbase/x402/blob/main/specs/schemes/exact/scheme_exact_evm.md>
- Related upstream issue: <https://github.com/coinbase/x402/issues/1065> (intermittent settle gas-estimation; symptomatically adjacent)
- Sprint 12 Track A history: commits `4842a3b`, `a13c65e`, `2e93b27`, `2ca40b9`, `cae61ed`
- This dispatch: web3-engineer P0 trace dated 2026-05-01
