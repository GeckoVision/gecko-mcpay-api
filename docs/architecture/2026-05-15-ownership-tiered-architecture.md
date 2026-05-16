# GeckoVision — Ownership-Tiered Architecture

**Date:** 2026-05-15
**Purpose:** Redraw of the 8-layer architecture so it reads as *one focused
product with good partners* — not a Swiss-army-knife.

## The problem with the original diagram

The original `geckovision_complete_architecture.png` used **one visual language
for two different things**: layers Gecko builds, and layers Gecko integrates.
That is what makes a focused product look like a do-everything tool.

A Swiss-army-knife is defined by what you *build*, not what the user *gets*.
The iPhone delivers a "complete pack" and integrates components it doesn't
forge. The fix here is not cutting layers — it is **encoding ownership**.

## The three tiers

| Tier | Line style | What it means | Revenue |
|------|-----------|---------------|---------|
| **1 — Gecko builds & operates** | `═══` double | The oracle. The actual product. | per-call x402 |
| **2 — Gecko's proof agent** | `───` single | Flagship demo / living case study. | $0 — marketing |
| **3 — Integrated partners** | `┄┄┄` dashed | Named, not built. Trust signals. | n/a |

## The diagram

```
╔══════════════════════════════════════════════════════════════════╗
║  TIER 1 — GECKO BUILDS & OPERATES        ← this is the product     ║
║                                            (metered: x402/call)   ║
║  ┌─────────────────────────┐  ┌─────────────────────────────┐     ║
║  │   [ KNOWLEDGE BASE ]    │  │    [ REAL-TIME DATA ]       │     ║
║  │  - MongoDB + Voyage     │  │  - Pyth (prices)            │     ║
║  │    (voyage-finance-2)   │  │  - DeFiLlama (yields)       │     ║
║  │  - Investor canon       │  │  - Protocol-native APIs     │     ║
║  │  - Protocol docs        │  │    (Kamino, Jupiter, …)     │     ║
║  └────────────┬────────────┘  └──────────────┬──────────────┘     ║
║               └───────────────┬──────────────┘                    ║
║                                ▼                                  ║
║  ╔══════════════════════════════════════════════════════════╗     ║
║  ║  [ TRADE RESEARCH ORACLE ]  — the 7-voice panel           ║     ║
║  ║  - Retrieves cited chunks (canon + live on-chain)         ║     ║
║  ║  - Adversarial debate → surviving dissent                 ║     ║
║  ║  - Verdict envelope: SAFE / DEFER / REJECT + citations    ║     ║
║  ╚════════════════════════════┬═════════════════════════════╝     ║
║                                ▼                                  ║
║  ╔══════════════════════════════════════════════════════════╗     ║
║  ║  [ AUDIT TRAIL + TRUST MODEL ]                            ║     ║
║  ║  - Every verdict logged with citations + timestamps       ║     ║
║  ║  - Every DEFER explained (blocker question surfaced)      ║     ║
║  ╚════════════════════════════┬═════════════════════════════╝     ║
╚════════════════════════════════│══════════════════════════════════╝
                                  │  verdict envelope (consumed, not sold)
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  TIER 2 — GECKO'S PROOF AGENT            ← flagship demo, $0 revenue │
│                                            "show, don't tell"       │
│  ┌──────────────────────────────────────────────────────────┐       │
│  │  [ TRADE EXECUTOR AGENT ]                                 │       │
│  │  - Consumes the oracle verdict (never reads corpus direct)│       │
│  │  - Short-term memory (session PnL) + long-term (limits)   │       │
│  │  - Ephemeral wallet — user custody only                   │       │
│  └────────────────────────────┬─────────────────────────────┘       │
│        ┌──────────────────────┴───────────────────────┐             │
│        ▼                                              ▼             │
│  ┌───────────────────────────┐   ┌────────────────────────────┐     │
│  │ [ PUBLIC KAMINO VAULT ]   │   │  [ BACKTESTING ]           │     │
│  │ - Public address = proof  │   │  - Validates the oracle's  │     │
│  │ - Verifiable PnL curve    │   │    verdicts vs. history    │     │
│  │ - "proof of concept"      │   │  - their agent vs. ours    │     │
│  └───────────────────────────┘   └────────────────────────────┘     │
│                                                                      │
│  This tier is a permanent CASE STUDY. It is never a separate SKU.    │
│  The day it gets a price tag, the company has split focus.           │
└──────────────────────────────────┬───────────────────────────────────┘
                                    │  wired in when the proof agent
                                    │  goes from demo → real capital
                                    ▼
┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
┊  TIER 3 — INTEGRATED PARTNERS       ← named, NOT built. Trust signal ┊
┊                                                                      ┊
┊  ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐ ┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐  ┊
┊  ┊ AgentDog          ┊ ┊ Cloak.ag          ┊ ┊ Backtrader / ext ┊  ┊
┊  ┊ [via partner]     ┊ ┊ [via partner]     ┊ ┊ [via partner]    ┊  ┊
┊  ┊ - trajectory mon. ┊ ┊ - shielded UTXO   ┊ ┊ - backtest engine┊  ┊
┊  ┊ - prompt-inject   ┊ ┊ - anti-front-run  ┊ ┊ - open source    ┊  ┊
┊  ┊ - honeypot tests  ┊ ┊ - viewing keys    ┊ ┊                  ┊  ┊
┊  └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘ └┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘  ┊
┊                                                                      ┊
┊  Dashed = future integration. Choosing a serious partner IS the       ┊
┊  proof that Gecko cares about security/privacy. Building a half-baked ┊
┊  version in-house would be the actual scope creep.                    ┊
└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘
```

## How to read it in 10 seconds

> Gecko **builds** a grounded trade-verdict oracle (Tier 1). It **proves** the
> oracle works by running a public agent with a verifiable track record
> (Tier 2). It **integrates** best-in-class partners for security, privacy,
> and backtesting (Tier 3) — it does not build those.

One product. One meter. A visible proof. Named partners. Not a knife.

## Decisions encoded here

1. **The oracle is the only thing sold.** Per-call x402. Tier 2 and Tier 3
   never carry a price tag.
2. **The proof agent is marketing, scoped to a track record.** Any agent
   feature that does not make the public PnL more legible is scope creep.
3. **Partner layers stay empty until the partner is wired.** No placeholder
   security/privacy/backtest layers built in-house "until the integration is
   ready." The box shows the partner name or nothing.
4. **The proof agent calls the oracle** — it never reads the corpus directly
   (consistent with the coach → oracle → execution rule in CLAUDE.md).

## Open question for the designer

Tier 2's backtesting box overlaps conceptually with Tier 3's Backtrader
partner box. Resolution: Tier 2 "Backtesting" is the *use case* (validate our
verdicts); Tier 3 "Backtrader" is the *engine* that powers it. Consider
drawing a thin connector between them rather than two separate boxes.
