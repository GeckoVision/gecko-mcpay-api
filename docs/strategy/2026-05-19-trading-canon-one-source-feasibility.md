# Trading-Canon One-Source Ingest — Feasibility for OKX Contest Window (2026-05-19)

**Mode:** read-only research brief. No code, no spend, no ingestion.
**Owner:** `trading-strategist`. Sibling to `2026-05-19-okx-contest-execution-brief.md`.
**Decision needed:** ingest one trading-canon source in the next 4–6h to unstick
the defer × 3 we saw on JTO/JUP/PYTH, or enter the contest on the existing canon
(Path B: shadow-ledger, starter-coach drives).
**Cross-references (do not re-state):**
- `memory/project_trade_vertical_v01_decisions_2026_05_11` — free + PD only.
- `packages/gecko-core/src/gecko_core/sources/types.py` — `ProviderKind`
  already includes `canon_mauboussin` (no migration needed if we pick him).
- Pattern A drift-test discipline — `tests/test_provider_kind_consistency.py`.
- Pattern F reachability discipline — momentum-flavored end-to-end probe.

---

## 0. Headline

**NO-GO on a new-source ingest in the contest window. Path B is the move.**

Honest read: the defer × 3 on JTO/JUP/PYTH is not a *corpus gap* — it is a
*panel-prior gap*. The value-investing canon abstains correctly because the
panel personae (Marks / Damodaran / Berkshire / Mauboussin) **do not hold
short-horizon momentum priors** that a single new source can install in 4–6h.
A momentum corpus reaches the retrieval layer; it does not reach the panel
*posture*. The risk on a contest-window ingest is asymmetric: best case we
move 1 of 3 defers to a low-confidence buy; worst case we add a bullishness
tilt the personae cannot reconcile and produce a *wrong* verdict on capital we
cannot afford to misallocate. See §3 for the contamination + corpus-balance
math, §4 for the go/no-go decision.

If the founder overrides this and wants to ingest anyway, the single highest-
leverage pick is **Jegadeesh & Titman 1993** (the academic momentum anchor),
not Lefèvre. Justification in §1.

Realistic confidence on the no-go: **0.65–0.80** (interval). The remaining
~25% is the world where panel personae weight a single high-status academic
citation enough to break the defer prior. That world is plausible but not
demonstrated — we have no Pattern F probe for *posture shift*, only for
*citation surfacing*.

---

## 1. Candidate ranking — which single source has highest expected leverage

Ranked by (a) probability of shifting a 1–2 day verdict on JTO/JUP/PYTH-class
tokens, (b) ingest cost in hours, (c) shape compatibility with `canon_marks` /
`canon_damodaran` style chunks (long-form narrative, attributable to author +
work + section).

### Rank 1 — Jegadeesh & Titman 1993 (and the momentum-anchor adjacent papers)

- **Source:** *Returns to Buying Winners and Selling Losers: Implications for
  Stock Market Efficiency*, J. Finance 1993.
- **Free PDF (verified):** https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf
  (mirror: https://www-2.rotman.utoronto.ca/~kan/3032/pdf/PredictabilityOfReturns_IntermediateAndLongHorizon/Jegadeesh_Titman_JF_1993.pdf)
- **Provider kind to add:** `canon_academic_momentum` (new — requires Pattern A
  migration + drift-test update).
- **Why it ranks #1:** the panel can *cite an empirical effect*. A defer prior
  flips when the personae have a concrete, citable, peer-reviewed regularity
  to weigh against the value-canon's caution. "Cross-sectional momentum at 3-12
  month horizons earned ~1%/month over 1965-1989" is the kind of statement a
  panel will incorporate; it gives Damodaran and Mauboussin a reason to lean
  into a tactical buy that the value canon alone does not provide.
- **Ingest cost:** **2.5–4h realistic** (interval). One PDF, ~28 pages, clean
  text layer, well-structured sections. Chunk count estimate: **40–70 chunks**
  at the existing ~500-token target. The bulk of the time is *new ProviderKind*
  plumbing (Pattern A), not the fetch/chunk/embed itself.
- **Risk:** the paper is US equities 1965-1989. Generalization to Solana spot
  on a 1-2 day horizon is a stretch; the panel may *correctly* note this and
  still defer. Realistic verdict-shift rate: **20–35%** of currently-deferred
  questions (interval), not the 60-80% a naïve read suggests.

### Rank 2 — Mauboussin: *Looking for Easy Games* + *Thirty Years*

- **Source:** Mauboussin's process / decision papers — *Looking for Easy Games*
  (Credit Suisse Jan 2017) and *Thirty Years: Reflections on the Ten Attributes
  of Great Investors* (2016).
- **Free PDF:** **not found at official Morgan Stanley / Credit Suisse URLs in
  the time budget.** Third-party mirrors exist (LinkedIn re-uploads, blog
  re-hosts) but those are *not* citable-provenance sources — they fail the
  attribution shape that `canon_*` enforces. **Blocked on a clean URL.**
- **Why it would rank higher if findable:** Mauboussin is already a `ProviderKind`
  (`canon_mauboussin` exists in `types.py:66`), so Pattern A is a no-op — drop
  files in, ingest. ~1.5–2h cost if URLs were clean. Process-oriented papers
  also shift the panel toward *base-rate thinking* without installing a
  bullishness tilt, which is the safest behavioral change for a $100-capital
  contest. The taxonomy-fit win is real; the URL-provenance loss kills it.
- **Recommendation if pursuing:** spend ≤30 min hunting an official URL; if not
  found, abandon — do NOT ingest from third-party mirrors (citation integrity
  is the wedge).

### Rank 3 — Lefèvre, *Reminiscences of a Stock Operator* (1923)

- **Free text (verified, PD-clean):** https://www.gutenberg.org/files/60979/60979-h/60979-h.htm
  (plain text: https://www.gutenberg.org/files/60979/60979-0.txt)
- **Why it ranks lower than its hype:** the book is *narrative wisdom*, not
  *cited regularity*. The panel cannot ground a tactical 1-2d entry on
  "Larry Livingston says don't fight the tape" the way it can on a JF-published
  effect. Worse, Lefèvre will *over-rotate* the panel toward Livermore-flavored
  pyramiding/cutting-losses heuristics, which is the wrong frame for a $100
  contest where realized PnL on closed trades is the leaderboard metric and
  pyramiding eats fees.
- **Ingest cost:** **3–5h** (interval). Big book (~110k words, ~180–250 chunks),
  attribution to chapter is easy from Gutenberg HTML anchors. The chunking
  itself is cheap; the *behavioral risk* is what makes this a bad pick.
- **Contamination risk:** very high — see §3.

### Rank 4 — Mackay, *Extraordinary Popular Delusions* (1841)

- **Free text:** Gutenberg, multiple editions.
- **Why it ranks last for contest use:** the book is a *bubble-aversion*
  text. Ingesting it now pushes the panel **further into defer**, not out of
  it. This is the opposite of the move we want for a contest where we *need*
  the panel to occasionally produce a buy verdict. Useful for a future
  cycle-awareness ticket; not useful in the next 33h.

### Rank 5 — Lo, *Adaptive Markets Hypothesis*

- Free preprint versions exist on Lo's MIT page for some papers; book itself is
  copyrighted (Princeton 2017). Ingesting the book is out of bounds per
  founder cash constraint; ingesting just the AMH precis papers gives us
  ~maybe 30-40 chunks. Net effect on a 1-2d verdict is **near-zero** in 4-6h —
  AMH is meta-level epistemology; it does not give the panel a directional
  prior.

### Verdict on ranking

If we **must** ingest one source, it is Jegadeesh & Titman. Mauboussin would
beat it on cost-efficiency if we could secure clean URLs in <30 min; the
search budget did not surface them at official hosts. Lefèvre and Mackay
are wrong-shaped for the contest mechanic. Lo is right-shaped but
right-rate-too-slow.

---

## 2. Realistic ingest cost for the top pick (Jegadeesh & Titman)

Walking the path end-to-end. All intervals.

| Step | Cost (h) | Notes |
|---|---|---|
| Fetch + verify PDF cleanliness | 0.25 | Bauer/UH mirror is text-extractable; ~28 pages, no scan artifacts. |
| Decide tagging: extend `canon_mauboussin` shape vs new `canon_academic_momentum` | 0.25 | Strong recommend new kind — the source is distinct enough that lumping it under Mauboussin will silently dilute Mauboussin retrieval. |
| Pattern A migration: add `canon_academic_momentum` to `ProviderKind` Literal + SQL CHECK (whichever side still applies — chunks live in Mongo Atlas per `memory/project_supabase_chunks_dropped_2026_05_08`, but the drift-test contract still binds) | 0.5–0.75 | Touch `types.py`, the SQL CHECK migration file (contract-only), `tests/test_provider_kind_consistency.py`. |
| New adapter: `packages/gecko-core/src/gecko_core/sources/canon_academic_momentum.py` mirroring `canon_marks.py` shape | 0.5 | Curated URL list (1 paper + maybe 2 follow-ons), CanonPaper dataclass, no scraping needed. |
| Ingest script: `scripts/canon/ingest_academic_momentum.py` | 0.5 | Borrow from `scripts/canon/ingest_marks.py`. PDF text extraction is the new wrinkle — `pdf.py` adapter already exists in `sources/`. |
| Chunk + embed run | 0.5–1 | 40–70 chunks × text-embedding-3-small ≈ <$0.01, ~2-5 min wall-clock. The hour budget is for re-running with corrections. |
| Pattern F probe: write a momentum-flavored query, assert ≥1 chunk from `canon_academic_momentum` reaches the trade-panel `$match` | 0.5 | This is the load-bearing step — without it we are guessing at reachability. |
| Smoke a JTO/JUP/PYTH verdict and inspect citation list | 0.5 | Does the new source actually surface? Does it move the verdict? |
| Buffer for "first run finds a bug" | 0.5–1.5 | Always. |

**Total realistic interval: 4.0–6.0 hours.** Right at the edge of the founder's
"4–6h" window. Anyone telling you this is a 2h job is mis-pricing Pattern A +
Pattern F overhead from prior sprints (S33-#80 is the latest example of
forgetting Pattern F costs hours, not minutes).

The 4h floor assumes everything works first try. The 6h ceiling assumes one
round-trip on a Pattern A test failure. Beyond 6h ⇒ abandon and back out.

---

## 3. Risk profile of the ingest

### 3.1 Contamination risk (LLM hindsight)

All five candidate sources are **pre-cutoff** for every panel model. Jegadeesh
& Titman 1993 has 12,000+ citations and is in every quant-finance syllabus —
gpt-4o-mini and claude-opus have certainly "read about" it. Lefèvre is
similarly canonical and quoted endlessly in financial writing.

**Implication:** the marginal value of *ingesting* these sources is not "the
panel learns something new" — it is "the panel can *cite* something it
already knew, with chunk-level provenance, which the verdict synthesizer can
surface as a citation." This is the wedge — citation-grounded dissent — and
it is real, but it is smaller than a naïve read suggests. We are not
teaching; we are *enabling citation*.

The risk: citation enablement may not be sufficient to flip a defer to a buy.
The panel's defer prior on JTO/JUP/PYTH is driven by personae *who do not
trade momentum*, not by missing citations. Marks would still defer with
Jegadeesh & Titman in front of him. Damodaran might use it to refine a
position-sizing comment but probably not to flip from defer to buy on a 1-2d
horizon.

**Bound:** verdict-shift rate from a momentum corpus ingest is realistically
**20–35%** of currently-deferred questions (interval), and of those, perhaps
**half** shift to *low-confidence* buys that we would not act on at $100 size
anyway. Net actionable shift: **10–18%** of deferred questions become
actionable. On a 3-question sample (JTO/JUP/PYTH), that's an expected
**0.3–0.55** flipped verdicts. Less than one.

### 3.2 Corpus-balance risk

The current canon is value-tilted. Adding a momentum source without adding
a *counter-momentum* source (e.g. De Bondt & Thaler 1985 on long-horizon
reversal, or Asness on factor combination) creates an asymmetric tilt the
personae cannot reconcile. Marks-the-persona reading momentum-only academic
work in isolation produces an *off-distribution* Marks. We have no eval that
catches this — `tests/eval/` measures retrieval/citation surfacing, not
persona-coherence under a corpus shift.

**Mitigation if we proceed:** ingest at minimum Jegadeesh+Titman AND De Bondt+
Thaler in the same batch. That doubles the cost to **7–10h** and blows the
window. So mitigation is *don't ingest one* — and "don't ingest at all in
the window" follows.

### 3.3 Rollback

Rollback is *technically* clean — `provider_kind` is a column, we filter the
new kind out of the retrieval `$match` and the panel sees the old corpus
again. But:

- We cannot rollback a *verdict that already drove a live trade*. The contest
  starts in 33h. If we ingest, smoke, deploy, and then a JTO buy verdict
  drives a live $20 trade that loses, the rollback is irrelevant — the loss
  is realized. The contest's leaderboard metric is realized PnL.
- The drift-test pattern enforces that removing a `ProviderKind` is also a
  schema event. A "soft" rollback (filter-only) is fine; a "clean" rollback
  (remove the kind) is another 1-2h.

Practical rollback budget: **0.5h soft, 2h clean**. Acceptable, but it does
not undo a bad trade.

---

## 4. Go / no-go

### Recommendation: **NO-GO on ingest. Enter on existing canon (Path B).**

The math, plainly:

- Expected actionable verdict-shifts on JTO/JUP/PYTH from a Jegadeesh+Titman
  ingest: **0.3–0.55** of three questions.
- Cost of pursuing: **4–6h** of a ~33h window, against an alternative use of
  that time (Path B execution polish, ledger build, fallback paths).
- Asymmetric downside: a single mis-installed bullishness tilt on a value-canon
  panel can produce a *wrong* buy verdict on capital we cannot reload. The
  contest is $100 of real money and Participation Reward requires *closed*
  trades — a single wrong directional call on a 30% position is 10× the
  expected leaderboard payout.
- The defer × 3 we saw today is the panel doing its job. Value personae deferring
  on short-horizon momentum questions is *correct epistemic behavior*. We do
  not want to engineer it away under time pressure.

**Path B is the move:** enter with the existing canon, let `starter-coach`
drive entries, run `gecko_trade_research` as a *shadow* ledger that records
what Gecko *would have* said — defer included. The shadow ledger is the
artifact for the Skill Quality submission and the post-contest writeup.
Defers are not a failure mode here; they are *data* for the writeup ("Gecko
correctly abstained on N of M momentum-flavored questions where the value
canon had nothing to say"). That story is stronger than a hastily-ingested
momentum corpus producing borderline buys we cannot defend.

If the founder overrides and wants to ingest anyway, the single biggest risk
to flag is the **corpus-balance asymmetry in §3.2**: ingesting Jegadeesh &
Titman *alone* tilts the panel into a momentum posture without the reversal
counterweight, and the personae have no defense against this off-distribution
shift because we have no eval that catches persona-coherence drift. Pair-
ingest or do not ingest.

---

## 5. Report-back summary

- **Top pick (if forced):** Jegadeesh & Titman 1993, https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf
- **Estimated ingest hours:** 4.0–6.0h (right at the window edge).
- **Go / no-go:** **NO-GO**. Path B (existing canon + shadow ledger) is the move.
- **Biggest risk found:** corpus-balance asymmetry — a momentum source ingested
  alone, without a reversal counterweight, produces an off-distribution panel
  posture that no current eval detects. The defer × 3 is correct behavior, not
  a bug. Engineering it away in 4-6h trades a correct abstention for an
  uncalibrated buy on $100 of real capital.
