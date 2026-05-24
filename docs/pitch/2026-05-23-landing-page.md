# Landing Page Reframe — geckovision.tech

*2026-05-23. Concrete copy + section structure for the frontend (gecko-mcpay-app). Same spine as the pitch: oracle-not-bot, show-the-number, integrations-as-plumbing. Hand this to `frontend-engineer` in gecko-mcpay-app.*

**The governing rule:** a visitor should understand in 5 seconds that Gecko is **the judgment layer you trust with your money — not another trading bot.**

---

## Hero

**Headline:**
> The honest second opinion you can trust with your money.

**Subhead:**
> Gecko is the verifiable judgment layer above any trading agent. It tells you **SAFE**, **DEFER**, or **REJECT** — with the reasoning, the citations, and the dissent — so you never act on a hallucination.

**Primary CTA:** `Get a verdict →` (links to the skill / a live demo verdict)
**Secondary CTA:** `For builders: read the skill` → `app.geckovision.tech/skill.md`

**Hero visual:** a real **verdict envelope** card — `VERDICT: SAFE`, `dissent: survives`, `citations: investor-canon` — with the agent voices visibly debating. *Show the reasoning happening.*

---

## Section 1 — The problem

**"Your agent acts. It doesn't think."**

Autonomous agents move real money on-chain now — but they execute without judgment. No second opinion. No grounding. No way to know when the agent is confidently wrong. Treating a wallet like an API call breaks the moment the agent is autonomous.

## Section 2 — What Gecko does

**"Ask before you act."**

Propose a trade or strategy. Gecko's multi-voice adversarial panel returns a grounded verdict — **SAFE / DEFER / REJECT** — backed by investor-canon citations and the dissent that survived the debate. Pay per call via x402. Works above any agent.

*(Visual: the SAFE/DEFER/REJECT envelope, expanded — voices, citations, the one dissent that didn't get refuted.)*

## Section 3 — The proof (lead with the number)

**"We don't ask you to trust the oracle. We show you the number."**

> **+0.6% gating delta — CI-clean, across regimes.**
> The trades Gecko approves beat the ones it defers. Backtested on our own multi-regime data, before anyone risks a cent.

*(Visual: the ACT-beats-DEFER bars / the gating-delta chart. Caveat line: "replicated · sign-robust · hardening across regimes.")*

## Section 4 — Not a bot

**"We're not a trading bot. We're the layer that makes any agent trustworthy."**

*(Visual: the architecture diagram, reframed — the Gecko Oracle large and central; OKX, Cloak.ag, Kamino, Solana as a small "works with" ring of swappable infrastructure.)*

> The trading agent is our proof artifact. The oracle is the product. Execution, privacy, and yield are partners — like AWS or Supabase.

## Section 5 — Three modes of trust

**Paper → Local → Hosted Safe Mode**

| Paper | Local (ElizaOS) | Hosted Safe Mode |
|---|---|---|
| Try it risk-free | Run it on your machine | Sandboxed env + Cloak privacy + your allocation policies |

## Section 6 — How it's different

| | They | Gecko |
|---|---|---|
| **AI trading agents** | act, no judgment | the judgment |
| **Security layers** | "is this tx allowed?" | "is this a good decision?" |
| **Data feeds** | sell data | sell judgment grounded in data |

## Section 7 — Honest by design

**"An oracle you can audit."**

LLM agents hallucinate confidence. Gecko surfaces dissent instead of hiding it — every verdict shows the reasoning, the sources, and the strongest argument against itself. We even ran our own pitch through it; it told us where we were weak.

## Section 8 — For builders

**Composable from day one.** x402 metering · MCP server · a one-command Claude skill · neutral across wallets and chains.

```
Read app.geckovision.tech/skill.md → bootstrap → call gecko_research
```

## Footer CTA

> **Stop trusting agents blindly. Start trusting the verdict.**
> `Get a verdict →`   ·   `Join the waitlist`

---

## Copy do / don't (for whoever edits the live site)

- ✅ Lead with **judgment / oracle / second opinion**. ❌ Never "bot" or "trading system" in the hero.
- ✅ **Show the reasoning** (verdict envelope, voices, dissent) — it *is* the product. ❌ Don't hide it behind marketing gloss.
- ✅ Integrations = a quiet **"works with"** logo strip. ❌ Never co-headline OKX/Cloak/Kamino with Gecko.
- ✅ Lead the proof with **the gating-delta number**. ❌ Don't say "trust us."
- ✅ Reputation/score **bands** in public surfaces (emerging/established). ❌ No raw scores, no public leaderboards (anti-gaming rule).
