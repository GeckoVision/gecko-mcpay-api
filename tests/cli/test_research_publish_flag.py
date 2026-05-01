"""S14-PUB-01 — `bb research --publish` opt-in to publish.new.

Verifies:
  * `--publish` triggers a publish.new artifact upload after the verdict.
  * Stub mode short-circuits to `stub://publish.new/<slug>` and surfaces
    the receipt block.
  * Without `--publish`, no publish call is made.
  * `--publish-price` and `--publish-as` overrides thread through.
  * PublishNewError surfaces a clean message and does not crash the run.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from click.testing import CliRunner


def _fake_result() -> Any:
    from gecko_core.models import ResearchResult

    return ResearchResult.model_validate(
        {
            "session_id": "11111111-1111-1111-1111-111111111111",
            "tier": "basic",
            "business_plan": {
                "problem": "p",
                "icp": "i",
                "solution": "s",
                "market": "m",
                "business_model": "bm",
                "channels": "c",
                "risks": ["r1"],
                "citations": [],
            },
            "validation_report": {
                "market_size_signal": "msig",
                "competitor_analysis": "ca",
                "demand_evidence": "de",
                "risk_flags": [],
                "citations": [],
            },
            "prd": {
                "v1_scope": ["v1"],
                "v2_scope": [],
                "v3_scope": [],
                "acceptance_criteria": ["ac"],
                "non_functional": [],
                "success_metrics": [],
                "citations": [],
            },
            "sources": [
                {
                    "url": "https://example.com/a",
                    "type": "web",
                    "chunk_count": 3,
                    "indexed_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
    )


_VALID_BASE = "0x" + "a" * 40


@pytest.fixture
def patched_research(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    captured: dict[str, Any] = {}

    async def _fake_research(**kwargs: Any) -> Any:
        captured.update(kwargs)
        return _fake_result()

    import gecko_core
    from gecko_cli.commands import research as research_module

    monkeypatch.setattr(gecko_core, "research", _fake_research)
    monkeypatch.setattr(research_module.gecko_core, "research", _fake_research)
    monkeypatch.setattr(research_module, "resolve_project_id", lambda *_a, **_k: None)
    return captured


def test_publish_flag_emits_stub_url(
    patched_research: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.setenv("GECKO_WALLET_ADDRESS_BASE", _VALID_BASE)
    from gecko_core.payments.x402_client import _settings

    _settings.cache_clear()

    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "stub idea", "--yes", "--publish"],
        input="",
        catch_exceptions=False,
    )
    _settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "Published" in result.output
    assert "stub://publish.new/" in result.output


def test_no_publish_flag_skips_publish(
    patched_research: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.setenv("GECKO_WALLET_ADDRESS_BASE", _VALID_BASE)
    from gecko_core.payments.x402_client import _settings

    _settings.cache_clear()

    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "stub idea", "--yes"],
        input="",
        catch_exceptions=False,
    )
    _settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert "Published" not in result.output
    assert "publish.new" not in result.output


def test_publish_missing_address_surfaces_error_no_crash(
    patched_research: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("X402_MODE", "stub")
    # The CLI's click callback re-loads the project .env via find_dotenv,
    # which re-injects GECKO_WALLET_ADDRESS_BASE. Stub publish_artifact
    # directly to assert the error-surface contract.
    from gecko_core.payments.x402_client import _settings

    _settings.cache_clear()

    import gecko_core.payments.publish_new as pn_mod
    from gecko_core.payments.publish_new import PublishNewError

    async def _raise(**_kwargs: Any) -> Any:
        raise PublishNewError(
            "publish.new requires a Base 0x author address — set "
            "GECKO_WALLET_ADDRESS_BASE or pass --publish-as 0x..., or run "
            "`bb wallet add publish-new` to bootstrap one."
        )

    monkeypatch.setattr(pn_mod, "publish_artifact", _raise)

    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "x", "--yes", "--publish"],
        input="",
        catch_exceptions=False,
    )
    _settings.cache_clear()

    # The CLI should NOT crash; the error renders as a red one-liner.
    assert result.exit_code == 0, result.output
    assert "publish.new error" in result.output
    # Rich may wrap the error message across lines; collapse whitespace before
    # asserting the actionable phrase is present.
    collapsed = " ".join(result.output.split())
    assert "bb wallet add publish-new" in collapsed


def test_publish_invalid_price_rejected(
    patched_research: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gecko_cli.main import cli

    runner = CliRunner()
    result = runner.invoke(
        cli,
        ["research", "--idea", "x", "--yes", "--publish", "--publish-price", "abc"],
        input="",
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "publish-price" in result.output.lower()


def test_publish_overrides_thread_through(
    patched_research: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI passes --publish-price + --publish-as to publish_artifact."""
    monkeypatch.setenv("X402_MODE", "stub")
    monkeypatch.delenv("GECKO_WALLET_ADDRESS_BASE", raising=False)
    from gecko_core.payments.x402_client import _settings

    _settings.cache_clear()

    captured: dict[str, Any] = {}

    async def _fake_publish(**kwargs: Any) -> Any:
        captured.update(kwargs)
        from gecko_core.payments.publish_new import PublishNewArtifact

        return PublishNewArtifact(
            url="stub://publish.new/foo",
            slug="foo",
            price_usd=kwargs.get("price_usd") or Decimal("0.50"),
            author_address=kwargs.get("author_address") or "0x" + "1" * 40,
            tx_signature=None,
            is_stub=True,
        )

    import gecko_core.payments.publish_new as pn_mod

    monkeypatch.setattr(pn_mod, "publish_artifact", _fake_publish)

    from gecko_cli.main import cli

    runner = CliRunner()
    other_addr = "0x" + "1" * 40
    result = runner.invoke(
        cli,
        [
            "research",
            "--idea",
            "x",
            "--yes",
            "--publish",
            "--publish-price",
            "0.10",
            "--publish-as",
            other_addr,
        ],
        input="",
        catch_exceptions=False,
    )
    _settings.cache_clear()

    assert result.exit_code == 0, result.output
    assert captured.get("price_usd") == Decimal("0.10")
    assert captured.get("author_address") == other_addr
