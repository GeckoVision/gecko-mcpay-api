# Roadmap — Self-Hosted, Multi-Wallet Agent Hosting (the "Gecko-hosted fleet" vision)

*2026-05-22. Captured from the founder's product vision + a 5-specialist engineering
review (staff, web3, defi, quant, ai-ml) of the "Hybrid AG2 + ElizaOS + OKX +
Cloak.ag + Gecko" architecture diagram. This is a FUTURE roadmap — nothing here
is committed for the current sprint. The live $100 proof bot keeps running.*

---

## 1. The vision (founder's words, refined)

A user runs a local Gecko agent, then **one-click moves it to a hosted server**.
We host the compute; the user keeps control of the funds. They can:

- **Copy-trade style** (mirror a Gecko-curated strategy), OR **run their own strategy** — both authored/validated by Gecko.
- Run **multiple strategies at once**, each with its **own wallet and its own limits** (like the OKX copy-tradeable grid bots: different risk profiles per bot).
- **Protect their wallets and control their funds** — we host, but custody stays with the user.
- Use **privacy specifically for the vault** where they store profits.

Capital trajectory that frames the whole roadmap:
- **Now:** ~$100, one strategy, adjusting the bot.
- **Near:** start with **$3–5k**.
- **Recurring:** move **~2k BRL/month (~$400) into a profit vault.**

This is **non-custodial managed hosting**: we run the agent + the Gecko oracle;
the user holds the keys (e.g. Privy embedded) and funds each strategy wallet.

## 2. The product shape

| Capability | What it is |
|---|---|
| One-click hosting | Local agent → hosted instance, no devops for the user |
| Strategy source | Copy a Gecko-curated strategy, or deploy your own — all Gecko-validated |
| Multi-wallet | One wallet per strategy; per-wallet limits, isolation, kill-switch |
| Fund control | Non-custodial — user holds keys; we host compute only |
| Profit vault + privacy | Sweep realized profits to a vault; optional privacy shield on the vault |

## 3. The architecture (what the team endorsed — and what to build vs integrate)

**Build exactly one box: the Oracle. Everything else is a swappable partner adapter.**

```
            ┌───────────────────────────────────────────┐
   BUILD →  │  GECKO ORACLE  (verdict envelope = the moat)│
            │  grounded SAFE/DEFER/REJECT + citations +    │
            │  surviving dissent, metered over x402       │
            └───────────────────┬───────────────────────┘
                                 │  versioned envelope (one-way contract)
            ┌───────────────────▼───────────────────────┐
   BUILD →  │  PYTHON EXECUTOR  (deterministic, per-wallet)│
            │  consumes ONLY the envelope; code-pinned     │
            │  coordinator; per-wallet breaker + spend cap │
            └──┬─────────────┬──────────────┬────────────┘
        adapter slots (INTEGRATE, never hard-couple — neutrality rule):
   executor = {okx, sendai, backpack}   venue = {jupiter, kamino, drift}
   custody  = {privy(self-host), okx-tee(managed)}   privacy = {none, cloak}
   prices   = {pyth, venue}             facilitator = {frames, cdp, cloudflare}
```

**The keystone (all five agreed):** the **verdict envelope** is both the moat and
the integration contract. "Executor consumes ONLY the Gecko verdict envelope" is
the genuinely strong idea in the diagram. Version it; publish it as the x402
product surface. It's a one-way decision — spend the rigor there.

### Strategy instance = (immutable spec + dedicated wallet + isolated state dir + own circuit breaker)
Run N instances under a dumb supervisor (separate processes / systemd / pm2) —
**not** a multi-strategy orchestrator that multiplexes wallets in one process.
The current code is ~70% shaped for this already (per-instance breaker +
artifact logger). Hard prerequisite before N>1: fix the **process-global
`circuit_breaker_state.json` path** so instances don't clobber each other.

## 4. Engineering team verdict (5 specialists, strongly convergent)

**Reject ElizaOS as the decision-executor** (staff + ai-ml + web3). An LLM-agent
loop executing trades contradicts our core discipline (decision logic in CODE,
not prompts) and adds nondeterminism + a fund-moving prompt-injection surface.
ElizaOS at most = a deployment/connector shell wrapping the Python executor,
partner-driven — never an internal rewrite of a working executor.

**It's a kitchen sink — redraw partners as adapter slots** (staff + web3 + defi).
AG2/ElizaOS/Cloak.ag/Kamino/OKX/Privy/Pyth are six partner integrations drawn as
owned architecture. That violates wallet/facilitator neutrality. If a slot has
only one possible vendor, that's a coupling bug.

**"7 voices" is vanity — prove by ablation** (ai-ml). Our 4 voices work because
they're orthogonal (price / ADX-regime / realized-PnL / risk-veto). Added voices
help only if decorrelated; correlated voices inflate false consensus (Pattern D).
Run a voice-ablation replay on the artifact logs before adding any.

**Kamino-as-execution-venue is a category error** (defi). It's lend/LP, not a
swap venue — you can't execute a momentum entry through it. Keep Kamino strictly
as **optional idle-yield on non-deployable capital.**

**Cloak.ag / ZK shielding: defer, but the VAULT use-case is the legit one**
(web3 + defi). Shielding *active* DEX trades buys ~nothing (the swap is public on
the AMM) and breaks the observability our logger/PnL/breaker depend on. BUT
shielding a **profit vault / treasury** is exactly where privacy *does* matter
("size-is-alpha" / don't-dox-your-treasury). The founder's framing (privacy for
the vault, not the trades) is correct — scope it there, opt-in, partner-driven.

**Custody is the real multi-wallet implication** (web3). OKX TEE keys are
non-exportable → cannot do user-funded self-hosted per-strategy wallets. Self-host
= **Privy-embedded** (we already have `wallets/privy.py`). TEE = managed product;
Privy = self-host. Two backends behind one `WalletHandle`, never co-mingled.
`live_buyer.py` is single-keypair today → needs per-wallet key resolution before
any multi-wallet live flip. (Correction to earlier notes: the *core* live x402
buyer IS implemented + contract-tested; only the contest *wrap* hard-requires stub.)

## 5. The quant gate (capital-staged — this drives sequencing)

**Multi-wallet is operational risk-isolation, NOT a returns win by itself.**
- Two momentum sleeves: ρ≈0.7–0.9 → **~1.05× Sharpe** (worthless).
- Momentum + an **uncorrelated** sleeve (stablecoin yield ρ≈0): **~1.4–1.6× Sharpe.**
  The prize is the correlation, not the count.
- Capital fragments below **~$300–500/sleeve** (min trade size + slippage on
  Solana DEX). At $100 split 6 ways you can't size a position. Multi-wallet earns
  its keep at **≥~$2k total with ≥2 validated, uncorrelated strategies.**
- **N strategies = N multiple-comparisons traps** — pre-register hypotheses,
  Bonferroni the "this sleeve is winning" claims (~0.05/N), report PnL with
  bootstrap CIs, walk-forward only. Current live result (2W/0L, +$1.05) is **n=2
  — statistically silent.** Don't fan out an unvalidated edge across wallets.

**This maps cleanly onto the founder's capital trajectory:**
- **At $100 (now):** one strategy + a **stablecoin/Kamino yield base** sleeve
  (single wallet). Highest-EV move on the board; also delivers passive income.
- **At $3–5k:** multi-wallet / multi-strategy becomes viable (clears the sizing
  floor) → the hosted multi-wallet product makes sense.
- **Recurring (2k BRL/mo → vault):** the **profit-vault sweep** + optional
  vault privacy. Idle vault capital earns yield (Kamino Lend USDC ~3–8%; Sanctum
  LST for SOL ~7–9%). NOTE: **JLP is NOT "safe stablecoin yield"** — it's a
  volatile, short-trader-PnL position; gate it like any directional strategy.

## 6. Capital-staged sequencing

**Stage 0 — now (~$100):** validate the single momentum strategy live; add the
**yield-base sleeve** (Kamino USDC lend on idle capital). Single wallet + caps.

**Stage 1 — V-next (1–2 sprints, no new framework):**
- Version the **verdict envelope** schema (one-way contract; software-engineer + staff sign-off).
- Make **strategy instance** a first-class unit (spec + wallet + isolated state dir) under a dumb supervisor; fix the state-path collision.
- `WalletHandle` abstraction with **Privy (self-host)** + TEE (managed) backends.
- Cheap wins (next bot restart, once no live position is open): **Pyth conf/staleness gate**, **live indexes in the studio dashboard** (ADX/RSI/MFI per token), per-instance state dir.

**Stage 2 — V2 (gated on ≥$2k + ≥2 uncorrelated strategies):**
- One-click hosted deployment (non-custodial; we host compute, user holds keys).
- Per-strategy wallet funding UX; per-wallet limits/breakers.
- **Shared cross-instance oracle cache** keyed on `idea_hash` (else N agents = N× oracle spend — the economics invert).
- Copy-trade strategy distribution + per-strategy x402 metering (one billing wallet per user, strategy-tagged; strategy wallets only touch the venue).
- ElizaOS *only* as an optional deployment/connector shell, if a distribution reason appears.

**Stage 3 — far-future / research:**
- Profit-vault **privacy** (Cloak.ag shielded vault, opt-in).
- Portfolio-level kill-switch (when live N actually grows — N momentum bots are one bet in a reversal).
- Additional uncorrelated strategy sleeves (mean-reversion, market-neutral), each validated before funding.

## 7. Deliberately deferred / cut (and why)
- **ElizaOS as executor** — cut (contradicts decision-in-code; nondeterminism + attack surface).
- **Kamino as execution venue** — cut (category error); keep only as idle-yield.
- **ZK shielding of active trades** — cut (buys nothing, breaks observability); keep only for the vault.
- **"7 voices" as a target** — defer to an ablation result, not a headline number.
- **Auto-allocator that splits a parent deposit** — defer (re-creates custodial blast radius); keep funding explicit per wallet in v1.

## 8. Open questions
1. Managed-hosting custody: even "non-custodial," do we ever hold keys transiently (deploy/restart)? Privy embedded + user-held = cleanest; confirm OKX onchainOS permits non-TEE keys in its runtime (else self-host forks off the onchainOS executor — a `solana-architect` + `defi-engineer` question).
2. Copy-trade mechanics: mirror at the *signal* level (re-run each user's gate on their wallet) vs the *fill* level (replicate trades)? Signal-level keeps each user's risk caps honest; fill-level is simpler but couples users.
3. Profit-vault definition: a separate Solana wallet, a Kamino position, or a shielded pool? Drives the privacy + yield design.

## 9. The moat to lead with (Pattern D)
Not orchestration (AG2/ElizaOS are table stakes). The wedge is **a verdict you can
trust enough to hand a self-hosted executor unsupervised**: the code-pinned
deterministic-veto coordinator + grounded citations + realized-outcome memory,
delivered as a versioned envelope over x402. Everything else is chassis.
