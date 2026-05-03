# Program-Judge Panels — The S21 Wedge

**Date:** 2026-05-02
**Author:** ernani
**Status:** Strategy / forward-look. Not in V1 demo. Not blocking S20 release.
**Related:** `docs/PRD.md`, `docs/product-story.md`, `docs/strategy/tradeable-judgment-surface.md`

---

## 1. The wedge claim

The current 5-voice advisor panel (Biz / Web3 / AI-ML / PD / Staff) is a **generic** debate. Generic debate is fakeable: a sufficiently prompted Perplexity or ChatGPT can stand up five plausible personas and produce a verdict that *looks* like ours. The S21 wedge is to replace generic personas with **program-specific judge panels** — voices that mirror the real selection committees of real accelerators, grants, and hackathons. A builder applying to Superteam Brasil's hackathon picks "evaluate me as Superteam Brasil would," and the panel runs in the voices of Kuka (market), Kaue (technical viability), Shimas (founder-market fit), each using that judge's published criteria. The verdict is no longer "five LLM personas argued"; it is "the actual room you're walking into argued, before you walked in."

## 2. Why this beats orchestration-as-table-stakes

CLAUDE.md Pattern D: orchestration is table stakes; the wedge is rarely orchestration. A generic five-voice debate is orchestration. A *named, program-bound* five-voice debate is **distribution + curation**, which Perplexity and ChatGPT structurally cannot ship:

- **Public criteria + curation.** Even where judge criteria are public, assembling them into faithful voice configs is editorial work. We do it once per program; competitors would have to do it per-program *and* keep it current.
- **Partnerships are the moat layer.** Programs that opt in get a distribution channel; builders converge on whichever tool matches the program they are applying to. This is a B2B2C flywheel, not a model capability.
- **Tradeable judgment compounds.** Per `tradeable-judgment-surface.md`, a verdict's market value scales with the credibility of the judges signing it. A verdict scored by *named program judges* clears at a higher price than one scored by anonymous LLM personas. The same debate engine, wrapped in named judges, is a different product.

The implication: orchestration quality is necessary but not sufficient. The defensible asset is the **roster of program-bound judge configs** and the **ingestion path** that lets programs self-publish into it.

## 3. Judge-persona schema sketch

Not implementation — shape only. A judge config is the unit of curation:

```jsonc
{
  "program_id": "superteam-brasil-hackathon-2026q2",
  "program_display": "Superteam Brasil Hackathon",
  "region": "BR",
  "ecosystem": "solana",
  "judges": [
    {
      "judge_id": "kuka",
      "display_name": "Kuka",
      "lens": "market",
      "criteria": [
        "TAM defensibility in LATAM",
        "GTM realism for crypto-native builders",
        "evidence of pull, not push"
      ],
      "voice_prompt_ref": "voices/superteam-br/kuka.md",
      "weight": 0.34
    },
    { "judge_id": "kaue", "lens": "technical", "weight": 0.33, "...": "..." },
    { "judge_id": "shimas", "lens": "founder-market-fit", "weight": 0.33, "...": "..." }
  ],
  "decision_rule": "weighted_majority_with_dissent",
  "attribution": {
    "judge_approved": true,
    "approval_artifact": "blink://publish.new/...",
    "display_policy": "name + role, no photo"
  }
}
```

Three things to note:

1. **Lens, not job title.** A judge's lens (market / technical / FMF) is what plugs into the existing debate engine. The engine does not need to know "this is Kuka" — it needs to know "this is the market lens, with this criteria set, in this voice."
2. **Weights are explicit and per-program.** Different rooms weight differently. We expose this so the verdict matches the room.
3. **Attribution is a first-class field.** Use of a judge's name is gated on an approval artifact (see section 4 and section 6).

## 4. Distribution path: publish.new as the ingestion surface

**publish.new** (Dialect, Solana-native — the Blinks/Actions infra) is the publishing surface for program criteria. The path:

1. Program (or judge) publishes their criteria as a Blink on publish.new.
2. The Blink resolves to a structured JSON payload (criteria, lens, voice guidance, attribution approval).
3. Gecko ingests the payload as a **voice config** registered against the program_id.
4. Builders selecting that program in `bb research` (or the web app) get the program-bound panel instead of the generic one.

This keeps the ingestion path **on-Solana**, which matters for two reasons: it inherits Solana-native distribution (Superteam, Dialect, frames.ag wallets already plug in), and it sidesteps any hosting/platform conflict with the rest of the stack. The voice plug-in mechanism on our side is just a registry lookup keyed on program_id; the new surface area is the ingestion adapter and the curation/QA step that turns a Blink payload into a vetted voice config.

## 5. Rollout sequence

| Sprint | Goal | Concrete |
|---|---|---|
| **S21** | Design partner + ingestion path | Superteam Brasil live as program #1. publish.new -> JSON -> voice plug-in path working end to end for one program. Hand-curated voice prompts; ingestion adapter scaffolded but human-in-the-loop. |
| **S22** | 3 programs live | Add 2 more Superteam regions (or 1 region + 1 Solana Foundation grant track). Tighten the curation playbook. First external builder verdicts cite named judges. |
| **S23** | Self-serve onboarding | Programs can publish a Blink and appear in the picker without manual curation, gated only on attribution approval. Curation becomes review, not authoring. |
| **Later** | Cross-ecosystem | Other Solana programs, then non-Solana (YC partner office hours, Buildspace cohorts, etc.). Only after self-serve is solid. |

The order matters: design partner before tooling, tooling before scale. Building self-serve before we have one program that loves us is the classic mistake.

## 6. Open questions

These are real, and we should not pretend to have answered them yet.

- **Paid vs free programs.** Superteam Brasil is free to apply to. YC is free to apply to but has enormous downstream value. Some accelerators charge. Does the verdict price differ? Does our cut differ?
- **Revenue split.** Is there a rev share with programs? With named judges individually? Default assumption: free for the program (they get distribution), Gecko keeps session revenue. Revisit when a program asks.
- **Judge approval and attribution.** A judge's name carries reputational risk. Approval artifact (the Blink) is the consent layer, but we need a clear revocation path and a clear "this is an AI rendering of published criteria, not the judge themselves" disclaimer on every verdict.
- **Legal.** Using public judge names is likely fine under nominative fair use; using their *voice* and *criteria* in an evaluative product is grayer. Get this right before S22.
- **Drift.** Judge criteria evolve per cohort. Who owns keeping the config current — us or the program?
- **What happens when a builder's verdict from "evaluate me as Superteam BR" is bad and they apply anyway and get in?** Calibration and credibility loop. We need a feedback channel from program outcomes back into config quality. Not S21, but on the radar.

## 7. What this is NOT (in V1)

- **Not in the Monday demo.** The demo ships the generic 5-voice panel. Program judges are forward-look.
- **Not blocking S20 release.** S20 closes on tradeable verdict + x402 settle. This wedge sits on top of that, not in front of it.
- **Not a PRD.** This is the thesis. Implementation tickets get cut from S21 planning, not from this doc.
- **Not a marketplace.** V3-flavored marketplace dynamics (judges bidding, programs bidding, builders bidding) are explicitly out. We are curating a roster, not running an auction.

---

**Dispatch from here:** when S20 closes, `staff-engineer` + `business-manager` cut S21 from this doc. `web3-engineer` owns the publish.new ingestion adapter. `ai-ml-engineer` owns the voice-config -> debate-engine plug-in and the calibration loop. `business-manager` owns the Superteam Brasil partnership conversation and the legal/attribution policy.
