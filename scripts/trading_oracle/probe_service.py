"""Standalone per-service x402 probe tool.

Why this exists
---------------
Running the full trading-oracle ingest (embed + Mongo write) just to
discover an endpoint URL is wrong wastes minutes per iteration. This
script lets you inspect any Bazaar/paysh service in isolation:

    1. ``--inspect``  — print listing fields, no network.
    2. ``--dry``      — issue a plain GET and capture the 402 challenge
                        (or 200 if the endpoint is free). Cached to disk
                        for an hour by default.
    3. ``--pay``      — sign + retry via the same ``_build_paid_requester``
                        the live ingest uses. NEVER cached.

Hard scope (per ticket):

* Imports from ``run.py`` only — no re-implementing signing or x402
  plumbing here.
* Does not modify any other file.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import time
from pathlib import Path
from typing import Any

import click
import httpx
from rich.console import Console
from rich.table import Table

# ---------------------------------------------------------------------------
# Module loading. ``scripts/`` is not on sys.path as a package, so import
# ``run.py`` the same way ``tests/scripts/dex/test_seed_corpus.py`` does.
# ---------------------------------------------------------------------------

_RUN_PATH = Path(__file__).resolve().parent / "run.py"
_spec = importlib.util.spec_from_file_location("trading_oracle_run", _RUN_PATH)
assert _spec is not None and _spec.loader is not None
_run_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("trading_oracle_run", _run_mod)
_spec.loader.exec_module(_run_mod)

_load_listings_from_file = _run_mod._load_listings_from_file

# Cache directory — sibling to this script.
CACHE_DIR = Path(__file__).resolve().parent / "probes"


# ---------------------------------------------------------------------------
# Helpers (pure).
# ---------------------------------------------------------------------------


def find_listing(listings: list[dict[str, Any]], service_id: str) -> dict[str, Any] | None:
    """Return the first listing whose ``fqn`` matches ``service_id`` exactly,
    falling back to a case-insensitive name match."""
    for ent in listings:
        if ent.get("fqn") == service_id:
            return ent
    lowered = service_id.lower()
    for ent in listings:
        if str(ent.get("fqn", "")).lower() == lowered:
            return ent
        if str(ent.get("name", "")).lower() == lowered:
            return ent
    return None


def cache_path_for(service_id: str, endpoint_idx: int) -> Path:
    """Cache file for a (service_id, endpoint_idx) pair.

    Both components are in the filename so a service with multiple
    probe-worthy endpoints does not collide.
    """
    safe = service_id.replace("/", "__").replace(" ", "_")
    return CACHE_DIR / f"{safe}__{endpoint_idx}.json"


def cache_is_fresh(path: Path, ttl_seconds: int) -> bool:
    if not path.exists():
        return False
    age = time.time() - path.stat().st_mtime
    return age < ttl_seconds


def render_summary(
    *,
    console: Console,
    service_id: str,
    endpoint_url: str,
    method: str,
    status: int | None,
    accepts: list[dict[str, Any]],
    note: str = "",
) -> None:
    table = Table(title=f"probe: {service_id}", show_lines=False)
    table.add_column("field", style="bold")
    table.add_column("value")
    table.add_row("service_id", service_id)
    table.add_row("endpoint_url", endpoint_url)
    table.add_row("method", method)
    table.add_row("status", str(status) if status is not None else "-")
    table.add_row("accepts.count", str(len(accepts)))
    if accepts:
        first = accepts[0]
        atomic = str(first.get("maxAmountRequired") or first.get("amount") or "0")
        try:
            usd = f"{int(atomic) / 1_000_000:.6f}"
        except (TypeError, ValueError):
            usd = "?"
        table.add_row("accepts[0].maxAmount", f"{atomic} ({usd} USDC)")
        table.add_row("accepts[0].asset", str(first.get("asset", "")))
        table.add_row("accepts[0].network", str(first.get("network", "")))
        table.add_row("accepts[0].payTo", str(first.get("payTo", "")))
    if note:
        table.add_row("note", note)
    console.print(table)


# ---------------------------------------------------------------------------
# Network legs.
# ---------------------------------------------------------------------------


async def dry_probe(
    *, url: str, method: str, timeout_seconds: float
) -> tuple[int, dict[str, str], list[dict[str, Any]], str]:
    """Issue an unsigned request and capture the 402 (or 200) response.

    Returns ``(status, headers, accepts, body_text)``. ``accepts`` is empty
    unless the response is a JSON 402 challenge.
    """
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        if method.upper() == "POST":
            resp = await client.post(url)
        else:
            resp = await client.get(url)
    accepts: list[dict[str, Any]] = []
    if resp.status_code == 402:
        try:
            challenge = resp.json()
            raw_accepts = challenge.get("accepts") or []
            if isinstance(raw_accepts, list):
                accepts = [a for a in raw_accepts if isinstance(a, dict)]
        except Exception:
            accepts = []
    return resp.status_code, dict(resp.headers), accepts, resp.text


async def paid_probe(*, url: str, max_cost_usd: float, timeout_seconds: float) -> Any:
    """Run the full sign + retry dance via ``_build_paid_requester`` (env-driven)."""
    requester = _run_mod._build_paid_requester()
    return await requester.request(
        url=url,
        query="",
        max_cost_usd=max_cost_usd,
        timeout_seconds=timeout_seconds,
    )


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------


@click.command()
@click.argument("service_id")
@click.option(
    "--listings-json",
    required=True,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Path to a planner-shaped listings JSON fixture.",
)
@click.option("--inspect", is_flag=True, help="Print listing fields only; no network.")
@click.option("--dry", is_flag=True, help="Probe for 402 challenge; never spends.")
@click.option("--pay", is_flag=True, help="Sign + retry. Costs USDC. Requires live env.")
@click.option(
    "--max-cost-usd",
    type=float,
    default=0.01,
    show_default=True,
    help="Cap on advertised price for --pay path.",
)
@click.option(
    "--method",
    type=click.Choice(["GET", "POST"], case_sensitive=False),
    default="GET",
    show_default=True,
)
@click.option("--endpoint-index", type=int, default=0, show_default=True)
@click.option(
    "--cache-ttl-seconds",
    type=int,
    default=3600,
    show_default=True,
    help="Dry-probe cache freshness window. Paid probes are never cached.",
)
@click.option("--no-cache", is_flag=True, help="Bypass the dry-probe cache.")
@click.option("--timeout-seconds", type=float, default=30.0, show_default=True)
def main(
    service_id: str,
    listings_json: Path,
    inspect: bool,
    dry: bool,
    pay: bool,
    max_cost_usd: float,
    method: str,
    endpoint_index: int,
    cache_ttl_seconds: int,
    no_cache: bool,
    timeout_seconds: float,
) -> None:
    """Probe a single Bazaar/paysh service by id (``fqn``).

    Exactly one of --inspect / --dry / --pay must be set.
    """
    chosen = sum([inspect, dry, pay])
    if chosen != 1:
        raise click.UsageError(f"specify exactly one of --inspect, --dry, --pay (got {chosen})")

    console = Console()
    listings = _load_listings_from_file(listings_json)
    listing = find_listing(listings, service_id)
    if listing is None:
        raise click.ClickException(
            f"service_id {service_id!r} not found in {listings_json} "
            f"(searched {len(listings)} listings by fqn + name)"
        )

    # The planner-shaped listing carries one ``service_url``. We surface
    # ``--endpoint-index`` for forward-compat with future multi-endpoint
    # listing shapes; today only index 0 is valid.
    if endpoint_index != 0:
        raise click.ClickException(
            f"--endpoint-index={endpoint_index}: this listing shape only "
            "exposes a single service_url (index 0)."
        )
    endpoint_url = str(listing.get("service_url") or "")
    if not endpoint_url:
        raise click.ClickException(f"listing {service_id!r} has no service_url to probe")

    # --inspect: zero network. Print everything we know about the listing.
    if inspect:
        table = Table(title=f"inspect: {service_id}")
        table.add_column("field", style="bold")
        table.add_column("value")
        for k in ("name", "fqn", "provider_kind", "service_url", "price_usd"):
            table.add_row(k, str(listing.get(k, "")))
        table.add_row("tags", ", ".join(listing.get("tags", []) or []))
        table.add_row("description", str(listing.get("description", ""))[:200])
        table.add_row("endpoints.detected", "1 (single service_url)")
        table.add_row("methods.detected", "GET (default — POST via --method)")
        console.print(table)
        return

    # --dry: capture 402, optionally serve from cache.
    if dry:
        cpath = cache_path_for(service_id, endpoint_index)
        if not no_cache and cache_is_fresh(cpath, cache_ttl_seconds):
            cached = json.loads(cpath.read_text())
            render_summary(
                console=console,
                service_id=service_id,
                endpoint_url=cached.get("endpoint_url", endpoint_url),
                method=cached.get("method", method),
                status=cached.get("status"),
                accepts=cached.get("accepts", []) or [],
                note=f"served from cache: {cpath}",
            )
            return

        status, headers, accepts, _body_text = asyncio.run(
            dry_probe(url=endpoint_url, method=method, timeout_seconds=timeout_seconds)
        )
        render_summary(
            console=console,
            service_id=service_id,
            endpoint_url=endpoint_url,
            method=method,
            status=status,
            accepts=accepts,
            note=("free endpoint (200)" if status == 200 else ""),
        )
        # Persist cache.
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cpath.write_text(
            json.dumps(
                {
                    "service_id": service_id,
                    "endpoint_url": endpoint_url,
                    "method": method,
                    "status": status,
                    "headers": headers,
                    "accepts": accepts,
                    "probed_at": int(time.time()),
                },
                indent=2,
                sort_keys=True,
            )
        )
        console.print(f"[dim]cached to {cpath}[/dim]")
        return

    # --pay: sign + retry. Never cached.
    if pay:
        resp = asyncio.run(
            paid_probe(
                url=endpoint_url,
                max_cost_usd=max_cost_usd,
                timeout_seconds=timeout_seconds,
            )
        )
        render_summary(
            console=console,
            service_id=service_id,
            endpoint_url=endpoint_url,
            method=method,
            status=getattr(resp, "status_code", None),
            accepts=[],
            note=f"paid {getattr(resp, 'cost_usd', 0.0)} USD; "
            f"tx={getattr(resp, 'tx_signature', None)}",
        )
        text = getattr(resp, "response_text", "") or ""
        total = len(text)
        snippet = text[:500]
        console.print(f"[bold]body[/bold] (first 500 of {total} chars):")
        console.print(snippet)
        if total > 500:
            console.print(f"... [truncated, total len={total}]")
        return


if __name__ == "__main__":
    main()
