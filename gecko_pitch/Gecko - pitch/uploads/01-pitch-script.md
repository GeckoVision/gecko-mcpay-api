# Pitch Script — 3 Minutes
**Format:** Recorded video for Colosseum hackathon submission
**Length:** 3:00 hard cap (judges stop watching)
**Approach:** Product-led, polished re-recording, founder-narrator with face on camera at key moments

---

## Production notes (for whoever edits this)

- **Voice-over recorded separately**, layered over screen recordings. Better audio than screen-mic.
- **Two camera setups:** webcam for founder-narrator moments (~30 seconds total), screen recording for the rest.
- **Music:** none, or extremely minimal/ambient. Music dates pitches and distracts from terminal text. The terminal output IS the soundtrack.
- **Captions:** burned-in for accessibility and because half of judges will watch with sound off.
- **Resolution:** record at 1080p minimum. Terminal text needs to be legible.
- **Pacing:** voice-over speaks at 130 wpm (slower than conversational). Lets visuals breathe.

---

## 0:00 – 0:15 — COLD OPEN

**On screen:** Black screen, 1 second. Then cut to a Claude Code terminal session, already open. Cursor blinks at the prompt.

**Voice-over:** *(silent — let the keystrokes carry)*

**Action:**
```
> Use gecko_research to validate: a hotel guide for Brazil
```
*(typed in real-time — visible character-by-character)*

**On screen continues:**
```
→ POST https://api.geckovision.tech/research
← HTTP 402 Payment Required
  Required: $20.00 USDC on Solana
  Pay to: 9xK7...3pQr
→ Signing payment via frames.ag wallet...
→ Transaction confirmed: 5xA8...
```

**Cut to split screen:** terminal on left, browser showing Solana Explorer on right with the actual transaction confirmed. Timestamp visible.

**Cut back to terminal:**
```
→ Indexing 7 sources... [████████]
→ Generating documents...

┌─ Business Plan ──────────────────────┐
│ Problem: Brazilian travelers...       │
│ ...                                    │
└────────────────────────────────────────┘
[Validation Report and PRD render briefly]
```

**On screen at 0:13:** white text, dark background, centered.

> *An AI agent just paid for its founder to find out if their idea is real.*

**Hold for 2 seconds.** Cut.

---

## 0:15 – 0:45 — THE PROBLEM

**On screen:** Founder on camera, plain background, looking into camera. (Eye contact matters — sells authenticity.)

**You say:**

> "Every founder I know — including me — has spent twenty hours of their life on research before knowing if their idea was real. Watching YouTube videos. Taking notes by hand. Reading PDFs at midnight."

**Cut to:** B-roll of someone scrolling YouTube, taking handwritten notes. *(If you don't have B-roll, stay on you.)*

> "And most of us either quit, or worse — we ship the wrong thing. Six months of building something nobody wanted. The cost isn't twenty bucks of research time. It's six months of your life."

**Cut back to you, slightly closer crop.**

> "I built Gecko because I'd done that twice."

**On screen text card at 0:43:**
> *Gecko — the agent that validates startup ideas before founders waste six months.*

---

## 0:45 – 1:30 — THE SOLUTION

**On screen:** Cut back to terminal. Now show the *full* document reveal, not the cold-open glimpse.

**Voice-over (you, off-camera):**

> "You give Gecko an idea. It indexes the sources you'd need to read — YouTube, web, articles. It generates three documents: a business plan, a validation report, and a PRD. Every claim cited to a real source you can click through to."

**On screen:** the three Rich panels render in full. Camera lingers on a citation as the cursor hovers — the URL is visible and clickable.

> "Thirty minutes. Not twenty hours."

**Cut to a fresh terminal:**
```
> Use gecko_ask <session_id> "what's the strongest validation signal?"
```

**On screen:** A grounded answer renders, with citations.

> "And the knowledge base stays alive. Founders ask follow-up questions for free, anytime, for ninety days. Because the unit isn't a query. It's a decision."

**On-screen text card at 1:28:**
> *$20 per session. The decision is worth more.*

---

## 1:30 – 2:15 — WHY NOW

**On screen:** You back on camera, slightly different framing (signal: new section).

**You say:**

> "This wasn't possible a year ago. Coinbase shipped x402 — payments over HTTP, designed for AI agents. The Linux Foundation just took it over with Visa, Mastercard, Stripe, and Microsoft as founding members. Three weeks ago."

**Cut to:** simple title card with logos: x402 / Coinbase / Linux Foundation / Visa / Mastercard / Microsoft.

> "frames.ag built the wallet for agents. ClawRouter built the LLM router for agents. We built the first thing those agents would actually want to buy — research that tells a builder whether their idea is real."

**Cut to:** simple diagram. Three boxes labeled "frames.ag — wallet," "ClawRouter — LLMs," "Gecko — research." Arrows show payment flow. Each box flashes briefly as named.

> "Every payment in the stack is x402. The agent pays Gecko. Gecko pays its LLMs through ClawRouter. No credit cards. No API keys. Anywhere."

**Cut back to you on camera.**

> "Other products use x402 for billing. We use x402 to compose an agentic economy from three independent primitives, in a single product founders can install with one URL."

---

## 2:15 – 2:45 — WHO + ASK

**On screen:** You on camera. Confident close.

**You say:**

> "I'm Ernani Britto. I've been a software engineer for fifteen years. I lived this problem twice. I'm building Gecko with my co-founder out of SuperteamBR."

**Brief pause.**

> "We're already integrated with frames.ag and ClawRouter. We're shipping on Solana mainnet. The product works."

**Cut to terminal one more time:**
```
> Read https://app.geckovision.tech/skill.md
```

**On screen text:**
> *One URL. No API keys. Just a wallet.*

**You say (voice-over):**

> "We want a Colosseum accelerator slot, because what we're building doesn't end at validation. The next chapter is every paid knowledge product agents commission for the humans they work for — due diligence, technical research, market sizing — all on the same rails. We want to build the canonical version of that."

---

## 2:45 – 3:00 — END CARD

**On screen:** Clean end card.

```
Gecko — Builder Bootstrap Platform

geckovision.tech
github.com/<owner>/gecko

Read https://app.geckovision.tech/skill.md to install.

Built on Solana. Powered by x402.
```

**Voice-over (final, calm):**

> "If you've ever wasted six months building the wrong thing — Gecko exists so the next founder doesn't have to."

**Hold 2 seconds.** Fade to black.

---

## Word count check

Voice-over text only (excluding visual cues, captions, on-screen text):
- Cold open: 0 words (silent)
- Problem: 95 words
- Solution: 75 words
- Why now: 95 words
- Who + ask: 60 words
- End card: 18 words

**Total: 343 words at 130 wpm = 2:38 of voice-over.** Leaves ~22 seconds for silent visual moments (cold open, cuts, end card hold). Comes in just under 3:00.

---

## What this script is NOT

- It's not the technical walkthrough. That's a separate 3-minute video where you show code, architecture, and the integrations in depth. **Do not put architecture diagrams in this video.**
- It's not the leave-behind. The one-pager (separate file) goes deeper on traction, team, and roadmap.
- It's not optimized for live Q&A. There's a separate Q&A prep doc for the panel review.
- It's not a slide deck pitch. If you find yourself making slides for this script, stop — this is a video. The "slides" are terminal sessions, on-screen text cards, and brief visual diagrams.

---

## Edit/recording checklist

Before you call it done:

- [ ] Cold open is *exactly* 15 seconds. Time it. If it runs long, cut.
- [ ] Solana Explorer transaction shown is real (devnet or mainnet, doesn't matter — but real, with a clickable link in the description).
- [ ] Citations in the document reveal point to real URLs that resolve.
- [ ] No model brand names visible anywhere on screen ("OpenAI," "Anthropic," "GPT-4o," etc.). Cover them with overlays if necessary.
- [ ] Captions burned in, accurate to spoken voice-over.
- [ ] Watch the whole thing with sound off. Does it still make sense? If no, add captions or adjust visuals.
- [ ] Watch the whole thing at 1.5x speed. Does any part drag? If yes, cut.
- [ ] First-frame freeze test: pause at 0:01. Is what's on screen interesting enough to keep watching? If a thumbnail is just your face, weak. If it's a terminal mid-action, strong.
