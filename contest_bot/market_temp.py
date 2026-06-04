"""Market-temperature sourcing — turn news/sentiment into a risk-on/off read.

"Fill the market temp": the system should SEE when the regime is macro-risk-off
(geopolitics, recession, hacks) and route to safety/yield instead of chasing a
bounce. This aggregates OKX news sentiment + a macro-headline keyword scan into:
  • temp ∈ [-1 risk-off … +1 risk-on], BTC-anchored (BTC is the macro driver)
  • per-coin net sentiment (bullish_ratio − bearish_ratio)
  • sentiment/price DIVERGENCE flags (sentiment bullish but price sold off →
    a relief-bounce CANDIDATE, flagged as counter-trend, NOT a buy signal)

Pure + injectable: `compute_market_temp(coins, headlines)` takes parsed inputs,
so it's testable with no network. `from_okx_sentiment()` parses the OKX
`news_get_coin_sentiment` response. A worker/voice (S28 market_news pipeline)
feeds it at runtime; this module is the read, not the fetcher. It does NOT touch
the founder's `decision_store/news_sink.py` / `news_query.py`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# macro keywords that pull the temperature toward risk-off / risk-on
_RISK_OFF = {
    "war", "conflict", "invasion", "missile", "strike", "sanction", "escalation",
    "recession", "downturn", "slowdown", "default", "crash", "selloff", "sell-off",
    "plunge", "liquidation", "liquidations", "hack", "exploit", "breach", "rug",
    "ban", "crackdown", "fear", "capitulation", "bear",
}
_RISK_ON = {
    "rally", "surge", "soar", "breakout", "inflow", "inflows", "etf", "approval",
    "all-time high", "ath", "rebound", "recovery", "bullish", "adoption", "upgrade",
}


@dataclass
class CoinTemp:
    coin: str
    bullish_ratio: float
    bearish_ratio: float
    mentions: int

    @property
    def net(self) -> float:
        return self.bullish_ratio - self.bearish_ratio


@dataclass
class MarketTemp:
    temp: float  # -1 risk-off … +1 risk-on
    label: str  # risk_off | cool | neutral | warm | risk_on
    btc_net: float
    drivers: list[str] = field(default_factory=list)
    coins: dict[str, CoinTemp] = field(default_factory=dict)
    divergences: list[str] = field(default_factory=list)  # informational, NOT buy signals

    def as_dict(self) -> dict:
        return {
            "temp": round(self.temp, 3),
            "label": self.label,
            "btc_net": round(self.btc_net, 3),
            "drivers": self.drivers,
            "coins": {c: {"net": round(v.net, 3), "mentions": v.mentions} for c, v in self.coins.items()},
            "divergences": self.divergences,
        }


def from_okx_sentiment(resp: dict) -> dict[str, CoinTemp]:
    """Parse an OKX `news_get_coin_sentiment` response → {COIN: CoinTemp}."""
    out: dict[str, CoinTemp] = {}
    data = (resp or {}).get("data") or []
    details = data[0].get("details", []) if data and isinstance(data[0], dict) else []
    for d in details:
        s = d.get("sentiment") or {}
        try:
            out[d["ccy"]] = CoinTemp(
                coin=d["ccy"],
                bullish_ratio=float(s.get("bullishRatio") or 0),
                bearish_ratio=float(s.get("bearishRatio") or 0),
                mentions=int(d.get("mentionCnt") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _keyword_signal(headlines: list[str]) -> tuple[float, list[str]]:
    """Scan headlines → a [-1,+1] macro nudge + the drivers that fired."""
    if not headlines:
        return 0.0, []
    text = " ".join(headlines).lower()

    def hit(kw: str) -> bool:
        # word-boundary + optional plural: "recession"→"recessions" yes; "war"→"warns" no
        return re.search(rf"\b{re.escape(kw)}s?\b", text) is not None

    off = sorted({w for w in _RISK_OFF if hit(w)})
    on = sorted({w for w in _RISK_ON if hit(w)})
    if "all time high" in text:
        on.append("all-time-high")
    nudge = 0.0
    if off:
        nudge -= min(0.5, 0.12 * len(off))
    if on:
        nudge += min(0.4, 0.10 * len(on))
    drivers = [f"-{w}" for w in off] + [f"+{w}" for w in on]
    return nudge, drivers


def compute_market_temp(
    coins: dict[str, CoinTemp], headlines: list[str] | None = None, price_moves: dict[str, float] | None = None
) -> MarketTemp:
    """Combine BTC-anchored sentiment + macro headlines → a market-temperature read.

    price_moves (optional, {COIN: recent_%_move}) lets us flag sentiment/price
    DIVERGENCE: a coin net-bullish in sentiment but down hard in price = a
    relief-bounce candidate (informational; our discipline still gates it as
    counter-trend in a risk-off tape)."""
    btc = coins.get("BTC")
    base = btc.net if btc else (sum(c.net for c in coins.values()) / len(coins) if coins else 0.0)
    nudge, kw_drivers = _keyword_signal(headlines or [])
    temp = max(-1.0, min(1.0, base + nudge))

    if temp <= -0.25:
        label = "risk_off"
    elif temp <= -0.08:
        label = "cool"
    elif temp < 0.08:
        label = "neutral"
    elif temp < 0.25:
        label = "warm"
    else:
        label = "risk_on"

    drivers: list[str] = []
    if btc:
        drivers.append(f"BTC sentiment net {btc.net:+.2f} ({btc.mentions} mentions)")
    drivers += kw_drivers

    divergences: list[str] = []
    for c, ct in coins.items():
        if c == "BTC":
            continue
        moved_down = price_moves and price_moves.get(c, 0.0) <= -3.0
        if ct.net >= 0.20 and (moved_down or temp <= -0.08):
            tag = f"{c}: sentiment {ct.net:+.2f}"
            if price_moves and c in price_moves:
                tag += f" vs price {price_moves[c]:+.1f}%"
            divergences.append(tag + " (relief-bounce candidate — counter-trend)")

    return MarketTemp(
        temp=temp, label=label, btc_net=(btc.net if btc else 0.0),
        drivers=drivers, coins=coins, divergences=divergences,
    )


# ── snapshot I/O (a worker writes; the API + bots read) ──────────────
def snapshot_path() -> str:
    base = os.environ.get("GECKO_STATE_DIR") or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "market_temp.json")


def save_snapshot(mt: MarketTemp, path: str | None = None) -> str:
    p = path or snapshot_path()
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    payload = mt.as_dict()
    payload["updated_at"] = datetime.now(UTC).isoformat()
    with open(p, "w") as f:
        json.dump(payload, f)
    return p


def load_snapshot(path: str | None = None) -> dict:
    """Return the latest market-temp snapshot, or a neutral/stale default if no
    worker has written one yet (so callers never crash on a cold start)."""
    p = path or snapshot_path()
    if not os.path.exists(p):
        return {"temp": 0.0, "label": "neutral", "stale": True, "drivers": ["no market-temp snapshot yet"]}
    try:
        with open(p) as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {"temp": 0.0, "label": "neutral", "stale": True, "drivers": ["unreadable snapshot"]}
