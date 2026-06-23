# Gecko Decision Firewall — End-to-End Architecture

> Code-grounded map. Current as of **June 2026**. Companion to [`../PRD.md`](../PRD.md),
> [`../concepts/jito-101.md`](../concepts/jito-101.md), [`../concepts/solana-101.md`](../concepts/solana-101.md).
>
> **Honesty legend:** **SHIPPED** = wired + tested e2e in-process · **DARK** = code exists,
> gated OFF in prod · **DESIGNED** = spec'd, little/no code · **MISSING** = not built.
>
> **The one-paragraph truth:** the firewall *engine* is real and provably catches attacks
> in-process (the surfpool fork demo runs the **actual** pipeline). But it is **DARK in prod**
> (no live data flows yet), the **verdict ledger — the stated moat — is not wired** (one
> unconnected anchoring primitive exists), and the **SendAI "agent checks before it acts"
> surface does not exist** (the in-repo `sendai` modules are *execution* stubs). The pipeline
> in the middle is sound; the gaps are at the two ends (live ingest in, ledger out) and the
> distribution surface. The prototype slice (§6) lights up every box once.

---

## 1. The shape in one line

`on-chain launch → ingest → per-mint state → 12 fused signals → verdict (ok/caution/block) → cache → /safety surface → agent/launchpad acts → verdict → ledger`

Gecko **verifies**; it never executes, custodies, or reorders. Everything below is that one pipeline.

---

## 2. End-to-end data flow

```
                        ┌──────────────────── INGEST ────────────────────┐
  Solana mainnet        │ pool_discovery_runner → pool_resolver           │
  AMM init logs ──DARK─▶│   logsSubscribe(AMM) → getTransaction → track   │
                        │ launch_runner.LaunchRunner.track_pool           │
                        │   ├ accountSubscribe(vaults) → swap_parser ─DARK─┤→ SwapEvent
                        │   └ logsSubscribe→getTransaction→tx_parser ─DARK─┤→ ParsedSwap
                        └──────────────────────┬──────────────────────────┘
   ┌─ fork demo (SHIPPED, local) ─┐           │ (same LaunchRunner, fork data)
   │ fork_adapter → surfpool 127.0.0.1│───────┘
   └──────────────────────────────────┘        ▼
                        ┌──────── STATE (SHIPPED, pure) ──────────────────┐
                        │ token_state.TokenState per mint                  │
                        │  .to_snapshot()→wash inputs  .to_snipe_snapshot()│
                        └──────────────────────┬──────────────────────────┘
                        ┌──────── SIGNALS (SHIPPED, pure, fail-OPEN) ─────┐
                        │ wash_signals (F1 loop·F2 self·F4 sybil·F5 bait)  │
                        │ snipe_gate: co_buy·jito_bundle·fresh_swarm·      │
                        │   fee_outlier·unknown_program(I2)·shared_alt·    │
                        │   lp_drain·concentrated_capture                  │
                        │ inputs: program_reputation·alt_identity·jito·    │
                        │         jito_tips.TipFloor (live REST)           │
                        └──────────────────────┬──────────────────────────┘
                        ┌──────── FUSION (SHIPPED, pure) ─────────────────┐
                        │ launch_monitor.recompute → precomputed.safety_gate│
                        │   → "ok|caution|block|unknown" + labels         │
                        └──────────────────────┬──────────────────────────┘
                        ┌──────── CACHE (SHIPPED) ────────────────────────┐
                        │ HotpathCache (in-proc TTL, per-key lock)         │
                        └──────────────────────┬──────────────────────────┘
   ┌──────────────────────── SURFACE ─────────────────────────────────────┐
   │ POST /safety  (warm-first; COLD MISS → static-only)        [SHIPPED]   │
   │ MCP gecko_safety → /safety                                 [SHIPPED]   │
   │ MCP gecko_trade_research = the PAID oracle (separate)      [SHIPPED]   │
   │ SendAI pre-trade check (agent calls /safety, acts on gate) [MISSING]   │
   └──────────────────────────────┬───────────────────────────────────────┘
        ┌──── ENFORCEMENT ─────────┘        ┌──── LEDGER (the moat) ────────┐
        │ Token-2022 hook + denylist PDA     │ receipt/hash (SHIPPED, pure)  │
        │                       [DESIGNED]   │ anchor_receipt→devnet memo     │
        └────────────────────────────────────│   (BUILT, 0 callers)          │
                                             │ commit-before-resolution[MISSING]│
                                             │ outcome-grading        [MISSING]│
                                             │ verdict persistence    [MISSING]│
                                             └───────────────────────────────┘
```

**Edge status:** every **internal** edge (state→signals→fusion→cache→/safety→MCP) is SHIPPED + tested. Every **live-chain** edge is DARK (gated by `GECKO_FIREWALL_ENABLED`, default off + needs `HELIUS_API_KEY`). Every **ledger** edge and the **SendAI-consumer** edge are MISSING. Enforcement is DESIGNED.

---

## 3. The pipeline, stage by stage (review spine)

1. **Ingest** — `launch_runner.py`, `pool_discovery_runner.py`, `pool_resolver.py`, `tx_parser.py`, `swap_parser.py`, `helius.py`/`helius_rpc.py`. Free "logs" mode (`logsSubscribe`→`getTransaction`→`parse_swap_tx`) vs paid "subscribe" mode, selected by `firewall_tx_mode()`. **DARK in prod** (gated). The surfpool **fork demo drives this exact runner** with fork data — the live wire is proven, just pointed at a fork.
2. **State** — `token_state.TokenState` accumulates `SwapEvent` + `ParsedSwap` per mint; emits `FirewallSnapshot` (wash) + `SnipeSnapshot` (snipe). Pure accumulator, **no thresholds**. SHIPPED.
3. **Signals** — `wash_signals` (F1/F2/F4/F5), `snipe_gate` (8 signals incl. `concentrated_capture`, the evasion-catch), fed by `program_reputation` (I2), `alt_identity`, `jito`, `jito_tips`. Pure, fail-OPEN. SHIPPED. *(Two live-fidelity holes: `alt_identity.PUBLIC_ALTS` ships empty → will FP on Jupiter ALTs until populated; `wallet_age_s` always None → `fresh_wallet_swarm` can't fire on live data without a creation-slot lookup.)*
4. **Fusion → verdict** — `launch_monitor.recompute` → `precomputed.safety_gate` → `ok|caution|block|unknown` + snipe/wash labels. One canonical gate, duck-typed (no orchestration import). SHIPPED.
5. **Cache** — `HotpathCache` (in-proc TTL, per-key asyncio lock); warm read = dict lookup + `is_fresh()`, single-digit ms. SHIPPED. *(Evaporates on TTL/restart — not persistence.)*
6. **Surface** — `POST /safety` (`safety_fast.serve_safety`): warm-first; **cold miss = static contract read only** (wash/snipe `None`). `gecko_safety` MCP tool → `/safety` (free). `gecko_trade_research` = the paid oracle (separate panel). The **SendAI pre-trade consumer is MISSING**. SHIPPED except SendAI.
7. **Enforcement** — Token-2022 transfer-hook + denylist PDA. DESIGNED, 0% built. (Signal layer ≠ enforcement layer — fine by positioning.)
8. **Ledger (the moat)** — `payments/receipt/hash.py` (canonical hash, SHIPPED) + `anchor_receipt` (devnet SPL-memo, BUILT but **0 callers**) + `/v1/receipt/verify` (SHIPPED). **No verdict is persisted anywhere today.** Commit-before-resolution + outcome-grading are MISSING. This is the biggest gap between positioning and code.

---

## 4. Component table

| Component | File | Status | Note |
|---|---|---|---|
| Discovery / resolve | `pool_discovery_runner.py`, `pool_resolver.py` | DARK | gated; pure parts testable |
| Live runner | `launch_runner.py` | DARK | `build_runner` returns None unless enabled+key |
| Tx / reserve parsers | `tx_parser.py`, `swap_parser.py` | SHIPPED | live Helius payload shape unverified (Pattern E) |
| Per-mint state | `token_state.py` | SHIPPED | accumulator, no thresholds |
| Wash signals | `wash_signals.py` | SHIPPED | F1/F2/F4/F5 + launch FP guard |
| Snipe gate | `snipe_gate.py` | SHIPPED | 8 signals; `concentrated_capture` = evasion catch |
| Program rep / ALT / Jito | `program_reputation.py`, `alt_identity.py`, `jito.py`, `jito_tips.py` | SHIPPED | `PUBLIC_ALTS` empty (FP risk live); tip floor = live REST |
| Gate kernel | `precomputed.py` | SHIPPED | one canonical gate + `PrecomputedSafety` + `SafetyStore` |
| Cache | `cache.py` | SHIPPED | in-proc TTL |
| Monitor | `launch_monitor.py` | SHIPPED | `recompute` is the heart |
| /safety | `gecko-api safety_fast.py`, `main.py` (/safety, lifespan) | SHIPPED / runner DARK | cold path = static only |
| MCP | `gecko-mcp server.py` (`gecko_safety`), `api_client.py` | SHIPPED | free firewall surface |
| Receipt | `payments/receipt/{hash,anchor,verify}.py`, `routes/receipt.py` | hash/verify SHIPPED; anchor BUILT 0-callers | the ledger primitive |
| Fork proof | `sandbox/launch_firewall/{fork_adapter,fork_pool,fork_attack,defense_harness}.py` | SHIPPED (local) | reuses the real stack |
| SendAI | `exec_adapters/sendai.py`, `gecko-trade-agent/.../sendai_adapter.py` | STUB (execution, not /safety) | the firewall-consumer surface is unbuilt |

---

## 5. Honest gaps (in priority order)

1. **The verdict ledger (the moat) is not wired.** No verdict is persisted — not Mongo, not Supabase, not on-chain. `anchor_receipt` is built with **zero callers**. The moat is currently a design + one unconnected primitive.
2. **The firewall is DARK in prod.** `/safety` in prod only serves the static cold path; wash/snipe are always `None` on a real call. The wedge runs only in the fork demo + tests. Needs `GECKO_FIREWALL_ENABLED=1` + a Helius plan, *after* a real-launch threshold backtest.
3. **The SendAI firewall-consumer surface does not exist.** "Agent checks before it acts" is asserted but unbuilt (in-repo `sendai` is execution-only).
4. **Enforcement (Token-2022 hook) is design-only.**
5. **Two live-fidelity holes** in otherwise-solid signals: empty `PUBLIC_ALTS` (FP risk) + missing `wallet_age_s` (fresh-swarm can't fire live).
6. **Cold-path is weaker than warm** — the first caller for an unseen mint (exactly the block-0 checker) gets static-only until the monitor accumulates.

---

## 6. The minimal prototype slice — "every box lights up once"

One runnable path: **fork launch → real signals → verdict → served over `/safety` → consumed by a SendAI-style pre-trade check → verdict written to a ledger row (+ optional devnet receipt).**

**Reused as-is (no new code):** the whole `hotpath/` stack + `LaunchMonitor.recompute`; the fork wire (`fork_adapter`/`fork_pool`/`fork_attack`); `POST /safety`; the receipt primitives; `defense_harness.py --mode fork`.

**New glue, in build order (~90 lines total):**
1. **Share one monitor (dev entrypoint, ~20 lines).** Construct one `LaunchMonitor`, hand it to both `LaunchRunner(ws→surfpool)` and a local FastAPI `app.state.safety_monitor`, so `POST /safety {mint}` returns the **live fork verdict with wash+snipe populated** (not the static cold path). *This is the crystal-clear moment.*
2. **`pretrade_check(mint) → {proceed, gate, reasons}` (~40 lines, the MISSING surface).** Calls `/safety`, `proceed = gate != "block"` (caution → proceed-with-flag). Wrap it with the **same `submit()` signature** as the SendAI exec adapter so it reads as "the gate the SendAI adapter consults before executing." ATTACK mint → `proceed=False`; ORGANIC → `proceed=True`.
3. **`record_firewall_verdict(...)` (~30 lines, the moat seam).** On each verdict, write one row **committed before the launch resolves**: `{mint, gate, snipe_label, snipe_fired, wash_label, computed_at, idea_hash}` to a Mongo `firewall_verdicts` collection (outcome-grading is a later batch job that backfills `resolved_outcome`). Optionally call the already-built `anchor_receipt(envelope)` → store `receipt_sig` (gives it its first caller; verifiable via `/v1/receipt/verify`).
4. **Assert the chain (reuse).** Extend `defense_harness.py --mode fork`: attack → `proceed=False` + ledger row `gate=block` (+ receipt verifies); organic → `proceed=True` + row `gate∈{ok,unknown}`.

After this slice, every box in §2 has executed once on a real (fork) launch, and the two MISSING edges (SendAI-consumer, ledger) exist in their thinnest honest form — the right base to harden toward §7.

---

## 7. Target architecture (the hardening path)

- **V1 (prototype slice, §6):** fork data, in-proc, Mongo ledger row + devnet receipt. *Proves the whole chain.*
- **V2 (go-live):** swap fork→live Helius behind `GECKO_FIREWALL_ENABLED` (needs a plan with `transactionSubscribe` or the free logs path); populate `PUBLIC_ALTS` + wire `wallet_age_s`; **run the real-launch threshold backtest** (the gate to charging); SendAI Agent-Kit action published to distribution.
- **V3 (the rail):** outcome-grading job → the labeled-attack benchmark (the moat compounds); Token-2022 enforcement hook for launchpads; Verification NCN (restaking) — see [`jito-101.md` §8](../concepts/jito-101.md).

---

## 8. The one one-way-door decision

Most of the slice is two-way (iterate freely): the dev entrypoint, `pretrade_check` shape, file layout. **One-way (design now, before writing rows you'll grade for months):** the **`firewall_verdicts` row schema** and the **receipt hash spec** (`receipt/hash.py` is already a published contract). The verdict envelope persisted in Step 3 + the `idea_hash`/grading keys *are* the moat's schema — get those field names right first. This is where to spend rigor before prototyping the ledger step.
