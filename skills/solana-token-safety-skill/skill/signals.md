# Signals — what each flag means

The check returns three families of signal. You rarely need all of them — read
`gate` first, then drill into whichever block explains it.

## 1. `rug_flags[]` — explicit string markers

| flag | meaning | severity |
|---|---|---|
| `fake_market_cap` | quoted market cap is unsupportable by on-chain liquidity (liq/mcap < ~0.2%) | **block** |
| `thin_liquidity_vs_mcap` | liquidity thin relative to mcap (< ~1%) — price moves on tiny volume | caution |
| `high_holder_concentration` | one wallet holds ≥ ~35% of supply — dump risk | caution |
| `mint_not_renounced` | mint authority live — dev can dilute supply | caution |
| `freeze_not_renounced` | freeze authority live — dev can freeze your position | caution |
| `depeg_risk` | a peg asset (LST/stable) is materially off peg | **block** |
| `safety_check_unavailable` / `not_a_token_mint` / `invalid_mint` | the check could not run | → `unknown` |

Absolute-size guard (built into the oracle, good to know): the liq/mcap *ratio*
alone false-positives on large caps whose real depth is on CEXes. The oracle
only flags thin float when liquidity is **also** small in absolute terms (below
a ~$500K on-chain floor), so blue-chips with deep CEX books don't trip it.

## 2. `information_mev` — manipulation severity of the *visible signal*

A single 0–1 `score` + a `label` + human-readable `reasons[]`. This is the
"is the price/mcap being manufactured" read, derived from the liquidity/mcap
ratio + holder concentration.

| label | score band | what it says |
|---|---|---|
| `clean` | low | the visible market signal looks real |
| `elevated` | mid | manipulable — thin float / concentration; size down |
| `manipulated` | high | the price/mcap is effectively fake — do not act on it |

`information_mev.label == "manipulated"` forces `gate == "block"` on its own.

## 3. `wash_risk` — flow-manipulation read (Launch-Firewall, rolling out)

Severity of bot/wash activity in the token's *trade flow* (vs the static
snapshot above). Same `{score, label, reasons, fired_signals}` shape. Present
once the streaming firewall is live for a token; absent otherwise (don't depend
on it being there yet). `fired_signals[]` carries machine codes:

| code | pattern |
|---|---|
| `thin_pool_buy_loop` | one-sided buys on tiny uniform size while price climbs (the classic bot pump) |
| `multi_pool_price_bait` | token quoted far above its liquidity-weighted index price in thin, dead satellite pools |
| `wash_self_trade` | a wallet trading both sides in balance with no net fresh capital — recirculation |
| `common_funder_sybil` | the "many buyers" were funded by a few fresh wallets just before launch |

A `manipulated` `wash_risk` also forces `gate == "block"`; `elevated` raises at
least `caution`.

## Reading them together

The `gate` already fuses all three (see [interpreting-verdicts.md](interpreting-verdicts.md)).
Use the individual blocks to **explain** the gate to a user — always surface the
`reasons[]`, because a "no" with no reason gets disabled within a week.
