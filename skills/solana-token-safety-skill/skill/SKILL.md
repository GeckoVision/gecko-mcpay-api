---
name: solana-token-safety
description: Pre-trade / pre-launch token safety for Solana agents and builders. Detects manipulation a contract check misses — bot/wash-traded volume, fake market cap, multi-pool price bait, single-wallet float — and returns a one-glance gate (block / caution / ok / unknown) with reasons. Calls the free Gecko /safety oracle over HTTP (no key) or the gecko_safety MCP tool. Use before an agent buys a token, before a router whitelists a market, or when a builder vets a fresh launch. NOT a contract rug-checker (those exist); this is the market-data-integrity layer they miss.
user-invocable: true
---

# Solana Token Safety Skill

> A second opinion on **whether a token's market is real** before you act on it.
> Contract checkers (RugCheck, GoPlus, Solsniffer) tell you the *contract* is
> fine. They pass tokens whose **price and volume are manufactured** by bots.
> This skill catches that — the layer that flagged BrCA as `block / manipulated`
> while the platform rated it "Normal".

## What This Skill Is For

Use this skill when the user (or an autonomous agent) needs to know **"is this
token's market trustworthy before I touch it?"** — specifically:

### Agent pre-trade gate
- An autonomous trading agent about to **buy/swap a Solana token** — check it first.
- "Should I ape this?" / "is this token safe to trade right now?"
- A router/aggregator deciding whether to **whitelist a new market**.

### Builder / issuer launch check
- A founder vetting their own **fresh launch** for bot manipulation (Block Zero).
- "Is the volume on my token real, or is it being wash-traded?"
- Pre-listing diligence on a token you didn't deploy.

### What it detects that a contract check does NOT
- **Fake market cap** — a large quoted mcap backed by tiny liquidity (the price
  is unsupportable; e.g. $26M mcap on $22K liquidity = 0.085%).
- **Wash / bot-inflated volume** — one-sided buy loops, recirculation, no real
  price discovery.
- **Multi-pool price bait** — the token quoted far above its liquidity-weighted
  index price in thin, dead satellite pools.
- **Single-wallet float** — one holder controls enough supply to dump the chart.

> This is the **Information-MEV / market-data-integrity** plane. For *contract*
> rug risk (mint/freeze authority, honeypot bytecode), use a dedicated auditor
> skill — this skill reports those signals too when the oracle returns them, but
> its edge is the manipulation a static contract scan can't see.

## How to use it (routing)

Pick the path that fits the situation; load only the file you need
(progressive, token-efficient):

| You want to… | Read |
|---|---|
| Make a single check fast (the one call) | [quickstart.md](quickstart.md) |
| Understand each flag/signal it returns | [signals.md](signals.md) |
| Act on the verdict (gate semantics, fail-OPEN) | [interpreting-verdicts.md](interpreting-verdicts.md) |
| Wire it into an agent's pre-trade loop (MCP + HTTP) | [agent-integration.md](agent-integration.md) |

There is also a ready command: [`/safety-check <mint>`](../commands/safety-check.md).

## The one thing to remember

The check is **free**, **keyless**, and **fail-OPEN**: `POST` a mint, get a
`gate`. Never treat `unknown` as safe — it means the check could not run, not
that the token is clean. Decision rule:

```
gate == "block"   -> do NOT trade / do NOT list. Surface the reasons.
gate == "caution" -> trade only with reduced size + explicit user confirm.
gate == "ok"      -> checked and clean (still not financial advice).
gate == "unknown" -> the oracle couldn't read it; degrade safely, don't assume safe.
```

## Provider

Powered by **Gecko** (geckovision.tech) — a decision-integrity oracle for Solana
agents. The `/safety` tier is free and unauthenticated by design (it's the
funnel + the public good); the considered multi-voice adjudication lives behind
the paid `/trade_research` tier. This skill only uses the free tier.

- HTTP: `POST https://api.geckovision.tech/safety`
- MCP: the `gecko_safety` tool (when the Gecko MCP server is connected)
- Docs: https://docs.geckovision.tech
