# Interpreting verdicts — act on the gate

The `gate` is the one field you must act on. It fuses the contract read, the
Information-MEV read, and (when present) the wash read into one recommendation.

## The truth table

| `gate` | what it means | what the agent should do |
|---|---|---|
| `block` | honeypot, fake market cap, material depeg, or a `manipulated` manipulation/wash read | **Refuse.** Do not trade / do not list. Surface `reasons[]`. |
| `caution` | elevated manipulation, thin liquidity, holder concentration, or un-renounced authority | Proceed only with **reduced size + explicit user confirmation**. Quote the reason. |
| `ok` | checked and clean | Allowed to proceed. Still not financial advice. |
| `unknown` | the check could not run (not a mint, source down, error) | **Degrade safely.** Never treat as clean. Prefer to abstain or ask the user. |

## The one rule that matters: fail-OPEN ≠ safe

`unknown` is **fail-OPEN** — the system answers instead of crashing, but it is
explicitly *not* a clean bill of health. Treating `unknown` as `ok` is the
single most dangerous misread. If your agent can't get a real `ok`/`block`,
default to caution or abstain.

## Surface the reason, every time

A block with no explanation gets disabled by the user within a week. Whenever
you act on `block`/`caution`, show the human the `reasons[]` from
`information_mev` / `wash_risk` / the `rug_flags`. Example user-facing line:

> ⚠️ Blocked **$XYZ** — fake market cap: $5.73M cap on $6.5K liquidity (0.11%),
> top holder owns 72%. The price isn't supportable by real liquidity.

## False-positive awareness (don't over-block)

- **Large caps with CEX liquidity**: the oracle's absolute-liquidity floor
  prevents flagging blue-chips whose depth is off-chain. If you see a `caution`
  on a major with deep CEX books, weight it lightly.
- **Brand-new fair launches** are *naturally* thin and concentrated in the first
  minutes. The firewall's launch guard avoids escalating a lone static signal to
  `block` at launch; if you're checking a < 1h-old token, expect `caution` more
  than `block` unless flow signals corroborate.

## Composition with other skills

This skill answers **"is the market real?"** It is complementary to:
- a **contract auditor** skill (mint/freeze/honeypot bytecode, formal analysis),
- a **tx-preflight** skill (does this specific transaction drain me?).

Run safety first as a cheap gate; escalate to a full audit only when something is
worth the deeper look.
