---
name: gecko-trade-agent
description: Self-hostable trading agent with a transparent 5-voice gate including a pre-execution devil's advocate. One command boots a paper-mode studio where chart, regime, memory, risk, and strategist voices debate every entry through a code-pinned coordinator — surfaced live in a dashboard, grounded by Gecko's investor-canon corpus when available. For crypto operators evaluating someone else's signals, not building new ones. Paper-default; honest about edge — 10 published nulls, breakout is -EV in chop. Sells discipline and transparency, not alpha. Plugs into OKX onchainOS today; SendAI Solana Agent Kit landing in Phase B.
version: 0.2.0
author: Gecko
tags: [trading-agent, agentic-trading, multi-agent, devils-advocate, oracle, solana, paper-trade, risk-management, dashboard, self-hostable]
dependencies: []
triggers:
  - "Start the Gecko trade agent"
  - "Run the gecko trading panel"
  - "Self-host a trading agent"
  - "Show me the agent voices trading"
  - "Paper trade with a transparent gate"
---

# Gecko Trade Agent

A self-hostable trading agent for crypto operators — the kind of person who's
already running someone else's bot and wants to know if its signals are real.
Boot it in one command; it runs in **paper mode** and opens a live dashboard
where **five voices** debate every entry, including a **pre-execution
devil's advocate** whose only job is to find the strongest reason a trade fails.

## Who this is for

You already run (or copy-trade) someone else's bot on Solana. You've been
burned. You want to know **whether the signals you're acting on are real**
before you risk more capital. You'd rather see *one trade refused for a
defensible reason* than ten trades fired on rubber-stamp consensus.

It **is**: a 5-voice panel that debates every entry through a coordinator
whose logic lives in code, not a prompt. It **is not**: a money printer, a
copy-trade-of-someone-else, or a single-strategy bot you can't audit. It
sells **discipline, dissent, and published nulls** — not alpha.

## The contest pedigree (where this came from)

This bot was hardened during the OKX Agentic Trading Contest: every entry
passed a risk gate, a circuit breaker, and an artifact logger before any
swap fired; PnL was computed from real fills, not oracle prices. It held
the participation grant — final wallet $106.81, +$0.84 net (3W/2L). That
isn't proof of edge; it's proof the gate works without breaking. The
honest lesson from contest data: a single breakout rule is **blind to
regime** — breakout is -EV in chop, and we have the backtest to prove it.

We've published **10 rigorously-validated nulls** since then, including
catching our own +2.3% carry result before deploying capital (it
disappeared when re-tested against 26 months of data instead of 180 days).
That falsifier-discipline is the moat — easy for any LLM-wrapper to copy
in principle, structurally hard in practice (publishing nulls kills the
growth narrative every competitor depends on).

## The five voices

- **chart_analyst** — indicator confluence (ADX/RSI/MFI/EMA/BB), grounded by
  the investor-canon corpus when `MONGO_URI` is set.
- **regime_analyst** — deterministic chop/trend classifier (ADX). Breakout in
  chop raises the bar; only the cleanest setups pass.
- **memory_voice** — grades *realized outcomes*, not its own past calls.
- **risk_voice** — deterministic veto (account caps, hourly drawdown, budget).
- **strategist_voice** *(new, Sprint 21)* — pre-execution **devil's advocate**.
  Reads the same snapshot the chart_analyst sees and tries to break it.
  Returns `bearish` only when it can name a specific falsifier class
  (chop breakout / RSI exhausted / volume divergence / EMA adverse /
  1h regime contradiction); returns `neutral` with high confidence when
  it tried hard and could not find a defensible bear case. It NEVER
  returns `bullish` — the strongest signal it can emit is "I could not
  break this; proceed."

Every voice's verdict + confidence + reasoning shows up in the dashboard.
That's the wedge: not "a bot," but a bot whose gate you can inspect.

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

- **Phase B (this sprint, in progress):** add **SendAI Solana Agent Kit** as a
  second execution venue alongside OKX onchainOS. The agent contract stays
  the same; you pick the venue via `EXECUTION_ADAPTER=okx|sendai` in `.env`.
- **v0.3:** the hosted, grounded **Gecko Oracle API** wired into the bot's
  per-cadence calls (currently disabled by default; flip with
  `FUNDAMENTALS_ORACLE_ENABLED=True`). When enabled, every Oracle call's
  surviving dissent renders as a `Dissent:` line in the dashboard + terminal.
- **v1.0:** marketplace integration (Sharktank / Bazaar / frames.ag listing).
  Your agent's track record + the Gecko grader feed determines listing
  visibility; no central trust authority.

## Config

Every tunable lives in `config.py` with paper-safe defaults: sizing, TP/SL,
trailing + stall exits, the instrument universe, concurrency + daily caps.
