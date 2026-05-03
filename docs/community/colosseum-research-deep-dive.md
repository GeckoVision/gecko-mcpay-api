# Colosseum Copilot — Deep Dive vs Gecko

## What Colosseum Copilot actually does

A **closed-corpus retrieval API** over a hand-curated Solana dataset: 5,400+ Colosseum hackathon submissions (Renaissance, Radar, Breakout, Cypherpunk), 84,000+ archive documents from 65+ curated sources (Satoshi posts → Breakpoint 2025 transcripts), 6,300+ products from The Grid, plus live web. It is distributed as a Claude Code/Codex skill (`npx skills add ColosseumOrg/colosseum-copilot`) wrapping the REST API at `copilot.colosseum.com/api/v1`. Tagline: **"Know the landscape before you build."**

## Their research/synthesis technique

- **Retrieval shape**: hybrid vector + text search over a *typed* corpus. Projects carry rich structured tags (`problemTags`, `solutionTags`, `primitives`, `techStack`, `targetUsers`, `clusterKeys`, `winnersOnly`, `isUniversityProject`).
- **Models**: 30 ML-derived project clusters precomputed offline; `/search/projects` (vector + text), `/search/archives` (semantic with similarity floor — ">0.4 strong, 0.2-0.4 verify"), and **cohort analytics** (`/analyze`, `/compare`) returning lift/delta scores between cohorts (e.g., winners vs all).
- **Synthesis is client-side**: the API returns *structured rows*, not prose. Claude (or whatever LLM hosts the skill) does the prose synthesis using the skill's prompt template. There is no AG2-style multi-agent debate.
- **Two modes**: Conversational (single-turn API calls + inline citations) and Deep Dive (8-step workflow: parallel data gathering → hackathon analysis → incumbent validation → gap classification → opportunity ranking). Gap taxonomy: Full / Partial (segment, UX, geographic, pricing, integration) / False.
- **Output shape**: tables (name, one-liner, hackathon, similarity, prize, crowdedness) + winner-vs-field deltas + cluster heat (hot / winning / open).

## What's structurally different vs Gecko

1. **Closed curated corpus vs open web**: They own a labeled DB of hackathon submissions with structured tag vocabularies. Gecko ingests Tavily output on demand — broader, but no priors.
2. **Precomputed cohort analytics**: `/compare` returns winner-vs-loser lift in one call. Gecko has no notion of cohorts or labeled "winning" examples.
3. **Templated retrieval, generative synthesis only**: API answers are tabular rows; the LLM only narrates. Gecko's AG2 panel does the heavy lift in the model.
4. **Single-event coupling**: Whole product is a wedge into the Colosseum hackathon funnel. Gecko is event-agnostic.
5. **Evidence floor + competitor honesty**: Hard rule to surface direct competitors with names + placements. Gecko's adversarial layer (critic agent) is similar in spirit but evidence-free.

## Worth borrowing for Gecko? (per item)

1. **Curated corpus** — *Partial yes.* Don't replicate Solana, but cache + tag prior `gecko_research` runs into a "precedent corpus" so repeat ideas hit warm RAG. (We already have `gecko_precedents` — extend it.)
2. **Cohort analytics / lift scores** — *Yes.* Add a "what survived vs what died" dimension to the critic agent. Even rough labels ("shipped" / "abandoned") would sharpen adversarial debate.
3. **Tabular API + LLM-side synthesis** — *No.* Our wedge *is* the multi-agent debate. Flattening to tables undercuts it.
4. **Event coupling** — *No.* Off-thesis. Gecko is upstream of any specific funnel.
5. **Gap taxonomy (Full/Partial/False)** — *Yes, cheap.* Add this as a structured field in `ValidationReport`. It forces the judge agent to commit to a category instead of hand-wavy prose.
6. **Direct competitor alerts with citations** — *Yes.* Force one synthesis section: "people who already shipped this, with URLs." Currently citations are diffuse.

## Direct quotes / evidence

- **Pitch**: "Pressure-test your startup idea against 5,400+ hackathon submissions, curated crypto sources, and live ecosystem data" — https://colosseum.com/copilot
- **Deep Dive**: "Full 8-step research workflow … parallel data gathering across projects, archives, and web; hackathon analysis; incumbent validation; gap classification; opportunity ranking" — https://docs.colosseum.com/copilot/introduction
- **Gap taxonomy**: "Full gap, Partial gap (segment/UX/geographic/pricing/integration variants), and False gap" — https://docs.colosseum.com/copilot/introduction
- **Hybrid search**: "`POST /search/projects` — Similar projects by query (vector + text hybrid search)" — `~/.claude/skills/colosseum-copilot/references/copilot-api-guide.md`
- **Cohort lift**: "Positive `delta` = winners over-index on this attribute. Negative = they under-index." — same file

## Bottom line

Colosseum Copilot is **not** "GPT-4 with a Solana prompt." It's a genuinely interesting *data product*: a labeled, clustered, queryable hackathon corpus exposed as plain tabular endpoints, with prose synthesis pushed to the client LLM. The valuable IP is the corpus and the tag vocabulary, not the retrieval stack. Gecko should steal the **gap taxonomy** and **competitor-alert-with-citations** patterns; should not chase corpus parity.
