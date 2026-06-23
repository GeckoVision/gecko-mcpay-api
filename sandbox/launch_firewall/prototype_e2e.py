"""Firewall E2E prototype slice — every box in firewall-e2e.md §2 lights up once.

The thinnest vertical that runs the WHOLE decision-firewall chain on a surfpool
fork, $0, ``source="fork"`` on every row:

    fork launch → real signals → verdict → served via /safety
        → consumed by a SendAI-style pretrade_check → firewall_verdicts ledger row
        (+ optional devnet receipt)

ORCHESTRATION CHOICE — in-process ``serve_safety`` (documented):
  We construct ONE ``LaunchMonitor`` + ``HotpathCache`` and hand it to BOTH
    (a) a ``LaunchRunner`` pointed at the surfpool fork ws/RPC (the SHIPPED ingest
        wire, exactly as ``fork_adapter`` drives it), AND
    (b) the ``/safety`` serve path, by calling
        ``gecko_api.safety_fast.serve_safety(mint, shared_store, shared_monitor)``
        IN-PROCESS against that same shared store.
  So a ``/safety {mint}`` read returns the LIVE fork verdict with wash+snipe
  populated (the warm read), not the static cold path.

  Why in-process over real HTTP+uvicorn: ``gecko_api.main`` constructs its OWN
  ``app.state.safety_store``/``safety_monitor`` at *module import* (main.py:807-808)
  and its lifespan builds a live runner; pointing a uvicorn app at OUR shared
  monitor would mean monkeypatching module-level app state and dragging the x402
  middleware + the MCP singleton into the slice. The build spec explicitly allows
  the in-process call ("calling serve_safety(...) in-process against the shared
  store is acceptable"). It exercises the IDENTICAL serve code path
  (``safety_fast.serve_safety`` — same warm-read + freshness logic), so the only
  thing skipped is the socket. Faithful where it matters.

The pretrade gate is the SendAI-shaped consumer (``gecko_core.firewall``); the
ledger row is the moat's first row (``gecko_core.firewall.ledger``); the optional
devnet receipt gives ``anchor_receipt`` its first caller.

ETHICS / SCOPE: surfpool mainnet-FORK / localnet ONLY (127.0.0.1). NEVER mainnet,
never real money. ``source="fork"`` on every row. Reuses the SHIPPED engine + the
SHIPPED fork wire as-is — this script is glue + assertions only.

Run (after the fork is up via run_fork_demo.sh and a pool exists):

    # ATTACK leg (spawns fork_attack.py --scenario attack against the live pool)
    uv run python sandbox/launch_firewall/prototype_e2e.py --scenario attack --seconds 70

    # ORGANIC leg (reset the pool first: fork_pool.py)
    uv run python sandbox/launch_firewall/prototype_e2e.py --scenario organic --seconds 70

``--no-spawn`` drives the gate against whatever the runner already saw (you run
fork_attack.py yourself). ``--receipt`` additionally anchors a devnet receipt for
the verdict (needs GECKO_RECEIPT_ENABLED + a devnet RPC + an oracle keypair).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# sandbox siblings (the SHIPPED fork wire)
from fork_adapter import QUOTE_USD_PER_UNIT, DrainWatcher, _assert_local, _ws_url_from_rpc
from fork_pool import POOL_DESCRIPTOR_PATH, ForkPool

# the SHIPPED engine (reused as-is)
from gecko_core.firewall.ledger import read_firewall_verdicts, record_firewall_verdict
from gecko_core.firewall.pretrade import FirewallGate
from gecko_core.trade_agent.hotpath.cache import HotpathCache
from gecko_core.trade_agent.hotpath.helius import HeliusWebSocketClient
from gecko_core.trade_agent.hotpath.helius_rpc import make_tx_fetcher
from gecko_core.trade_agent.hotpath.launch_monitor import LaunchMonitor
from gecko_core.trade_agent.hotpath.launch_runner import LaunchRunner

HERE = Path(__file__).resolve().parent
RESULT_PATH = Path("/tmp/gecko-firewall-e2e-result.json")


def _load_pool() -> ForkPool:
    if not POOL_DESCRIPTOR_PATH.exists():
        raise SystemExit(
            f"no pool descriptor at {POOL_DESCRIPTOR_PATH} — run fork_pool.py first "
            "(see run_fork_demo.sh DEMO FLOW)."
        )
    return ForkPool(**json.loads(POOL_DESCRIPTOR_PATH.read_text()))


def _spawn_attack(scenario: str) -> subprocess.Popen[bytes]:
    """Run fork_attack.py --scenario <scenario> as a child against the live pool.

    Inherits the env (so HELIUS/.env-sourced vars propagate). The attack signs
    REAL txs on the LOCAL fork — fork_attack hard-guards 127.0.0.1 itself.
    """
    return subprocess.Popen(
        [sys.executable, str(HERE / "fork_attack.py"), "--scenario", scenario],
        cwd=str(HERE),
    )


async def _maybe_anchor_receipt(verdict_envelope: dict[str, Any]) -> Any | None:
    """Optionally anchor a devnet receipt; return the ReceiptAnchor or None.

    Gated behind GECKO_RECEIPT_ENABLED (config raises ReceiptDisabled if off). We
    surface any error verbatim and return None so the slice still completes — the
    receipt is OPTIONAL by design.
    """
    from gecko_core.payments.receipt.anchor import anchor_receipt
    from gecko_core.payments.receipt.config import ReceiptDisabled

    try:
        # anchor_receipt is sync (solana-py Client); run it off the loop.
        anchor = await asyncio.to_thread(anchor_receipt, verdict_envelope)
    except ReceiptDisabled:
        print("    receipt: SKIPPED (GECKO_RECEIPT_ENABLED off — optional)")
        return None
    except Exception as exc:  # surface verbatim — never fake a pass
        print(f"    receipt: FAILED (surfaced verbatim) -> {type(exc).__name__}: {exc}")
        return None
    print(f"    receipt: anchored sig={anchor.receipt_sig} memo={anchor.memo}")
    return anchor


async def _verify_receipt(verdict_envelope: dict[str, Any], anchor: Any) -> bool:
    """Verify a previously anchored receipt via the SHIPPED verify path.

    ``anchor_receipt`` returns after ``confirmTransaction`` (signature-status
    based), but ``getTransaction`` (ledger-store based) can briefly lag behind
    on devnet — so a verify fired the instant the anchor returns can hit
    "transaction not found" purely from propagation, not a real mismatch. We
    retry the SHIPPED verify on that one transient reason with bounded backoff;
    every other failure reason (memo mismatch, wrong signer) is surfaced
    immediately and verbatim — we never paper over a real verification failure.
    """
    from gecko_core.payments.receipt.config import load_config
    from gecko_core.payments.receipt.verify import default_rpc_fetch, verify_receipt

    try:
        cfg = load_config()
        fetch = default_rpc_fetch(cfg.rpc_url)
        result = None
        for attempt in range(10):
            result = await asyncio.to_thread(
                verify_receipt,
                verdict_envelope,
                receipt_sig=anchor.receipt_sig,
                oracle_pubkey=anchor.oracle_pubkey,
                fetch=fetch,
            )
            if result.verified or result.reason != "transaction not found":
                break
            if attempt == 0:
                print("    receipt verify: tx not yet in ledger store; polling getTransaction…")
            await asyncio.sleep(2.0)
        assert result is not None
        ok = bool(result.verified)
        suffix = "" if ok else f" ({result.reason})"
        print(f"    receipt verify: {'OK' if ok else 'FAIL'}{suffix}")
        return ok
    except Exception as exc:  # surface verbatim
        print(f"    receipt verify: FAILED (surfaced verbatim) -> {type(exc).__name__}: {exc}")
        return False


async def run(scenario: str, seconds: float, *, spawn: bool, receipt: bool) -> int:
    pool = _load_pool()
    rpc = pool.rpc
    _assert_local(rpc)
    ws_url = _ws_url_from_rpc(rpc)

    # -- Step 1: ONE monitor + store, shared between the runner AND /safety ----- #
    store = HotpathCache()
    monitor = LaunchMonitor(store)

    ws_client = HeliusWebSocketClient(api_key="fork", base_ws=ws_url, http_base=rpc)
    fetcher = make_tx_fetcher("fork", http_base=rpc)
    runner = LaunchRunner(monitor, ws_client, tx_fetcher=fetcher, tx_mode="logs")

    # The in-process /safety reader — same serve code path the HTTP endpoint uses,
    # bound to OUR shared store + monitor (so it returns the live fork verdict).
    from gecko_api.safety_fast import serve_safety

    async def safety_reader(mint: str) -> dict[str, Any]:
        return await serve_safety(mint, store, monitor)

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
    print(f"\n  [step1] shared monitor live on {ws_url}; watching pool {pool.pool_addr[:8]}…")
    print(f"          scenario={scenario} window={seconds}s mint={pool.mint}")

    # -- drive the attack/organic flow on the fork (real signed txs) ----------- #
    child: subprocess.Popen[bytes] | None = None
    if spawn:
        print(f"  [drive] spawning fork_attack.py --scenario {scenario} …")
        child = _spawn_attack(scenario)

    # -- watch: recompute on cadence so the shared store warms (the ingest box) - #
    deadline = time.time() + seconds
    last = ""
    try:
        while time.time() < deadline:
            await asyncio.sleep(2.0)
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
                line = f"gate={pc.gate} snipe={pc.snipe.label if pc.snipe else '—'} fired={fired}"
                if line != last:
                    print(f"          {time.strftime('%H:%M:%S')} {line}")
                    last = line
            # once the child has finished AND we have a decisive read, we can stop early
            if child is not None and child.poll() is not None and pc is not None:
                if scenario == "attack" and pc.gate == "block":
                    break
                if (
                    scenario == "organic"
                    and pc.gate in ("ok", "unknown")
                    and time.time() > (deadline - seconds + 12)
                ):
                    break
    finally:
        if child is not None and child.poll() is None:
            child.wait(timeout=30)
        # one last recompute so the warm read is current before we consult /safety
        await monitor.recompute(pool.mint, time.time())

    # -- Step 2+3: the SendAI-style gate consults /safety AND records the row --- #
    print("\n  [step2/3] pretrade gate consults /safety (in-proc) + records ledger row")
    gate = FirewallGate(reader=safety_reader, record=record_firewall_verdict, source="fork")
    result = await gate.submit(mint=pool.mint, side="buy", size_usd=100.0)
    decision = result["decision"]
    sink = result["ledger_sink"]
    print(
        f"          proceed={decision['proceed']} gate={decision['gate']} "
        f"flagged={decision['flagged']}"
    )
    print(f"          reasons={decision['reasons']}")
    print(f"          ledger_sink={sink}")

    # -- optional devnet receipt (gives anchor_receipt its first caller) -------- #
    receipt_sig: str | None = None
    if receipt:
        from gecko_core.firewall.ledger import envelope_for_verdict

        safety = await safety_reader(pool.mint)
        snipe = safety.get("snipe") or {}
        wash = safety.get("wash_risk") or {}
        envelope = envelope_for_verdict(
            mint=pool.mint,
            gate=decision["gate"],
            snipe_label=snipe.get("label"),
            snipe_fired=list(snipe.get("fired_signals") or []),
            wash_label=wash.get("label"),
            wash_fired=list(wash.get("fired_signals") or []),
        )
        anchor = await _maybe_anchor_receipt(envelope)
        if anchor is not None:
            receipt_sig = anchor.receipt_sig
            # record a second row carrying the anchor (the verify-able one)
            await record_firewall_verdict(
                mint=pool.mint,
                gate=decision["gate"],
                snipe_label=snipe.get("label"),
                snipe_fired=list(snipe.get("fired_signals") or []),
                wash_label=wash.get("label"),
                wash_fired=list(wash.get("fired_signals") or []),
                source="fork",
                receipt_sig=receipt_sig,
            )
            await _verify_receipt(envelope, anchor)

    await runner.stop()
    await ws_client.stop()

    # -- Step 4: assert the chain (read the row back) -------------------------- #
    rows = await read_firewall_verdicts(pool.mint)
    print(f"\n  [step4] read back {len(rows)} ledger row(s) for mint={pool.mint[:8]}…")
    ok, checks = _assert_chain(scenario, decision, rows)
    _print_result(scenario, decision, rows, sink, receipt_sig, ok, checks)

    RESULT_PATH.write_text(
        json.dumps(
            {
                "scenario": scenario,
                "decision": decision,
                "ledger_sink": sink,
                "receipt_sig": receipt_sig,
                "rows": [r.model_dump(mode="json") for r in rows],
                "checks": checks,
                "pass": ok,
            },
            indent=2,
        )
    )
    return 0 if ok else 1


def _assert_chain(
    scenario: str, decision: dict[str, Any], rows: list[Any]
) -> tuple[bool, list[tuple[str, bool]]]:
    """The chain assertion (build spec Step 4)."""
    latest = rows[-1] if rows else None
    checks: list[tuple[str, bool]]
    if scenario == "attack":
        checks = [
            ("attack: proceed == False", decision["proceed"] is False),
            ("attack: gate == 'block'", decision["gate"] == "block"),
            ("attack: a row was written", latest is not None),
            ("attack: row gate == 'block'", latest is not None and latest.gate == "block"),
            ("row source == 'fork'", latest is not None and latest.source == "fork"),
            (
                "row has envelope_hash",
                latest is not None and len(latest.envelope_hash) == 64,
            ),
        ]
    else:  # organic
        checks = [
            ("organic: proceed == True", decision["proceed"] is True),
            (
                "organic: gate in {ok, unknown}",
                decision["gate"] in ("ok", "unknown"),
            ),
            ("organic: a row was written", latest is not None),
            (
                "organic: row gate in {ok, unknown}",
                latest is not None and latest.gate in ("ok", "unknown"),
            ),
            ("row source == 'fork'", latest is not None and latest.source == "fork"),
        ]
    return all(p for _, p in checks), checks


def _print_result(
    scenario: str,
    decision: dict[str, Any],
    rows: list[Any],
    sink: str | None,
    receipt_sig: str | None,
    ok: bool,
    checks: list[tuple[str, bool]],
) -> None:
    print("\n  " + "=" * 64)
    print(f"  FIREWALL E2E PROTOTYPE — scenario={scenario}")
    print("  " + "=" * 64)
    for name, passed in checks:
        print(f"    [{'PASS' if passed else 'FAIL'}] {name}")
    if rows:
        r = rows[-1]
        print(
            f"\n    ledger row: id={r.verdict_id} gate={r.gate} "
            f"snipe={r.snipe_label} wash={r.wash_label}"
        )
        print(f"               envelope_hash={r.envelope_hash}")
        print(f"               source={r.source} receipt_sig={r.receipt_sig}")
    print(f"\n    sink={sink}")
    if receipt_sig:
        print(f"    receipt_sig={receipt_sig}")
    print("  " + "=" * 64)
    print(
        f"  {'PASS' if ok else 'FAIL'}: the chain "
        f"{'lit up end-to-end' if ok else 'did NOT match expectations'}\n"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Firewall E2E prototype slice (fork-only)")
    ap.add_argument("--scenario", default="attack", choices=["attack", "organic"])
    ap.add_argument("--seconds", type=float, default=70.0, help="watch window")
    ap.add_argument(
        "--no-spawn",
        action="store_true",
        help="do NOT spawn fork_attack.py (you run it yourself)",
    )
    ap.add_argument(
        "--receipt",
        action="store_true",
        help="also anchor a devnet receipt (needs GECKO_RECEIPT_ENABLED)",
    )
    args = ap.parse_args()
    try:
        return asyncio.run(
            run(args.scenario, args.seconds, spawn=not args.no_spawn, receipt=args.receipt)
        )
    except KeyboardInterrupt:
        print("\n  interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
