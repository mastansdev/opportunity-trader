from core.atr import compute_atr, true_range


def _c(high, low, close):
    return {"high": high, "low": low, "close": close}


# --------------------------------------------------
# true_range
# --------------------------------------------------

def test_true_range_with_no_prev_close_is_just_high_minus_low():
    assert true_range(_c(110, 100, 105)) == 10


def test_true_range_catches_a_gap_up_beyond_the_days_own_range():
    # High-low is only 5, but the candle gapped up from a prev
    # close of 90 -- true range must reflect the full 20-point move.
    candle = _c(high=110, low=105, close=108)
    assert true_range(candle, prev_close=90) == 20


def test_true_range_catches_a_gap_down_beyond_the_days_own_range():
    candle = _c(high=95, low=90, close=92)
    assert true_range(candle, prev_close=110) == 20


def test_true_range_uses_high_low_when_no_gap_present():
    candle = _c(high=105, low=100, close=102)
    assert true_range(candle, prev_close=101) == 5


# --------------------------------------------------
# compute_atr
# --------------------------------------------------

def test_compute_atr_returns_none_for_empty_candle_list():
    assert compute_atr([], period=14) is None


def test_compute_atr_single_candle_no_prior_close():
    candles = [_c(110, 100, 105)]
    assert compute_atr(candles, period=14) == 10


def test_compute_atr_averages_true_range_across_the_window():
    # Three candles, closes chosen so there's no gap between any of
    # them -- TR for each after the first is just high-low.
    candles = [
        _c(100, 95, 98),    # seed only (gives candle 2 a prev_close)
        _c(105, 98, 102),   # TR = max(7, |105-98|=7, |98-98|=0) = 7
        _c(108, 100, 104),  # TR = max(8, |108-102|=6, |100-102|=2) = 8
    ]
    # period=2 -> uses last 3 candles (period+1), averages TR of
    # candle 2 and candle 3 only (candle 1 is the seed for candle 2).
    atr = compute_atr(candles, period=2)
    assert atr == (7 + 8) / 2


def test_compute_atr_ignores_candles_older_than_period_plus_one():
    far_past = _c(1000, 1, 500)  # wildly different range, must be excluded
    candles = [
        far_past,
        _c(100, 95, 98),
        _c(105, 98, 102),
        _c(108, 100, 104),
    ]
    atr_with_far_past = compute_atr(candles, period=2)
    atr_without = compute_atr(candles[1:], period=2)
    assert atr_with_far_past == atr_without


def test_compute_atr_degrades_gracefully_with_fewer_candles_than_period():
    candles = [_c(105, 98, 102), _c(108, 100, 104)]
    atr = compute_atr(candles, period=14)
    expected = true_range(candles[1], prev_close=candles[0]["close"])
    assert atr == expected
