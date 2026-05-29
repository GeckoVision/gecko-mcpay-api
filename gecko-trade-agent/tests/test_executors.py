"""Sprint 21 Phase B — tests for the execution-adapter abstraction.

The OKX adapter is real (wraps the actual OnchainOS subprocess client);
the SendAI adapter is a stub raising :class:`SendAINotConfiguredError`
until v0.3.

These tests verify:
  1. ExecutionAdapter Protocol is structurally satisfiable by both
     adapters.
  2. SwapAttempt + SwapOutcome model the contract correctly.
  3. OKX adapter correctly translates SwapAttempt → OnchainOS call →
     SwapOutcome (via a fake OnchainOS that records inputs).
  4. SendAI adapter constructs cleanly (so the bot doesn't crash on
     import even when SendAI isn't configured) but RAISES on swap()
     with an actionable message.
  5. The OKX adapter's slippage_bps → slippage-fraction translation
     is correct (10000 bps = 1.0 fraction).
  6. The OKX adapter handles upstream exceptions gracefully (returns
     SwapOutcome with ok=False, never crashes the bot).

Light fakes only — no real CLI invocations, no real network.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# Make the skill importable.
_SKILL_DIR = Path(__file__).resolve().parents[1]
if str(_SKILL_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILL_DIR))

from executors import (  # noqa: E402
    ExecutionAdapter,
    OKXExecutor,
    SendAIExecutor,
    SendAINotConfiguredError,
    SwapAttempt,
    SwapOutcome,
)

# ── Light fake for OnchainOS ───────────────────────────────────────────


@dataclass
class _FakeSwapResult:
    """Mirror of OnchainOS.SwapResult — duck-typed for the adapter."""

    ok: bool = True
    tx_hash: str = "0xfake"
    error: str = ""
    from_token: str = ""
    to_token: str = ""
    amount: str = ""
    to_amount_raw: str = "12345"
    to_decimals: int = 6


class _FakeOnchainOS:
    """Records swap_execute calls + returns a configurable SwapResult."""

    def __init__(self, result: _FakeSwapResult | None = None) -> None:
        self._result = result or _FakeSwapResult()
        self.calls: list[dict[str, Any]] = []
        self.should_raise: Exception | None = None

    def swap_execute(
        self,
        from_token: str,
        to_token: str,
        readable_amount: str,
        wallet: str,
        slippage: float | None = None,
        mev_protection: bool = False,
    ) -> _FakeSwapResult:
        self.calls.append(
            {
                "from_token": from_token,
                "to_token": to_token,
                "readable_amount": readable_amount,
                "wallet": wallet,
                "slippage": slippage,
                "mev_protection": mev_protection,
            }
        )
        if self.should_raise is not None:
            raise self.should_raise
        # Populate the from/to tokens so adapter can pass through.
        self._result.from_token = from_token
        self._result.to_token = to_token
        self._result.amount = readable_amount
        return self._result


# ── Protocol conformance ───────────────────────────────────────────────


def test_okx_executor_satisfies_protocol() -> None:
    """The OKX adapter is structurally an ExecutionAdapter."""
    fake = _FakeOnchainOS()
    executor = OKXExecutor(client=fake)
    assert isinstance(executor, ExecutionAdapter)
    assert executor.venue_name == "okx"


def test_sendai_executor_satisfies_protocol() -> None:
    """The SendAI adapter satisfies the contract even as a stub."""
    executor = SendAIExecutor(api_key="placeholder")
    assert isinstance(executor, ExecutionAdapter)
    assert executor.venue_name == "sendai"


# ── SwapAttempt / SwapOutcome shape ────────────────────────────────────


def test_swap_attempt_rejects_unknown_fields() -> None:
    """extra='forbid' on SwapAttempt catches typos at construction time."""
    with pytest.raises(Exception):
        SwapAttempt(
            from_token="A",
            to_token="B",
            readable_amount="45",
            wallet="W",
            typo_field=123,  # type: ignore[call-arg]
        )


def test_swap_attempt_clamps_slippage_to_bps_range() -> None:
    """slippage_bps is in [0, 10_000] — pydantic enforces."""
    with pytest.raises(Exception):
        SwapAttempt(
            from_token="A",
            to_token="B",
            readable_amount="45",
            wallet="W",
            slippage_bps=20_000,
        )


# ── OKX adapter behavior ───────────────────────────────────────────────


def test_okx_adapter_translates_attempt_to_onchainos_call() -> None:
    """SwapAttempt fields land on the OnchainOS swap_execute call."""
    fake = _FakeOnchainOS()
    executor = OKXExecutor(client=fake)
    attempt = SwapAttempt(
        from_token="USDC_MINT",
        to_token="JTO_MINT",
        readable_amount="45",
        wallet="WALLET_ADDR",
        slippage_bps=50,  # 0.5%
    )
    outcome = executor.swap(attempt)

    assert outcome.ok is True
    assert outcome.venue == "okx"
    assert outcome.tx_hash == "0xfake"
    assert outcome.to_amount_raw == "12345"
    assert outcome.to_decimals == 6

    # The fake recorded the translated call
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["from_token"] == "USDC_MINT"
    assert call["to_token"] == "JTO_MINT"
    assert call["wallet"] == "WALLET_ADDR"
    # 50 bps → 0.005 fraction (10_000 bps = 1.0)
    assert call["slippage"] == pytest.approx(0.005)


def test_okx_adapter_passes_mev_protection_through_venue_options() -> None:
    """venue_options['mev_protection'] reaches the OnchainOS call."""
    fake = _FakeOnchainOS()
    executor = OKXExecutor(client=fake)
    attempt = SwapAttempt(
        from_token="A",
        to_token="B",
        readable_amount="10",
        wallet="W",
        venue_options={"mev_protection": True},
    )
    executor.swap(attempt)
    assert fake.calls[0]["mev_protection"] is True


def test_okx_adapter_defaults_slippage_to_none_when_unset() -> None:
    """No slippage_bps in attempt → adapter passes None (venue default)."""
    fake = _FakeOnchainOS()
    executor = OKXExecutor(client=fake)
    attempt = SwapAttempt(from_token="A", to_token="B", readable_amount="10", wallet="W")
    executor.swap(attempt)
    assert fake.calls[0]["slippage"] is None


def test_okx_adapter_handles_upstream_exception() -> None:
    """OnchainOS raising → adapter returns ok=False, never crashes."""
    fake = _FakeOnchainOS()
    fake.should_raise = TimeoutError("CLI timeout after 30s")
    executor = OKXExecutor(client=fake)
    attempt = SwapAttempt(from_token="A", to_token="B", readable_amount="10", wallet="W")
    outcome = executor.swap(attempt)
    assert outcome.ok is False
    assert outcome.venue == "okx"
    assert "TimeoutError" in outcome.error
    assert "CLI timeout" in outcome.error
    # Outcome still carries the attempt fields so callers can log it.
    assert outcome.from_token == "A"
    assert outcome.to_token == "B"


def test_okx_adapter_records_elapsed_ms() -> None:
    """Latency observability — adapter measures HTTP/CLI round-trip."""
    fake = _FakeOnchainOS()
    executor = OKXExecutor(client=fake)
    attempt = SwapAttempt(from_token="A", to_token="B", readable_amount="10", wallet="W")
    outcome = executor.swap(attempt)
    assert outcome.elapsed_ms is not None
    assert outcome.elapsed_ms >= 0


# ── SendAI stub behavior ───────────────────────────────────────────────


def test_sendai_adapter_constructs_without_credentials() -> None:
    """SendAIExecutor() does NOT validate credentials at construction —
    that's why bot.py importing this never crashes even when SendAI
    isn't configured. The validation happens on swap() call.
    """
    executor = SendAIExecutor()  # no kwargs, no env
    assert executor.venue_name == "sendai"


def test_sendai_adapter_raises_on_swap_with_actionable_message() -> None:
    """Loud failure is the right UX for a venue that isn't wired yet."""
    executor = SendAIExecutor(api_key="placeholder")
    attempt = SwapAttempt(from_token="A", to_token="B", readable_amount="10", wallet="W")
    with pytest.raises(SendAINotConfiguredError) as exc_info:
        executor.swap(attempt)
    # Message must carry the migration path so the user knows what to do
    msg = str(exc_info.value)
    assert "v0.3" in msg
    assert "EXECUTION_ADAPTER=okx" in msg


def test_sendai_adapter_reads_env_when_constructed_without_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SENDAI_API_KEY in env is picked up automatically — saves the
    caller from threading env-var reads through bot.py."""
    monkeypatch.setenv("SENDAI_API_KEY", "env-supplied-key")
    monkeypatch.setenv("SENDAI_RPC_URL", "https://env-rpc.example")
    executor = SendAIExecutor()
    # Stub still raises on swap(), but the construction picked up env values
    assert executor._api_key == "env-supplied-key"
    assert executor._rpc_url == "https://env-rpc.example"


# ── SwapOutcome shape ──────────────────────────────────────────────────


def test_swap_outcome_serializes_round_trip() -> None:
    """Wire shape stays intact through model_dump / model_validate."""
    o = SwapOutcome(
        ok=True,
        venue="okx",
        tx_hash="0xabc",
        from_token="USDC",
        to_token="JTO",
        readable_amount="45",
        to_amount_raw="123456789",
        to_decimals=6,
        elapsed_ms=1450,
    )
    dumped = o.model_dump()
    rebuilt = SwapOutcome.model_validate(dumped)
    assert rebuilt.tx_hash == "0xabc"
    assert rebuilt.to_amount_raw == "123456789"
    assert rebuilt.elapsed_ms == 1450
