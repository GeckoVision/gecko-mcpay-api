# S40 Pending Patches — ready to apply post-contest (2026-05-21 07:10 UTC-3)

Three parallel agents (patch-report mode, nothing written to the live tree
during the contest) produced complete, ready-to-apply implementations.
Scheduled for application at the post-contest sprint kickoff. Agent IDs are
continuable via SendMessage if the full code rolled off context.

---

## C1 — Grid backtest extension  (agent `a91ec9321ef07da0c`)

Add to `contest_bot/backtest_entry.py`:
- `atr()` + `bb()` pure-Python helpers (after `mfi`, ~line 162)
- GRID config constants (after `TIME_STOP_BARS`, ~line 59): `GRID_LEVELS=8`,
  `GRID_BB_N=20`, `GRID_BB_K=2.0`, `GRID_FILL_FEE_PCT=0.6`, `GRID_ATR_N=14`,
  `GRID_RANGE_BREAK_ATR=1.0`; regime consts `REGIME_ADX_CHOP=18`,
  `REGIME_ADX_TREND=25`, `REGIME_CONFIRM_BARS=3`.
- `simulate_grid(c, start, end, params)` — Bollinger-bound grid, 8 levels,
  0.6%/fill fee, range-break = halt+market-exit. Returns realized_pnl_pct.
- `segment_regimes(c, adx_n=14)` — splits series into chop/trend runs with
  3-bar confirm + dead-zone hysteresis.
- `--grid` mode in main(): runs grid only on chop segments, prints the
  KILL METRIC (grid vs cash(0%) vs breakout-in-chop, per symbol).
Run: `python3 backtest_entry.py --grid`. Expected: thin memes (BOME/TNSR)
likely SHELVE (fees > step); PYTH/WIF/DRIFT the candidates.

## D2 — Skill self-lint  (agent `a0d8fd3134beb2d97`)

Create `scripts/skills/lint_skill.py` — pure-Python REVIEWING.md rubric
checker: frontmatter parse, description 80-150 words, <500 lines, no phantom
OKX tools (validates against the 22-skill onchainos set), examples JSON
parses. Fail-closed (exit 1). Usage: `python3 scripts/skills/lint_skill.py <skill-dir>`.
**Verified: our gecko-risk-oracle PASSES** (114-word desc, 322 lines, no
phantom tools, 16 JSON blocks parse; 3 guideline WARNs for absent
scripts/references/assets dirs).

## A0 — Fill empty canon corpus  (agent `af5a533cec0cea644`)

The kinds `canon_mauboussin` + `canon_macro` are declared in the Literal
(`sources/types.py` ~lines 66,69) + SQL CHECK
(`20260511000000_canon_provider_kinds.sql`) but have ZERO chunks
(declared-but-empty; drift-test passes because it reads the Literal, not the
corpus — only a REACH test catches this).

Create 4 files mirroring `ingest_marks.py` / `canon_marks.py`:
`packages/gecko-core/src/gecko_core/sources/canon_mauboussin.py`,
`canon_macro.py`, `scripts/canon/ingest_mauboussin.py`, `ingest_macro.py`.
Pattern: `CanonSource` NamedTuple (url/title/year/author/venue) + `*_SOURCES`
tuple; ingest tags `provider_kind`, `protocol=()` (cross-cutting, Pattern F),
`freshness_tier="static"`, `content_kind="mechanism"`, 1000-token chunks.
**DRY-RUN first** (`--dry-run`) to verify URLs before spending embed tokens,
then add a reach test (≥1 chunk per kind surfaces via the real retrieval path).

### Canon URLs (the hard-to-recreate research)

**Mauboussin / Counterpoint Global** (HIGH confidence on the first 2; the
`morganstanley.com/im/publication/insights/articles/article_*.pdf` slugs are
MEDIUM — confirm on dry-run):
- https://www.trendfollowing.com/pdfs/UntanglingSkillandLuck.pdf — Untangling Skill and Luck (2010)
- https://obj.portfolioconstructionforum.edu.au/articles_perspectives/PortfolioConstruction-Forum_Credit-Suisse_30-years-reflections-on-10-attributes-of-great-investors.pdf — Thirty Years / Ten Attributes (2016)
- {MS_HOST}/article_capitalallocation.pdf — Capital Allocation (2022)
- {MS_HOST}/article_measuringthemoat.pdf — Measuring the Moat (2016)
- {MS_HOST}/article_returnoninvestedcapital.pdf — ROIC (2022)
- {MS_HOST}/article_roicandtheinvestmentprocess.pdf — ROIC and the Investment Process (2023)
- {MS_HOST}/article_roicandintangibleassets_us.pdf — ROIC and Intangible Assets (2023)
- {MS_HOST}/article_probabilitiesandpayoffs.pdf — Probabilities and Payoffs (2024)
- {MS_HOST}/article_confidence.pdf — Confidence (2023)
- {MS_HOST}/article_birthdeathandwealthcreation.pdf — Birth, Death, and Wealth Creation (2022)
- {MS_HOST}/article_totalshareholderreturns.pdf — Total Shareholder Return (2023)
- {MS_HOST}/article_theimpactofintangiblesonbaserates.pdf — Intangibles on Base Rates (2021)
- {MS_HOST}/article_categorizingforclarity.pdf — Categorizing for Clarity (2022)
- {MS_HOST}/article_tradingstagesinthecompanylifecycle.pdf — Trading Stages in the Company Life Cycle (2023)
- {MS_HOST}/article_marketexpectedreturnoninvestment_en.pdf — MEROI (2023)

`{MS_HOST}` = `https://www.morganstanley.com/im/publication/insights/articles`

**Macro — Fed / BIS / IMF** (BIS HIGH; Fed/IMF MEDIUM-HIGH, confirm slugs;
the 2026 IMF WP/26/74 is forward-dated — verify it exists):
- https://www.newyorkfed.org/medialibrary/media/research/epr/2024/EPR_2024_digital-assets_azar.pdf — Financial Stability Implications of Digital Assets (2024)
- https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr1073.pdf — Stablecoins as new MMFs (2023)
- https://www.federalreserve.gov/econres/feds/files/2024011r1pap.pdf — Monetary Policy Shocks (2024)
- https://www.federalreserve.gov/econres/feds/files/2024050pap.pdf — Inflation and the Labor Market (2024)
- https://www.federalreserve.gov/econres/feds/files/2025071pap.pdf — Pandemic and War Inflation (2025)
- https://www.bis.org/publ/work1270.pdf — Stablecoins and Safe Asset Prices (2024)
- https://www.bis.org/publ/work1164.pdf — Public Information and Stablecoin Runs (2024)
- https://www.bis.org/publ/bisbull108.pdf — Stablecoin Growth: Policy Challenges (2024)
- https://www.bis.org/publ/qtrpdf/r_qt2412.pdf — BIS Quarterly Review Dec 2024
- https://www.imf.org/-/media/files/publications/wp/2024/english/wpiea2024133-print-pdf.pdf — Crypto as Marketplace for Capital Flight (2024)
- https://www.imf.org/-/media/files/publications/wp/2025/english/wpiea2025141-source-pdf.pdf — Decrypting Crypto / Stablecoin Flows (2025)
- https://www.imf.org/-/media/files/publications/dp/2025/english/usea.pdf — Understanding Stablecoins (2025)
- https://www.imf.org/-/media/files/publications/wp/2026/english/wpiea2026074-source-pdf.pdf — Making Stablecoins Stable (2026, VERIFY EXISTS)

Note: migration marks `canon_macro` as `daily` tier; ingest writes `static`
(correct for permanent reference papers) — minor inconsistency, leave static.

---

## Application order (per S40 critical path)
A0 (fill canon) + D2 (lint) first (independent, no bot impact) → C1 grid
backtest → Track B voices (sequential, eval-gated) → tests → agent execution
on real data (PAPER mode unless founder authorizes live).

All code-writing SEQUENTIAL (no parallel writes — git tangle). The full
deliverable code is in the 2026-05-21 session transcript + the three agent
IDs above (continuable via SendMessage).

---

## S40 KICKOFF EXECUTED — 2026-05-21 ~07:20 UTC-3 (results)

**Contest outcome:** PARTICIPATION GRANT HELD ✅ — final wallet $106.81
(≥$100), joinStatus 1, final PnL +$0.84 (3W/2L). The bot took its 1 remaining
overnight trade (-$0.18, within the predicted -$1.35 max). Watchdog + bot
stopped cleanly post-contest.

**Patches applied + committed:**
- C1 grid backtest → SHELVE grid (heavily -EV after 0.6%/fill DEX fees on all
  6 symbols). Keep momentum + chop-abstain. (commit 677eeea)
- D2 skill self-lint → scripts/skills/lint_skill.py; gecko-risk-oracle PASSES. (34f534a)
- A0 canon fill → 28/28 URLs verified live; ingested 398 macro + 439
  mauboussin chunks to Mongo. (committed)

**⚠️ FOLLOW-UP NEEDED — canon DOUBLE-INGEST (founder approval to dedup):**
canon_macro + canon_mauboussin each have 2× duplicate chunks (likely a
worktree agent ingested + the kickoff ingested again). Retrieval still works
but duplicates skew relevance. The dedup (delete-many on prod Mongo) was
correctly blocked by the guardrail — needs founder OK. Ready command:
```python
# keep one per (provider_kind, source_url, chunk_index), delete extras
# for canon_macro + canon_mauboussin in gecko_rag.chunks
```
Run when awake (or add a Bash permission rule). Drift test passes (4/4).

**DEFERRED to founder-awake (per cron instruction):**
- Track B voices (chart_analyst v2 / regime_analyst / memory-fix) — changes
  agent behavior; needs sequential apply + eval gate + founder scope sign-off.
- Formal canon reach test (Pattern E/F).
- Improved-agent paper execution (no improved agents until Track B lands).
