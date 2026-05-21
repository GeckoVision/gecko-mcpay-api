# OKX Agentic Trading Contest — Execution Brief (S39-#137)

**Mode:** read-only execution-side brief. No code, no spend, no live trading.
**Owner:** `trading-strategist`. Complement to `quant-analyst`'s EV math.
**Companion docs:** `2026-05-19-gecko-verdict-demo-comparison-design.md`
(#128 ledger), `2026-05-19-okx-skill-quality-feasibility.md` (#125 gate
analysis), `2026-05-19-okx-complement-map-s38-plan.md` (skill plan).

**Scope:** $100 real capital, single Agentic-Wallet sub-account, Solana spot
through `onchainos`/`okx-agent-trade-kit`, Gecko-gated entries with a shadow
counterfactual ledger. Stability posture (Sharpe ~0.5) over volume-chasing.

---

## 0. Bottom line — what binds the strategy

Three constraints dominate everything below and are stated up front so the
reader does not have to triage them out of §3:

1. **Realized PnL only.** Open positions earn nothing toward the leaderboard.
   This forces *closing discipline*, which forces *holding-window discipline*,
   which forces a TP/SL rule with a hard time-stop. A "good thesis held too
   long" scores zero in this contest.
2. **Contest-counting trade filter excludes the safe pairs.** SOL↔USDC,
   native↔wrapped, stable↔stable do **not count**. The only contest-eligible
   instruments are exactly the *risk-bearing* ones — token spot legs against
   USDC or SOL where the token is neither a stablecoin nor a wrap of the
   quote asset. Slippage and impact realism therefore bind harder than they
   would on any "safe" universe.
3. **Participation Reward at $100 cumulative volume is realistically the only
   in-reach payout.** A $1,000 leaderboard-gate volume on $100 of capital
   requires ~10x turnover; doing that in 7 days *without* leaking ≥3-5% to
   fees+slippage is a separate skill from picking direction. The brief
   below explicitly **targets Participation, not leaderboard**, and §7
   explains why the founder's "stability over volume" posture is correct.

Everything in §1–§6 reads downstream of these three.

---

## 1. OKX onchainOS execution reality at $100 capital

### 1.1 What the four founder-shared docs actually specify

Honest summary of what the four URLs cover *for execution mechanics*:

| Doc | Contains | Does NOT contain |
|---|---|---|
| `run-your-first-ai-agent.md` | Example flow ("Executing buy <token_a>: 1 USDT", trailing-TP +50% with 10% pullback, SL -20%) | Fee schedule, slippage controls, min trade size, DEX routing |
| `run-your-first-mcp.md` | Generic onchainOS setup; notes "MCP services may charge a fee paid in USDT" | `okx-agent-trade-kit` tool names, X402 flow specifics, execution call shape |
| `agentic-wallet-overview.md` | TEE custody ("not even OKX"), up to 50 sub-wallets, **x402-protocol-native** ("Agents pay onchain automatically when calling external APIs") | Per-trade fees, gas pass-through, single-wallet rule |
| `supported-chain.md` | Solana + X Layer both listed under Agentic Wallet; OpenAPI lists 17+ chains | Per-chain token list, min trade sizes, excluded pairs, DEX coverage |

**Verdict:** the dev-docs do not pin fees, minimums, or routing. Those have
to be measured against the live MCP at read-only (§6) before any execution.
Anything below labeled **WIDE PRIOR** is honestly unknown until we probe.

### 1.2 What we *do* know from the installed skills (`starter-coach` precedent)

From the feasibility doc (`2026-05-19-okx-skill-quality-feasibility.md` §Q1)
and the installed `okx-*` skills the founder already has at
`~/.local/bin/onchainos` v3.2.0+:

- **Trade routing** is via `onchainos swap execute` — a single CLI shape that
  is the de-facto Solana DEX-aggregator surface for the wallet. Underlying
  aggregator is not named in the four docs, but the `okx-dex-*` skill family
  implies OKX's own DEX aggregator (which on Solana fans out across Jupiter,
  Raydium, Orca, Meteora pools). **Treat as a meta-aggregator with Jupiter-
  class routing; verify on the first read-only quote.**
- **Dry-run / quote without execution** exists — `starter-coach` references
  the `onchainos gateway simulate` path for tx dry-run. This is the
  pre-flight tool for slippage measurement at §6.
- **Position close mechanics:** there is no "close position" primitive on a
  DEX. To realize PnL on a TOKEN→USDC entry you submit the reverse swap
  USDC→TOKEN→USDC (or TOKEN→USDC on the exit leg). Every realized-PnL trade
  pair therefore eats **two full swap fee+slippage rounds**. This is the
  single most under-appreciated cost at $100 capital and drives §3's sizing.
- **X402 on the MCP layer:** the wallet "pays onchain automatically when
  calling external APIs" — so MCP-tool consumption (e.g. paid market-data
  calls) is metered in USDT from the sub-account balance. Our Gecko side is
  `X402_MODE=stub` per project memory; OKX's own MCP charges are the
  exposure. **WIDE PRIOR on per-call USDT amounts** until probed; the
  Participation $100-balance constraint means even sub-cent leakage
  matters across a 7-day window.

### 1.3 Fee / slippage realism at $10–$50 trade size — WIDE PRIOR with bounds

Solana DEX-aggregator round-trip on a $30 swap of a thick-liquidity token:

| Component | Realistic band (Jupiter-class routing, $30 notional) |
|---|---|
| Aggregator fee | 0 – 10 bps (Jupiter is 0; OKX aggregator unknown) |
| Pool LP fee | 25 – 100 bps depending on pool tier |
| Solana gas | ~$0.0005 – $0.005 per swap (negligible at this size) |
| Price impact | 5 – 80 bps depending on pool depth |
| **Round-trip (open + close)** | **~60 – 300 bps total** |

**Order-of-magnitude planning number:** budget **~150 bps round-trip** for
top-5-liquidity Solana tokens at $30 ticket size. For thinner tokens it
blows out to 300–500+ bps and they leave the universe (§2). Replace these
numbers with the first `onchainos swap quote` read after the §6 probe.

### 1.4 Settle/close: realised PnL accounting

A position is realised only when the token leg is sold back to USDC (or
SOL, which is then closeable to USDC — but SOL↔USDC doesn't count, so the
TOKEN→USDC exit is the only contest-clean realisation path). Therefore:

- Track positions in the ledger as `open` until the close-leg signature lands.
- A position with an unrealised loss at the time stop *must close* if the
  contest window is closing; the realised loss counts, the unrealised does
  not. Drawdown discipline (§3.5) hard-stops new entries but does not force
  exits — that decision is per-position, time-stop-driven.

---

## 2. Tradable instrument universe — Solana, $100, contest-counting

Filter criteria:

- (a) Solana DEX depth sufficient to round-trip $30 with **<1% slippage**
  (~150 bps round-trip per §1.3 — the upper tradable band).
- (b) Gecko corpus has reach on the token's protocol (named coverage of the
  associated protocol in our investor-canon + retrieval corpus; the panel
  must be able to return `act` verdicts, not stall on thin grounding).
- (c) Eligible per contest rules — not SOL, not a stable, not a wrap.

### 2.1 Ranked candidates (5–8, opinionated)

| # | Token | Pair | Liquidity (Jupiter top-route depth, WIDE PRIOR — verify on probe) | Gecko corpus reach | Notes |
|---|---|---|---|---|---|
| 1 | **JTO** (Jito) | JTO/USDC | Thick — LST-governance flagship | **Strong** — Jito appears in liquid-staking canon, named protocol | Best-in-class for our corpus; volatility is real and verdict gate is meaningful |
| 2 | **JUP** (Jupiter) | JUP/USDC | Very thick — DEX-aggregator native token | **Strong** — Jupiter is the routing layer the corpus references directly | High coverage, lower idiosyncratic risk than memecoins |
| 3 | **PYTH** (Pyth Network) | PYTH/USDC | Thick — oracle flagship | **Strong** — oracle layer is referenced throughout DeFi canon | Direction is macro-DeFi-correlated; cleaner thesis than memecoins |
| 4 | **DRIFT** (Drift Protocol) | DRIFT/USDC | Moderate — perp-DEX governance | **Moderate-strong** — Drift named in DeFi corpus | Watch slippage at $30; may push round-trip toward 200 bps |
| 5 | **RAY** (Raydium) | RAY/USDC | Thick — incumbent AMM token | **Moderate** — Raydium in DEX-AMM section of corpus | Slower-moving than 1–3; lower verdict-gate signal expected |
| 6 | **BONK** | BONK/USDC | Very thick — flagship Solana memecoin | **Thin** — memecoin coverage in canon is sparse; expect more `REFINE` verdicts | Include only if the Gecko verdict actively says `act`; default abstain |
| 7 | **W** (Wormhole) | W/USDC | Moderate — bridge governance | **Moderate** — bridge risk in canon; verdict gate is informative | Bridge-incident tail risk is exactly what the verdict gate is for |
| 8 | **KMNO** (Kamino) | KMNO/USDC | Moderate | **Strong** — Kamino is the protocol used in the yield-verdict skill demo (#132 fixed) | Closes the loop with the parallel yield demo |

### 2.2 Honest gaps — where Gecko's corpus is thin and we should NOT trade

- **Long-tail memecoins (WIF beyond BONK, PNUT, etc.):** corpus is thin;
  expect persistent `REFINE`/abstain verdicts. If we trade these despite
  abstain we are *defeating the wedge gate* and the counterfactual ledger
  will record exactly that mistake.
- **Brand-new launches (<30 days):** the canon corpus is by construction
  historical; new launches have no canon reach. Default abstain.
- **X-Layer tokens:** see §3.7 — likely no.

---

## 3. Strategy spec — single-wallet, $100, Gecko-gated, stability posture

Written in the shape of a `starter-coach` strategy card. This is the spec the
agent executes; numeric values are pre-registered before the contest window
opens and frozen for the duration.

### 3.1 Position-size rule

- **Per-trade ticket: 25% of current wallet balance** (~$25 at start).
- **Hard cap: 2 concurrent open positions.** Total deployed ≤50%, leaves
  50% USDC buffer for the $100-balance Participation gate (§3.5) and for
  re-entry without forced sells.
- **Minimum ticket: $20.** Below this, fees+slippage swamp the edge (§1.3).
- **No averaging down.** If a position moves against us, the time-stop
  closes it; we do not add. Averaging down breaks the counterfactual.

### 3.2 Entry rule (Gecko verdict gate)

For each candidate from §2.1, on a triggered evaluation:

1. `onchainos defi/market` discovery → candidate token + on-chain facts.
2. `onchainos swap quote` (read-only) → realisable round-trip cost in bps.
   Reject if round-trip >200 bps.
3. `gecko_trade_research` → verdict envelope (verdict, confidence, citations,
   surviving_dissent).
4. **Gate logic:**
   - `verdict == GO` AND `confidence_bucket in {established, senior}` AND
     `citation_count ≥ 2` → **act** (deposit full ticket).
   - `verdict == REFINE` → **down-size to 50% ticket** ($10–$12). One
     concurrent down-size position max.
   - `verdict == PIVOT` OR `low_grounding == true` OR `citation_count < 2`
     → **decline**, log shadow-position counterfactual (§4).
   - Verdict-call failure (5xx, timeout) → **decline + alert**, do NOT
     fall back to baseline. A failed verdict is a failed gate.

### 3.3 Exit rule — realised PnL discipline

A position has three exit triggers, whichever fires first:

- **Take-profit: +8%** on the token leg. Modest by memecoin standards;
  appropriate for the Sharpe-~0.5 stability posture and the corpus reach
  bias toward thicker tokens.
- **Stop-loss: -5%** on the token leg. Asymmetric TP/SL (+8 / -5) reflects
  that Gecko gating is *meant* to skew the entry distribution positive; if
  it doesn't, the SL is what enforces honesty.
- **Time stop: 36 hours.** Forces realisation inside the 7-day window
  (`assumed`, verify in OKX docs on next probe). A position closed flat at
  the time stop still counts toward Participation volume; a position
  held open at window-close counts nothing.

All three close via `onchainos swap execute` on the reverse leg. The close
fill price is the realised PnL number; unrealised mark-to-market never
enters the ledger as PnL.

### 3.4 Volume targeting — explicit

**We are targeting Participation ($100 cumulative volume + maintain $100
balance), NOT the $1,000 leaderboard gate.**

- $100 cumulative volume = ~4 round-trip trips at $25 ticket
  (4 × $25 × 2 legs = $200 traded, of which only the buy legs are
  generally counted as "volume" — verify the OKX counting convention on
  the §6 probe; assume buy-leg-only as a conservative planning number,
  so 4 entries = $100).
- **Target: 6–8 entries over 7 days.** A 20–30% margin above the $100
  gate so a single bad fill or a contest-counting edge case doesn't
  drop us below.
- We do **not** chase $1,000. Reaching it on $100 capital requires
  ~20 entries (~3/day), which on this token universe with a 36h time
  stop is *mechanically* incompatible with the spec. Forcing it would
  mean either (a) firing through the verdict gate (defeats the wedge)
  or (b) shrinking tickets below the $20 minimum (fees eat the edge).
  Either path produces a worse Sharpe and no leaderboard placement
  (see §7). The Participation payout is the rational target.

### 3.5 Drawdown discipline

- **Hard stop at wallet balance ≤ $90:** cease all new entries; let open
  positions run to their TP/SL/time-stop; do not re-open until the contest
  window closes.
- This serves two purposes: (i) protects the $100 Participation balance
  requirement with a $10 buffer for fees+slippage drift, (ii) bounds the
  contest downside to $10 in absolute terms.
- **Soft alert at ≤ $95:** down-size next ticket to 15% of balance, no
  concurrent positions.

### 3.6 Re-verdict cadence (apply the trade-vertical convention)

Per CLAUDE.md trade-vertical conventions, the agent does **not** verdict
per-tick. It verdicts on:

- Pre-entry evaluation (§3.2 step 3).
- Circuit-breaker trip (drawdown soft alert §3.5) → re-verdict open
  positions to confirm the exit thesis hasn't inverted.
- Scheduled basic refresh every 24h.
- Idea-hash change (a candidate that was rejected 12h ago and now has
  meaningfully different on-chain facts triggers a fresh verdict).

Cache-then-charge is moot here (`X402_MODE=stub`, $0/call) but the cadence
discipline still matters for *behavior realism* — we are validating the
gate the production oracle uses, not bypassing it.

### 3.7 X-Layer use?

**No.** Rationale:

- Gecko corpus reach on X-Layer-native tokens is **near-zero** — the canon
  is Solana/EVM-DeFi-heavy; X-Layer tokens will mostly return `REFINE`
  / abstain, producing no actionable entries.
- The X-Layer instrument list and DEX depth are unverified at our $30
  ticket size (no data in supported-chain.md §1.1).
- A single chain (Solana) simplifies the ledger, the close-mechanics, the
  fee model, and the operational surface. Multi-chain adds operational
  risk for no expected verdict-gate edge.

Stay on Solana. Document the X-Layer exclusion in the pre-registration
so it cannot be revisited mid-window.

---

## 4. Counterfactual ledger spec — shadow-baseline arm

Adapted from the #128 yield-verdict ledger schema in
`2026-05-19-gecko-verdict-demo-comparison-design.md` §2.3. Same append-only
JSONL discipline, same "immutable decision row + single settled-patch"
contract.

**Path:** `tests/demo/contest_runs/2026-05-DD-okx-contest-cycle-01.jsonl`

**Row schema (one per *decision*, both arms):**

```json
{
  "run_id": "okx-contest-2026-05-DD",
  "decision_id": "uuid",
  "arm": "gecko|shadow_baseline",
  "ts_decided": "2026-05-DD HH:MM:SSZ",
  "candidate_token": "JTO",
  "pair": "JTO/USDC",
  "chain": "solana",
  "onchainos_facts": {
    "price_usd": 0.0,
    "depth_score": 0.0,
    "safety_tags": ["lp_locked", "no_honeypot", ...],
    "quoted_round_trip_bps": 150
  },
  "ticket_budget_usdc": 25.0,
  "verdict": "GO|REFINE|PIVOT|null",
  "confidence_bucket": "emerging|established|senior",
  "surviving_dissent": "string|null",
  "citation_count": 3,
  "low_grounding": false,
  "decision": "deposit|downsize|decline",
  "deposit_size_usdc": 25.0,
  "is_shadow": false,
  "exit_rule": {"tp_pct": 0.08, "sl_pct": -0.05, "time_stop_h": 36},
  "outcome": {
    "ts_settled": null,
    "exit_trigger": null,
    "realised_pnl_usdc": null,
    "realised_pnl_bps": null,
    "fees_paid_usdc": null,
    "settled": false
  }
}
```

### 4.1 The shadow arm — what "the ungated agent would have done"

**Single-wallet constraint forces the baseline to be paper, not real.** We
have one $100 wallet; we cannot run the Gecko arm with real money AND a
parallel baseline arm with real money. The baseline is therefore a
**shadow ledger** computed from the same onchainOS facts the Gecko arm saw.

**Shadow decision rule (frozen in pre-registration):**

- For every Gecko-arm decision point, write a paired `arm: shadow_baseline`
  row with `is_shadow: true`.
- Shadow decision = "the onchainOS-only signal would have *acted* if the
  candidate cleared a fixed depth/safety threshold from `onchainos defi`
  (depth_score ≥ X, no failing safety tag) — irrespective of Gecko verdict."
  Numeric thresholds pre-registered before window open.
- Shadow position sizing identical to Gecko-arm rule (§3.1) — 25% ticket,
  hard cap 2.
- Shadow exit identical to Gecko-arm rule (§3.3) — same TP/SL/time-stop.
- Shadow outcome computed from the **same fill prices** the live trade
  would have hit (use the `onchainos swap quote` round-trip estimate; if
  the candidate was traded in the Gecko arm, reuse the realised fills).

### 4.2 What the shadow arm proves / doesn't prove

**Proves:** whether Gecko's verdict gate *changed* the entry set in a way
that improved realised PnL on this contest run. The McNemar/paired-bootstrap
machinery from #128 §3 carries over — same statistical contract, just on
trade decisions instead of yield deposits.

**Does NOT prove:** any rate, percentage, or "X% better" claim on N<25
discordant decisions. With 6–8 entries planned (§3.4), this contest run
is **directional illustration only**, per the #128 §3.2 honest-thresholds
table. The contest is one cycle of an ongoing measure, not a one-shot proof.

### 4.3 Pre-registration block

Before the **first** live trade, freeze a `preregistration` block at the top
of the ledger containing: verdict-gate thresholds (§3.2), exit rule (§3.3),
shadow decision rule (§4.1), drawdown stop (§3.5), and the explicit
statement: *"This run is directional illustration; no rate or percentage
claim will be made from N < 25 discordant decisions."*

---

## 5. What ships in the public artifact

Distinct from any prize. The point is the *public demonstration of the
methodology* — the contest is the dogfood vehicle.

| File | Format | Content |
|---|---|---|
| `tests/demo/contest_runs/2026-05-DD-okx-contest-cycle-01.jsonl` | JSONL | Full immutable ledger, all decision rows + settled outcomes (both arms) |
| `tests/demo/contest_runs/2026-05-DD-okx-contest-cycle-01.preregistration.json` | JSON | Frozen pre-registration block (thresholds, exit rule, claim discipline) |
| `docs/strategy/2026-05-DD-okx-contest-results.md` | Markdown | Post-window narrative: setup, the spec, the realised entries with verdict snippets, the shadow counterfactual, the headline number (per §4.2 honesty thresholds), what we learned about the corpus's reach in live execution |
| `tests/demo/contest_runs/_trend.json` (append) | JSON | One row for this cycle in the running trend table (#128 §5 — repeatable cycles) |
| Public `gecko_trade_research` verdict envelopes (extracted) | JSONL | Per-decision verdict snapshots; demonstrates the citations + surviving_dissent on real trade calls |

**Out of scope of the public artifact:** wallet addresses (already public
per OKX TEE pattern but no need to amplify), exact fee numbers from the
sub-account beyond what's in the ledger, any forward-looking claim.

---

## 6. Pre-flight checks — read-only ops sequence

Each line is a single concrete CLI/MCP call. Execute IN ORDER before any
execution; abort the run if any fails.

1. **Sub-account binding verified**
   `onchainos wallet status`
   → expect `loggedIn: true` AND `subAccount: <expected-contest-alias>`.
   If `subAccount` is the wrong alias, re-bind before going further (per
   `project_okx_wallet_alias_2026_05_11`).

2. **Starting balance on the right Solana address**
   `onchainos wallet balance --chain solana`
   → expect USDC balance ≈ $100, SOL balance > 0 (gas float). Record the
   exact starting balance for the ledger's pre-registration block.

3. **Trade-routing reachability — read-only quote on the universe**
   `onchainos swap quote --chain solana --from USDC --to JTO --amount 25`
   then the same for each token in §2.1 you intend to consider.
   → expect a route returned for each, with round-trip <200 bps. Tokens
   that fail this check drop out of the universe BEFORE pre-registration.

4. **Skill-guard scan on the registered contest skill**
   `onchainos skill scan gecko-yield-verdict` (or the trade-skill equivalent
   once registered)
   → expect `status: pass` and the manifest hash matches the committed
   `SKILL.md`. A failing scan blocks the run — fix it offline and re-scan
   before window open.

5. **Gecko oracle reachable at `X402_MODE=stub`**
   `curl -s https://api.geckovision.tech/trade_research -d @sample-jto.json`
   → expect a verdict envelope (`verdict`, `confidence`, `surviving_dissent`,
   `citations`) with `citation_count ≥ 1`. A 500 or empty citations zeroes
   the Gecko arm; do not start the run.

6. **Pre-registration block committed**
   The JSON described in §4.3 written to disk and *committed to git on a
   feature branch* before the first live trade. Pre-registration is what
   makes the result quotable; an uncommitted block does not count.

---

## 7. Competition diagnostics — prior OKX agentic contests

**Honest read of what we know:**

- **Window length: 7 days, ASSUMED.** The founder's brief says "7-day window
  assumed (verify in OKX docs if you find different)." The four shared docs
  do **not** state a contest window. **Open question — verify on the OKX
  contest landing page before pre-registration.** If the window is shorter
  (3–5 days) the §3.4 volume target needs the same downsizing; if longer
  (10–14) the §3.3 time-stop can stretch to 48–72h.
- **Prior winner profile:** WIDE PRIOR. We do not have published leaderboard
  data from prior OKX agentic contests. Reasoned inference: leaderboard-gated
  ($1,000 volume) PnL%-leaderboard prizes historically favor **volume-spikers
  on volatile memecoins with leverage** — neither of which is in our spec.
  The realistic top-100 PnL% in a 7-day Solana-spot contest at small capital
  is plausibly +30% to +200%; capturing top-100 with a Sharpe-0.5 stability
  posture is **not realistic** and we should not pretend it is.
- **Implication:** confirming what the founder already decided — we are
  **not** chasing leaderboard placement. The contest's value to us is
  (a) the Participation reward as a small offset, (b) the public artifact
  in §5 as a defensible demo of grounded-verdict gating, (c) the trend-row
  in `_trend.json` as the first live-money cycle of the ongoing measure
  defined in #128 §5.

**Per `feedback_okx_no_funding_pressure`:** $100 is not the prize, the
artifact is. The brief is built around that.

---

## 8. Open questions to resolve before pre-registration

These can ONLY be answered against the live MCP / OKX docs on the next
read-only probe. They are listed so the founder can clear them in one pass.

1. **Contest window length** — 7d assumed; verify (§7).
2. **Volume-counting convention** — buy-legs only, or both legs, or notional?
   Drives §3.4's entry count from "6–8" to "3–4 or 12–16."
3. **OKX MCP per-call USDT fee, if any** — the agentic-wallet doc says
   "MCP services may charge a fee paid in USDT" without numbers (§1.2).
   Could quietly erode the $100 balance.
4. **Realised round-trip fee at $25 ticket on the §2.1 tokens** — measure
   on §6 step 3; replace the §1.3 WIDE PRIOR band with the actual quote.
5. **Whether `onchainos swap execute` exposes `slippage_bps` and
   `max_acceptable_round_trip_bps` parameters** — the spec assumes both
   exist; if not, the §3.2 step-2 reject-at-200bps gate moves into our own
   pre-quote loop.

---

## 9. Report-back summary (per brief)

- **Strategy spec one-pager (entry/exit/sizing/drawdown):** §3.
- **Top-3 candidate instruments:** **JTO, JUP, PYTH** — thick Solana
  liquidity at $30 ticket, strongest corpus reach for `act`-class
  verdicts, named in the canon corpus tags directly. Add KMNO as #4 to
  close the loop with the parallel yield-verdict demo.
- **Single biggest execution risk:** **the close leg.** A position with a
  verdict-gated `act` entry that subsequently can't realise PnL inside the
  time-stop (either because slippage on the exit leg blew out or because
  the price drifted into the dead zone between TP and SL and time-stopped
  flat-minus-fees) is the dominant failure mode. Two round-trip fee rounds
  on every realised trade against a Sharpe-~0.5 expected edge means the
  fee budget eats ~60–80% of the per-trade EV on the §2.1 universe at
  $25 ticket. Mitigation: the §3.2-step-2 reject-at-200bps gate, the §3.4
  6–8 entry cap (not 20), and the §3.1 $20 minimum-ticket floor.
- **Rule clarifications that could change the math:** §8 lists five. The
  highest-leverage ones are (1) contest window length and (2) volume-
  counting convention; either could move the §3.4 entry-count target by
  2x in either direction and should clear before pre-registration.

---

**Done-criteria for this brief:** §3 is executable as written, §4 ledger
spec is unambiguous, §6 pre-flight is six concrete calls, §8 open
questions are listed not hidden. The brief does not commit to any trade
and does not flip `X402_MODE`. Both gates from project memory are
respected.
