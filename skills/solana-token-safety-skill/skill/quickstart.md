# Quickstart — one safety check

The whole skill in one call. Free, keyless, sub-second.

## The call

```bash
curl -s -X POST https://api.geckovision.tech/safety \
  -H "Content-Type: application/json" \
  -d '{"mint": "<SPL_MINT_ADDRESS>"}'
```

`mint` is the base58 SPL mint address (32–44 chars). No API key, no auth.

## The response

```jsonc
{
  "gate": "block",                 // block | caution | ok | unknown  <- read this first
  "checked": true,                 // did the check actually run?
  "honeypot": false,
  "mint_mutable": false,           // mint authority NOT renounced?
  "freeze_mutable": false,         // freeze authority NOT renounced?
  "top_holder_pct": 0.72,          // largest holder's share of supply (0..1)
  "market_cap_usd": 5730000.0,
  "liquidity_usd": 6500.0,
  "liquidity_to_mcap_pct": 0.11,   // LOW = the price is unsupportable
  "rug_flags": ["fake_market_cap", "thin_liquidity_vs_mcap", "high_holder_concentration"],
  "information_mev": {             // the manipulation-severity read
    "score": 0.95,
    "label": "manipulated",        // clean | elevated | manipulated
    "reasons": ["fake market cap: $5.73M mcap on $6.5K liquidity (0.11%)", "..."]
  },
  "source": "quicknode+coingecko"
}
```

> The flow-manipulation block (`wash_risk`: one-sided buy-loops, multi-pool price
> bait, wash recirculation) is added as the Launch-Firewall stream rolls out;
> when present it has the same `{score, label, reasons}` shape and can raise the
> `gate` on its own. Until then, rely on `gate` + `information_mev` + `rug_flags`.

## The 5-second decision

```
gate == "block"   -> do NOT trade / do NOT list. Show reasons[] to the user.
gate == "caution" -> reduced size + explicit confirm only.
gate == "ok"      -> checked and clean (not financial advice).
gate == "unknown" -> the check could not run — degrade safely, never assume safe.
```

## Minimal clients

**Python**
```python
import httpx

def safety(mint: str) -> dict:
    r = httpx.post("https://api.geckovision.tech/safety", json={"mint": mint}, timeout=10)
    r.raise_for_status()
    return r.json()

v = safety("So11111111111111111111111111111111111111112")
if v["gate"] == "block":
    raise SystemExit(f"blocked: {v.get('information_mev', {}).get('reasons')}")
```

**TypeScript**
```ts
async function safety(mint: string) {
  const r = await fetch("https://api.geckovision.tech/safety", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mint }),
  });
  return r.json();
}
```

Next: [signals.md](signals.md) for what each flag means · [interpreting-verdicts.md](interpreting-verdicts.md) to act on it.
