# User-Facing Repo Plan — `gecko-claude`

**Date:** 2026-04-27 · pre-Shipathon (~5 days)
**Source:** staff-engineer dispatch
**Companion:** `docs/scaffold-and-pro-tier-plan.md` (the broader roadmap), `docs/auth-frames-bearer.md` (web3-engineer, in flight)

---

## 1. Frontend decision

**Decision: Option C — terminal-first now, branded frontend post-Shipathon.**

Why:
- The wedge is "paste one line into Claude Code, get superpowers." A frontend isn't on that critical path. frames.ag already owns the funding surface — duplicating it before Shipathon is brand vanity, not user value.
- 5 days is exactly enough to ship a bullet-proof scaffold + skill.md + install.sh + an OTP flow that works inside Claude Code. Adding even an MVP Next.js dashboard halves the polish budget on the thing judges will actually see (the Claude Code demo).
- Post-Shipathon, the dashboard becomes a real product surface: project list, per-session economics, fund buttons, marketing pages. We already have `gecko-mcpay-app` scaffolded for that. Don't pre-build it.
- Honest tradeoff: users briefly leave Claude Code to fund at `frames.ag/u/{username}`. 30-second context switch with a recognizable brand. Acceptable.

Reversibility: two-way. Frontend can ship anytime post-Shipathon.

---

## 2. Repo structure for `gecko-claude` (new public MIT repo)

```
gecko-claude/
├── README.md                  # one-line install + 60-second demo gif
├── LICENSE                    # MIT
├── install.sh                 # bootstrap (see §3)
├── CLAUDE.md                  # working agreements (no secrets, x402 ground rules,
│                              #   "the wallet is the only credential")
├── .claude/
│   ├── skills/
│   │   ├── gecko-research.md  # wraps the MCP tool, names the price, JSON shape
│   │   ├── gecko-ask.md       # free follow-up
│   │   ├── gecko-sources.md   # free, list sources
│   │   ├── fund-wallet.md     # opens frames.ag/u/{u}, instructs reload
│   │   └── extract-page.md    # paid Tavily wrapper (already implemented)
│   └── agents/
│       ├── research-analyst.md
│       ├── market-validator.md
│       ├── technical-architect.md
│       ├── validator.md
│       └── builder.md
├── .mcp.json.template         # gecko + supabase pre-registered placeholders
└── docs/flow.md               # sequence diagram
```

**No `apps/starter-nextjs/` in v1.** The `builder` agent scaffolds one on demand via `npx create-next-app`. Shipping a stale skeleton creates maintenance debt with zero day-1 user value. Add post-Shipathon if user research shows demand.

V1 skill set deliberately small: 3 Gecko tools + fund-wallet + extract-page. `transcribe-audio`, `search-x`, `deep-research` arrive in Phase D as separate PRs to this repo — they're independent.

---

## 3. `install.sh` — line-by-line at a high level

1. `set -euo pipefail`; detect OS (mac/linux), abort on Windows with WSL hint.
2. Verify `python3 >= 3.11`, `claude` CLI, `uv` (auto-install uv via astral.sh if missing).
3. `uv tool install gecko-mcp` (from PyPI; fall back to git+subdirectory until published).
4. Detect git root vs cwd; copy `.claude/`, `CLAUDE.md`, `.mcp.json` into target dir (prompt before overwrite).
5. `claude mcp add gecko -- gecko-mcp serve`.
6. Print next-step banner: "Open Claude Code in this directory and say `Read app.geckovision.tech/skill.md`".

**`install.sh` does NOT touch the wallet.** Wallet/OTP happens *inside* Claude Code via the skill — that's the demo magic.

---

## 4. Hosting `install.sh`

**Decision: serve from `https://app.geckovision.tech/install.sh`** (302 redirect to GitHub raw `main`; mirror on GitHub raw).

Why: branded URL is cleaner for the one-line demo (`curl … geckovision.tech/install.sh | bash`) and survives a repo rename. solana-claude-config serves raw GitHub directly; we benefit from the brand domain because the user reads the URL out loud during demo.

Reversibility: one-way-ish. Once shared, we can't change the path. Lock now.

---

## 5. Auth + identity

**Decision: identity = frames.ag `apiToken`, sent as bearer to `gecko-api`.**

Why:
- frames.ag already issues + manages it via OTP. Re-issuing a Gecko-specific token is duplicate state with no security gain — frames.ag holds the wallet keys, they're the trust anchor either way.
- Server-side, `gecko-api` validates the token by calling frames.ag once per request (cached, short TTL) and derives `username` → that's our session scope.
- One credential to lose, one to rotate, one to revoke. Web3-engineer's bearer middleware lands on this exact contract.
- Trade-off: we depend on frames.ag uptime for auth. Acceptable — we already depend on them for payments.

Reversibility: two-way. Adding a Gecko-issued token later is additive (exchange the frames token for ours at connect time).

---

## 6. `skill.md` sketch (~350 words rendered)

Frontmatter: `name: gecko`, description matching today's file. Body sections:

1. **What you're installing** — one MCP server, three tools, prices in dollars (not tokens).
2. **Step 1 — Run the installer**: `curl -fsSL https://app.geckovision.tech/install.sh | bash` (Claude Code runs it for the user).
3. **Step 2 — Connect your frames.ag wallet** (inside Claude Code, no browser):
   - Ask user for email.
   - `POST https://frames.ag/api/connect/start {email}` → "I sent you a 6-digit code. Paste it back here."
   - User pastes code → `POST /api/connect/complete` → save `{apiToken, username}` to `~/.agentwallet/config.json` (chmod 600).
4. **Step 3 — Fund your wallet**: print `https://frames.ag/u/{username}`, tell user "$5 USDC covers ~50 basic sessions; come back when funded." `gecko-mcp doctor` re-checks balance.
5. **Step 4 — Run your first research**: `Use gecko_research to validate: <idea>`. First call surfaces the x402 prompt; user approves; ~60s later they get plan + validation + PRD.
6. **Notes for Claude Code**: never ask for API keys, redact apiToken in logs, the wallet is the only credential, link to `app.geckovision.tech/skills/` for more.

---

## 7. Naming

**Decision: `gecko-claude`.**

Why: `gecko-scaffold` reads internal-tooling. `gecko-bootstrap` collides with the literal "Builder Bootstrap" product name (confusing in docs). `gecko-claude` mirrors `solana-claude-config`'s naming convention exactly — users searching that pattern find us — and signals the surface (Claude Code) without overclaiming.

Public, MIT.

Reversibility: one-way once install URL ships. Decide now.

---

## 8. Top three risks

1. **frames.ag OTP-in-terminal UX is novel.** If `/api/connect/start` rate-limits or email is slow, demo stalls in the most visible moment. Mitigation: smoke-test 10 cold OTPs end-to-end this week; document `gecko-mcp wallet import` fallback in skill.md.

2. **PyPI publishing not done.** `uv tool install gecko-mcp` requires we ship the package. Git+subdirectory works but is slow and ugly. Mitigation: cut a 0.1.0 to PyPI before scaffold goes public; treat as Phase A blocker alongside the deploy.

3. **Skill drift between repos.** Once `gecko-claude` ships, every API/MCP-tool-name change here can break installed users. Mitigation: version the skills (`gecko-research@v1`), pin MCP minor in `install.sh`, document the contract in `docs/flow.md`.

---

## Sequencing

| Item | Time | Status |
|---|---|---|
| /projects endpoints + bearer auth | 2-3h | web3 designing now, software-engineer round 2 |
| CLI refactor (drop direct Supabase calls) | 1-2h | depends on above |
| PyPI publish gecko-mcp 0.1.0 | 1h | Phase A blocker |
| Create `gecko-claude` repo + install.sh + skill.md | 4-6h | new |
| `.claude/skills/*.md` (5 skills) | 3-4h | new |
| `.claude/agents/*.md` (5 personas) | 4-6h | new (could parallel with skills) |
| OTP smoke (10 cold runs) | 1h | risk mitigation |
| `app.geckovision.tech/install.sh` 302 + skill.md hosting | 1h | DNS + Vercel/Cloudflare static |

**Total: ~24-30 hours of focused engineering. Fits in 4-5 days with parallelism.**
