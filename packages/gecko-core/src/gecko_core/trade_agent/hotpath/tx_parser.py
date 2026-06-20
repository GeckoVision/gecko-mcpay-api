"""Parsed-transaction → ParsedSwap — the keystone that lights up the snipe gate.

The reserve-delta path (`swap_parser`) sees *that* a pool's balance changed, but
not *who* changed it — so it can only power F1/F5. The snipe gate, I2, and the
ALT-identity vein need signer-level facts: who bought, in which slot, paying which
tip, through which programs, referencing which lookup tables. Those live in the
**parsed transaction**, delivered by Helius `transactionSubscribe` (the enhanced /
geyser websocket).

This module is the pure decoder: a parsed-tx dict → :class:`ParsedSwap`. It reads
the fields the snipe gate consumes and nothing else:

* **signer**  — the fee payer (``accountKeys`` entry flagged signer+writable, else index 0).
* **slot**    — from the notification context.
* **tip_lamports** — sum of native (System-program) transfers to a Jito tip account.
* **program_ids**  — every program invoked (top-level + inner), for I2 attribution.
* **alt_addresses** — ``addressTableLookups`` table keys, for ALT-as-identity.
* **is_buy / notional_sol** — direction + size, from the fee-payer's SOL delta
  (``meta.preBalances``/``postBalances`` at the signer index): SOL out = a buy of
  the launch token. Net-of-fee is acceptable at launch sizes.

Pure + offline (`pydantic`/stdlib + sibling hotpath modules): fixture-testable
today (Pattern B/C). The exact live Helius payload shape is confirmed at the live
smoke before the firewall flag flips (Pattern E). **Fail-OPEN** — any unexpected
shape returns ``None`` and the tx is skipped, never crashing the runner.
"""

from __future__ import annotations

from typing import Any

from gecko_core.trade_agent.hotpath.jito import JITO_TIP_ACCOUNTS
from gecko_core.trade_agent.hotpath.snipe_features import LAMPORTS_PER_SOL, ParsedSwap

_SYSTEM_PROGRAM = "11111111111111111111111111111111"
_TIP_SET = frozenset(JITO_TIP_ACCOUNTS)
# A buy must move at least this much SOL from the signer to count (filters dust /
# fee-only txns that aren't real swaps).
_MIN_BUY_SOL = 1e-4


def _tx_inner(notification: dict[str, Any]) -> tuple[dict[str, Any], int | None] | None:
    """Extract (transaction-dict, slot) from a transactionSubscribe notification.

    Tolerates both the ws notification envelope (``result.value`` / ``result.slot``)
    and a bare parsed-tx dict (for fixtures). Returns ``None`` on an unusable shape.
    """
    result = (notification or {}).get("result")
    if isinstance(result, dict):
        value = result.get("value")
        slot = result.get("slot")
        if isinstance(value, dict):
            return value, (slot if isinstance(slot, int) else None)
    # bare parsed-tx (fixture path)
    if isinstance(notification, dict) and "transaction" in notification:
        slot = notification.get("slot")
        return notification, (slot if isinstance(slot, int) else None)
    return None


def _account_keys(message: dict[str, Any]) -> list[Any]:
    return message.get("accountKeys") or []


def _key_str(k: Any) -> str | None:
    if isinstance(k, str):
        return k
    if isinstance(k, dict):
        pk = k.get("pubkey")
        if isinstance(pk, str):
            return pk
    return None


def _signer(message: dict[str, Any]) -> str | None:
    """The fee payer: first signer+writable key (jsonParsed), else index 0."""
    keys = _account_keys(message)
    for k in keys:
        if isinstance(k, dict) and k.get("signer") and k.get("writable"):
            pk = _key_str(k)
            if pk:
                return pk
    # raw message: first account key is the fee payer
    if keys:
        return _key_str(keys[0])
    return None


def _program_ids(message: dict[str, Any], meta: dict[str, Any]) -> list[str]:
    """Every program invoked — top-level instruction programIds + inner ones."""
    out: list[str] = []
    for ix in message.get("instructions") or []:
        if isinstance(ix, dict) and isinstance(ix.get("programId"), str):
            out.append(ix["programId"])
    for group in meta.get("innerInstructions") or []:
        for ix in (group or {}).get("instructions") or []:
            if isinstance(ix, dict) and isinstance(ix.get("programId"), str):
                out.append(ix["programId"])
    return list(dict.fromkeys(out))  # de-dup, preserve order


def _alt_addresses(message: dict[str, Any]) -> list[str]:
    """The address-lookup-table account keys this tx referenced (ALT identity)."""
    out: list[str] = []
    for lut in message.get("addressTableLookups") or []:
        if isinstance(lut, dict):
            key = lut.get("accountKey")
            if isinstance(key, str):
                out.append(key)
    return list(dict.fromkeys(out))


def _tip_lamports(message: dict[str, Any]) -> int:
    """Sum of native transfers to a Jito tip account (0 = not a bundle)."""
    total = 0
    for ix in message.get("instructions") or []:
        if not isinstance(ix, dict):
            continue
        if ix.get("programId") != _SYSTEM_PROGRAM:
            continue
        parsed = ix.get("parsed")
        if not isinstance(parsed, dict) or parsed.get("type") != "transfer":
            continue
        info = parsed.get("info") or {}
        dest = info.get("destination")
        lamports = info.get("lamports")
        if dest in _TIP_SET and isinstance(lamports, int):
            total += lamports
    return total


def _signer_sol_delta(message: dict[str, Any], meta: dict[str, Any], signer: str) -> float | None:
    """Signed SOL change for the signer (post-pre), in SOL. Negative = SOL spent."""
    keys = [_key_str(k) for k in _account_keys(message)]
    try:
        idx = keys.index(signer)
    except ValueError:
        return None
    pre = meta.get("preBalances")
    post = meta.get("postBalances")
    if not isinstance(pre, list) or not isinstance(post, list):
        return None
    if not (0 <= idx < len(pre) and idx < len(post)):
        return None
    try:
        return (int(post[idx]) - int(pre[idx])) / LAMPORTS_PER_SOL
    except (TypeError, ValueError):
        return None


def parse_swap_tx(
    notification: dict[str, Any], *, timestamp: float | None = None
) -> ParsedSwap | None:
    """Decode a transactionSubscribe notification into a :class:`ParsedSwap`.

    Returns ``None`` (fail-OPEN) when the tx isn't a usable launch buy: failed tx,
    missing signer, or SOL movement below :data:`_MIN_BUY_SOL`. ``timestamp`` (block
    time) is stamped through when the caller has it.
    """
    extracted = _tx_inner(notification)
    if extracted is None:
        return None
    tx, slot = extracted
    meta = tx.get("meta") or {}
    if meta.get("err") is not None:  # failed tx — never a real buy
        return None
    message = (tx.get("transaction") or {}).get("message") or tx.get("message") or {}
    if not isinstance(message, dict):
        return None

    signer = _signer(message)
    if not signer:
        return None

    sol_delta = _signer_sol_delta(message, meta, signer)
    tip = _tip_lamports(message)
    # A buy spends SOL beyond the tip+fee. Use the net signer outflow as the side
    # signal: SOL out (negative delta) past the dust floor = a buy of the token.
    is_buy = sol_delta is not None and sol_delta < -_MIN_BUY_SOL
    notional_sol = abs(sol_delta) if sol_delta is not None else 0.0

    block_time = tx.get("blockTime")
    ts = (
        timestamp
        if timestamp is not None
        else (block_time if isinstance(block_time, int) else None)
    )

    return ParsedSwap(
        signer=signer,
        slot=slot if slot is not None else 0,
        is_buy=is_buy,
        notional_sol=notional_sol,
        tip_lamports=tip,
        program_ids=_program_ids(message, meta),
        alt_addresses=_alt_addresses(message),
        wallet_age_s=None,  # filled by a creation-slot lookup (deferred enrichment)
        timestamp=float(ts) if ts is not None else None,
    )


__all__ = ["parse_swap_tx"]
