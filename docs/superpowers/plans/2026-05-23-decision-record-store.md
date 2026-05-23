# Decision-Record Store Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every agent decision (all voices + indicators + future market-context slot + oracle verdict + coordinator outcome), tagged by simulation/strategy/agent-group, with realized outcomes linked — durable to per-run JSONL + best-effort to MongoDB — so we can analyze, backtest, and tune strategies with data.

**Architecture:** A self-contained `contest_bot/decision_store/` package: typed models, a recorder that writes each decision to per-run JSONL (synchronous, durable) and best-effort-upserts to Mongo (the trading loop never blocks/crashes on Mongo), a `sync` CLI that backfills JSONL→Mongo, plus 3 new pure indicator features. The bot calls the recorder at decision points and on position close. Default `agent_group="default"`, `market_context=None` (future slots present, minimally filled).

**Tech Stack:** Python 3.11+, dataclasses, `pymongo` (best-effort), pytest. Reuses `contest_bot/indicators.py` + the bot's existing voice/coordinator outputs.

---

## File structure

| File | Responsibility |
|---|---|
| `contest_bot/indicators.py` *(modify)* | + `adx_slope`, `adx_distance`, `chop_distance` pure functions |
| `contest_bot/decision_store/__init__.py` *(create)* | Public exports: `SimulationRegistry`, `DecisionRecorder`, models |
| `contest_bot/decision_store/models.py` *(create)* | `SimulationDoc`, `DecisionDoc`, `Outcome` dataclasses + `to_dict`/`from_dict` |
| `contest_bot/decision_store/mongo.py` *(create)* | `best_effort_upsert(coll, key, doc)` — fail-safe Mongo, never raises |
| `contest_bot/decision_store/recorder.py` *(create)* | `SimulationRegistry`, `DecisionRecorder` (JSONL + best-effort Mongo) |
| `contest_bot/decision_store/sync.py` *(create)* | `python -m decision_store.sync` — backfill JSONL→Mongo |
| `contest_bot/tests/test_decision_store.py` *(create)* | Unit tests (in-memory fake Mongo; no live Atlas required) |
| `contest_bot/tests/test_indicator_distances.py` *(create)* | Unit tests for the 3 new features on synthetic data |
| `contest_bot/jto_breakout_gecko_gated_contest_bot.py` *(modify)* | Start run, record at decision points, attach outcomes |

Storage layout on disk: `contest_bot/decision_runs/<run_id>/simulation.json` + `<run_id>/decisions.jsonl`.

---

### Task 1: Indicator distance/slope features

**Files:**
- Modify: `contest_bot/indicators.py`
- Test: `contest_bot/tests/test_indicator_distances.py`

- [ ] **Step 1: Write the failing tests**

```python
# contest_bot/tests/test_indicator_distances.py
from indicators import adx_slope, adx_distance, chop_distance

def test_adx_slope_rising():
    # ADX series rising over last 3 bars -> positive slope
    assert adx_slope([20.0, 22.0, 25.0, 28.0], lookback=3) == 8.0

def test_adx_slope_falling_and_none():
    assert adx_slope([30.0, 28.0, 26.0], lookback=2) == -4.0
    assert adx_slope([None, 25.0], lookback=3) is None  # insufficient data

def test_adx_distance_signed_margin():
    # distance from the 25 trend threshold
    assert adx_distance(27.6) == 2.6
    assert adx_distance(18.0) == -7.0
    assert adx_distance(None) is None

def test_chop_distance_below_chop_threshold_is_positive():
    # 61.8 - chop ; positive = on the trending side
    assert round(chop_distance(43.3), 1) == 18.5
    assert round(chop_distance(70.0), 1) == -8.2
    assert chop_distance(None) is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd contest_bot && python -m pytest tests/test_indicator_distances.py -v`
Expected: FAIL — `ImportError: cannot import name 'adx_slope'`.

- [ ] **Step 3: Implement the three pure functions**

```python
# contest_bot/indicators.py  (append near the other pure functions)
def adx_slope(adx_series: list[float | None], lookback: int = 3) -> float | None:
    """Δ of ADX over `lookback` bars. Positive = strengthening trend. None if insufficient."""
    if len(adx_series) <= lookback:
        return None
    a, b = adx_series[-1], adx_series[-1 - lookback]
    if a is None or b is None:
        return None
    return round(a - b, 4)

def adx_distance(adx_value: float | None, trend_threshold: float = 25.0) -> float | None:
    """Signed margin from the trend threshold. Positive = above (trending)."""
    return None if adx_value is None else round(adx_value - trend_threshold, 4)

def chop_distance(chop_value: float | None, chop_threshold: float = 61.8) -> float | None:
    """Signed distance from the chop ceiling. Positive = below (trending side)."""
    return None if chop_value is None else round(chop_threshold - chop_value, 4)
```

- [ ] **Step 4: Run to verify pass**

Run: `cd contest_bot && python -m pytest tests/test_indicator_distances.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add contest_bot/indicators.py contest_bot/tests/test_indicator_distances.py
git commit -m "feat(indicators): adx_slope + adx_distance + chop_distance (decision-store features)"
```

---

### Task 2: Models

**Files:**
- Create: `contest_bot/decision_store/__init__.py`, `contest_bot/decision_store/models.py`
- Test: `contest_bot/tests/test_decision_store.py`

- [ ] **Step 1: Write the failing test**

```python
# contest_bot/tests/test_decision_store.py
from decision_store.models import SimulationDoc, DecisionDoc, Outcome

def test_simulation_doc_roundtrip():
    s = SimulationDoc(run_id="r1", strategy_id="jto_breakout", agent_group="default",
                      symbol_universe=["PYTH"], universe_label="no-tax-majors",
                      config={"floor": 0.85}, mode="paper", code_commit="abc")
    d = s.to_dict()
    assert d["run_id"] == "r1" and d["agent_group"] == "default"
    assert SimulationDoc.from_dict(d).symbol_universe == ["PYTH"]

def test_decision_doc_has_future_slots_and_null_outcome():
    dec = DecisionDoc(run_id="r1", symbol="PYTH", symbol_group="majors",
                      signal={"fired": True}, indicators={"adx": 27.6},
                      voices=[{"name": "chart_analyst", "verdict": "abstain", "confidence": 0.0}],
                      oracle=None, coordinator={"action": "decline", "rule": "chart_below_threshold"})
    d = dec.to_dict()
    assert d["market_context"] is None        # future slot present
    assert d["outcome"] is None               # unset until close
    assert d["decision_id"]                    # auto-generated
    assert d["ts"]                             # auto-stamped

def test_outcome_dict():
    o = Outcome(pnl_pct=-0.3, pnl_usd=-0.27, exit_reason="flat_stall_exit", duration_min=90)
    assert o.to_dict()["exit_reason"] == "flat_stall_exit"
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd contest_bot && python -m pytest tests/test_decision_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'decision_store'`.

- [ ] **Step 3: Implement the models**

```python
# contest_bot/decision_store/models.py
from __future__ import annotations
import uuid, dataclasses
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class SimulationDoc:
    run_id: str
    strategy_id: str
    agent_group: str
    symbol_universe: list[str]
    universe_label: str
    config: dict
    mode: str               # "paper" | "live"
    code_commit: str
    started_at: str = field(default_factory=_now)
    ended_at: str | None = None
    host: str = ""
    def to_dict(self) -> dict: return asdict(self)
    @classmethod
    def from_dict(cls, d: dict) -> "SimulationDoc":
        return cls(**{k: d.get(k) for k in (f.name for f in dataclasses.fields(cls))})

@dataclass
class Outcome:
    pnl_pct: float
    pnl_usd: float | None = None
    exit_reason: str | None = None
    duration_min: float | None = None
    entry_price: float | None = None
    exit_price: float | None = None
    peak_pct: float | None = None
    def to_dict(self) -> dict: return asdict(self)

@dataclass
class DecisionDoc:
    run_id: str
    symbol: str
    symbol_group: str
    signal: dict
    indicators: dict
    voices: list[dict]
    oracle: dict | None
    coordinator: dict
    decision_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    ts: str = field(default_factory=_now)
    market_context: dict | None = None     # future slot (#2)
    candles_ref: dict | None = None        # {window_hash, last_ts, n_bars}
    outcome: dict | None = None            # patched on close
    def to_dict(self) -> dict: return asdict(self)
```

```python
# contest_bot/decision_store/__init__.py
from .models import SimulationDoc, DecisionDoc, Outcome
from .recorder import SimulationRegistry, DecisionRecorder
__all__ = ["SimulationDoc", "DecisionDoc", "Outcome", "SimulationRegistry", "DecisionRecorder"]
```
*(Note: `__init__` imports `recorder` — Task 4 creates it. Until then, run model tests with `from decision_store.models import ...` directly; the `__init__` import resolves after Task 4.)*

- [ ] **Step 4: Run to verify pass**

Run: `cd contest_bot && python -m pytest tests/test_decision_store.py -v`
Expected: PASS (3 model tests). *(Import `decision_store.models` directly in the test, not the package root, until Task 4 lands.)*

- [ ] **Step 5: Commit**

```bash
git add contest_bot/decision_store/ contest_bot/tests/test_decision_store.py
git commit -m "feat(decision-store): models (SimulationDoc, DecisionDoc, Outcome)"
```

---

### Task 3: Best-effort Mongo client (never raises)

**Files:**
- Create: `contest_bot/decision_store/mongo.py`
- Test: add to `contest_bot/tests/test_decision_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to contest_bot/tests/test_decision_store.py
from decision_store.mongo import best_effort_upsert

class _FakeColl:
    def __init__(self): self.docs = {}
    def update_one(self, flt, update, upsert=False):
        self.docs[flt["decision_id"]] = update["$set"]

def test_upsert_writes_to_coll():
    c = _FakeColl()
    ok = best_effort_upsert(c, {"decision_id": "d1"}, {"decision_id": "d1", "x": 1})
    assert ok is True and c.docs["d1"]["x"] == 1

def test_upsert_swallows_errors():
    class _Boom:
        def update_one(self, *a, **k): raise RuntimeError("mongo down")
    assert best_effort_upsert(_Boom(), {"decision_id": "d1"}, {"decision_id": "d1"}) is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd contest_bot && python -m pytest tests/test_decision_store.py -k upsert -v`
Expected: FAIL — `ModuleNotFoundError: decision_store.mongo`.

- [ ] **Step 3: Implement**

```python
# contest_bot/decision_store/mongo.py
from __future__ import annotations
import logging, os
logger = logging.getLogger("decision_store.mongo")

def best_effort_upsert(coll, flt: dict, doc: dict) -> bool:
    """Upsert; NEVER raises (the trading loop must not crash on Mongo). Returns success."""
    try:
        coll.update_one(flt, {"$set": doc}, upsert=True)
        return True
    except Exception as exc:  # noqa: BLE001 — fail-safe by design
        logger.warning("decision_store: mongo upsert failed (%s); JSONL remains source of truth", exc)
        return False

def get_collections():
    """Return (simulations, decisions) collections, or (None, None) if Mongo unreachable."""
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return None, None
    try:
        from pymongo import MongoClient
        db = MongoClient(uri, serverSelectionTimeoutMS=3000)[os.environ.get("MONGODB_DB", "gecko")]
        return db["simulations"], db["decisions"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("decision_store: mongo unavailable (%s); JSONL-only", exc)
        return None, None
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_decision_store.py -k upsert -v` → PASS (2).
- [ ] **Step 5: Commit**

```bash
git add contest_bot/decision_store/mongo.py contest_bot/tests/test_decision_store.py
git commit -m "feat(decision-store): best-effort fail-safe mongo client"
```

---

### Task 4: SimulationRegistry + DecisionRecorder (JSONL + best-effort Mongo)

**Files:**
- Create: `contest_bot/decision_store/recorder.py`
- Test: add to `contest_bot/tests/test_decision_store.py`

- [ ] **Step 1: Write the failing test** (uses a tmp dir; Mongo collections injected as fakes)

```python
# append to contest_bot/tests/test_decision_store.py
import json, pathlib
from decision_store.recorder import SimulationRegistry, DecisionRecorder
from decision_store.models import SimulationDoc, DecisionDoc, Outcome

def _mk(tmp_path):
    sims, decs = _FakeColl(), _FakeColl()
    reg = SimulationRegistry(root=tmp_path, sims_coll=sims, decs_coll=decs)
    return reg, sims, decs

def test_start_writes_simulation_json(tmp_path):
    reg, sims, _ = _mk(tmp_path)
    run_id = reg.start(SimulationDoc(run_id="", strategy_id="jto", agent_group="default",
                       symbol_universe=["PYTH"], universe_label="majors", config={}, mode="paper", code_commit="abc"))
    assert (tmp_path / run_id / "simulation.json").exists()

def test_record_appends_jsonl_and_attach_outcome_patches(tmp_path):
    reg, sims, decs = _mk(tmp_path)
    run_id = reg.start(SimulationDoc(run_id="", strategy_id="jto", agent_group="default",
                       symbol_universe=["PYTH"], universe_label="majors", config={}, mode="paper", code_commit="abc"))
    rec = reg.recorder()
    did = rec.record(DecisionDoc(run_id=run_id, symbol="PYTH", symbol_group="majors",
                     signal={"fired": True}, indicators={"adx": 27.6}, voices=[], oracle=None,
                     coordinator={"action": "act", "rule": "all_voices_aligned"}))
    rec.attach_outcome(did, Outcome(pnl_pct=-0.3, exit_reason="flat_stall_exit"))
    lines = (tmp_path / run_id / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2                                  # the decision + the outcome patch
    assert json.loads(lines[0])["decision_id"] == did
    assert json.loads(lines[1]) == {"decision_id": did, "outcome": {"pnl_pct": -0.3, "pnl_usd": None,
            "exit_reason": "flat_stall_exit", "duration_min": None, "entry_price": None,
            "exit_price": None, "peak_pct": None}}
    assert decs.docs[did]["coordinator"]["action"] == "act"  # mongo got it too
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_decision_store.py -k "start or record" -v` → FAIL (no `recorder`).

- [ ] **Step 3: Implement**

```python
# contest_bot/decision_store/recorder.py
from __future__ import annotations
import json, pathlib
from datetime import datetime, timezone
from .models import SimulationDoc, DecisionDoc, Outcome
from .mongo import best_effort_upsert, get_collections

class DecisionRecorder:
    def __init__(self, run_dir: pathlib.Path, decs_coll=None):
        self._path = run_dir / "decisions.jsonl"
        self._coll = decs_coll
    def record(self, decision: DecisionDoc) -> str:
        d = decision.to_dict()
        self._append(d)
        if self._coll is not None:
            best_effort_upsert(self._coll, {"decision_id": d["decision_id"]}, d)
        return d["decision_id"]
    def attach_outcome(self, decision_id: str, outcome: Outcome) -> None:
        patch = {"decision_id": decision_id, "outcome": outcome.to_dict()}
        self._append(patch)                          # immutable: a new patch row
        if self._coll is not None:
            best_effort_upsert(self._coll, {"decision_id": decision_id}, {"outcome": outcome.to_dict()})
    def _append(self, obj: dict) -> None:
        with self._path.open("a") as fh:
            fh.write(json.dumps(obj) + "\n")

class SimulationRegistry:
    def __init__(self, root: pathlib.Path | str = None, sims_coll=None, decs_coll=None):
        self._root = pathlib.Path(root) if root else pathlib.Path(__file__).parent.parent / "decision_runs"
        if sims_coll is None and decs_coll is None:
            sims_coll, decs_coll = get_collections()
        self._sims, self._decs = sims_coll, decs_coll
        self._run_dir: pathlib.Path | None = None
    def start(self, sim: SimulationDoc) -> str:
        if not sim.run_id:
            import uuid; sim.run_id = uuid.uuid4().hex
        self._run_dir = self._root / sim.run_id
        self._run_dir.mkdir(parents=True, exist_ok=True)
        d = sim.to_dict()
        (self._run_dir / "simulation.json").write_text(json.dumps(d, indent=2))
        if self._sims is not None:
            best_effort_upsert(self._sims, {"run_id": sim.run_id}, d)
        return sim.run_id
    def recorder(self) -> DecisionRecorder:
        assert self._run_dir is not None, "call start() first"
        return DecisionRecorder(self._run_dir, self._decs)
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_decision_store.py -v` → PASS (all). The `decision_store/__init__.py` import now resolves.
- [ ] **Step 5: Commit**

```bash
git add contest_bot/decision_store/recorder.py contest_bot/decision_store/__init__.py contest_bot/tests/test_decision_store.py
git commit -m "feat(decision-store): SimulationRegistry + DecisionRecorder (JSONL durable + best-effort mongo)"
```

---

### Task 5: `sync` backfill CLI (JSONL → Mongo)

**Files:**
- Create: `contest_bot/decision_store/sync.py`
- Test: add to `contest_bot/tests/test_decision_store.py`

- [ ] **Step 1: Write the failing test**

```python
# append to contest_bot/tests/test_decision_store.py
from decision_store.sync import sync_run

def test_sync_loads_jsonl_into_coll(tmp_path):
    reg, sims, decs = _mk(tmp_path)
    run_id = reg.start(SimulationDoc(run_id="", strategy_id="jto", agent_group="default",
                       symbol_universe=["PYTH"], universe_label="majors", config={}, mode="paper", code_commit="abc"))
    rec = reg.recorder()
    did = rec.record(DecisionDoc(run_id=run_id, symbol="PYTH", symbol_group="majors", signal={}, indicators={}, voices=[], oracle=None, coordinator={"action": "act"}))
    fresh_sims, fresh_decs = _FakeColl(), _FakeColl()              # simulate a previously-down mongo
    n = sync_run(tmp_path / run_id, fresh_sims, fresh_decs)
    assert n == 1 and fresh_decs.docs[did]["symbol"] == "PYTH" and run_id in fresh_sims.docs
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_decision_store.py -k sync -v` → FAIL.
- [ ] **Step 3: Implement**

```python
# contest_bot/decision_store/sync.py
from __future__ import annotations
import json, pathlib, sys
from .mongo import best_effort_upsert, get_collections

def sync_run(run_dir: pathlib.Path, sims_coll, decs_coll) -> int:
    """Backfill one run's simulation.json + decisions.jsonl into Mongo. Returns #decisions synced."""
    sim = json.loads((run_dir / "simulation.json").read_text())
    best_effort_upsert(sims_coll, {"run_id": sim["run_id"]}, sim)
    merged: dict[str, dict] = {}
    for line in (run_dir / "decisions.jsonl").read_text().splitlines():
        if not line.strip(): continue
        row = json.loads(line)
        merged.setdefault(row["decision_id"], {}).update(row)   # fold outcome patches onto the decision
    for did, doc in merged.items():
        best_effort_upsert(decs_coll, {"decision_id": did}, doc)
    return len(merged)

def main() -> None:
    sims, decs = get_collections()
    root = pathlib.Path(__file__).parent.parent / "decision_runs"
    total = sum(sync_run(d, sims, decs) for d in root.iterdir() if (d / "simulation.json").exists())
    print(f"synced {total} decisions across {len(list(root.iterdir()))} runs")

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_decision_store.py -k sync -v` → PASS.
- [ ] **Step 5: Commit**

```bash
git add contest_bot/decision_store/sync.py contest_bot/tests/test_decision_store.py
git commit -m "feat(decision-store): sync CLI — backfill JSONL to Mongo (folds outcome patches)"
```

---

### Task 6: Bot integration

**Files:**
- Modify: `contest_bot/jto_breakout_gecko_gated_contest_bot.py`
- Test: `contest_bot/tests/test_decision_store_integration.py`

**Context:** the bot already computes the panel (`_LOCAL_PANEL.run(market_state)` ~line 1191) returning voices + the coordinator action, the indicator snapshot (`_indicators.compute_latest` ~line 278), the oracle verdict (the `fundamentals_check`/`oracle_reject` path), and closes positions in `close_position` (~line 1363). Integration = assemble a `DecisionDoc` at each panel decision and `attach_outcome` on close. Map the in-memory `position` to its `decision_id` (store it on the position dict).

- [ ] **Step 1: Write the failing test** (a light fake — assert `record` is called with the right shape at a decision point, and `attach_outcome` on close; do NOT spin the full poll loop, per `feedback_lighter_tests`)

```python
# contest_bot/tests/test_decision_store_integration.py
def test_build_decision_doc_maps_panel_to_record():
    from jto_breakout_gecko_gated_contest_bot import build_decision_doc
    doc = build_decision_doc(
        run_id="r1", symbol="PYTH",
        snap={"adx": 27.6, "rsi": 67.0, "chop": 43.3, "adx_slope": 2.0, "adx_distance": 2.6, "chop_distance": 18.5},
        signal={"fired": True, "type": "breakout"},
        panel_voices=[{"name": "chart_analyst", "verdict": "abstain", "confidence": 0.0}],
        oracle={"verdict": "pass", "citations": 9, "grounded": True},
        coordinator={"action": "decline", "rule": "chart_below_threshold"})
    d = doc.to_dict()
    assert d["symbol"] == "PYTH" and d["indicators"]["adx_distance"] == 2.6
    assert d["coordinator"]["action"] == "decline" and d["market_context"] is None
```

- [ ] **Step 2: Run to verify it fails** — `pytest tests/test_decision_store_integration.py -v` → FAIL (`build_decision_doc` undefined).

- [ ] **Step 3: Implement the helper + wire the hooks**

```python
# in jto_breakout_gecko_gated_contest_bot.py — near the imports
from decision_store import SimulationRegistry, DecisionDoc, Outcome

# module-level, after config constants:
_SIM = SimulationRegistry()
_RUN_ID = _SIM.start_from_config()  # see below
_RECORDER = _SIM.recorder()

def build_decision_doc(run_id, symbol, snap, signal, panel_voices, oracle, coordinator) -> DecisionDoc:
    return DecisionDoc(
        run_id=run_id, symbol=symbol, symbol_group="majors",
        signal=signal,
        indicators={k: snap.get(k) for k in (
            "adx", "plus_di", "minus_di", "rsi", "mfi", "chop", "bb_width",
            "range_24h_pct", "ema_stack", "regime", "regime_1h",
            "adx_slope", "adx_distance", "chop_distance")},
        voices=panel_voices, oracle=oracle, coordinator=coordinator)
```

Add `start_from_config()` to `SimulationRegistry` (in `recorder.py`):
```python
    def start_from_config(self) -> str:
        import os, subprocess
        sha = subprocess.run(["git","rev-parse","--short","HEAD"], capture_output=True, text=True).stdout.strip()
        return self.start(SimulationDoc(
            run_id="", strategy_id="jto_breakout", agent_group=os.environ.get("AGENT_GROUP","default"),
            symbol_universe=os.environ.get("INSTRUMENTS","PYTH,WIF,JUP,RAY,JTO").split(","),
            universe_label=os.environ.get("UNIVERSE_LABEL","no-tax-majors"),
            config={"chart_min_conf": os.environ.get("GECKO_CHART_MIN_CONF","0.85"),
                    "max_daily_trades": os.environ.get("MAX_DAILY_TRADES","3"),
                    "max_concurrent": os.environ.get("MAX_CONCURRENT","2"),
                    "tp_pct": TAKE_PROFIT_PCT, "sl_pct": STOP_LOSS_PCT},
            mode="paper" if PAPER_TRADE else "live", code_commit=sha))
```

At the panel-decision site (right after `_LOCAL_PANEL.run(market_state)` resolves, ~line 1191), compute the 3 distance features from the snap and record:
```python
        snap["adx_slope"] = _indicators.adx_slope(adx_series)       # adx_series from adx_full
        snap["adx_distance"] = _indicators.adx_distance(snap.get("adx"))
        snap["chop_distance"] = _indicators.chop_distance(snap.get("chop"))
        _did = _RECORDER.record(build_decision_doc(
            _RUN_ID, sym, snap, {"fired": True, "type": entry_type},
            [{"name": o.voice_name, "verdict": o.verdict, "confidence": o.confidence,
              "reasoning": (o.reasoning or "")[:300]} for o in local_decision.opinions],
            oracle_verdict_dict, {"action": local_decision.action, "rule": local_decision.rule}))
        if local_decision.action == "act":
            position["decision_id"] = _did       # carry the link to the outcome
```

In `close_position` (~line 1363), after computing `pnl_pct`/`exit_reason`:
```python
    if pos.get("decision_id"):
        _RECORDER.attach_outcome(pos["decision_id"], Outcome(
            pnl_pct=pnl_pct, pnl_usd=pnl_usd, exit_reason=exit_reason,
            duration_min=duration_min, entry_price=ep, exit_price=cur, peak_pct=pos.get("peak_pct")))
```

Wrap all recorder calls in `try/except` logging only (the recorder is best-effort but the *call sites* must also never break the loop).

- [ ] **Step 4: Run to verify pass** — `pytest tests/test_decision_store_integration.py -v` → PASS. Then `python -c "import ast; ast.parse(open('jto_breakout_gecko_gated_contest_bot.py').read())"` → no syntax error.
- [ ] **Step 5: Smoke + commit**

```bash
cd contest_bot && PAPER_TRADE=true timeout 70 python3 -u jto_breakout_gecko_gated_contest_bot.py > /tmp/ds_smoke.log 2>&1 &
sleep 65 && ls decision_runs/*/decisions.jsonl && fuser -k 8265/tcp
git add contest_bot/jto_breakout_gecko_gated_contest_bot.py contest_bot/decision_store/recorder.py contest_bot/tests/test_decision_store_integration.py
git commit -m "feat(decision-store): wire bot — record at decision points + attach outcomes on close"
```

---

### Task 7: gitignore the run dir + a README

**Files:**
- Modify: `.gitignore`
- Create: `contest_bot/decision_store/README.md`

- [ ] **Step 1:** Add `contest_bot/decision_runs/` to `.gitignore` (the JSONL is local + synced to Mongo; don't track).
- [ ] **Step 2:** Write `README.md`: what the store is, the schema, `python -m decision_store.sync` to backfill, how to query Mongo (`db.decisions.find({"run_id": ...})`), and the env tags (`AGENT_GROUP`, `UNIVERSE_LABEL`).
- [ ] **Step 3: Commit**

```bash
git add .gitignore contest_bot/decision_store/README.md
git commit -m "chore(decision-store): gitignore run dir + README"
```

---

## Spec coverage check
- Storage (Mongo + per-run JSONL durable + best-effort upsert) → Tasks 3,4. ✓
- Schema (simulations + decisions, future slots) → Task 2. ✓
- Granularity (record at decision points + outcome link) → Task 6. ✓
- ADX/CHOP distance+slope features → Task 1. ✓
- Mongo-down resilience (JSONL durable, recorder never raises, sync backfill) → Tasks 3,4,5. ✓
- Tests with light fakes, no live Atlas required → all tasks. ✓
- Future-fit (agent_group/universe_label/market_context slots, env-tagged) → Tasks 2,6. ✓
- Out of scope (market-context fill #2, analysis/backtest #3, multi-group runtime #4) → not in this plan. ✓
