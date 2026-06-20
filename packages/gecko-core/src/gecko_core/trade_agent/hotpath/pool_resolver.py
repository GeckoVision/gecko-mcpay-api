"""Pool resolver — turn a new-pool init transaction into a trackable pool.

Pool discovery hears a `logsSubscribe` notification that a launch pool was just
created; this module turns that into the concrete `(mint, base_vault, quote_vault)`
the `LaunchRunner` needs to arm its vault subscriptions.

**Design choice — data-driven, not instruction-layout-driven.** Decoding per-AMM
init-instruction account indices is brittle (every AMM orders accounts
differently, and the layouts drift). Instead we read `meta.postTokenBalances`
from the parsed transaction: a pool-init creates exactly the two token vaults, and
postTokenBalances reliably carries each one's `mint`, `owner`, and `accountIndex`
across every SPL-based AMM. We pair the vault whose mint is a known quote
(WSOL/USDC/USDT) with the vault whose mint is the launch token. The vault account
pubkeys come from `accountKeys[accountIndex]`.

Pure + offline (`pydantic`/stdlib only): `resolve_from_parsed_tx` is a pure
function over a tx dict, fixture-testable today (Pattern B/C). The exact init-log
markers + the live `getTransaction` payload shape are confirmed by the live smoke
before the firewall flag flips (Pattern E). **Fail-OPEN everywhere** — any
unexpected shape returns ``None`` and the pool is simply skipped, never crashing
the runner.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Known quote/settlement mints. A pool pairs the launch token against one of
# these; the OTHER side is the launch mint. (Pattern A: one canonical place.)
WSOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
USDT_MINT = "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"
KNOWN_QUOTE_MINTS: frozenset[str] = frozenset({WSOL_MINT, USDC_MINT, USDT_MINT})

# Stable quotes price 1:1 in USD; WSOL notionals are left in SOL units for v1
# (the snipe signals — co-buy, reserve moves, fee outliers — are unit-agnostic).
_STABLE_USD_PER_UNIT: dict[str, float] = {USDC_MINT: 1.0, USDT_MINT: 1.0}

# Case-insensitive substrings that indicate a pool-init instruction in the log
# lines. Generic across the majors; a false match just triggers a resolve attempt
# that fails-OPEN if the tx isn't actually a new pool. Confirm/extend at the live
# smoke. (Pattern A: one canonical place.)
INIT_LOG_MARKERS: tuple[str, ...] = (
    "initialize2",  # Raydium AMM v4
    "init_pc_amount",  # Raydium init args
    "initializepool",  # CLMM / generic
    "initialize_pool",
    "create_pool",
    "createpool",
    "instruction: create",  # PumpSwap / Meteora create
    "instruction: initialize",
)


class ResolvedPool(BaseModel):
    """A discovered pool, ready to hand to ``LaunchRunner.track_pool``."""

    model_config = ConfigDict(extra="forbid")

    mint: str = Field(..., description="the launch token mint (non-quote side).")
    pool_addr: str = Field(..., description="stable tracking key for this pool.")
    base_vault: str = Field(..., description="vault holding the launch token.")
    quote_vault: str = Field(..., description="vault holding the quote (WSOL/stable).")
    quote_mint: str = Field(..., description="the quote mint this pool settles in.")
    quote_usd_per_unit: float = Field(default=1.0, ge=0.0)
    pool_created_ts: int | None = Field(default=None, ge=0)


def is_pool_init_log(logs: list[str] | None) -> bool:
    """True if any log line looks like a pool-init instruction (cheap pre-filter)."""
    if not logs:
        return False
    for line in logs:
        low = line.lower()
        if any(marker in low for marker in INIT_LOG_MARKERS):
            return True
    return False


def _account_keys(tx: dict[str, Any]) -> list[str]:
    """Flatten message.accountKeys to a list of pubkey strings (jsonParsed or raw)."""
    msg = (tx.get("transaction") or {}).get("message") or {}
    keys = msg.get("accountKeys") or []
    out: list[str] = []
    for k in keys:
        if isinstance(k, str):
            out.append(k)
        elif isinstance(k, dict) and isinstance(k.get("pubkey"), str):
            out.append(k["pubkey"])
    # Address-lookup-table loaded addresses, when present, extend the index space.
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    for bucket in ("writable", "readonly"):
        for k in loaded.get(bucket) or []:
            if isinstance(k, str):
                out.append(k)
    return out


def _post_token_balances(tx: dict[str, Any]) -> list[dict[str, Any]]:
    rows = (tx.get("meta") or {}).get("postTokenBalances") or []
    return [r for r in rows if isinstance(r, dict)]


def resolve_from_parsed_tx(
    tx: dict[str, Any],
    *,
    signature: str | None = None,
    created_ts: int | None = None,
) -> ResolvedPool | None:
    """Resolve a parsed init tx into a :class:`ResolvedPool`, or ``None`` (fail-OPEN).

    Pairs the quote vault (mint ∈ :data:`KNOWN_QUOTE_MINTS`) with the launch vault
    (the other mint), reading vault pubkeys from ``accountKeys[accountIndex]``.
    Returns ``None`` if the tx doesn't present exactly one clean launch/quote pair.
    """
    keys = _account_keys(tx)
    balances = _post_token_balances(tx)
    if not keys or len(balances) < 2:
        return None

    quote_rows: list[dict[str, Any]] = []
    launch_rows: list[dict[str, Any]] = []
    for r in balances:
        mint = r.get("mint")
        idx = r.get("accountIndex")
        if not isinstance(mint, str) or not isinstance(idx, int):
            continue
        if not (0 <= idx < len(keys)):
            continue
        (quote_rows if mint in KNOWN_QUOTE_MINTS else launch_rows).append(r)

    if not quote_rows or not launch_rows:
        return None

    # Prefer the deepest quote vault (largest balance) + the launch vault that
    # shares its owner (the pool authority), so we pick the real pool pair even if
    # the tx touched unrelated token accounts.
    def _ui(r: dict[str, Any]) -> float:
        amt = (r.get("uiTokenAmount") or {}).get("uiAmount")
        try:
            return float(amt) if amt is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    quote_row = max(quote_rows, key=_ui)
    quote_owner = quote_row.get("owner")
    same_owner = [r for r in launch_rows if r.get("owner") == quote_owner and quote_owner]
    launch_row = max(same_owner or launch_rows, key=_ui)

    quote_vault = keys[quote_row["accountIndex"]]
    base_vault = keys[launch_row["accountIndex"]]
    launch_mint = launch_row.get("mint")
    quote_mint = quote_row.get("mint")
    if not isinstance(launch_mint, str) or not isinstance(quote_mint, str):
        return None
    if base_vault == quote_vault:
        return None

    # Stable tracking key from the vault pair (unique + deterministic; the reserve
    # tracker keys on vault pubkeys, so we don't need the AMM's pool PDA itself).
    pool_addr = f"pool:{base_vault}:{quote_vault}"

    # Default the creation time from the tx's own blockTime if the caller didn't
    # pass one (so the resolver is self-sufficient on a parsed tx).
    if created_ts is None and isinstance(tx.get("blockTime"), int):
        created_ts = tx["blockTime"]

    return ResolvedPool(
        mint=launch_mint,
        pool_addr=pool_addr,
        base_vault=base_vault,
        quote_vault=quote_vault,
        quote_mint=quote_mint,
        quote_usd_per_unit=_STABLE_USD_PER_UNIT.get(quote_mint, 1.0),
        pool_created_ts=created_ts,
    )


def extract_signature(params: dict[str, Any]) -> str | None:
    """Pull the tx signature from a logsNotification ``params`` payload."""
    value = ((params or {}).get("result") or {}).get("value") or {}
    sig = value.get("signature")
    return sig if isinstance(sig, str) else None


def extract_logs(params: dict[str, Any]) -> list[str] | None:
    """Pull the log lines from a logsNotification ``params`` payload."""
    value = ((params or {}).get("result") or {}).get("value") or {}
    logs = value.get("logs")
    if isinstance(logs, list) and all(isinstance(x, str) for x in logs):
        return logs
    return None


__all__ = [
    "INIT_LOG_MARKERS",
    "KNOWN_QUOTE_MINTS",
    "USDC_MINT",
    "USDT_MINT",
    "WSOL_MINT",
    "ResolvedPool",
    "extract_logs",
    "extract_signature",
    "is_pool_init_log",
    "resolve_from_parsed_tx",
]
