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
        self.docs[flt["decision_id"]] = update["$set"]


def test_upsert_writes_to_coll():
    c = _FakeColl()
    ok = best_effort_upsert(c, {"decision_id": "d1"}, {"decision_id": "d1", "x": 1})
    assert ok is True and c.docs["d1"]["x"] == 1


def test_upsert_swallows_errors():
    class _Boom:
        def update_one(self, *a, **k):
            raise RuntimeError("mongo down")

    assert best_effort_upsert(_Boom(), {"decision_id": "d1"}, {"decision_id": "d1"}) is False
