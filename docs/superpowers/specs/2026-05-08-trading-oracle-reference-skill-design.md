# Trading-Oracle Reference Skill — Design

**Date:** 2026-05-08
**Status:** Design — pending user review
**Owner:** ernanibmurtinho
**Sprint:** S23 (extends FIX-12 marketplace routing)

## 1. Why

A partner is building a paid Claude Code skills marketplace with two adopters today and a possible 10k-user distribution path. We've decided Gecko positions as **KaaS / knowledge oracle**, not a marketplace, not a trading service (see `memory/project_kaas_positioning_2026_05_08.md`).

The fastest way to make that positioning real is to ship one concrete reference integration: a "trading-oracle" Claude Code skill that calls Gecko for grounded verdicts, prints a mock execution intent for a user-chosen venue, and never custodies funds or signs transactions.

Building this also unblocks two things we've been wanting:
- First end-to-end live x402 buyer spend (paysh + bazaar). The buyer wallet has been blocked since 2026-05-08 morning (`memory/project_buyer_wallet_blocker_2026_05_08.md`); this design funds it.
- First Solana-DeFi corpus on top of FIX-12's marketplace routing — proves the "Pioneer-as-bounty" thesis with real revenue share to paysh/bazaar contributors.

## 2. Scope

### In scope
- Buyer wallet provisioning (Solana mainnet, $20 USDC cap).
- Curated trading-oracle prompt against paysh + bazaar live x402 services, scoped to **Solana DeFi only** (Jupiter, Kamino, Jito, Pyth, Drift, Orca, Raydium, Meteora, MarginFi, Sanctum, etc).
- Live ingest of paid responses → MongoDB chunks (`provider_kind ∈ {paysh_live, bazaar_live}`, `vertical=defi-trading`).
- Reference skill in `gecko-claude/examples/trading-oracle/`:
  - `skill.md` — Claude Code skill manifest.
  - `.mcp.json` — mounts `mcp.geckovision.tech`.
  - `example_call.py` — Kamino / lana.ai-style **intent payload** (never signs).
  - `README.md` — one-paste install instructions.
- Smoke verification: install skill in Claude Code → trading question → verdict cites paysh/bazaar chunks → mock intent payload printed.

### Out of scope (explicit)
- New `gecko_market_context` thin tool. Use existing `gecko_research` / `gecko_ask`. Add only if step-7 latency is unacceptable.
- Signed verdict envelope + canonical viewer at `app.geckovision.tech/v/<id>`. Deferred — V2 trust primitive.
- Partner co-listing in their marketplace. Deferred — follow-up after the example proves out.
- Multi-chain coverage (EVM). Deferred.
- Real Jito/Kamino execution. The example **never signs**; it prints intent only.
- **Hand-rolling Kamino-specific knowledge inside our example.** Delegated to `solana-claude`'s `defi-engineer` agent (Superteam Brasil collaborator). We don't redo what they already ship.

### Hard non-goals (do not drift)
- No custody. No signing. No order routing. No private-key handling in the skill.
- No trading recommendation verbs ("buy", "sell"). Output is advisory + bucketed confidence.

## 3. Components

```
gecko-mcpay-api (this repo)
├── packages/gecko-core/
│   ├── payments/              ← buyer wallet wired here (already shipped)
│   └── ingestion/             ← new: trading-oracle ingest entrypoint
├── scripts/trading_oracle/
│   ├── prompt.md              ← curated prompt (drafted in §4 below)
│   ├── run_live_ingest.py     ← orchestrator: paysh+bazaar list → filter → live call → chunk → ingest
│   └── budget_guard.py        ← hard $20 cap, refuses next call if exceeded
└── docs/superpowers/specs/2026-05-08-trading-oracle-reference-skill-design.md  (this file)

gecko-claude (sister repo)
└── examples/trading-oracle/
    ├── skill.md               ← installs solana-claude alongside (Superteam Brasil bundle)
    ├── .mcp.json              ← mounts mcp.geckovision.tech
    ├── example_call.py        ← calls Gecko for verdict, hands intent shape to solana-claude's defi-engineer agent
    └── README.md              ← one-paste: install solana-claude + Gecko skill, run prompt
```

## 4. The trading-oracle prompt (draft)

Crafted to maximize relevance against paysh/bazaar Solana-DeFi listings. To be refined with `ai-ml-engineer` review before live spend.

> "Acting as a Solana DeFi trading research oracle: for the protocols Jupiter, Kamino, Jito, Pyth, Drift, Orca, Raydium, Meteora, MarginFi, Sanctum, and Sanctum Infinity, retrieve and summarize current operational facts that affect a trader's decision-making — pool TVL trends, fee tiers, oracle staleness windows, recent governance / parameter changes, audit status, known incident history within the last 90 days, and integration partners. Cite source per fact. Do not produce buy/sell recommendations; produce *parameters a trader's agent needs to reason*."

Refinement criteria before spending:
- ai-ml lens: does the prompt over-fetch (too many protocols at once)? Should we batch by protocol class (DEX vs LST vs perps)?
- Filtering criteria for paysh/bazaar listings: keyword match on `solana`, `dex`, `lst`, `perp`, `oracle`, `liquidity`, `staking`. Skip listings that don't pattern-match.

## 5. Data flow

1. `run_live_ingest.py` calls paysh `/list` and bazaar catalog, filters to Solana-DeFi-relevant.
2. For each candidate, `budget_guard.py` checks remaining budget against the listing's posted price. Skip if over budget or projected total > $20.
3. Live x402 call via existing `LiveX402Client.charge` (already shipped, see `packages/gecko-core/src/gecko_core/payments/`).
4. Response → chunk → embed (Voyage 1024) → insert to MongoDB with `provider_kind={paysh_live|bazaar_live}`, `vertical=defi-trading`, `freshness_tier=daily` (new field, see §7).
5. Skill at install time mounts `mcp.geckovision.tech` AND installs `solana-claude` (Superteam Brasil bundle) via `curl -fsSL https://raw.githubusercontent.com/solanabr/solana-claude-config/main/install.sh | bash`. User prompt routes through `gecko_research` (or `gecko_ask` for follow-ups) with `vertical=defi-trading`.
6. Verdict returns with citations including paysh/bazaar chunks. The skill **hands the verdict to solana-claude's `defi-engineer` agent**, which owns Kamino-specific intent payload shape (Kamino, Jupiter, Drift, Raydium, Orca, Meteora — per their published agent table). The intent is rendered as a Python dict, **never signed**. This keeps lane boundaries clean: Gecko = oracle (knowledge + verdict), solana-claude = execution-domain expertise (intent shape), user-chosen venue = settlement.

## 6. Error handling

- **Budget exhausted:** ingest stops cleanly, logs remaining budget, writes a `partial_corpus_marker` to the session record so we know the corpus is incomplete.
- **paysh/bazaar 5xx or x402 facilitator failure:** retry once with backoff; second failure → skip listing, log, continue.
- **No qualifying listings:** abort before any spend; report and re-prompt user with broader criteria.
- **Voyage embed failure during ingest:** loud crash per `feedback_wedge_reachability_check` policy (no silent fallback to OpenAI 1536-dim).

## 7. Schema delta

One new field on chunks (per data-engineer's recommendation): `freshness_tier ∈ {static, daily, live_only}`. For this design, all paysh/bazaar trading-oracle chunks are `daily` — they're paid snapshots, not live prices. Live prices are out of scope for this spec.

If the field doesn't already exist, add migration `infra/supabase/migrations/20260508130000_freshness_tier.sql` (or equivalent Mongo writer change). Default existing rows to `static` to preserve current behavior.

## 8. Testing

Per `feedback_local_api_over_pytest_sweep`: targeted pytest + local API smoke, not full sweep.

- **Unit (light fakes per `feedback_lighter_tests`):** `budget_guard` pure function, prompt template renderer, paysh/bazaar listing filter.
- **Integration:** ingest entrypoint with stubbed paysh/bazaar fixtures (recorded once during the live run via VCR pattern from S12.5).
- **Local API smoke:** `gecko-api` running locally, hit `/research` with `vertical=defi-trading`, confirm corpus chunks present and cited.
- **End-to-end (manual):** install reference skill in a fresh Claude Code session, run a trading prompt, verify verdict + intent payload.

## 9. Step ordering & gates

1. **Founder funds buyer wallet.** Operator-only — see `memory/project_buyer_wallet_blocker_2026_05_08.md` §4 (4-step checklist). Blocking gate.
2. **Refine prompt with ai-ml-engineer.** Cheap, async; can run in parallel with step 1.
3. **Schema delta + budget guard.** Code-level, no spend. Lands before step 4.
4. **Live ingest run.** $20 cap enforced. One-shot.
5. **Reference skill in `gecko-claude`.** Generated once corpus is in. Cross-repo dispatch.
6. **End-to-end smoke + falsifier (Tavily-vs-Gecko on 5 trading prompts).** Decides whether the wedge actually exists.

## 10. Falsifier

If, after the corpus is in and the skill is built, **Gecko's verdict on 5 trading prompts is not measurably better-grounded than raw Tavily** (judged on hallucinated-fact rate against ground-truth protocol docs), the KaaS-oracle thesis is wrong and we should not pursue partner integration. Cheap to run; honest signal.

## 11. Cross-repo

- This repo: ingest scaffolding, schema delta, budget guard, prompt.
- `gecko-claude`: example skill files. Cross-repo dispatch via `frontend-engineer` stub once corpus is in.
- `gecko-mcpay-app`: no work this spec.
- `solana-claude` (Superteam Brasil, external collaborator — `project_solana_brasil_community.md`): we depend on but do not modify. Their `defi-engineer` agent owns Kamino/Jupiter/Drift/Raydium/Orca/Meteora intent shape. We install via their published one-liner and hand off.

## 12. Risks

- **Buyer wallet funded but paysh/bazaar listings don't have enough Solana-DeFi coverage.** Mitigation: step 6 falsifier still runs; the corpus gap itself is a signal to seed more sources.
- **Live ingest spends $20 and produces a thin corpus.** Mitigation: budget guard logs every call's value; we'll know exactly which listings paid off.
- **Latency too high for skill-as-caller.** Mitigation: step 5 explicitly tests; if too slow, ship `gecko_market_context` thin tool as the V1.1 follow-up.
- **Partner's marketplace doesn't ship in time to validate the integration.** Doesn't block — the example skill stands on its own as a public artifact.

---

**Next step after approval:** invoke `writing-plans` to turn this design into the implementation plan.
