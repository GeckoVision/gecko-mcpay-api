#!/usr/bin/env python3
"""Replay-v2 — pre-contest period through current bot's DETERMINISTIC gate stack.

Founder's reframe (2026-05-27): "Not goal-seeking. Diagnostic. For each
historical winner, which specific gate blocks it under current bot logic?"

Approach:
1. Pull HOURLY OHLCV from CoinGecko free for the historical universe
   (PYTH/JTO/JUP/BONK/DRIFT/WIF/RAY/MEW/POPCAT) over May 15-22.
2. For each historical local_panel ACT event (19 acts May 20-21), look up
   the OHLCV bar at that timestamp + apply the CURRENT bot's gate stack:
     - Fix 4: would price_breakout fire? (we only allow price_breakout per
       the bot's current entry logic; volume_spike alone declines)
     - Fix 5: is regime_1h TREND-UP?
     - memory_voice v2 cohort: would symbol be in MINUS_EV cohort?
     - coordinator rule: would all voices align (approximated)?
3. Diagnostic output: PER-TRADE table showing which specific gate blocks
   or passes each historical entry.

Output: stdout report + private/strategy/2026-05-27-replay-v2-findings.md
"""

from __future__ import annotations

import json
import os
import statistics as st
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

_HERE = Path(__file__).resolve().parent
CACHE_DIR = Path(_HERE).parent.parent / "scripts" / "calibration" / "data" / "replay_v2"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# CoinGecko id map for historical universe
COIN_IDS = {
    "PYTH": "pyth-network",
    "JTO": "jito-governance-token",
    "JUP": "jupiter-exchange-solana",
    "BONK": "bonk",
    "DRIFT": "drift-protocol",
    "WIF": "dogwifcoin",
    "RAY": "raydium",
    "MEW": "cat-in-a-dogs-world",
    "POPCAT": "popcat",
}

# Current bot gate thresholds (per memory_voice_v2.py + bot constants)
PRICE_BREAKOUT_LOOKBACK_BARS = 20  # ~20h on hourly bars (loose proxy of bot's 30s polling)
TREND_UP_EMA_SHORT = 24            # 24h EMA
TREND_UP_EMA_LONG = 120            # 5d EMA (faster than the 50/200d daily check; tuned for hourly)


def fetch_hourly_ohlcv(coin_id: str, days: int = 14) -> list[list]:
    """Fetch CoinGecko /coins/{id}/market_chart at hourly granularity.

    Free tier: hourly auto-returned for days in [2, 90]. Returns list of
    [ts_ms, price] pairs from `prices` field.
    """
    cache = CACHE_DIR / f"{coin_id}_market_chart.json"
    if cache.exists() and (time.time() - cache.stat().st_mtime) < 6 * 3600:
        return json.loads(cache.read_text())

    for attempt in range(3):
        try:
            r = httpx.get(
                f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": days},
                timeout=20,
            )
            if r.status_code == 200:
                data = r.json()
                cache.write_text(json.dumps(data))
                return data
            if r.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"      429 backoff {wait}s", flush=True)
                time.sleep(wait)
                continue
            print(f"      HTTP {r.status_code}", flush=True)
            return {}
        except Exception as e:
            print(f"      {type(e).__name__}: {e}", flush=True)
            return {}
    return {}


def load_universe_ohlcv() -> dict[str, list[tuple[int, float]]]:
    """For each historical-universe symbol, fetch + return (ts_ms, price) hourly series."""
    out: dict[str, list[tuple[int, float]]] = {}
    for sym, cid in COIN_IDS.items():
        print(f"  fetching {sym} ({cid})", flush=True)
        data = fetch_hourly_ohlcv(cid, days=14)
        prices = data.get("prices") or []
        if prices:
            out[sym] = [(int(p[0]), float(p[1])) for p in prices]
        else:
            print(f"    NO DATA for {sym}")
        time.sleep(3.0)  # gentle pacing
    return out


def load_historical_events() -> dict:
    """Load May 20-21 historical local_panel acts + position_closes from artifact log."""
    import glob
    acts = []
    closes = []
    for f in sorted(glob.glob('contest_bot/artifact_2026052[01]*.jsonl')):
        try:
            with open(f) as fh:
                for line in fh:
                    try:
                        d = json.loads(line)
                        kind = d.get('kind')
                        p = d.get('payload') or {}
                        if kind == 'local_panel' and p.get('action') == 'act':
                            acts.append({
                                'ts': d.get('ts'),
                                'instrument': p.get('instrument') or p.get('symbol'),
                                'reason': p.get('reason'),
                            })
                        elif kind == 'position_close':
                            closes.append({
                                'ts': d.get('ts'),
                                'symbol': p.get('symbol'),
                                'pnl_pct': p.get('pnl_pct'),
                                'exit_reason': p.get('exit_reason'),
                            })
                    except Exception:
                        pass
        except FileNotFoundError:
            pass
    return {"acts": acts, "closes": closes}


def _bar_at(series: list[tuple[int, float]], target_ts_ms: int) -> tuple[int, float] | None:
    """Return the (ts, price) entry in series at or just before target_ts."""
    if not series:
        return None
    best = None
    for ts, px in series:
        if ts <= target_ts_ms:
            best = (ts, px)
        else:
            break
    return best


def _idx_at(series: list[tuple[int, float]], target_ts_ms: int) -> int:
    """Return the index in series at or just before target_ts."""
    if not series:
        return -1
    for i in range(len(series) - 1, -1, -1):
        if series[i][0] <= target_ts_ms:
            return i
    return -1


def _ema(values: list[float], period: int) -> float | None:
    """Simple EMA over a list."""
    if len(values) < period:
        return None
    alpha = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = alpha * v + (1 - alpha) * ema
    return ema


def diagnose_entry(symbol: str, target_ts_ms: int, universe: dict[str, list[tuple[int, float]]]) -> dict:
    """For a historical entry at (symbol, target_ts), apply current bot's gate stack.

    Returns a diagnostic dict explaining which gate blocks/passes.
    """
    series = universe.get(symbol)
    if not series:
        return {"symbol": symbol, "error": "NO_OHLCV_DATA", "current_bot_action": "?"}

    idx = _idx_at(series, target_ts_ms)
    if idx < 0:
        return {"symbol": symbol, "error": "TS_BEFORE_DATA_START", "current_bot_action": "?"}
    if idx < PRICE_BREAKOUT_LOOKBACK_BARS:
        return {"symbol": symbol, "error": "INSUFFICIENT_HISTORY", "current_bot_action": "?",
                "diag": f"only {idx} bars before entry; need >= {PRICE_BREAKOUT_LOOKBACK_BARS}"}

    # Bar at entry
    entry_ts, entry_px = series[idx]

    # GATE 1: price_breakout
    # Fix 4 says: bot only accepts price_breakout (volume_spike alone declined)
    # Check: is current close > max(prior N closes)?
    prior_closes = [series[idx - i][1] for i in range(1, PRICE_BREAKOUT_LOOKBACK_BARS + 1)]
    prior_max = max(prior_closes)
    breakout = entry_px > prior_max

    # GATE 2: regime_1h (TREND-UP proxy via EMA50 > EMA200 + price > EMA50)
    closes_for_ema = [px for _, px in series[max(0, idx - TREND_UP_EMA_LONG - 10):idx + 1]]
    ema_short = _ema(closes_for_ema, TREND_UP_EMA_SHORT)
    ema_long = _ema(closes_for_ema, TREND_UP_EMA_LONG)
    regime_1h = "UNKNOWN"
    if ema_short is not None and ema_long is not None:
        if ema_short > ema_long and entry_px > ema_short:
            regime_1h = "TREND-UP"
        elif ema_short < ema_long and entry_px < ema_short:
            regime_1h = "TREND-DOWN"
        else:
            regime_1h = "CHOP"
    fix5_pass = regime_1h == "TREND-UP"

    # GATE 3: memory_voice v2 SOLANA cohort (SOFT, 0.40 confidence — won't single-vote-block)
    # Per Phase D #2 rolling cohort: WIF, PYTH, BONK in MINUS_EV
    SOLANA_MINUS_EV = {"WIF", "IO", "ATH", "VIRTUAL", "ORDI", "FIDA", "BIO", "PYTH", "FARTCOIN", "BONK",
                        # Plus rolling additions from Phase D #2:
                        "TRUMP", "HOLO", "JUP", "BAT"}
    SOLANA_PLUS_EV = {"MUON", "GOOGLX", "CHZ", "KMNO", "ZEC", "CAKE", "DRIFT", "HIMSON", "GRASS", "PRIME",
                      # Plus rolling additions:
                      "JTO", "PENGU", "STRK", "ZAMA"}
    if symbol in SOLANA_MINUS_EV:
        v2_vote = "bearish_soft"
    elif symbol in SOLANA_PLUS_EV:
        v2_vote = "bullish_soft"
    else:
        v2_vote = "abstain"

    # GATE 4: coordinator rule — "all_voices_aligned" requires no bear/neutral
    # If memory_voice v2 votes bearish SOFT (0.40), it adds weight to bear side
    # but is below the panel-threshold. For diagnostic: count "would memory_voice
    # block the unanimous-bull call?"
    panel_pass_likely = v2_vote != "bearish_soft"  # SOFT bearish breaks unanimous-bull

    # Overall: would current bot ENTER?
    would_enter = breakout and fix5_pass and panel_pass_likely

    # Identify the SPECIFIC blocker (first failure)
    blocker = None
    if not breakout:
        blocker = "FIX 4 / no_price_breakout"
    elif not fix5_pass:
        blocker = f"FIX 5 / regime={regime_1h}"
    elif not panel_pass_likely:
        blocker = f"memory_voice v2 / {symbol}_in_SOLANA_MINUS_EV"

    return {
        "symbol": symbol,
        "entry_ts_actual": datetime.fromtimestamp(target_ts_ms / 1000, tz=timezone.utc).isoformat(),
        "ohlcv_ts_used": datetime.fromtimestamp(entry_ts / 1000, tz=timezone.utc).isoformat(),
        "entry_px": entry_px,
        "prior_N_max": prior_max,
        "breakout": breakout,
        "regime_1h": regime_1h,
        "fix5_pass": fix5_pass,
        "v2_vote": v2_vote,
        "panel_pass_likely": panel_pass_likely,
        "current_bot_action": "ENTER" if would_enter else "BLOCK",
        "blocker": blocker,
    }


def main() -> int:
    print("=" * 100)
    print("REPLAY-v2 — pre-contest May 20-21 through CURRENT bot's deterministic gate stack")
    print("=" * 100)

    print("\n[1/3] Loading OHLCV (CoinGecko free, ~30s)...")
    universe = load_universe_ohlcv()
    print(f"  loaded {len(universe)}/{len(COIN_IDS)} coins")
    for sym, series in universe.items():
        if series:
            first_ts = datetime.fromtimestamp(series[0][0] / 1000, tz=timezone.utc).isoformat()
            last_ts = datetime.fromtimestamp(series[-1][0] / 1000, tz=timezone.utc).isoformat()
            print(f"    {sym}: {len(series)} bars  span [{first_ts[:10]} .. {last_ts[:10]}]")

    print("\n[2/3] Loading historical events...")
    events = load_historical_events()
    print(f"  {len(events['acts'])} historical ACTS")
    print(f"  {len(events['closes'])} historical CLOSES")

    # Map symbol → its close PnL (when we have one) for the row's annotation
    close_by_symbol_ts: dict[tuple[str, str], float] = {}
    for c in events['closes']:
        sym = (c.get('symbol') or '').split('-')[0]
        # Match acts to closes within reason (same symbol; pick first close in same day)
        close_by_symbol_ts.setdefault(sym, []).append(c)

    print("\n[3/3] Replay-v2: applying CURRENT bot's deterministic gates per historical act:")
    print()
    print(f"  {'historical_ts':<20s}  {'sym':<6s}  {'entry_px':>10s}  {'prior_max':>10s}  "
          f"{'breakout':>9s}  {'regime':<10s}  {'fix5':>5s}  {'v2_vote':<14s}  "
          f"{'panel':>6s}  {'CURRENT_BOT':<10s}  {'blocker':<40s}")
    print("-" * 170)

    pass_count = 0
    block_count = 0
    blocker_dist = Counter()
    results = []
    for act in events['acts']:
        ts_str = act.get('ts')
        if not ts_str:
            continue
        target_ts_ms = int(datetime.fromisoformat(ts_str.replace('Z', '+00:00')).timestamp() * 1000)
        sym = act.get('instrument')
        diag = diagnose_entry(sym, target_ts_ms, universe)
        results.append(diag)
        action = diag.get("current_bot_action", "?")
        if action == "ENTER":
            pass_count += 1
        elif action == "BLOCK":
            block_count += 1
            blocker_dist[diag.get("blocker") or "unknown"] += 1
        # Print row
        if "error" in diag:
            print(f"  {ts_str[:19]:<20s}  {sym:<6s}  ERROR: {diag['error']}")
        else:
            print(
                f"  {ts_str[:19]:<20s}  {sym:<6s}  "
                f"{diag.get('entry_px',0):>10.5f}  {diag.get('prior_N_max',0):>10.5f}  "
                f"{'YES' if diag.get('breakout') else 'no':>9s}  "
                f"{diag.get('regime_1h',''):<10s}  "
                f"{'✓' if diag.get('fix5_pass') else '✗':>5s}  "
                f"{diag.get('v2_vote',''):<14s}  "
                f"{'✓' if diag.get('panel_pass_likely') else '✗':>6s}  "
                f"{action:<10s}  {(diag.get('blocker') or 'none'):<40s}"
            )

    print()
    print("=" * 100)
    print("SUMMARY:")
    print("=" * 100)
    n = len(results)
    print(f"  Historical acts: {n}")
    print(f"  Current bot would ENTER: {pass_count}/{n} ({100*pass_count/max(n,1):.0f}%)")
    print(f"  Current bot would BLOCK: {block_count}/{n} ({100*block_count/max(n,1):.0f}%)")
    print()
    print(f"  Block reasons:")
    for r, c in blocker_dist.most_common():
        print(f"    {c:>3d}×  {r}")

    # Per-symbol pass/block
    print()
    print(f"  By symbol (historical → current verdict):")
    by_sym = defaultdict(lambda: {"enter": 0, "block": 0, "blockers": []})
    for r in results:
        if "error" in r: continue
        sym = r["symbol"]
        if r["current_bot_action"] == "ENTER":
            by_sym[sym]["enter"] += 1
        else:
            by_sym[sym]["block"] += 1
            by_sym[sym]["blockers"].append(r.get("blocker"))
    for sym in sorted(by_sym):
        s = by_sym[sym]
        blockers_uniq = Counter(s["blockers"])
        blockers_str = ', '.join(f"{c}× {b}" for b, c in blockers_uniq.most_common(2))
        print(f"    {sym:<8s}  enter={s['enter']}  block={s['block']}  blocked_by: {blockers_str}")

    print()
    print("CAVEATS:")
    print("  1. Hourly OHLCV (CoinGecko free) — coarser than bot's 30s polling. Breakout signal accurate at hourly resolution but intra-bar fluctuations missed.")
    print("  2. regime_1h is approximated via EMA24/EMA120 on hourly bars (proxy for bot's 1h regime). True bot uses actual 1h EMA-stack indicator.")
    print("  3. memory_voice v2 cohort uses CURRENT (rolling 90d) cohort lists; not as-of-May-20 state.")
    print("  4. chart_analyst voice not simulated (it's an LLM call); panel-pass approximation = 'cohort doesn't vote bearish'.")
    print("  5. Sample N=19 historical acts — directional only.")

    # Persist
    out_dir = Path(_HERE).parent.parent / "analysis" / "data" / "replay_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "diagnostics.json").write_text(json.dumps(results, indent=2, default=str))
    print(f"\nResults → {(out_dir / 'diagnostics.json').relative_to(Path(_HERE).parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
