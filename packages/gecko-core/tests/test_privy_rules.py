"""Contract tests for `scope_to_privy_rules` (V1 Phase 2, Task 2.1).

Pure-function tests — NO network, NO Privy client. We assert directly on the
returned rule dicts. The sacred non-custodial invariant under test:

    The ONLY permitted transfer/withdraw destination is the user's OWN address.
    Any transfer to a non-allowlisted destination MUST be denied.

Grounded against the LIVE Privy v2 policy schema (verified 2026-06-09):
  * rule  = {name, method, conditions[], action in {ALLOW, DENY}}
  * cond  = {field_source, field, operator, value}
  * Solana field_sources: solana_program_instruction(programId),
    solana_token_program_instruction(Transfer.destination),
    solana_system_program_instruction(Transfer.to).
  * Solana-supported operators: {eq, gt, gte, lt, lte, in, in_condition_set}.
    `neq` is REJECTED on the wire — so non-self transfers are denied by Privy
    DENY-BY-DEFAULT (no eq-self ALLOW matches them), NOT by an explicit DENY.
"""

from __future__ import annotations

from typing import Any

import pytest
from gecko_core.wallets.privy_rules import (
    DRIFT_V2_PROGRAM_ID,
    JUPITER_V6_PROGRAM_ID,
    KLEND_PROGRAM_ID,
    TRADE_ACTION_PROGRAM_IDS,
    scope_to_privy_rules,
)
from gecko_core.wallets.provider import TRADE_ONLY_ACTIONS, Scope, user_scope

# A non-real, non-secret base58-shaped placeholder for the user's own address.
USER_ADDRESS = "GeckoUser1111111111111111111111111111111111"
# A different placeholder standing in for "some other wallet" (attacker / drain).
OTHER_ADDRESS = "Attacker22222222222222222222222222222222222"

# The ONLY operators Privy's live Solana condition validator accepts. `neq` is
# deliberately absent — emitting it 400s the policy create on the real API.
ALLOWED_SOLANA_OPERATORS = frozenset({"eq", "gt", "gte", "lt", "lte", "in", "in_condition_set"})


def _conditions(rule: dict[str, Any]) -> list[dict[str, Any]]:
    return rule.get("conditions", [])


def _allow_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rules if r["action"] == "ALLOW"]


def _deny_rules(rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rules if r["action"] == "DENY"]


def _program_allow_values(rules: list[dict[str, Any]]) -> set[str]:
    """Every programId an ALLOW rule whitelists."""
    out: set[str] = set()
    for r in _allow_rules(rules):
        for c in _conditions(r):
            if c["field_source"] == "solana_program_instruction" and c["field"] == "programId":
                v = c["value"]
                if isinstance(v, list):
                    out.update(v)
                else:
                    out.add(v)
    return out


def _is_transfer_dest_condition(c: dict[str, Any]) -> bool:
    """True for a condition that constrains a SOL or SPL transfer destination."""
    return (
        c["field_source"] == "solana_token_program_instruction"
        and c["field"] == "Transfer.destination"
    ) or (c["field_source"] == "solana_system_program_instruction" and c["field"] == "Transfer.to")


# ---------------------------------------------------------------------------
# Shape / wellformedness
# ---------------------------------------------------------------------------


def test_returns_list_of_wellformed_rule_dicts() -> None:
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)
    assert isinstance(rules, list)
    assert rules, "must produce at least one rule"
    for r in rules:
        assert set(("name", "method", "conditions", "action")) <= set(r.keys())
        assert r["action"] in ("ALLOW", "DENY")
        assert isinstance(r["conditions"], list)
        for c in r["conditions"]:
            assert set(("field_source", "field", "operator", "value")) <= set(c.keys())


# ---------------------------------------------------------------------------
# (a) Trade actions are allowed (program interactions)
# ---------------------------------------------------------------------------


def test_trade_actions_allow_their_programs() -> None:
    scope = user_scope(USER_ADDRESS)  # allows all TRADE_ONLY_ACTIONS
    rules = scope_to_privy_rules(scope, USER_ADDRESS)
    allowed_programs = _program_allow_values(rules)
    # Every program backing a granted trade action must be allow-listed.
    for action in TRADE_ONLY_ACTIONS:
        prog = TRADE_ACTION_PROGRAM_IDS[action]
        assert prog in allowed_programs, f"{action} -> {prog} not allowed"
    # Sanity: the three canonical mainnet programs are present.
    assert KLEND_PROGRAM_ID in allowed_programs
    assert JUPITER_V6_PROGRAM_ID in allowed_programs
    assert DRIFT_V2_PROGRAM_ID in allowed_programs


def test_unscoped_trade_action_program_not_allowed() -> None:
    # A scope granting ONLY jupiter_swap must not allow Kamino/Drift programs.
    scope = user_scope(USER_ADDRESS, actions=frozenset({"jupiter_swap"}))
    rules = scope_to_privy_rules(scope, USER_ADDRESS)
    allowed_programs = _program_allow_values(rules)
    assert JUPITER_V6_PROGRAM_ID in allowed_programs
    assert KLEND_PROGRAM_ID not in allowed_programs
    assert DRIFT_V2_PROGRAM_ID not in allowed_programs


# ---------------------------------------------------------------------------
# (b) Transfer/withdraw destination is locked to the user's own address
# ---------------------------------------------------------------------------


def test_transfer_destination_is_pinned_to_user_address() -> None:
    """There must be an ALLOW rule whose transfer-destination condition pins the
    destination to exactly user_address (and to no other value)."""
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)

    pinned_values: set[str] = set()
    for r in _allow_rules(rules):
        for c in _conditions(r):
            if _is_transfer_dest_condition(c):
                assert c["operator"] == "eq", "destination allow must be an equality pin"
                pinned_values.add(c["value"])

    assert pinned_values, "no ALLOW rule constrains the transfer destination"
    # The ONLY destination any transfer ALLOW pins is the user's own address.
    assert pinned_values == {USER_ADDRESS}


def test_no_neq_deny_rules_emitted() -> None:
    """The corrected wire shape carries NO `neq` rules at all.

    Privy's live Solana validator rejects `neq` (400 invalid_policy_format), so
    the old belt-and-suspenders DENY rules were removed. Non-self transfers are
    now denied by deny-by-default, not by an explicit DENY. Assert there is no
    DENY transfer rule and no condition anywhere uses the `neq` operator.
    """
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)

    # No DENY rule constrains a transfer destination anymore.
    for r in _deny_rules(rules):
        for c in _conditions(r):
            assert not _is_transfer_dest_condition(c), (
                "explicit non-self transfer DENY must be gone"
            )

    # No condition anywhere uses `neq`.
    for r in rules:
        for c in _conditions(r):
            assert c["operator"] != "neq", f"`neq` operator emitted in rule {r['name']!r}"


def test_every_operator_is_in_the_supported_solana_set() -> None:
    """Hard wire-conformance guard: every operator the mapper emits must be in
    Privy's allowed Solana operator set. This is the Pattern-C check that would
    have caught the `neq` bug before the live run."""
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)
    for r in rules:
        for c in _conditions(r):
            assert c["operator"] in ALLOWED_SOLANA_OPERATORS, (
                f"operator {c['operator']!r} in rule {r['name']!r} is not a "
                f"Privy-supported Solana operator {sorted(ALLOWED_SOLANA_OPERATORS)}"
            )


def test_no_rule_allows_a_non_self_destination() -> None:
    """The hard invariant: NO ALLOW rule anywhere whitelists OTHER_ADDRESS as a
    transfer destination, and no transfer-destination value other than the
    user's own address is ever ALLOWed."""
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)

    for r in _allow_rules(rules):
        for c in _conditions(r):
            if _is_transfer_dest_condition(c):
                assert c["operator"] == "eq"
                assert c["value"] == USER_ADDRESS
                assert c["value"] != OTHER_ADDRESS


def test_self_withdrawal_is_permitted() -> None:
    """Withdrawal to the user's OWN address is always allowed (sacred, never
    kill-switch-gated) — i.e. user_address is an allowed transfer destination."""
    scope = user_scope(USER_ADDRESS)
    rules = scope_to_privy_rules(scope, USER_ADDRESS)

    self_allowed = any(
        _is_transfer_dest_condition(c) and c["operator"] == "eq" and c["value"] == USER_ADDRESS
        for r in _allow_rules(rules)
        for c in _conditions(r)
    )
    assert self_allowed, "withdrawal to the user's own address must be permitted"


def test_fail_closed_on_widened_allowlist() -> None:
    """The fail-closed guard is now the ONLY thing (with deny-by-default) gating
    an arbitrary-destination withdrawal — it MUST still raise if the scope's
    withdraw_allowlist is anything other than exactly {user_address}."""
    widened = Scope(
        allowed_actions=TRADE_ONLY_ACTIONS,
        withdraw_allowlist=frozenset({USER_ADDRESS, OTHER_ADDRESS}),
    )
    with pytest.raises(ValueError, match="withdraw_allowlist must be exactly"):
        scope_to_privy_rules(widened, USER_ADDRESS)

    # Even a SINGLE foreign address (not the user's own) must fail closed.
    foreign_only = Scope(
        allowed_actions=TRADE_ONLY_ACTIONS,
        withdraw_allowlist=frozenset({OTHER_ADDRESS}),
    )
    with pytest.raises(ValueError, match="withdraw_allowlist must be exactly"):
        scope_to_privy_rules(foreign_only, USER_ADDRESS)


def test_allowlist_drawn_from_scope_not_hardcoded() -> None:
    """The pinned destination follows the scope's withdraw_allowlist, proving it
    is the user's address and not a constant."""
    other_user = "OtherUser3333333333333333333333333333333333"
    scope = user_scope(other_user)
    rules = scope_to_privy_rules(scope, other_user)
    pinned = {
        c["value"]
        for r in _allow_rules(rules)
        for c in _conditions(r)
        if _is_transfer_dest_condition(c)
    }
    assert pinned == {other_user}
    assert USER_ADDRESS not in pinned
