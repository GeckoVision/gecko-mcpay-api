from decision_store.models import SimulationDoc, DecisionDoc, Outcome


def test_simulation_doc_roundtrip():
    s = SimulationDoc(
        run_id="r1",
        strategy_id="jto_breakout",
        agent_group="default",
        symbol_universe=["PYTH"],
        universe_label="no-tax-majors",
        config={"floor": 0.85},
        mode="paper",
        code_commit="abc",
    )
    d = s.to_dict()
    assert d["run_id"] == "r1" and d["agent_group"] == "default"
    assert SimulationDoc.from_dict(d).symbol_universe == ["PYTH"]


def test_decision_doc_has_future_slots_and_null_outcome():
    dec = DecisionDoc(
        run_id="r1",
        symbol="PYTH",
        symbol_group="majors",
        signal={"fired": True},
        indicators={"adx": 27.6},
        voices=[{"name": "chart_analyst", "verdict": "abstain", "confidence": 0.0}],
        oracle=None,
        coordinator={"action": "decline", "rule": "chart_below_threshold"},
    )
    d = dec.to_dict()
    assert d["market_context"] is None  # future slot present
    assert d["outcome"] is None  # unset until close
    assert d["decision_id"]  # auto-generated
    assert d["ts"]  # auto-stamped


def test_outcome_dict():
    o = Outcome(pnl_pct=-0.3, pnl_usd=-0.27, exit_reason="flat_stall_exit", duration_min=90)
    assert o.to_dict()["exit_reason"] == "flat_stall_exit"


from decision_store.mongo import best_effort_upsert


class _FakeColl:
    def __init__(self):
        self.docs = {}

    def update_one(self, flt, update, upsert=False):
        # Mirror Mongo $set semantics: merge into the existing doc keyed by the
        # filter's identity field (decision_id for decisions, run_id for simulations).
        key = flt.get("decision_id") or flt.get("run_id")
        self.docs.setdefault(key, {}).update(update["$set"])


def test_upsert_writes_to_coll():
    c = _FakeColl()
    ok = best_effort_upsert(c, {"decision_id": "d1"}, {"decision_id": "d1", "x": 1})
    assert ok is True and c.docs["d1"]["x"] == 1


def test_upsert_swallows_errors():
    class _Boom:
        def update_one(self, *a, **k):
            raise RuntimeError("mongo down")

    assert best_effort_upsert(_Boom(), {"decision_id": "d1"}, {"decision_id": "d1"}) is False


import json

from decision_store.recorder import DecisionRecorder, SimulationRegistry


def _mk(tmp_path):
    sims, decs = _FakeColl(), _FakeColl()
    reg = SimulationRegistry(root=tmp_path, sims_coll=sims, decs_coll=decs)
    return reg, sims, decs


def test_start_writes_simulation_json(tmp_path):
    reg, sims, _ = _mk(tmp_path)
    run_id = reg.start(
        SimulationDoc(
            run_id="",
            strategy_id="jto",
            agent_group="default",
            symbol_universe=["PYTH"],
            universe_label="majors",
            config={},
            mode="paper",
            code_commit="abc",
        )
    )
    assert (tmp_path / run_id / "simulation.json").exists()


def test_record_appends_jsonl_and_attach_outcome_patches(tmp_path):
    reg, sims, decs = _mk(tmp_path)
    run_id = reg.start(
        SimulationDoc(
            run_id="",
            strategy_id="jto",
            agent_group="default",
            symbol_universe=["PYTH"],
            universe_label="majors",
            config={},
            mode="paper",
            code_commit="abc",
        )
    )
    rec = reg.recorder()
    did = rec.record(
        DecisionDoc(
            run_id=run_id,
            symbol="PYTH",
            symbol_group="majors",
            signal={"fired": True},
            indicators={"adx": 27.6},
            voices=[],
            oracle=None,
            coordinator={"action": "act", "rule": "all_voices_aligned"},
        )
    )
    rec.attach_outcome(did, Outcome(pnl_pct=-0.3, exit_reason="flat_stall_exit"))
    lines = (tmp_path / run_id / "decisions.jsonl").read_text().strip().splitlines()
    assert len(lines) == 2  # the decision + the outcome patch
    assert json.loads(lines[0])["decision_id"] == did
    assert json.loads(lines[1]) == {
        "decision_id": did,
        "outcome": {
            "pnl_pct": -0.3,
            "pnl_usd": None,
            "exit_reason": "flat_stall_exit",
            "duration_min": None,
            "entry_price": None,
            "exit_price": None,
            "peak_pct": None,
        },
    }
    assert decs.docs[did]["coordinator"]["action"] == "act"  # mongo got it too
