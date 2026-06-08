from gecko_core.agents.state_reader import read_agent_state, scope_state_for_user


def test_read_returns_none_when_no_doc(monkeypatch):
    monkeypatch.setattr("gecko_core.agents.state_reader._collection", lambda name: None)
    assert read_agent_state("missing-agent") is None


class _FakeCollection:
    def __init__(self, doc):
        self._doc = doc

    def find_one(self, *args, **kwargs):
        return self._doc


def test_read_returns_none_when_doc_absent(monkeypatch):
    # _collection resolves (not the no-collection branch), but find_one returns
    # no document → the `not doc` path inside read_agent_state.
    fake = _FakeCollection(None)
    monkeypatch.setattr("gecko_core.agents.state_reader._collection", lambda name: fake)
    assert read_agent_state("a") is None


def test_read_merges_updated_at_into_state(monkeypatch):
    fake = _FakeCollection(
        {
            "agent_id": "a",
            "state": {"positions": [], "realized_pnl_today": 2.5},
            "updated_at": "2026-06-07T00:00:00+00:00",
        }
    )
    monkeypatch.setattr("gecko_core.agents.state_reader._collection", lambda name: fake)
    out = read_agent_state("a")
    assert out is not None
    assert out["realized_pnl_today"] == 2.5
    assert out["updated_at"] == "2026-06-07T00:00:00+00:00"


def test_scope_state_strips_config_fields():
    raw = {
        "positions": [{"symbol": "BTC"}],
        "realized_pnl_today": 1.2,
        "still_alive_at": "2026-06-07T00:00:00+00:00",
        "poll_count": 9,
        "spec": {"secret_params": 1},
        "total_spent_usd": 100.0,
    }
    out = scope_state_for_user(raw)
    assert "spec" not in out and "total_spent_usd" not in out
    assert out["realized_pnl_today"] == 1.2 and out["positions"][0]["symbol"] == "BTC"
