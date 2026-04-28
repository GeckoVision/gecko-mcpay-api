"""Internal-only routes — invoked by EventBridge / private cron, not users.

These endpoints emit operational metrics and are not part of the public API
contract. They live behind the same ALB as the public routes; in V1 we rely
on the path being unadvertised + non-public discovery (no /.well-known entry,
no docs). V2 will move them to a private listener / VPC endpoint.

Currently exposed:

    GET /internal/twitsh/balance — reads twit.sh wallet USDC balance via
        Base RPC and emits the `Gecko/Twitsh/WalletBalanceUSDC` CloudWatch
        metric used by the `gecko-twitsh-wallet-low` alarm. EventBridge hits
        this every 5 minutes when twit.sh is enabled. Returns early without
        emitting when `is_twitsh_configured()` is False so the metric stays
        dormant before onboarding (alarm `TreatMissingData=notBreaching`).

The full Base RPC + USDC ERC20 balance read lands with S2X-08 (the twit.sh
client itself). This route is a stub today: it returns the configured-vs-not
state and the wallet address (no secrets), so the EventBridge schedule can
be wired in advance.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from gecko_api.settings import Settings

router = APIRouter(prefix="/internal", tags=["internal"])


@router.get("/twitsh/balance")
async def twitsh_balance() -> dict[str, Any]:
    """Reads twit.sh wallet USDC balance via Base RPC, emits CloudWatch metric.

    Called by EventBridge every 5 minutes. Returns the balance for visibility.
    Returns early (no metric emit) when twit.sh is not configured — the alarm
    treats missing data as not-breaching so this is safe.
    """
    settings = Settings.from_env()
    if not settings.is_twitsh_configured():
        return {
            "configured": False,
            "enabled": settings.twitsh_enabled,
            "address": None,
            "balance_usdc": None,
            "note": (
                "twit.sh not configured (TWITSH_ENABLED=false or wallet "
                "sentinels in SSM). No metric emitted; alarm TreatMissingData "
                "is notBreaching."
            ),
        }

    # S2X-08 territory: the actual Base RPC USDC balanceOf() call + the
    # CloudWatch PutMetricData(Namespace='Gecko/Twitsh', MetricName=
    # 'WalletBalanceUSDC') happens in the twit.sh client. This stub keeps
    # the route addressable for the EventBridge wire-up and reports config
    # state without exposing secrets.
    return {
        "configured": True,
        "enabled": settings.twitsh_enabled,
        "address": settings.twitsh_wallet_address,
        "balance_usdc": None,  # populated when S2X-08 lands
        "note": "balance read pending S2X-08 client",
    }


__all__ = ["router"]
