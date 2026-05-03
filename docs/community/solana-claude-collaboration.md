# solana-claude vs Gecko — Competitive / Learning Analysis

Source: https://github.com/solanabr/solana-claude (repo also `solana-claude-config`, v1.2.0). Install via `curl ... install.sh | bash`.

## Verdict
**Complement, not a competitor.** solana-claude is a static, free, install-once Claude Code *configuration kit* (agents + skills + rules). Gecko is a live, paid, MCP-served *intelligence service* with x402 metering, persistent memory, multi-agent debate, and stateful sessions. Different category — they ship prompt files; we ship a backend.

## What they do well (worth borrowing)
- **Progressive skill loading via a single hub.** `.claude/skills/SKILL.md` is a router that links out; nothing loads until referenced. Token-efficient by construction. (See SKILL.md routing table — task → primary skill mapping is excellent.)
- **Path-scoped auto-loading rules.** `.claude/rules/{anchor,rust,typescript,pinocchio,dotnet}.md` load only when matching files are read (frontmatter `paths:`/`globs:`). Zero startup cost, contextual enforcement.
- **Submodule-based skill federation.** 10 external repos (`ext/solana-dev`, `ext/sendai`, `ext/colosseum`, `ext/trailofbits`, `ext/safe-solana-builder`, etc.) wired in via `.gitmodules` with `bin/update.sh` + `bin/resync.sh` for upstream sync. Lets them aggregate ecosystem skills without forking.
- **Token-loading model documented explicitly in CLAUDE.md.** Table of "when each file loads + budget guidance." Forces discipline; CLAUDE-solana.md ships <120 lines.
- **Ripple Map.** A maintainer table in CLAUDE.md listing "when X changes, also update Y" — the #1 cause of stale config docs. Pragmatic, cheap, high-leverage.
- **Dynamic agent teams via env flag.** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` + `CLAUDE_CODE_COORDINATOR_MODE=1` in settings.json enables natural-language team assembly ("architect → engineer → QA"). No static team config.
- **Sandbox + denyWrite on key paths.** `settings.json` blocks writes to `~/.ssh`, `~/.gnupg`, `~/.aws`, `~/.config/solana/id.json`. Defense-in-depth at harness level.
- **`/cleanup` and `--agents` install modes.** Friction reducers — fork template, install into `.agents/` for non-Claude tools (Cursor, Codex). Distribution is cheap.

## What Gecko does they don't
- **Paid metering on Solana.** x402 USDC per-call ($0.10–$0.40); revenue-bearing infra they have none of.
- **Stateful backend.** Supabase + pgvector sessions, sources, chunks, embeddings. solana-claude has no server — every session restarts cold.
- **Native memory layer with contradiction detection.** `gecko_memory_*` semantically searches and flags inconsistencies. Their `memsearch` is a third-party MCP they list, not a product they own.
- **Adversarial multi-agent debate.** Pro-tier 5-voice (analyst/critic/architect/scoper/judge) AutoGen GroupChat verdicting SHIP/KILL. Their teams are cooperative role-routers, not adversarial.
- **Sprint-loop primitives.** `gecko_pulse`, `gecko_resume`, `gecko_review`, 5-voice Advisor Panel for sprint planning. Theirs is task-scoped (build-program, audit), not sprint-scoped.
- **Tiered routing (`gecko_route` 3-tier) with per-role model selection** and a single source-of-truth model catalog. Their model assignments are hardcoded per-agent (Opus/Sonnet) in markdown.

## What's worth borrowing for Gecko (concrete tickets)
- **S9-LEARN-01 — Skill hub routing table for the gecko skill.** Their `SKILL.md` "Task Routing" table (user asks X → load Y) is a clean pattern. Add a "When the user says X → call gecko_Y" table to our skill markdown in `gecko-mcpay-skills` so Claude picks the right tool faster. Pattern: solana-claude `.claude/skills/SKILL.md` lines under "## Task Routing".
- **S9-LEARN-02 — Path-scoped auto-rules in `gecko-mcpay-skills`.** Ship a `rules/` dir with frontmatter `paths:` so e.g. when Claude reads `*.sql` we auto-load Supabase RLS conventions; when it reads `app/**/*.tsx` we auto-load API contract notes. Pattern: their `.claude/rules/anchor.md`.
- **S9-LEARN-03 — Token loading budget table in our skill.md.** Force discipline on what loads at session start vs lazily. Pattern: their CLAUDE.md "Token Loading Model" table.
- **S9-LEARN-04 — Ripple map in CLAUDE.md.** When `gecko_research` signature changes, list every place to update (MCP schema, SDK, CLI, API openapi, skill, README, frontend). Cheap insurance against stale docs. Pattern: their CLAUDE.md "Ripple Map" section.
- **S9-LEARN-05 — `--agents` install mode + non-Claude distribution.** Their installer supports `.agents/` target so Cursor/Codex/Windsurf users can install. Gecko's MCP is portable; we should make the *skill prose* portable too. Pattern: their `install.sh` flag parsing + selective overwrite logic.

## What's NOT worth copying
- **Fifteen specialized agents per stack.** Our wedge is a small set of high-leverage tools (research/advise/plan/scaffold/route) with adversarial intelligence inside, not a sprawl of role personas. Adding `anchor-engineer`/`pinocchio-engineer` clones dilutes the brand.
- **Submodule-federated external skills.** They federate because they're a free aggregator; we are a paid service. Pulling in 10 third-party submodules muddies the contract for what users pay $0.10–$0.40 to invoke.

## Specific note on colosseum + startup research
Their "startup research" is **almost entirely a wrapper around the Colosseum Copilot API** (`COLOSSEUM_COPILOT_PAT` required, calls `copilot.colosseum.com/api/v1/search/projects` and `/search/archives`). The skill is a ~150-line markdown prompt that tells Claude when to hit `/search/projects` vs `/search/archives` and what evidence floors to meet. There is no original retrieval, no embeddings, no contradiction detection, no synthesis layer they own — Colosseum's hackathon corpus (5,400 projects) does the work. By contrast, `gecko_research` runs Tavily → extract → chunk → embed → pgvector retrieve → LLM synthesize, persists to Supabase, and feeds downstream `gecko_advise`/`gecko_plan`. Theirs is **API templating**; ours is **a research pipeline**. Net: their research is broader on Solana hackathon data (which we lack) and shallower on synthesis. Sensible borrow: optionally let `gecko_research` call Colosseum Copilot as one source among many for crypto-specific queries — they did the corpus work, we do the synthesis.
