# Gecko Pitch — Figma Handoff Brief

> Companion to **`Gecko Narrative Pitch.html`** (10 slides, 1920×1080).
> Use this to rebuild the deck in Figma with proper variables, components, and edit-ability.

---

## 0 · Setup before you start

**Frame size:** 1920 × 1080 (one frame per slide, named `01_Thesis` … `10_Ask`).

**Pages in Figma:**
1. `Cover` — the deck itself
2. `Components` — Logo, Tag, SlideHeader, SlideFooter, PhotoCard, VerdictCard
3. `Tokens` — local variables (see §1)
4. `Persona` — Caio reference photo / mood

**Plugins worth installing first:**
- **html.to.design** — paste a public URL of the HTML file, get editable Figma layers as a starting point. (Cuts rebuild time by ~70%.)
- **Variables Import** — if you'd rather paste the JSON below than click through the Variables panel.

---

## 1 · Design tokens (Figma Variables)

Create a single collection `Gecko Brand` with one default mode.

### Colors
| Variable | Value | Use |
|---|---|---|
| `bg/dark` | `#0E1420` | Slides 01, 03, 05, 07, 09, 10 |
| `bg/light` | `#F1F3F7` | Slides 02, 04, 06, 08 |
| `surface/white` | `#FFFFFF` | Cards on light slides |
| `surface/dark-alt` | `#161C2A` | Subtle panels on dark |
| `accent/blue` | `#1E56F5` | Primary accent (headlines, dividers, CTAs) |
| `accent/pale-blue` | `#B8C7F9` | Footer/header rail on dark slides |
| `text/white` | `#FFFFFF` | Body on dark |
| `text/ink` | `#0A0B10` | Body on light |
| `text/muted` | `#60636B` | Secondary copy |
| `status/green` | `#14D98A` | Reserved for "GO" verdicts |
| `status/red` | `#F45B5B` | Reserved for "KILL" verdicts |

### Typography
| Variable | Family | Weights | Use |
|---|---|---|---|
| `font/display` | **Archivo Black** | 900 | Headlines (uppercase, slab) |
| `font/body` | **Inter** | 400 / 500 / 700 | Body, captions |
| `font/mono` | **JetBrains Mono** | 400 / 500 | Tags, hashes, technical |

### Type scale (text styles)
- `Hero / 140` — only the cover thesis
- `Title / 84` — slide titles
- `Subtitle / 44` — secondary headers
- `Body Lg / 28` — primary body
- `Body / 22` — secondary body
- `Mono / 22` — tags, labels, code
- `Tag / 18` — small uppercase labels

All display/title styles: line-height **0.98**, tracking **-0.015em**, **uppercase**, **balance** wrap.

### Spacing
- Frame padding: **110px** left/right, **54px** top (header rail), **50px** bottom (footer)
- Section title gap: **52px** below header rail
- Card grid gap: **22px**

---

## 2 · Components to build (in this order)

### 2.1 `GeckoMark` (logo glyph)
- 40×40 SVG: 5 dots arranged like a + with center dot, connecting strokes (`accent/blue`, 2.2px).
- Center dot r=5.5, outer dots r=3.5.
- Variants: `light` / `dark` (just toggles surrounding text color, mark itself stays blue).

### 2.2 `Tag` (the workhorse)
- Auto-layout, padding `8px 14px`, gap 0.
- Variants:
  - **black** → bg `text/ink`, text `text/white` (default on light slides)
  - **blue** → bg `accent/blue`, text `text/white` (used for the "live"/"now" emphasis)
- Text style: `Mono / 22`, **uppercase**, tracking `0.08em`.

### 2.3 `SlideHeader`
- Top of every content slide (slides 02–10).
- 3 elements in a horizontal auto-layout: `SECTION LABEL` — long hairline — `02` (page number).
- Color: `accent/blue` on light, `accent/pale-blue` on dark.
- Hairline: 1px, 35% opacity of the header color.

### 2.4 `SlideFooter`
- `GeckoLogo` bottom-left, `PITCHDECK — 2026` bottom-right (Mono / 22, uppercase, 0.12em).

### 2.5 `PhotoCard` (Caio's portrait, slide 02)
- Outer wrapper 420×560.
- A blue rectangle (`accent/blue`) offset behind by `+30px right / +30px down`.
- Foreground: image fill, `grayscale(100%)` filter. Stripe placeholder until real photo lands.
- Caption tag below in `Mono / 18`.

### 2.6 `VerdictCard` (slide 06)
- 480×280, `surface/white` bg, **2px** border in `accent/blue`.
- Top label: `VERDICT · SIGNED` (Mono / 16, blue, tracking 0.12em).
- Body: huge **REFINE** in display font (84px, blue).
- Below: hash in mono, then a divider, then `5 / 5 VOICES` ↔ `$0.0107`.

---

## 3 · Slide-by-slide build notes

| # | Slide | Background | Key visual | Notes |
|---|---|---|---|---|
| 01 | Thesis | `bg/dark` | Two-line slab title: "CAPABILITY IS COMMODITIZED. JUDGMENT IS SCARCE." | The word `JUDGMENT` is `accent/blue`. `COMMODITIZED` is white at 35% opacity. Subtitle in mono pale-blue: "Bazaar makes capability tradeable. Gecko makes judgment tradeable." |
| 02 | Caio (persona) | `bg/light` | `PhotoCard` right side, 3-row data table left | The data table is **3 rows of `Mono label / body text`** separated by hairlines (12% black). Quote under photo in display font: "AM I BUILDING **THE WRONG THING** AGAIN?" |
| 03 | Dark Room | `bg/dark` | Big slab + 3-stat strip at the bottom | Stats: `90%` / `20H` / `$0`. Hairlines top + bottom of the strip in pale-blue 25%. |
| 04 | The Shift | `bg/light` | Two-column compare: BEFORE (white card) / AFTER (dark card) with `→` arrow | Before card uses muted color throughout; after card matches `bg/dark`. The `→` is 64px in display font, `accent/blue`. |
| 05 | Product | `bg/dark` | 3-card grid: gecko_classify / gecko_research / gecko_ask | Cards: `accent/blue` 8% bg, pale-blue 25% border, `Mono` headline, latency stat below. |
| 06 | Evidence | `bg/light` | Title + `VerdictCard` right + 3 disagreement cards bottom | The disagreement block is the **single most important visual** in the deck. Three cards labeled CEO / PM / CTO with a 3px blue accent bar on the left. |
| 07 | Why Now | `bg/dark` | 3-card row: AGENT-MEDIATED / MICRO-COST / COMPOSABLE | Same card style as slide 05. Headline picks up `accent/blue` on second line. |
| 08 | Moat | `bg/light` | 3 horizontal "feature rows" stacked | Each row: `01` index (mono blue) / title (display 28) / description (body 20 muted). Left border accent. |
| 09 | Status | `bg/dark` | Two columns: shipping list (left) / V1·V1.5·V2 stack (right) | Shipping rows: text + Tag (LIVE = blue, POST-PILOT = black). V-blocks have left border + tinted bg. |
| 10 | Ask | `bg/dark` | Title + 3 budget rows + founders block + closing line | Closing line at bottom: "THE NEXT FOUNDER **DOESN'T HAVE TO BUILD IN THE DARK.**" (display 30, blue emphasis). |

---

## 4 · Narrative arc (cheat sheet for live presentation)

**Act 1 — The thesis (slide 01):** state the macro idea. *Capability is commoditized. Judgment is scarce. Bazaar made the first tradeable; we make the second.*

**Act 2 — The persona (slides 02–03):** Caio is the audience-mirror. He's three projects deep, no senior to ping, ChatGPT just agrees with him. Six months and zero users is the cost of building without judgment.

**Act 3 — The shift (slides 04–05):** instead of asking one yes-man, you convene a panel. Five voices, one verdict, cited dissent. Three API calls, a reproducible hash, a 90-day session.

**Act 4 — The proof (slides 06–08):** we ran Gecko on Gecko. It told us to REFINE. The CEO and CTO disagreed publicly — that's the product. Why now: agent-native settlement makes the unit economics work. Why us: encoded judgment, sessions as assets, dogfood at proof scale.

**Act 5 — The ask (slides 09–10):** devnet live, pilots running, $250K to mainnet + 50 founders. Close on the persona: the next founder doesn't have to build in the dark.

---

## 5 · Importing the HTML into Figma (fastest path)

1. In your dev environment, host `Gecko Narrative Pitch.html` at a public URL (Vercel preview, GitHub Pages, or any static host).
2. In Figma → **Plugins → html.to.design → Import URL**.
3. Paste the URL. Set viewport to **1920 × 1080**.
4. The plugin renders each `<section data-screen-label="…">` as a Figma frame.
5. Rename frames to match § "Setup" naming.
6. **Now retrofit your local variables onto the imported layers** — html.to.design imports raw colors, not variables. Use the Variables panel + select-similar to bind:
   - All `#1E56F5` → `accent/blue`
   - All `#0E1420` → `bg/dark`
   - … etc.

## 6 · Things to flag for designer review

1. **Real photo of Caio.** Right now slide 02 uses a striped placeholder. Either commission a portrait (gritty, dim-lit, 3am-builder energy) or use a stock image with the grayscale + blue offset treatment from `PhotoCard`.
2. **Verdict pill states.** Add `GO` (green) and `KILL` (red) variants of `VerdictCard` so we can swap on-stage if a panel question comes up.
3. **The disagreement card on slide 06.** This is the single asset I'd push hardest in user testing — try a "transcript-style" version too (CEO speech bubble pointing at PM speech bubble) as a v2.
4. **Slide 04 arrow.** Currently a typographic `→`. Consider a custom motion-blurred arrow asset that picks up the glitch-square motif from the v1 deck.
5. **Cover slide.** Optionally add the glitch-square cluster (`GlitchSquares` from common.jsx) bottom-right for visual noise — currently clean.

---

**Source HTML:** `Gecko Narrative Pitch.html`
**Components:** `components/common.jsx`, `components/narrative-slides.jsx`
**Print-to-PDF:** open the deck and print — `deck-stage` handles one-page-per-slide.
