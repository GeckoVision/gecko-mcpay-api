"""Tests for ``scripts/trading_oracle/probe_service.py``.

Per ``feedback_lighter_tests``: pure helpers + a single end-to-end
``--dry`` exercise. No real HTTP — ``dry_probe`` is monkeypatched to a
fake. No paid path (operator-fired manually).
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

# Load the probe script as a module — same pattern as
# ``tests/scripts/dex/test_seed_corpus.py``.
_SCRIPT_PATH = (
    Path(__file__).resolve().parents[3] / "scripts" / "trading_oracle" / "probe_service.py"
)
_spec = importlib.util.spec_from_file_location("trading_oracle_probe", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
probe_mod = importlib.util.module_from_spec(_spec)
sys.modules["trading_oracle_probe"] = probe_mod
_spec.loader.exec_module(probe_mod)


def _write_listings(tmp_path: Path) -> Path:
    listings = [
        {
            "name": "Exa",
            "description": "Exa /contents endpoint",
            "tags": ["solana", "search"],
            "price_usd": "0.0",
            "provider_kind": "paysh_live",
            "fqn": "exa-ai",
            "service_url": "https://api.exa.ai/contents",
        }
    ]
    p = tmp_path / "listings.json"
    p.write_text(json.dumps(listings))
    return p


def test_find_listing_matches_fqn() -> None:
    listings = [{"fqn": "exa-ai", "name": "Exa", "service_url": "https://x"}]
    assert probe_mod.find_listing(listings, "exa-ai") is listings[0]
    assert probe_mod.find_listing(listings, "EXA-AI") is listings[0]
    assert probe_mod.find_listing(listings, "nope") is None


def test_cache_path_includes_service_and_index(tmp_path: Path) -> None:
    p = probe_mod.cache_path_for("merit-systems/stablecrypto/market-data", 0)
    assert p.name == "merit-systems__stablecrypto__market-data__0.json"
    assert p.parent == probe_mod.CACHE_DIR


def test_dry_probe_writes_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    listings_path = _write_listings(tmp_path)
    cache_dir = tmp_path / "probes"
    monkeypatch.setattr(probe_mod, "CACHE_DIR", cache_dir)

    fake_accepts = [
        {
            "maxAmountRequired": "10000",
            "asset": "USDC",
            "network": "base-mainnet",
            "payTo": "0xabc",
        }
    ]

    async def fake_dry_probe(
        *, url: str, method: str, timeout_seconds: float
    ) -> tuple[int, dict[str, str], list[dict[str, Any]], str]:
        return 402, {"content-type": "application/json"}, fake_accepts, "{}"

    monkeypatch.setattr(probe_mod, "dry_probe", fake_dry_probe)

    runner = CliRunner()
    result = runner.invoke(
        probe_mod.main,
        [
            "exa-ai",
            "--listings-json",
            str(listings_path),
            "--dry",
        ],
    )
    assert result.exit_code == 0, result.output

    cache_file = cache_dir / "exa-ai__0.json"
    assert cache_file.exists(), f"cache not written; output: {result.output}"
    payload = json.loads(cache_file.read_text())
    assert payload["service_id"] == "exa-ai"
    assert payload["endpoint_url"] == "https://api.exa.ai/contents"
    assert payload["method"] == "GET"
    assert payload["status"] == 402
    assert payload["accepts"] == fake_accepts
    assert isinstance(payload["probed_at"], int)
    assert isinstance(payload["headers"], dict)
