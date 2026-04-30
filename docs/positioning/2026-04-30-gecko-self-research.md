# Gecko self-research stress matrix

**Date:** 2026-04-30
**Mode:** stub (default)
**Source script:** `scripts/positioning_check.sh`
**Raw transcripts:** `docs/positioning/raw/2026-04-30/` (populated on run)

5 Gecko-flavored idea variants run through the full `bb research` +
`bb plan` (5-voice advisor panel) pipeline. Each row records the verdict
(inferred from gap_classification per Sprint 9 S9-VERDICT-01), the
structured gap label, and a count of unique sources cited.

> **Status:** placeholder skeleton. Run `scripts/positioning_check.sh`
> from a shell with a populated `.env` (Tavily + LLM keys) to overwrite
> this file with real verdicts. The script regenerates the file in
> place; no manual editing required.

## How to run

```bash
# Stub mode — free, no real x402 charge, exercises the full pipeline
scripts/positioning_check.sh

# Live mainnet — requires Track B preflight to pass first
scripts/live_preflight.sh && scripts/positioning_check.sh --live
```

Estimated cost (stub): $0.10 OpenRouter (research only — plan is free
in stub if the LLM fails, and the panel just records the failure per
F17 defensive logic).

## Summary (placeholder)

| # | Idea | Verdict | Gap class | Sources | Notes |
|---|------|---------|-----------|---------|-------|
| 1 | AI co-founder for indie hackers, x402-paid via MCP inside Claude Code | _pending_ | _pending_ | _pending_ | _pending_ |
| 2 | Builder Bootstrap Platform that lives inside Claude Code | _pending_ | _pending_ | _pending_ | _pending_ |
| 3 | pay-per-use research agent for solo founders, USDC on Solana | _pending_ | _pending_ | _pending_ | _pending_ |
| 4 | adversarial 5-agent debate to kill bad startup ideas before you build them | _pending_ | _pending_ | _pending_ | _pending_ |
| 5 | upstream of Kiro: should-I-build before how-do-I-build | _pending_ | _pending_ | _pending_ | _pending_ |

## Verdict heuristic

The current `bb research` output doesn't print a single-token verdict
(KILL / SHIP / REFINE) — it prints `gap_classification` per S9-VERDICT-01.
The script maps:

- `False` → **KILL** (the demand isn't real)
- `Full` → **KILL** (an existing competitor fully covers the wedge)
- `Partial:<facet>` → **REFINE** (real wedge, sharpen the named facet)
- _unparsed_ → **UNKNOWN** (logged as a script-side parse miss)

If the matrix produces 5x UNKNOWN, the renderer's gap line is missing
from research stdout — the parsing regex in `extract_gap` is the
suspect, not the pipeline.

## Run notes

_Populated by the script when run._
