# Solana-agent skill links — finding + fix

**Date:** 2026-05-16
**Context:** We imported 3 agents (`solana-architect`, `defi-engineer`,
`solana-researcher`) from Superteam's `solana-claude-config` into
`.claude/agents/`. Their bodies reference skill/command files via relative
paths. Those paths are dead in this repo.

## Finding — there is NO upstream bug

All 21 relative links were verified against a fresh upstream clone **with
submodules** (`git clone --recurse-submodules`). **Every target exists
upstream.** The `skills/ext/*` trees are git submodules
(`sendai`, `solana-dev`, `colosseum`, `qedgen`, …) declared in
`solana-claude-config/.gitmodules`; the `skills/*.md` and `commands/*.md`
files live in the main repo.

The links break **only in this repo** because we copied the 3 agent `.md`
files without the `skills/` and `commands/` trees. This is a partial-copy
consequence on our side — **not a fork-and-PR fix**.

If you want to contribute upstream, the *real* defensible PR is unrelated to
these links: `install.sh` unconditionally overwrites the consumer's
`CLAUDE.md` and `cp -r`'s over `.claude/agents/` ("always overwrite with
upstream"), which clobbers a consumer's existing custom agents. That is a
genuine destructiveness bug worth raising. See the "Optional upstream PR"
section at the bottom.

## The 21 links (all valid upstream, all dead here)

### `.claude/agents/solana-architect.md`

| Line | Link target | Upstream |
|------|-------------|----------|
| 13 | `../skills/ext/solana-dev/skill/references/programs/anchor.md` | exists |
| 14 | `../skills/ext/solana-dev/skill/references/programs/pinocchio.md` | exists |
| 15 | `../skills/ext/solana-dev/skill/references/security.md` | exists |
| 16 | `../skills/deployment.md` | exists |
| 17 | `../skills/ext/colosseum/skills/colosseum-copilot/SKILL.md` | exists |
| 18 | `../commands/audit-solana.md` | exists |
| 405 | `../skills/ext/qedgen/SKILL.md` | exists |
| 407 | `../skills/ext/solana-dev/skill/references/security.md` | exists (dup of L15) |

### `.claude/agents/defi-engineer.md`

| Line | Link target | Upstream |
|------|-------------|----------|
| 13 | `../skills/ext/sendai/skills/jupiter/SKILL.md` | exists |
| 14 | `../skills/ext/sendai/skills/drift/SKILL.md` | exists |
| 15 | `../skills/ext/sendai/skills/kamino/SKILL.md` | exists |
| 16 | `../skills/ext/sendai/skills/raydium/SKILL.md` | exists |
| 17 | `../skills/ext/sendai/skills/orca/SKILL.md` | exists |
| 18 | `../skills/ext/sendai/skills/meteora/SKILL.md` | exists |
| 19 | `../skills/ext/sendai/skills/marginfi/SKILL.md` | exists |
| 20 | `../skills/ext/sendai/skills/sanctum/SKILL.md` | exists |
| 21 | `../skills/ext/sendai/skills/pyth/SKILL.md` | exists |
| 22 | `../skills/ext/sendai/skills/switchboard/SKILL.md` | exists |
| 23 | `../skills/ext/solana-dev/skill/references/security.md` | exists |
| 24 | `../commands/build-program.md` | exists |

### `.claude/agents/solana-researcher.md`

| Line | Link target | Upstream |
|------|-------------|----------|
| 13 | `../skills/ext/solana-dev/skill/references/resources.md` | exists |
| 14 | `../skills/SKILL.md` | exists |
| 15 | `../skills/ext/colosseum/skills/colosseum-copilot/SKILL.md` | exists |

## The Gecko-side fix — pick ONE

### Option A — neutralize the links (recommended)

We do not want the full Solana skill tree (it is large, submodule-heavy, and
mostly irrelevant to a Python backend). So make our 3 copies self-contained:
strip the markdown link syntax, keeping the reference as plain text.

- In each file, the `## Related Skills` / `## Related Skills & Commands`
  section becomes a plain bullet list of names (no `(../path)`).
- `solana-architect.md` L405 and L407: de-link the two inline references —
  keep "QEDGen" / "security checklist" as plain text.

Result: zero dead links, agent prompts keep their useful body. ~5 edits
total across 3 files. Reversible.

### Option B — vendor the referenced skills

Add `solana-claude-config`'s `skills/` + `commands/` trees (or the specific
referenced files) under `.claude/`. Keeps the links live but pulls a large,
mostly-unused dependency into the repo. Not recommended.

### Option C — leave as-is

The links degrade gracefully: an agent that tries to open one gets a
file-not-found and continues. Acceptable but sloppy; a reader of the agent
file sees dead links.

## Optional upstream PR (the real one, if you want to contribute)

Repo: `github.com/solanabr/solana-claude-config`, file: `install.sh`.

Problem: the installer is destructive to a consumer that already has Claude
Code config —
1. `cp CLAUDE-solana.md → CLAUDE.md` runs unconditionally (a `.bak` is made,
   but the consumer's `CLAUDE.md` is still replaced).
2. `for dir in agents skills rules commands bin; cp -r` over `.claude/$dir`
   with the comment "always overwrite with upstream" — clobbers any custom
   agents the consumer authored.

Suggested fix for a PR: treat `CLAUDE.md` and `.claude/agents/` like the
already-protected `settings.json` — copy only if absent, or merge, or prompt.
This is a real, defensible contribution; the skill-link "issue" is not.
