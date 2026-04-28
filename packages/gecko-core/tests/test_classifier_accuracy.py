"""Held-out accuracy test for the embedding-NN classifier.

Skips automatically if `OPENAI_API_KEY` is unset — this test makes a real
embedding call (one per held-out idea, ~$0.0001 total at current prices).
For unit-level coverage of the dispatch path, see other tests.
"""

from __future__ import annotations

import os

import pytest
from gecko_core.classify import classify_idea

_OPENAI_KEY = os.getenv("OPENAI_API_KEY")

pytestmark = pytest.mark.skipif(
    not _OPENAI_KEY,
    reason="classifier accuracy test requires a real OPENAI_API_KEY",
)

# 20 held-out ideas + 2 explicit unknowns. None overlap with seeds.json.
HELD_OUT: list[tuple[str, set[str]]] = [
    # crypto (4)
    ("A Solana memecoin sniper bot that auto-buys at launch and sets stop losses", {"crypto"}),
    ("A multi-sig wallet for Solana DAOs with delegated approval thresholds", {"crypto"}),
    ("An on-chain notary using Solana for timestamping legal documents", {"crypto"}),
    ("A SOL airdrop hunting tool that tracks wallet eligibility across protocols", {"crypto"}),
    # defi (3)
    ("A leveraged yield farming aggregator that loops Marinade liquid staking on Kamino", {"defi"}),
    ("A delta-neutral SOL strategy vault using perps on Drift and Mango", {"defi"}),
    (
        "A liquidity bootstrapping pool platform for token launches with Dutch auction pricing",
        {"defi"},
    ),
    # devtools (3)
    (
        "A Python static analyzer that catches missing await on async functions in PR review",
        {"devtools"},
    ),
    ("A git history rewriter that splits accidental megacommits into atomic ones", {"devtools"}),
    ("An LSP plugin that surfaces stale TODOs older than 90 days as warnings", {"devtools"}),
    # saas (3)
    (
        "A recurring billing dashboard for indie SaaS founders with Mercury and Stripe sync",
        {"saas"},
    ),
    ("A help center generator that turns Linear tickets into public FAQ articles", {"saas"}),
    (
        "A B2B onboarding checklist tool for customer success teams handling enterprise contracts",
        {"saas"},
    ),
    # regulated (3)
    (
        "A pharmacy benefits manager portal compliant with HIPAA for self-insured employers",
        {"regulated"},
    ),
    (
        "A SEC-registered crowdfunding platform for accredited investors with Reg D filings",
        {"regulated"},
    ),
    ("A workers' comp claims processor for state insurance funds with audit trails", {"regulated"}),
    # hackathon-team (2)
    (
        "A weekend project partner finder for participants of the Solana Mobile hackathon",
        {"hackathon-team"},
    ),
    (
        "A teammate-search board where ETHGlobal hackers post their stack and time zone",
        {"hackathon-team"},
    ),
    # unknown (2)
    ("A recipe app for cats with weekly meal plans and grocery lists", set()),
    ("A meditation timer app with rain sounds and breathing exercises for anxious users", set()),
]


@pytest.mark.asyncio
async def test_classifier_top1_accuracy() -> None:
    """Top-1 accuracy on held-out, in-domain ideas should be >= 0.70.

    The spec asks for 0.80 but allows tuning down to ~0.55-0.70 if needed —
    we report the actual measured accuracy at the end.
    """
    in_domain = [(idea, expected) for idea, expected in HELD_OUT if expected]
    correct = 0
    misses: list[tuple[str, set[str], set[str]]] = []
    for idea, expected in in_domain:
        predicted = await classify_idea(idea)
        # "Top-1 correct" = the expected single label is in the predicted set.
        # (Multi-label predictions are fine as long as the truth is present.)
        if expected.issubset(predicted) and predicted:
            correct += 1
        else:
            misses.append((idea, expected, predicted))

    accuracy = correct / len(in_domain)
    print(f"\nClassifier top-1 accuracy: {accuracy:.2%} ({correct}/{len(in_domain)})")
    if misses:
        print("Misses:")
        for idea, exp, pred in misses:
            print(f"  expected={exp} predicted={pred} :: {idea[:60]}...")
    assert accuracy >= 0.70, f"top-1 accuracy {accuracy:.2%} below 0.70"


@pytest.mark.asyncio
async def test_classifier_unknowns_return_empty() -> None:
    """Off-domain ideas should classify as empty set (caller falls back
    to the safe baseline source bundle)."""
    unknowns = [idea for idea, expected in HELD_OUT if not expected]
    for idea in unknowns:
        predicted = await classify_idea(idea)
        assert predicted == set(), f"unknown idea got categories {predicted}: {idea}"


@pytest.mark.asyncio
async def test_classifier_multilabel_defi_devtools() -> None:
    """A clearly multi-domain idea (CLI for DEX TVL drift) should pick up
    both `defi` and `devtools` if both clear threshold."""
    idea = "A CLI tool for monitoring Solana DEX TVL drift across Raydium and Orca pools"
    predicted = await classify_idea(idea)
    # We don't strictly require BOTH (depends on threshold tuning), but at
    # least one of the two should hit, and the prediction shouldn't be empty.
    assert predicted, f"multi-domain idea returned empty: {idea}"
    assert predicted & {"defi", "devtools", "crypto"}, (
        f"expected defi/devtools/crypto overlap, got {predicted}"
    )
