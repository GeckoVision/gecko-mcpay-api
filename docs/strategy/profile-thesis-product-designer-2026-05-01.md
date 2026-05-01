# Profile Thesis — Product Designer Lens

**Date:** 2026-05-01
**Verdict:** refine. Thesis holds; the reveal moment can absorb profile-typed citations only if we treat profile as a *layer*, not a column.

---

## 1. The reveal evolves — without bloating

Today the validation panel reads: VERDICT token (`render.py:224-237`), Gap line (`:240-251`), four KV blocks, risk flags, then numbered Sources (`:102-140`) plus the Creator payouts footer (`:143-166`). That is already at the edge of one screen at 80 cols.

Add profiles as a **single new line above Sources**, not a new section:

```
Weighed in ─── 3 judges · 2 investors · 1 PM   (avg rep 0.74)
```

One line, dim accent, clickable to expand. The verdict stays the headline; profile mix is the *texture* of the verdict. Expansion (on `gecko show --profiles <session>`) renders a small table grouped by `profile_type`. Don't put per-judge commentary on the main reveal — that's a drill-down, not a beat.

## 2. Citation density spec

S13 already pushed citations to two lines (URL + creator sub-line, `:125-137`). Adding `profile_type` and `reputation_score` to every citation breaks the 80-col budget. Spec:

- **Inline (default):** `[1] url   chunk 3  (sim 0.81)` — line 1 unchanged.
- **Sub-line (when populated):** `@handle · judge · rep 0.74 · $0.0150 paid · sol:9xKp…aF2Q`
- Five fields max on the sub-line. Profile type goes second (right after handle) because it's the trust signal the founder is scanning for. Reputation third, dim. Payout + wallet stay last (existing order).
- **Threshold:** if sub-line wraps past terminal width, drop wallet first, then payout. Never drop profile_type or reputation — those are the new trust mechanism.

Trust curve: 2 fields = anonymous (current pre-S13), 3 = creator-attributed (S13), 5 = profile-attested (S15+). Above 5 we lose the founder. Anything richer (cited-precedent count, prior verdicts) lives behind `gecko profile <handle>`, not on the main reveal.

## 3. First-time contributor funnel

`paragraph login` is the right shape. Sequence:

1. `gecko profile init` — opens browser to publish.new OAuth + wallet sign.
2. Self-claim profile_type from a fixed taxonomy (judge / investor / PM / designer / security / operator). Self-claim is cheap; reputation is what makes it real.
3. First reveal moment: a one-screen "your profile is live" panel — handle, type (with a `unverified` dim tag), wallet truncated, **zero citations yet**. Honesty over theater.
4. Reputation grows by being cited. Every citation event triggers a digest email/CLI notification: `+1 citation · DeFi BUILD · session 9f2…`. The "build reputation" feel is *passive accrual you can watch*, not a leaderboard.

## 4. Anti-pattern — the worst is reputation gaming

Verification theater is solvable with attestations. Information overload is solvable with the density spec above. Reputation gaming is the existential one: the moment a numeric `reputation_score` is visible, contributors optimize for the score, not for being right.

Design defenses:
- **Never render the raw float.** Replace `0.7421` with bucketed bands: `emerging / established / senior`. Three buckets, no leaderboard rank.
- **Show outcome-tied deltas, not totals.** "+1 BUILD that shipped" reads as earned; "rep: 847" reads as gameable.
- **No public ranking page on day one.** The product is the verdict, not the league table.

## 5. Apex copy

Sub-fold today: "validation layer above frames.ag". The triple sub-fold (Sprint 14) needs a third line. Earned phrasing: **"profile-typed orchestration of paid expertise"** — but only when 3+ profile types appear in a real verdict. Until then it's a promise, not a feature. Gate the copy on `min(profile_types_cited) >= 3` over a 7-day window.

## 6. Sprint 15+ ticket

**S15-PROFILE-CITE-01 — Profile sub-line in citation render**

3-4 days. Extend `Citation` model with `profile_type` + `reputation_band` (string, not float). Update `_citations_renderable` (`render.py:102-140`) to insert profile fields between handle and payout. Add "Weighed in" summary line above Sources block in `_validation_body` (`:254-283`).

**Acceptance:**
- Pre-S15 citations (no profile) render byte-identically to S13.
- 80-col snapshot test with 3 profile types passes without wrap.
- Reputation band renders as one of three tokens, never as a number.
- "Weighed in" line absent when zero profiles cited.

---

Files: `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api/apps/cli/src/gecko_cli/render.py`
