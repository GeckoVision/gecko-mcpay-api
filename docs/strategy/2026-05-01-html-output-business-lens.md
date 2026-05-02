# HTML-First Output — Business-Lens Decision Memo

**Date:** 2026-05-01
**Author:** business-manager
**Decision context:** Post-S16 (twit.sh + Bazaar buyer + arxiv landed). Founder proposing HTML verdicts and an HTML/PDF "scratch pitch deck" with a vision-model assist, no custom UI yet.
**Verdict up front:** **Recommend with one cut.** Ship HTML verdict + HTML pitch as a `--format html` flag on existing commands. **Cut the vision-model "scratch presentation" from V1.**

---

## 1. Is HTML-first the right V1 surface?

Yes — but as an **adjunct** to terminal output, not a replacement. The CLI persona (V1 ICP) lives in Claude Code. They will read the verdict in the terminal. What they will *not* do is screenshot a `rich`-formatted block to share with a co-founder, an investor, or a Discord. That's where HTML earns its keep: it's the **shareable artifact** of a non-shareable session.

Concretely, `bb research --idea "..."` should keep returning the verdict + 3 docs in the terminal (unchanged). Add `--format html` (or auto-write `~/.gecko/sessions/<id>/verdict.html`) that renders the same payload as a single self-contained file with embedded CSS and inline citations. No server, no upload — local file, openable in any browser, AirDrop-able, attachable.

The wedge proof here is *retention via shareability*, not polish. Terminal output proves the verdict is real. HTML proves the founder told someone else about it. Both signals matter; only the second is GTM.

## 2. Pricing implications

Current ladder: $0.10 basic, $0.75 pro, $9 DeFi suite, $0.50 pulse, $0.50 publish.

**HTML verdict:** **free, bundled with the existing tier.** Format is not a feature; it's a render target. Charging for HTML when the verdict is already paid creates a pricing-page line item that explains nothing and erodes trust. The seam is the verdict, not its filetype.

**HTML pitch deck (`--pitch html`):** **$1.00 flat.** Defensible reasoning:
- Gamma free tier covers most founders; paid is $10/mo. We are not competing with Gamma on polish — we are competing on *grounded synthesis from an already-paid session*. The price has to feel like rounding error against the $0.75 pro session that produced it.
- Per-page pricing is a trap. Founders won't budget against an unknown page count. Flat $1 is a yes-decision.
- $3 is the wrong number: it implies parity with a real deck tool. We don't have parity. We have a head start on slide content.

**Do not introduce a "pitch tier."** The pitch is an output of an existing session, not a session of its own. The x402 seam is `verdict_id → pitch_html` — one extra paid call against a session you already own.

## 3. GTM angle: "scratch deck for founders" — real or fluff?

Half real. The honest framing is **"a starting structure they edit, not a finished artifact."** Pick that and defend it.

Founders who would *use* an auto-deck unedited are not the founders we want — they're the ones investors flag in 30 seconds. The founders we want will rewrite every slide. What they want from us is the **frame**: the 10-slide skeleton, the right headers, the cited claims pre-positioned, the gaps marked. The verdict's KILL/REFINE/BUILD synthesis maps cleanly onto a Hook/Problem/Wedge/Evidence/Ask shape.

So the GTM line is not "we generate your pitch deck." It's "we hand you the deck outline your verdict already implies, with citations attached." That's a frame, not a finished slide. Frames travel; finished auto-decks get clowned.

## 4. What V2 buys that V1 HTML doesn't

V1 HTML is a local file. It cannot:
- Show progress while a session runs (non-technical founder persona unlock)
- Persist a shareable URL behind auth (`gecko.sh/v/<id>`)
- Surface session history without `bb sources`
- Embed a Privy wallet for non-CC-literate buyers

The trigger to greenlight the real web UI is **not vibes**. Concrete gate:

> **Build V2 when EITHER (a) 10 paying non-stub sessions land via Bazaar buyer flows post-S16, OR (b) first inbound from a fund / accelerator asks "where do I see the deck."**

Until one of those fires, HTML local files are sufficient and cheaper to maintain. The fund-inbound trigger matters more than the volume trigger — investors won't `cat verdict.html`.

## 5. The cut

**Cut: vision-model "scratch presentation" generation in V1.**

The trap is that vision models for slide *layout* are slow, expensive, non-deterministic, and the output looks 80% like every other AI-generated deck. We'd be paying inference cost to compete with Gamma on its strongest axis (visual polish) using our weakest tool (a vision model called from a CLI). The founder is excited about it because it's the demo-able part — and that's exactly why it's a trap. It optimises for the pitch of Gecko, not the product of Gecko.

Ship HTML pitch as **templated layout + verdict-grounded content**. Same Tailwind-ish CSS skeleton every time. Founders fork it. If V2 ships and a fund asks for "make it pretty," revisit vision models then with real demand signal.

---

**Recommendation:** Ship `--format html` (free, bundled) and `--pitch html` ($1 flat, templated). Cut vision-model slide generation from V1. Re-evaluate visual polish at V2 trigger (10 Bazaar-flow paying sessions OR first fund inbound).
