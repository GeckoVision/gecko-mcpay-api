"""Map a Gecko ``Scope`` to a Privy v2 policy ``rules[]`` array (V1 Phase 2, Task 2.1).

NON-CUSTODIAL INVARIANT (sacred — see ``provider.py`` + ``memory/
project_noncustodial_custody_decision_2026_06_07``): the user OWNS their keys;
Gecko only ever holds a *scoped, revocable* grant. The single rule this module
exists to encode on-chain:

    The ONLY permitted transfer / withdraw destination is the user's OWN
    address. A transfer to ANY non-allowlisted destination MUST be denied.

This is a PURE function — no network, no Privy client. It produces the exact
``rules`` shape ``PrivyClient.create_policy(rules=...)`` passes through verbatim
to ``POST /v1/policies`` (the adapter that calls Privy is Task 2.2). The Privy
policy schema we target (grounded against https://docs.privy.io/controls/
policies/overview):

  * Policy semantics are **deny-by-default**: a request matching no rule is
    denied, and **DENY takes precedence over ALLOW**. So locking transfers to
    self needs (a) an ALLOW pinned to the user's address and (b) an explicit
    DENY for any other destination — the DENY is belt-and-suspenders over the
    implicit default-deny, and is self-documenting.
  * Rule  = ``{name, method, conditions: [...], action: "ALLOW" | "DENY"}``.
  * Cond  = ``{field_source, field, operator, value}``.
  * Solana field sources / fields used here:
      - ``solana_program_instruction`` / ``programId`` — gate program interaction
      - ``solana_token_program_instruction`` / ``Transfer.destination`` — SPL dest
      - ``solana_system_program_instruction`` / ``Transfer.to`` — native SOL dest
  * Operators: ``eq`` / ``neq`` (and ``in`` for multi-value, unused here).

We do NOT call Privy and we do NOT widen the allowlist: if a destination cannot
be pinned to exactly ``user_address``, this module fails closed (deny) rather
than permitting an arbitrary withdrawal.
"""

from __future__ import annotations

from typing import Any, Final

from gecko_core.wallets.provider import Scope

# ---------------------------------------------------------------------------
# Canonical Solana mainnet program IDs for the V1 trade-only action set.
#
# Grounded (2026-06-09):
#   * KLend   — solscan.io/account/KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD
#   * Jup v6  — solscan.io/account/JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4
#   * Drift v2 — docs.drift.trade/about-v2/program-vault-addresses
#
# kamino_deposit + kamino_withdraw both interact with the single KLend program.
# ---------------------------------------------------------------------------
KLEND_PROGRAM_ID: Final[str] = "KLend2g3cP87fffoy8q1mQqGKjrxjC8boSyAYavgmjD"
JUPITER_V6_PROGRAM_ID: Final[str] = "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4"
DRIFT_V2_PROGRAM_ID: Final[str] = "dRiftyHA39MWEi3m9aunc5MzRF1JYuBsbn6VPcn33UH"

#: trade action -> the Solana program it dispatches against.
TRADE_ACTION_PROGRAM_IDS: Final[dict[str, str]] = {
    "kamino_deposit": KLEND_PROGRAM_ID,
    "kamino_withdraw": KLEND_PROGRAM_ID,
    "jupiter_swap": JUPITER_V6_PROGRAM_ID,
    "drift_trade": DRIFT_V2_PROGRAM_ID,
}

# Privy's Solana signing RPC method. ``*`` would also work but we name the
# concrete method so the policy reads as exactly what we intend.
_SIGN_METHOD: Final[str] = "signAndSendTransaction"


def _program_allow_rule(action: str, program_id: str) -> dict[str, Any]:
    """ALLOW interacting with the program backing a granted trade action."""
    return {
        "name": f"allow-{action}",
        "method": _SIGN_METHOD,
        "conditions": [
            {
                "field_source": "solana_program_instruction",
                "field": "programId",
                "operator": "eq",
                "value": program_id,
            }
        ],
        "action": "ALLOW",
    }


def _self_transfer_allow_rules(user_address: str) -> list[dict[str, Any]]:
    """ALLOW SPL + native SOL transfers ONLY when the destination is the user's
    own address. Withdrawal-to-self is sacred and never kill-switch-gated."""
    return [
        {
            "name": "allow-spl-withdraw-to-self",
            "method": _SIGN_METHOD,
            "conditions": [
                {
                    "field_source": "solana_token_program_instruction",
                    "field": "Transfer.destination",
                    "operator": "eq",
                    "value": user_address,
                }
            ],
            "action": "ALLOW",
        },
        {
            "name": "allow-sol-withdraw-to-self",
            "method": _SIGN_METHOD,
            "conditions": [
                {
                    "field_source": "solana_system_program_instruction",
                    "field": "Transfer.to",
                    "operator": "eq",
                    "value": user_address,
                }
            ],
            "action": "ALLOW",
        },
    ]


def _non_self_transfer_deny_rules(user_address: str) -> list[dict[str, Any]]:
    """Explicit DENY for any SPL/SOL transfer whose destination != user_address.

    Belt-and-suspenders over Privy's implicit deny-by-default: because DENY
    beats ALLOW, this guarantees no program-allow rule can be abused to drain
    funds to a foreign address via a bundled transfer instruction.
    """
    return [
        {
            "name": "deny-spl-transfer-to-non-self",
            "method": _SIGN_METHOD,
            "conditions": [
                {
                    "field_source": "solana_token_program_instruction",
                    "field": "Transfer.destination",
                    "operator": "neq",
                    "value": user_address,
                }
            ],
            "action": "DENY",
        },
        {
            "name": "deny-sol-transfer-to-non-self",
            "method": _SIGN_METHOD,
            "conditions": [
                {
                    "field_source": "solana_system_program_instruction",
                    "field": "Transfer.to",
                    "operator": "neq",
                    "value": user_address,
                }
            ],
            "action": "DENY",
        },
    ]


def scope_to_privy_rules(scope: Scope, user_address: str) -> list[dict[str, Any]]:
    """Render a Gecko ``Scope`` as a Privy v2 policy ``rules[]`` array.

    Encodes:
      (a) ALLOW interaction with the program behind each granted trade action
          (Kamino KLend / Jupiter v6 / Drift v2);
      (b) ALLOW SPL + native-SOL transfers ONLY to ``user_address`` (the scope's
          own withdraw allowlist is the user's address — see ``user_scope``);
      (c) explicit DENY of any transfer to a non-self destination.

    Pure — no I/O. The result is consumed verbatim by
    ``PrivyClient.create_policy(rules=...)`` in Task 2.2.

    Raises ``ValueError`` if the scope's ``withdraw_allowlist`` is anything other
    than exactly ``{user_address}`` — we refuse to emit a policy that could
    permit an arbitrary withdrawal (fail closed, never widen the allowlist).
    """
    if scope.withdraw_allowlist != frozenset({user_address}):
        raise ValueError(
            "non-custodial invariant: withdraw_allowlist must be exactly the "
            "user's own address; refusing to emit a policy that permits any "
            "other transfer destination"
        )

    rules: list[dict[str, Any]] = []

    # (a) trade-action program allows — deterministic order for stable output.
    for action in sorted(scope.allowed_actions):
        program_id = TRADE_ACTION_PROGRAM_IDS.get(action)
        if program_id is None:
            # Unknown/non-trade action: emit no allow rule. Deny-by-default
            # then blocks it. (Transfer actions are handled below, not here.)
            continue
        rules.append(_program_allow_rule(action, program_id))

    # (b) withdraw-to-self ALLOW, then (c) non-self DENY (DENY > ALLOW).
    rules.extend(_self_transfer_allow_rules(user_address))
    rules.extend(_non_self_transfer_deny_rules(user_address))

    return rules


__all__ = [
    "DRIFT_V2_PROGRAM_ID",
    "JUPITER_V6_PROGRAM_ID",
    "KLEND_PROGRAM_ID",
    "TRADE_ACTION_PROGRAM_IDS",
    "scope_to_privy_rules",
]
