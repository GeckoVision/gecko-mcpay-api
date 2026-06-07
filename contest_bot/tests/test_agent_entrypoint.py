import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _entrypoint() -> str:
    with open(os.path.join(ROOT, "docker-entrypoint-agent.sh")) as f:
        return f.read()


def test_entrypoint_bakes_paper_and_stub():
    s = _entrypoint()
    assert re.search(r"export PAPER_TRADE=true", s)
    assert re.search(r"export X402_MODE=stub", s)
    assert "GECKO_STATE_BACKEND=mongo" in s


def test_entrypoint_never_flips_live():
    s = _entrypoint()
    assert "PAPER_TRADE=false" not in s
    assert "X402_MODE=live" not in s


def test_entrypoint_execs_monolith():
    assert "jto_breakout_gecko_gated_contest_bot.py" in _entrypoint()


def test_entrypoint_uses_headless_okx_spot_venue():
    # 2026-06-07 crash-loop fix: the hosted agent MUST run the okx_spot paper
    # venue (public ccxt market data — no onchainos CLI, no wallet login).
    # The legacy onchainos venue can't run headless and crash-looped on
    # "Not logged in → sys.exit(1)". Lock the venue so it can't silently regress.
    s = _entrypoint()
    assert "GECKO_VENUE=" in s and "okx_spot" in s
    assert "GECKO_STRATEGY=" in s
