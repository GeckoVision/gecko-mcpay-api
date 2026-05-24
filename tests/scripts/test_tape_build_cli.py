"""Smoke/wiring test for the tape build CLI — no network, no live bot.

Drives cmd_forward + summary + regimes through monkeypatched storage + a fake
OKX fetcher to prove the subcommands wire the adapters -> storage -> regime
labeling end to end (Pattern E: exercise the real path, not just units)."""

from __future__ import annotations

import argparse
import importlib.util
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
_TAPE = os.path.join(_REPO, "scripts", "calibration", "tape")


def _load(name: str):
    path = os.path.join(_TAPE, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"tape_{name}", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _synthetic_okx_page(start_ts: int, n: int, step_ms: int, rising: bool) -> dict:
    """OKX-shaped descending page of confirmed bars."""
    rows = []
    for k in range(n):
        ts = start_ts + k * step_ms
        price = 1.0 + (k * 0.02 if rising else -k * 0.0)
        rows.append(
            [
                str(ts),
                str(price),
                str(price * 1.01),
                str(price * 0.99),
                str(price),
                "100",
                "100",
                "1000",
                "1",
            ]
        )
    rows.sort(key=lambda r: int(r[0]), reverse=True)  # OKX is newest-first
    return {"code": "0", "msg": "", "data": rows}


def test_forward_then_summary_then_regimes(tmp_path, monkeypatch, capsys) -> None:
    build = _load("build_tape")
    storage = build.storage  # the exact module instance the CLI uses

    # redirect all storage to tmp
    monkeypatch.setattr(storage, "TAPE_DIR", str(tmp_path))
    monkeypatch.setattr(storage, "INDEX_PATH", str(tmp_path / "tape_index.json"))

    # fake OKX fetcher: one ascending page of 120 bars, deterministic
    def fake_fetch(url, params):
        return _synthetic_okx_page(1_700_000_000_000, 120, 300_000, rising=True)

    orig = build.okx.fetch_history

    def patched_fetch_history(sym, tf, **kw):
        kw.pop("fetcher", None)
        return orig(sym, tf, fetcher=fake_fetch, sleeper=lambda _s: None, **kw)

    monkeypatch.setattr(build.okx, "fetch_history", patched_fetch_history)

    # forward on a tiny universe
    ns = argparse.Namespace(symbols="PYTH", tfs="5m", sleep=0.0)
    build.cmd_forward(ns)

    # the tape now exists
    assert storage.load_tape("PYTH", "5m"), "forward should have written bars"

    # summary runs without error and reports the symbol
    build.cmd_summary(argparse.Namespace())
    out = capsys.readouterr().out
    assert "PYTH" in out
    assert "TAPE COVERAGE SUMMARY" in out

    # regimes labels the tape and reports a distribution
    build.cmd_regimes(argparse.Namespace(write=False))
    out2 = capsys.readouterr().out
    assert "REGIME DISTRIBUTION" in out2
    assert "trend_up" in out2
