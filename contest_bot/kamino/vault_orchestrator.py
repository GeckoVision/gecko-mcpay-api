"""Vault orchestrator (S45) — "the agent manages the portfolio while you trade."

Paper-mode. Ties the flow together:
  realized trading profit → allocate across the user's PROFILE basket
  → vault_check gate (S44) → paper deposit → positions
  → monitor cadence (S42, fed the Oracle's predicted downside)
  → act on verdicts (EXIT / DELEVERAGE / ROTATE / HOLD)

Every public method is best-effort and never raises into the bot loop (same
discipline as the S25 paper-sink). Real custody is out of scope here — the live
path swaps a `VaultAdapter` (devnet/stub now; OKX-TEE/Privy later, founder-gated)
behind the gate. This module decides WHAT to do; the adapter does it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from kamino import vault_gate as vg
from kamino.monitor import DELEVERAGE, EXIT, FIAT_CDB_BR, HOLD, ROTATE, Hurdle, evaluate
from kamino.multiply import LeverageStrategy

logger = logging.getLogger("kamino.vault_orchestrator")


# ── Profile baskets: (strategy template, weight). Weights sum to 1.0. ──────
def _lend() -> LeverageStrategy:
    return LeverageStrategy("USDC lend", 0.058, 0.0, 1.0, 0.75, 0.80, True, "stable_spread")


def _lst(leverage: float) -> LeverageStrategy:
    return LeverageStrategy(f"JitoSOL/SOL {leverage:g}x", 0.07, 0.06, leverage, 0.90, 0.93, True, "lst_staking")


def _jlp() -> LeverageStrategy:
    return LeverageStrategy("JLP/USDC 3.2x", 0.12, 0.06, 3.2, 0.69, 0.73, False, "jlp_fees")


# conservative = no liquidation surface; aggressive = leverage + a volatile sleeve.
PROFILE_BASKETS: dict[str, list[tuple[LeverageStrategy, float]]] = {
    "conservative": [(_lend(), 1.0)],
    "moderate": [(_lst(4.0), 0.6), (_lend(), 0.4)],
    "aggressive": [(_lst(8.0), 0.5), (_jlp(), 0.3), (_lend(), 0.2)],
}


def predicted_drawdown_from_market_temp(snap: dict | None) -> float | None:
    """Bridge the S40/S41 market-temperature read → a downside prediction the vault
    monitor consumes. THE UNIFICATION (founder, 2026-06-04): the same risk-off signal
    that gates trades now sizes the vault's liquidation-risk watch — "watch the vault
    the way we watch a trade." Maps the macro tape to a plausible adverse move on a
    volatile collateral leg:
        risk_off (≤ -0.25) → ~15%   cool (≤ -0.08) → ~8%   neutral/warm/risk_on → None
    Returns None when the tape isn't risk-off (no elevated downside to act on) or the
    snapshot is stale/missing (fail-open — never fabricate a prediction)."""
    if not snap or snap.get("stale"):
        return None
    try:
        temp = float(snap.get("temp", 0.0))
    except (TypeError, ValueError):
        return None
    if temp <= -0.25:
        return 0.15
    if temp <= -0.08:
        return 0.08
    return None


@dataclass
class VaultLot:
    """A paper position in one strategy."""

    source: str  # yield_source key, doubles as the lot id within a profile
    principal_usd: float
    strategy: LeverageStrategy


@dataclass
class VaultOrchestrator:
    profile: str = "conservative"
    policy: vg.VaultPolicy = field(default_factory=vg.VaultPolicy)
    hurdle: Hurdle = field(default_factory=lambda: FIAT_CDB_BR)
    lots: list[VaultLot] = field(default_factory=list)

    @property
    def allocation_usd(self) -> float:
        return sum(lot.principal_usd for lot in self.lots)

    # ── allocation ─────────────────────────────────────────────────────────
    def allocate_profit(
        self, profit_usd: float, *, predicted_drawdown_pct: float | None = None
    ) -> dict:
        """Split realized profit across the profile basket; gate each leg; paper-deposit
        the ones that pass. Returns a per-leg report (never raises)."""
        try:
            basket = PROFILE_BASKETS.get(self.profile, PROFILE_BASKETS["conservative"])
            deposited: list[dict] = []
            denied: list[dict] = []
            for template, weight in basket:
                amt = round(profit_usd * weight, 4)
                if amt <= 0:
                    continue
                v = vg.vault_check(
                    vg.DEPOSIT, amt, self.policy,
                    strategy=template,
                    current_allocation_usd=self.allocation_usd,
                    predicted_drawdown_pct=predicted_drawdown_pct,
                )
                if not v.allow:
                    denied.append({"source": template.yield_source, "amount": amt, "reasons": v.reasons})
                    continue
                self._add_to_lot(template, amt)
                deposited.append({"source": template.yield_source, "amount": amt, "monitor": v.monitor_action})
            return {"deposited": deposited, "denied": denied, "allocation_usd": self.allocation_usd}
        except Exception as exc:  # never break the bot loop
            logger.warning("vault allocate_profit swallow: %s", exc)
            return {"deposited": [], "denied": [], "error": f"{type(exc).__name__}: {exc}"}

    def _add_to_lot(self, template: LeverageStrategy, amt: float) -> None:
        for lot in self.lots:
            if lot.source == template.yield_source and lot.strategy.leverage == template.leverage:
                lot.principal_usd = round(lot.principal_usd + amt, 4)
                return
        self.lots.append(VaultLot(source=template.yield_source, principal_usd=amt, strategy=template))

    # ── monitor cadence ──────────────────────────────────────────────────────
    def monitor_tick(self, *, predicted_drawdown_pct: float | None = None) -> list[dict]:
        """Judge every lot with the S42 monitor (fed the Oracle's downside). Returns
        a verdict per lot; does NOT mutate — call apply_actions to act."""
        out: list[dict] = []
        for lot in self.lots:
            try:
                v = evaluate(lot.strategy, hurdle=self.hurdle, predicted_drawdown_pct=predicted_drawdown_pct)
                out.append({
                    "source": lot.source, "principal_usd": lot.principal_usd,
                    "action": v.action, "reason": v.reason, "net_apy": round(v.net_apy, 4),
                    "suggested_leverage": v.suggested_leverage,
                })
            except Exception as exc:
                logger.warning("vault monitor_tick swallow (%s): %s", lot.source, exc)
        return out

    def apply_actions(self, verdicts: list[dict]) -> list[dict]:
        """Paper-act on monitor verdicts: EXIT closes the lot, DELEVERAGE/ROTATE
        re-leverages it. Returns what changed. Real execution swaps in the adapter."""
        changed: list[dict] = []
        for v in verdicts:
            lot = next((lt for lt in self.lots if lt.source == v["source"]), None)
            if lot is None:
                continue
            action = v.get("action")
            if action == EXIT:
                self.lots.remove(lot)
                changed.append({"source": v["source"], "did": "exited", "freed_usd": lot.principal_usd})
            elif action == ROTATE and v.get("suggested_leverage"):
                lot.strategy = lot.strategy.with_leverage(v["suggested_leverage"])
                changed.append({"source": v["source"], "did": f"rotated→{v['suggested_leverage']:.1f}x"})
            elif action == DELEVERAGE:
                new_lev = max(1.0, lot.strategy.leverage * 0.5)
                lot.strategy = lot.strategy.with_leverage(new_lev)
                changed.append({"source": v["source"], "did": f"deleveraged→{new_lev:.1f}x"})
            elif action == HOLD:
                pass
        return changed

    def snapshot(self) -> dict:
        """Dashboard/API view of the whole vault."""
        return {
            "profile": self.profile,
            "allocation_usd": round(self.allocation_usd, 2),
            "hurdle_apy": self.hurdle.apy,
            "lots": [
                {
                    "source": lot.source,
                    "principal_usd": round(lot.principal_usd, 2),
                    "leverage": lot.strategy.leverage,
                    "net_apy": round(lot.strategy.net_apy, 4),
                    "liquidation_drop_pct": round(lot.strategy.liquidation_drop_pct, 4),
                    "correlated": lot.strategy.correlated,
                }
                for lot in self.lots
            ],
        }
