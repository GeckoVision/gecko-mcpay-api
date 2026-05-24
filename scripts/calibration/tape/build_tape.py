#!/usr/bin/env python3
"""Historical-tape collector + forward-collector + coverage summary (s46).

Builds the first persistent, regime-labeled, multi-TF, multi-symbol candle
dataset so the Phase-V validation harness has real multi-regime weather. Sources:
OKX public REST (primary, deep, free, no auth) + Birdeye on-chain (key-gated).

Subcommands:
  build    deep backfill (~6-12mo) per (symbol, tf); writes tape + manifest
  forward  append latest CLOSED bars for all (symbol, tf); idempotent
  summary  print symbols x TFs x date-range x bar-counts x regime distribution
  regimes  (re)label all tapes -> window index + regime distribution

OKX is polite: page_limit<=300, small sleeps between pages, capped calls/(sym,tf).
Birdeye is skipped + flagged when BIRDEYE_API_KEY is absent (never fabricates).

Usage:
  python3 scripts/calibration/tape/build_tape.py build  [--symbols PYTH,WIF] [--tfs 5m,1H] [--lookback-days 270]
  python3 scripts/calibration/tape/build_tape.py forward [--symbols ...] [--tfs ...]
  python3 scripts/calibration/tape/build_tape.py summary
  python3 scripts/calibration/tape/build_tape.py regimes [--write]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
import time

# package-relative imports work whether run as module or script
try:
    from . import birdeye_source as be
    from . import config as cfg
    from . import okx_source as okx
    from . import regime_label as rl
    from . import storage
except ImportError:  # run as a plain script
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import birdeye_source as be  # type: ignore[no-redef]
    import config as cfg  # type: ignore[no-redef]
    import okx_source as okx  # type: ignore[no-redef]
    import regime_label as rl  # type: ignore[no-redef]
    import storage  # type: ignore[no-redef]


def _log(msg: str) -> None:
    print(msg, file=sys.stderr)


def _iso(ts_ms: float | None) -> str:
    if ts_ms is None:
        return "—"
    return dt.datetime.utcfromtimestamp(ts_ms / 1000.0).strftime("%Y-%m-%d %H:%M")


def _parse_csv(val: str | None, default: list[str]) -> list[str]:
    if not val:
        return default
    return [x.strip() for x in val.split(",") if x.strip()]


# ── build (deep backfill) ───────────────────────────────────────────
def cmd_build(args: argparse.Namespace) -> None:
    symbols = _parse_csv(args.symbols, cfg.SYMBOLS)
    tfs = _parse_csv(args.tfs, cfg.TIMEFRAMES)
    lookback_ms = args.lookback_days * cfg.DAY_MS
    lookback_s = args.lookback_days * cfg.DAY_S

    entries: dict[str, dict] = {}
    birdeye_flagged: list[str] = []
    okx_missing: list[str] = []

    for sym in symbols:
        for tf in tfs:
            _log(f"[build] {sym} {tf} (lookback {args.lookback_days}d)...")
            candles, missing = okx.fetch_history(
                sym,
                tf,
                lookback_ms=lookback_ms,
                max_calls=args.max_calls,
                sleep_s=args.sleep,
                log=_log,
            )
            source = "okx"
            if missing:
                okx_missing.append(f"{sym}-{tf}")
                # try Birdeye on-chain for OKX-unlisted names (e.g. POPCAT)
                mint = cfg.MINTS.get(sym, "")
                if not mint:
                    _log(f"  {sym}-{tf}: not on OKX and no mint -> SKIP")
                    continue
                if not be.api_key_present():
                    birdeye_flagged.append(f"{sym}-{tf}")
                    _log(f"  {sym}-{tf}: OKX-unlisted; BIRDEYE_API_KEY absent -> SKIP (flagged)")
                    continue
                try:
                    candles = be.collect_history(
                        mint, tf, lookback_s=lookback_s, sleep_s=args.sleep, log=_log
                    )
                    source = "birdeye"
                except be.BirdeyeKeyMissing:
                    birdeye_flagged.append(f"{sym}-{tf}")
                    continue
            if not candles:
                _log(f"  {sym}-{tf}: no data -> SKIP")
                continue
            n = storage.write_tape(sym, tf, candles)
            meta = storage.tape_meta(storage.load_tape(sym, tf))
            entries[f"{sym}_{tf}"] = {"symbol": sym, "tf": tf, "source": source, **meta}
            _log(
                f"  {sym}-{tf}: wrote {n} bars [{_iso(meta['ts_start'])} .. {_iso(meta['ts_end'])}]"
            )
            time.sleep(args.sleep)

    # merge with any existing index entries not rebuilt this run
    idx = storage.load_index()
    merged = {**idx.get("tapes", {}), **entries}
    storage.write_index(merged, dt.date.today().isoformat())
    _log(f"\n[build] wrote {len(entries)} tapes; index has {len(merged)} total.")
    if okx_missing:
        _log(f"[build] OKX-unlisted (routed to Birdeye): {okx_missing}")
    if birdeye_flagged:
        _log(
            "[build] FLAG: BIRDEYE_API_KEY needed for on-chain coverage of "
            f"{sorted(set(s.split('-')[0] for s in birdeye_flagged))} "
            "(set BIRDEYE_API_KEY and re-run `build` to fill these)."
        )


# ── forward (append latest closed bars) ─────────────────────────────
def cmd_forward(args: argparse.Namespace) -> None:
    symbols = _parse_csv(args.symbols, cfg.SYMBOLS)
    tfs = _parse_csv(args.tfs, cfg.TIMEFRAMES)
    total_added = 0
    for sym in symbols:
        for tf in tfs:
            # one shallow page is enough to catch up recent closed bars; the
            # lookback only needs to cover the gap since last forward run.
            candles, missing = okx.fetch_history(
                sym, tf, lookback_ms=okx.TF_MS[tf] * 300, max_calls=2, sleep_s=args.sleep, log=_log
            )
            if missing or not candles:
                continue
            added, total = storage.append_tape(sym, tf, candles)
            total_added += added
            if added:
                _log(f"[forward] {sym}-{tf}: +{added} bars (total {total})")
            time.sleep(args.sleep)
    # refresh manifest meta
    _refresh_index()
    _log(f"\n[forward] appended {total_added} new bars across all tapes.")


def _refresh_index() -> None:
    entries: dict[str, dict] = {}
    idx = storage.load_index()
    for sym, tf in storage.list_tapes():
        meta = storage.tape_meta(storage.load_tape(sym, tf))
        prev = idx.get("tapes", {}).get(f"{sym}_{tf}", {})
        entries[f"{sym}_{tf}"] = {
            "symbol": sym,
            "tf": tf,
            "source": prev.get("source", "okx"),
            **meta,
        }
    storage.write_index(entries, dt.date.today().isoformat())


# ── regimes (label + distribution) ──────────────────────────────────
def _all_windows() -> list[dict]:
    windows: list[dict] = []
    for sym, tf in storage.list_tapes():
        candles = storage.load_tape(sym, tf)
        if len(candles) < rl.base.WARMUP + rl.window_len(tf):
            continue
        windows.extend(rl.label_tape(sym, tf, candles))
    return windows


def cmd_regimes(args: argparse.Namespace) -> None:
    windows = _all_windows()
    dist = rl.distribution(windows)
    by_tf = rl.distribution_by_tf(windows)
    print("\n=== REGIME DISTRIBUTION (window index) ===")
    print(f"  total labeled windows: {len(windows)}")
    for bucket in rl.REGIME_BUCKETS:
        print(f"    {bucket:>13}: {dist.get(bucket, 0)}")
    print("\n  by timeframe:")
    for tf in cfg.TIMEFRAMES:
        if tf in by_tf:
            row = "  ".join(f"{b}={by_tf[tf].get(b, 0)}" for b in rl.REGIME_BUCKETS)
            print(f"    {tf:>4}: {row}")
    ok = rl.has_multiregime_coverage(windows)
    print(f"\n  multi-regime coverage (>=5 windows/bucket): {'YES' if ok else 'NO'}")
    if args.write:
        storage._atomic_write(
            storage.os.path.join(storage.TAPE_DIR, "regime_windows.json"),
            {"generated": dt.date.today().isoformat(), "distribution": dist, "windows": windows},
        )
        _log(f"[regimes] wrote regime_windows.json ({len(windows)} windows)")


# ── summary ─────────────────────────────────────────────────────────
def cmd_summary(_args: argparse.Namespace) -> None:
    idx = storage.load_index()
    tapes = idx.get("tapes", {})
    print("\n=== TAPE COVERAGE SUMMARY ===")
    print(f"  index generated: {idx.get('generated')}")
    print(f"  {'sym_tf':>12} {'src':>8} {'bars':>7}  {'start':>16}  {'end':>16}")
    print("  " + "-" * 64)
    by_sym: dict[str, list[str]] = {}
    for key in sorted(tapes):
        t = tapes[key]
        by_sym.setdefault(t["symbol"], []).append(t["tf"])
        print(
            f"  {key:>12} {t.get('source', '?'):>8} {t.get('bars', 0):>7}  "
            f"{_iso(t.get('ts_start')):>16}  {_iso(t.get('ts_end')):>16}"
        )
    print("\n  symbols x TFs:")
    for sym in cfg.SYMBOLS:
        print(f"    {sym:>7}: {sorted(by_sym.get(sym, []))}")
    # regime distribution from current tapes
    windows = _all_windows()
    if windows:
        dist = rl.distribution(windows)
        print(
            f"\n  regime windows: total={len(windows)} "
            + " ".join(f"{b}={dist.get(b, 0)}" for b in rl.REGIME_BUCKETS)
        )


def main() -> None:
    ap = argparse.ArgumentParser(description="Historical-tape collector (s46)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="deep backfill")
    b.add_argument("--symbols", default=None)
    b.add_argument("--tfs", default=None)
    b.add_argument("--lookback-days", type=int, default=cfg.DEFAULT_LOOKBACK_DAYS)
    b.add_argument("--max-calls", type=int, default=80, help="page cap per (sym,tf)")
    b.add_argument("--sleep", type=float, default=0.15, help="seconds between calls")
    b.set_defaults(func=cmd_build)

    f = sub.add_parser("forward", help="append latest closed bars")
    f.add_argument("--symbols", default=None)
    f.add_argument("--tfs", default=None)
    f.add_argument("--sleep", type=float, default=0.15)
    f.set_defaults(func=cmd_forward)

    r = sub.add_parser("regimes", help="label + distribution")
    r.add_argument("--write", action="store_true", help="write regime_windows.json")
    r.set_defaults(func=cmd_regimes)

    s = sub.add_parser("summary", help="coverage summary")
    s.set_defaults(func=cmd_summary)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
