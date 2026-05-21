---
name: gecko-okx-quickstart
description: A ready-to-go OKX onchainOS trading bot with a transparent multi-voice gate. One command boots a paper-mode studio where chart, regime, memory, and risk voices vote on every entry through a code-pinned coordinator — surfaced live in a dashboard, grounded by Gecko's investor-canon corpus when available. Built and hardened during the OKX Agentic Trading Contest. Use it when someone wants to run, watch, or learn from an agentic trading bot on Solana without writing one from scratch. Paper-default and honest about edge — it sells discipline and transparency, not alpha.
version: 0.1.0
author: Gecko
tags: [trading-bot, agentic-trading, multi-agent, onchainos, okx, solana, paper-trade, risk-management, dashboard]
dependencies: []
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
