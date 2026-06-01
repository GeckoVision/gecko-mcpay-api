# Gecko Oracle Stack — what we use, what we're adding

**Audience:** investors, builders asking "which oracle is Gecko using?", pitch deck Q&A backup.
**Last updated:** 2026-06-01.

## The honest one-line answer

> **OKX OnchainOS is our primary data spine today. Pyth + Jupiter are coming Sprint 29 as independent cross-source verification. We're not Chainlink-dependent — Chainlink's Solana coverage is too thin for our universe.**

---

## What "oracle" means in our stack

The word "oracle" gets overloaded. We use it three different ways:

1. **Price oracle** = where the bot reads the current price of an asset (Pyth, Switchboard, DEX TWAP, CEX feeds). This is what investors usually mean.
2. **Data oracle** = the broader feed (OHLCV history, order book, funding, news). OKX OnchainOS fills this role.
3. **Judgment oracle** = Gecko itself. The 7-specialist panel that says act/pass/defer with citations. This is the **product**.

When we say "Gecko is the judgment oracle," we mean #3. The "which oracle do you use" question is about #1 and #2.

---

## Today (live in production)

| Layer | Provider | What it gives | Why this one |
|---|---|---|---|
| **Primary data spine** | **OKX OnchainOS** | OHLCV (5m + 1h) · order book depth · funding rate · smart-money signals · news | Single API for the full stack; strong Solana coverage; no key rotation; we already use OKX's Agent Trade Kit for execution |
| **On-chain RPC** | **Helius** | Solana account state, parsed transactions, asset metadata (DAS) | Industry default for Solana RPC; we pay $99/mo for the tier we use |
| **Investor canon corpus** | Free public-domain PDFs (Marks, Damodaran, Berkshire, Mauboussin) | The grounding for citation-shaped verdicts | Free, copyright-clean, embeddable |
| **Backtest history (offline)** | ccxt → Binance + CoinGecko hourly | Deep OHLCV history for CPCV / PBO / DSR rigor | Free, cross-cycle history Pyth Hermes doesn't have |

**Not in active use today:** Pyth, Birdeye, Switchboard, Chainlink.

---

## Sprint 29 (planned, not yet shipped)

Adding two **independent** price sources as cross-source verification — NOT replacing OKX:

| Source | Role | Why add it |
|---|---|---|
| **Pyth Hermes** | "Fair value" reference from 15+ publishers | Independent failure mode — catches OKX stale/manipulated price; free public REST API |
| **Jupiter aggregator** | EXECUTABLE price (what you'd actually buy at after slippage) | Different from Pyth's "fair value"; catches when fair-value-vs-executable-spread widens (a real risk signal) |

The bot's price gating becomes a **three-way agreement check**:
- OKX, Pyth, Jupiter all agree within 30bp → high-confidence trade
- Any pair disagrees > 50bp → decline (data quality too low)
- This becomes the **7th voice** (`oracle_voice`), deterministic confidence, no LLM

**Cost:** ~$0.35/mo (Voyage embeddings on the snapshot substrate). The oracle APIs themselves are free.

**Status:** design locked, implementation planned next sprint. See `docs/build-plan-sprint-29-oracle-ingest.md`.

---

## Why NOT Chainlink

Honest answer: **Chainlink's Solana coverage is too thin for our universe.**

- Chainlink's data feeds on Solana cover SOL, USDC, BTC, ETH, AVAX — but coverage drops sharply for the meme + small-cap tokens our bot trades (PYTH, WIF, JTO, etc.)
- Pyth has feed IDs for 600+ Solana assets including our entire active universe — see `packages/gecko-core/src/gecko_core/sources/market_data.py` for the pinned IDs
- Chainlink's pull model on Solana is gas-paid; Pyth Hermes is free REST
- For a multi-source verification strategy, **Pyth + Jupiter + OKX gives more independent failure modes than Pyth + Chainlink + OKX**

We're not anti-Chainlink. We'd add it if a specific symbol needed it (e.g. wrapped BTC pricing if we expand to cross-chain). For Solana-native + meme-leaning universe, Pyth is the right primary on-chain oracle.

---

## Why NOT Switchboard

Same logic as Chainlink: marginal coverage gain over Pyth alone for our universe.

- Switchboard is operationally similar to Pyth (multi-publisher aggregation)
- Adding Switchboard as a 4th source = political diversification (don't depend on a single oracle provider)
- Defer to Phase 3 of Sprint 29 — only adds value AFTER Pyth + Jupiter prove their cost-benefit

---

## Common investor questions + sharp answers

**Q: "What oracle is Gecko using?"**
A: "OKX OnchainOS as primary data spine; Pyth + Jupiter coming next sprint as cross-source verification. The 'judgment oracle' people refer to as our product is the 7-specialist panel itself."

**Q: "Are you using Chainlink?"**
A: "No. Chainlink's Solana coverage is too thin for our meme + small-cap universe. Pyth has feed IDs for every asset we trade. We're picking on independence + coverage, not brand."

**Q: "What if OKX has an outage?"**
A: "Today: the bot would decline new entries until OKX recovers — we don't have cross-source verification yet. Sprint 29 adds Pyth + Jupiter so any single-source outage triggers an oracle_voice abstain instead of a full halt. Cross-source agreement BECOMES the data-quality signal."

**Q: "Why not build your own oracle?"**
A: "We're not in the price-discovery business. We're in the judgment business. Pyth has 15+ publishers; we're not going to out-publish them. Our edge is what we do WITH the price — adversarial debate, surviving dissent, default-decline. The oracle layer is plumbing."

**Q: "Is OKX a centralized point of failure?"**
A: "Today, yes. It's a CEX-rooted data feed. Sprint 29 reduces that dependence — when Pyth + Jupiter + OKX all need to agree, OKX going down doesn't take the bot down; it just narrows what we can grade. That's the right kind of degradation."

**Q: "Does the judgment oracle need a price oracle to function?"**
A: "Yes for the trade-decision path. No for the verdict-shape path. The `gecko_trade_research` MCP call works on a question + context regardless of live price — you can ask 'is depositing USDC into Kamino a good move' and get a cited verdict whether or not the price feed is live. Live price gating is for the autonomous-agent path."

---

## What's in code today (verifiable)

If someone asks for proof:

```bash
# Primary OHLCV source (the bot's eyes):
grep "get_candles\|onchainos" contest_bot/jto_breakout_gecko_gated_contest_bot.py | head

# Pyth client (exists but NOT in the live bot's price path):
ls packages/gecko-core/src/gecko_core/trade_agent/hotpath/pyth.py

# Pyth feed IDs catalog (reference, not active):
grep "PYTH_PRICE" packages/gecko-core/src/gecko_core/sources/market_data.py

# Helius (RPC, not price oracle):
grep "HELIUS_API_KEY" .env
```

Honest framing: **the Pyth code exists from earlier sprints but the live bot doesn't read it.** Sprint 29 makes that real.

---

## Cross-references

- `docs/build-plan-sprint-29-oracle-ingest.md` — full Sprint 29 design
- `docs/methodology/data-pipeline.md` — how data flows from source to voice
- `docs/methodology/lopez-de-prado-pitfalls.md` — why cross-source verification matters (Pitfall #3 / data quality)
- `packages/gecko-core/src/gecko_core/sources/market_data.py` — the Pyth feed ID catalog
- `packages/gecko-core/src/gecko_core/trade_agent/hotpath/pyth.py` — existing PythHermesClient we can reuse
