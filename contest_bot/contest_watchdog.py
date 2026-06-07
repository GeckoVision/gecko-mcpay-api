#!/usr/bin/env python3
"""Bot-contest watchdog — the 30h-stuck guard.

S31 burned us: bots sat at 0 positions for 30h and we only noticed late. This
flags, per contestant: process/port DEAD, state FROZEN (no write in >FREEZE_MIN),
or STUCK (0 trades AND 0 open past GRACE_HRS — sitting out forever). Exit code 1
if any contestant is unhealthy, so it can drive an alert/cron.

    uv run python contest_watchdog.py
"""
from __future__ import annotations

import json
import os
import urllib.request
from datetime import UTC, datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
FREEZE_MIN = 10.0     # no state write in this long = frozen
GRACE_HRS = 4.0       # after this, 0 trades AND 0 open = stuck-sitting

# name -> (state_file, port)
CONTESTANTS = {
    "trend_breakout": (f"{_HERE}/state/contest/trend_breakout/bot_state.json", 8265),
    "mean_reversion": (f"{_HERE}/state/contest/mean_reversion/bot_state.json", 8266),
    "range_fade": (f"{_HERE}/state/contest/range_fade/bot_state.json", 8268),
    "legacy_gate": (f"{_HERE}/bot_state.json", 8267),
}


def _port_up(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/healthz", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _age_min(saved: str | None) -> float | None:
    if not saved:
        return None
    try:
        return (datetime.now(UTC) - datetime.fromisoformat(saved)).total_seconds() / 60
    except (ValueError, TypeError):
        return None


def main() -> int:
    unhealthy = []
    for name, (path, port) in CONTESTANTS.items():
        up = _port_up(port)
        d = {}
        if os.path.exists(path):
            with open(path) as f:
                d = json.load(f)
        pos = d.get("positions", []) or []
        closed = [p for p in pos if p.get("exit_ts") or p.get("status") in ("closed", "exited")]
        openp = len(pos) - len(closed)
        age = _age_min(d.get("saved_at"))
        boot = _age_min(d.get("still_alive_at")) or age  # rough uptime proxy

        status, why = "OK", []
        if not up:
            status = "DEAD"
            why.append(f"port {port} down")
        if age is not None and age > FREEZE_MIN:
            status = "FROZEN"
            why.append(f"no state write {age:.0f}m")
        if up and len(closed) == 0 and openp == 0 and boot is not None and boot / 60 > GRACE_HRS:
            status = "STUCK"
            why.append(f"0 trades {boot/60:.1f}h (the 30h-stuck pattern)")
        flag = "✅" if status == "OK" else "🚨"
        fresh = f"{age:.0f}m" if age is not None else "—"
        print(f"{flag} {name:<16} {status:<7} trades={len(closed)} open={openp} fresh={fresh}")
        if why:
            print(f"     → {'; '.join(why)}")
        if status != "OK":
            unhealthy.append(name)
    if unhealthy:
        print(f"\n🚨 unhealthy: {', '.join(unhealthy)} — investigate/restart.")
        return 1
    print("\n✅ all contestants healthy.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
