"""Spec loader contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from gecko_core.trade_agent.spec import (
    AgentSpec,
    SpecValidationError,
    load_spec,
)


def test_load_spec_from_dict(valid_spec_dict):
    spec = load_spec(valid_spec_dict)
    assert isinstance(spec, AgentSpec)
    assert spec.name == "test-strategy"
    assert spec.version == "0.1.0"
    assert spec.entry.primitive == "buy_dip"
    assert spec.spec_id.startswith("spec_")


def test_load_spec_from_path(tmp_path: Path, valid_spec_dict):
    p = tmp_path / "spec.json"
    p.write_text(json.dumps(valid_spec_dict))
    spec = load_spec(p)
    assert spec.name == "test-strategy"


def test_load_spec_from_json_string(valid_spec_dict):
    spec = load_spec(json.dumps(valid_spec_dict))
    assert spec.entry.params == {"drawdown_pct": 5}


def test_missing_oracle_grounding_rejected(valid_spec_dict):
    valid_spec_dict.pop("oracle_grounding")
    with pytest.raises(SpecValidationError, match="oracle_grounding"):
        load_spec(valid_spec_dict)


def test_missing_required_field_rejected(valid_spec_dict):
    valid_spec_dict.pop("entry")
    with pytest.raises(SpecValidationError):
        load_spec(valid_spec_dict)


def test_invalid_version_string_rejected(valid_spec_dict):
    valid_spec_dict["version"] = "v1"  # not semver triple
    with pytest.raises(SpecValidationError):
        load_spec(valid_spec_dict)


def test_invalid_entry_primitive_rejected(valid_spec_dict):
    valid_spec_dict["entry"]["primitive"] = "not_a_primitive"
    with pytest.raises(SpecValidationError):
        load_spec(valid_spec_dict)


def test_oracle_grounding_empty_rules_rejected(valid_spec_dict):
    valid_spec_dict["oracle_grounding"]["rule_verdicts"] = []
    with pytest.raises(SpecValidationError):
        load_spec(valid_spec_dict)


def test_file_not_found_rejected(tmp_path: Path):
    with pytest.raises(SpecValidationError, match="not found"):
        load_spec(tmp_path / "missing.json")


def test_spec_id_stable_across_loads(valid_spec_dict):
    a = load_spec(valid_spec_dict)
    b = load_spec(dict(valid_spec_dict))
    assert a.spec_id == b.spec_id


def test_version_bump_changes_spec_id(valid_spec_dict):
    a = load_spec(valid_spec_dict)
    valid_spec_dict["version"] = "0.2.0"
    b = load_spec(valid_spec_dict)
    assert a.spec_id != b.spec_id
