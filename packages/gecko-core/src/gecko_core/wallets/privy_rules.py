"""Map a Gecko ``Scope`` to a Privy v2 policy ``rules[]`` array (V1 Phase 2, Task 2.1).

NON-CUSTODIAL INVARIANT (sacred — see ``provider.py`` + ``memory/
project_noncustodial_custody_decision_2026_06_07``): the user OWNS their keys;
Gecko only ever holds a *scoped, revocable* grant. The single rule this module
exists to encode on-chain:

    The ONLY permitted transfer / withdraw destination is the user's OWN
    address. A transfer to ANY non-allowlisted destination MUST be denied.

ENFORCEMENT MODEL — DENY-BY-DEFAULT (corrected against the live Privy API,
2026-06-09). Privy's Solana condition validator accepts ONLY these operators:
``eq | gt | gte | lt | lte | in | in_condition_set``. It REJECTS ``neq``. The
original belt-and-suspenders explicit ``neq`` DENY rules were therefore invalid
on the wire and have been REMOVED. After their removal, "no non-self transfer"
is enforced by exactly two things, together:

  1. self-pinned ``eq`` ALLOW rules — a transfer is ALLOWed only when its
     destination/`to` field equals ``user_address``; and
  2. Privy **deny-by-default** — any signing request that matches no ALLOW rule
     is denied. A transfer to any non-self destination matches no ``eq``-self
     ALLOW, so it falls through to the default deny.

There is NO explicit DENY rule for non-self transfers anymore. The self-pinned
``eq`` ALLOW + deny-by-default is the whole enforcement. The fail-closed guard
in ``scope_to_privy_rules`` (raises unless ``withdraw_allowlist == {user_address}``)
remains the second line of defence so we never emit a policy that pins anything
other than the user's own address.

⚠️  L2 DEVNET VERIFICATION IS MANDATORY BEFORE LIVE SIGNING. Deny-by-default is
only as strong as Privy's destination extraction. A real non-self transfer MUST
be observed to be REJECTED on devnet — including a CPI-NESTED transfer buried
inside an otherwise-allowed program call (e.g. a Jupiter route that smuggles an
SPL transfer to a foreign address). That residual extraction risk is exactly
why ``execute``/``withdraw`` signing stays gated (NotImplementedError) until L2
confirms rejection on the wire.

This is a PURE function — no network, no Privy client. It produces the exact
``rules`` shape ``PrivyClient.create_policy(rules=...)`` passes through verbatim
to ``POST /v1/policies`` (the adapter that calls Privy is Task 2.2). Schema:

  * Rule  = ``{name, method, conditions: [...], action: "ALLOW" | "DENY"}``.
  * Cond  = ``{field_source, field, operator, value}``.
  * Solana field sources / fields used here:
      - ``solana_program_instruction`` / ``programId`` — gate program interaction
      - ``solana_token_program_instruction`` / ``Transfer.destination`` — SPL dest
      - ``solana_system_program_instruction`` / ``Transfer.to`` — native SOL dest
  * Operators (Solana-supported set): ``eq`` / ``gt`` / ``gte`` / ``lt`` /
    ``lte`` / ``in`` / ``in_condition_set``. ``neq`` is NOT supported.

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


def scope_to_privy_rules(scope: Scope, user_address: str) -> list[dict[str, Any]]:
    """Render a Gecko ``Scope`` as a Privy v2 policy ``rules[]`` array.

    Encodes:
      (a) ALLOW interaction with the program behind each granted trade action
          (Kamino KLend / Jupiter v6 / Drift v2);
      (b) ALLOW SPL + native-SOL transfers ONLY when the destination ``eq``s
          ``user_address`` (the scope's own withdraw allowlist is the user's
          address — see ``user_scope``).

    Non-self transfers are denied by Privy **deny-by-default** (no ALLOW rule
    matches them), NOT by an explicit DENY — the original ``neq`` DENY rules are
    invalid on the live Solana validator and have been removed. See the module
    docstring "ENFORCEMENT MODEL — DENY-BY-DEFAULT" + the mandatory L2 devnet
    verification note.

    Pure — no I/O. The result is consumed verbatim by
    ``PrivyClient.create_policy(rules=...)`` in Task 2.2.

    Raises ``ValueError`` if the scope's ``withdraw_allowlist`` is anything other
    than exactly ``{user_address}`` — we refuse to emit a policy that could
    permit an arbitrary withdrawal (fail closed, never widen the allowlist).
    This fail-closed guard is now the ONLY thing (together with deny-by-default)
    standing between a granted scope and an arbitrary-destination withdrawal, so
    it MUST NOT be relaxed.
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

    # (b) withdraw-to-self ALLOW. Non-self transfers fall through to Privy's
    # deny-by-default — there is intentionally NO explicit non-self DENY rule
    # (neq is unsupported on the live Solana validator). The self-pinned eq
    # ALLOW above is the whole positive surface; everything else is denied.
    rules.extend(_self_transfer_allow_rules(user_address))

    return rules


__all__ = [
    "DRIFT_V2_PROGRAM_ID",
    "JUPITER_V6_PROGRAM_ID",
    "KLEND_PROGRAM_ID",
    "TRADE_ACTION_PROGRAM_IDS",
    "scope_to_privy_rules",
]
