# HTML Output — Design Lens

**Date:** 2026-05-01
**Author:** product-designer
**Decision frame:** founder proposes shipping `bb research` outputs as HTML (and a `--pitch html` scratch deck). Ship / cut / defer?

## 1. IA for the HTML verdict — order matters

1. **Verdict badge (above fold).** `KILL / REFINE / BUILD` as the largest element, with the one-line "why" beneath. No prelude. The user paid; the answer leads.
2. **Confidence + dissent strip.** A single row showing confidence band (bucketed, not raw) plus the loudest advisor dissent quote. Trust comes from showing the disagreement, not hiding it.
3. **Idea + ICP recap.** Two lines. So a shared link is self-contained without scrolling up.
4. **Bull / Bear two-column.** Side-by-side, equal weight. Citation superscripts inline.
5. **Market signal + competitor table.** Numbers with source links. No raw TAM hand-waves without a citation.
6. **Risks → next moves.** Risk flags from the validation report, each paired with a concrete next action. This is where REFINE earns its keep.
7. **Sources (numbered, scannable).** URL, title, provider, captured-at. The trust ledger.
8. **Footer:** session id, phase, parent session if pulse, x402 receipt hash. Metadata in dim tone.

Rationale: verdict-first because the user already sat through 20 minutes of indexing — context-first would feel like padding. Citations live inline AND as a footer list because founders share both ways (skimmers want anchors, skeptics want the full ledger).

## 2. Single artifact vs. multi-page

**One HTML file, long-scroll, with a sticky in-page nav (Verdict / Plan / PRD).** Not three files. Not tabs.

- Founders share via DM/Notion — one file, one link wins. Three files = "which one do I send the investor."
- Tabs hide content. The PRD is the most-skipped section; if it's behind a tab it's invisible. Sticky nav lets skim-readers jump but keeps the artifact whole.
- Long-scroll renders cleanly as PDF via headless print. Tabs don't.

## 3. `--pitch html` — what shape

**Narrative, not slides. 5 anchored sections in a single scrolling page** styled like a Stripe/Linear marketing page, not PowerPoint. Sections: Problem → Insight → Solution → Why-now → Ask.

Reasoning: we don't have the data to fill 12 slides without padding. A 12-slide deck from `gpt-4o-mini` will read as filler; a 5-section narrative reads as intentional. Founders will paste this into a real deck themselves — our job is to give them the *argument*, not the chrome. Call the flag `--pitch narrative` if we want to lean into this and avoid the deck-shaped expectation.

If the founder insists on slide-shaped output, defer to V2 once we have the verdict-quality bar to justify it.

## 4. Render layer vs. data layer

**HTML is a render of the verdict JSON. Verdict JSON stays canonical.** Non-negotiable.

- Verdict JSON already persists to DB (S14) and is the artifact published to publish.new at $0.50. Re-rendering it as HTML on demand keeps publish.new buyers consuming the structured form.
- HTML embeds the JSON as `<script type="application/ld+json">` so a buyer's agent can re-parse without scraping.
- Pulse (S14) re-renders against the same JSON shape — render layer must stay cheap to swap. If HTML becomes canonical we'll be stuck regenerating prose every time the validation prompt changes.

## 5. Vision-model visuals — where it's real, where it's slop

**Real value:**
- **Competitive landscape 2x2** (price × focus, or generalist × vertical). Vision model places ~6 competitors on axes the verdict already named. Template can't, because axes are idea-specific.
- **Bull/bear flow arrows** showing which risks compound into which outcomes. Idea-specific causal sketch, not a generic chart.

**Slop, do not ship:**
- Persona portraits. Generic stock-style faces add nothing and read as cheap.
- TAM bar charts. A `<table>` is more honest. Bar charts imply precision we don't have.
- Logo collages of "competitors." Trademark hazard, no information density.
- Hero illustrations. The product is the verdict; decoration dilutes it.

Rule: vision visuals only where the *content is idea-specific* and a template literally cannot encode it. Otherwise it's slop.

## 6. Will founders actually open the HTML?

Honestly: **about half**, on first run. Most will read the Rich terminal output and move on — Claude Code users live in the terminal. The HTML pays off in two specific moments: (a) when they share the link with a co-founder or investor, and (b) when they revisit the session a week later. So the HTML's job is **shareability and persistence**, not the primary read. Design accordingly: optimize for the paste-into-Slack moment, not the first render. Print a single line at the end of `bb research`: `Shareable verdict: file://… (also: gecko publish to mint at $0.50)`.

## 7. The one UX fail mode to avoid

**Generic "AI report" styling.** Default fonts, full-width prose blocks, gradient hero, lorem-ipsum-shaped sections. The moment it looks like every other GPT-wrapper output, the verdict reads as cheap regardless of content quality. Defense: tight typographic system (one serif for headings, one mono for metadata, no gradients), citations as first-class visual elements not footnote-grey, and the verdict badge as the only "loud" element on the page. If it looks like a Stripe receipt crossed with an academic abstract, we win. If it looks like a Notion AI export, we lose.

## Recommendation

**SHIP** the HTML render of the verdict (one file, long-scroll, JSON-embedded) in the next slice. It is a thin renderer over data we already persist; the marginal cost is low and the share-surface payoff is real.

**DEFER to V2** the `--pitch html` scratch deck. The verdict-quality bar isn't high enough yet for a generated deck to not read as slop, and the narrative-vs-slides question deserves a real design pass once S16 chunking reliability lands. Ship a `--pitch narrative` markdown stub instead if founder wants something this slice — markdown is honest about being a draft.

**CUT** vision-model visuals from this slice entirely. Add the competitive 2x2 only after we've shipped HTML and seen which sections founders actually share. Premature visual generation is the fastest path to the slop fail mode in §7.
