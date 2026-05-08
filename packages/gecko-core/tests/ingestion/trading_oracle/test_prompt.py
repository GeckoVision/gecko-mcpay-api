import pytest
from gecko_core.ingestion.trading_oracle.prompt import (
    SOLANA_DEFI_PROTOCOLS,
    TRADING_ORACLE_PROMPT,
    TRADING_ORACLE_PROTOCOLS_V1,
    is_solana_defi_relevant,
    prompt_for_protocol,
)


def test_prompt_mentions_each_protocol():
    for proto in SOLANA_DEFI_PROTOCOLS:
        assert proto.lower() in TRADING_ORACLE_PROMPT.lower(), proto


def test_prompt_does_not_recommend_buy_sell():
    forbidden = ["buy ", "sell ", "long ", "short "]
    body = TRADING_ORACLE_PROMPT.lower()
    for v in forbidden:
        assert v not in body, f"prompt must not contain trade verb {v!r}"


def test_filter_accepts_solana_defi():
    assert (
        is_solana_defi_relevant(
            {
                "name": "Kamino Lend Snapshot",
                "description": "Daily TVL + APY for Kamino USDC reserves on Solana",
                "tags": ["solana", "lending", "kamino"],
            }
        )
        is True
    )


def test_filter_rejects_unrelated():
    assert (
        is_solana_defi_relevant(
            {
                "name": "Hotel Booking API",
                "description": "Search hotels via Ctrip",
                "tags": ["travel"],
            }
        )
        is False
    )


def test_filter_rejects_evm_only():
    assert (
        is_solana_defi_relevant(
            {
                "name": "Aave V3 USDC",
                "description": "Ethereum mainnet lending rate",
                "tags": ["ethereum", "defi", "aave"],
            }
        )
        is False
    )


def test_filter_rejects_email_service():
    """AgentMail-style listing — paysh email service that substring-matches
    "oracle" via vendor description. Should reject regardless of solana tag."""
    assert (
        is_solana_defi_relevant(
            {
                "name": "AgentMail",
                "description": "Email inbox + SMTP for agents",
                "tags": ["solana"],
            }
        )
        is False
    )


def test_filter_accepts_perplexity_via_allowlist():
    assert (
        is_solana_defi_relevant(
            {
                "name": "Perplexity",
                "fqn": "docs-perplexity-ai",
                "description": "AI search and reasoning",
                "tags": ["base", "ai"],  # no solana token, no defi token
            }
        )
        is True
    )


def test_filter_accepts_claude_via_allowlist():
    assert (
        is_solana_defi_relevant(
            {
                "name": "Claude",
                "fqn": "docs-anthropic-com",
                "description": "Anthropic models",
                "tags": ["base"],
            }
        )
        is True
    )


def test_filter_rejects_air_quality():
    """Air Quality API — paysh environmental data tagged with "oracle" but
    irrelevant to Solana DeFi. Should reject before the DeFi-token path."""
    assert (
        is_solana_defi_relevant(
            {
                "name": "Air Quality API",
                "description": "AQI readings by city",
                "tags": ["solana", "oracle"],
            }
        )
        is False
    )


def test_prompt_for_protocol_names_one_protocol():
    body = prompt_for_protocol("Kamino")
    assert "Kamino" in body
    # Should NOT mention the other 9 protocols since this is single-scoped
    for other in [
        "Jupiter",
        "Jito",
        "Pyth",
        "Drift",
        "Orca",
        "Raydium",
        "Meteora",
        "MarginFi",
        "Sanctum",
    ]:
        assert other not in body, f"prompt_for_protocol('Kamino') leaked {other}"


def test_prompt_for_protocol_rejects_empty():
    with pytest.raises(ValueError):
        prompt_for_protocol("")


def test_prompt_for_protocol_works_for_all_v1_protocols():
    for p in TRADING_ORACLE_PROTOCOLS_V1:
        body = prompt_for_protocol(p)
        assert p in body
        assert len(body) > 100  # rough sanity
