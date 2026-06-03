"""Sprint 31 monolith-surgery regression guard.

The memecoin bot must keep running UNCHANGED on port 8267 (its S30 MFI hard-gate
falsifier is still accruing N>=15). This test proves the multi-strategy surgery
is INERT when all GECKO_* env are unset (legacy path byte-identical), and wires
correctly when set. Uses subprocesses so each gets a clean module-level env
(the universe/venue branch runs at import time).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CONTEST_BOT_DIR = Path(__file__).resolve().parents[1]


def _probe(env_extra: dict, code: str) -> str:
    env = dict(os.environ)
    # never arm the decision store / never run main in the probe
    env["GECKO_DECISION_STORE_OFF"] = "1"
    env["PYTEST_CURRENT_TEST"] = "1"
    env.update(env_extra)
    full = "import jto_breakout_gecko_gated_contest_bot as bot\n" + code
    out = subprocess.run(
        [sys.executable, "-c", full],
        cwd=str(_CONTEST_BOT_DIR),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, f"probe failed:\nSTDOUT={out.stdout}\nSTDERR={out.stderr}"
    return out.stdout.strip()


def test_legacy_path_byte_identical_when_env_unset():
    out = _probe(
        {},
        "print(bot.GECKO_STRATEGY)\n"
        "print(','.join(i['symbol'] for i in bot.INSTRUMENTS))\n"
        "print(type(bot.oc).__name__)\n"
        "print('honeypot_check' in bot.SAFETY)\n"
        "print(bot.TAKE_PROFIT_PCT, bot.STOP_LOSS_PCT)\n",
    ).splitlines()
    assert out[-5] == "jto_breakout"
    assert out[-4] == "PYTH,WIF"  # unchanged memecoin universe
    assert out[-3] == "OnchainOS"  # still the Solana feed
    assert out[-2] == "True"  # SAFETY honeypot scan still on
    assert out[-1] == "2 3"  # original exit constants untouched


def test_trend_breakout_okx_mode_wires():
    out = _probe(
        {
            "GECKO_STRATEGY": "trend_breakout",
            "GECKO_UNIVERSE": "BTC,ETH,SOL,XRP,DOGE",
            "GECKO_VENUE": "okx_spot",
        },
        "print(bot.GECKO_STRATEGY)\n"
        "print(','.join(i['mint'] for i in bot.INSTRUMENTS))\n"
        "print(type(bot.oc).__name__)\n"
        "print(type(bot._STRATEGY).__name__)\n"
        "print(len(bot.SAFETY))\n"
        "print(bot.TAKE_PROFIT_PCT, bot.STOP_LOSS_PCT)\n",
    ).splitlines()
    assert out[-6] == "trend_breakout"
    assert out[-5] == "BTC/USDT,ETH/USDT,SOL/USDT,XRP/USDT,DOGE/USDT"
    assert out[-4] == "OkxSpotCandleProvider"  # feed swapped, no order path
    assert out[-3] == "TrendBreakout"
    assert out[-2] == "0"  # SAFETY neutralized on okx_spot
    assert out[-1] == "1.0 0.8"  # exits from trend exit_policy()


def test_mean_reversion_disables_trailing():
    out = _probe(
        {
            "GECKO_STRATEGY": "mean_reversion",
            "GECKO_UNIVERSE": "BTC,ETH",
            "GECKO_VENUE": "okx_spot",
        },
        "print(bot.TAKE_PROFIT_PCT, bot.STOP_LOSS_PCT)\nprint(bot.TRAIL_ACTIVATE_AFTER_PCT)\n",
    ).splitlines()
    assert out[-2] == "0.8 0.5"
    assert float(out[-1]) >= 999.0  # trailing disabled for the snap-back trade
