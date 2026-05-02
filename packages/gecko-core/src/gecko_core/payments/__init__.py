"""Payments — x402 on Solana with stub/live/frames modes.

Owned by `web3-engineer`. Stub by default; live mode requires explicit
env config. See `docs/implementation-plan.md` Phase 4.
"""

from gecko_core.payments.cdp import (
    CDPAuthProvider,
    CDPCredentials,
    CDPFacilitatorClient,
    build_cdp_facilitator_client,
    is_unconfigured,
)
from gecko_core.payments.cdp_x402_client import (
    BASE_MAINNET_NETWORK_ID,
    BASE_MAINNET_USDC_CONTRACT,
    BASE_SEPOLIA_NETWORK_ID,
    CDP_FACILITATOR_BASE_URL,
    CDPNotConfiguredError,
    CDPSettleError,
    CDPX402Client,
    CDPX402Error,
)
from gecko_core.payments.creator_payout import (
    DEFAULT_PER_CITE_USD as CREATOR_PAYOUT_DEFAULT_PER_CITE_USD,
)
from gecko_core.payments.creator_payout import (
    aggregate_creator_payouts,
    resolve_per_cite_amount_usd,
    settle_creator_payouts,
)
from gecko_core.payments.factory import (
    CLOUDFLARE_NETWORK_ID,
    resolve_client,
)
from gecko_core.payments.gate import run_payment_gate
from gecko_core.payments.models import (
    PaymentIntent,
    PaymentRequiredError,
    PaymentResult,
)
from gecko_core.payments.networks import (
    NETWORKS,
    NetworkConfig,
    NetworkName,
    resolve_network,
)
from gecko_core.payments.pricing import price_for
from gecko_core.payments.protocol import (
    ConfirmationStatus,
    PaymentReceipt,
)
from gecko_core.payments.verdict_settle import (
    VERDICT_DETAIL_PRICE_USDC,
    VERDICT_SETTLE_LIVE_ENV,
    InvalidVerdictPaymentError,
    VerdictPaymentError,
    VerdictPaywallNotLiveError,
    is_verdict_settle_live_enabled,
    make_verdict_payment_requirement,
    resolve_verdict_settle_mode,
    verify_verdict_payment,
)
from gecko_core.payments.verdict_settle import (
    PaymentRequirements as VerdictPaymentRequirements,
)
from gecko_core.payments.verdict_settle import (
    SettlementReceipt as VerdictSettlementReceipt,
)
from gecko_core.payments.verifier import (
    VerifyResult,
    VerifyTarget,
    is_stub_signature,
    resolve_rpc_url,
    summarize,
    verify_target,
    verify_targets,
)
from gecko_core.payments.x402_client import (
    PAYMENT_MODES,
    FramesX402Client,
    LiveX402Client,
    NetworkKind,
    PaymentMode,
    StubX402Client,
    X402Client,
    X402Mode,
    facilitator_id_for_network,
    get_client,
    resolve_client_for_network,
)

__all__ = [
    "BASE_MAINNET_NETWORK_ID",
    "BASE_MAINNET_USDC_CONTRACT",
    "BASE_SEPOLIA_NETWORK_ID",
    "CDP_FACILITATOR_BASE_URL",
    "CLOUDFLARE_NETWORK_ID",
    "CREATOR_PAYOUT_DEFAULT_PER_CITE_USD",
    "NETWORKS",
    "PAYMENT_MODES",
    "VERDICT_DETAIL_PRICE_USDC",
    "VERDICT_SETTLE_LIVE_ENV",
    "CDPAuthProvider",
    "CDPCredentials",
    "CDPFacilitatorClient",
    "CDPNotConfiguredError",
    "CDPSettleError",
    "CDPX402Client",
    "CDPX402Error",
    "ConfirmationStatus",
    "FramesX402Client",
    "InvalidVerdictPaymentError",
    "LiveX402Client",
    "NetworkConfig",
    "NetworkKind",
    "NetworkName",
    "PaymentIntent",
    "PaymentMode",
    "PaymentReceipt",
    "PaymentRequiredError",
    "PaymentResult",
    "StubX402Client",
    "VerdictPaymentError",
    "VerdictPaymentRequirements",
    "VerdictPaywallNotLiveError",
    "VerdictSettlementReceipt",
    "VerifyResult",
    "VerifyTarget",
    "X402Client",
    "X402Mode",
    "aggregate_creator_payouts",
    "build_cdp_facilitator_client",
    "facilitator_id_for_network",
    "get_client",
    "is_stub_signature",
    "is_unconfigured",
    "is_verdict_settle_live_enabled",
    "make_verdict_payment_requirement",
    "price_for",
    "resolve_client",
    "resolve_client_for_network",
    "resolve_network",
    "resolve_per_cite_amount_usd",
    "resolve_rpc_url",
    "resolve_verdict_settle_mode",
    "run_payment_gate",
    "settle_creator_payouts",
    "summarize",
    "verify_target",
    "verify_targets",
    "verify_verdict_payment",
]
