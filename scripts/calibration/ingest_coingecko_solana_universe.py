"""Phase D #1 — ingest CoinGecko daily close+volume for Solana-native tokens.

Free tier (no key required, 30 req/min). Three-step:
1. Discovery: /coins/markets?category=solana-ecosystem&order=volume_desc&per_page=100
   Returns ranked list of Solana-ecosystem tokens by 24h volume.
2. NATIVE filter: exclude obvious cross-chain tokens (wrapped BTC/ETH, bridged
   assets, stablecoins). Output is Solana-native + Solana-launched.
3. Daily close+volume pull: /coins/{id}/market_chart?vs_currency=usd&days=365
   &interval=daily per token. Returns ~365 daily rows of (ts, close_usd,
   volume_usd). DAILY granularity is appropriate for COHORT derivation (which
   tokens chronically lose on momentum); fine-grained intra-day simulation is
   overkill at the cohort layer.

Output: scripts/calibration/data/solana/<SYMBOL>_dex.json with shape:
list of {ts, open, high, low, close, volume}. Since /market_chart only gives
close (not OHLC), we mirror close into open/high/low — this is honest at the
DAILY level (a daily 'bar' is essentially close-to-close for cohort use).

Run: uv run python scripts/calibration/ingest_coingecko_solana_universe.py
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = REPO_ROOT / "scripts" / "calibration" / "data" / "solana"

CG_BASE = "https://api.coingecko.com/api/v3"

# Free-tier pacing: 30 req/min = 2s/req minimum. Use 3s as headroom.
PACE_SEC = 3.0
N_TOKENS_DEFAULT = 50
DAYS_OF_HISTORY = 365

# Cross-chain / wrapped / bridged tokens we EXCLUDE from "Solana-native" cohort.
# These appear in CoinGecko's "solana-ecosystem" category because they're on
# Solana as wrapped/bridged versions, but they're priced by their HOME chain
# and don't represent Solana-native momentum behavior. For cohort derivation
# we want assets whose price ACTION is determined by Solana DEX flow.
EXCLUDED_IDS = {
    # Wrapped versions of foreign assets
    "wrapped-solana",       # SOL wrapped (duplicates real SOL)
    "coinbase-wrapped-btc", # CBBTC
    "wrapped-btc",
    "weth",
    "wrapped-eth",
    "wrapped-bitcoin",
    # Cross-chain originals (priced by home chain)
    "chainlink",            # LINK is ETH-originated
    "aave",                 # AAVE is ETH-originated
    "render-token",         # RENDER migrated from ETH
    "ethena",
    # Stablecoins (handled by EXCLUDED_SYMBOLS too)
    "usd1-wlfi",            # USD1 from WLFI
}
EXCLUDED_SYMBOLS = {
    # Stablecoins
    "usdc", "usdt", "dai", "pyusd", "fdusd", "usds", "usde", "susde",
    "tusd", "usdp", "frax", "usd1", "usdg",
    # Wrapped/bridged duplicates
    "cbbtc", "wbtc", "weth",
}


# Bot's live universe — force-include these in the cohort even if they
# fall out of the top-N by volume on a given day. The cohort filter is
# useless if it can't classify the bot's actual trading symbols.
BOT_UNIVERSE_IDS = {
    "jito-governance-token",   # JTO
    "jupiter-exchange-solana", # JUP
    "dogwifcoin",              # WIF
    "pyth-network",            # PYTH
    "raydium",                 # RAY
}


def discover_top_tokens(n: int = N_TOKENS_DEFAULT) -> list[dict]:
    """Return list of top-N Solana ecosystem tokens by 24h volume.

    Each dict has at least {id, symbol, name, market_cap, total_volume}.
    Filters: market_cap > $1M (excludes dust), excludes stablecoins by symbol.
    """
    rows: list[dict] = []
    # CoinGecko paginates 100/page; fetch enough to filter
    for page in (1, 2):
        r = httpx.get(
            f"{CG_BASE}/coins/markets",
            params={
                "vs_currency": "usd",
                "category": "solana-ecosystem",
                "order": "volume_desc",
                "per_page": 100,
                "page": page,
            },
            timeout=20,
        )
        if r.status_code == 429:
            time.sleep(30)
            r = httpx.get(
                f"{CG_BASE}/coins/markets",
                params={
                    "vs_currency": "usd",
                    "category": "solana-ecosystem",
                    "order": "volume_desc",
                    "per_page": 100,
                    "page": page,
                },
                timeout=20,
            )
        if r.status_code != 200:
            print(f"  discovery page {page}: HTTP {r.status_code}")
            continue
        rows.extend(r.json())
        time.sleep(PACE_SEC)

    # Filter: skip stables + wrapped + cross-chain + tiny market caps,
    # EXCEPT always retain the bot's universe (force-include even if filtered).
    def _kept(c: dict) -> bool:
        if c.get("id") in BOT_UNIVERSE_IDS:
            return True
        if c.get("symbol", "").lower() in EXCLUDED_SYMBOLS:
            return False
        if c.get("id") in EXCLUDED_IDS:
            return False
        if (c.get("market_cap") or 0) < 5_000_000:
            return False
        return True

    filtered = [c for c in rows if _kept(c)]
    # Dedupe by symbol (some symbols appear under multiple ids — wrapped + native)
    seen_symbols: set[str] = set()
    dedup: list[dict] = []
    for c in filtered:
        sym = c.get("symbol", "").upper()
        if sym and sym not in seen_symbols:
            seen_symbols.add(sym)
            dedup.append(c)
    # Re-sort by volume desc
    dedup.sort(key=lambda c: -(c.get("total_volume") or 0))

    # Now take top-n, but ALWAYS ensure all 5 bot-universe symbols are present
    top_n = dedup[:n]
    top_n_ids = {c.get("id") for c in top_n}
    for c in dedup:
        if c.get("id") in BOT_UNIVERSE_IDS and c.get("id") not in top_n_ids:
            top_n.append(c)
            top_n_ids.add(c.get("id"))
    return top_n


def fetch_market_chart(coin_id: str, days: int = DAYS_OF_HISTORY) -> dict | None:
    """Fetch CoinGecko /coins/{id}/market_chart for close+volume time-series.

    Returns {prices: [[ts_ms, close_usd], ...], total_volumes: [[ts_ms, vol_usd], ...]}.
    For days>=90 with interval=daily, returns ~days daily rows. Best-effort.
    """
    for attempt in range(3):
        try:
            r = httpx.get(
                f"{CG_BASE}/coins/{coin_id}/market_chart",
                params={"vs_currency": "usd", "days": days, "interval": "daily"},
                timeout=20,
            )
            if r.status_code == 200:
                return r.json()
            if r.status_code == 429:
                wait = 12 * (attempt + 1)
                print(f"      429; backing off {wait}s")
                time.sleep(wait)
                continue
            print(f"      HTTP {r.status_code}")
            return None
        except Exception as e:
            print(f"      {type(e).__name__}: {e}")
            return None
    return None


def write_solana_ohlcv(symbol: str, chart: dict) -> Path | None:
    """Convert CoinGecko market_chart to the Binance-perp file shape.

    /market_chart gives close + volume but no OHLC. We mirror close into
    open/high/low — honest at the daily-cohort layer (the cohort question is
    "did this token go up or down over the year"; high/low intra-day noise
    isn't material at this granularity).

    Returns the written path, or None if input is too short.
    """
    if not chart:
        return None
    prices = chart.get("prices") or []
    volumes = chart.get("total_volumes") or []
    if len(prices) < 30:  # need at least 30 daily points
        return None
    # Build vol lookup
    vol_by_ts = {int(row[0]): float(row[1]) for row in volumes}
    rows = []
    for p in prices:
        ts = int(p[0])
        close = float(p[1])
        rows.append({
            "ts": ts,
            "open": close,  # daily proxy: no intra-day OHLC available
            "high": close,
            "low": close,
            "close": close,
            "volume": float(vol_by_ts.get(ts, 0.0)),
        })
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{symbol.upper()}_dex.json"
    p.write_text(json.dumps(rows))
    return p


def main() -> int:
    n = int(os.environ.get("INGEST_N", str(N_TOKENS_DEFAULT)))
    days = int(os.environ.get("INGEST_DAYS", str(DAYS_OF_HISTORY)))

    print(f"=== Phase D #1: ingest CoinGecko OHLC for top-{n} Solana ecosystem tokens ===")
    print(f"    days_of_history={days}  pace={PACE_SEC}s/request  out={OUT_DIR.relative_to(REPO_ROOT)}")
    print()

    print("[1/3] Discovering top tokens by volume...")
    tokens = discover_top_tokens(n=n)
    print(f"    discovered {len(tokens)} tokens (filtered: market_cap >= $1M, non-stable)")
    if not tokens:
        print("    ABORT: no tokens returned")
        return 1
    for i, t in enumerate(tokens[:10]):
        print(f"      #{i+1:>2d}  {t.get('symbol','').upper():<8s}  vol_24h_usd=${(t.get('total_volume') or 0):>14,.0f}  mcap=${(t.get('market_cap') or 0):>14,.0f}  id={t.get('id')}")
    if len(tokens) > 10:
        print(f"      ... + {len(tokens)-10} more")
    print()

    print(f"[2/3] Fetching market_chart (eta ~{len(tokens) * PACE_SEC / 60:.1f}min for {len(tokens)} tokens × 1 call each)...")
    success = 0
    fail = 0
    for i, t in enumerate(tokens):
        sym = t.get("symbol", "").upper()
        cid = t.get("id")
        if not cid or not sym:
            continue
        print(f"  [{i+1:>2d}/{len(tokens)}] {sym} ({cid})", flush=True)
        chart = fetch_market_chart(cid, days=days)
        time.sleep(PACE_SEC)
        if not chart:
            print(f"      market_chart fetch FAILED")
            fail += 1
            continue
        path = write_solana_ohlcv(sym, chart)
        if path is None:
            print(f"      insufficient data ({len(chart.get('prices') or [])} rows; need >=30)")
            fail += 1
            continue
        prices = chart.get("prices") or []
        print(f"      wrote {len(prices)} rows → {path.relative_to(REPO_ROOT)}")
        success += 1

    print()
    print(f"[3/3] DONE.  success={success}  fail={fail}  out_dir={OUT_DIR}")
    return 0 if success > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
