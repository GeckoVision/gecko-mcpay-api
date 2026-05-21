# Design: `gecko-okx-quickstart` skill

**Date:** 2026-05-21
**Status:** Approved (brainstorm) → ready for implementation plan
**Branch:** `s40/quickstart-okx-bot-skill`
**Owner:** founder + Claude

---

## 1. Motivation

The OKX Agentic Trading Contest produced a working, live-hardened bot: a gated
breakout strategy with a risk gate, circuit breaker, real-fill PnL accounting,
and (post-contest) a multi-voice "studio" — `chart_analyst`, `regime_analyst`,
`memory_voice`, `risk_voice` voting through a code-pinned coordinator, surfaced
in a live dashboard.

That work currently lives in `contest_bot/` as a lab artifact. This skill
**packages the studio bot as a ready-to-go, distributable Claude Code skill**:
`Read SKILL.md → set one key → run`, and the studio comes up in paper mode.

The skill is a **$0 proof artifact** per the ownership-tier strategy (the
*oracle* is the product; the *bot* is the proof that demonstrates it). Its job
is to **show the system working for us** — not to be a public, self-serve money
bot. The wedge it demonstrates is not "a trading bot" (table stakes) but **a
bot gated by a transparent, grounded multi-voice panel**.

## 2. Goals

- One-command boot of the multi-voice studio bot against OKX onchainOS, in
  **paper mode by default**.
- A `SKILL.md` that narrates the **pre-contest → post-contest** evolution —
  doubling as source material for the build-in-public post.
- Self-contained: the skill directory runs without needing the rest of this
  repo on the path (it copies what it needs).
- Full MongoDB-vector corpus grounding **in our setup** (we have `MONGO_URI` +
  `gecko_core`); graceful degradation everywhere else.

## 3. Non-goals (explicit deferrals)

- **Hosted x402 oracle call.** The waitlist-gated `gecko-risk-oracle` API is the
  *next version*. v1 runs the gate locally. (`fundamentals_oracle` ships
  **disabled by default**.)
- **Public self-serve grounding.** The canon corpus lives in our private Atlas;
  external users can't query it. v1 shows it working *for us*. Public users get
  a bot that degrades to indicators + LLM voices. Solving public grounding =
  the hosted oracle, deferred.
- **shadcn / LangGraph Studio UI.** The inline dashboard is the v1 studio.
  Richer visualization is aspirational v2.
- **Live trading by default.** `PAPER_TRADE=True`; the live flip is a deliberate
  user action, mirroring `X402_MODE=stub` posture.

## 4. Locked decisions (from brainstorm)

| Decision | Choice |
|---|---|
| Skill shape | Studio bot only (the "now"); pre/post story told in narrative, not code modes |
| Execution surface | OKX onchainOS CLI — reuse the proven `onchainos.py` (DEX, Solana mints, TEE wallet) |
| Entry gate | Self-contained: local 4-voice panel + coordinator + best-effort Mongo-vector grounding. No paid API. |
| Name | `gecko-okx-quickstart` |
| Location | repo root (matches `gecko-yield-verdict/`) |
| Oracle access | Waitlist-gated (us + enabled people); v1 = "show it working for us" |

## 5. Architecture

### 5.1 Directory layout

```
gecko-okx-quickstart/
  SKILL.md            # pre→post narrative + quickstart + safety (buildinpublic source)
  README.md           # 60-second start
  package.json        # OKX skill manifest (mirror gecko-risk-oracle)
  .claude-plugin/
    plugin.json
  bot.py              # the studio bot (de-JTO'd → generic momentum studio)
  config.py           # all tunables in one documented place; PAPER_TRADE=True
  onchainos.py        # OKX onchainOS wrapper (copied verbatim)
  gecko_wrap.py       # gate + circuit breaker + artifact logger
  bot_state.py        # state persistence
  indicators.py       # shared pure-Python TA
  llm_client.py       # OpenRouter client (max_tokens capped)
  local_memory.py     # JSONL outcome memory
  local_panel.py      # panel runner
  bootstrap.py        # wires the 4 voices + coordinator
  voices/
    base.py
    chart_analyst.py      # indicator confluence + best-effort corpus lens
    regime_analyst.py     # deterministic ADX chop/trend
    memory_voice.py       # grades realized outcomes
    risk_voice.py         # deterministic veto
    coordinator_rules.py  # code-pinned, regime-modulated floor
  tests/
    test_coordinator.py   # ported coordinator + regime tests
    test_indicators.py
    test_regime.py
  .env.example        # OPENROUTER_API_KEY (req), MONGO_URI (optional), onchainOS auth
  requirements.txt    # httpx, websockets, pydantic, (pymongo optional)
```

### 5.2 Component responsibilities

- **`bot.py`** — main loop: poll candles → build market_state → run local panel
  → coordinator decision → (paper) open/close → serve `/api/state` + dashboard.
- **`config.py`** — single source for every tunable (sizing, TP/SL/trail, stall
  exits, instrument list, MAX_CONCURRENT, MAX_DAILY_TRADES, poll cadence,
  feature flags). All conservative + paper-safe defaults.
- **`gecko_wrap.py`** — the gate: every entry passes risk gate → circuit breaker
  → artifact logger before any (paper) fill.
- **voices + coordinator** — the panel. Coordinator logic stays in **code, not
  prompt** (per `feedback_prompt_iteration_plateau`).
- **dashboard** — inline HTML/JS in `bot.py`, "Agent Voices" panel showing per
  instrument regime + each voice's verdict/confidence/reasoning.

### 5.3 Data flow (one poll)

```
onchainOS candles ─▶ market_state {price, candles, change_*}
                       │
        ┌──────────────┼─────────────────────────┐
        ▼              ▼                           ▼
   chart_analyst   regime_analyst            risk_voice
   (indicators +   (ADX chop/trend,          (deterministic
    Mongo-vector    deterministic)            band + veto)
    corpus lens,                              memory_voice
    best-effort)                              (realized outcomes)
        └──────────────┴─────────────────────────┘
                       ▼
              coordinator_rules (code)
              risk veto → chart floor (regime-modulated) → memory contradict
                       ▼
              act / decline  ──▶ gecko_wrap gate ──▶ (PAPER) fill
                       ▼
              _LAST_PANEL ──▶ /api/state ──▶ dashboard "Agent Voices"
```

## 6. The six cleanups (copy → product)

1. **Generic naming** — `jto_breakout_gecko_gated_contest_bot.py` → `bot.py`;
   strip "JTO/contest" language → "momentum studio bot."
2. **`fundamentals_oracle` off by default** — `FUNDAMENTALS_ORACLE_ENABLED=False`
   in `config.py` (needs the deferred x402 endpoint). Code ships but dormant.
3. **Corpus lens documented, unchanged** — stays best-effort; grounds fully for
   us, degrades elsewhere. Document the `MONGO_URI` + `gecko_core` requirement
   for full grounding.
4. **`config.py` extraction** — pull every magic constant out of `bot.py` into a
   documented config module with paper-safe defaults.
5. **`.env.example` + setup docs** — `OPENROUTER_API_KEY` required; `MONGO_URI`
   optional (grounding); onchainOS auth for execution.
6. **Inline dashboard kept** — no UI rewrite in v1.

## 7. SKILL.md narrative (outline)

1. **What this is** — a ready-to-go OKX onchainOS bot with a transparent
   multi-voice gate. Paper-default.
2. **What we ran in the contest (pre)** — gated breakout, real fills, +$0.84
   net, the discipline that held the participation grant. The honest lesson:
   a single breakout rule is blind to regime.
3. **What we're building now (post)** — the multi-voice studio: chart / regime /
   memory / risk voting live, MongoDB-vector grounded, surfaced in the
   dashboard. The wedge = transparent, grounded gate, not "a bot."
4. **Quickstart** — install → `OPENROUTER_API_KEY` → `python bot.py` → open
   `localhost:8265` → watch the voices vote in paper mode.
5. **Safety + honesty** — paper-default; breakout is -EV in chop (we backtested
   it); not financial advice; the live flip is a deliberate action.
6. **Roadmap** — hosted, grounded oracle API (waitlist) is next; that's what
   gives any user the corpus-grounded verdict without our Mongo.

## 8. Safety

- `PAPER_TRADE=True` default; no real execution without an explicit flip.
- No secrets in the skill: `.env.example` ships with empty values; real keys are
  the user's.
- Honest performance framing in SKILL.md — sells discipline + transparency, not
  alpha.
- Gate + circuit breaker + artifact logger preserved from the contest hardening.

## 9. Testing

- Port the deterministic tests that already pass: coordinator (15, incl. regime),
  indicators, regime classifier, bot_state. Run inside the skill dir so it's
  self-contained.
- A smoke check: `python bot.py` boots, serves `/api/state`, panel populates in
  paper mode (no live calls required for the deterministic voices).
- Do **not** dispatch a full repo pytest sweep (per `feedback_remove_freezing_tests`).

## 10. Tradeoffs accepted

- **Code fork.** The skill copies `contest_bot` code (a distributable skill must
  run without our repo). `contest_bot/` stays the lab; the skill is the packaged
  product. They will diverge. Acceptable for v1; revisit a shared-core extraction
  if both need to evolve in lockstep.

## 11. Out of scope / next versions

- Hosted x402 oracle invocation (v2 — the product).
- Public corpus grounding (v2, via the oracle).
- shadcn / richer studio UI (v2).
- Transplant of validated lab voices into the PRD oracle (Track E — separate).

## 12. Open questions

None blocking. The fork-vs-shared-core question is deferred to when/if the lab
and the skill need to evolve together.
