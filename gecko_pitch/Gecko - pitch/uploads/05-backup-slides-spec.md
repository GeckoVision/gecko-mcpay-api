# Backup Slide Deck Specification

**Purpose:** for the panel review (after shortlisting), when a judge says "can you walk me through that?" and you screen-share. Not the primary pitch artifact. Just insurance.

**Format:** 8 slides max. Plain. Readable.
**Tool:** Whatever you're fastest with — Keynote, Figma, Slides. Don't over-design.

The video pitch is your primary deliverable. These slides exist for the moment a judge wants to dig in past the video. Keep them focused on the *evidence* layer, not the *narrative* layer.

---

## Slide 1 — Cover
*Equivalent to the video's end card, used as cover here.*

**Top half:** Logo (or just "Gecko" in clean type)
**Center:** *Builder Bootstrap Platform*
**Below center:** *The first product where an AI agent commissions startup validation for the founder it works for.*
**Footer:** Solana · x402 · geckovision.tech

---

## Slide 2 — The problem, with one number

**Title:** *Founders waste six months building the wrong thing.*

**Body:** Single quote, large text:
> *"I spent twenty hours manually transcribing YouTube videos before I knew if my idea was real. Then I shipped the wrong product and lost six months."*
> — Co-founder, Gecko

**Footer:** This isn't a survey result. It's why we're here.

(One quote with attribution beats a fake-survey statistic. Judges have seen too many "$50B market" decks.)

---

## Slide 3 — The product, in one screenshot

**Title:** *30 minutes from idea to validated decision.*

**Body:** Single screenshot — the three Rich panels rendered (Business Plan, Validation Report, PRD) with citations visible. Don't add bullet points around it. **Let the screenshot do the work.**

**Footer:** Cited sources. 90-day knowledge base. Free follow-ups.

---

## Slide 4 — Why x402 is load-bearing (the differentiation)

**Title:** *Three reasons x402 is structural, not a checkout method.*

**Body:** Three short bullets, each one sentence:

1. **The buyer is an agent.** Agents can't use Stripe. Agents can't fill out forms.
2. **No API keys, ever.** Wallet signature is auth. Same primitive does payment.
3. **The stack composes from independent x402-native primitives.** Without the protocol, frames.ag + ClawRouter + Gecko don't interop.

**Footer:** Run our validation rubric on Gecko. Without x402 = no product.

---

## Slide 5 — The architecture, simplified

**Title:** *Every payment in the stack is x402.*

**Body:** Diagram. Three boxes left-to-right:

```
[Builder's agent]   →   [Gecko API]   →   [LLM providers]
       │                     │                  │
       ↓                     ↓                  ↓
 frames.ag wallet      x402 middleware     ClawRouter
 (pays Gecko)          (verifies + runs)   (routes + pays)

       └──── all USDC, all on-chain, all visible ────┘
```

**Footer:** No credit cards. No API keys. Anywhere.

---

## Slide 6 — Status

**Title:** *Working today, on Solana mainnet.*

| Component | State |
|---|---|
| Core SDK + ingestion + RAG | ✅ Live |
| x402 payment middleware on `gecko-api` | ✅ Live |
| frames.ag wallet integration | ✅ Live |
| ClawRouter LLM integration | ✅ Live |
| MCP server + Claude Code skill | ✅ Live |
| Pro tier (5-agent GroupChat) | 🚧 In progress |
| Web app | 📋 V2 |

**Footer:** Skill bootstrap: `app.geckovision.tech/skill.md`

---

## Slide 7 — Roadmap

**Title:** *Sessions today. Knowledge marketplace tomorrow.*

| Phase | When | What |
|---|---|---|
| **V1** | Now | Builder Bootstrap — paid research sessions for founders |
| **V2** | Q3 2026 | Web app + creator attribution + accelerator B2B |
| **V3** | 2027 | Knowledge API for other agentic frameworks |

**Footer:** Same product, expanding categories: validation → due diligence → market sizing.

---

## Slide 8 — Ask

**Title:** *We want a Colosseum accelerator slot.*

**Body:**
- $250K pre-seed funding
- Mentor network in agentic infrastructure
- Credibility for partner integrations across x402 ecosystem

**Below body, smaller:**
*Founders: Ernani Britto (15+ years engineering, lived this pain twice) + co-founder (design)*
*Community: SuperteamBR · Hub: geckovision.tech · Repo: github.com/<owner>/gecko*

---

## What's NOT in this deck

To be deliberate:

- **No tech stack laundry list.** "Python + FastAPI + Supabase + ..." is in the repo. Showing it here just steals attention.
- **No competitor matrix.** Frames.ag and MCPay are partners, not competitors. A matrix forces you to position against them — and you lose that frame.
- **No revenue projections.** $X by year Y. Don't fabricate numbers a panel will instantly poke holes in. Trust your traction story.
- **No "team values" or "vision" slide.** Earned trust comes from the product working, not from declarations.
- **No QR code.** Solid in-person, weak on video calls. Use a clean URL instead.

If a judge asks for any of the above, you have answers ready (the one-pager covers traction + revenue thinking). But unprompted, none of it earns its slide.

---

## Build instructions

Don't spend more than 90 minutes on these slides. They're insurance, not the primary deliverable. The video pitch and one-pager are what win.

If you find yourself adjusting fonts or animations, stop. The slides exist to support live conversation. They are not the conversation.
