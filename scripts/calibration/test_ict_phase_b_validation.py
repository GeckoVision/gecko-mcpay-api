"""Unit tests for the Phase B ICT validation harness (quant-analyst).

Focus on the LEAKAGE-PRONE machinery: the cross-timeframe point-in-time 4H<-15m
map (must never let a 15m entry see an unclosed 4H bar), the RR>=2.5 exit gate,
and the per-regime gross-EV aggregation. Pure, no I/O, no tape files needed.

Run: uv run pytest scripts/calibration/test_ict_phase_b_validation.py -q
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ict_phase_b_validation as ph  # noqa: E402


# ── Cross-timeframe point-in-time map ───────────────────────────────
def test_4h_map_picks_most_recent_closed_bar():
    # 4H bars open at t = 0, 4, 8, 12, 16 (hours, scaled). A 4H bar opening at t
    # CLOSES at t+4 (= next bar's open). A 15m query at t=9 may use the bar that
    # CLOSED at or before 9: bar opening at 4 closes at 8 (usable); bar opening at
    # 8 closes at 12 (NOT yet closed at 9). So the answer is index 1 (opened at 4).
    ts4 = [0.0, 4.0, 8.0, 12.0, 16.0]
    assert ph._map_4h_index(ts4, 9.0) == 1
    # query at exactly t=8: bar opened at 4 closes at 8 -> usable; bar opened at 8
    # closes at 12 -> not closed. answer index 1.
    assert ph._map_4h_index(ts4, 8.0) == 1
    # query at t=12: bar opened at 8 closes at 12 -> usable; answer index 2.
    assert ph._map_4h_index(ts4, 12.0) == 2
    # query at t=16: bar opened at 12 closes at 16 -> usable; answer index 3.
    assert ph._map_4h_index(ts4, 16.0) == 3


def test_4h_map_returns_none_before_first_close():
    # Before the first 4H bar has CLOSED (i.e. before the 2nd bar's open), nothing
    # is usable -> None. This is the warmup guard against cross-tf lookahead.
    ts4 = [0.0, 4.0, 8.0]
    assert ph._map_4h_index(ts4, 3.9) is None
    assert ph._map_4h_index(ts4, 0.0) is None


def test_4h_map_never_returns_unclosed_bar():
    # Property: the returned bar's CLOSE (next-open) must be <= query. Sweep many
    # queries and assert no future-bar leak.
    ts4 = [float(4 * k) for k in range(50)]
    for q in [x * 0.5 for x in range(2, 400)]:
        k = ph._map_4h_index(ts4, q)
        if k is None:
            continue
        close_k = ts4[k + 1] if k + 1 < len(ts4) else float("inf")
        assert close_k <= q, f"leaked an unclosed 4H bar at query {q} (idx {k})"


# ── RR>=2.5 exit gate ───────────────────────────────────────────────
def _flat_15m(prices: list[float]) -> dict:
    n = len(prices)
    return {
        "ts": [i * 900_000 for i in range(n)],
        "open": prices[:],
        "high": [p * 1.001 for p in prices],
        "low": [p * 0.999 for p in prices],
        "close": prices[:],
        "atr14": [None] * n,
    }


def test_system_exit_skips_when_rr_below_threshold():
    # Entry just below a near BSL -> tiny reward; SL far below -> big risk -> RR<2.5.
    # Construct: prior-M highs ~ 100.5 (so TP=100.5), entry=100.0, sweep_low=90.0
    # -> risk=10, reward=0.5 -> RR=0.05 -> skip (None).
    prices = [100.5] * ph.SYS_BSL_LOOKBACK + [100.0, 100.2, 100.4]
    c = _flat_15m(prices)
    # override the prior highs to exactly 100.5
    for j in range(ph.SYS_BSL_LOOKBACK):
        c["high"][j] = 100.5
    entry_idx = ph.SYS_BSL_LOOKBACK
    res = ph.simulate_system_exit(c, entry_idx, sweep_low=90.0)
    assert res is None  # RR gate rejects


def test_system_exit_accepts_when_rr_met_and_hits_tp():
    # TP=110 (prior high), entry=100, sweep_low=98 -> risk≈2, reward=10 -> RR≈5.
    # Then price rallies to >=110 -> TP hit, gross ≈ +10%.
    n_pre = ph.SYS_BSL_LOOKBACK
    prices = [105.0] * n_pre + [100.0, 104.0, 108.0, 112.0]
    c = _flat_15m(prices)
    for j in range(n_pre):
        c["high"][j] = 110.0  # BSL = 110
    entry_idx = n_pre
    # disable the high*1.001 inflation interfering with the exact TP read:
    res = ph.simulate_system_exit(c, entry_idx, sweep_low=98.0)
    assert res is not None
    gross, rr = res
    assert rr >= ph.SYS_MIN_RR
    # TP at 110 from entry 100 -> +10% exactly
    assert abs(gross - 10.0) < 1e-6


def test_system_exit_hits_sl():
    # TP=110 (RR ok), but price falls to the SL (sweep_low - tick) -> negative gross.
    n_pre = ph.SYS_BSL_LOOKBACK
    prices = [105.0] * n_pre + [100.0, 99.0, 97.5]  # falls through sweep_low=98
    c = _flat_15m(prices)
    for j in range(n_pre):
        c["high"][j] = 110.0
    entry_idx = n_pre
    res = ph.simulate_system_exit(c, entry_idx, sweep_low=98.0)
    assert res is not None
    gross, rr = res
    assert gross < 0  # stopped out


# ── Per-regime aggregation ──────────────────────────────────────────
def test_gross_ev_ci_partitions_by_tape():
    cands = [
        ph.Cand("A", 0, "trend_up", 2.0),
        ph.Cand("A", 1, "trend_up", 2.0),
        ph.Cand("B", 0, "chop", -1.0),
    ]
    r = ph.gross_ev_ci(cands)
    assert r["n"] == 3
    # mean = (2+2-1)/3 = 1.0
    assert abs(r["gross_ev"] - 1.0) < 1e-9


def test_analyze_primitive_regime_split():
    fired = [ph.Cand("A", i, "trend_up", 3.0) for i in range(5)] + [
        ph.Cand("A", 10 + i, "chop", -2.0) for i in range(5)
    ]
    notf = [ph.Cand("A", 100 + i, "trend_up", 0.0) for i in range(5)]
    a = ph.analyze_primitive("x", fired, notf)
    assert a["regimes"]["trend_up"]["gross_ev"] > 0
    assert a["regimes"]["chop"]["gross_ev"] < 0
    assert a["regimes"]["trend_up"]["n_fired"] == 5


def test_fixed_forward_return_math():
    c = {"close": [100.0, 110.0, 121.0]}
    # horizon 1 from idx 0: (110-100)/100 = +10%
    assert abs(ph.fixed_forward_return(c, 0, 1) - 10.0) < 1e-9
    # horizon 2 from idx 0: (121-100)/100 = +21%
    assert abs(ph.fixed_forward_return(c, 0, 2) - 21.0) < 1e-9
    # at last bar -> 0 (no forward bar)
    assert ph.fixed_forward_return(c, 2, 1) == 0.0
