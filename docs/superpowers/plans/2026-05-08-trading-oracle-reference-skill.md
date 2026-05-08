# Trading-Oracle Reference Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Claude Code skill that calls Gecko for grounded Solana-DeFi verdicts (corpus from paysh/bazaar live x402 spend) and executes a Kamino-style yield deposit on Solana devnet — proving Gecko = oracle, solana-claude = execution-domain expertise, devnet venue = settlement.

**Architecture:** Three lanes. (1) `gecko-mcpay-api` runs a one-shot live ingest from paysh/bazaar capped at $20 USDC, writing chunks to MongoDB with `vertical=defi-trading`. (2) A new Python `kamino_devnet` adapter ports the prior art from `gecko-social-fi-creators-api/src/services/kamino.service.ts` (`KAMINO_MODE=simulate|devnet`, KTX REST → unsigned base64 tx → sign + submit). (3) `gecko-claude/examples/trading-oracle/` ships a skill that mounts `mcp.geckovision.tech`, installs Superteam Brasil's `solana-claude` for the `defi-engineer` agent, and runs end-to-end: prompt → Gecko verdict → defi-engineer formats Kamino intent → kamino_devnet executes on devnet.

**Tech Stack:** Python 3.11 (`uv`), MongoDB Atlas (Voyage 1024-dim), `solana-py` + `solders` for Kamino devnet, existing `LiveX402Client` for paid ingest, FastMCP for the tool surface, Claude Code skill manifest format for the example.

**Spec:** `docs/superpowers/specs/2026-05-08-trading-oracle-reference-skill-design.md`

**Phase gates:**
- Phase 1 (Tasks 1–5): no mainnet funds needed. Ship in parallel.
- Phase 2 (Task 6): blocked on founder funding `GECKO_BUYER_WALLET` (~$20 USDC, Solana mainnet). One-shot.
- Phase 3 (Tasks 7–8): cross-repo `gecko-claude`. Ships after Task 6.

---

## File Structure

### Created in this repo (`gecko-mcpay-api`)
- `packages/gecko-core/src/gecko_core/ingestion/budget_guard.py` — pure $-cap module.
- `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/__init__.py` — package marker.
- `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/prompt.py` — curated prompt + listing filter.
- `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py` — orchestrator.
- `packages/gecko-core/src/gecko_core/execution/__init__.py` — new sub-package.
- `packages/gecko-core/src/gecko_core/execution/kamino_devnet.py` — port of prior TS service.
- `packages/gecko-core/tests/ingestion/test_budget_guard.py`
- `packages/gecko-core/tests/ingestion/trading_oracle/test_prompt.py`
- `packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py`
- `packages/gecko-core/tests/execution/test_kamino_devnet.py`
- `packages/gecko-core/tests/execution/fixtures/ktx_deposit_response.json`
- `infra/supabase/migrations/20260508130000_chunk_freshness_tier.sql` (Pattern A: SQL `CHECK` mirrors Python literal)

### Modified in this repo
- `packages/gecko-core/src/gecko_core/db/mongo_chunks.py` — accept optional `freshness_tier` on insert.
- `packages/gecko-core/src/gecko_core/sources/types.py` — add `FreshnessTier` literal.
- `packages/gecko-core/tests/test_provider_kind_consistency.py` — mirror schema-drift test for `FreshnessTier`.

### Created in sister repo (`gecko-claude`)
- `examples/trading-oracle/skill.md`
- `examples/trading-oracle/.mcp.json`
- `examples/trading-oracle/example_call.py`
- `examples/trading-oracle/README.md`

---

## Task 1: Budget Guard

**Why:** every paid call must be gated against a hard $20 cap. Pure module = trivial to unit test, no DB or network.

**Files:**
- Create: `packages/gecko-core/src/gecko_core/ingestion/budget_guard.py`
- Test: `packages/gecko-core/tests/ingestion/test_budget_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/gecko-core/tests/ingestion/test_budget_guard.py
from decimal import Decimal
import pytest
from gecko_core.ingestion.budget_guard import BudgetGuard, BudgetExceededError


def test_initial_state():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    assert g.remaining() == Decimal("20.00")
    assert g.spent() == Decimal("0")


def test_can_afford_within_cap():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    assert g.can_afford(Decimal("5.00")) is True


def test_cannot_afford_over_cap():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("18.00"), label="paysh:foo")
    assert g.can_afford(Decimal("5.00")) is False


def test_charge_updates_remaining():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("3.50"), label="bazaar:bar")
    assert g.remaining() == Decimal("16.50")
    assert g.spent() == Decimal("3.50")


def test_charge_over_cap_raises():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("18.00"), label="paysh:foo")
    with pytest.raises(BudgetExceededError):
        g.charge(Decimal("5.00"), label="bazaar:big")


def test_ledger_records_each_charge():
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    g.charge(Decimal("1.00"), label="a")
    g.charge(Decimal("2.00"), label="b")
    assert [(e.amount_usd, e.label) for e in g.ledger()] == [
        (Decimal("1.00"), "a"),
        (Decimal("2.00"), "b"),
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/ingestion/test_budget_guard.py -v`
Expected: FAIL — `ModuleNotFoundError: gecko_core.ingestion.budget_guard`

- [ ] **Step 3: Write the minimal implementation**

```python
# packages/gecko-core/src/gecko_core/ingestion/budget_guard.py
"""Hard USD spend cap for paid x402 ingest runs.

Pure, sync, no I/O. The caller is expected to:
    g = BudgetGuard(cap_usd=Decimal("20.00"))
    if not g.can_afford(price):
        skip
    ...issue the paid call...
    g.charge(actual_price, label="paysh:fqn")

Why a separate module: the prior live-spend incident showed that ad-hoc
spend tracking inside the orchestrator gets ignored under retry pressure.
A pure module that raises on overrun is the only way to make the cap
actually enforce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence


class BudgetExceededError(RuntimeError):
    """Raised when a charge would push spent above cap."""


@dataclass(frozen=True)
class LedgerEntry:
    amount_usd: Decimal
    label: str


@dataclass
class BudgetGuard:
    cap_usd: Decimal
    _ledger: list[LedgerEntry] = field(default_factory=list)

    def spent(self) -> Decimal:
        return sum((e.amount_usd for e in self._ledger), Decimal("0"))

    def remaining(self) -> Decimal:
        return self.cap_usd - self.spent()

    def can_afford(self, price_usd: Decimal) -> bool:
        return price_usd <= self.remaining()

    def charge(self, amount_usd: Decimal, *, label: str) -> None:
        if amount_usd > self.remaining():
            raise BudgetExceededError(
                f"charge ${amount_usd} would exceed cap (remaining ${self.remaining()})"
            )
        self._ledger.append(LedgerEntry(amount_usd=amount_usd, label=label))

    def ledger(self) -> Sequence[LedgerEntry]:
        return tuple(self._ledger)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/gecko-core/tests/ingestion/test_budget_guard.py -v`
Expected: PASS — 6/6.

- [ ] **Step 5: Commit**

```bash
git add packages/gecko-core/src/gecko_core/ingestion/budget_guard.py \
        packages/gecko-core/tests/ingestion/test_budget_guard.py
git commit -m "feat(ingestion): add BudgetGuard for paid-ingest \$ cap enforcement"
```

---

## Task 2: Freshness Tier Schema Delta

**Why:** data-engineer's recommendation (spec §7). Distinguishes `static` (protocol docs, audits) from `daily` (paysh/bazaar paid snapshots) from `live_only` (excluded from vector store entirely). Without this, the corpus rots silently.

**Files:**
- Create: `infra/supabase/migrations/20260508130000_chunk_freshness_tier.sql`
- Modify: `packages/gecko-core/src/gecko_core/sources/types.py`
- Modify: `packages/gecko-core/src/gecko_core/db/mongo_chunks.py`
- Modify: `packages/gecko-core/tests/test_provider_kind_consistency.py`

- [ ] **Step 1: Add the literal (Pattern A: single source of truth)**

In `packages/gecko-core/src/gecko_core/sources/types.py`, add at module bottom (do not redeclare elsewhere):

```python
# --- Freshness tier (Pattern A: SQL CHECK in 20260508130000 mirrors this) ---
FreshnessTier = Literal["static", "daily", "live_only"]
FRESHNESS_TIER_VALUES: tuple[FreshnessTier, ...] = ("static", "daily", "live_only")
```

- [ ] **Step 2: Write the failing schema-drift test**

In `packages/gecko-core/tests/test_provider_kind_consistency.py`, append:

```python
def test_freshness_tier_values_match_sql_check() -> None:
    """Pattern A: Python literal must match SQL CHECK constraint exactly."""
    from pathlib import Path
    from gecko_core.sources.types import FRESHNESS_TIER_VALUES

    migration = Path(__file__).parent.parent.parent.parent / "infra" / "supabase" / "migrations" / "20260508130000_chunk_freshness_tier.sql"
    sql = migration.read_text()
    for value in FRESHNESS_TIER_VALUES:
        assert f"'{value}'" in sql, f"freshness tier {value!r} missing from SQL CHECK"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/test_provider_kind_consistency.py::test_freshness_tier_values_match_sql_check -v`
Expected: FAIL — migration file does not exist.

- [ ] **Step 4: Write the migration**

Create `infra/supabase/migrations/20260508130000_chunk_freshness_tier.sql`:

```sql
-- Adds freshness_tier to chunks. Mirrors gecko_core.sources.types.FreshnessTier.
-- Defaults existing rows to 'static' (preserves current retrieval behavior).
-- Pattern A: any addition here must update FreshnessTier literal in the same commit.

ALTER TABLE chunks
  ADD COLUMN IF NOT EXISTS freshness_tier text NOT NULL DEFAULT 'static';

ALTER TABLE chunks
  DROP CONSTRAINT IF EXISTS chunks_freshness_tier_check;

ALTER TABLE chunks
  ADD CONSTRAINT chunks_freshness_tier_check
  CHECK (freshness_tier IN ('static', 'daily', 'live_only'));

CREATE INDEX IF NOT EXISTS chunks_freshness_tier_idx ON chunks (freshness_tier);
```

- [ ] **Step 5: Run schema-drift test to verify it now passes**

Run: `uv run pytest packages/gecko-core/tests/test_provider_kind_consistency.py::test_freshness_tier_values_match_sql_check -v`
Expected: PASS.

- [ ] **Step 6: Wire freshness_tier into Mongo writer**

In `packages/gecko-core/src/gecko_core/db/mongo_chunks.py`, find the chunk-insert function (likely `insert_chunks` or similar — grep `insert_many\|chunks_collection` to locate). Add `freshness_tier` to the document shape with default `"static"`. Example shape:

```python
def _chunk_doc(chunk: Chunk, *, freshness_tier: FreshnessTier = "static") -> dict:
    return {
        # ... existing fields ...
        "freshness_tier": freshness_tier,
    }
```

Thread the kwarg through the public insert function. Existing callers stay default; new trading-oracle ingest will pass `"daily"`.

- [ ] **Step 7: Run targeted tests**

Run: `uv run pytest packages/gecko-core/tests/ -k "mongo_chunks or provider_kind_consistency or freshness" -v`
Expected: PASS (existing tests untouched + new drift test green).

- [ ] **Step 8: Commit**

```bash
git add infra/supabase/migrations/20260508130000_chunk_freshness_tier.sql \
        packages/gecko-core/src/gecko_core/sources/types.py \
        packages/gecko-core/src/gecko_core/db/mongo_chunks.py \
        packages/gecko-core/tests/test_provider_kind_consistency.py
git commit -m "feat(schema): add chunks.freshness_tier (Pattern A literal + SQL CHECK)"
```

---

## Task 3: Trading-Oracle Prompt + Listing Filter

**Why:** the prompt is the highest-leverage knob. Filter logic decides which paysh/bazaar listings we actually pay for — wrong filter = wasted budget.

**Files:**
- Create: `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/__init__.py` (empty)
- Create: `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/prompt.py`
- Create: `packages/gecko-core/tests/ingestion/trading_oracle/__init__.py` (empty)
- Create: `packages/gecko-core/tests/ingestion/trading_oracle/test_prompt.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/gecko-core/tests/ingestion/trading_oracle/test_prompt.py
from gecko_core.ingestion.trading_oracle.prompt import (
    SOLANA_DEFI_PROTOCOLS,
    TRADING_ORACLE_PROMPT,
    is_solana_defi_relevant,
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
    assert is_solana_defi_relevant({
        "name": "Kamino Lend Snapshot",
        "description": "Daily TVL + APY for Kamino USDC reserves on Solana",
        "tags": ["solana", "lending", "kamino"],
    }) is True


def test_filter_rejects_unrelated():
    assert is_solana_defi_relevant({
        "name": "Hotel Booking API",
        "description": "Search hotels via Ctrip",
        "tags": ["travel"],
    }) is False


def test_filter_rejects_evm_only():
    assert is_solana_defi_relevant({
        "name": "Aave V3 USDC",
        "description": "Ethereum mainnet lending rate",
        "tags": ["ethereum", "defi", "aave"],
    }) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/ -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the implementation**

```python
# packages/gecko-core/src/gecko_core/ingestion/trading_oracle/prompt.py
"""Curated prompt + listing filter for the trading-oracle ingest run.

Scope: Solana DeFi only. Multi-chain and CEX-news scope deliberately
excluded — see docs/superpowers/specs/2026-05-08-trading-oracle-reference-skill-design.md §4.
"""

from __future__ import annotations

from collections.abc import Mapping

SOLANA_DEFI_PROTOCOLS: tuple[str, ...] = (
    "Jupiter",
    "Kamino",
    "Jito",
    "Pyth",
    "Drift",
    "Orca",
    "Raydium",
    "Meteora",
    "MarginFi",
    "Sanctum",
)

TRADING_ORACLE_PROMPT: str = (
    "Acting as a Solana DeFi trading research oracle: for the protocols "
    + ", ".join(SOLANA_DEFI_PROTOCOLS)
    + ", retrieve and summarize current operational facts that affect a trader's "
    "decision-making — pool TVL trends, fee tiers, oracle staleness windows, "
    "recent governance / parameter changes, audit status, known incident history "
    "within the last 90 days, and integration partners. Cite source per fact. "
    "Do not produce trade recommendations; produce parameters a trader's agent "
    "needs to reason."
)

_SOLANA_TOKENS = ("solana", "spl", "anchor")
_DEFI_TOKENS = ("defi", "dex", "lending", "lst", "perp", "perps", "oracle", "liquidity", "amm", "staking", "yield")
_EVM_REJECT_TOKENS = ("ethereum", "evm", "arbitrum", "base", "polygon", "bsc", "optimism", "avalanche")


def _haystack(listing: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in ("name", "description"):
        v = listing.get(key)
        if isinstance(v, str):
            parts.append(v)
    tags = listing.get("tags")
    if isinstance(tags, (list, tuple)):
        parts.extend(str(t) for t in tags)
    proto_match = any(p.lower() in " ".join(parts).lower() for p in SOLANA_DEFI_PROTOCOLS)
    if proto_match:
        parts.append("__protocol_match__")
    return " ".join(parts).lower()


def is_solana_defi_relevant(listing: Mapping[str, object]) -> bool:
    h = _haystack(listing)
    if any(t in h for t in _EVM_REJECT_TOKENS) and not any(s in h for s in _SOLANA_TOKENS):
        return False
    if "__protocol_match__" in h:
        return True
    has_solana = any(t in h for t in _SOLANA_TOKENS)
    has_defi = any(t in h for t in _DEFI_TOKENS)
    return has_solana and has_defi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/ -v`
Expected: PASS — 5/5.

- [ ] **Step 5: Commit**

```bash
git add packages/gecko-core/src/gecko_core/ingestion/trading_oracle/ \
        packages/gecko-core/tests/ingestion/trading_oracle/
git commit -m "feat(trading-oracle): curated prompt + Solana-DeFi listing filter"
```

---

## Task 4: Live Ingest Orchestrator (with stub fixtures)

**Why:** wire `BudgetGuard` + `is_solana_defi_relevant` + existing `paysh_live`/`bazaar_live` providers + Mongo writer into one orchestrator. Test against stubbed fixtures (Pattern C — recorded in Task 6, replayed forever after).

**Files:**
- Create: `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py`
- Create: `packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py`

- [ ] **Step 1: Write the failing test**

```python
# packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py
from decimal import Decimal
from gecko_core.ingestion.trading_oracle.run_live_ingest import (
    IngestPlan,
    plan_ingest,
)


def _listing(name: str, price: float, *, tags=("solana", "defi")):
    return {"name": name, "description": f"{name} feed", "tags": list(tags), "price_usd": Decimal(str(price))}


def test_plan_skips_irrelevant():
    listings = [
        _listing("Kamino TVL", 1.0),
        _listing("Hotel Search", 0.5, tags=["travel"]),
    ]
    plan = plan_ingest(listings, cap_usd=Decimal("20.00"))
    assert [c.name for c in plan.calls] == ["Kamino TVL"]


def test_plan_respects_cap():
    listings = [_listing(f"Proto-{i}", 5.0) for i in range(10)]
    plan = plan_ingest(listings, cap_usd=Decimal("20.00"))
    # 5*4 = 20.00; the 5th call would push over.
    assert len(plan.calls) == 4
    assert plan.projected_total_usd == Decimal("20.00")


def test_plan_records_skipped_reason():
    listings = [
        _listing("A", 5.0),
        _listing("B-EVM-only", 5.0, tags=["ethereum", "defi"]),
        _listing("C", 18.0),  # would exceed remaining
    ]
    plan = plan_ingest(listings, cap_usd=Decimal("20.00"))
    assert [c.name for c in plan.calls] == ["A"]
    skipped = {s.name: s.reason for s in plan.skipped}
    assert skipped["B-EVM-only"] == "filter:not_solana_defi"
    assert skipped["C"] == "budget:would_exceed_cap"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Write the orchestrator (planner-only first; live execute in Task 6)**

```python
# packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py
"""Trading-oracle live ingest orchestrator.

Two surfaces:
    - plan_ingest(listings, cap_usd) -> IngestPlan   (pure, deterministic, tested)
    - execute_plan(plan, *, mongo, x402_client)      (Task 6: wires LiveX402Client + Mongo)

Splitting these means we can prove the planner is correct before any
USDC moves. The live execute call lands in Task 6 once the buyer wallet
is funded.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from gecko_core.ingestion.budget_guard import BudgetGuard
from gecko_core.ingestion.trading_oracle.prompt import is_solana_defi_relevant


@dataclass(frozen=True)
class PlannedCall:
    name: str
    price_usd: Decimal
    listing: Mapping[str, Any]


@dataclass(frozen=True)
class SkippedCall:
    name: str
    reason: str  # "filter:not_solana_defi" | "budget:would_exceed_cap" | "no_price"


@dataclass(frozen=True)
class IngestPlan:
    calls: tuple[PlannedCall, ...]
    skipped: tuple[SkippedCall, ...]
    projected_total_usd: Decimal


def plan_ingest(
    listings: Sequence[Mapping[str, Any]],
    *,
    cap_usd: Decimal,
) -> IngestPlan:
    guard = BudgetGuard(cap_usd=cap_usd)
    calls: list[PlannedCall] = []
    skipped: list[SkippedCall] = []
    for listing in listings:
        name = str(listing.get("name", "<unknown>"))
        price = listing.get("price_usd")
        if not isinstance(price, Decimal):
            skipped.append(SkippedCall(name=name, reason="no_price"))
            continue
        if not is_solana_defi_relevant(listing):
            skipped.append(SkippedCall(name=name, reason="filter:not_solana_defi"))
            continue
        if not guard.can_afford(price):
            skipped.append(SkippedCall(name=name, reason="budget:would_exceed_cap"))
            continue
        guard.charge(price, label=name)
        calls.append(PlannedCall(name=name, price_usd=price, listing=listing))
    return IngestPlan(
        calls=tuple(calls),
        skipped=tuple(skipped),
        projected_total_usd=guard.spent(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py -v`
Expected: PASS — 3/3.

- [ ] **Step 5: Commit**

```bash
git add packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py \
        packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py
git commit -m "feat(trading-oracle): planner stage of live ingest orchestrator"
```

---

## Task 5: Kamino Devnet Adapter (Python port of prior TS)

**Why:** the example skill needs to *actually execute* on devnet to be a stronger demo than mock intent. Reference: `~/PycharmProjects/Gecko/gecko-social-fi-creators-api/src/services/kamino.service.ts:46-220`. Two modes: `simulate` (no network) and `devnet` (real KTX REST → sign → submit).

**Files:**
- Create: `packages/gecko-core/src/gecko_core/execution/__init__.py` (empty)
- Create: `packages/gecko-core/src/gecko_core/execution/kamino_devnet.py`
- Create: `packages/gecko-core/tests/execution/__init__.py` (empty)
- Create: `packages/gecko-core/tests/execution/test_kamino_devnet.py`
- Create: `packages/gecko-core/tests/execution/fixtures/ktx_deposit_response.json`

- [ ] **Step 1: Confirm `solana-py` + `solders` are workspace deps**

Run: `grep -E "solana|solders" packages/gecko-core/pyproject.toml`
Expected: both present. If not:

```bash
uv add --package gecko-core solana solders httpx
```

- [ ] **Step 2: Record the KTX response fixture**

Create `packages/gecko-core/tests/execution/fixtures/ktx_deposit_response.json` (synthetic — not real Kamino, just shape-correct):

```json
{
  "transaction": "AQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA==",
  "lastValidBlockHeight": 100000
}
```

- [ ] **Step 3: Write the failing test**

```python
# packages/gecko-core/tests/execution/test_kamino_devnet.py
import json
from decimal import Decimal
from pathlib import Path
import pytest
from gecko_core.execution.kamino_devnet import (
    KaminoIntent,
    build_simulate_intent,
    fetch_unsigned_deposit_tx,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_simulate_intent_never_signs():
    intent = build_simulate_intent(
        wallet="HzXDevnetTraderPubkey",
        market="So1anaKmK1ndDeVnetMrkt",
        reserve="USDCRsrvDeVnet",
        amount_usdc=Decimal("1.50"),
    )
    assert intent.mode == "simulate"
    assert intent.wallet == "HzXDevnetTraderPubkey"
    assert intent.amount_usdc == Decimal("1.50")
    # Critical invariant: simulate mode produces NO signed payload.
    assert intent.signed_tx_b64 is None
    assert intent.signature is None


def test_simulate_intent_renders_dict():
    intent = build_simulate_intent(
        wallet="W", market="M", reserve="R", amount_usdc=Decimal("2"),
    )
    d = intent.to_dict()
    assert d == {
        "mode": "simulate",
        "venue": "kamino",
        "action": "deposit",
        "wallet": "W",
        "market": "M",
        "reserve": "R",
        "amount_usdc": "2",
    }


@pytest.mark.asyncio
async def test_fetch_unsigned_deposit_tx_replays_fixture(monkeypatch):
    # Replay the recorded fixture without hitting the network.
    fixture = json.loads((FIXTURES / "ktx_deposit_response.json").read_text())

    class _Resp:
        status_code = 200
        def json(self): return fixture
        def raise_for_status(self): pass

    class _AsyncClient:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): pass
        async def post(self, *a, **kw): return _Resp()

    monkeypatch.setattr(
        "gecko_core.execution.kamino_devnet.httpx.AsyncClient",
        lambda *a, **kw: _AsyncClient(),
    )

    tx_b64 = await fetch_unsigned_deposit_tx(
        ktx_url="https://api.kamino.finance",
        wallet="W", market="M", reserve="R", amount_usdc=Decimal("1.0"),
    )
    assert tx_b64 == fixture["transaction"]
```

- [ ] **Step 4: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/execution/ -v`
Expected: FAIL — module missing.

- [ ] **Step 5: Write the implementation**

```python
# packages/gecko-core/src/gecko_core/execution/kamino_devnet.py
"""Kamino devnet adapter — port of gecko-social-fi-creators-api/src/services/kamino.service.ts.

Two modes:
    - simulate: returns an intent dict, never signs, never hits network.
    - devnet:  fetches an unsigned base64 versioned tx from KTX REST,
               signs with the user's keypair (passed in by the example),
               submits to Solana devnet RPC, waits for confirmation.

Mainnet is intentionally not supported here — the example skill must not
custody mainnet funds. Mainnet deposits stay with the user's chosen UI
(Kamino webapp, lana.ai, etc).

Reference: kamino.service.ts:46-220 (KAMINO_MODE, ktxPost, signAndSend).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

import httpx

KaminoMode = Literal["simulate", "devnet"]


@dataclass(frozen=True)
class KaminoIntent:
    mode: KaminoMode
    wallet: str
    market: str
    reserve: str
    amount_usdc: Decimal
    signed_tx_b64: str | None = None
    signature: str | None = None

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "venue": "kamino",
            "action": "deposit",
            "wallet": self.wallet,
            "market": self.market,
            "reserve": self.reserve,
            "amount_usdc": str(self.amount_usdc),
        }


def build_simulate_intent(
    *,
    wallet: str,
    market: str,
    reserve: str,
    amount_usdc: Decimal,
) -> KaminoIntent:
    return KaminoIntent(
        mode="simulate",
        wallet=wallet,
        market=market,
        reserve=reserve,
        amount_usdc=amount_usdc,
    )


async def fetch_unsigned_deposit_tx(
    *,
    ktx_url: str,
    wallet: str,
    market: str,
    reserve: str,
    amount_usdc: Decimal,
) -> str:
    """Call KTX /ktx/klend/deposit and return the base64 unsigned transaction.

    Mirrors `ktxPost` from kamino.service.ts:124-141.
    """
    payload = {
        "wallet": wallet,
        "market": market,
        "reserve": reserve,
        "amount": str(amount_usdc),
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(f"{ktx_url}/ktx/klend/deposit", json=payload)
        resp.raise_for_status()
        body = resp.json()
    tx = body.get("transaction")
    if not isinstance(tx, str):
        raise RuntimeError(f"KTX deposit returned no transaction: {body!r}")
    return tx
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run pytest packages/gecko-core/tests/execution/ -v`
Expected: PASS — 3/3.

- [ ] **Step 7: Commit**

```bash
git add packages/gecko-core/src/gecko_core/execution/ \
        packages/gecko-core/tests/execution/
git commit -m "feat(execution): Kamino devnet adapter (simulate + KTX fetch) — port of prior TS"
```

> **Note on devnet sign+submit:** the actual sign + send + confirm step is *not* in this Python adapter. The example skill in Task 7 holds the user's devnet keypair and signs locally, then calls a tiny `submit_signed_tx_devnet(b64)` helper that wraps `solana.rpc.async_api.AsyncClient`. Keeping the keypair handling in the example skill (not in `gecko-core`) preserves the non-custodial boundary — Gecko never sees a private key.

---

## Phase 2 Gate — Founder funds `GECKO_BUYER_WALLET`

> **STOP. This task requires founder action — operator-only.**
>
> Per `memory/project_buyer_wallet_blocker_2026_05_08.md`, the 4-step checklist:
> 1. Generate buyer keypair locally (or reuse if already done).
> 2. Push to AWS SSM as `SecureString` named `/gecko/prod/buyer_wallet_keypair`.
> 3. Wire ECS task env: add `GECKO_BUYER_WALLET_SSM_PARAM=/gecko/prod/buyer_wallet_keypair`.
> 4. Transfer ~$20 USDC mainnet to the buyer wallet's USDC ATA.
>
> Do NOT proceed to Task 6 until founder confirms wallet is funded. The agent stops here.

---

## Task 6: One-Shot Live Ingest Run

**Why:** spend the $20, ingest paysh + bazaar Solana-DeFi paid responses to MongoDB, generate the corpus that makes the example skill substantive.

**Files:**
- Modify: `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py` (add `execute_plan`).
- Create: `scripts/trading_oracle/run.py` (thin CLI wrapper).
- Modify: `packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py` (add execute test with stubbed x402 client).

- [ ] **Step 1: Write the failing test for execute_plan**

Append to `packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py`:

```python
import pytest
from decimal import Decimal
from gecko_core.ingestion.trading_oracle.run_live_ingest import (
    IngestPlan, PlannedCall, execute_plan,
)


@pytest.mark.asyncio
async def test_execute_plan_writes_chunks_with_freshness_daily():
    plan = IngestPlan(
        calls=(PlannedCall(name="Kamino TVL", price_usd=Decimal("1.00"),
                           listing={"name": "Kamino TVL", "fqn": "paysh:kamino-tvl",
                                    "provider_kind": "paysh_live"}),),
        skipped=(),
        projected_total_usd=Decimal("1.00"),
    )

    written = []

    async def fake_charge_and_fetch(call):
        return {"body": "Kamino USDC reserve TVL = 12.3M, APY 8.4%", "fqn": call.listing["fqn"]}

    async def fake_write_chunk(*, text, provider_kind, vertical, freshness_tier, source_url):
        written.append({"vertical": vertical, "provider_kind": provider_kind, "freshness_tier": freshness_tier})

    report = await execute_plan(
        plan,
        charge_and_fetch=fake_charge_and_fetch,
        write_chunk=fake_write_chunk,
        vertical="defi-trading",
    )
    assert report.spent_usd == Decimal("1.00")
    assert len(written) == 1
    assert written[0]["freshness_tier"] == "daily"
    assert written[0]["vertical"] == "defi-trading"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py::test_execute_plan_writes_chunks_with_freshness_daily -v`
Expected: FAIL — `execute_plan` not defined.

- [ ] **Step 3: Implement `execute_plan` (DI-friendly — no hardcoded clients)**

Append to `packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py`:

```python
from collections.abc import Awaitable, Callable
from typing import Any


@dataclass(frozen=True)
class IngestReport:
    spent_usd: Decimal
    chunks_written: int
    failures: tuple[str, ...]


async def execute_plan(
    plan: IngestPlan,
    *,
    charge_and_fetch: Callable[[PlannedCall], Awaitable[Mapping[str, Any]]],
    write_chunk: Callable[..., Awaitable[None]],
    vertical: str,
) -> IngestReport:
    """Execute a planned ingest. DI'd for testing.

    `charge_and_fetch(call)` performs the live x402 call — wrapped here so the
    real LiveX402Client is plumbed in by the CLI script, fakes by tests.
    `write_chunk(...)` writes one chunk to MongoDB with freshness_tier="daily".
    """
    written = 0
    failures: list[str] = []
    spent = Decimal("0")
    for call in plan.calls:
        try:
            response = await charge_and_fetch(call)
            text = response.get("body") if isinstance(response, Mapping) else None
            if not isinstance(text, str) or not text.strip():
                failures.append(f"{call.name}: empty body")
                continue
            await write_chunk(
                text=text,
                provider_kind=call.listing.get("provider_kind", "paysh_live"),
                vertical=vertical,
                freshness_tier="daily",
                source_url=call.listing.get("fqn", ""),
            )
            written += 1
            spent += call.price_usd
        except Exception as exc:  # don't abort the whole run on one failure
            failures.append(f"{call.name}: {type(exc).__name__}: {exc}")
    return IngestReport(spent_usd=spent, chunks_written=written, failures=tuple(failures))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py -v`
Expected: PASS (4/4 including the new one).

- [ ] **Step 5: Write the live CLI wrapper**

```python
# scripts/trading_oracle/run.py
"""Live ingest CLI. Run ONCE after buyer wallet is funded.

Usage:
    GECKO_X402_MODE=live \\
    GECKO_BUYER_WALLET_SSM_PARAM=/gecko/prod/buyer_wallet_keypair \\
    uv run python scripts/trading_oracle/run.py --cap-usd 20.00
"""

from __future__ import annotations

import asyncio
import logging
import os
from decimal import Decimal

import click

from gecko_core.ingestion.trading_oracle.run_live_ingest import (
    execute_plan,
    plan_ingest,
)
from gecko_core.sources.bazaar_live import list_bazaar_live_listings, charge_bazaar_call
from gecko_core.sources.paysh_live import list_paysh_live_listings, charge_paysh_call
from gecko_core.db.mongo_chunks import insert_chunk_with_embedding


log = logging.getLogger("trading_oracle.run")


async def _charge_and_fetch(call):
    pk = call.listing.get("provider_kind", "paysh_live")
    if pk == "paysh_live":
        return await charge_paysh_call(call.listing)
    if pk == "bazaar_live":
        return await charge_bazaar_call(call.listing)
    raise ValueError(f"unknown provider_kind {pk!r}")


async def _write_chunk(*, text, provider_kind, vertical, freshness_tier, source_url):
    await insert_chunk_with_embedding(
        text=text,
        provider_kind=provider_kind,
        vertical=vertical,
        freshness_tier=freshness_tier,
        source_url=source_url,
    )


@click.command()
@click.option("--cap-usd", default="20.00", help="Hard spend cap in USD.")
@click.option("--dry-run", is_flag=True, help="Plan only — no live calls.")
def main(cap_usd: str, dry_run: bool) -> None:
    logging.basicConfig(level=logging.INFO)

    async def _run() -> None:
        listings = []
        listings += await list_paysh_live_listings()
        listings += await list_bazaar_live_listings()
        plan = plan_ingest(listings, cap_usd=Decimal(cap_usd))
        log.info("planned %d calls (skip %d, projected $%s)",
                 len(plan.calls), len(plan.skipped), plan.projected_total_usd)
        for s in plan.skipped:
            log.info("  SKIP %-40s reason=%s", s.name, s.reason)
        for c in plan.calls:
            log.info("  CALL %-40s price=$%s", c.name, c.price_usd)
        if dry_run:
            return
        report = await execute_plan(
            plan,
            charge_and_fetch=_charge_and_fetch,
            write_chunk=_write_chunk,
            vertical="defi-trading",
        )
        log.info("DONE: spent $%s, wrote %d chunks, %d failures",
                 report.spent_usd, report.chunks_written, len(report.failures))
        for f in report.failures:
            log.warning("  FAIL %s", f)

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

> **Note:** if `list_paysh_live_listings` / `charge_paysh_call` don't exist with those exact names, grep `packages/gecko-core/src/gecko_core/sources/paysh_live.py` for the actual public functions and adjust imports. Same for `bazaar_live.py`. The expectation is that the live providers are already shipped (per `project_buyer_wallet_blocker_2026_05_08`).

- [ ] **Step 6: Dry-run first to verify the plan**

```bash
uv run python scripts/trading_oracle/run.py --cap-usd 20.00 --dry-run
```

Expected: lists planned calls + skipped reasons. NO USDC moves.

- [ ] **Step 7: Live run (founder-authorized, one shot)**

```bash
GECKO_X402_MODE=live \
GECKO_BUYER_WALLET_SSM_PARAM=/gecko/prod/buyer_wallet_keypair \
uv run python scripts/trading_oracle/run.py --cap-usd 20.00 2>&1 | tee logs/trading_oracle_run_$(date +%Y%m%d_%H%M%S).log
```

Expected: spent ≤ $20, ≥ 5 chunks written. Verify in MongoDB:

```bash
# expect non-zero count
uv run python -c "from gecko_core.db.mongo import get_chunks_collection; import asyncio; c = asyncio.run(get_chunks_collection()); print(c.count_documents({'vertical':'defi-trading','freshness_tier':'daily'}))"
```

- [ ] **Step 8: Commit ingest scaffold (NOT logs)**

```bash
git add packages/gecko-core/src/gecko_core/ingestion/trading_oracle/run_live_ingest.py \
        packages/gecko-core/tests/ingestion/trading_oracle/test_run_live_ingest.py \
        scripts/trading_oracle/run.py
git commit -m "feat(trading-oracle): execute_plan + live CLI for one-shot \$20 ingest"
```

---

## Task 7: Reference Skill in `gecko-claude`

**Why:** the public artifact other builders clone. Cross-repo — files land in `~/PycharmProjects/Gecko/gecko-claude/examples/trading-oracle/`.

**Files** (all in sister repo `gecko-claude`):
- Create: `examples/trading-oracle/skill.md`
- Create: `examples/trading-oracle/.mcp.json`
- Create: `examples/trading-oracle/example_call.py`
- Create: `examples/trading-oracle/README.md`

- [ ] **Step 1: Write `skill.md`**

```markdown
---
name: trading-oracle
description: Solana DeFi trading research with Gecko's adversarial-debate verdict, hand-off to solana-claude's defi-engineer for Kamino-style intent, devnet execution.
---

# Trading Oracle (reference skill)

This skill demonstrates the Gecko KaaS pattern:

1. Gecko provides grounded knowledge + adversarial verdict.
2. Superteam Brasil's `solana-claude` `defi-engineer` agent owns Kamino/Jupiter/Drift/Raydium/Orca/Meteora intent shape.
3. The user's chosen venue (devnet here, mainnet via Kamino webapp / lana.ai elsewhere) settles.

Gecko never custodies funds, never signs transactions, never executes trades.

## Setup (one-paste)

```bash
# 1. Install solana-claude (Superteam Brasil bundle)
curl -fsSL https://raw.githubusercontent.com/solanabr/solana-claude-config/main/install.sh | bash

# 2. Mount Gecko MCP
# (.mcp.json in this directory adds mcp.geckovision.tech)

# 3. (Optional) generate a devnet keypair if you want to actually execute
solana-keygen new --outfile ~/.config/solana/devnet-trader.json
solana airdrop 2 -u devnet -k ~/.config/solana/devnet-trader.json
```

## Use

In Claude Code, paste:

> "Use the trading-oracle skill: should I deposit $1 USDC into Kamino's USDC reserve right now? Use Gecko for context, defi-engineer for intent, and execute on devnet."

The skill will:
1. Call `gecko_research` with `vertical=defi-trading`.
2. Hand the verdict + Kamino-specific shaping to `defi-engineer`.
3. Build a Kamino devnet deposit intent.
4. Sign with your devnet keypair, submit, return the signature.
```

- [ ] **Step 2: Write `.mcp.json`**

```json
{
  "mcpServers": {
    "gecko": {
      "type": "http",
      "url": "https://mcp.geckovision.tech/mcp/"
    }
  }
}
```

- [ ] **Step 3: Write `example_call.py`** (the client-side keypair holder — Gecko never sees this)

```python
"""Reference: end-to-end trading-oracle flow.

Holds the user's devnet keypair locally. Calls Gecko via MCP for verdict.
Hands shaping to solana-claude's defi-engineer. Submits to devnet.
"""

from __future__ import annotations

import asyncio
import json
import os
from decimal import Decimal
from pathlib import Path

from solana.rpc.async_api import AsyncClient
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


DEVNET_RPC = os.environ.get("SOLANA_DEVNET_RPC", "https://api.devnet.solana.com")
KEYPAIR_PATH = Path(os.environ.get(
    "SOLANA_DEVNET_KEYPAIR",
    str(Path.home() / ".config/solana/devnet-trader.json"),
))


def _load_keypair() -> Keypair:
    secret = json.loads(KEYPAIR_PATH.read_text())
    return Keypair.from_bytes(bytes(secret))


async def submit_signed_tx_devnet(unsigned_tx_b64: str, keypair: Keypair) -> str:
    """Sign + submit to devnet. Mirrors signAndSend from kamino.service.ts:107-121."""
    import base64
    raw = base64.b64decode(unsigned_tx_b64)
    vtx = VersionedTransaction.from_bytes(raw)
    signed = VersionedTransaction(vtx.message, [keypair])
    async with AsyncClient(DEVNET_RPC) as client:
        resp = await client.send_raw_transaction(bytes(signed))
        sig = resp.value
        await client.confirm_transaction(sig, commitment="confirmed")
        return str(sig)


async def main() -> None:
    keypair = _load_keypair()
    print(f"devnet wallet: {keypair.pubkey()}")
    # 1. The Claude Code session itself calls gecko_research via MCP.
    # 2. defi-engineer agent shapes the Kamino intent.
    # 3. defi-engineer hands back an unsigned tx (or asks this script to fetch it).
    # 4. We sign + submit:
    # sig = await submit_signed_tx_devnet(unsigned_tx_b64, keypair)
    # print(f"devnet signature: {sig}")
    print("This script is a helper; orchestration happens in the Claude Code session.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 4: Write `README.md`**

```markdown
# trading-oracle

Reference Claude Code skill demonstrating Gecko's KaaS oracle pattern.

**Three lanes, no overlap:**
- **Gecko** — adversarial-debate verdict from Solana-DeFi corpus (paysh + bazaar live x402 spend).
- **solana-claude `defi-engineer`** — Kamino/Jupiter/Drift intent shape (Superteam Brasil bundle).
- **Solana devnet** — settlement venue. The user signs locally; no custody crosses any service boundary.

See `skill.md` for setup and use.
```

- [ ] **Step 5: Cross-repo commit (run inside `gecko-claude`, not this repo)**

```bash
cd ~/PycharmProjects/Gecko/gecko-claude
git add examples/trading-oracle/
git commit -m "feat(examples): trading-oracle reference skill (Gecko + solana-claude + devnet)"
git push
```

---

## Task 8: End-to-End Smoke + Tavily Falsifier

**Why:** spec §10 — if we can't beat Tavily on a named axis, the wedge collapses regardless of how slick the integration looks.

**Files:**
- Create: `tests/integration/test_trading_oracle_e2e.py`
- Create: `tests/falsifier/trading_oracle_vs_tavily.py`

- [ ] **Step 1: E2E smoke (uses live MongoDB corpus from Task 6)**

```python
# tests/integration/test_trading_oracle_e2e.py
"""End-to-end smoke: prompt -> Gecko -> verdict cites paysh/bazaar chunks.

Marked @live_corpus — only run after Task 6 ingests the corpus.
"""

import os
import pytest
import httpx


pytestmark = pytest.mark.skipif(
    os.environ.get("GECKO_TRADING_ORACLE_E2E") != "1",
    reason="set GECKO_TRADING_ORACLE_E2E=1 after Task 6 corpus is in",
)


@pytest.mark.asyncio
async def test_research_cites_marketplace_chunks_on_kamino_question():
    api = os.environ.get("GECKO_API_URL", "http://localhost:8000")
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{api}/research",
            json={
                "idea": "Should a trader deposit USDC into Kamino USDC reserve right now?",
                "vertical": "defi-trading",
                "tier": "basic",
            },
        )
    r.raise_for_status()
    body = r.json()
    cited_urls = [m["url"] for m in body.get("citation_markers", [])]
    assert any("paysh" in u or "bazaar" in u or "agentic.market" in u for u in cited_urls), (
        f"verdict did not cite a marketplace chunk; cited_urls={cited_urls!r}"
    )
```

- [ ] **Step 2: Tavily falsifier (5 prompts, Gecko vs raw Tavily)**

```python
# tests/falsifier/trading_oracle_vs_tavily.py
"""Falsifier: 5 trading prompts, Gecko vs Tavily-direct, hallucinated-fact rate.

Run manually:
    GECKO_API_URL=... TAVILY_API_KEY=... uv run python tests/falsifier/trading_oracle_vs_tavily.py
Output: comparison report. If Gecko hallucinated-rate >= Tavily rate, the
KaaS-oracle thesis is wrong — don't pursue partner integration.
"""

import asyncio
import json
import os
from pathlib import Path

import httpx

PROMPTS = [
    "What is the current TVL of Kamino USDC reserve and when was it last updated?",
    "Has Drift had any oracle-staleness incidents in the last 90 days?",
    "What audit firms have signed off on Jito's recent vault contract changes?",
    "Compare Orca vs Raydium fee tiers for SOL/USDC — cite source per number.",
    "Has Pyth pushed any breaking parameter change to its SOL/USD feed in 2026?",
]

OUTPUT = Path("docs/superpowers/falsifier-results/trading_oracle_vs_tavily.json")


async def _gecko(prompt: str) -> dict:
    api = os.environ["GECKO_API_URL"]
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.post(f"{api}/research", json={
            "idea": prompt, "vertical": "defi-trading", "tier": "basic",
        })
    r.raise_for_status()
    return r.json()


async def _tavily(prompt: str) -> dict:
    key = os.environ["TAVILY_API_KEY"]
    async with httpx.AsyncClient(timeout=60.0) as c:
        r = await c.post("https://api.tavily.com/search", json={
            "api_key": key, "query": prompt, "search_depth": "advanced",
        })
    r.raise_for_status()
    return r.json()


async def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in PROMPTS:
        gecko_r = await _gecko(p)
        tavily_r = await _tavily(p)
        rows.append({
            "prompt": p,
            "gecko_citations": [m["url"] for m in gecko_r.get("citation_markers", [])],
            "gecko_verdict": gecko_r.get("verdict"),
            "tavily_top_urls": [r["url"] for r in tavily_r.get("results", [])[:5]],
        })
    OUTPUT.write_text(json.dumps(rows, indent=2))
    print(f"wrote {OUTPUT}")
    print("Manual judging step: read the JSON, score each row for hallucinated-fact rate.")


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 3: Run after Task 6 corpus is in**

```bash
GECKO_TRADING_ORACLE_E2E=1 uv run pytest tests/integration/test_trading_oracle_e2e.py -v
GECKO_API_URL=http://localhost:8000 TAVILY_API_KEY=$TAVILY_API_KEY uv run python tests/falsifier/trading_oracle_vs_tavily.py
```

- [ ] **Step 4: Commit (results JSON gitignored — grading is manual + private)**

```bash
echo "docs/superpowers/falsifier-results/" >> .gitignore
git add tests/integration/test_trading_oracle_e2e.py \
        tests/falsifier/trading_oracle_vs_tavily.py \
        .gitignore
git commit -m "test(trading-oracle): e2e smoke + Tavily falsifier"
```

---

## Self-Review (filled inline)

**Spec coverage:** every spec §1–§12 maps to a task. §1 motivation → preamble. §2 scope → tasks 1–8. §3 components → file structure. §4 prompt → task 3. §5 data flow → tasks 4+6+7. §6 errors → task 6 step 3 (try/except in `execute_plan`). §7 schema → task 2. §8 testing → embedded in each task. §9 ordering → phase gates. §10 falsifier → task 8. §11 cross-repo → task 7. §12 risks → mitigated by guard + dry-run + falsifier.

**Placeholder scan:** no TBDs. Two real notes flagged inline (`> Note:` blocks in tasks 5 and 6) — intentional, not placeholders: they reference exact files to grep if names differ.

**Type consistency:** `KaminoIntent`, `IngestPlan`, `PlannedCall`, `BudgetGuard`, `FreshnessTier` referenced consistently. `provider_kind` matches existing `ProviderKind` literal in `sources/types.py`.

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-08-trading-oracle-reference-skill.md`.**

Two execution options:

1. **Subagent-Driven (recommended)** — fresh subagent per task, I review between tasks, fast iteration.
2. **Inline Execution** — execute tasks in this session via executing-plans, batch with checkpoints.

Which approach?
