"""Parse Helius account-update notifications into swaps + pool reserves (step 6).

The live ingest bridge's decoding layer. The existing ``HeliusWebSocketClient``
exposes ``subscribe_account`` / ``subscribe_program`` with ``jsonParsed`` encoding
(NO ``transactionSubscribe``), so the firewall watches a pool's two **token-vault
accounts** and infers each swap from the change in reserves. This is
provider-agnostic: it decodes standard ``jsonParsed`` SPL-token account data
(``parsed.info.tokenAmount``) — NO Raydium/Orca/PumpSwap-specific layouts.

A swap moves both vaults: the base reserve falls when someone buys (base leaves
the pool to the buyer) and rises when someone sells. We track the latest balance
per vault and, on each base-vault change, emit one :class:`SwapEvent` with:

* ``side``         — ``buy`` if base reserve fell, ``sell`` if it rose.
* ``notional_usd`` — ``|Δ quote reserve| * quote_usd_per_unit``.
* ``price_usd``    — ``quote_reserve_usd / base_reserve`` (the pool spot).

Hotpath isolation: ``pydantic`` + stdlib + sibling hotpath modules only. Pure +
deterministic — every function takes the payload + a caller-supplied ``ts`` (no
clock, no I/O), so it's falsifiable against recorded fixtures before any live
wire (Pattern B/C). The runner (``launch_runner.py``) owns the websocket.

⚠️ Correctness caveat: the reserve-delta inference is verified here only against
the documented ``jsonParsed`` shape + synthetic fixtures. The exact wire payload
must be confirmed against a live Helius stream before the firewall's wash read is
trusted in prod — which is why the runner is env-gated OFF by default.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from gecko_core.trade_agent.hotpath.token_state import SwapEvent
from gecko_core.trade_agent.hotpath.wash_signals import PoolSnapshot


class VaultBalance(BaseModel):
    """A single SPL token-vault balance read out of a jsonParsed notification."""

    model_config = ConfigDict(extra="forbid")

    pubkey: str | None = Field(default=None, description="The vault account address, if known.")
    mint: str = Field(..., description="The token mint held by this vault.")
    ui_amount: float = Field(..., ge=0.0, description="Balance in UI units (decimals applied).")
    slot: int | None = Field(default=None, description="Slot of this observation, if present.")


def parse_vault_balance(
    params: dict[str, Any], *, pubkey: str | None = None
) -> VaultBalance | None:
    """Decode a Helius account/program notification into a :class:`VaultBalance`.

    Handles the ``accountSubscribe`` shape (``result.value.data.parsed.info``),
    the ``programSubscribe`` shape (``result.value.account.data...`` with
    ``value.pubkey``), and the poll-fallback synthetic shape (same ``result``).
    Returns ``None`` when the payload isn't a parsed SPL-token account (e.g.
    base64 encoding, a non-token account, or a malformed message) — fail-OPEN,
    never raise into the read loop.
    """
    result = params.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get("value")
    if not isinstance(value, dict):
        return None

    slot = None
    ctx = result.get("context")
    if isinstance(ctx, dict) and isinstance(ctx.get("slot"), int):
        slot = ctx["slot"]

    # programSubscribe nests the account under "account" and carries "pubkey".
    acct = value
    pk = pubkey
    if "account" in value and isinstance(value["account"], dict):
        acct = value["account"]
        if isinstance(value.get("pubkey"), str):
            pk = value["pubkey"]

    data = acct.get("data")
    if not isinstance(data, dict):
        return None  # base64/raw data — not jsonParsed; can't decode here
    parsed = data.get("parsed")
    if not isinstance(parsed, dict):
        return None
    info = parsed.get("info")
    if not isinstance(info, dict):
        return None
    mint = info.get("mint")
    token_amount = info.get("tokenAmount")
    if not isinstance(mint, str) or not isinstance(token_amount, dict):
        return None
    ui = token_amount.get("uiAmount")
    if ui is None:
        # Fall back to amount/decimals if uiAmount is absent.
        raw = token_amount.get("amount")
        dec = token_amount.get("decimals")
        if raw is None or dec is None:
            return None
        try:
            ui = int(raw) / (10 ** int(dec))
        except (TypeError, ValueError):
            return None
    try:
        ui_f = float(ui)
    except (TypeError, ValueError):
        return None
    if ui_f < 0:
        return None
    return VaultBalance(pubkey=pk, mint=mint, ui_amount=ui_f, slot=slot)


class PoolReserveTracker:
    """Infers swaps + pool reserves for ONE pool from its two vault balances.

    Configured with the base/quote vault addresses and the quote token's USD
    value per unit (1.0 for USDC; the SOL/USD price for SOL-quoted pools, which
    the runner injects + refreshes). Not a pydantic model — it holds mutable
    last-seen state and is driven by the runner.
    """

    __slots__ = (
        "_count",
        "_last_base",
        "_last_quote",
        "base_vault",
        "pool_addr",
        "quote_usd",
        "quote_vault",
    )

    def __init__(
        self,
        pool_addr: str,
        *,
        base_vault: str,
        quote_vault: str,
        quote_usd_per_unit: float = 1.0,
    ) -> None:
        self.pool_addr = pool_addr
        self.base_vault = base_vault
        self.quote_vault = quote_vault
        self.quote_usd = quote_usd_per_unit
        self._last_base: float | None = None
        self._last_quote: float | None = None
        self._count = 0

    def _snapshot(self) -> PoolSnapshot:
        base = self._last_base or 0.0
        quote_usd_val = (self._last_quote or 0.0) * self.quote_usd
        spot = (quote_usd_val / base) if base > 0 else None
        # CPMM TVL ≈ 2× the quote-side USD value (both legs roughly equal value).
        tvl = 2.0 * quote_usd_val if quote_usd_val > 0 else None
        return PoolSnapshot(
            pool_addr=self.pool_addr,
            spot_price_usd=spot,
            tvl_usd=tvl,
            vol_5m_usd=0.0,
            swap_count_5m=self._count,
            is_clmm=False,
        )

    def observe(self, vb: VaultBalance, *, ts: float) -> tuple[SwapEvent | None, PoolSnapshot]:
        """Fold in one vault balance; return (swap_or_None, current_pool_snapshot).

        A swap is emitted only when the BASE reserve changed since the last emit
        and both reserves are known — that's the event that carries side + size.
        A quote-only update refreshes the price/TVL silently.
        """
        is_base = vb.pubkey == self.base_vault
        is_quote = vb.pubkey == self.quote_vault
        if is_base:
            prev_base = self._last_base
            self._last_base = vb.ui_amount
        elif is_quote:
            self._last_quote = vb.ui_amount
            return None, self._snapshot()
        else:
            # Unknown vault for this pool — ignore.
            return None, self._snapshot()

        # Base changed: try to emit a swap if we have both legs + a prior base.
        if prev_base is None or self._last_quote is None or self._last_base is None:
            return None, self._snapshot()
        base_delta = self._last_base - prev_base
        if base_delta == 0:
            return None, self._snapshot()

        side: Literal["buy", "sell"] = "buy" if base_delta < 0 else "sell"  # base out = buy
        # Notional ≈ the quote that moved. We don't see the pre-swap quote on the
        # base notification, so approximate via constant-product: |Δbase| * price.
        price = self._snapshot().spot_price_usd
        if price is None:
            return None, self._snapshot()
        notional = abs(base_delta) * price
        self._count += 1
        # HONEST LIMITATION: vault-reserve ingest does NOT reveal the swap signer.
        # We attribute every swap on a pool to ONE stable placeholder wallet so we
        # never FAKE buyer diversity. Consequence: F1 cannot use its unique-buyer
        # guard on this path (it leans on the size-uniformity guard instead), and
        # F2 (wash) / F4 (sybil) — which are per-wallet — are INERT here. Real
        # per-wallet attribution needs the parsed-transaction path (getBlock /
        # transactionSubscribe), deferred. This path powers F1 (flow shape) + F5
        # (price bait) only.
        swap = SwapEvent(
            ts=ts,
            wallet=f"pool:{self.pool_addr}",
            side=side,
            notional_usd=notional,
            price_usd=price,
            pool_addr=self.pool_addr,
        )
        return swap, self._snapshot()
