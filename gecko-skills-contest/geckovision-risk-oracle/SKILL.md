---
name: geckovision-risk-oracle
description: A grounded, adversarial risk oracle that prevents AI trading agents from hallucinating or executing unsafe trades. Runs a three-lens debate (market structure, security, portfolio memory) and returns SAFE / DEFER / REJECT with surviving dissent and citations — never a black box, never a fabricated "looks fine."
version: 2.0.0
author: GeckoVision
tags: [risk-management, security, trading-bot, onchainos, solana, ethereum, guardrails, defi, agentic-trading, safety]
triggers:
  - "Is this safe to trade?"
  - "Check risk for [token]"
  - "Should I buy [token]?"
  - "Analyze risk before swapping"
  - "GeckoVision risk check"
  - "Risk assessment for [token]"
  - "Is [token] safe?"
  - "Is [position] stalling?"
  - "Should I rotate out of [token]?"
  - "Manage my open positions"
dependencies:
  - okx-dex-token
  - okx-dex-market
  - okx-wallet-portfolio
  - okx-security
---

# GeckoVision Risk Oracle

> The safety layer for agentic trading. Before any swap executes, three
> independent lenses debate the trade and a deterministic coordinator
> returns **SAFE / DEFER / REJECT** — grounded in live on-chain data and
> investor-canon principles, with surviving dissent shown, never hidden.

## Why this exists

Trading agents are probabilistic; money is deterministic. When an LLM
agent hallucinates conviction — recommends a rug, ignores portfolio
concentration, or rounds "I'm not sure" up to "looks good" — real capital
is lost. Every other trading skill is an *accelerator* ("buy the dip",
"copy this wallet", "snipe new tokens"). **This is the brake.** It is the
one skill that makes all the others safe to run unattended.

**The core principle: abstain, do not fabricate.** When evidence is thin,
the oracle returns DEFER or REJECT — it never invents a green light. This
discipline is not theoretical: GeckoVision's own trading agent ran live on
the OKX Agentic Trading Contest and declined dozens of low-conviction
candidates in a row rather than force a trade, while the trades it *did*
take closed positive. The brake is the product.

## What makes this different

Most "risk check" skills are a single threshold table: liquidity < X →
reject. That is table stakes — anyone can write it, and a single lens is
exactly how agents get fooled (a token can have deep liquidity *and* be a
honeypot). GeckoVision runs an **adversarial panel**: three lenses analyze
the same trade independently, are allowed to disagree, and a fixed
coordinator rule — not a vibe — turns their dissent into a verdict.

| Generic risk skill | GeckoVision Risk Oracle |
|---|---|
| One threshold table | **Three adversarial lenses** that can veto each other |
| On-chain metrics only | On-chain data **+ investor-canon principles**, both cited |
| Binary safe/scam | **Three-way verdict** — the DEFER tier is where most real trades live |
| "Trust the score" | **Surviving dissent shown** — every objection that didn't kill the trade is still surfaced |
| Fabricates a verdict on thin data | **Abstains** — defaults to DEFER, never to a false SAFE |

## How it works

### Step 1 — Trigger detection
Fire when the user or another agent is about to swap/trade, or asks any
risk question: "Should I buy X?", "Is this safe?", "Check risk for X",
"Analyze before swapping".

### Step 2 — Gather evidence (one pass, cached)
Pull only what the lenses need, in parallel, and cache by token+chain for
the duration of the session:

- **okx-dex-token** — market cap, liquidity depth, holder distribution, age
- **okx-dex-market** — live price, 24h volume, volatility, swap slippage
- **okx-wallet-portfolio** — current holdings, sector concentration, free balance
- **okx-security** — contract verification, honeypot/phishing flags, approval risk

If any source fails, do **not** guess its values — mark that lens
`abstain` and let the coordinator handle it (see Step 4).

### Step 3 — The three-lens panel
Each lens produces `{verdict: bullish|bearish|neutral|abstain, confidence: 0-1, observations: [...]}`.
The lenses are independent and adversarial — they are *expected* to disagree.

**🟦 Market-structure lens** (the "is there a real, tradeable setup" lens)
Reads liquidity, volume, volatility, slippage, age. Bullish only when
there is genuine depth and a clean structure; neutral on chop; bearish on
thin/illiquid/erratic structure. *Canon anchor: Howard Marks — "risk means
more things can happen than will happen"; reward thin-liquidity assets with
suspicion, not optimism.*

**🟥 Security lens** (the hard-veto lens)
Reads contract verification, honeypot/phishing flags, tax traps, holder
concentration. This lens holds a **veto**: a confirmed scam/honeypot/
phishing pattern is bearish at high confidence regardless of how good the
structure looks. *Canon anchor: capital preservation first — a 100% loss
is not recoverable by any future gain.*

**🟩 Portfolio-memory lens** (the "have we been burned here, and what does
this do to the book" lens)
Reads portfolio concentration, sector exposure, and prior outcomes for
this token/sector. Bearish when the trade over-concentrates the book or
repeats a known loss pattern. *Canon anchor: Damodaran — position sizing
and diversification dominate single-trade conviction.*

### Step 4 — Deterministic coordinator (verdict logic in code, not vibes)
The verdict is computed by a fixed rule chain — never the model's gut. This
is what makes the oracle *deterministic* on top of probabilistic lenses:

```
1. security.verdict == bearish AND security.confidence >= 0.8
     → REJECT  (reason: security_veto)
2. market.verdict != bullish OR market.confidence < 0.6
     → DEFER   (reason: insufficient_positive_signal)
3. memory.verdict == bearish AND memory.confidence >= 0.6
     → DEFER   (reason: portfolio_or_history_contradicts)
4. otherwise
     → SAFE    (reason: all_lenses_aligned)
```

A missing lens is treated as `abstain` — its rule simply does not fire to a
green light. Because the market lens is the only *positive*-signal source,
its absence can never produce SAFE. **The system can only say SAFE when it
has affirmative, corroborated evidence.**

### Step 5 — Execution gate
- **SAFE** → agent may proceed to `okx-dex-swap`
- **DEFER** → agent must ask the user for explicit confirmation, surfacing the dissent
- **REJECT** → agent refuses and explains why

## Output format (always JSON)

```json
{
  "verdict": "SAFE | DEFER | REJECT",
  "confidence_score": 0,
  "coordinator_reason": "all_lenses_aligned | insufficient_positive_signal | portfolio_or_history_contradicts | security_veto | insufficient_data",
  "lenses": {
    "market":   {"verdict": "bullish", "confidence": 0.0, "observations": []},
    "security": {"verdict": "neutral", "confidence": 0.0, "observations": []},
    "memory":   {"verdict": "neutral", "confidence": 0.0, "observations": []}
  },
  "surviving_dissent": ["objections that did not kill the trade but the user should know"],
  "reasoning": "Plain-language synthesis of the panel.",
  "recommendation": "Concrete next step.",
  "citations": ["okx-security: contract_verified=true", "canon: Marks — risk = more can happen than will"]
}
```

`surviving_dissent` is the differentiator: even on a SAFE verdict, any lens
objection that didn't reach veto strength is surfaced, not buried. The user
sees the *whole* debate, not just the conclusion.

## Examples

### SAFE — major asset, all lenses aligned
**"Should I buy 1000 USDC of SOL on Solana?"**
```json
{
  "verdict": "SAFE",
  "confidence_score": 92,
  "coordinator_reason": "all_lenses_aligned",
  "lenses": {
    "market":   {"verdict": "bullish", "confidence": 0.9, "observations": ["liquidity $500M+", "slippage 0.1%"]},
    "security": {"verdict": "neutral", "confidence": 0.7, "observations": ["native asset, no contract risk"]},
    "memory":   {"verdict": "neutral", "confidence": 0.6, "observations": ["5% of portfolio — within limits"]}
  },
  "surviving_dissent": [],
  "reasoning": "SOL has deep liquidity, no contract attack surface, and the trade is a small, well-diversified portfolio addition. All three lenses align.",
  "recommendation": "Proceed.",
  "citations": ["okx-dex-market: liquidity=$500M+", "okx-security: native_asset=true", "okx-wallet-portfolio: position=5%"]
}
```

### DEFER — structure ok, but the panel won't fully clear it
**"Should I buy 1000 USDC of NEWFI on Solana?"**
```json
{
  "verdict": "DEFER",
  "confidence_score": 55,
  "coordinator_reason": "insufficient_positive_signal",
  "lenses": {
    "market":   {"verdict": "neutral", "confidence": 0.5, "observations": ["liquidity $500k — shallow", "volatility 15%"]},
    "security": {"verdict": "neutral", "confidence": 0.6, "observations": ["contract unverified — audit pending"]},
    "memory":   {"verdict": "neutral", "confidence": 0.6, "observations": ["10% portfolio impact — acceptable"]}
  },
  "surviving_dissent": ["Contract unverified — not a veto, but unresolved", "Holder concentration 45% in top 10"],
  "reasoning": "NEWFI is not a scam, but the market lens cannot confirm a clean tradeable structure (shallow liquidity, high volatility) and the contract is unverified. No lens reaches a green-light bar.",
  "recommendation": "Verify the contract on a block explorer and reduce size by 50% before proceeding. Or wait for the audit.",
  "citations": ["okx-dex-token: liquidity=$500k, holder_top10=45%", "okx-security: contract_verified=false", "canon: Marks — reward thin liquidity with suspicion"]
}
```

### REJECT — security veto overrides everything
**"Should I buy 1000 USDC of SCAM on Solana?"**
```json
{
  "verdict": "REJECT",
  "confidence_score": 98,
  "coordinator_reason": "security_veto",
  "lenses": {
    "market":   {"verdict": "neutral", "confidence": 0.4, "observations": ["liquidity $10k", "age 2h"]},
    "security": {"verdict": "bearish", "confidence": 0.95, "observations": ["honeypot pattern", "known phishing flag"]},
    "memory":   {"verdict": "neutral", "confidence": 0.3, "observations": []}
  },
  "surviving_dissent": [],
  "reasoning": "The security lens vetoes: honeypot pattern and a known phishing flag. Per capital-preservation-first, a confirmed scam overrides any structural appeal. Executing would likely result in total loss.",
  "recommendation": "Do not proceed. This token is flagged high-risk.",
  "citations": ["okx-security: honeypot=true, phishing=true", "okx-dex-token: age=2h, liquidity=$10k", "canon: a 100% loss is unrecoverable"]
}
```

## Error handling — abstain, never fabricate

**Insufficient data** (a source fails): the affected lens is `abstain`. If
the market lens can't be evaluated, the verdict cannot be SAFE — default to
DEFER:
```json
{"verdict": "DEFER", "confidence_score": 0, "coordinator_reason": "insufficient_data",
 "reasoning": "Could not retrieve token/market data. The oracle does not guess — it abstains.",
 "recommendation": "Retry shortly or verify manually on a block explorer.", "citations": []}
```

**Token not found on any supported DEX:** REJECT — a token that doesn't
exist where it should is a typo or a scam.

## Token efficiency
- Target 500–900 tokens per query. Pull only the fields each lens needs.
- Cache evidence by `token+chain` for the session — never re-fetch within one decision.
- Default to DEFER on incomplete data, **never** to SAFE.

## Security & transparency
- **No custody.** All swaps are signed by the user's TEE-protected Agentic Wallet; this skill only advises.
- **Full audit trail.** Every verdict logs its three lenses, the coordinator reason, surviving dissent, and citations.
- **Explainable, not a black box.** The user always sees *why* — the whole debate, not just the answer.

## Integration with OnchainOS
Sits between research and execution in any trading flow:
```
okx-dex-token → okx-dex-market → [GECKOVISION RISK CHECK] → okx-dex-swap
okx-dex-signal (smart money) → okx-dex-token → [GECKOVISION RISK CHECK] → okx-dex-swap
```
- **SAFE** → continue to `okx-dex-swap`
- **DEFER** → confirm with user, surfacing dissent
- **REJECT** → refuse, explain

## Position management: stall detection (post-entry)

The oracle's job doesn't end at entry. The most common silent loss in
agentic trading isn't a scam — it's the **stall**: a position that climbs
+1–2%, fades, and oscillates in that band for hours without hitting a
take-profit or a stop-loss. It binds a slot at near-zero forward
expectancy while better setups go untaken. GeckoVision flags it.

**Trigger:** "Is [position] stalling?", "Should I rotate out of [token]?",
"Manage my open positions", or any post-entry check on a held position.

**The stall signature** (a held position is stalling when ALL hold):
- **Aged** — open beyond a meaningful window (e.g. ≥90 min on intraday)
- **Stuck in the green no-man's-land** — PnL in roughly +0.3% to +2%, i.e.
  above flat but below the level a real winner reaches
- **No new high recently** — price has not made a new high in ~30 min.
  This is the key *pause-vs-stall* discriminator: a position merely
  *consolidating* before a breakout makes a new high inside that window; a
  *stalled* one does not.

**The pause exception (do NOT exit):** if volume is still healthy (≥~40%
of the entry-bar level) or the price is still printing wide candles, the
position is catching its breath, not dying. Hold. Cutting a pause is how
you turn a winner into a small win.

**The rotation principle:** exiting a confirmed stall is worth it because
it **frees the slot for a better trade** — not because the exit price is
great. Therefore: only rotate when a *fresh, higher-conviction candidate
actually exists*. Rotating a flat +1% position into idle cash (paying
~0.2% round-trip) for no replacement is value-destroying. The verdict must
gate on "a better seat is available," never on "this seat is mediocre."

**Output (stall check):**
```json
{
  "verdict": "HOLD | ROTATE",
  "stall_confirmed": true,
  "signals": {"age_min": 192, "pnl_pct": 1.1, "mins_since_high": 60, "volume_vs_entry": 0.3},
  "reasoning": "Open 3.2h, stuck at +1.1% for over an hour, no new high in 60min, volume decayed to 30% of entry. Momentum is spent — this is a stall, not a pause.",
  "recommendation": "ROTATE only if a fresh candidate is available; otherwise hold to the time-stop. Do not exit into idle cash.",
  "citations": ["okx-dex-market: no_new_high_60min, volume=30%_of_entry"]
}
```

**Provenance:** this rule is not theoretical — GeckoVision's live contest
agent watched the same token stall in the +1–2% band twice (3h+ each)
before this detector was added, and the simple time+structure heuristic
above was falsified against the live trade log: it fires on the stalls and
spares every position that later reached take-profit. The data-driven v2
(return-autocorrelation + volume-decay classifier) is in development as
per-poll telemetry accumulates.

## Monetization
Per-query via the OKX x402 payment protocol (~$0.01–0.05/check), paid
automatically by the calling agent. The risk oracle is a metered service:
agents pay for the brake the same way they pay for the accelerator. Both
the **pre-trade verdict** and the **post-entry stall check** are metered
calls — the oracle covers the full trade lifecycle, entry to exit.

## Provenance
GeckoVision built and ran a live trading agent on the OKX Agentic Trading
Contest using this exact discipline — adversarial lenses, a deterministic
coordinator, and abstain-not-fabricate. The agent declined far more
candidates than it took, and its real on-chain trades closed net positive.
This skill is that discipline, packaged for any agent to install.
