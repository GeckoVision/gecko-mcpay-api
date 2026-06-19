# solana-token-safety-skill

**A second opinion on whether a Solana token's *market* is real — before an agent
trades it or a builder lists it.**

Built for the [Solana AI Kit](https://github.com/solanabr). A progressive,
token-efficient skill that gives any coding/trading agent a one-call pre-trade
safety gate.

## The problem it solves

Every contract checker on Solana (RugCheck, GoPlus, Solsniffer, Bubblemaps) tells
you whether the **contract** is safe — mint/freeze authority, honeypot bytecode.
They routinely **pass tokens whose price and volume are manufactured**: bot-
inflated wash volume, a fake market cap held up by a few thousand dollars of
liquidity, the same token quoted far above its real price in thin satellite
pools, one wallet sitting on the float.

That's the gap that drains agents and rugs retail. A static contract scan can't
see it, because the manipulation is in the **market data**, not the contract.

This skill is that missing layer. It flagged a live token (BrCA) as
`block / manipulated 0.95` — $5.73M quoted market cap on **$6.5K** of liquidity,
top holder 72% — while the platform it traded on rated it "Normal".

## What it does

One call → a one-glance gate:

```
block    — do not trade / do not list (fake mcap, manipulated/wash, depeg, honeypot)
caution  — reduced size + explicit confirm (thin liquidity, concentration, elevated)
ok       — checked and clean
unknown  — the check could not run (fail-OPEN — never assume safe)
```

…plus the `reasons[]` to explain the verdict to a human, and (as the Launch-
Firewall stream rolls out) a `wash_risk` block with the specific flow signal that
fired (one-sided buy-loop, multi-pool price bait, wash recirculation, sybil
funder cluster).

It's **free, keyless, and fail-OPEN** — `POST` a mint, get a gate.

## Install

```bash
git clone <this-repo> && cd solana-token-safety-skill
bash install.sh          # copies the skill + /safety-check command into ~/.claude
```

Or point it at a custom config dir: `CLAUDE_DIR=/path bash install.sh`.

## Use

- Ask your agent: *"is this token safe to trade: `<mint>`?"*
- Run the command: `/safety-check <mint>`
- Wire it into an agent's pre-trade loop → [`skill/agent-integration.md`](skill/agent-integration.md)

## Structure

```
skill/
  SKILL.md                 entry point + routing (load this)
  quickstart.md            the one call (curl / Python / TS)
  signals.md               what each flag/signal means
  interpreting-verdicts.md gate semantics + fail-OPEN + FP awareness
  agent-integration.md     MCP + HTTP pre-trade gate pattern
commands/
  safety-check.md          /safety-check <mint>
install.sh                 copy-only installer (no binaries, no network)
LICENSE                    MIT
```

## How it works

The skill is a thin, safe client over **Gecko's free `/safety` oracle**
(`POST https://api.geckovision.tech/safety`) or the `gecko_safety` MCP tool. The
oracle reads on-chain liquidity/holder/market data, computes deterministic
manipulation signals, and returns the gate. The skill ships **no executable
logic of its own** beyond the install copy — nothing opaque, nothing to audit
beyond markdown.

- Docs: https://docs.geckovision.tech
- Provider: [Gecko](https://geckovision.tech) — a decision-integrity oracle for
  Solana agents. The `/safety` tier is free by design; the considered multi-voice
  adjudication lives behind the paid `/trade_research` tier (not used by this skill).

## License

MIT — ready to be merged or submoduled into the kit.
