# gecko-claude — Builder Bootstrap scaffold for Claude Code

[![Claude Code](https://img.shields.io/badge/claude--code-MCP-D97757.svg)](https://docs.anthropic.com/claude/claude-code)
[![x402](https://img.shields.io/badge/x402-Solana-9945FF.svg)](https://x402.org/)
[![frames.ag](https://img.shields.io/badge/wallet-frames.ag-000000.svg)](https://frames.ag/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)

**Turn a startup idea into a validated brief, paid for on-chain, ready for Claude Code to build.**

One Claude Code skill. Three MCP tools. Real Solana payments via [frames.ag](https://frames.ag). No API keys, no signup, no credit card — just a wallet.

The Python backend lives in [`gecko-mcpay-api`](https://github.com/ernanibmurtinho/gecko-mcpay-api) (private). The web frontend lives at `gecko-mcpay-app`. This repo is the **user-facing scaffold** — what `curl | bash` drops into your project.

---

## Install

```bash
curl -fsSL https://app.geckovision.tech/install.sh | bash
```

Then open Claude Code in the same directory and paste:

```
Read https://app.geckovision.tech/skill.md and follow the instructions.
```

Claude walks you through wallet setup (email + OTP, ~30 seconds) and funding (~$5 USDC covers ~50 sessions).

## What's in this repo

| Path | Purpose |
|---|---|
| `install.sh` | One-line installer (`curl \| bash`); idempotent, mac+linux. |
| `skill.md` | Master entry point hosted at `app.geckovision.tech/skill.md`. |
| `.claude/skills/` | 5 skills wrapping the MCP tools and wallet flows. |
| `.claude/agents/` | 5 sub-agent personas (analyst, validator, architect, builder…). |
| `CLAUDE.md` | Working agreement that ships into the user's project. |
| `.mcp.json.template` | MCP registration template copied to `.mcp.json`. |
| `docs/flow.md` | End-to-end sequence diagram (cold install → first paid result). |

## What you get

| Tool | Cost | What it does |
|---|---|---|
| `gecko_research` | **$0.10** (basic) / **$0.75** (pro) | Validates an idea. Returns business plan, validation report with citations, V1/V2/V3-scoped PRD. |
| `gecko_ask` | free | Follow-up Q&A grounded in indexed sources. |
| `gecko_sources` | free | Lists every source with chunk counts. |
| `extract-page` | ~$0.004/URL | Tavily Extract for bot-walled pages. |
| `fund-wallet` | — | Walks the user through topping up their frames.ag wallet. |

Plus:

- **Per-project budgets** — `gecko project init my-idea --budget 5.00` (soft cap in v1, cryptographic isolation in v2 via Privy).
- **On-chain receipts** — every paid call has a real Solana transaction signature; `gecko-mcp economics <session_id>` shows the margin math.

## How it works

```
1. You paste one line into Claude Code
   ↓
2. Claude orchestrates: install → wallet OTP → fund prompt → MCP register
   ↓
3. You ask for research: "Use gecko_research to validate: <idea>"
   ↓
4. frames.ag wallet pays $0.10 USDC on Solana → gecko-api runs the workflow
   ↓
5. Full PRD lands in your context. Sub-agents help you build from it.
```

End-to-end: ~3 minutes from cold install to a research result in context. Full sequence in [`docs/flow.md`](./docs/flow.md).

## Cost transparency

Per session at $0.10 retail:

| Line | Real cost |
|---|---|
| LLM (gpt-4o-mini orchestration) | $0.0030 |
| Embeddings (text-embedding-3-small) | $0.0012 |
| Tavily (source discovery) | $0.0080 |
| **Total** | **$0.0122** |
| **Margin** | **$0.088 (88%)** |

Run `gecko-mcp economics <session_id>` after any session to see the full breakdown.

## Sub-agents (`.claude/agents/`)

After your `gecko_research` lands, five pre-baked personas help you build:

| Agent | Role |
|---|---|
| `research-analyst` | Explore the result; run free `gecko_ask` follow-ups. |
| `market-validator` | Adversarial reader of the validation report. |
| `technical-architect` | Translate `prd.v1_scope` into Next.js + Tailwind + Supabase. |
| `validator` | Pre-implementation sanity check (catches V2-in-disguise scope). |
| `builder` | Scaffolds via `npx create-next-app`; implements V1 only. |

## Skills (`.claude/skills/`)

| Skill | Purpose |
|---|---|
| `gecko-research.md` | Paid validation entry point. |
| `gecko-ask.md` | Free follow-ups grounded in indexed sources. |
| `gecko-sources.md` | Free; lists sources for the active session. |
| `extract-page.md` | Paid Tavily Extract (~$0.004/URL) for bot-walled pages. |
| `fund-wallet.md` | Wallet topping-up flow. |

## Roadmap

- ✅ **v1** (this repo) — terminal-first; project budgets policy-bounded.
- ⏳ **v2** — Privy direct integration for cryptographic per-project wallet isolation.
- 🔜 **v3** — branded frontend at `app.geckovision.tech` for project dashboards + economics charts.

## License

MIT. See [`LICENSE`](./LICENSE).

---

*Builder Bootstrap Platform · geckovision.tech · No API keys, just a wallet.*
