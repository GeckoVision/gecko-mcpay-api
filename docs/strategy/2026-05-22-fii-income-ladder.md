# The FII-Anchored Income Ladder — a real plan against real money

**Date:** 2026-05-22
**Branch:** `s41/oracle-real-execution`
**Author:** quant-analyst
**Companion:** `docs/strategy/2026-05-22-calibration-validation.md` (the edge data this plan is gated on)

> Founder philosophy this doc obeys: *"avoid speed, get data, study, stop intuiting
> and start predicting."* Nothing below promises a return the data has not shown.
> Where the data is silent, this doc says so.

---

## The situation (real numbers)

| | Amount | Rate | Risk | Currency | Cadence |
|---|---|---|---|---|---|
| **FIIs (existing)** | ~40,000 BRL | ~371 BRL/mo = **0.93%/mo ≈ 11.7%/yr, tax-free** | low, FGC-adjacent | BRL | monthly |
| **Crypto system (today)** | ~$100 ≈ **500 BRL** | unproven (n=2 live trades) | high | USD | none yet |

Goal: a continuous ladder to generate **371 BRL/month, then 500 BRL/month** from the
crypto system.

FX assumption used throughout: **BRL/USD ≈ 5.0** (1 USD = 5 BRL). This is a *stated
assumption*, not a constant — see the FX-risk note.

---

## 1. The honest comparison — crypto-yield does NOT beat the FIIs risk-adjusted

| Dimension | FIIs | Crypto USDC yield (Kamino ~6%/yr) |
|---|---|---|
| Net rate | **0.93%/mo (11.7%/yr), tax-free** | ~0.5%/mo (~6%/yr), **lower** |
| Risk | low; real-asset backed; FGC-adjacent | smart-contract risk, **USDC depeg risk, no insurance** |
| Currency | BRL (matches your expenses) | **USD → BRL/USD FX risk on every BRL you actually spend** |
| Liquidity | monthly distribution, T+2 sale | instant, but bridging/off-ramp friction + spread |

**Plainly: crypto *yield alone* is a strictly worse deal than your FIIs** — lower
return, higher risk, plus a currency mismatch your FIIs don't have. If the only thing
crypto did was earn yield, the correct move would be to put nothing into it and keep the
FIIs.

**The only reason to hold crypto capital is GROWTH / trading-alpha — and that edge is
currently UNPROVEN.** Live history is n=2 trades. The 2026-05-22 calibration validation
(companion doc) found the momentum signal's gross edge (~+0.1%/trade) is **smaller than
round-trip fees**, i.e. net-negative in every regime tested, with CIs excluding zero on
the *losing* side. We do not yet have a measured, positive, fee-net edge. **Until we do,
treating crypto as an income source is intuiting, not predicting.**

---

## 2. Capital-for-income table

Capital required to throw off a target monthly income, at a range of **net monthly**
rates. `capital = income / monthly_rate`. (Computed; see reproduce block.)

| Net monthly rate (annualized) | Risk / status | Capital for **371 BRL/mo** | Capital for **500 BRL/mo** |
|---|---|---:|---:|
| 0.5%/mo (6.2%/yr) — **yield-only, Kamino USDC** | low-ish, +depeg/FX | **74,200 BRL** | **100,000 BRL** |
| 0.93%/mo (11.7%/yr) — **FII benchmark** | low, tax-free | 39,892 BRL | 53,763 BRL |
| 1%/mo (12.7%/yr) — **conservative blended** | moderate, partly unproven | **37,100 BRL** | **50,000 BRL** |
| 2%/mo (26.8%/yr) — *if-proven* trading-blended | high, **UNPROVEN** | 18,550 BRL | 25,000 BRL |
| 3%/mo (42.6%/yr) — *if-proven* trading-blended | high, **UNPROVEN** | 12,367 BRL | 16,667 BRL |
| 5%/mo (79.6%/yr) — *if-proven* trading-blended | very high, **UNPROVEN** | 7,420 BRL | 10,000 BRL |

**The trade-off, stated plainly:**
- To hit the income target at **low (yield) risk**, you need **FII-like-or-MORE capital**
  (74k–100k BRL for yield-only; ~40–54k at FII-equivalent rate). You do not have spare
  capital of that size beyond the FIIs themselves.
- The only way **less capital** hits the target is at **higher monthly rates** — and
  every rate above ~1%/mo is **trading-alpha that is currently unproven and high-risk.**
  The 2%/3%/5% rows are *hypotheticals labelled "if-proven"* — they are NOT forecasts.
- **FX overlay:** every row is in BRL via an assumed 5.0 FX. A 10% BRL appreciation
  (USD→BRL falls to 4.5) cuts the BRL value of USD-denominated crypto income by 10% —
  on top of the trading risk. FIIs carry zero FX risk. This makes the high-rate rows
  *even less* attractive on a risk-adjusted basis than the headline number suggests.

What ~500 BRL (today's crypto capital) actually produces per month, for scale:
0.5%/mo → **2.50 BRL/mo**; 2%/mo → 10 BRL/mo; 5%/mo → 25 BRL/mo. At current capital,
even an unproven 5%/mo edge is **rounding error** against the 371 BRL target. **Capital,
not rate, is the binding constraint right now.**

---

## 3. The continuous ladder — capital AND edge gated

The ladder advances only when BOTH a capital threshold and an edge-proof gate are met.
This is deliberately slow — per the founder's philosophy, the gates are the point.

### Stage A — PROVE THE EDGE + BUILD THE YIELD FLOOR (now → edge measured)
- **Capital range:** $100–$1,000 (500–5,000 BRL). Small enough that loss is tuition.
- **Edge gate (the prerequisite to leave this stage):** a measured, fee-net positive EV
  with a 95% CI **excluding zero on the positive side**, on **N ≥ ~70 floor-passing
  trades in the relevant regime** (the calibration validation shows N=5–7 today — a
  ~10–14× data shortfall). Anchor the rate on the *validated* number from Deliverable 1,
  **not an assumed 2%/mo.** Today that validated number is **negative net of fees** — so
  the gate is currently **NOT met.**
- **Income drawn:** **ZERO.** Reinvest everything. Do not pull a single BRL.
- **Action:** keep the bot live at small size purely to *generate data*; run the
  calibration harness on a rolling window; in parallel, stand up the low-risk USDC yield
  floor (Kamino) with a *small* allocation to learn the operational round-trip
  (deposit/withdraw/off-ramp), NOT for income. The yield floor's job in Stage A is
  operational readiness + a small real return, not replacing the FIIs.

### Stage B — PARTIAL INCOME (edge proven AND capital sufficient)
- **Capital range:** ~5,000 → ~18,000 BRL.
- **Prerequisite:** Stage A edge gate **passed** (positive fee-net EV, CI excludes zero,
  adequate N) AND capital large enough that the *measured* rate × capital ≥ a meaningful
  fraction of 371 BRL. At a *proven* 2%/mo, 18,550 BRL → 371 BRL/mo; at a conservative
  proven 1%/mo you need 37,100 BRL.
- **Income drawn:** begin drawing **only the portion above a reinvestment floor** —
  e.g. draw 50% of realized monthly profit, reinvest 50%, never touch principal.
- **Action:** scale capital via *contributions* (see the reality check below), keep
  re-validating the edge each window; if the edge degrades (CI re-crosses zero), **stop
  drawing and drop back to Stage A.** The ladder is reversible.

### Stage C — SCALE TO TARGET (371 → 500 BRL/mo)
- **Capital range:** 18,000 → 25,000+ BRL (at proven 2%/mo) or 37,000–50,000 BRL (at
  conservative 1%/mo).
- **Prerequisite:** edge proven *and stable across multiple windows*, capital at the
  table threshold for the target.
- **Action:** draw the full 371, then 500 BRL/mo; keep the FIIs untouched as the floor.

### The reality check that dominates the ladder

Growing from 500 BRL by **reinvestment alone** (no added capital), to the capital that
replaces the FII income:

| Target capital | @1%/mo | @2%/mo | @3%/mo | @5%/mo |
|---|---:|---:|---:|---:|
| 5,000 BRL (Stage A→B) | 19.3 yr | 9.7 yr | 6.5 yr | 3.9 yr |
| 18,550 BRL (371/mo @2%) | 30.3 yr | 15.2 yr | 10.2 yr | 6.2 yr |
| 37,100 BRL (371/mo @1%, FII-like) | 36.1 yr | 18.1 yr | 12.1 yr | 7.4 yr |

**Even at an (unproven, very aggressive) 5%/mo, reinvesting from $100 takes ~4 years
just to reach the Stage A→B threshold.** From $100, returns barely move the needle —
month-1 at 2%/mo on 500 BRL is **+10 BRL.** The ladder is therefore driven by **added
capital**, not by compounding the $100:

| Monthly top-up (reinvested into base, @2%/mo) | after 12 mo | after 24 mo |
|---|---:|---:|
| +0 BRL/mo | 634 BRL | 804 BRL |
| +100 BRL/mo | 1,975 BRL | 3,846 BRL |
| +371 BRL/mo (= recycle FII income IN) | 5,610 BRL | 12,091 BRL |

**Conclusion baked into the ladder:** the crypto base grows on a useful timescale ONLY
if fed by contributions (salary, or — once the edge is proven — recycling FII
distributions into the crypto base). Compounding $100 alone is a multi-decade path. This
is *why* income-drawing is a late-stage event: there is nothing to draw until capital is
scaled, and capital scales from contributions + a proven edge, not from the starting
$100.

---

## 4. The honest recommendation

1. **Keep the FIIs as the stable BRL income floor. Do not touch them.** They are
   0.93%/mo, tax-free, low-risk, BRL-denominated, FX-free — strictly better than crypto
   yield and currently better than the (negative) measured crypto trading edge.

2. **Treat crypto as the GROWTH ENGINE, not an income source — yet.** It converts to
   income only after the edge is *measured positive net of fees with a CI excluding
   zero and adequate N* (Stage A gate), AND capital is scaled to the table threshold
   (Stage B/C). Both gates. Today, **neither is met.**

3. **Do NOT move FII money into crypto to chase income.** That is the wrong-risk move:
   it swaps a proven 0.93%/mo tax-free BRL stream for an unproven, fee-negative,
   FX-exposed, uninsured one. Even *if* the edge later proves out, the right response is
   a **measured, capped allocation** sized to what the data supports — never a wholesale
   migration. The FII floor is the thing that lets you take crypto risk at all.

4. **Stage A is the whole job right now: get data, validate, build the yield-floor
   operations — draw nothing.** This is the founder's philosophy applied to money:
   stop intuiting a 2%/mo edge; measure it. The calibration harness is how you replace
   the adjective with the interval.

---

## Reproduce

```bash
python3 - <<'PY'
targets=[371,500]
rates={"yield 0.5%":0.005,"conservative 1%":0.01,"FII 0.93%":0.0093,
       "if-proven 2%":0.02,"if-proven 3%":0.03,"if-proven 5%":0.05}
for n,r in rates.items():
    print(f"{n:<18} 371->{371/r:>9,.0f} BRL  500->{500/r:>9,.0f} BRL  ({(1+r)**12-1:.1%}/yr)")
PY
```

All figures BRL at assumed FX 5.0. Crypto trading-rate rows labelled "if-proven" are
hypotheticals, NOT forecasts — the only measured crypto rate to date (calibration
validation, 2026-05-22) is **negative net of fees**.
