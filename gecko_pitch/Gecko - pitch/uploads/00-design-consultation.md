# Pitch Design Consultation
*From: product-designer agent*
*To: Ernani*
*Re: how to structure the 3-minute Colosseum video pitch*

---

## The brief, restated

You're submitting to Colosseum's hackathon. Format is a **3-minute video pitch** (max), submitted alongside a technical walkthrough (also under 3 minutes), a GitHub repo, and product docs. Judges review hundreds of submissions asynchronously. Top projects then get a panel review.

This is **not a live stage pitch.** It's a recorded artifact that competes against ~1,500 other recorded artifacts for ~30 seconds of judge attention before they decide whether to keep watching.

That changes everything.

## What a live stage pitch optimizes for vs. a video pitch

| Dimension | Live stage | Recorded video |
|---|---|---|
| Risk of failure | Network can break, mic can fail | None — you re-record until it's right |
| Audience attention | Captive, full 3 minutes | First 15 seconds decides whether they finish |
| Drama mechanism | Tension/release in real time | Cuts, reveals, pacing — like a film trailer |
| Q&A | Live, adversarial | None — your video is your only shot |
| What earns the prize | Composure under pressure + the moment | The moment, plus making it visible to a tired reviewer |

You're optimizing for the second column. Most builders don't realize this and produce live-pitch-style videos that lose the first 15 seconds to setup. Don't do that.

## Three principles I'd hold this pitch to

These are the same principles I hold the *product* to, applied to the pitch:

### 1. The reveal is the pitch.
In the product, 20 minutes of indexing is invisible work — the documents rendering is the moment. In the pitch, 6 weeks of building is invisible work — the **402 → on-chain payment → documents return** cycle is the moment. Everything else in the 3 minutes is scaffolding around that moment. The video should be designed back-from the moment, not forward-from a problem statement.

### 2. Progress, not silence.
A judge watching their 47th video at midnight needs visual movement. Static slides with you talking over them is silence. They tab away. Use:
- Terminal sessions actually running (real text appearing, not screenshots)
- On-chain transactions actually confirming (Solana explorer in real time, or recorded with timestamps visible)
- Documents actually rendering (the Rich panels appearing one after another, not a single static screenshot)

Movement signals "this is real, not vaporware." Stillness signals "this is a deck."

### 3. No model branding, no jargon decoration.
Same rule as in the product. Don't say "AutoGen GroupChat with 5 specialist agents." Say "five specialists work on it together." Don't say "x402 HTTP 402 Payment Required protocol." Say "the agent gets a bill, pays it, gets the answer." Jargon is a self-conscious tell. Confident products explain themselves in plain language. Then, if someone asks, *then* you say "x402."

This is counterintuitive for a Solana hackathon — you'd think more jargon = more credibility. It doesn't. The judges already know x402. They're looking for the project that uses x402 to do something they hadn't seen before. Your job is to show the *something*, not the *protocol*.

## The structural decision

I'd structure the 3 minutes like a film trailer, not like a slide deck. Specifically:

```
[0:00 – 0:15]  THE COLD OPEN — 15 seconds
                The reveal moment, mostly without context.
                Show terminal: agent calls research → 402 →
                payment confirms → documents render.
                One short caption: "An AI agent just paid for
                its founder to find out if their idea is real."
                No logo, no name, no problem statement.

[0:15 – 0:45]  THE PROBLEM — 30 seconds
                NOW the context. The pain you're solving.
                "Every founder loses 20 hours of their life
                to research before knowing if the idea is real.
                Most quit. Most ship the wrong thing."
                Visual: someone manually transcribing a YouTube
                video into a notes app at 1am.

[0:45 – 1:30]  THE SOLUTION — 45 seconds
                What Gecko does, in plain language.
                Demo the actual flow more thoroughly now.
                You can let it breathe.
                Show the document reveal in full.
                Citations clickable. Sources visible.

[1:30 – 2:15]  WHY NOW — 45 seconds
                The agentic economy is real this quarter.
                MCPay, frames.ag, ClawRouter — show the stack
                you compose. "We're the first product where
                the buyer is an agent and the beneficiary is
                a person." 
                This is where you flag the moat — encoded
                judgment, session-as-asset, x402 throughout.

[2:15 – 2:45]  WHO YOU ARE + ASK — 30 seconds
                15-year engineer, lived the pain, built the
                product. SuperteamBR community.
                One specific ask: accelerator slot, not a
                vague "support."

[2:45 – 3:00]  END CARD — 15 seconds
                Domain. One QR or URL. Repo link.
                "Read app.geckovision.tech/skill.md to install."
```

The key structural choice is the **cold open**. Putting the reveal first violates every "problem-solution-traction" deck template, which is exactly why it works. After 47 videos that all start "Hi, I'm X, today I'm presenting Y, let me tell you about a problem...", a video that opens on something *happening* gets attention.

## The thing most builders get wrong

Most pitches treat the product as the *answer to the problem.* So they spend a minute on problem, then the rest on solution. By the time the demo arrives, the judge is half-engaged.

Reverse it. **Treat the product as the hook, and the problem as the explanation of why the hook matters.** The judge is engaged from second 1. By the time the problem statement arrives, they want to know why this thing they just saw exists. That's a much higher level of engagement than passive listening.

This is also why the cold open is short — 15 seconds. Long enough to show something working, short enough that the judge is still in "what am I looking at?" mode when the problem statement starts answering it.

## What the demo moment specifically should look like

This is the most important 15 seconds. Storyboard:

**Frame 1 (3 sec):** Terminal. Already-running Claude Code session.
> User types: `Use gecko_research to validate: a hotel guide for Brazil`

**Frame 2 (3 sec):** Terminal output appears in real-time:
```
→ POST https://api.geckovision.tech/research
← HTTP 402 Payment Required
  Required: $20 USDC on Solana
  Pay to: 9xK7...3pQr
```

**Frame 3 (3 sec):** Split screen. Left: terminal continues. Right: Solana Explorer in browser.
```
Left terminal:
→ Signing payment via frames.ag wallet...
→ Transaction confirmed: 5xA8...

Right browser:
[explorer.solana.com showing the actual tx]
"USDC Transfer · 20.00 USDC · Confirmed 2s ago"
```

**Frame 4 (3 sec):** Terminal back to fullscreen.
```
→ Indexing sources... [████████] 7/7
→ Generating documents...
```

**Frame 5 (3 sec):** Three Rich panels render in sequence.
```
┌─ Business Plan ──────────────┐
│ Problem: Brazilian travelers │
│   booking hotels rely on...  │
│   [more content]              │
│ Sources: 1, 4, 7              │
└──────────────────────────────┘
[next panel renders]
```

15 seconds. No voice-over yet — let the visuals talk. Add a single text caption at the end:

> *An AI agent just paid for its founder to find out if their idea is real.*

That's the cold open. Everything that follows is context.

## What stays out

A few things I'd cut even though they feel important:

- **Tech stack slides.** The judge can read your repo. Showing "Python + FastAPI + Supabase + ..." in the video is wasted seconds. Save it for the technical walkthrough video.
- **Architecture diagrams.** Same reason. They belong in the doc, not the pitch.
- **Token economics / future tokenomics.** Not relevant to V1. Distracting.
- **The full 3-document reveal.** Show *one* document fully, *the other two as glimpses*. Three full documents takes 30 seconds and the judge has already gotten the point after the first. Save the "yes really, all three are this good" for the leave-behind one-pager.
- **Creator economy V2.** It's in the roadmap. Don't muddy V1's pitch with V2's vision unless explicitly asked.

## What goes in the technical walkthrough (the second video)

The hackathon also asks for a separate technical walkthrough under 3 minutes. **This is where the architecture diagrams, code, and integration depth go.** Don't conflate it with the pitch. The pitch is about the product working; the walkthrough is about how it works.

Ideal walkthrough structure:
1. The 30-second flow at a system level (diagram + voice-over)
2. Show the actual x402 middleware code in `gecko-api/main.py` — 30 seconds
3. Show the frames.ag `/x402/fetch` integration — 30 seconds
4. Show ClawRouter routing per-specialist models — 30 seconds
5. Show the citation-grounding test passing — 30 seconds
6. Repo link + "all open source" — 15 seconds

Keep them as separate videos. Conflating them weakens both.

## My specific recommendations for the pitch package

Build these artifacts, in this order:

1. **Stage script (the pitch video script)** — second-by-second, what's on screen, what you say. This is the primary deliverable.
2. **Demo moment storyboard** — the 15-second cold open frame-by-frame, since this is the hardest and most important part to nail.
3. **One-pager / leave-behind** — what a judge reads when they want to learn more after the video. Should make the pitch redundant — i.e., it should stand alone for someone who never watched the video.
4. **Q&A prep** — even though there's no live Q&A, the panel review at the end of the hackathon does include conversations. The 10 hardest questions and your answers.
5. **Backup slide deck** — for when the panel asks you to walk through something live and screen-share. 5-8 slides. Not a primary artifact, just insurance.

Build them in that order because each subsequent artifact references the previous one. If you start with slides, you'll over-design them and underbuild the script.

## One framing thing I want you to push back on

Reading the conversation history, there's a tension in your pitch I want to surface: **are you pitching Builder Bootstrap, or are you pitching "x402 throughout"?**

These are not the same pitch.

- **"Builder Bootstrap"** — the product that validates startup ideas. The x402 part is implementation. Audience: anyone who's ever started a company.
- **"X402 throughout"** — the technical achievement of composing three x402-native primitives. The product is the demonstration. Audience: Solana ecosystem judges who care about agentic infrastructure.

The Colosseum diagnosis pushed you toward the second framing. The product story is the first framing. Both are real. But you can't lead with both in 3 minutes — you have to pick which one is the cold open and which one is the explanation.

My instinct: **lead with the product, explain via x402.** Reasons:
- Judges have seen 30 x402 pitches by now. "We use x402" is no longer differentiation.
- The product is genuinely novel (agent-buys-research-for-human is new).
- Leading with x402 makes you a wrapper. Leading with the product makes x402 a tool you used.
- The diagnosis was right that x402 needs to be load-bearing — but load-bearing in the demo, not in the headline.

If you lead with "x402 throughout," you're competing with frames.ag and MCPay on infrastructure. You'll lose. If you lead with "agents buying validation for founders," you're in a category of one.

## Pitch length sanity check

3 minutes is **450 words at normal speaking pace**, or 300 words if you're leaving room for visuals to breathe. Your script should target ~300 words of voice-over. That's 1 page double-spaced.

If your draft is longer, cut. If it's much shorter, you're under-using the time.

## What I want you to confirm before I (or `business-manager`) draft the script

Three calibrations, because the script flexes on these:

1. **Lead framing: product (Builder Bootstrap) or infrastructure (x402 throughout)?** I recommend product. Confirm.
2. **Demo: live recording of the actual flow, or polished re-recording with edits?** Polished is better for video; live captures don't trim well. Confirm.
3. **Tone: founder-narrator (you on camera) or product-driven (no face, just terminal/voice-over)?** Founder-narrator is more memorable; product-driven is more polished. Hackathon judges historically respond to founder-narrator because it shows you can pitch.

Once those are answered, the next step is the script itself, the storyboard for the cold open, the one-pager, and the Q&A prep — in that order.

---

*— product-designer*
