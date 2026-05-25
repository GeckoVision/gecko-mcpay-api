#!/usr/bin/env python3
"""Normalize a Dune `dex_solana.trades` hourly-net-flow execution result into
per-token flow tapes aligned to the 1H price-tape clock (ms-epoch `ts`).

Input: the raw getExecutionResults JSON (schema: {data:{rows:[{hour,mint,
net_usd_flow,gross_usd_vol,trades}]}, resultMetadata:{...}}).
Output: scripts/calibration/data/flow/{SYM}_1H_flow.json  ->  [{ts, net, gross, trades}]

Usage: python build_flow_tapes.py <execution_result.json>
Keeps the big payload OUT of the agent context — prints only a coverage summary.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import statistics as st
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(_HERE, "data", "flow")

MINT_TO_SYM = {
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "WIF",
    "HZ1JovNiVvGrGNiiYvEozEVgZ58xaU3RKwX8eACQBCt3": "PYTH",
    "jtojtomepa8beP8AuQc6eXt5FriJwfFMwQx2v2f9mCL": "JTO",
    "ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82": "BOME",
}


def parse_hour_to_ms(h) -> int:
    """Dune date_trunc('hour', ts) -> ms-epoch. Handles ISO strings and epochs."""
    if isinstance(h, (int, float)):
        v = float(h)
        return int(v if v > 1e11 else v * 1000)  # secs vs ms heuristic
    # tokens like ['2025-08-22', '00:00:00.000', 'UTC'] -> keep date + time only
    parts = str(h).strip().replace("T", " ").split()
    s = (parts[0] + " " + parts[1]) if len(parts) >= 2 else parts[0]
    fmts = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")
    for f in fmts:
        try:
            d = dt.datetime.strptime(s, f).replace(tzinfo=dt.UTC)
            return int(d.timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError(f"unparseable hour: {h!r}")


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: build_flow_tapes.py <execution_result.json>", file=sys.stderr)
        return 2
    with open(sys.argv[1]) as f:
        payload = json.load(f)
    meta = payload.get("resultMetadata", {})
    rows = payload["data"]["rows"]
    print(
        f"totalRowCount={meta.get('totalRowCount')}  rows_in_payload={len(rows)}  "
        f"cost_credits={meta.get('executionCostCredits')}"
    )
    if meta.get("totalRowCount") and len(rows) < meta["totalRowCount"]:
        print(
            f"!! WARNING: payload truncated ({len(rows)} < {meta['totalRowCount']}) — "
            f"re-pull with higher limit/pagination",
            file=sys.stderr,
        )

    by_sym: dict[str, list[dict]] = {s: [] for s in MINT_TO_SYM.values()}
    unknown = 0
    for r in rows:
        sym = MINT_TO_SYM.get(r["mint"])
        if sym is None:
            unknown += 1
            continue
        by_sym[sym].append(
            {
                "ts": parse_hour_to_ms(r["hour"]),
                "net": float(r["net_usd_flow"]),
                "gross": float(r["gross_usd_vol"]),
                "trades": int(r["trades"]),
            }
        )
    if unknown:
        print(f"  skipped {unknown} rows with unmapped mint", file=sys.stderr)

    os.makedirs(OUT_DIR, exist_ok=True)
    for sym, recs in by_sym.items():
        recs.sort(key=lambda x: x["ts"])
        with open(os.path.join(OUT_DIR, f"{sym}_1H_flow.json"), "w") as f:
            json.dump(recs, f)
        if recs:
            ts = [x["ts"] for x in recs]
            nets = [x["net"] for x in recs]

            def fmt(t):
                return dt.datetime.utcfromtimestamp(t / 1000).strftime("%Y-%m-%d %H:%M")

            print(
                f"  {sym:5} n={len(recs):5}  {fmt(min(ts))} -> {fmt(max(ts))}  "
                f"net[min/med/max]=[{min(nets):+,.0f}/{st.median(nets):+,.0f}/{max(nets):+,.0f}]  "
                f"hrs_with_trades={len(recs)}"
            )
        else:
            print(f"  {sym:5} n=0  (NO DATA)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
