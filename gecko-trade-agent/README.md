# gecko-trade-agent

A self-hostable, **paper-default** trading agent with a transparent 5-voice
gate and a live dashboard. Five voices — chart, regime, memory, risk, and a
**pre-execution devil's advocate** — debate every entry through a coordinator
whose logic lives in code, not a prompt.

Built and hardened during the OKX Agentic Trading Contest; the strategist
voice (devil's advocate) was added in Sprint 21 to close the architectural
hole where the executor effectively rubber-stamped the chart_analyst's
signal. Now there's a voice on the panel whose only job is to find the
strongest reason the trade fails — before any swap fires.

## 60-second start

```bash
pip install -r requirements.txt
cp .env.example .env          # set OPENROUTER_API_KEY (required)
onchainos login               # one-time, for candles + OKX execution
python bot.py                 # runs in paper mode
# open http://localhost:8265
```

## What you'll see

Five voices — **chart, regime, memory, risk, strategist** — vote on every
candidate through a code-pinned coordinator. The dashboard shows each
instrument's regime and every voice's verdict, confidence, and reasoning,
live. When the strategist finds a defensible falsifier, it prints
`bearish` with reasoning; when it tried hard and could not break the
setup, it prints `neutral` with high confidence — that's a real signal
("I could not falsify; proceed"), not abstention.

## Going live

Edit `config.py` → `PAPER_TRADE = False`. Do this deliberately. The bot
sells discipline + transparency, not guaranteed returns — breakout is
-EV in chop, and the bot abstains there on purpose. Our published
falsification history is part of the product: 10 nulls including a
+2.3% carry result that collapsed when re-tested against deeper data.

## Execution venues

- **OKX onchainOS** (default, today) — `EXECUTION_ADAPTER=okx`.
- **SendAI Solana Agent Kit** *(Phase B, landing this sprint)* —
  `EXECUTION_ADAPTER=sendai`. Same agent contract; swap layer is the
  one thing that changes.

See `SKILL.md` for the full story and `config.py` for every tunable.
