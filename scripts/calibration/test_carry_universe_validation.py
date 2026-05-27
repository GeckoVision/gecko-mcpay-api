"""Unit tests for ``carry_universe_validation`` — Sprint 4 S4-1 + Sprint 4.5.

Per ``feedback_lighter_tests``: synthetic legs data + monkeypatch on the
file-loader; no real Binance data needed. Tests cover:
- ``_bar_at`` leakage-safe forward-fill (never peeks at unclosed bars)
- ``build()`` cross-sectional weekly book on synthetic 50-coin data
- ``render_verdict()`` gate logic + verdict-block taxonomy
- ``load_universe`` filtering (subset for testing)
- Sprint 4.5: ``pbo_sweep`` + ``pbo_branch`` classification
"""

from __future__ import annotations

import json
import math
import os

import pytest

from scripts.calibration import carry_universe_validation as cuv
from scripts.calibration import overfitting_rigor as ofr_local


# ── Auto-mock the heavy PBO compute for ALL tests in this file ─────────
# pbo_by_coin under time_20 (n_bins=20) does C(20,10)=184k combinations and
# is intrinsically minutes-slow even on small data. PBO math is covered by
# overfitting_rigor's own tests; tests in this file verify orchestration.
# Per-test monkeypatches (e.g. TestPboSweep) take precedence over this
# autouse default within their own test scope.
@pytest.fixture(autouse=True)
def _fast_pbo_default(monkeypatch):
    def fast_pbo_by_coin(per_coin, n_bins=10):
        return ofr_local.PBOResult(
            pbo=0.15, n_combinations=42, n_variants=10, median_logit=0.5,
        )
    monkeypatch.setattr(cuv.cx, "pbo_by_coin", fast_pbo_by_coin)


class TestBarAt:
    def test_returns_none_when_no_closed_bar_yet(self):
        ts_sorted = [1000, 2000, 3000]
        bars = {1000: 10.0, 2000: 20.0, 3000: 30.0}
        # interval = 1000ms; at t=500 no bar has closed yet
        assert cuv._bar_at(ts_sorted, bars, interval_ms=1000, t=500) is None

    def test_returns_close_of_most_recently_closed_bar(self):
        ts_sorted = [1000, 2000, 3000]
        bars = {1000: 10.0, 2000: 20.0, 3000: 30.0}
        # at t=2500, the bar opened at 2000 hasn't closed yet (closes at 3000);
        # so the most recent closed bar is the one opened at 1000.
        assert cuv._bar_at(ts_sorted, bars, interval_ms=1000, t=2500) == 10.0
        # at t=3001, the bar opened at 2000 just closed.
        assert cuv._bar_at(ts_sorted, bars, interval_ms=1000, t=3001) == 20.0

    def test_never_peeks_at_unclosed_bar(self):
        # Bar opens at t=1000, closes at t=1000+1000=2000.
        # At t=1500 (mid-bar), we must NOT return that bar's close.
        ts_sorted = [0, 1000]
        bars = {0: 5.0, 1000: 15.0}
        assert cuv._bar_at(ts_sorted, bars, interval_ms=1000, t=1500) == 5.0


class TestLoadUniverse:
    def test_raises_when_universe_file_missing(self, monkeypatch, tmp_path):
        monkeypatch.setattr(cuv, "UNIVERSE_PATH", str(tmp_path / "nope.json"))
        with pytest.raises(FileNotFoundError, match="frozen universe missing"):
            cuv.load_universe()

    def test_coin_filter_narrows_ranking(self, monkeypatch, tmp_path):
        fake_universe = {
            "selected_at": "2026-05-26T00:00:00Z",
            "n": 3,
            "ranking": [
                {"symbol": "BTC", "perp_symbol": "BTC/USDT:USDT", "spot_symbol": "BTC/USDT"},
                {"symbol": "ETH", "perp_symbol": "ETH/USDT:USDT", "spot_symbol": "ETH/USDT"},
                {"symbol": "SOL", "perp_symbol": "SOL/USDT:USDT", "spot_symbol": "SOL/USDT"},
            ],
        }
        path = tmp_path / "u.json"
        path.write_text(json.dumps(fake_universe))
        monkeypatch.setattr(cuv, "UNIVERSE_PATH", str(path))
        ranking = cuv.load_universe(["BTC", "SOL"])
        assert {r["symbol"] for r in ranking} == {"BTC", "SOL"}


class TestBuild:
    def _synth_legs(self, n_coins: int, n_events: int, fund_per_coin: list[float]):
        """Synthesize per-coin legs with constant funding (so cross-sectional
        ranking is stable) and zero perp/spot returns (basis-neutral)."""
        legs: dict[str, dict[int, tuple[float, float, float]]] = {}
        ts_step = 8 * 3600 * 1000  # 8h in ms
        for i in range(n_coins):
            coin = f"C{i:02d}"
            f = fund_per_coin[i]
            legs[coin] = {
                t * ts_step: (f, 0.0, 0.0) for t in range(n_events)
            }
        return legs

    def test_empty_legs_returns_empty_port(self):
        port, per_coin = cuv.build({}, k=3, flip_cost=0.002)
        assert port == []
        assert per_coin == {}

    def test_insufficient_coins_skips_week(self):
        # Only 2 coins, K=3 → never enough to form a book
        legs = self._synth_legs(2, 100, [0.001, -0.001])
        port, per_coin = cuv.build(legs, k=3, flip_cost=0.002)
        assert port == []

    def test_cross_sectional_picks_top_and_bottom_funding(self):
        # 10 coins: funding values 0..9 (basis-points style). K=3 means we short
        # top-3 (coins 7,8,9 with highest funding +1 mult) + long bottom-3
        # (coins 0,1,2 with lowest funding -1 mult).
        # With zero perp/spot returns, leg_return per event = mult * funding;
        # mean across 6 legs = mean(+7+8+9-0-1-2)/6 = 21/6 = 3.5 per event.
        # First-event-of-week subtracts flip_cost from each new book entry.
        legs = self._synth_legs(10, 50, [i * 0.001 for i in range(10)])
        port, per_coin = cuv.build(legs, k=3, flip_cost=0.002)
        # 50 events, W=21 → first rebalance at i=21; ~1 full week of 21 events
        # before all_ts runs out at idx 42. Quick smoke: port should be non-empty
        # and mostly-positive after costs.
        assert len(port) > 0
        # Average per-event return should be near (21*0.001/6) = 0.0035
        # before costs; modestly less with the per-coin flip_cost amortised.
        avg = sum(port) / len(port)
        assert avg > 0  # positive cross-sectional capture
        # Each of the 6 selected coins should have entries; the 4 middle coins
        # (3,4,5,6) should NOT.
        for c in ("C00", "C01", "C02", "C07", "C08", "C09"):
            assert per_coin[c], f"selected coin {c} should have entries"
        for c in ("C03", "C04", "C05", "C06"):
            assert per_coin[c] == [], f"unselected coin {c} should NOT have entries"


class TestRenderVerdict:
    def _synth_port(self, mean_per_event: float, n: int = 800) -> list[float]:
        # Constant per-event return; simplest synthetic that lets us reason
        # about Sharpe + Brier-equivalent gates.
        return [mean_per_event] * n

    def test_constant_positive_port_emits_a_verdict_block(self):
        # 800 events at +0.0001 per-event → annualized ~10.95% (EVENTS_YR=1095)
        port = self._synth_port(0.0001, n=800)
        per_coin = {"C00": [(i, 0.0001) for i in range(200)]}
        universe = [{"symbol": "C00", "perp_symbol": "x", "spot_symbol": "y"}]
        v = cuv.render_verdict(
            k=3, flip_cost=0.002, universe=universe, available=universe,
            port=port, per_coin=per_coin,
        )
        assert "VERDICT:" in v["text"]
        assert v["verdict"] in {"DEPLOY", "PAPER ONLY", "REJECT"}
        assert "Kamino" in v["text"]
        # annualized_pct ≈ 0.0001 * 1095 * 100 = 10.95%; > Kamino 6.5% floor
        assert v["kamino_benchmark_beaten"] is True
        # Constant returns produce stddev=0 → can't compute Sharpe properly →
        # DSR fails AND there is no drawdown (Calmar undefined / inf) so tail
        # gate fails too. Mean is positive, CI lower-bound > 0 (collapses to
        # mean on constant input), so verdict lands on PAPER ONLY (not DEPLOY,
        # not REJECT — exactly the intermediate state the gate is designed to
        # surface when something positive is happening but rigor isn't met).
        assert v["dsr"] < 0.95
        assert v["verdict"] == "PAPER ONLY"
        # Rationale must include the failed rigor gates that prevent DEPLOY
        assert "DSR" in v["rationale"] or "tail" in v["rationale"]

    def test_negative_port_rejects(self):
        port = self._synth_port(-0.0001, n=800)
        per_coin = {"C00": [(i, -0.0001) for i in range(200)]}
        universe = [{"symbol": "C00", "perp_symbol": "x", "spot_symbol": "y"}]
        v = cuv.render_verdict(
            k=3, flip_cost=0.002, universe=universe, available=universe,
            port=port, per_coin=per_coin,
        )
        assert v["verdict"] == "REJECT"
        assert v["kamino_benchmark_beaten"] is False

    def test_insufficient_data_short_circuits_reject(self):
        v = cuv.render_verdict(
            k=3, flip_cost=0.002, universe=[], available=[],
            port=[0.001], per_coin={},
        )
        assert v["verdict"] == "REJECT"
        assert "insufficient_data" in v["rationale"]

    def test_verdict_includes_all_six_gates(self):
        port = self._synth_port(0.0001, n=800)
        per_coin = {"C00": [(i, 0.0001) for i in range(200)]}
        universe = [{"symbol": "C00", "perp_symbol": "x", "spot_symbol": "y"}]
        v = cuv.render_verdict(
            k=3, flip_cost=0.002, universe=universe, available=universe,
            port=port, per_coin=per_coin,
        )
        gates = v["gates"]
        # The six rigor gates, all named in the dict
        expected = {
            "net carry CI excludes 0 (lower bound > 0)",
            "DSR >= 0.95",
            "PBO < 0.20",
            "%CPCV-paths Sharpe<0 < 25%",
            "tail OK (Calmar > 0 AND maxDD < 0)",
        }
        assert expected.issubset(gates)
        # Plus the Kamino-benchmark gate dynamic name
        assert any("Kamino" in g for g in gates)


class TestPboSweep:
    def _synthetic_per_coin(
        self, n_coins: int = 10, n_events: int = 200, mean_pnl: float = 0.0001
    ) -> dict[str, list[tuple[int, float]]]:
        ts_step = 8 * 3600 * 1000
        return {
            f"C{i:02d}": [(t * ts_step, mean_pnl + (i - n_coins / 2) * 1e-5) for t in range(n_events)]
            for i in range(n_coins)
        }

    def test_sweep_runs_all_four_strategies(self, monkeypatch):
        # Mock cx.pbo_by_coin: time_20 is C(20,10)=184k combos so the real
        # call is intrinsically slow in unit tests. PBO math is tested
        # elsewhere in overfitting_rigor's own tests; here we verify
        # orchestration shape only.
        from scripts.calibration import overfitting_rigor as ofr_local
        canned_returns = {n: 0.15 for n in cuv.PBO_PARTITION_STRATEGIES}  # all PASS
        def fake_pbo_by_coin(per_coin, n_bins=10):
            # Find which strategy this n_bins maps to
            name = next(
                (k for k, v in cuv.PBO_PARTITION_STRATEGIES.items() if v == n_bins),
                "?",
            )
            return ofr_local.PBOResult(
                pbo=canned_returns[name],
                n_combinations=42,
                n_variants=10,
                median_logit=0.5,
            )
        monkeypatch.setattr(cuv.cx, "pbo_by_coin", fake_pbo_by_coin)
        result = cuv.pbo_sweep({})  # input shape doesn't matter — fake ignores
        assert set(result.keys()) == {"time_10", "time_20", "time_5", "walk_forward_2"}
        for name, r in result.items():
            assert "pbo" in r
            assert "n_combinations" in r
            assert "n_bins" in r
            assert r["n_bins"] == cuv.PBO_PARTITION_STRATEGIES[name]

    def test_sweep_handles_degenerate_input_per_strategy(self, monkeypatch):
        # Single coin — pbo_by_coin returns nan with note. Mock to skip the
        # real (slow) compute; the orchestration should propagate NaN cleanly.
        import math
        from scripts.calibration import overfitting_rigor as ofr_local
        def fake_pbo_by_coin(per_coin, n_bins=10):
            return ofr_local.PBOResult(
                pbo=math.nan, n_combinations=0, n_variants=1, median_logit=math.nan,
                note="need >=2 coins",
            )
        monkeypatch.setattr(cuv.cx, "pbo_by_coin", fake_pbo_by_coin)
        result = cuv.pbo_sweep({})
        for name, r in result.items():
            assert "pbo" in r
            assert math.isnan(r["pbo"])
            assert r["note"] == "need >=2 coins"

    def test_sweep_swallows_per_strategy_exceptions(self, monkeypatch):
        # If pbo_by_coin raises (shouldn't normally, but defense-in-depth),
        # the sweep continues with an "err" note for that strategy.
        def flaky_pbo_by_coin(per_coin, n_bins=10):
            if n_bins == 20:
                raise RuntimeError("simulated PBO compute failure")
            from scripts.calibration import overfitting_rigor as ofr_local
            return ofr_local.PBOResult(0.10, 42, 10, 0.5)
        monkeypatch.setattr(cuv.cx, "pbo_by_coin", flaky_pbo_by_coin)
        result = cuv.pbo_sweep({})
        # 3 strategies return clean; time_20 should have an err note
        for name in ("time_10", "time_5", "walk_forward_2"):
            assert result[name]["pbo"] == 0.10
        assert "err" in result["time_20"]["note"].lower()

    def test_branch_classification_all_pass(self):
        sweep = {n: {"pbo": 0.10, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        assert cuv.pbo_branch(sweep) == "A_all_pass"

    def test_branch_classification_all_fail(self):
        sweep = {n: {"pbo": 0.30, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        assert cuv.pbo_branch(sweep) == "C_all_fail"

    def test_branch_classification_b1_walkforward_only_fails(self):
        sweep = {n: {"pbo": 0.10, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        sweep["walk_forward_2"]["pbo"] = 0.30
        assert cuv.pbo_branch(sweep) == "B_mixed_b1_walkforward_only_fails"

    def test_branch_classification_b2_time20_only_fails(self):
        sweep = {n: {"pbo": 0.10, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        sweep["time_20"]["pbo"] = 0.30
        assert cuv.pbo_branch(sweep) == "B_mixed_b2_time20_only_fails"

    def test_branch_classification_b3_time5_only_fails(self):
        sweep = {n: {"pbo": 0.10, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        sweep["time_5"]["pbo"] = 0.30
        assert cuv.pbo_branch(sweep) == "B_mixed_b3_time5_only_fails"

    def test_branch_classification_b_mixed_other(self):
        # time_5 AND time_20 fail — not one of the named B1/B2/B3 sub-branches
        sweep = {n: {"pbo": 0.10, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        sweep["time_5"]["pbo"] = 0.30
        sweep["time_20"]["pbo"] = 0.30
        assert cuv.pbo_branch(sweep) == "B_mixed_other"

    def test_branch_threshold_is_respected(self):
        # PBO 0.19 passes <0.20; PBO 0.21 fails. Verify the boundary.
        sweep = {n: {"pbo": 0.19, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        assert cuv.pbo_branch(sweep, threshold=0.20) == "A_all_pass"
        sweep = {n: {"pbo": 0.21, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        assert cuv.pbo_branch(sweep, threshold=0.20) == "C_all_fail"

    def test_branch_classification_nan_treated_as_fail(self):
        import math
        sweep = {n: {"pbo": math.nan, "n_bins": v} for n, v in cuv.PBO_PARTITION_STRATEGIES.items()}
        # NaN does not pass < threshold, so all fail = C_all_fail
        assert cuv.pbo_branch(sweep) == "C_all_fail"


class TestVerdictBlockTextFormat:
    def test_verdict_block_contains_required_sections_per_rigor_skill(self):
        port = [0.0001 + i * 1e-7 for i in range(800)]  # some variance
        per_coin = {f"C{i:02d}": [(j, port[j % len(port)]) for j in range(20)] for i in range(10)}
        universe = [{"symbol": f"C{i:02d}"} for i in range(10)]
        v = cuv.render_verdict(
            k=3, flip_cost=0.002, universe=universe, available=universe,
            port=port, per_coin=per_coin,
        )
        text = v["text"]
        # quant-backtest-rigor §6 verdict-block sections
        assert "PRIMARY METRICS:" in text
        assert "Deflated Sharpe Ratio:" in text
        assert "PBO:" in text
        assert "Max DD" in text
        assert "Calmar" in text
        assert "VERDICT:" in text
        assert "RATIONALE:" in text
