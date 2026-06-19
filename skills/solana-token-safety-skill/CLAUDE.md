# CLAUDE.md — solana-token-safety-skill

Context for any agent working *in this repo*. (The skill itself, for end users,
is `skill/SKILL.md`.)

## What this is

A standalone, MIT-licensed skill for the Solana AI Kit: a pre-trade / pre-launch
**market-integrity** gate for Solana tokens. It answers *"is this token's market
real, or manufactured?"* — the layer contract checkers (RugCheck/GoPlus) miss.

It is a **thin, safe client** over Gecko's free, keyless `/safety` oracle
(`POST https://api.geckovision.tech/safety`) or the `gecko_safety` MCP tool. It
ships **no executable logic of its own** beyond a copy-only `install.sh`.

## Layout

```
skill/        SKILL.md (entry + routing) → quickstart, signals,
              interpreting-verdicts, agent-integration, launch-check
commands/     /safety-check (trader) · /launch-check (issuer)
agents/       token-safety-auditor (market-integrity specialist persona)
rules/        pre-trade-safety (opt-in: gate swaps with a check first)
examples/     clean-jup.json (real) · blocked-brca.json (illustrative)
install.sh    copy-only installer · LICENSE (MIT) · README.md
```

## Rules for editing

- **Stay accurate to the live endpoint.** The response shape in the docs must
  match `POST /safety`. Verify with a real call before changing field docs:
  `curl -s -X POST https://api.geckovision.tech/safety -H "Content-Type: application/json" -d '{"mint":"JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN"}'`
- **No bloat, nothing opaque.** No binaries, no network calls in the installer,
  no shady executables (kit requirement). Markdown + a copy script only.
- **Honesty over polish.** `unknown` is never "safe" (fail-OPEN). Don't claim the
  skill predicts price — it reads market integrity, not the future. Mark
  illustrative data as illustrative (see `examples/blocked-brca.json`).
- **Don't claim contract-audit scope.** This is the market-data layer; defer
  bytecode/formal-verification to a dedicated auditor skill.
- **Keep it progressive.** SKILL.md routes; focused files load on demand. Don't
  inline everything into SKILL.md.

## Provider

Built by [Gecko](https://geckovision.tech). The `/safety` tier is free by design
(the public good + the funnel); the paid multi-voice `/trade_research` tier is
NOT used by this skill. Docs: https://docs.geckovision.tech
