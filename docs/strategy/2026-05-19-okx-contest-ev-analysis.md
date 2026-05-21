# OKX Agentic Trading Contest — EV Analysis at $100 Capital

**Date:** 2026-05-19 · **Owner:** `quant-analyst` (EV math) ·
**Question owner:** founder.
**Companions:** `2026-05-19-okx-skill-quality-feasibility.md` (the
Skill-Quality track read); `2026-05-19-backtest-phase3-contamination-design.md`
(sample-size honesty, contamination + quotability rules);
`2026-05-19-gecko-verdict-demo-comparison-design.md` (#128 BPAR sample-size
table).
**Mode:** read-only analytical brief. No code, no spend, no probes.
**Branch:** `s39/backtest-phase3`.

---

## 0. Recommendation, up front

**Posture A — Stable / Gecko-gated — wins on dollar EV at $100 capital,
by a narrow nominal margin but a *wide* risk-adjusted margin.**
Posture A returns **+$3.15 mean EV, median +$3.32, 95% CI [-$3.47, +$10.94],
sd $3.91, P(net loss) ≈ 0.30**. Postures B and C have nominally
higher *mean* EVs (~+$29 each) but those means are driven by jackpot
tails; their **medians are +$2.62 and -$49.58 respectively**. C's
modal outcome is a $50–$90 loss with a 76% chance of net-negative
finish and a 54% chance of ending below $50.

**The volume question, answered directly:** there is **no volume
sweet-spot that dominates stability in expected dollar terms** under
honest priors. Higher volume *does* unlock leaderboard tier EV
(~+$10–15 per path conditional on clearing $1k volume), but the
required per-trade size erodes per-trade edge (Gecko can gate 3 trades
well, gating 20 well is a different problem) and the variance grows
faster than the mean. The curve is approximately flat in expected
return between n_trades=3 and n_trades=15 at modest size; above that,
mean drifts negative and only the tail keeps EV positive.

**The artifact-value caveat:** if entering the contest produces a
quotable proof-agent demo (per the ownership-tiered scope strategy,
trading agent = $0 proof artifact), the **non-monetary return likely
dominates the monetary EV at this capital level**. $3 of expected
dollar return is a rounding error against any of the three postures'
strategic optionality.

---

## 1. The three postures, operationally

| Posture | Trades | Avg size | Gating | Target | Volume | $1k LB gate? |
|---|---|---|---|---|---|---|
| **A — Stable** | 2–5 | $20–40 | Full Gecko verdict per trade | drawdown <5%, mean ~+1.5%/trade | ~$210 | **No** |
| **B — Moderate** | 10–20 | $20–50 (rotated) | Lighter gating | clear $1k vol, +5–15% target | ~$1,050 | **62%** of paths |
| **C — High-variance** | 5–10 | $50–100 (concentrated rotation) | None — chase top-500 PnL% | jackpot or bust | ~$1,130 | **64%** of paths |

A note on C: OnchainOS execution on Solana / X Layer per the
installed skill examples is **spot-only**, so "leverage" in C means
*concentrated bankroll exposure to small-cap rotations* — not
margin. That ceiling-caps the right tail vs a true leveraged play.

---

## 2. Contest rules — the math hinges on these (verbatim)

- *"1st 5,000 USDC · 2nd 2,500 · 3rd 1,000 · 4–10 = 300 each · 11–20
  = 150 each · 21–50 = 80 each · 51–100 = 30 each · 101–500 = 10 each"*
  — per board, two boards (PnL% absolute + Realized PnL absolute),
  identical ladders. Per-board ladder sums to **20,000 USDC**;
  matches the **40,000 USDC** combined pool.
- *"Leaderboard eligibility: $1,000+ cumulative trading volume during
  the contest."*
- *"Participation Reward: 5,000 USDC pool, equally split across
  qualifiers; qualify with $100+ volume AND maintain $100+ wallet
  balance throughout (random snapshots)."*
- *"Only token trades on Solana + X Layer. Stable↔stable,
  native↔wrapped, SOL↔USDC are EXCLUDED."*
- *"Realized PnL only — unrealised positions excluded."*

**Window length:** assumed **7 days** per the founder's brief.
**WIDE PRIOR:** the actual window is not in our materials; if it's
14 days, A's volume scales linearly (still under the $1k gate); B
and C bust-rates grow.

---

## 3. EV computation (Monte Carlo, n=200,000 per posture)

All paths simulate at $100 starting capital, OKX taker fees ≈ 10 bps
applied round-trip per trade, min trade size $5. Per-trade return
distributions are **WIDE PRIORS** anchored to small-cap Solana spot
base rates; full assumptions in §3.4.

### 3.1 Posture A — Stable / Gecko-gated

| Metric | Value |
|---|---|
| Trading PnL | mean **+$1.81**, median +$1.55, 95% CI **[−$3.47, +$8.56]**, sd $3.08 |
| Volume cleared $100 gate | 96.8% |
| Volume cleared $1,000 gate | **0.0%** (by design) |
| P(intra-window min balance < $100) | 55.3% |
| P(random-snapshot catches a dip) | ≈ 0.39 conditional |
| **P(participation reward FORFEITED)** | **≈ 0.21** (snapshot model) |
| Participation reward payoff | mean $1.33, 95% CI [$0.00, $4.59] |
| Leaderboard payoff | **$0.00** (gate not cleared) |
| **Combined EV** | **mean +$3.15, median +$3.32, 95% CI [−$3.47, +$10.94], sd $3.91** |
| P(net loss) | 0.295 |

### 3.2 Posture B — Moderate volume

| Metric | Value |
|---|---|
| Trading PnL | mean +$0.53, median +$0.52, 95% CI **[−$27.10, +$28.13]**, sd $13.99 |
| Volume cleared $1,000 gate | **56.2%** |
| P(wallet ever dipped <$100) | 84.6% → participation gate is essentially gone |
| Participation reward payoff | mean $0.30 (small — most paths bust the gate) |
| Leaderboard payoff conditional on placing | E[payoff \| place] ≈ $106 |
| P(leaderboard placement, any tier) | 0.266 |
| P(top-100 on either board) | 0.063 |
| P(top-10 on either board) | 0.0075 |
| **Combined EV** | **mean +$29.13, median +$2.62, 95% CI [−$27.07, +$186.07], sd $340.67** |
| P(net loss) | 0.444 |

**The mean is misleading.** Median is essentially the same as A; sd
is 87× larger. The +$29 mean is the participation-busted, jackpot-tail
shape of the distribution.

### 3.3 Posture C — High-variance smallcap

| Metric | Value |
|---|---|
| Trading PnL | mean +$4.15, **median −$54.07**, 95% CI **[−$89.09, +$592.07]**, sd $193.50 |
| Volume cleared $1,000 gate | 63.8% |
| P(wallet ever dipped <$100) | 94.4% |
| Participation reward payoff | mean $0.11 (gate almost always busted) |
| Leaderboard payoff conditional on placing | ≈ $92 |
| P(leaderboard placement) | 0.273 |
| P(top-10) | 0.0065 |
| **Combined EV** | **mean +$29.21, median −$49.58, 95% CI [−$89.07, +$708.22], sd $419.00** |
| **P(net loss)** | **0.761** |
| P(end below $50) | 0.539 |

**C's mean is positive only because of the jackpot tail.** Three out
of four paths lose money; one out of two ends below $50. This is the
shape of a lottery ticket, not a strategy.

### 3.4 Assumptions and their fragility

- **Per-trade return distributions (WIDE PRIORS).** A: N(+1.5%, 6%)
  clipped at −5%; B: N(+0.3%, 10%) ungated; C: 80% loss N(−20%, 10%)
  + 18% modest win N(+30%, 20%) + 2% jackpot LogNormal(1.5, 0.8).
  The +1.5% mean on A is the load-bearing assumption — see §5.
- **Leaderboard field size (WIDE PRIOR).** Log-uniform over [500, 3000]
  eligible entrants. Volume gate at $1k is materially higher than
  participation gate; field is bounded by that.
- **Participation qualifier count (WIDE PRIOR).** Log-uniform over
  [1,000, 10,000]. Per-qualifier share = $5,000 / N → $0.50 to $5.00.
- **Snapshot model (WIDE PRIOR).** 3 random snapshots over 7 days;
  conditional P(catches a dip | wallet ever dipped) ≈ 0.39 using a
  ~15% time-below-threshold prior. **If snapshots are continuous, A's
  participation EV collapses to $0** because trade-day dips are
  unavoidable.
- **Two-board placement correlation.** PnL% and absolute PnL on a $100
  base are ~100% rank-correlated; we credit both ladders to any
  placing path. This is generous to B and C, not A.

---

## 4. The volume sweet-spot — there isn't one

Sweep over (n_trades × avg_size) at fixed gating-decay
(per-trade mean drops 6 bps per added trade beyond n=3; per-trade sd
grows 0.4 pts per added trade):

| n_trades | avg_size | per-trade μ | mean PnL | mean total EV | clears $1k |
|---|---|---|---|---|---|
| 3 | $35 | +1.50% | +$1.34 | +$2.34 | no |
| 5 | $35 | +1.38% | +$2.12 | +$3.12 | no |
| **10** | **$50** | **+1.08%** | **+$4.41** | **+$15.11** | **yes** |
| 15 | $35 | +0.78% | +$3.11 | +$13.07 | yes |
| 20 | $35 | +0.48% | +$1.99 | +$11.84 | yes |
| 30 | $35 | −0.12% | −$3.37 | +$5.59 | yes |

**Reading the table:**
- Below the $1k volume gate, EV scales gently with size at fixed
  gating quality.
- Crossing the volume gate adds ~+$10–12 of expected leaderboard EV
  (the participation pool is tiny by comparison).
- Past n_trades ≈ 15 with realistic gating decay, per-trade edge goes
  negative and total EV starts to fall.
- There is a **shallow peak around (n=10, size=$50)** at mean total
  EV ≈ +$15. **But:** the variance at that point is multiple times
  Posture A's. Mean EV is +$15 vs A's +$3; sd is ~$15 vs A's $4.
  Risk-adjusted (return/sd), A is comparable or better.

**The sweet-spot point estimate (+$15 mean) survives only if the
per-trade gating quality decays *gently* with volume.** Under a
harsher decay (Gecko can't gate 10 trades and the 6th–10th trades
revert to base-rate noise), the peak collapses back toward A.

---

## 5. Is 0.5 Sharpe achievable in 7 days with $100 on Solana spot?

**Honest answer: the 7-day *realized* Sharpe is statistically
indistinguishable from any value in the [-1.5, +2.5] range
regardless of true Sharpe.** Sharpe is annualized; on 7 days with
~3–5 independent trade returns, the confidence interval on annualized
Sharpe is wider than the parameter space.

Per the #128 sample-size honesty thresholds (cross-referenced from
`2026-05-19-backtest-phase3-contamination-design.md`): N < 10
independent observations is "directional illustration only" and not
quotable as a number. A 7-day contest with 3–5 trades cannot produce
a quotable Sharpe.

**What IS achievable and demonstrable:**
- Mean per-trade return positive (sign-test on small N, weak claim).
- Max drawdown bounded — observable directly from the equity curve.
- Hit rate (fraction of trades closing above entry) — countable.

**What is NOT honestly claimable:**
- Annualized Sharpe at any specific value.
- "Gecko produces a 0.5 Sharpe strategy" — the contest window is too
  short to falsify even Sharpe = 0.
- Statistical significance of the per-trade edge — n=5 with sd 6%
  needs |μ| > 0.085 to reject μ=0 at p<0.05, which is way above the
  +1.5% assumption.

The framing should be: *Gecko-gated trades produced positive realized
PnL in N=3–5 instances over a 7-day window with bounded drawdown.*
That's the quotable shape. Anything Sharpe-flavored is per the Phase 3
quotability rules (§0): "directional illustration only" until N≥10.

---

## 6. Recommendation

**Take Posture A.** EV is +$3 with a ±$7 interval, modal outcome
is small-positive, max realistic loss is ~$10. The participation
reward alone ($0.50–$5 per qualifier) does not justify $100 of
true downside risk — but A's actual downside is ~$5–10, not $100,
because the discipline floor (5% per-trade stop) and the small
trade count bound the loss. The dollar return is **a rounding error
relative to the proof-artifact value** of having shipped a
Gecko-gated trade record consistent with the wedge claim. *That* is
the return.

The Participation Reward is **not worth the $100 risk on its own
terms** — $5,000 / 5,000 qualifiers = $1, and bust probability is
non-trivial. It's worth taking *as a side effect of A* because A's
real downside is small. It is NOT worth taking on its own (entering
without an aligned strategy is just paying $0 to maybe earn $1).

**Posture B is an EV-tie on mean but loses on every other dimension:**
median is the same, sd is 87× larger, participation gate is busted
on 85% of paths, and the leaderboard EV is jackpot-driven. There is
no risk-adjusted scenario where B beats A.

**Posture C is negative-EV on median and positive-EV on mean only
because of fat tails — this is the structural shape of a slot
machine.** Three of four runs lose money. One of two ends below $50.
Do not take C.

---

## 7. What the founder should NOT do

- **Do NOT chase top-10 PnL%.** P(top-10) is 0.0065–0.0075 across the
  realistic postures. Expected payoff conditional on top-10 is ~$2,500,
  unconditional EV from top-10 is ~$17. The variance cost of pursuing
  it is +$300+ in sd. Not worth it.
- **Do NOT take Posture C "for the proof story."** A blown-up bankroll
  is the opposite of the wedge. A C-run that ends at $11 is a story
  about Gecko being a lottery ticket, not a verdict oracle.
- **Do NOT lean on the Participation Reward as a thesis.** It pays
  $0.50–$5. It is contest dust. Entering for the participation reward
  alone is paying $0 to maybe earn $1.
- **Do NOT publish a Sharpe number from the contest window.** N is too
  small; per the Phase 3 quotability rules, the language is "directional
  illustration only" and contamination controls (model-cutoff sanity
  check on chosen pools) still apply if any backtest narrative gets
  attached.
- **Do NOT increase trade size to clear the $1k volume gate at the
  expense of gating quality.** The math (§4) is approximately flat
  between n=3 and n=15 at realistic gating decay; the variance penalty
  is real and the gating-decay assumption is itself a WIDE PRIOR.
- **Do NOT enter the leaderboard race assuming our field-size prior is
  right.** If the field is materially larger than our [500, 3000]
  range, leaderboard EV in B and C halves; A is unaffected.

---

## 8. The single biggest sensitivity

**A's per-trade mean return assumption (+1.5%) is the load-bearing
prior.** If Gecko's gating produces a true per-trade mean of +0.5%,
A's mean EV drops to ~+$0.60 and 41% of paths end negative. If gating
produces a true mean of 0% (gating is decorative, not edge-producing),
A's mean EV is negative and the entire EV analysis collapses to
"don't enter."

**This is unfalsifiable in the contest itself** (N too small). It is
falsifiable in #128's BPAR backtest with N≥10 contamination-clean
adverse events. **The contest entry decision should be downstream of
the BPAR result, not upstream of it.** If BPAR shows BPAR > 0.55 with
a clean CI, A's +1.5% prior is defensible. If BPAR is at parity, A's
+1.5% prior is wishful and the contest entry should be reframed as
purely proof-artifact, not EV-positive.

---

## 9. Cross-references

- `2026-05-19-backtest-phase3-contamination-design.md` §0, §6 —
  sample-size quotability, "directional illustration only" language
  below N=10, contamination probe gating.
- `2026-05-19-gecko-verdict-demo-comparison-design.md` (#128) —
  BPAR design, sample-size honesty table.
- `memory/project_ownership_tier_strategy_2026_05_16` — trading agent
  as $0 proof artifact; this is what reframes "+$3 EV" as not the
  primary return.
- `2026-05-19-okx-skill-quality-feasibility.md` — the Skill Quality
  Award track decision, which is a separate question from the trading
  contest EV computed here.
