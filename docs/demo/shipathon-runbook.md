# Shipathon demo runbook

**Sprint:** S18-DEMO-RUNBOOK-01 (D3)
**Owner:** product-designer + Ernani
**Target wall-clock:** **<90 seconds** end-to-end from `Read app.geckovision.tech/skill.md` to rendered verdict.

The demo proves one sentence:

> **Gecko produces grounded, adversarial verdicts on pre-ideas — a judgment you can buy, sell, or stake on.**

The runbook is opinionated. Stick to the script; the timing budget is real.

---

## Pre-flight (do once before the demo session)

- [ ] `.env` has `MONGODB_URI`, `OPENAI_API_KEY`, `TAVILY_API_KEY`, `VOYAGE_API_KEY` (S19), `GECKO_CHUNK_STORE=mongo`.
- [ ] `gecko-mcp doctor` reports all green. Specifically:
  - `chunk_store:mongo:ping` → `db=gecko_rag`
  - `chunk_store:mongo:index:chunks_vector` → `ready`
  - `chunk_store:mongo:index:chunks_text` → `ready`
- [ ] `app.geckovision.tech/skill.md` is reachable via `curl -fsS` (the Claude Code skill load step needs it).
- [ ] `bb research --idea "warm-up idea"` runs to verdict in <90s on a known-good idea (e.g. "x402 dev tools for Solana"). If this is slow, kill anything else competing for the OpenAI rate limit.
- [ ] Pick the demo idea. Recommended: an idea that lands on `REFINE` or `GO`, not `PIVOT`. PIVOT is correct behavior on weak ideas but feels like a rejection in front of a live audience. Test on the user's actual idea backlog before the demo.
- [ ] Terminal width is ≥120 cols. The Rich panels wrap badly below that.

---

## The script (runtime ~75–90s)

### Step 0 — Open Claude Code (5s)

```
$ claude
```

Wait for the prompt.

### Step 1 — Load the skill (5s)

In Claude Code:

```
Read app.geckovision.tech/skill.md
```

Claude responds with the bootstrapped instructions and `bb` becomes available. The audience watching sees: a one-liner installs the whole product. **This is the wedge — Gecko is a Claude Code skill, not a SaaS dashboard.**

### Step 2 — Run research (60–75s)

```
bb research --idea "$DEMO_IDEA"
```

The progress block prints in real time:

```
researching ▷ [phase 1/4] discovering sources
researching ▷ [phase 2/4] ingesting (web + bazaar + arxiv + twit.sh)
researching ▷ [phase 3/4] retrieval + adversarial debate
researching ▷ [phase 4/4] verdict synthesis
```

What the audience sees:
- **Diversity of providers** (web ≠ all). Bazaar/arxiv/twit.sh chunks land in the corpus.
- **Real citations** in the verdict (`[1] bazaar://...`, `[2] https://arxiv.org/...`).
- A **single token verdict** in the footer: `GO` / `REFINE` / `PIVOT`.
- A **deterministic hash** in the footer: `verdict@a1b2c3d4e5f6` — this is the artifact ID that the S19 tradeable surface paywalls.

### Step 3 — Show the artifacts (5s)

```
ls .gecko/scaffolds/<session_id>/
# PRD.md  business-plan.md  BUILDING.md
```

> "Three docs. Verdict-grounded. Yours, in 90 seconds, for one stablecoin payment."

---

## Talking points (in order, time-budgeted)

1. **Wedge sentence first** (5s). Read it verbatim. Don't paraphrase.
2. **Adversarial part** (10s). Point at the dissent block in the validation report. "Five voices argued this; you're seeing the synthesised verdict, but the dissent is preserved and citable." This is what Perplexity / ChatGPT don't ship.
3. **Tradeable part** (10s). Point at the verdict hash. "Same idea + same evidence → same hash. That's the foundation for buying, selling, or staking on a verdict — S19's tradeable-judgment surface." Don't promise on-chain settlement; that's still spec.
4. **Pricing** (5s). One sentence: a basic session is one stablecoin payment, x402 on Solana, no subscription, no per-seat.

---

## Failure modes + recovery

| Symptom | Likely cause | Recover (don't panic) |
|---|---|---|
| `bb` not found after `Read skill.md` | Claude Code skill loader regression | Pivot to `pip install gecko-cli && gecko research ...` |
| `chunks_vector` index `BUILDING` | M1 just provisioned, ANN warming | Wait ~2 min; demo on cached corpus instead |
| Verdict comes back PIVOT on demo idea | The product working correctly | Lean into it. "The product just told me 'no, not yet' — that's the whole point of an honest verdict layer." |
| All citations are `https://` | Wedge wire flag flipped off OR provider failed | Run `pytest tests/test_reach_ci.py` post-demo to diagnose; for the demo itself, finish gracefully and skip the diversity claim |
| `gecko-mcp doctor` red on `chunk_store:mongo:*` | Mongo Atlas cluster paused / region issue | Flip `GECKO_CHUNK_STORE=supabase`, restart `gecko-mcp serve`, demo from legacy store |
| OpenAI rate-limited mid-research | Demo ran before the audience was warm | Reset session, blame the network, run a second time |

---

## Timing checkpoint table

If any step blows budget, **stop and triage** before the next demo. The demo is the unit test for the "<90s" promise.

| Checkpoint | Budget | Hard cap |
|---|---|---|
| Skill load | 5s | 15s |
| Research start → ingestion done | 25s | 40s |
| Ingestion done → verdict rendered | 35s | 50s |
| Total | 75s | 90s |
