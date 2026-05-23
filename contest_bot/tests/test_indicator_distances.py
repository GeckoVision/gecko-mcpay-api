from indicators import adx_distance, adx_slope, chop_distance


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
