# OKX Complement-Map + Skill-Publishing Plan — S38-#126 (2026-05-19)

**Mode:** read-only deep research. No code, no spend.
**Frame (already set — not re-litigated):** Gecko *complements*, never competes
with, the OKX skill suite. Every OKX skill *executes* ("do the thing") or
*informs* ("show the data"). None *adjudicates*. `gecko_trade_research` is the
neutral verdict layer one step upstream of every execution skill — the
"should I?" before the "do it." Differential: grounded adversarial verdict that
**abstains rather than fabricates** — 7 voices, surviving dissent, citations —
proven by the S37 6/6 N=57 statistical ship-gate. The OKX skill is distribution
channel #1, not the product.

Sources fetched: `okx/onchainos-skills` (full file tree + SKILL.md + CLAUDE.md
+ marketplace.json + CLI source), `okx/agent-trade-kit` (CONTRIBUTING + docs),
`okx/agent-skills`, `okx.com/llms.txt`, `web3.okx.com/llms-full.txt`. Builds on
`docs/strategy/2026-05-19-okx-skill-quality-feasibility.md` (#125).

---

## 1. OKX skill suite teardown

### Correction to the #125 / 2026-05-11 model — verified against the live repo

The earlier teardown assumed `starter-coach` and a Python skill model. **Neither
exists in `okx/onchainos-skills`.** The verified anatomy:

- **A skill is Markdown only.** Each `skills/<name>/` is a `SKILL.md` (YAML
  frontmatter + CLI command reference prose), plus optional `_shared/*.md`
  (preflight, chain-support) and `references/*.md` (cli-reference, ws-protocol,
  glossaries, troubleshooting). **No Python, no `schema.json`, no per-skill
  `plugin.yaml`.** The 2026-05-11 manifest model (`coach.py`, `schema.json`,
  `primitives/`) is wrong — discard it.
- **The engine is a single Rust binary, `onchainos`** (`cli/`, `clap`-based,
  built for 9 platforms via `release.yml`). The same binary doubles as a
  **native MCP server** (`cli/src/mcp/mod.rs`, `rmcp` v1.1.1). A skill is a
  *prompt-routing document that tells the agent which `onchainos` subcommand to
  shell out to.* `CLAUDE.md` is emphatic: *"NEVER skip CLI calls... Do NOT
  answer from skill files or your own knowledge."*
- **Plugin packaging** is repo-level, not skill-level: `.claude-plugin/`,
  `.codex-plugin/`, `.cursor-plugin/`, `.opencode/` manifests + a
  `marketplace.json` listing one plugin (`onchainos-skills`, MIT, owner OKX).
  Install: `npx skills add okx/onchainos-skills` (auto-detects CC / Cursor /
  Codex / OpenCode) or `/plugin marketplace add okx/onchainos-skills`.
- **The 18 onchainos skills** group as: wallet/portfolio (`okx-agentic-wallet`,
  `okx-wallet-portfolio`, `okx-defi-portfolio`), trade
  (`okx-dex-swap` market orders, `okx-dex-strategy` price-triggered limit
  orders, `okx-dex-bridge`, `okx-defi-invest`), data/intelligence
  (`okx-dex-market`, `okx-dex-token`, `okx-dex-signal`, `okx-dex-social`,
  `okx-dex-trenches`, `okx-dex-ws`), safety/infra (`okx-security`,
  `okx-onchain-gateway`, `okx-audit-log`), routing/meta (`okx-dapp-discovery`,
  `okx-growth-competition`, `okx-how-to-play`), payments
  (`okx-agent-payments-protocol` — x402 `exact`/`aggr_deferred`, MPP, a2a-pay).
- **`okx/agent-trade-kit` is a separate, parallel product** — a TypeScript/pnpm
  CEX MCP server (`okx` CLI: spot/swap/futures/bot/market/earn). Distinct
  binary, distinct API auth (OK-ACCESS-KEY). It carries a
  **`skills` module** — a *marketplace client* (`okx skill search/add/download`)
  that pulls third-party skills off the **OKX Skills Marketplace**. That
  marketplace, not the GitHub repo, is the publishing destination.
- **Two skill ecosystems, two distribution paths.** (a) `onchainos-skills`
  GitHub repo — OKX-authored, MIT, contributions via MR. (b) **OKX Skills
  Marketplace** — third-party skills, downloadable via `okx skill add`, each
  carrying a backend-injected `_meta.json`. The marketplace explicitly disclaims
  review: *"Skills... are created by independent third-party developers. OKX
  does not review or endorse their content."*

### What "good" looks like by their bar (`REVIEWING.md` + `CONTRIBUTING.md`)

- Frontmatter: `---`-delimited YAML; `name`, `description` (80–150 words of
  natural-language trigger phrases — routing is description-driven, 1024-char
  cap), `license: MIT`, `metadata.author`, `metadata.version`.
- `SKILL.md` core under ~500 lines; overflow into `references/`. Standard
  layout `SKILL.md` + `scripts/` + `references/` + `assets/`.
- Mandatory sections: prerequisites/credentials, **Demo vs Live Mode**, Skill
  Routing (Step-0 re-route to peer skills), 3–5-command Quickstart, Command
  Index with READ/WRITE classification, CLI Command Reference param tables, MCP
  Tool Reference mapping, I/O examples, edge cases.
- **Every CLI command / MCP tool listed must actually exist** (verified against
  the binary). WRITE ops need confirmation gates. Cross-skill deps need
  fallback behavior. No internal URLs / credentials / PII. ALL-CAPS reserved
  for safety constraints.

---

## 2. The complement map

Every row: an OKX skill (executes or informs) → the Gecko verdict-layer
"should I?" that runs one step upstream. Gecko consumes OnchainOS-sourced facts;
it never competes as a data feed.

| OKX skill | What it does (execute / inform) | Gecko verdict-layer complement — the "should I?" upstream |
|---|---|---|
| **`okx-dex-swap`** | Executes a market swap NOW at best aggregated price | **Should I make this swap at all?** Verdict on the token + entry timing, grounded in canon (Marks on chasing, Graham margin-of-safety) + on-chain freshness; abstains if corpus has no basis. The single highest-leverage complement. |
| **`okx-dex-strategy`** | Places a price-triggered limit order (buy dip / take profit / stop loss) | **Is this trigger price the right level?** Verdict on whether the dip/TP/SL level reflects a sound thesis vs an arbitrary number; dissent line on the bear case for the level. |
| **`okx-defi-invest`** | Executes deposit/withdraw across Aave/Lido/Kamino/etc. | **Should I deposit into this pool right now?** This is the canonical Class-D question ("should I deposit USDC into Kamino?") — verdict on yield sustainability vs depeg/utilization/protocol risk, cited. |
| **`okx-dex-signal`** | Informs: shows what smart money / KOLs are buying | **Should I follow this signal?** Verdict on whether a whale/KOL buy is a thesis or noise — base-rate framing (Mauboussin), reflexivity caution (Soros). Counters herd-following. |
| **`okx-dex-trenches`** | Informs: scans new meme / pump.fun launches | **Is this launch worth a position?** Verdict gating speculative entries — the abstain-not-fabricate behavior matters most where corpus grounding is thinnest; honest "no basis" beats a confident meme call. |
| **`okx-dex-social`** | Informs: news + market sentiment ranking | **Does sentiment change the thesis?** Verdict that weighs sentiment as one input, not the driver — explicitly resists sentiment-chasing. |
| **`okx-dex-market`** | Informs: prices, K-lines, PnL | **Does this chart support entry?** Verdict overlay on raw OHLCV — turns "here's the candle" into "here's whether the setup holds up." |
| **`okx-dex-bridge`** | Executes cross-chain bridge | **Should I bridge for this opportunity?** Verdict on whether the destination-chain opportunity justifies bridge cost + risk. |
| **`okx-growth-competition`** | Executes: join trading competitions | **Which competition strategy is sound?** Verdict-graded strategy before committing competition capital. |

**Headline rows:** `okx-dex-swap` (every swap deserves a "should I?"),
`okx-defi-invest` (the literal Class-D question in CLAUDE.md), `okx-dex-signal`
(verdict-layer kills the herd-following failure mode no execution skill can).

---

## 3. The wedge — build `okx-defi-invest`'s complement first

**Recommendation:** the first Gecko skill is the **"should I deposit?" verdict
companion to `okx-defi-invest`** — working title `gecko-yield-verdict`.

Justification, recommendation-first:

1. **It is the question the product already answers.** CLAUDE.md's Class-D
   re-route names it verbatim: *"should I deposit USDC into Kamino?"* The S37
   ship-gate corpus (Marks/Damodaran/Berkshire) is densest exactly on yield,
   risk premia, and protocol-quality reasoning — so the abstain-vs-fabricate
   differential is *most visible* here. A meme-launch verdict (`okx-dex-trenches`)
   would be the corpus's *weakest* showing — wrong place to debut.
2. **Lowest friction.** `okx-defi-invest` is informational-then-executing with
   a clean decision boundary: discover pool → **[verdict here]** → deposit.
   Inserting one verdict step needs no change to OKX execution. `okx-dex-swap`'s
   complement is higher *traffic* but its decision point is more time-pressured
   (market order, MEV windows) — a slower oracle call fits a deposit decision
   far better than a market-swap one.
3. **Highest-leverage framing.** DeFi deposits are *recurring, sticky,
   higher-ticket* decisions vs one-off swaps. A yield deposit is a thesis a user
   holds for weeks — exactly where a grounded "should I?" with surviving dissent
   earns repeat oracle calls. It also showcases the moat: yield decisions are
   where canon literature (cycle awareness, margin of safety) genuinely
   out-reasons a price feed.
4. **Clean neutrality story.** A yield-verdict skill is venue-agnostic by
   construction — it grades the *pool*, and `okx-defi-invest` already routes
   across hundreds of protocols. No hard-coding of one venue (CLAUDE.md
   neutrality rule satisfied for free).

Skill shape: a thin `SKILL.md` whose Step-0 router fires on deposit/yield/stake
intent, instructs the agent to first run `onchainos defi` discovery (OKX stays
the **primary data source** — satisfies the hard requirement from #125), then
call `gecko_trade_research` over those OnchainOS-sourced facts, render the
verdict envelope (verdict + confidence + one surviving-dissent line +
citations), and only then hand off to `okx-defi-invest` for execution. Gecko
never sources pool data or executes — it adjudicates between OKX's "show" and
OKX's "do."

---

## 4. Demo / simulation execution mode — assessment

The founder flagged a demo/sim execution asset. **Verified — and it splits two
ways.** The honest read: it is a Pattern-B asset, but a *partial* one.

- **`okx/agent-trade-kit` (CEX side) — full demo asset.** Global `--demo` flag
  on the `okx` CLI: *"Use simulated trading (demo) mode."* `CONTRIBUTING.md`
  documents an OKX **Demo Trading account** (Trading → Demo Trading → API
  Management, `demo = true` in `~/.okx/config.toml`,
  `okx.com/demo-trading`). Smoke + MCP e2e tests run against it with **zero real
  funds**. This is a genuine, falsifiable-before-live sandbox — *but it is for
  CEX spot/swap/futures, not the on-chain `onchainos` path.*
- **`okx/onchainos-skills` (on-chain side) — partial.** There is **no `--demo`
  flag** on the `onchainos` binary. The closest asset is
  `onchainos gateway simulate` — a transaction **dry-run**
  (`POST /api/v6/dex/pre-transaction/simulate`, `cli/src/commands/gateway.rs`):
  it simulates a tx without broadcasting. Plus the README's "built-in sandbox
  keys for testing only." So on-chain swaps/deposits can be *simulated/dry-run*
  but there is no full paper-trading account equivalent.

**For the chosen wedge (`gecko-yield-verdict` on the on-chain path), this is
sufficient.** The Gecko verdict step has no money in it at all — it is a
read-only oracle call. The only money-touching step is the final
`okx-defi-invest` hand-off, and that can be demoed with `onchainos gateway
simulate` (dry-run the deposit tx) plus a sandbox key. Pattern-B holds: the
verdict overlay is built and tested entirely off-chain against the live
`X402_MODE=stub` oracle ($0), and the execution hand-off is dry-run-verified
before any mainnet tx. **No real money is required to build, test, or demo the
wedge skill end-to-end.** What we do NOT get on the on-chain side is a
persistent paper-trading PnL ledger — if a future skill needs that, it lives on
the CEX `agent-trade-kit` side with `--demo`.

---

## 5. Publishing path

Two distinct paths — pick by audience.

**Path A — MR into `okx/onchainos-skills` (the GitHub repo).**
- Add `skills/<name>/SKILL.md` (+ `_shared/`, `references/`). Submit a merge
  request (`.gitlab/merge_request_templates/Default.md` exists — GitLab-mirrored).
- **Format check** (`REVIEWING.md`): `---`-delimited frontmatter; description
  80–150 words; core under ~500 lines; every CLI/MCP tool must *actually exist*;
  cross-skill fallbacks; WRITE-op confirmation gates.
- **Security scan** (`CONTRIBUTING.md` checklist): no internal URLs /
  credentials / PII; WRITE commands flagged with safety notes; all commands
  verified against the binary. `SECURITY.md` governs vuln reporting. *No
  automated scanner is documented* — review is a human checklist against
  `REVIEWING.md`. CI (`ci.yml`) exists but its skill-lint scope is unconfirmed.
- **IP / ownership:** *"By contributing, you agree that your contributions will
  be licensed under the MIT License."* Author retains frontmatter credit. **A
  Gecko skill merged here is MIT-licensed and OKX-co-owned in practice** — fine
  for the `SKILL.md` routing doc (it is just prose), but it means the routing
  layer is open. Gecko's moat is the `api.geckovision.tech/trade_research`
  endpoint behind it, which is *not* in the skill — keep it that way.
- **"Goes live":** MR merged → ships in the next `npx skills add
  okx/onchainos-skills` install. No separate approval step documented beyond
  reviewer sign-off.

**Path B — OKX Skills Marketplace (third-party, via `okx skill` CLI).**
- The marketplace is reachable via `agent-trade-kit`'s `skills` module
  (`okx skill search/add/download`, backend-injected `_meta.json`). Submission
  mechanics for *publishing* to it are **not in any fetched doc** — the repos
  only document the *consumer* side. **This is an unknown (see §7).**
- Marketplace explicitly **does not review or endorse** third-party skills —
  lower bar, but also no quality signal and no OKX co-sign.

**Founder-side prerequisites (flagged):**
- **Identity verification.** No identity/founder-account check is documented
  for an `onchainos-skills` MR — a GitHub/GitLab account suffices. The
  identity-verification surface lives elsewhere: (a) the **OKX Developer
  Portal** API-key path (`OKX_API_KEY/SECRET/PASSPHRASE`) for production use,
  and (b) the OKX **Demo Trading account** for `agent-trade-kit` tests — both
  require an OKX account, which is KYC-gated. The Skills *Marketplace publisher*
  path is the most likely place a real identity check sits, and it is
  undocumented — treat as a founder-decision unknown.
- **IP terms:** Path A = mandatory MIT, OKX-co-owned routing doc. Path B IP
  terms unknown. Either way the verdict endpoint stays Gecko-owned and off-repo.

---

## 6. Skeleton S38 plan — `gecko-yield-verdict` wedge

Not a full plan — a skeleton for founder approval. Two layers per the
three-layer architecture: the **onchainOS spine** (OKX-owned, we only route to
it) + the **Gecko verdict overlay** (our moat).

- **WS-A — Spine wiring (verify, don't build).** Install `npx skills add
  okx/onchainos-skills`; run a real `onchainos defi` discovery call + an
  `onchainos gateway simulate` dry-run; confirm the binary's exact `defi`
  subcommand surface from `okx-defi-invest/references/cli-reference.md`. ~0.5 day.
- **WS-B — `gecko_trade_research` reachability probe.** Confirm the live
  `api.geckovision.tech/trade_research` endpoint returns the verdict envelope
  (verdict / confidence / surviving_dissent / citations) for a yield question
  ("should I deposit USDC into Kamino"), `X402_MODE=stub`, $0. End-to-end probe
  per Pattern E. ~0.5 day.
- **WS-C — Author `skills/gecko-yield-verdict/SKILL.md`.** Frontmatter +
  Step-0 router (deposit/yield/stake triggers) + Command Index + Demo-vs-Live
  section + the verdict-render block + the `okx-defi-invest` hand-off + a
  graceful "oracle unavailable → baseline" fallback (a 500 must not brick a
  judge run). Mirror `okx-dex-strategy/SKILL.md` structure; ~500-line cap. ~1 day.
- **WS-D — Verdict-render + citation formatting.** The originality wedge:
  decide how verdict + one surviving-dissent line + citations render in-terminal
  without being janky. Coordinate `product-designer`. ~0.5 day.
- **WS-E — End-to-end smoke + dry-run demo.** Full path: `onchainos defi`
  discovery → `gecko_trade_research` verdict → `onchainos gateway simulate`
  deposit dry-run. No mainnet tx. ~0.5 day.
- **WS-F — Submission decision gate.** Path A (MR) vs Path B (marketplace) vs
  ship via `gecko-claude` only. Decide after WS-E demos cleanly — optionality
  over leaderboard rank, per `feedback_okx_no_funding_pressure`.

Rough sequencing: WS-A ∥ WS-B (parallel, day 1) → WS-C (days 1–2) → WS-D
(day 2) → WS-E (day 3) → WS-F gate. ~3 days. Handoffs: `software-engineer`
(no Python in the skill itself — but the `/trade_research` endpoint behind it
is theirs), `ai-ml-engineer` (verdict envelope shape), `product-designer`
(WS-D render), `web3-engineer` (WS-A `onchainos` install + dry-run).

---

## 7. Unknowns — founder decisions

1. **Path A vs Path B.** MR into the OKX repo (MIT, OKX co-sign, quality bar)
   vs the third-party Marketplace (no review, no co-sign) vs `gecko-claude`-only
   distribution. The frame says "distribution channel #1" — which channel?
2. **Marketplace publisher onboarding** is fully undocumented in the fetched
   sources — including whether it carries a real identity/KYC check and what IP
   terms apply. Needs a direct check on the OKX Developer Portal / Skills
   Marketplace publisher console before committing to Path B.
3. **MIT co-ownership of the `SKILL.md`.** Accept that the routing doc is open
   and OKX-co-owned (moat stays in the endpoint), or hold the skill private?
4. **`gecko_trade_research` uptime during any judging window** — a judge
   hitting a 500 zeroes the run; the WS-C fallback mitigates but does not
   eliminate this.
5. **CEX vs on-chain wedge.** This plan picks the on-chain `okx-defi-invest`
   complement. The CEX `agent-trade-kit` `--demo` path is a stronger *sandbox*
   — if a persistent paper-PnL track record (Tier-2 proof agent) is wanted,
   that argues for a CEX-side skill instead. Founder call on which ecosystem.
