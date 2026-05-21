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
