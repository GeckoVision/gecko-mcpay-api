"""The ONE real live wire: fork websocket → ParsedSwap/SwapEvent → LaunchMonitor.

This is the only piece of the demo that touches a live (local) chain stream. It
reuses the SHIPPED ingest stack end-to-end rather than reinventing it:

    surfpool ws (127.0.0.1:8900)
        │
        ├─ accountSubscribe(base_vault), accountSubscribe(quote_vault)
        │     └─ swap_parser.parse_vault_balance → PoolReserveTracker.observe
        │           └─ LaunchMonitor.ingest_swap   (reserve deltas → wash F1/F5, lp_drain)
        │
        └─ logsSubscribe(base_vault) → getTransaction(sig) (127.0.0.1:8899)
              └─ tx_parser.parse_swap_tx → LaunchMonitor.ingest_parsed_swap
                    (signer + slot + Jito tip + ALT + program ids → snipe gate)

All of that is exactly ``hotpath.launch_runner.LaunchRunner.track_pool``. We point
its ``HeliusWebSocketClient`` at the fork ws and its ``getTransaction`` fetcher at
the fork RPC — the same code that will run against live Helius mainnet, pointed at
a local fork instead. That is the point: the live wire is the shipped wire.

What this module ADDS on top of LaunchRunner:

* a drain detector — ``lp_drained`` is a flag on ``TokenState`` that no signal
  auto-computes from the reserve series (by design; it's an upstream input). We
  watch the base-vault reserve and set ``state.lp_drained`` once it rises back
  toward / above the pre-inflate level after a run-up (inflate-then-drain). This
  lights the snipe gate's ``lp_drain`` signal faithfully on the fork.
* a verdict reporter — recompute on a cadence and print the live gate + fired
  signals so the demo shows the firewall reacting in real time.

ETHICS / SCOPE: local fork only (127.0.0.1). The ws/RPC URLs are asserted local.

Run (with surfpool up + a pool from fork_pool.py):

    uv run python sandbox/launch_firewall/fork_adapter.py --seconds 90
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from gecko_core.trade_agent.hotpath.helius import HeliusWebSocketClient
from gecko_core.trade_agent.hotpath.helius_rpc import make_tx_fetcher
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.launch_runner import LaunchRunner
from gecko_core.trade_agent.hotpath.precomputed import SafetyStore

try:  # in-process cache (the shipped Phase-1 SafetyStore)
    from gecko_core.trade_agent.hotpath.cache import HotpathCache
except Exception:  # pragma: no cover - cache always present in repo
    HotpathCache = None  # type: ignore[assignment, misc]

from fork_pool import POOL_DESCRIPTOR_PATH, ForkPool

# A fork has no real wSOL price; the snipe/wash signals here are unit-agnostic
# (co-buy, reserve moves, one-sidedness), so quote-USD=1.0 is fine for the demo.
QUOTE_USD_PER_UNIT = 1.0


def _assert_local(rpc: str) -> None:
    if not (rpc.startswith("http://127.0.0.1") or rpc.startswith("http://localhost")):
        raise SystemExit(f"REFUSING non-local RPC {rpc!r} — fork/localnet ONLY.")


def _ws_url_from_rpc(rpc: str) -> str:
    """surfpool RPC :8899 → ws :8900 (its default ws port)."""
    return rpc.replace("http://", "ws://").replace(":8899", ":8900")


class DrainWatcher:
    """Sets ``TokenState.lp_drained`` once reserves recover after a run-up.

    Inflate-then-drain footprint: base reserve falls as snipers buy (price up),
    then the snipers dump and the base reserve climbs back toward / past where it
    started. We flag the drain on that recovery after a meaningful dip — exactly
    the ``lp_drain`` snipe-signal precondition (reserves dropped + buyers exited).
    """

    __slots__ = ("_min_base", "_start_base", "fired")

    def __init__(self) -> None:
        self._start_base: float | None = None
        self._min_base: float | None = None
        self.fired = False

    def observe(self, base_reserve: float) -> bool:
        if self._start_base is None:
            self._start_base = base_reserve
            self._min_base = base_reserve
            return False
        self._min_base = min(self._min_base or base_reserve, base_reserve)
        if self.fired:
            return True
        dipped = self._min_base < 0.7 * self._start_base  # ≥30% of base bought out
        recovered = base_reserve >= 0.95 * self._start_base  # then dumped back
        if dipped and recovered:
            self.fired = True
        return self.fired


async def run_adapter(seconds: float, *, rpc: str | None = None) -> int:
    if not POOL_DESCRIPTOR_PATH.exists():
        print(f"  no pool descriptor at {POOL_DESCRIPTOR_PATH} — run fork_pool.py", file=sys.stderr)
        return 1
    pool = ForkPool(**json.loads(POOL_DESCRIPTOR_PATH.read_text()))
    rpc = rpc or pool.rpc
    _assert_local(rpc)
    ws_url = _ws_url_from_rpc(rpc)

    if HotpathCache is None:
        print("  HotpathCache unavailable", file=sys.stderr)
        return 1
    store: SafetyStore = HotpathCache()
    monitor = LaunchMonitor(store)

    # Point the SHIPPED clients at the fork. The api_key is a non-empty dummy
    # (the URL override carries no key — surfpool ignores the query string).
    ws_client = HeliusWebSocketClient(api_key="fork", base_ws=ws_url, http_base=rpc)
    fetcher = make_tx_fetcher("fork", http_base=rpc)
    runner = LaunchRunner(monitor, ws_client, tx_fetcher=fetcher, tx_mode="logs")

    await ws_client.start()
    await runner.track_pool(
        mint=pool.mint,
        pool_addr=pool.pool_addr,
        base_vault=pool.base_vault,
        quote_vault=pool.quote_vault,
        quote_usd_per_unit=QUOTE_USD_PER_UNIT,
        pool_created_ts=pool.created_unix,
    )
    await runner.start()

    drain = DrainWatcher()
    state = monitor.track(pool.mint)
    print(f"\n  adapter live on {ws_url} — watching pool {pool.pool_addr[:8]}…\n")
    deadline = time.time() + seconds
    last_print = ""
    try:
        while time.time() < deadline:
            await asyncio.sleep(2.0)
            # drain detection off the latest base-vault reserve the tracker holds
            tp = runner._pools.get(pool.pool_addr)
            if (
                tp is not None
                and tp.tracker._last_base is not None
                and drain.observe(tp.tracker._last_base)
            ):
                state.lp_drained = True
            pc = await monitor.recompute(pool.mint, time.time())
            if pc is not None:
                fired = (pc.snipe.fired_signals if pc.snipe else []) + (
                    pc.wash.fired_signals if pc.wash else []
                )
                line = f"gate={pc.gate:<8} snipe={pc.snipe.label if pc.snipe else '—':<14} fired={fired}"
                if line != last_print:
                    print(f"  {time.strftime('%H:%M:%S')}  {line}")
                    last_print = line
    finally:
        await runner.stop()
        await ws_client.stop()

    pc = await monitor.recompute(pool.mint, time.time())
    out = {
        "mint": pool.mint,
        "gate": pc.gate if pc else None,
        "snipe_label": pc.snipe.label if (pc and pc.snipe) else None,
        "snipe_fired": pc.snipe.fired_signals if (pc and pc.snipe) else [],
        "wash_label": pc.wash.label if (pc and pc.wash) else None,
        "wash_fired": pc.wash.fired_signals if (pc and pc.wash) else [],
        "lp_drained": state.lp_drained,
    }
    Path("/tmp/gecko-lf-fork-verdict.json").write_text(json.dumps(out, indent=2))
    print(f"\n  final verdict -> /tmp/gecko-lf-fork-verdict.json\n  {out}\n")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Launch-Firewall fork adapter (live wire)")
    ap.add_argument("--seconds", type=float, default=90.0, help="how long to watch")
    ap.add_argument("--rpc", default=None, help="override fork RPC (127.0.0.1 only)")
    args = ap.parse_args()
    return asyncio.run(run_adapter(args.seconds, rpc=args.rpc))


if __name__ == "__main__":
    raise SystemExit(main())
