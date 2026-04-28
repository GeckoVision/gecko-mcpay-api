# Gecko Pitch Package v1

The pitch artifacts for Colosseum hackathon submission. Built using the `product-designer` agent's perspective on demo structure first, then the deliverables.

## What's in here

```
.
├── README.md                       (this file)
├── 00-design-consultation.md       — product-designer's reasoning on the pitch structure
├── 01-pitch-script.md              — the 3-min video script, second-by-second
├── 02-cold-open-storyboard.md      — frame-by-frame for the critical first 15 seconds
├── 03-one-pager.md                 — leave-behind for judges who want depth after the video
├── 04-qa-prep.md                   — 10 hardest questions + sharp first-sentence answers
└── 05-backup-slides-spec.md        — 8-slide deck spec for live screen-share moments
```

## Reading order

If you read top-to-bottom, you get the reasoning behind every choice. If you're short on time:

- **Start with `00-design-consultation.md`** to understand *why* the pitch is structured this way (product-led, cold open, 15s reveal moment, no jargon-decoration).
- **Then `01-pitch-script.md`** for the actual deliverable.
- **Then `02-cold-open-storyboard.md`** before recording — those 15 seconds are the hardest to nail.
- **Skim `03-one-pager.md`** — copy-paste ready as Markdown, can be exported as PDF for submission.
- **`04-qa-prep.md`** — read once before the panel review, don't over-memorize.
- **`05-backup-slides-spec.md`** — only if you have time after recording the video.

## What's NOT in this package

- **The technical walkthrough script.** Colosseum asks for a separate ≤3-min walkthrough video alongside the pitch. That's a different artifact (architecture + code) and it should be built separately, after the pitch is locked. The pitch is the product working; the walkthrough is how it works.
- **A separate PRD or business plan.** You already have these (`docs/PRD.md`, `docs/product-story.md`, the Colosseum diagnosis, `docs/implementation-plan-v3.md`). Those are appendix material — useful when a judge digs in. The pitch synthesizes from them; it doesn't replace them.
- **Submission form copy.** The Colosseum platform has fields for project description, tracks, etc. The one-pager content is the source for those fields — adapt and shorten as needed.

## Calibrations made (so you know what to push back on)

I committed to three structural choices without explicit confirmation, because the conversation history made the answers clear. If any feels wrong, push back and I'll adjust:

1. **Lead framing: product, not infrastructure.** "Builder Bootstrap" is the headline, "x402 throughout" is the explanation. If you wanted to lead with infrastructure, the script flips inside-out.
2. **Tone: founder-narrator with face on camera.** You're on screen during the problem statement and the team/ask sections. Off-screen voice-over for the demo and explanation. If you'd rather be entirely off-camera, the script reduces to voice-over throughout — works, but loses the trust signal.
3. **Demo: real flow, real wallet, real on-chain transaction.** The Solana Explorer link in the cold open is a real transaction signature. If you'd rather show stub mode (faster to record, more controllable), the cold open becomes weaker — judges trust real on-chain over staged anything.

## Production timeline (rough)

If you commit today (Saturday) to the pitch package as-is:

- **Sunday:** record cold open. Multiple takes. This will take 2-3 hours and you'll re-record after seeing playback.
- **Sunday evening:** record the founder-narrator segments (problem statement, team/ask). 1 hour.
- **Monday:** voice-over for the rest. Edit. 3-4 hours.
- **Tuesday:** review with co-founder, do one polish pass, finalize.
- **Wednesday:** record the technical walkthrough (separate video).
- **Thursday:** prepare one-pager PDF, submission form copy, slide deck if time.
- **Friday:** submit.

That's a 7-day production cycle for a 3-minute video. Not unreasonable. Most builders underestimate this and ship a rushed video on the last day.

## What changes if your demo doesn't actually work yet

The pitch script assumes the v3 implementation works end-to-end on Solana mainnet. If by Sunday the integration testing (frames.ag + ClawRouter) reveals issues, your fallback is to record the demo against **stub mode** — same flow, same documents, but no real on-chain transaction.

The cold open then loses the Solana Explorer split-screen moment. Replace it with a clearer caption: *"Stub mode shown for demo purposes. Live mode toggle is one env var. Repo includes mainnet test transactions in CHANGELOG."* Then put a real mainnet transaction signature in your video description as proof.

This is a graceful degradation, not a failure. The pitch still works; it just shifts the trust burden from "watch it happen on chain" to "trust the engineer, verify in the repo." Keep the Saturday checklist outcome in mind when deciding which version to record.

## One thing I want to flag honestly

The strongest version of this pitch requires the demo to actually work end-to-end. A pitch that promises an on-chain moment and delivers a stub is dramatically weaker than the same pitch with real flow. **Don't record the pitch until the demo is real.**

If by Tuesday the integration isn't working, the right call is *not* to ship a weaker pitch — it's to descope the pitch to what's actually true. "We've shipped V1 of the original creator-economy product. Here's our architecture for the agent-native pivot, and here's why it's the right bet." That's an honest pitch judges respect. A pitch that overpromises and a demo that under-delivers is the failure mode that loses you the prize.

## What we're betting on

The Colosseum diagnosis flagged Red Flag 3: "V1 has no proprietary technical component." This pitch's bet against that is twofold:

1. **The composition story replaces the proprietary-component story.** Not "we built a wallet" but "we composed three independent x402-native primitives into the first product that earns the rails their existence."
2. **The encoded-judgment moat replaces the technical moat.** Phase 13 of v3 (two days of prompt engineering) is what makes this real. If the prompts produce output that's measurably better than ChatGPT-with-search, the moat is real. If they don't, no pitch saves it.

This pitch is honest about both. It doesn't claim a technical moat we don't have. It claims a positioning moat we *can* defend, plus an output-quality moat we have to earn through prompt iteration in the days before submission.
