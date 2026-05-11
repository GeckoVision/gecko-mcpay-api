"""AgentSpec — load + validate a coach-emitted strategy JSON.

The strategy spec schema is the canonical contract published by the
``gecko-trade-coach`` skill at
``gecko-claude/.claude/skills/gecko-trade-coach/schema.json``. The runtime
treats the spec as the immutable source of truth for an agent's behaviour
during one *spec_version*; mid-flight edits go through the hot-swap path
in :mod:`.runtime`, never an in-place mutation.

Per SE-1 design notes (`docs/strategy/2026-05-11-trade-vertical-expansion.md` §3):

* JSON-Schema validation is mandatory; missing ``oracle_grounding`` is the
  load-bearing check (the wedge is verdict-grounding — a spec without it
  is by definition invalid).
* Returns a typed Pydantic model; consumers must never see the raw dict.
* Errors are typed (:class:`SpecValidationError`) — never raise bare
  ``Exception`` (CLAUDE.md style rule).

We intentionally do NOT pin a ``jsonschema`` dep. The schema file is the
documentation contract; the structural checks here cover the required
fields + enum constraints relevant to runtime dispatch. If a schema-drift
test catches divergence later, we can add ``jsonschema`` as a hard dep.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

logger = logging.getLogger(__name__)


class SpecValidationError(Exception):
    """Raised when a coach-emitted spec fails to load or validate."""


# Mirror the enums in schema.json. Single source of truth for runtime
# dispatch; the JSON-Schema file is the public contract.
EntryPrimitive = Literal[
    "dca", "buy_dip", "momentum_follow", "smart_money_copy", "snipe_new", "grid"
]
ExitPrimitive = Literal[
    "take_profit", "trailing_stop", "time_based", "verdict_flip", "drawdown_stop"
]
SizingPrimitive = Literal[
    "fixed_usd", "percent_bankroll", "kelly_fraction", "verdict_confidence_scaled"
]
ExecutionRail = Literal["okx-agentic-wallet", "sendai", "backpack", "spec-only"]
Vertical = Literal["dex"]
RuleVerdict = Literal["act", "pass", "defer"]


class _PrimitiveBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    primitive: str
    params: dict[str, Any] = Field(default_factory=dict)
    rule_id: str | None = None


class EntryBlock(_PrimitiveBlock):
    primitive: EntryPrimitive  # type: ignore[assignment]


class ExitBlock(_PrimitiveBlock):
    primitive: ExitPrimitive  # type: ignore[assignment]


class SizingBlock(_PrimitiveBlock):
    primitive: SizingPrimitive  # type: ignore[assignment]


class FilterBlock(BaseModel):
    model_config = ConfigDict(extra="allow")
    min_liquidity_usd: float | None = None
    max_holder_concentration_pct: float | None = None
    require_oracle_act: bool = True
    block_honeypot: bool = True


class RiskBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_concurrent_positions: int = Field(ge=1, le=20)
    max_single_position_pct: float = Field(ge=0, le=100)
    max_daily_loss_pct: float = Field(ge=0, le=100)
    circuit_breaker_on_dissent_strength: float | None = Field(default=None, ge=0, le=1)


class RuleVerdictRecord(BaseModel):
    model_config = ConfigDict(extra="allow")
    rule_id: str
    verdict_id: str
    verdict: RuleVerdict
    confidence: float | None = None
    citations: list[str] = Field(default_factory=list)
    dissent_id: str | None = None
    acknowledged_by_user: bool | None = None


class OracleGrounding(BaseModel):
    model_config = ConfigDict(extra="allow")
    tool: Literal["gecko_trade_research"]
    rule_verdicts: list[RuleVerdictRecord] = Field(min_length=1)
    session_verdict_id: str | None = None
    session_tier: Literal["basic", "pro"] | None = None


class AgentSpec(BaseModel):
    """Validated, typed view of a coach-emitted strategy spec."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(min_length=1, max_length=80)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    vertical: Vertical
    protocol: str
    chain: str | None = None
    entry: EntryBlock
    exit: ExitBlock
    sizing: SizingBlock
    filter: FilterBlock | None = None
    risk: RiskBlock
    oracle_grounding: OracleGrounding
    execution_rail: ExecutionRail | None = None
    author: dict[str, Any] | None = None
    backtest: dict[str, Any] | None = None
    paper_trade: dict[str, Any] | None = None
    published: dict[str, Any] | None = None

    @field_validator("oracle_grounding")
    @classmethod
    def _require_at_least_one_rule(cls, v: OracleGrounding) -> OracleGrounding:
        # Redundant with min_length=1 above — explicit for readability.
        if not v.rule_verdicts:
            raise ValueError("oracle_grounding.rule_verdicts must be non-empty")
        return v

    @property
    def spec_id(self) -> str:
        """Stable identifier — hash of (name, version) so a re-load of
        the same logical spec produces the same id, but a version bump
        produces a new id (hot-swap pivots on this).
        """
        h = hashlib.sha256(f"{self.name}@{self.version}".encode()).hexdigest()
        return f"spec_{h[:16]}"

    def fingerprint(self) -> str:
        """Content fingerprint over the *meaningful* spec body. Used by
        the runtime to detect that two specs sharing (name, version)
        actually diverge (a user-side bug we want to surface, not paper
        over)."""
        body = self.model_dump(exclude={"author", "backtest", "paper_trade", "published"})
        return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()


def load_spec(source: str | Path | dict[str, Any]) -> AgentSpec:
    """Load + validate a strategy spec.

    Accepts a filesystem path (str/Path), a JSON string, or an already
    parsed ``dict``. Raises :class:`SpecValidationError` with a useful
    diagnostic on any failure — file-missing, malformed JSON, schema
    violation.
    """
    raw: Any
    if isinstance(source, dict):
        raw = source
    elif isinstance(source, Path):
        if not source.exists():
            raise SpecValidationError(f"spec file not found: {source}")
        try:
            raw = json.loads(source.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SpecValidationError(f"spec file is not valid JSON: {source} ({exc})") from exc
    else:
        # str — try filesystem first, then JSON literal. ``Path.exists``
        # itself raises ``OSError`` on absurdly long candidates (ENAMETOOLONG)
        # so we guard with a length heuristic before touching the FS.
        as_path: Path | None
        if len(source) <= 4096 and "\n" not in source:
            try:
                as_path = Path(source)
                exists = as_path.exists()
            except OSError:
                as_path = None
                exists = False
        else:
            as_path = None
            exists = False
        if as_path is not None and exists:
            try:
                raw = json.loads(as_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise SpecValidationError(
                    f"spec file is not valid JSON: {as_path} ({exc})"
                ) from exc
        else:
            try:
                raw = json.loads(source)
            except json.JSONDecodeError as exc:
                raise SpecValidationError(
                    f"spec source is neither a file path nor a JSON string: {exc}"
                ) from exc

    if not isinstance(raw, dict):
        raise SpecValidationError(f"spec must decode to a JSON object, got {type(raw).__name__}")

    if "oracle_grounding" not in raw:
        # Load-bearing wedge check — call out explicitly so the error
        # message tells the user WHY we rejected.
        raise SpecValidationError(
            "spec is missing required 'oracle_grounding' block. Every rule "
            "must be grounded by a gecko_trade_research verdict."
        )

    try:
        return AgentSpec.model_validate(raw)
    except ValidationError as exc:
        raise SpecValidationError(f"spec failed schema validation: {exc.errors()}") from exc


__all__ = [
    "AgentSpec",
    "EntryBlock",
    "ExitBlock",
    "FilterBlock",
    "OracleGrounding",
    "RiskBlock",
    "RuleVerdictRecord",
    "SizingBlock",
    "SpecValidationError",
    "load_spec",
]
