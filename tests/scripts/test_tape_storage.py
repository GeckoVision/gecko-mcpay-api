"""TDD for the tape storage layer — canonical shape + idempotent append +
exit_reconciliation --cached compatibility."""

from __future__ import annotations

import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_ST = os.path.join(_REPO, "scripts", "calibration", "tape", "storage.py")

_spec = importlib.util.spec_from_file_location("tape_storage", _ST)
assert _spec and _spec.loader
storage = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(storage)


def _candle(ts: float, c: float = 1.0) -> dict[str, float]:
    return {"ts": ts, "open": c, "high": c, "low": c, "close": c, "volume": 10.0}


def test_normalize_dedupes_and_sorts() -> None:
    out = storage.normalize([_candle(3000), _candle(1000), _candle(2000), _candle(1000, 9.0)])
    assert [c["ts"] for c in out] == [1000, 2000, 3000]
    # last write wins on duplicate ts
    assert out[0]["close"] == 9.0
    assert set(out[0]) == set(storage.CANDLE_KEYS)


def test_write_and_load_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "TAPE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "INDEX_PATH", str(tmp_path / "tape_index.json"))
    n = storage.write_tape("PYTH", "5m", [_candle(2000), _candle(1000)])
    assert n == 2
    loaded = storage.load_tape("PYTH", "5m")
    assert [c["ts"] for c in loaded] == [1000, 2000]


def test_append_is_idempotent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "TAPE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "INDEX_PATH", str(tmp_path / "tape_index.json"))
    storage.write_tape("WIF", "1H", [_candle(1000), _candle(2000)])
    # append overlapping + new
    added, total = storage.append_tape("WIF", "1H", [_candle(2000), _candle(3000)])
    assert added == 1  # only ts=3000 is new
    assert total == 3
    # re-append the SAME -> nothing added, no dupes
    added2, total2 = storage.append_tape("WIF", "1H", [_candle(2000), _candle(3000)])
    assert added2 == 0
    assert total2 == 3
    assert [c["ts"] for c in storage.load_tape("WIF", "1H")] == [1000, 2000, 3000]


def test_load_tape_as_cached_shape_matches_exit_reconciliation(tmp_path, monkeypatch) -> None:
    """The assembled mapping must be {sym: [candle...]} with the exact keys that
    chart_floor_calibration.enrich indexes (x['ts'], x['open'], ...)."""
    monkeypatch.setattr(storage, "TAPE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "INDEX_PATH", str(tmp_path / "tape_index.json"))
    storage.write_tape("PYTH", "5m", [_candle(1000), _candle(2000)])
    storage.write_tape("BTC", "5m", [_candle(1000)])
    cached = storage.load_tape_as_cached(["PYTH", "BTC", "ABSENT"], "5m")
    assert set(cached) == {"PYTH", "BTC"}  # ABSENT skipped
    candle = cached["PYTH"][0]
    for k in ("ts", "open", "high", "low", "close", "volume"):
        assert k in candle


def test_index_roundtrip_and_list_tapes(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(storage, "TAPE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "INDEX_PATH", str(tmp_path / "tape_index.json"))
    storage.write_tape("SOL", "4H", [_candle(1000)])
    storage.write_tape("BTC", "1H", [_candle(1000)])
    meta = storage.tape_meta(storage.load_tape("SOL", "4H"))
    storage.write_index({"SOL_4H": {"symbol": "SOL", "tf": "4H", **meta}}, "2026-05-23")
    idx = storage.load_index()
    assert idx["generated"] == "2026-05-23"
    assert idx["tapes"]["SOL_4H"]["bars"] == 1
    assert set(storage.list_tapes()) == {("SOL", "4H"), ("BTC", "1H")}
