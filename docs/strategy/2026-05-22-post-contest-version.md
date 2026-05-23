# Post-Contest Version (v0.2) — release definition + plan

*2026-05-22. The consolidated Gecko system after the OKX contest + the s42 sprint.
"Prepare" = define what ships + the release steps. Live use is GATED on the eval
(a proven edge), per our discipline. We ship the SYSTEM honestly, not a return claim.*

## What the post-contest version IS
The contest entry was a single-strategy gated breakout bot (v0.1). v0.2 is the
**intelligence + safety layer** matured into a coherent, observable, honest system:

- **Direction-aware multi-voice oracle gate** — chart / regime(+DI/−DI) / memory(realized outcomes) / risk, code-pinned coordinator, grounded Gecko Oracle soft-gate (SAFE/DEFER/REJECT + citations).
- **The studio** — live ADX/RSI/MFI/CHOP/bb_width indexes, the agent's reasoning, direction-aware bull/bear triggers, Agent Voices, the Oracle panel, Signal Feed.
- **s42 edge work** — net-flow CVD gate (blocks distribution spikes), multi-timeframe 1h regime modulator (no 5m longs into a 1h downtrend), no-tax liquid universe (PYTH/WIF/JUP/RAY/JTO).
- **The yield pipe** — proven $5 Kamino lend round-trip ($0 net), gate-validated, the stabilizer floor.
- **The honesty discipline** — abstain-not-fabricate, real-fill PnL, the calibration that caught our own −EV; env-gated live (paper-default), non-custodial.
- **Distribution** — the `gecko-okx-quickstart` skill (one-command, paper-default), updated to the v0.2 system.

## What changed since the contest (the story)
| Contest (v0.1) | Post-contest (v0.2) |
|---|---|
| Breakout + local panel, shadow oracle | Direction-aware regime, **active grounded oracle gate**, net-flow + multi-TF |
| 6 meme tokens (incl. high-tax) | 5 no-tax liquid names |
| Black-box-ish decisions | **Full studio**: indexes + the agent's reasoning, visible |
| Paper hides bugs | Caught 3 yield bugs + a −EV strategy + a direction-blind voice — with data, for ~$0 |
| "Did it make money?" | "Can you *trust* it with your money?" — the wedge |

## Release steps (in order)
1. **Eval validates** (the gate) — the 5-day paper run on the full-sprint config; the quant's pre-registered rule decides if the gate is calibrated (and whether the net-flow/multi-TF filters help or over-block). **Live money stays gated on a proven net-positive edge.**
2. **Fix the pre-existing test drift** surfaced this session: `test_btc_overlay_*` (BTC_OVERLAY=None) + `test_max_concurrent_*` (config=2 vs test=1) — stale, not from the sprint. Update or remove.
3. **Merge `s41/oracle-real-execution` → main** (it carries the whole post-contest body: oracle wiring, yield pipe, s42 sprint, the quickstart skill).
4. **Update the `gecko-okx-quickstart` skill** to the v0.2 system (direction-aware regime, net-flow, multi-TF, CHOP, new universe, the studio) — re-run the skill lint.
5. **Tag `v0.2-post-contest`.**
6. **Build-in-public post** — the honest arc (contest → caught our own −EV → built the trust system) per `2026-05-22-positioning.md`.

## The gate (non-negotiable)
- **No live money** until the eval shows a net-positive edge (the fee wall is still the open problem; the s42 filters are the attempt, not yet proven).
- v0.2 ships the **system + the honesty**, not a return number. The provable positive today is the yield pipe + the discipline, not trading alpha.

## Open items feeding the next version (v0.3)
- The fee-beating edge (if the eval shows the s42 filters still don't clear the fee wall, the answer is lower-fee execution / fewer-higher-conviction trades / a different signal).
- Smart-money voice promoted from the net-flow signal (lab → PRD oracle).
- The hosted "safe mode" (non-custodial, Privy) + multi-wallet — per `2026-05-22-self-hosted-multi-wallet-roadmap.md`.

## Status
- s42 sprint: **delivered + deployed to paper** (commits through `c1ee3da` + Wave 2b `e98189a`/`2724b54`).
- Eval: **running** on the full-sprint config.
- Release (steps 2–6): **pending eval validation** — do not merge/tag/ship-live until the eval gives a verdict.
