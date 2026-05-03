# gecko_research — Output Shape (Demo, 2026-05-02)

**Owner:** product-designer
**Status:** Spec for the demo this week. Implementation by `software-engineer` against `apps/cli/src/gecko_cli/render.py`.
**Mode:** `X402_MODE=stub`. Tavily + OpenAI live. Retrieval, debate, and citations are real.
**Surface:** MCP tool `gecko_research` invoked inside Claude Code; output streams to the user's terminal via Rich.

---

## 1. Why this shape, not the legacy three-panel reveal

The Sprint 7 reveal (Business Plan / Validation Report / PRD as three Panels) was the right shape when the JTBD was "give me documents." The demo JTBD has shifted: the user has a pre-idea and wants a **verdict they can act on** — build / pitch / submit. Three documents bury the lede.

The new shape leads with the verdict, surfaces multi-voice dissent as the differentiator (Perplexity collapses dissent; we headline it), and closes with falsifiers that make the verdict tradeable (per `tradeable-judgment-surface.md`). The legacy three documents remain reachable behind the paywall hint in the footer (`x402://verdict/<hash>?detail=full`).

The voice section is intentionally structured so that when S21 ships program-bound judges (per `program-judges-wedge.md`), the line `▸ Biz Manager:` becomes `▸ Kuka — Market (Superteam BR):` with no layout change. The `lens` field of a judge config maps 1:1 to our current voice slots.

---

## 2. Section-by-section layout

Total target: **2-3 screenfuls at 80 cols**. Header + Voices + Summary lands in screen 1 (the punchline preview). Landscape + Dissent in screen 2. Next Steps + Footer in screen 3 (the actionable close).

### 2.1 Header — verdict + idea recap

```
╭─ Gecko Verdict ──────────────────────────────────────────────────────────────╮
│  GO   verdict@a4f10c2b9e3d                                                   │
│  Idea: Stablecoin payouts API for LATAM gig platforms.                       │
╰──────────────────────────────────────────────────────────────────────────────╯
```

- Verdict label color: `GO`=green, `REFINE`=yellow, `PIVOT`=red, `KILL`=bright_red.
- Verdict label is **bold + reverse** so it reads as a stamp, not a word.
- `verdict@<12hex>` is the first 12 chars of `ResearchResult.verdict_hash`. Dim cyan, monospace. This is the tradeable handle — it's deliberately visible from line 1.
- Idea recap is one line, truncated at 76 chars with ellipsis. No wrap.

**Different from Perplexity/ChatGPT:** they answer in prose. We stamp a single token + a hash. The hash is a primary key for a verdict, not a session ID.
**Complementary to solana.new `validate-idea`:** solana.new is a single-voice validator inside the community stack; our 5-voice debate produces a tradeable verdict hash — adjacent layer, not replacement.

### 2.2 Per-Voice Readout — 5 voices, 3 lines each, never collapsed

```
▸ Voices

  ▸ Biz Manager
    Position: LATAM gig payouts is a real wedge — Mercado Pago skips USD rails.
    Tension:  Pushed back on "API-first" — gig platforms want a dashboard, not SDK.
    Recommend: Ship a hosted payout console first, expose API in V2.

  ▸ Web3 Engineer
    Position: USDC on Solana settles in <1s for ~$0.0003 — the rails are ready.
    Tension:  Off-ramp to BRL is the real bottleneck; on-chain is the easy half.
    Recommend: Partner with one local off-ramp (e.g. Transfero) before building.

  ▸ AI/ML Engineer
    Position: No model surface here — this is a payments product, not an AI one.
    Tension:  Resisted shoe-horning fraud-ML; called it premature optimisation.
    Recommend: Defer ML to V3; rule-based velocity checks cover V1 fraud.

  ▸ Product Designer
    Position: Recipient UX is the moat — most LATAM rails leak at receive-side.
    Tension:  Dissent on attribution: payout receipts must show platform, not Gecko.
    Recommend: White-label receipt page with platform brand, Gecko in fine print.

  ▸ Staff Engineer
    Position: Architecturally clean — stateless API, idempotency keys, webhooks.
    Tension:  Worried about regulatory drift across BR/MX/AR; suggested geo-flag.
    Recommend: Launch BR-only; gate other geos on local counsel sign-off.
```

- `▸` markers are bright_green; voice names are bold cyan.
- Field labels (`Position:`, `Tension:`, `Recommend:`) dim; values default color.
- Three lines, fixed order, never collapsed. If a voice has no tension, the prompt is broken — we still render `Tension: (no pushback this round)` in dim italic so the gap is visible, not hidden.
- Voice order is fixed (Biz, Web3, AI/ML, PD, Staff). Order ≠ weight; this is just the narrative arc — market → tech → model → human → architecture.

**Different from Perplexity/ChatGPT:** they synthesize voices into one answer. We refuse to. The user sees five disagreements before they see consensus.
**Future-compatible with S21:** when judges arrive, replace `Biz Manager` with `<Judge Name> — <lens> (<program>)`. Layout is identical.

### 2.3 Transcript Summary — 4 lines, plain prose

```
▸ Transcript

  Biz pushed for a hosted console framing; Web3 countered that on-chain is solved
  and the off-ramp is the real bottleneck. The panel converged on BR-first launch
  with a single off-ramp partner. PD's dissent on attribution survived: the
  payout receipt must brand the platform, not Gecko.
```

- Plain text, no bullets. Reads like a meeting recap a chief of staff would write.
- Always names which dissent **survived** — links forward to §2.5.
- 4 lines max. Wraps at 76. If the synthesizer can't summarise in 4, we truncate; we don't grow.


### 2.4 Market Landscape — Rich Table, 3-5 competitors

```
▸ Landscape

  ┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
  ┃ Competitor     ┃ Their thing                 ┃ Why we're different       ┃
  ┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
  │ Mercado Pago   │ BRL payouts, no USD rails   │ We settle USD on-chain    │
  │ Wise           │ Cross-border for SMBs       │ We're API-first for gigs  │
  │ Transfero      │ BR off-ramp, no payout API  │ We're the layer above     │
  │ Bitso Business │ MX/AR, weak BR coverage     │ We're BR-first            │
  └────────────────┴─────────────────────────────┴───────────────────────────┘
```

- Table widths: 16 / 30 / 28 (sums to 74 + borders → fits 80 cols).
- "Why we're different" is the **wedge sentence per competitor** — every cell here is load-bearing for the pitch deck.
- 3-5 rows. Fewer than 3 = retrieval too thin (note in §6 open questions).

**Different from Perplexity:** they list competitors. We force a wedge sentence per competitor. The cell can't be empty; if the model can't fill it, the wedge isn't real.

### 2.5 Surviving Dissent — verbatim, attributed, yellow

```
▸ Surviving Dissent                                                          [!]

  ┃ "If the payout receipt shows Gecko's brand, we eat the platform's user
  ┃  trust. Attribution must default to the platform; Gecko is fine print."
  ┃     — Product Designer

  ┃ "BR-only sounds safe but cedes MX to Bitso for 18 months. I'd ship MX
  ┃  in V1.5 with a regulatory escape hatch."
  ┃     — Staff Engineer  (minority)
```

- `[!]` marker is yellow.
- Quotes use a left rule (`┃` in yellow) — visually distinct from the green `▸` voice readout.
- Attribution line dim; `(minority)` tag in dim italic when only one voice held the position.
- **Mandatory section.** If `surviving_dissent` is empty, we render:

  ```
  ▸ Surviving Dissent                                                          [!]

    No dissent survived this debate. Either consensus was real, or the
    orchestration is collapsing voices — flag for ai-ml-engineer review.
  ```

  This is a deliberate self-incrimination surface. Per CLAUDE.md Pattern D, dissent is the wedge; if it disappears, we say so out loud rather than pretend.

**Different from Perplexity/ChatGPT:** they produce one answer. They cannot show you what they argued against. We can.

### 2.6 Next Steps — numbered, ≤5, with falsifiers

```
▸ Next Steps

  1. Sign LOI with Transfero for BR off-ramp partnership.
     Surfaced by: Web3 Engineer
     Falsifier:   No signed LOI by 2026-05-23 → off-ramp risk is real, replan.

  2. Prototype hosted payout console (no API yet) with one design-partner gig
     platform.
     Surfaced by: Biz Manager, Product Designer
     Falsifier:   No design partner active by 2026-05-30 → demand is push, not pull.

  3. White-label receipt page; platform brand primary, Gecko in fine print.
     Surfaced by: Product Designer
     Falsifier:   Platform rejects white-label terms → attribution model is wrong.

  4. Geo-gate to BR only; document MX/AR gating rule.
     Surfaced by: Staff Engineer
     Falsifier:   BR regulator issues guidance against stablecoin payouts by
                  2026-06-15 → pivot geo or rails.

  5. Defer fraud-ML to V3; ship rule-based velocity checks.
     Surfaced by: AI/ML Engineer
     Falsifier:   First 100 payouts show >2% fraud → rule-based is insufficient.
```

- Numbered list, max 5. Each step: action, attribution, falsifier.
- **Attribution proves multi-voice was load-bearing.** If every step is "Surfaced by: Biz Manager", the debate didn't happen.
- **Falsifier makes the verdict tradeable** (per `tradeable-judgment-surface.md`). A verdict without a falsifier is an opinion. A verdict with a falsifier is a contract.
- Falsifier dates are concrete (e.g. `2026-05-23`), not relative ("in three weeks").
- Action is plain imperative; no hedging verbs (no "consider", "explore"). If the model emits hedge verbs, we strip them in post-processing.

**What's distinctive:** Perplexity gives bullets, ChatGPT gives a roadmap, solana.new (complementary, in the community stack) closes on a CTA. Gecko's added layer is the falsifier — the conditions under which we'll be wrong.

### 2.7 Footer — tier, cost, hash, paywall hint

```
─────────────────────────────────────────────────────────────────────────────
  basic · session $0.04 · verdict@a4f10c2b9e3d
  Full transcript: x402://verdict/a4f10c2b9e3d (paywalled)
  Next: gecko_advise --hash a4f10c2b9e3d  to debate this verdict further.
```

- Dim gray, single rule above.
- `tier` is `basic` or `pro`. No model names. No token counts. **Session price is the unit.**
- `verdict@<12hex>` repeats so it's grep-able from the bottom.
- Paywall hint is the call-to-pay; explicitly marked `(paywalled)` so users aren't surprised.
- `Next:` line is the chained-skill CTA — equivalent of solana.new's `claude "/find-next-crypto-idea"`. Points to `gecko_advise` (the next skill).

**Future surface (NOT in V1):** the `verdict@<hash>` becomes a "Verdict Receipt" — a tradeable on-chain artifact. Mentioned here so `web3-engineer` knows the hash is the anchor; not rendered in the demo.

---

## 3. Rich rendering pseudocode

Reuses the Console + style conventions already in `apps/cli/src/gecko_cli/render.py`. New helpers live in the same module. Pseudocode only — `software-engineer` writes the actual code.

```python
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.rule import Rule
from rich.text import Text
from rich.padding import Padding

VERDICT_STYLES = {
    Verdict.GO:     "bold reverse green",
    Verdict.REFINE: "bold reverse yellow",
    Verdict.PIVOT:  "bold reverse red",
    Verdict.KILL:   "bold reverse bright_red",
}

def render_research(result: ResearchResult, console: Console) -> None:
    console.print(_header(result))
    console.print(_voices(result))
    console.print(_transcript(result))
    console.print(_landscape(result))
    console.print(_dissent(result))
    console.print(_next_steps(result))
    console.print(_footer(result))


def _header(r: ResearchResult) -> Panel:
    label = Text(f" {r.verdict.value} ", style=VERDICT_STYLES[r.verdict])
    hash12 = Text(f"verdict@{r.verdict_hash[:12]}", style="dim cyan")
    idea   = Text(f"Idea: {_truncate(r.idea, 76)}")
    body   = Group(Text.assemble(label, "  ", hash12), idea)
    return Panel(body, title="Gecko Verdict", border_style="cyan", width=80)


def _voices(r: ResearchResult) -> Group:
    items = [Text("▸ Voices", style="bold cyan")]
    for v in r.voices:  # ordered: biz, web3, aiml, pd, staff
        items.append(Padding(Group(
            Text.assemble(("▸ ", "bright_green"), (v.name, "bold cyan")),
            Text.assemble(("    Position:  ", "dim"), v.position),
            Text.assemble(("    Tension:   ", "dim"), v.tension or "(no pushback this round)"),
            Text.assemble(("    Recommend: ", "dim"), v.recommendation),
        ), (0, 0, 1, 0)))
    return Group(*items)


def _transcript(r: ResearchResult) -> Group:
    return Group(
        Text("▸ Transcript", style="bold cyan"),
        Padding(Text(r.transcript_summary), (0, 0, 1, 2)),
    )


def _landscape(r: ResearchResult) -> Group:
    t = Table(show_header=True, header_style="bold cyan", border_style="dim")
    t.add_column("Competitor", width=16)
    t.add_column("Their thing", width=30)
    t.add_column("Why we're different", width=28)
    for c in r.landscape[:5]:
        t.add_row(c.name, c.their_thing, c.our_wedge)
    return Group(Text("▸ Landscape", style="bold cyan"), Padding(t, (0, 0, 1, 2)))


def _dissent(r: ResearchResult) -> Group:
    header = Text.assemble(("▸ Surviving Dissent", "bold cyan"),
                           ("                                                          [!]", "yellow"))
    if not r.surviving_dissent:
        body = Text(
            "No dissent survived this debate. Either consensus was real, or the\n"
            "orchestration is collapsing voices — flag for ai-ml-engineer review.",
            style="yellow",
        )
        return Group(header, Padding(body, (0, 0, 1, 2)))
    blocks = []
    for d in r.surviving_dissent:
        quote = Text(f"┃ \"{d.quote}\"", style="yellow")
        attr  = Text(f"┃    — {d.voice}{' (minority)' if d.minority else ''}", style="dim")
        blocks.append(Group(quote, attr, Text("")))
    return Group(header, Padding(Group(*blocks), (0, 0, 1, 2)))


def _next_steps(r: ResearchResult) -> Group:
    items = [Text("▸ Next Steps", style="bold cyan")]
    for i, s in enumerate(r.next_steps[:5], start=1):
        items.append(Padding(Group(
            Text.assemble((f"  {i}. ", "bold"), s.action),
            Text.assemble(("     Surfaced by: ", "dim"), ", ".join(s.surfaced_by)),
            Text.assemble(("     Falsifier:   ", "dim yellow"), s.falsifier),
        ), (0, 0, 1, 0)))
    return Group(*items)


def _footer(r: ResearchResult) -> Group:
    return Group(
        Rule(style="dim"),
        Text(f"  {r.tier} · session ${r.session_cost_usd:.2f} · verdict@{r.verdict_hash[:12]}", style="dim"),
        Text(f"  Full transcript: x402://verdict/{r.verdict_hash[:12]} (paywalled)", style="dim"),
        Text(f"  Next: gecko_advise --hash {r.verdict_hash[:12]}  to debate this verdict further.", style="dim"),
    )
```

Width handling: every Panel and Table is pinned to widths that sum to ≤ 78 + borders so 80-col terminals don't wrap mid-cell. At 120 / 200 cols we let prose reflow but keep the table fixed (wider tables would dilute scannability).

---

## 4. Data shape this assumes (request to ai-ml-engineer)

The current `ResearchResult` carries `business_plan`, `validation_report`, `prd`, `transcript`, `verdict`, `verdict_hash`, `provider_mix_flag`. It does **not** yet carry the structured fields this layout consumes:

- `voices: list[VoiceReadout]` with `name`, `position`, `tension`, `recommendation`
- `transcript_summary: str` (4-line prose, distinct from raw `transcript` dict)
- `landscape: list[Competitor]` with `name`, `their_thing`, `our_wedge`
- `surviving_dissent: list[Dissent]` with `quote`, `voice`, `minority: bool`
- `next_steps: list[Step]` with `action`, `surfaced_by: list[str]`, `falsifier`
- `idea: str` (the recap line — currently lives only in the session row)
- `session_cost_usd: float`

These fields can be derived from the existing pro-tier transcript by the synthesizer; basic tier needs a degraded path (single voice → all five "voices" are facets of one model with explicit `(no pushback this round)` tensions). `ai-ml-engineer` owns the synthesizer prompts; `data-engineer` owns persisting the new fields. I recommend adding them to `ResearchResult` rather than stuffing into `transcript: dict` — strong typing here is what lets the renderer be dumb.

---

## 5. Open questions (need ai-ml-engineer)

1. **Falsifier date generation.** Does the synthesizer pick the date, or does the renderer compute `today + N days` from a relative hint? If model picks, how do we keep dates realistic and not all clustered at "+30 days"?
2. **Basic-tier degraded voices.** When there's no debate, do we fake five voices (bad — theatre) or render one voice + a note "upgrade to pro for the 5-agent panel"? My vote: the latter, with the dissent and voices sections collapsed into a "Single-pass analysis" block. Needs your call.
3. **Dissent extraction reliability.** Do we have a prompt that reliably extracts *surviving* dissent (positions held to end of debate) vs *raised-then-conceded* dissent? Today's transcript has both; we only want surviving.
4. **Attribution multi-voice on Next Steps.** Can the synthesizer reliably attribute a step to multiple voices when the recommendation co-emerged? Or is it always single-voice attribution?
5. **Landscape minimum.** What do we render when retrieval returns <3 competitors? Synthesise generic ones (bad), surface a "thin retrieval" warning (better), or block the verdict (best but harsh)?
6. **Verdict-hash stability across reruns.** Per `provider_mix_flag` exclusion in `_verdict_payload`, the hash is reproducible. Do we want to surface "this is the same verdict you got 2 days ago" detection? Out of scope for demo, worth a note.
7. **KILL rendering.** When verdict is KILL (incoherent premise), does the Next Steps section even make sense? Probably degrades to "Steps to falsify the premise" — different framing entirely. Flagging for your read.

---

## 6. What this spec deliberately does NOT include

- No three-document reveal (Business Plan / Validation Report / PRD). Those are reachable behind the paywall hint; the demo is the verdict surface.
- No source-list footer. Citations are inline-implicit via the landscape table; the full numbered source list lives behind `?detail=full`.
- No emojis. (CLAUDE.md / product-designer rules.)
- No model names, token counts, or per-operation costs. (CLAUDE.md security non-negotiable.)
- No "Verdict Receipt" trading artifact. Future surface; the `verdict@<hash>` is the seed.
- No program-judge naming. S21 wedge; layout is forward-compatible but V1 ships generic voices.

---

**Files referenced:**
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/apps/cli/src/gecko_cli/render.py` (existing Rich patterns to reuse)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/packages/gecko-core/src/gecko_core/models.py` (`ResearchResult`, `Verdict`, `verdict_hash`)
- `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/docs/strategy/program-judges-wedge.md` (forward-compat target for §2.2)
