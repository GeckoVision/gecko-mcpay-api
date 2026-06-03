"""Shared technical indicators — pure Python, computed from DEX candles.

B1 (S40 Track B). The OKX 80-indicator API is CEX-only and not callable
from this bot's runtime, so we compute indicators in Python from the same
5m candles the bot already fetches via onchainos (DEX). These functions are
the single source of truth shared by the live bot's voices AND
backtest_entry.py.

Candles are ASCENDING (oldest-first) — get_candles sorts them (iter-3.11
fix). All series functions return a list aligned to the input, with `None`
during the warmup window.

`compute_latest(candles)` is the per-poll convenience: returns the latest
indicator snapshot a voice reasons over (adx, rsi, mfi, ema50, atr, bb).
"""

from __future__ import annotations


def ema(vals: list[float], n: int) -> list[float | None]:
    if len(vals) < n:
        return [None] * len(vals)
    k = 2 / (n + 1)
    out: list[float | None] = [None] * (n - 1)
    seed = sum(vals[:n]) / n
    out.append(seed)
    for v in vals[n:]:
        out.append(out[-1] * (1 - k) + v * k)  # type: ignore[operator]
    return out


def rsi(closes: list[float], n: int = 14) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    avg_g = sum(gains[:n]) / n
    avg_l = sum(losses[:n]) / n
    for i in range(n, len(closes)):
        if i > n:
            avg_g = (avg_g * (n - 1) + gains[i - 1]) / n
            avg_l = (avg_l * (n - 1) + losses[i - 1]) / n
        rs = avg_g / avg_l if avg_l > 0 else float("inf")
        out[i] = 100.0 if avg_l == 0 else 100 - (100 / (1 + rs))
    return out


def _wilder_smooth(vals: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(vals)
    if len(vals) < n:
        return out
    s = sum(vals[:n])
    out[n - 1] = s
    for i in range(n, len(vals)):
        s = s - (s / n) + vals[i]
        out[i] = s
    return out


def adx(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    n: int = 14,
) -> list[float | None]:
    m = len(closes)
    out: list[float | None] = [None] * m
    if m < 2 * n:
        return out
    tr, plus_dm, minus_dm = [0.0], [0.0], [0.0]
    for i in range(1, m):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )
    atr_s = _wilder_smooth(tr, n)
    pdm_s = _wilder_smooth(plus_dm, n)
    mdm_s = _wilder_smooth(minus_dm, n)
    dx: list[float | None] = [None] * m
    for i in range(m):
        if atr_s[i] and atr_s[i] != 0 and pdm_s[i] is not None and mdm_s[i] is not None:
            pdi = 100 * pdm_s[i] / atr_s[i]
            mdi = 100 * mdm_s[i] / atr_s[i]
            dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0
    first = next((i for i, v in enumerate(dx) if v is not None), None)
    if first is None or first + n > m:
        return out
    seed = sum(v for v in dx[first : first + n] if v is not None) / n  # type: ignore[arg-type]
    out[first + n - 1] = seed
    for i in range(first + n, m):
        if dx[i] is not None:
            out[i] = (out[i - 1] * (n - 1) + dx[i]) / n  # type: ignore[operator]
    return out


def adx_full(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    n: int = 14,
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Return (adx_series, plus_di_series, minus_di_series) aligned to input.

    The DI series are smoothed +DI / −DI lines (same Wilder smoothing used
    inside ``adx()``). These share the same warmup window as ADX — values
    are None until the first valid ADX bar.  ``compute_latest`` calls this
    instead of ``adx()`` so the directional components are available without
    recomputing the raw DMs a second time.
    """
    m = len(closes)
    none_series: list[float | None] = [None] * m
    if m < 2 * n:
        return none_series[:], none_series[:], none_series[:]

    tr, plus_dm, minus_dm = [0.0], [0.0], [0.0]
    for i in range(1, m):
        up = highs[i] - highs[i - 1]
        dn = lows[i - 1] - lows[i]
        plus_dm.append(up if (up > dn and up > 0) else 0.0)
        minus_dm.append(dn if (dn > up and dn > 0) else 0.0)
        tr.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )

    atr_s = _wilder_smooth(tr, n)
    pdm_s = _wilder_smooth(plus_dm, n)
    mdm_s = _wilder_smooth(minus_dm, n)

    adx_out: list[float | None] = [None] * m
    pdi_out: list[float | None] = [None] * m
    mdi_out: list[float | None] = [None] * m

    dx: list[float | None] = [None] * m
    for i in range(m):
        if atr_s[i] and atr_s[i] != 0 and pdm_s[i] is not None and mdm_s[i] is not None:
            pdi = 100 * pdm_s[i] / atr_s[i]  # type: ignore[operator]
            mdi = 100 * mdm_s[i] / atr_s[i]  # type: ignore[operator]
            pdi_out[i] = pdi
            mdi_out[i] = mdi
            dx[i] = 100 * abs(pdi - mdi) / (pdi + mdi) if (pdi + mdi) > 0 else 0.0

    first = next((i for i, v in enumerate(dx) if v is not None), None)
    if first is None or first + n > m:
        return adx_out, pdi_out, mdi_out

    seed = sum(v for v in dx[first : first + n] if v is not None) / n  # type: ignore[arg-type]
    adx_out[first + n - 1] = seed
    for i in range(first + n, m):
        if dx[i] is not None:
            adx_out[i] = (adx_out[i - 1] * (n - 1) + dx[i]) / n  # type: ignore[operator]

    return adx_out, pdi_out, mdi_out


def mfi(highs, lows, closes, vols, n: int = 14) -> list[float | None]:
    m = len(closes)
    out: list[float | None] = [None] * m
    if m <= n:
        return out
    tp = [(highs[i] + lows[i] + closes[i]) / 3 for i in range(m)]
    pos, neg = [0.0], [0.0]
    for i in range(1, m):
        rmf = tp[i] * vols[i]
        if tp[i] > tp[i - 1]:
            pos.append(rmf)
            neg.append(0.0)
        elif tp[i] < tp[i - 1]:
            pos.append(0.0)
            neg.append(rmf)
        else:
            pos.append(0.0)
            neg.append(0.0)
    for i in range(n, m):
        p = sum(pos[i - n + 1 : i + 1])
        ng = sum(neg[i - n + 1 : i + 1])
        out[i] = 100.0 if ng == 0 else 100 - (100 / (1 + p / ng))
    return out


def atr(
    highs: list[float], lows: list[float], closes: list[float], n: int = 14
) -> list[float | None]:
    m = len(closes)
    out: list[float | None] = [None] * m
    if m <= n:
        return out
    tr = [0.0]
    for i in range(1, m):
        tr.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )
    seed = sum(tr[1 : n + 1]) / n
    out[n] = seed
    for i in range(n + 1, m):
        out[i] = (out[i - 1] * (n - 1) + tr[i]) / n  # type: ignore[operator]
    return out


def bb(
    closes: list[float], n: int = 20, k: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    m = len(closes)
    lower: list[float | None] = [None] * m
    mid: list[float | None] = [None] * m
    upper: list[float | None] = [None] * m
    if m < n:
        return lower, mid, upper
    for i in range(n - 1, m):
        window = closes[i - n + 1 : i + 1]
        sma = sum(window) / n
        var = sum((x - sma) ** 2 for x in window) / n
        sd = var**0.5
        mid[i] = sma
        lower[i] = sma - k * sd
        upper[i] = sma + k * sd
    return lower, mid, upper


def chop(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    n: int = 14,
) -> list[float | None]:
    """Choppiness Index (CHOP) series aligned to input candles.

    CHOP = 100 * log10( sum(TR, n) / (max(high, n) - min(low, n)) ) / log10(n)

    Interpretation:
      > 61.8 — maximum chop (mean-reverting, momentum is -EV)
      < 38.2 — strongly trending (directional momentum applies)
      between — transitional

    Returns None for the first n-1 bars (warmup). Uses the same True Range
    definition as atr(): TR_i = max(H-L, |H-prev_C|, |L-prev_C|).
    """
    m = len(closes)
    out: list[float | None] = [None] * m
    if m <= n:
        return out
    import math

    # Build TR series (index 0 = first bar, TR[0]=0 by convention)
    tr = [0.0]
    for i in range(1, m):
        tr.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    for i in range(n, m):
        # sum of TR over window [i-n+1 .. i] (n bars)
        sum_tr = sum(tr[i - n + 1 : i + 1])
        hh = max(highs[i - n + 1 : i + 1])
        ll = min(lows[i - n + 1 : i + 1])
        denom = hh - ll
        if denom <= 0 or sum_tr <= 0:
            # flat candles / zero range — undefined; leave None
            continue
        out[i] = 100.0 * math.log10(sum_tr / denom) / math.log10(n)

    return out


def churn_ratio(closes: list[float], n: int = 24, cap: float = 50.0) -> float | None:
    """Path-inefficiency over the last n closes: Σ|Δclose| / |net Δ|.

    A clean directional move has churn ≈ 1 (path ≈ displacement). Bot churn /
    wash-like oscillation travels far but nets little → churn ≫ 1 (e.g. SOL
    overnight 2026-06-03: net 6.3% over a 55% path = 8.8×; XRP 19.7×). This is
    the "is this real movement or noise?" signal — the input to the
    oracle-says-no-to-noise gate.

    Returns None if < n+1 closes. When net ≈ 0 (pure round-tripping, maximal
    churn) returns `cap` rather than +inf so callers can threshold cleanly.
    """
    if len(closes) < n + 1:
        return None
    w = closes[-(n + 1) :]
    path = sum(abs(w[i] - w[i - 1]) for i in range(1, len(w)))
    net = abs(w[-1] - w[0])
    if path <= 0:
        return None  # perfectly flat window — undefined, not churn
    if net <= 1e-12:
        return cap
    return min(path / net, cap)


def reversal_rate(closes: list[float], n: int = 24) -> float | None:
    """Fraction of bar-to-bar direction flips over the last n closes, in [0, 1].

    ~0.5 = a coin-flip every bar (no directional conviction = oscillation/noise);
    low = a persistent one-way move. Pairs with churn_ratio: high churn + ~0.5
    reversals = the bot-churn regime. Flat (zero-move) bars are ignored."""
    if len(closes) < n + 1:
        return None
    w = closes[-(n + 1) :]
    dirs = [1 if w[i] > w[i - 1] else (-1 if w[i] < w[i - 1] else 0) for i in range(1, len(w))]
    nz = [d for d in dirs if d != 0]
    if len(nz) < 2:
        return None
    return sum(1 for i in range(1, len(nz)) if nz[i] != nz[i - 1]) / (len(nz) - 1)


def compute_latest(candles: list[dict]) -> dict:
    """Per-poll snapshot of the latest indicator values from a candle list
    (ascending, dicts with open/high/low/close/volume). Returns a dict the
    voices reason over; values are None when not enough warmup. bb_width is
    the band width as a % of mid (a volatility-compression / regime cue).
    chop is the Choppiness Index (n=14): >61.8 max chop, <38.2 trending."""
    if not candles:
        return {}
    highs = [c["high"] for c in candles]
    lows = [c["low"] for c in candles]
    closes = [c["close"] for c in candles]
    vols = [c.get("volume", 0.0) for c in candles]

    def _last(series: list) -> float | None:
        return next((v for v in reversed(series) if v is not None), None)

    bl, bm, bu = bb(closes, 20, 2.0)
    bl_v, bm_v, bu_v = _last(bl), _last(bm), _last(bu)
    bb_width = (
        ((bu_v - bl_v) / bm_v * 100) if (bl_v is not None and bu_v is not None and bm_v) else None
    )

    adx_s, pdi_s, mdi_s = adx_full(highs, lows, closes, 14)

    return {
        "price": closes[-1] if closes else None,
        "adx": _last(adx_s),
        "plus_di": _last(pdi_s),
        "minus_di": _last(mdi_s),
        "rsi": _last(rsi(closes, 14)),
        "mfi": _last(mfi(highs, lows, closes, vols, 14)),
        "ema9": _last(ema(closes, 9)),
        "ema21": _last(ema(closes, 21)),
        "ema50": _last(ema(closes, 50)),
        "ema200": _last(ema(closes, 200)),  # Strategy B "no downtrend" gate (S31)
        "atr": _last(atr(highs, lows, closes, 14)),
        "bb_lower": bl_v,
        "bb_mid": bm_v,
        "bb_upper": bu_v,
        "bb_width": bb_width,
        "chop": _last(chop(highs, lows, closes, 14)),
        # S33 churn/noise detector — "is this real movement or bot churn?"
        "churn_ratio": churn_ratio(closes, 24),
        "reversal_rate": reversal_rate(closes, 24),
    }


def compute_regime_1h(candles_1h: list[dict]) -> str:
    """Classify 1h-bar regime as TREND-UP / TREND-DOWN / CHOP.

    Uses ADX (n=14) + DI direction + CHOP (n=14) on the 1h candles.
    Requires at least 28 bars for a valid ADX warm-up (2×n); with fewer bars
    returns "CHOP" as the conservative unknown (don't trust an up-trend we
    haven't measured).

    Classification rules (CODE — never in a prompt):
      ADX >= 25 AND +DI > -DI → TREND-UP
      ADX >= 25 AND -DI > +DI → TREND-DOWN
      ADX <= 18 OR CHOP >= 61.8 → CHOP
      else → CHOP  (transitional — treat conservatively)

    The regime modulator in coordinator_rules.py gates on TREND-DOWN and CHOP
    to raise the chart floor for 5m longs.
    """
    if not candles_1h or len(candles_1h) < 28:
        return "CHOP"  # insufficient history — conservative default

    def _last(series: list) -> float | None:
        return next((v for v in reversed(series) if v is not None), None)

    highs = [c["high"] for c in candles_1h]
    lows = [c["low"] for c in candles_1h]
    closes = [c["close"] for c in candles_1h]

    adx_s, pdi_s, mdi_s = adx_full(highs, lows, closes, 14)
    chop_s = chop(highs, lows, closes, 14)

    adx_v = _last(adx_s)
    pdi_v = _last(pdi_s)
    mdi_v = _last(mdi_s)
    chop_v = _last(chop_s)

    if adx_v is None:
        return "CHOP"

    if adx_v >= 25:
        if pdi_v is not None and mdi_v is not None:
            return "TREND-UP" if pdi_v > mdi_v else "TREND-DOWN"
        return "TREND-UP"  # direction indeterminate but trending — mild default

    # ADX < 25 — check CHOP for strong choppiness confirmation
    if adx_v <= 18 or (chop_v is not None and chop_v >= 61.8):
        return "CHOP"

    # Transitional (18 < ADX < 25, CHOP < 61.8) — conservative
    return "CHOP"


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


__all__ = [
    "adx",
    "adx_distance",
    "adx_full",
    "adx_slope",
    "atr",
    "bb",
    "chop",
    "chop_distance",
    "compute_latest",
    "compute_regime_1h",
    "ema",
    "mfi",
    "rsi",
]
