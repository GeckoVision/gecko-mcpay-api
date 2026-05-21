# gecko-okx-quickstart Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the proven post-contest multi-voice studio bot as a self-contained, paper-default Claude Code skill at repo root `gecko-okx-quickstart/`.

**Architecture:** Copy the battle-tested `contest_bot/` runtime verbatim (its imports are flat + cwd-relative, so copies preserve them), then apply six cleanups: config extraction, generic naming, fundamentals-off-by-default, `.env.example`, README, and the SKILL.md pre→post narrative. The hosted x402 oracle and public corpus grounding are deferred to v2.

**Tech Stack:** Python 3.11+, `httpx`, `websockets`, `pydantic`, OpenRouter (voice LLM), OKX onchainOS CLI (execution), optional `pymongo` (best-effort corpus lens), stdlib `http.server` (dashboard).

**Source of truth:** `docs/superpowers/specs/2026-05-21-gecko-okx-quickstart-skill-design.md`

**Working dir for all paths:** `/home/nan/PycharmProjects/Gecko/gecko-mcpay-api`

---

### Task 0: Scaffold the skill directory + manifests

**Files:**
- Create: `gecko-okx-quickstart/.claude-plugin/plugin.json`
- Create: `gecko-okx-quickstart/package.json`
- Create: `gecko-okx-quickstart/requirements.txt`
- Create: `gecko-okx-quickstart/.env.example`

- [ ] **Step 1: Create the directory tree**

Run:
```bash
mkdir -p gecko-okx-quickstart/.claude-plugin gecko-okx-quickstart/voices gecko-okx-quickstart/tests
```

- [ ] **Step 2: Write `.claude-plugin/plugin.json`** (mirrors `starter-coach`)

```json
{
  "name": "gecko-okx-quickstart",
  "description": "Ready-to-go OKX onchainOS trading bot with a transparent multi-voice gate. Boots a paper-mode studio in one command: chart, regime, memory, and risk voices vote on every entry through a code-pinned coordinator, surfaced live in a dashboard. Built and hardened during the OKX Agentic Trading Contest.",
  "version": "0.1.0",
  "author": {
    "name": "Gecko",
    "github": "ernanibmurtinho"
  },
  "license": "MIT",
  "keywords": [
    "trading-bot",
    "agentic-trading",
    "multi-agent",
    "onchainos",
    "okx",
    "solana",
    "paper-trade",
    "risk-management",
    "dashboard"
  ],
  "repository": "https://github.com/ernanibmurtinho/gecko-mcpay-api"
}
```

- [ ] **Step 3: Write `package.json`** (mirrors `gecko-risk-oracle`)

```json
{
  "name": "gecko-okx-quickstart",
  "version": "0.1.0",
  "description": "Ready-to-go OKX onchainOS trading bot with a transparent multi-voice gate. Boots a paper-mode studio in one command: chart, regime, memory, and risk voices vote on every entry through a code-pinned coordinator, surfaced live in a dashboard. Paper-default, honest about edge (breakout is -EV in chop), grounded by Gecko's investor-canon corpus when available. Built and hardened during the OKX Agentic Trading Contest.",
  "author": "Gecko",
  "license": "MIT",
  "keywords": ["trading-bot", "agentic-trading", "multi-agent", "onchainos", "okx", "solana", "paper-trade", "risk-management", "dashboard"],
  "main": "SKILL.md",
  "scripts": {
    "test": "python3 -m pytest tests/ -q",
    "start": "python3 bot.py"
  },
  "tags": ["trading-bot", "agentic-trading", "multi-agent", "onchainos", "okx", "solana", "paper-trade"],
  "triggers": [
    "Run a trading bot on OKX",
    "Start the Gecko trading studio",
    "Quickstart an OKX bot",
    "Show me the agent voices trading",
    "Paper trade on Solana"
  ]
}
```

- [ ] **Step 4: Write `requirements.txt`**

```
httpx>=0.27
websockets>=12.0
pydantic>=2.6
# Optional — only needed for the best-effort investor-canon corpus lens.
# The bot runs fine without it (voices fall back to indicators + LLM).
pymongo>=4.6
```

- [ ] **Step 5: Write `.env.example`**

```bash
# REQUIRED — voice LLM calls route through OpenRouter.
OPENROUTER_API_KEY=

# OPTIONAL — enables the investor-canon corpus lens (MongoDB vector retrieval).
# Without it, chart_analyst degrades gracefully to indicators + LLM only.
MONGO_URI=

# OPTIONAL — dashboard port (default 8265).
DASHBOARD_PORT=8265

# OKX onchainOS auth is handled by the onchainos CLI itself (`onchainos login`).
# No key goes here — the TEE wallet is non-exportable.
```

- [ ] **Step 6: Verify the manifests are valid JSON**

Run:
```bash
python3 -c "import json; json.load(open('gecko-okx-quickstart/.claude-plugin/plugin.json')); json.load(open('gecko-okx-quickstart/package.json')); print('manifests OK')"
```
Expected: `manifests OK`

- [ ] **Step 7: Commit**

```bash
git add gecko-okx-quickstart/
git commit -m "feat(s40-skill): scaffold gecko-okx-quickstart — manifests + env example"
```

---

### Task 1: Copy the self-contained runtime modules verbatim

**Why:** Every intra-bot import is flat and cwd-relative (`from llm_client import`, `import indicators`, `from voices.base import`). Verbatim copies preserve them. `gecko_wrap.py` does NOT import `gecko_core` (only mentions it in comments), so it is self-contained.

**Files:**
- Copy: `contest_bot/{onchainos,gecko_wrap,bot_state,indicators,llm_client,local_memory,local_panel,bootstrap}.py` → `gecko-okx-quickstart/`
- Copy: `contest_bot/voices/{__init__,base,chart_analyst,regime_analyst,memory_voice,risk_voice,coordinator_rules}.py` → `gecko-okx-quickstart/voices/`

- [ ] **Step 1: Copy the runtime modules**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
for f in onchainos gecko_wrap bot_state indicators llm_client local_memory local_panel bootstrap; do
  cp "contest_bot/$f.py" "gecko-okx-quickstart/$f.py"
done
cp contest_bot/voices/*.py gecko-okx-quickstart/voices/
```

- [ ] **Step 2: Verify every module imports cleanly from the skill dir**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
python3 -c "import bootstrap, local_panel, gecko_wrap, bot_state, indicators, llm_client, local_memory, onchainos; from voices import base, chart_analyst, regime_analyst, memory_voice, risk_voice, coordinator_rules; print('all runtime modules import OK')"
```
Expected: `all runtime modules import OK`
(If `OPENROUTER_API_KEY` unset triggers an import-time error, that is a bug — clients construct lazily; imports must not require env. Investigate before proceeding.)

- [ ] **Step 3: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/
git commit -m "feat(s40-skill): copy self-contained runtime modules + voices"
```

---

### Task 2: Port the deterministic test suite

**Files:**
- Copy: `contest_bot/tests/test_local_voices.py` → `gecko-okx-quickstart/tests/test_local_voices.py`
- Copy: `contest_bot/tests/test_bot_state.py` → `gecko-okx-quickstart/tests/test_bot_state.py`
- Create: `gecko-okx-quickstart/tests/__init__.py` (empty)
- Create: `gecko-okx-quickstart/conftest.py`

- [ ] **Step 1: Copy the deterministic tests**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
cp contest_bot/tests/__init__.py gecko-okx-quickstart/tests/__init__.py
cp contest_bot/tests/test_local_voices.py gecko-okx-quickstart/tests/test_local_voices.py
cp contest_bot/tests/test_bot_state.py gecko-okx-quickstart/tests/test_bot_state.py
```

- [ ] **Step 2: Write `conftest.py`** so tests resolve sibling modules without env

```python
"""Make the skill root importable so tests can `import voices...` and
`import bot_state` exactly as the bot does at runtime (cwd-relative)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
```

- [ ] **Step 3: Run the ported tests**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
python3 -m pytest tests/ -q -p no:cacheprovider
```
Expected: PASS (coordinator 15/15 incl. regime, plus voice-parse + bot_state). If any test imports `gecko_core` or a contest-only module, delete that test file from the skill copy — the skill ships only the deterministic, self-contained tests.

- [ ] **Step 4: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/
git commit -m "test(s40-skill): port deterministic coordinator + bot_state tests"
```

---

### Task 3: Extract `config.py` from the main bot

**Files:**
- Create: `gecko-okx-quickstart/config.py`
- Reference: `contest_bot/jto_breakout_gecko_gated_contest_bot.py:82-161` (constant block to transplant)

- [ ] **Step 1: Write `config.py`** with the tunables (paper-safe defaults)

```python
"""All bot tunables in one place. Paper-safe defaults.

Flipping PAPER_TRADE to False is the only thing standing between this and
real money — do it deliberately, never by accident.
"""
import os

# ── execution mode ─────────────────────────────────────────────────────
PAPER_TRADE = True            # NEVER auto-flip. Real money requires editing this.
CHAIN = "solana"
POLL_SEC = 30
TIMEFRAME = "5m"
ENTRY_TYPE = "price_breakout"

# ── sizing + risk ──────────────────────────────────────────────────────
USD_PER_TRADE = 45
STOP_LOSS_PCT = 3
TAKE_PROFIT_PCT = 4
MAX_DAILY_TRADES = 3
MAX_CONCURRENT = 2
SESSION_LOSS_PAUSE = 2
MAX_BUDGET_USD = 100          # GLOBAL cap across all INSTRUMENTS

# ── exit overlays ──────────────────────────────────────────────────────
STALL_GREEN_EXIT_AGE_MIN = 60
STALL_GREEN_EXIT_MIN_PCT = 2.0
FLAT_STALL_AGE_MIN = 90
FLAT_STALL_PNL_LO = -0.5
FLAT_STALL_PNL_HI = 2.0
FLAT_STALL_NO_NEW_HIGH_MIN = 30
TRAIL_STOP_PCT = 1
TRAIL_ACTIVATE_AFTER_PCT = 2

# ── filters ────────────────────────────────────────────────────────────
VOL_SPIKE_MULTIPLIER = 1.5
VOL_SPIKE_AVG_BARS = 24
BTC_OVERLAY = None            # coarse BTC belt off; the voices are the gate
BTC_WBTC_MINT = "3NZ9JMVBmGAqocybic2c7LQCJScmgsAZ6vQqTDzcqmJh"
SAFETY = {"honeypot_check": True, "phishing_exclude": True}

# ── feature flags ──────────────────────────────────────────────────────
# Off by default — the fundamentals layer calls the hosted (waitlist-gated)
# x402 oracle, which is a v2 feature. v1 runs the gate locally.
FUNDAMENTALS_ORACLE_ENABLED = False

# ── infra ──────────────────────────────────────────────────────────────
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8265"))
WALLET_ADDRESS = ""          # resolved at runtime from onchainos if empty

# ── universe + entry params ────────────────────────────────────────────
# COPY VERBATIM from contest_bot/jto_breakout_gecko_gated_contest_bot.py:
#   INSTRUMENTS  (lines 119-137)
#   ENTRY_PARAMS (lines 138-146)
# Paste the two literal blocks below this comment, unchanged.
```

- [ ] **Step 2: Transplant the `INSTRUMENTS` and `ENTRY_PARAMS` literals**

Open `contest_bot/jto_breakout_gecko_gated_contest_bot.py`, copy the `INSTRUMENTS: list[dict] = [ ... ]` block (lines 119-137) and the `ENTRY_PARAMS = { ... }` block (lines 138-146) **verbatim**, and paste them at the end of `config.py` (replacing the placeholder comment). Do not alter values.

- [ ] **Step 3: Verify config imports + key values**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
python3 -c "import config; assert config.PAPER_TRADE is True; assert config.FUNDAMENTALS_ORACLE_ENABLED is False; assert config.TAKE_PROFIT_PCT == 4; assert len(config.INSTRUMENTS) >= 1; assert isinstance(config.ENTRY_PARAMS, dict); print('config OK:', len(config.INSTRUMENTS), 'instruments')"
```
Expected: `config OK: N instruments`

- [ ] **Step 4: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/config.py
git commit -m "feat(s40-skill): extract config.py — tunables + fundamentals-off-by-default"
```

---

### Task 4: Copy + de-JTO the main bot as `bot.py`, wire config + fundamentals flag

**Files:**
- Create: `gecko-okx-quickstart/bot.py` (from `contest_bot/jto_breakout_gecko_gated_contest_bot.py`)

- [ ] **Step 1: Copy the main bot**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
cp contest_bot/jto_breakout_gecko_gated_contest_bot.py gecko-okx-quickstart/bot.py
```

- [ ] **Step 2: Replace the inline constant block with imports from `config.py`**

In `gecko-okx-quickstart/bot.py`, DELETE the constant definitions now living in `config.py` (the block spanning the originals at lines 82-161: `PAPER_TRADE` through `ENTRY_PARAMS`, including `WALLET_ADDRESS`, `SAFETY`, `BTC_*`, `VOL_SPIKE_*`, `DASHBOARD_PORT`). Replace the whole block with:

```python
from config import (
    BTC_OVERLAY,
    BTC_WBTC_MINT,
    CHAIN,
    DASHBOARD_PORT,
    ENTRY_PARAMS,
    ENTRY_TYPE,
    FLAT_STALL_AGE_MIN,
    FLAT_STALL_NO_NEW_HIGH_MIN,
    FLAT_STALL_PNL_HI,
    FLAT_STALL_PNL_LO,
    FUNDAMENTALS_ORACLE_ENABLED,
    INSTRUMENTS,
    MAX_BUDGET_USD,
    MAX_CONCURRENT,
    MAX_DAILY_TRADES,
    PAPER_TRADE,
    POLL_SEC,
    SAFETY,
    SESSION_LOSS_PAUSE,
    STALL_GREEN_EXIT_AGE_MIN,
    STALL_GREEN_EXIT_MIN_PCT,
    STOP_LOSS_PCT,
    TAKE_PROFIT_PCT,
    TIMEFRAME,
    TRAIL_ACTIVATE_AFTER_PCT,
    TRAIL_STOP_PCT,
    USD_PER_TRADE,
    VOL_SPIKE_AVG_BARS,
    VOL_SPIKE_MULTIPLIER,
    WALLET_ADDRESS,
)
```

Leave every *usage* of these bare names in `bot.py` unchanged — they now resolve via the import.

- [ ] **Step 3: Gate the fundamentals oracle behind the flag**

The bot constructs `_FUNDAMENTALS = FundamentalsOracle(...)` and calls it in `open_position` (the `fundamentals_check` log) and preloads it in `__main__`. Wrap each so the flag controls it:

At construction (was `contest_bot` line ~58):
```python
_FUNDAMENTALS = (
    FundamentalsOracle(stub_mode=True, ttl_seconds=21_600, timeout_s=120.0)
    if FUNDAMENTALS_ORACLE_ENABLED
    else None
)
```

At the call site in `open_position` (was `fund_verdict = _FUNDAMENTALS.get_for_instrument(instrument)`):
```python
fund_verdict = (
    _FUNDAMENTALS.get_for_instrument(instrument) if _FUNDAMENTALS else None
)
```

At the preload in `__main__` (the `[fundamentals] preloading ...` block): wrap the whole block in `if FUNDAMENTALS_ORACLE_ENABLED and _FUNDAMENTALS:` and keep the existing `GECKO_FUND_PRELOAD_SKIP` short-circuit inside.

- [ ] **Step 4: De-JTO the user-facing strings**

Replace contest/JTO naming in `bot.py` with generic language (the dashboard `<title>` and `<h2>` already say "My Strategy" — leave those). Specifically: the module docstring header and the startup banner. Do NOT rename `gecko_wrap` internals or the artifact-log schema. Verify none remain in *printed* output:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
grep -nE "JTO|jto_breakout|contest" bot.py | grep -iE "print|banner|title|\"\"\"" || echo "no user-facing JTO/contest strings"
```

- [ ] **Step 5: Verify `bot.py` imports + compiles**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
python3 -c "import py_compile; py_compile.compile('bot.py', doraise=True); print('bot.py compiles')"
python3 -c "import ast; ast.parse(open('bot.py').read()); print('AST OK')"
```
Expected: both OK.

- [ ] **Step 6: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/bot.py
git commit -m "feat(s40-skill): de-JTO main bot -> bot.py, wire config.py + fundamentals flag"
```

---

### Task 5: Boot smoke — paper mode + dashboard

**Files:** none (verification only)

- [ ] **Step 1: Boot the bot in paper mode and confirm the dashboard answers**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
set -a; . ../.env 2>/dev/null; set +a   # OPENROUTER_API_KEY for the voices
python3 -u bot.py > /tmp/qs_boot.log 2>&1 &
BOT_PID=$!
sleep 90
curl -s http://localhost:8265/api/state | python3 -c "import sys,json; d=json.load(sys.stdin); print('mode:', d.get('mode'), '| panel decisions:', len(d.get('panel',[])))"
kill -9 $BOT_PID 2>/dev/null
```
Expected: `mode: paper | panel decisions: N` (N may be 0 on a cold first tick — acceptable; the requirement is the server answers and `mode` is `paper`).

- [ ] **Step 2: Confirm no crash / no live execution in the log**

Run:
```bash
grep -ciE "live|real money|swap_execute" /tmp/qs_boot.log; grep -ci "traceback" /tmp/qs_boot.log
```
Expected: live/swap_execute count is 0, traceback count is 0. If a traceback appears, fix before proceeding.

- [ ] **Step 3: No commit** (verification only). If Step 1-2 required code fixes, commit those with message `fix(s40-skill): boot smoke fixes`.

---

### Task 6: Write `SKILL.md` — the pre→post narrative

**Files:**
- Create: `gecko-okx-quickstart/SKILL.md`

- [ ] **Step 1: Write `SKILL.md`** (frontmatter mirrors `gecko-risk-oracle`; body is the narrative)

```markdown
---
name: gecko-okx-quickstart
description: A ready-to-go OKX onchainOS trading bot with a transparent multi-voice gate. One command boots a paper-mode studio where chart, regime, memory, and risk voices vote on every entry through a code-pinned coordinator — surfaced live in a dashboard, grounded by Gecko's investor-canon corpus when available. Built and hardened during the OKX Agentic Trading Contest. Use it when someone wants to run, watch, or learn from an agentic trading bot on Solana without writing one from scratch. Paper-default and honest about edge — it sells discipline and transparency, not alpha.
version: 0.1.0
author: Gecko
tags: [trading-bot, agentic-trading, multi-agent, onchainos, okx, solana, paper-trade, risk-management, dashboard]
triggers:
  - "Run a trading bot on OKX"
  - "Start the Gecko trading studio"
  - "Quickstart an OKX bot"
  - "Show me the agent voices trading"
  - "Paper trade on Solana"
---

# Gecko OKX Quickstart

A ready-to-go trading bot for OKX onchainOS with a gate you can actually see.
Boot it in one command; it runs in **paper mode** and opens a live dashboard
where four voices debate every entry.

## What this is (and isn't)

It **is**: the post-contest "studio" bot — a multi-voice panel (chart, regime,
memory, risk) voting through a coordinator whose logic lives in code, not a
prompt. It **is not** a money printer. It sells discipline + transparency.

## What we ran in the contest (pre)

We entered the OKX Agentic Trading Contest with a gated breakout bot: every
entry passed a risk gate, a circuit breaker, and an artifact logger before any
swap fired; PnL was computed from real fills, not oracle prices. It held the
participation grant — final wallet $106.81, +$0.84 net (3W/2L). The honest
lesson: a single breakout rule is **blind to regime** — breakout is -EV in
chop, and we have the backtest to prove it.

## What we're building now (post)

So we added the missing axis: a transparent multi-voice panel.

- **chart_analyst** — indicator confluence (ADX/RSI/MFI/EMA/BB), grounded by
  the investor-canon corpus when `MONGO_URI` is set.
- **regime_analyst** — deterministic chop/trend classifier (ADX). Breakout in
  chop raises the bar; only the cleanest setups pass.
- **memory_voice** — grades *realized outcomes*, not its own past calls.
- **risk_voice** — deterministic veto.

Every decision — regime, each voice's verdict/confidence/reasoning — shows up
in the dashboard. That's the wedge: not "a bot," but a bot whose gate you can
inspect.

## Quickstart

1. `pip install -r requirements.txt`
2. `cp .env.example .env` and set `OPENROUTER_API_KEY` (required).
   Optionally set `MONGO_URI` for corpus grounding.
3. `onchainos login` (one-time, for execution + candles).
4. `python bot.py`
5. Open `http://localhost:8265` — watch the voices vote in paper mode.

## Safety

- **Paper-default.** `PAPER_TRADE = True` in `config.py`. Real money requires
  editing that line on purpose — never by accident.
- **Not financial advice.** Past performance (a +$0.84 contest) is not a
  promise. Breakout is -EV in chop; the bot abstains there by design.
- **No secrets ship.** `.env.example` is empty; your keys are yours.

## Roadmap

- **v2:** the hosted, grounded **Gecko oracle API** (waitlist). That's what
  gives any user the corpus-grounded verdict without running our MongoDB —
  the bot becomes a thin client of the oracle.
- Richer studio UI; more voices promoted from the lab once validated.

## Config

Every tunable lives in `config.py` with paper-safe defaults: sizing, TP/SL,
trailing + stall exits, the instrument universe, concurrency + daily caps.
```

- [ ] **Step 2: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/SKILL.md
git commit -m "docs(s40-skill): SKILL.md — pre->post contest narrative + quickstart"
```

---

### Task 7: Write `README.md` (60-second start)

**Files:**
- Create: `gecko-okx-quickstart/README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# gecko-okx-quickstart

A ready-to-go, **paper-default** OKX onchainOS trading bot with a transparent
multi-voice gate and a live dashboard. Built during the OKX Agentic Trading
Contest; this is the post-contest "studio" version.

## 60-second start

```bash
pip install -r requirements.txt
cp .env.example .env          # set OPENROUTER_API_KEY (required)
onchainos login               # one-time, for candles + execution
python bot.py                 # runs in paper mode
# open http://localhost:8265
```

## What you'll see

Four voices — **chart, regime, memory, risk** — vote on every candidate through
a code-pinned coordinator. The dashboard shows each instrument's regime and
every voice's verdict, confidence, and reasoning, live.

## Going live

Edit `config.py` → `PAPER_TRADE = False`. Do this deliberately. The bot sells
discipline and transparency, not guaranteed returns — breakout is -EV in chop,
and it abstains there on purpose.

See `SKILL.md` for the full story and `config.py` for every tunable.
```

- [ ] **Step 2: Commit**

```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git add gecko-okx-quickstart/README.md
git commit -m "docs(s40-skill): README — 60-second quickstart"
```

---

### Task 8: Final gate — skill lint + full skill test run

**Files:** none (verification) — fix-and-commit only if issues found

- [ ] **Step 1: Run the repo's skill linter against the new skill**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
python3 scripts/skills/lint_skill.py gecko-okx-quickstart 2>&1 | tail -20 || echo "(linter path/usage differs — inspect scripts/skills/lint_skill.py --help)"
```
Expected: PASS, or a concrete list of rubric gaps to fix. If it flags the `description` length or missing sections, fix `SKILL.md`/`package.json` to satisfy it, then re-run.

- [ ] **Step 2: Final self-contained test run**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api/gecko-okx-quickstart
python3 -m pytest tests/ -q -p no:cacheprovider
```
Expected: all PASS.

- [ ] **Step 3: Confirm no junk staged + tree clean**

Run:
```bash
cd /home/nan/PycharmProjects/Gecko/gecko-mcpay-api
git status --short gecko-okx-quickstart/
```
Expected: clean (runtime artifacts like `bot_state.json`, `*.log`, `local_memory.jsonl` are already gitignored by the repo-wide `contest_bot/` patterns — verify none of those globs need a `gecko-okx-quickstart/` equivalent; if a `gecko-okx-quickstart/bot_state.json` appears, add the matching ignore line and commit it).

- [ ] **Step 4: Final commit (if any fixes)**

```bash
git add gecko-okx-quickstart/ .gitignore
git commit -m "chore(s40-skill): lint fixes + ignore runtime artifacts"
```

---

## Self-Review

**Spec coverage:**
- §5.1 directory layout → Tasks 0-7 create every listed file (note: `dashboard/` stays inline in `bot.py` per §6.6 — intentional, no separate dir).
- §5.2/5.3 components + data flow → preserved by verbatim copy (Task 1) + config wiring (Task 4).
- §6 six cleanups → Task 4 (naming #1, fundamentals #2), Task 3 (config #4), Task 0 (.env #5), §6.3 corpus-lens-unchanged is a no-op by design, §6.6 inline dashboard is a no-op by design.
- §7 SKILL.md narrative → Task 6. §8 safety → config.py paper-default (Task 3) + SKILL/README copy (Tasks 6-7). §9 testing → Tasks 2, 5, 8.
- §10 fork tradeoff → realized by the copy approach (Task 1). §11 deferrals → fundamentals-off (Task 4), no oracle/UI work. §3 non-goals respected.

**Placeholder scan:** the only "copy verbatim from source lines" references (Task 3 Step 2, Task 4 Step 2) point at exact line ranges in a named file — precise, not vague. No TBD/TODO.

**Type consistency:** the `from config import (...)` name list in Task 4 matches the names defined in `config.py` (Task 3) one-for-one; `FUNDAMENTALS_ORACLE_ENABLED` is defined in config and consumed in bot.py both as named.
