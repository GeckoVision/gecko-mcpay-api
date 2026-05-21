# OKX Contest — Fire-Rate Retune Analysis (S39-#142)

**Mode:** read-only analytical brief. No code, no spend, no live trading.
**Owner:** `trading-strategist`. ~30h to contest close.
**Companion docs:** `2026-05-19-okx-contest-ev-analysis.md` (`7c652c0`,
quant EV math), `2026-05-19-okx-contest-execution-brief.md` (`50ee190`,
the strategy spec this doc retunes), `contest_bot/OPERATIONS.md` (the
running bot's runbook).

**The question:** the current spec — JTO-USDC 5m breakout, lookback 24
bars, confirm 1.0%, Gecko gate `act` + conf≥0.6 — is firing at ~4%
12h-probability under realistic priors. With ~30h left we either retune
the strategy (keeping the gate strict) to push fire-rate to 30–50% over
the remaining window, or we ship the artifact play (zero trades,
"Gecko declined every candidate"). This doc picks one.

---

## 0. Bottom line, up front

**Take the artifact play. Do not retune.**

The single sentence: a retune that 10x's fire-rate also 10x's the
chance of the first live trade being one the gate would have refused
on a normal day, which collapses the wedge story the bot exists to
demonstrate.

**Three lines:**

1. Recommendation: **accept zero. Let the gate decline. Ship the
   ledger as the artifact.**
2. Retune options (§3) raise expected fire-rate from ~[2%, 9%] to
   ~[15%, 40%] in the 24h window — but every option that achieves that
   either weakens the entry primitive (more false breakouts the gate
   wasn't trained on) or multiplies the instruments (eats the
   per-wallet $100 Participation gate). The retune fights the wedge.
3. The contest closes in 30h; the artifact is the proof, the dollars
   are rounding error (§5 of the EV brief). The pre-registered "Gecko
   declined every candidate" ledger row is the cleaner story.

---

## 1. Fire-rate quant — refining the 4% point estimate

The founder's back-of-envelope is `P(breakout fires) × P(Gecko act)`.
Both factors deserve an interval, not a point.

### 1.1 P(breakout fires) on JTO-USDC, current params

Current entry: `price_breakout`, `lookback_bars: 24` (2h on 5m),
`confirm_pct: 1.0`. The bot waits for the current bar's close to
exceed the trailing-2h high by 1.0%.

**Base-rate prior on low-vol Solana mid-caps (JTO/JUP/PYTH class):**

| Regime | 24h range | P(1% breakout fires in any given 12h block) |
|---|---|---|
| Tight consolidation | <5% | ~[0.08, 0.20] |
| Normal Solana mid-cap drift | 5–10% | ~[0.20, 0.45] |
| Active trend / news | >10% | ~[0.45, 0.80] |

JTO is currently in the *tight consolidation → normal drift* boundary
(observed 24h range 6.91%, 1h Δ +0.99%, 24h Δ -1.23%). Best read
across that boundary on a 12h forward window:

**P(breakout fires in 12h) ≈ [0.20, 0.45], modal ~0.30.**

The 24h interval roughly doubles to ~[0.36, 0.65], modal ~0.50, with
the caveat that breakouts cluster (if one fires in the first 12h, the
second-12h conditional probability is *not* independent — it's lower
because the lookback window now contains the breakout).

**WIDE PRIOR — the 1% confirm threshold is meaningful on a 2h window
for a mid-cap consolidating asset.** Pull the confirm to 0.5% or
shorten the lookback and these numbers move materially (§3).

### 1.2 P(Gecko `act` | momentum spot question)

This is the chokepoint and it is the wedge.

Observed today: three live polls (JTO, JUP, PYTH) all returned
`defer`. The canon corpus does not ground momentum spot trades — Marks
on cycles, Damodaran on valuation, Berkshire on durability are not in
the business of confirming "the 2h high just broke, buy now." The
panel correctly declines.

**Defer is the modal outcome on this question class.** From observed
verdict patterns on similar non-yield questions plus the trade-vertical
re-route table (Class D single-shot judgments rarely clear the
grounding bar on momentum-style entries):

| Verdict | Realistic rate on JTO/JUP/PYTH momentum-spot questions |
|---|---|
| `act` | ~[0.05, 0.15] (this is the strict gate the bot uses) |
| `act` AND `conf ≥ 0.6` | ~[0.02, 0.10], modal ~0.05 |
| `defer` (incl. low-grounding) | ~[0.70, 0.90] |
| `pivot` / `caution` | ~[0.05, 0.20] |

The 0.6 confidence floor is non-trivial — on the questions where the
panel does manage to ground, surviving dissent often keeps confidence
below 0.6. **P(act ∩ conf≥0.6) ≈ [0.02, 0.10] is the load-bearing
prior** and it is wide because we have N<10 same-class polls to
calibrate against.

### 1.3 Combined fire-rate, current spec

Multiplying independent factors (which slightly over-states the
12h-window estimate because re-poll cadence is hourly and Gecko
cache-then-charge prevents fresh verdicts per bar — see §1.4):

**12h fire-rate:** [0.20, 0.45] × [0.02, 0.10] = **[0.004, 0.045],
modal ~0.015** — i.e. 1.5% modal, 4.5% upper, 0.4% lower.

**24h fire-rate:** [0.36, 0.65] × [0.02, 0.10] = **[0.007, 0.065],
modal ~0.025**.

The founder's 4% back-of-envelope was at the upper end of the modal
band on a 12h window. The interval is wider than the point estimate
suggests, but the *direction* is the same — sub-5%, low single digits.

### 1.4 What §1.3 does not account for, and which way it cuts

- **Re-verdict cadence.** Per CLAUDE.md trade-vertical convention, the
  oracle isn't called per bar. The bot polls every 30s on price but
  only invokes Gecko on a fresh breakout signal. This *raises* the
  conditional fire-rate given a breakout signal (the gate is asked
  more cleanly), and is already baked into §1.2.
- **Hourly circuit breaker.** The bot's $3/h drawdown breaker can
  pause trading for an hour. If it trips on a paper-flat bar
  (vanishingly unlikely on paper-trade), fire-rate drops to zero
  during that hour.
- **JTO regime drift.** If JTO transitions from tight consolidation
  into a news-driven trend in the next 24h, the §1.1 distribution
  shifts right — fire-rate could climb without any spec change. This
  is luck, not strategy.
- **Idea-hash dedup.** A second breakout fires on a near-identical
  idea_hash within the cache window — the gate returns the cached
  `defer`, no new act. Cuts the *effective* poll count below the
  signal count.

**Honest read:** the realistic 24h fire-rate interval on the current
spec is **[1%, 7%], modal ~2.5%, point estimate 4%**. The founder is
right to be worried about a zero-trade contest; that is the modal
outcome.

---

## 2. The retune trilemma

Before evaluating options individually: any retune is choosing one
corner of a three-way trade-off.

```
          More breakout signals
                 /\
                /  \
               /    \
              /      \
             /        \
   Stricter / -------- \ Multi-instrument
   gate   /             \  (parallel bots)
         /               \
        /                 \
       /                   \
      /_____________________\
```

- **Loosening the entry primitive** (lower `confirm_pct`, shorter
  `lookback_bars`, switch to `ma_cross` or `volume_spike`) raises raw
  signal count but feeds the gate more *low-quality* candidates. The
  gate's `act`-rate doesn't change — Gecko still defers on momentum
  spot — so fire-rate *per signal* drops while signal count rises.
  Net effect is sub-linear in fire-rate gain and damages the wedge
  narrative because more of the gate-rejected questions are
  "honestly wouldn't have acted" rather than "Gecko correctly held
  the line on a real signal."
- **Loosening the verdict gate** is off-limits per the brief. The
  wedge is `verdict == act AND conf ≥ 0.6`. Moving that floor is the
  one knob we cannot turn.
- **Multi-instrument parallel bots** multiplies signal *and* gate
  polls per unit time. Three bots at $33 each on JTO/JUP/PYTH triples
  the effective fire-rate ceiling (subject to gate-rate per instrument,
  which is similar across these three). **But:** it almost certainly
  breaks the Participation Reward gate (§2.2).

### 2.1 Per-instrument vs per-wallet sizing — the trap

Contest rules: Participation requires `$100+ wallet balance throughout
(random snapshots)`. The current single-wallet $100 setup is right at
the threshold; three bots at $33 each still sums to $100, but:

- The Participation gate reads *wallet balance*, not per-bot allocation.
  A single wallet that hosts three parallel bots with $33 each in open
  positions has a USDC balance of close to zero during open positions,
  and that *will* get caught by a random snapshot.
- Three separate sub-account wallets are not allowed under contest
  rules (one wallet per account, per
  `project_okx_wallet_custody_2026_05_11`).
- One wallet with a `symbol: "*"` universe spec spreading $33 max per
  open position keeps the wallet balance constraint cleaner — the open
  exposure peaks at $66 (2 concurrent positions) and the buffer stays
  ≥$34. This is the only multi-instrument approach that doesn't break
  the Participation gate.

**Implication:** a "3 bots in parallel" framing is dead on arrival.
A "1 bot, 3-instrument universe" framing is viable but only modestly
better than single-instrument because the gate is still the bottleneck.

### 2.2 What a retune cannot fix

The chokepoint is **`P(act ∩ conf≥0.6) ≈ [0.02, 0.10]` on momentum
spot questions**, and that probability is structural to the wedge —
the canon literature does not ground 5m breakouts and we should not
want it to. Every retune option below raises the *numerator*
(opportunities to ask) without moving the *denominator*
(probability the gate clears). The fire-rate ceiling under any
strict-gate retune is approximately:

**P(fire | retuned spec) ≤ N_signals × 0.10**

where 0.10 is the upper end of the gate-clear interval. To hit 50%
fire-rate over 24h we need ~5 distinct gate-clearing opportunities,
which means ~50+ signals fed to the gate, which means signal density
has to climb ~10x. Every option below pays for that 10x with one of:
quality (more false breakouts), narrative (the gate now declines
everything because the signals are noise), or capital constraint
(multi-instrument vs Participation).

---

## 3. Retune options evaluated

Six concrete option groups. Each rated on (a) expected fire-rate lift
in the 24h window, (b) wedge integrity, (c) operational cost / risk
in <30h.

### 3.1 Reduce `lookback_bars: 24 → 12` (2h → 1h breakout window)

- **Signal lift:** ~[1.5x, 2x]. A 1h trailing high is broken more often
  than a 2h high. Modal P(breakout fires in 12h) ≈ [0.35, 0.65].
- **Gate impact:** unchanged in shape, but the panel is now reading a
  question of the form "JTO just broke its 1h high by 1%, act?" — even
  weaker grounding than the 2h version. Modal `act`-rate per signal
  drops slightly (maybe [0.015, 0.08]).
- **Net fire-rate:** modal ~[0.005, 0.05] per 12h → ~[0.01, 0.08]
  per 24h. **Barely moves.** The gate eats the signal gain.
- **Wedge integrity:** mostly intact. The gate is still strict.
- **Cost:** one-line config diff. ~5 min to deploy.

### 3.2 Reduce `confirm_pct: 1.0 → 0.5`

- **Signal lift:** ~[1.8x, 3x]. A 0.5% confirm on a 2h high fires
  significantly more often on a consolidating asset.
- **Gate impact:** worse than §3.1. The panel reads "JTO just broke
  2h high by 0.5%" — most readers would call that noise, the gate
  certainly will. `act`-rate per signal drops further, maybe
  [0.01, 0.06].
- **Net fire-rate:** ~[0.005, 0.06] per 24h. **Worse on a
  quality-adjusted basis.**
- **Wedge integrity:** weakened. The story "Gecko gated noise" is not
  the story we want; the story we want is "Gecko gated a real
  breakout because the canon-grounded panel correctly held the line."
- **Cost:** one-line config diff.

### 3.3 Switch entry primitive: `ma_cross` (EMA 5/20) or `volume_spike`

- **`ma_cross` signal lift:** EMA 5/20 cross fires maybe 2–4x per
  day on a 5m timeframe in this regime, but a meaningful fraction of
  those are false / immediate reversals.
- **`volume_spike` signal lift:** more variable; volume spikes
  cluster around news and breakouts and can fire 0 or 5+ times in
  24h with no smooth distribution.
- **Gate impact:** here is the subtle problem — the panel doesn't
  ground momentum entries *by primitive*. EMA cross is no more
  groundable than price breakout. `act`-rate is similar.
- **Net fire-rate:** ~[0.02, 0.10] per 24h. Modest improvement at
  best.
- **Wedge integrity:** mixed. Switching the primitive *the day before
  contest close* with no backtest signals desperation — the artifact
  reads worse, not better.
- **Cost:** non-trivial. The current bot's `price_breakout` plumbing
  is shipped (`d4e7b18`); a new primitive needs new TA helpers, new
  state machine, new tests. <30h is enough for the code change but
  not enough for confidence the new primitive isn't subtly broken.

### 3.4 Multi-instrument universe: `symbol: "*"` on JTO + JUP + PYTH

- **Signal lift:** roughly 3x raw signal count (3 instruments).
- **Gate impact:** `act`-rate is similar across the three — they
  share corpus reach and question class. So fire-rate scales close
  to linearly with signal count.
- **Net fire-rate:** ~[0.03, 0.20] per 24h — the only option that
  meaningfully clears 10% expected fire-rate.
- **Wedge integrity:** intact and arguably strengthened — the
  artifact then says "Gecko evaluated 3 named protocols across N
  signals and declined N-k, accepted k." More observations, same gate.
- **Cost:** the bot already imports `onchainos` and supports a
  configurable symbol; the change is *parallel poll loops* for the
  three instruments and a shared `gecko_wrap` / `circuit_breaker` /
  `artifact_logger`. The MAX_CONCURRENT=1 constraint becomes
  per-instrument or global — global is safer for the Participation
  gate. Realistically: 2–4 dev-hours for a clean retune, plus a
  smoke run before the live flip.
- **Capital constraint:** see §2.1 — single-wallet, $25/trade,
  global `MAX_CONCURRENT=2` is the safe shape. Three concurrent open
  positions of $25 each = $75 deployed, $25 buffer — that breaches
  the $90 soft drawdown line (execution-brief §3.5) on a single bad
  fill. Stay at MAX_CONCURRENT=2.

### 3.5 Lower TP +5% → +3%, lower SL -3% → -2%

- **Signal lift:** zero. This changes resolution speed, not entry
  count.
- **Resolution speed lift:** modest. Tighter TP/SL resolves positions
  ~30–50% faster on average, which raises the trades-per-window count
  *if and only if* the gate is firing.
- **Gate impact:** none. The gate sees entry questions, not exits.
- **Net fire-rate:** unchanged on entries. Total realised-trade count
  per window rises if entries are clearing, but if fire-rate is ~3%
  the trades-per-window dial doesn't matter.
- **Wedge integrity:** intact.
- **Cost:** one-line config diff.

### 3.6 Drop time_exit 144 → 72 (12h → 6h hold)

- Same shape as §3.5 — resolution-speed knob, not entry-count knob.
  Negligible effect on fire-rate. Skip.

### 3.7 Stacking — `lookback 12 + confirm 0.5 + 3-instrument universe`

Stacking the three biggest entry-side knobs:

- Modal P(breakout fires in 12h) per instrument ~[0.50, 0.75].
- Modal `act`-rate per signal drops to ~[0.01, 0.05] (lower quality
  signals).
- 3 instruments stacked.

**Net fire-rate over 24h:** ~[0.08, 0.40].

This is the only combination that gets us into the 30–50% band the
founder asked for. **But:** the gate is now declining lots of low-
quality signals, the artifact reads "Gecko declined 87 of 89
candidates, acted on 2 marginal ones" — which is *quantitatively*
right but *narratively* worse than "Gecko declined 4 of 4 high-
quality candidates."

---

## 4. The realistic best-case retune, written as a spec diff

If the founder rejects §0 and insists on a retune, this is the one to
run. It is not the recommendation.

| Param | Current | Retuned | Why |
|---|---|---|---|
| `SYMBOL` | `JTO-USDC` | `JTO-USDC,JUP-USDC,PYTH-USDC` (3 instances) | §3.4 — biggest fire-rate lift, keeps the wedge intact |
| `MAX_CONCURRENT` (global) | 1 | 2 | Avoid 3 concurrent $25 positions breaching the $90 drawdown floor |
| `ENTRY_PARAMS.lookback_bars` | 24 | 16 | A modest tighten (1h20m instead of 2h) — more signals without the noise-floor collapse of 12 |
| `ENTRY_PARAMS.confirm_pct` | 1.0 | 0.8 | Modest tighten; keeps breakouts "real" not noise |
| `USD_PER_TRADE` | 25 | 25 | unchanged — keeps the per-trade discipline |
| `MAX_DAILY_TRADES` (global) | 3 | 4 | One headroom slot |
| `STOP_LOSS_PCT` | 3 | 3 | unchanged |
| `TAKE_PROFIT_PCT` | 5 | 5 | unchanged |
| `TIME_EXIT_BARS` | 144 | 144 | unchanged |
| `SAFETY` | as-is | as-is | unchanged |
| `MAX_BUDGET_USD` | 100 | 100 | unchanged |
| **Gate** | `act ∩ conf≥0.6` | `act ∩ conf≥0.6` | **UNCHANGED, the wedge holds** |

**Expected 24h fire-rate under this spec:** ~[0.08, 0.25], modal ~0.15
— a 5–6x improvement over the current ~[0.01, 0.07] interval.

**New `live_only` filters to add:**

- Per-instrument cooldown of 4h (so JTO firing twice in 2h doesn't
  double-spend the gate budget on near-duplicate idea hashes).
- Global pause if `wallet_balance < 95 USDC` (already in execution-brief
  §3.5 — make sure the live config has it).

**What the retune does NOT change:**

- The gate.
- The instrument *class* (still Solana-native, still corpus-reached
  protocols).
- The $25 trade size.
- The drawdown discipline.

**Deployment cost:** 2–4 dev-hours plus a 30-min paper smoke. Doable
in the 30h window — but read §5 before pulling the trigger.

---

## 5. Counter-recommendation — the artifact play, both sides honestly

### 5.1 The case FOR retuning

- Zero realised trades = zero Participation Reward pool share. The
  pool share is ~$0.50–$5 (EV brief §3.4), tiny but >$0.
- Zero realised trades = zero per-trade ledger rows. The shadow
  counterfactual arm has nothing to attach paired-decision rows to.
  The artifact is "Gecko declined 4 polls; here is what the gate
  said" — a thinner ledger than "Gecko declined 60 of 65 signals;
  here are the 5 that cleared."
- A small fire-rate retune (§4) keeps the wedge intact and produces a
  fuller ledger with real settled outcomes. If 3–5 trades land and 2
  close green, that's the BPAR-style story the EV brief and #128
  comparison design both ask for.
- The retune is a one-shot decision; we can revert if the first 4h of
  live runs look pathological.

### 5.2 The case FOR accepting zero

- **The contest closes in ~30h.** A retune deployed at t-30h gives
  ~24h of live runtime, of which the gate has to: warm up, calibrate
  to the new signal density, and produce N enough trades for the
  artifact. On a fire-rate interval modal ~15%, expected trades over
  24h ≈ 24 × (signals/hr) × 0.15. With ~3–6 signals/hr across 3
  instruments, that's [10, 22] gate evaluations and [1.5, 3.3]
  modal expected trades. **The expected ledger gain over the artifact
  play is 1–3 settled trades** — and there is a non-trivial chance
  one of them goes pathologically wrong (slippage spike on the close
  leg, mispriced fill, exit gets stuck), at which point the artifact
  reads worse than the zero-trade story.
- **The wedge story for a *defer-only* contest is cleaner than the
  story for a *2 trades, 1 green 1 red* contest.** "Gecko held the
  line on every momentum-spot question because the canon doesn't
  ground 5m breakouts" is the verdict-oracle story. "Gecko cleared
  2 of 60 signals; 1 closed green +3%, 1 closed red -2%" is a
  noisy backtest story that no one will believe at N=2.
- **The Participation Reward is contest dust** (EV brief §3.4 — pool
  share $0.50–$5). It is not the artifact and the founder has been
  explicit (`feedback_okx_no_funding_pressure`) that dollars aren't
  the goal here.
- **Per the founder's own reframe (today): stability over peak.** The
  retune is chasing peak — pushing for *more* outcomes in a short
  window. The artifact play is stability — accepting the modal
  outcome of the original spec and shipping the ledger that the
  spec actually produced.
- **The retune fights its own gate.** A spec change that pushes
  fire-rate from 2.5% modal to 15% modal does so by feeding the gate
  more signals; the gate's `act`-rate per signal stays low. The
  realised trade record is therefore a *thin slice of a noisy signal
  stream*, not "Gecko picked the high-conviction moments." That's a
  worse story.
- **No backtest of the retuned spec exists.** Per CLAUDE.md
  trading-strategist principle #5 ("backtest is the artifact, not
  the deck"): a working backtest harness on the retuned spec showing
  positive PnL delta would change this answer. We don't have one.
  Going live on a spec we haven't backtested in a 30h window is the
  exact failure mode CLAUDE.md principle #6 calls out (capital
  staging — never propose >$20 at risk before the backtest harness
  shows positive PnL delta on 90d holdout). The retune crosses that
  line.

### 5.3 What we are losing by accepting zero

Be specific about it:

- **Participation Reward:** ~$0.50–$5 EV. Forfeit if the wallet ever
  dips below $100 on a snapshot, which is hard to evaluate without
  trades but is moot if we don't trade at all (the balance stays
  at $100).
- **Leaderboard placement:** never in scope; not a loss.
- **Ledger density:** 0–4 decision rows (from the existing polls)
  instead of 10–22 (from the retune). Both versions of the ledger
  are quotable; the dense version is no more *truthful*, just
  longer.
- **A potential "Gecko gated a real winner" highlight:** if the
  retune happens to clear the gate on a JTO/JUP/PYTH move that
  closes +5%, the contest result includes one quotable highlight.
  Modal probability of this happening: ~[0.08, 0.20] over the 24h
  window, conditional on at least 1 trade landing — call it ~10%
  overall. Not zero, but not load-bearing.

### 5.4 What we keep by accepting zero

- The published pre-registration block is intact (per execution-brief
  §4.3 — pre-registration is what makes the result quotable).
- The artifact reads: *"Across the contest window, Gecko was polled
  on N momentum-spot questions on JTO/JUP/PYTH. It returned defer on
  all N. The wedge held."* That is a defensible verdict-oracle story
  consistent with the canon's actual coverage — and it is **honest**.
- The next cycle (post-contest) can be a calmly-built retuned spec
  with a real backtest under it, per `feedback_dogfood_loop`.
- We respect CLAUDE.md principle #7 (surface failures verbatim — a
  low fire-rate IS a signal, don't reframe it as "needs more data").

---

## 6. The single biggest assumption — what would change this answer

The §1.2 prior `P(act ∩ conf≥0.6) ≈ [0.02, 0.10]` is load-bearing. If
the live gate clears at materially higher rates on momentum-spot
questions than today's three-poll defer cluster suggests — say [0.15,
0.30] — then the §4 retune produces a [0.15, 0.50] fire-rate interval
and the artifact-play recommendation flips. But:

- We have N=3 same-class polls on JTO/JUP/PYTH today, all defer.
- We have no reason to believe the canon corpus grounds 5m breakouts
  meaningfully better tomorrow than today.
- The 24h window doesn't give us time to verify a higher gate-clear
  rate before the retune commits to live capital.

So: the prior could be wrong, but we cannot resolve that in time, and
the asymmetric cost is that a wrong-direction prior fix (gate clears
more, not less, than we think) is *harmless to the artifact play*
(the existing spec still produces a few trades, that's fine) but
*damaging to the retune* (the retune produces N=15 noisy trades, the
artifact reads worse).

---

## 7. Bottom line — three lines

1. **Accept zero.** Do not retune. Ship the pre-registered ledger
   showing Gecko declined the candidates it was asked about; that
   is the verdict-oracle artifact.
2. **The most underweighted reason in the artifact-only path:** the
   contest is one cycle of a repeatable measure (per `_trend.json` in
   the execution brief §5), not a one-shot proof. A clean
   defer-only run is a clean data point in the running trend; a
   noisy retuned run pollutes the trend's first cycle.
3. **If the founder overrides and retunes:** §4 is the spec — 3
   instruments, MAX_CONCURRENT=2, lookback 24→16, confirm 1.0→0.8,
   gate UNCHANGED. Expected fire-rate ~[0.08, 0.25] over 24h. Smoke
   30 minutes in paper before flipping live; revert at first sign of
   pathological behavior.

---

## 8. Cross-references

- `2026-05-19-okx-contest-ev-analysis.md` (`7c652c0`) — Posture A EV
  math; Participation Reward = contest dust; artifact value
  dominates dollar EV at $100 capital.
- `2026-05-19-okx-contest-execution-brief.md` (`50ee190`) — the spec
  being retuned; pre-registration discipline; shadow-arm ledger.
- `contest_bot/OPERATIONS.md` — runbook for the live bot, including
  the PAPER → LIVE flip checklist (do not bypass).
- `CLAUDE.md` trading-strategist principles #5 (backtest first), #6
  (capital staging), #7 (surface failures verbatim).
- `memory/feedback_okx_no_funding_pressure` — dollars aren't the
  goal; the artifact is.
- `memory/project_ownership_tier_strategy_2026_05_16` — trading
  agent = $0 proof artifact, not a revenue product.
