"""
Decision-correctness tests for the trailing stop engine. Each
test asserts a SPECIFIC stop level for a known candle sequence,
and specifically proves the stop only ever moves in the
protective direction, never back, and is scoped correctly with
a small window. LONG and SHORT are mirror images of each other,
tested in parallel.
"""

from core.trailing_stop import TrailingStopEngine, LONG, SHORT


# -- LONG --

def test_start_seeds_the_stop_at_the_breakout_candle_low():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)

    assert ts.get_stop("TCS") == 100.0
    assert ts.get_direction("TCS") == LONG


def test_long_stop_ratchets_up_when_rolling_low_rises():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)

    ts.update_on_candle_close("TCS", candle_low=102.0, candle_high=103.0)
    ts.update_on_candle_close("TCS", candle_low=104.0, candle_high=105.0)
    # Window is [100, 102, 104] here (start's low still counted),
    # min is 100 -- stop should NOT have moved yet.
    assert ts.get_stop("TCS") == 100.0

    ts.update_on_candle_close("TCS", candle_low=106.0, candle_high=107.0)
    # Window now [102, 104, 106] (100 fell out) -- min is 102,
    # higher than current stop of 100 -- ratchets up.
    assert ts.get_stop("TCS") == 102.0


def test_long_stop_never_moves_down_on_a_lower_candle():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)
    ts.update_on_candle_close("TCS", 105.0, 106.0)
    ts.update_on_candle_close("TCS", 108.0, 109.0)
    ts.update_on_candle_close("TCS", 110.0, 111.0)
    stop_before = ts.get_stop("TCS")
    assert stop_before > 100.0

    # A sharp pullback candle -- must not drag the stop back down.
    ts.update_on_candle_close("TCS", 90.0, 95.0)

    assert ts.get_stop("TCS") == stop_before


def test_long_is_hit_true_only_at_or_below_the_current_stop():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)

    assert ts.is_hit("TCS", 100.5) is False
    assert ts.is_hit("TCS", 100.0) is True
    assert ts.is_hit("TCS", 99.0) is True


# -- SHORT (mirror image) --

def test_start_seeds_the_short_stop_at_the_breakdown_candle_high():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=SHORT)

    assert ts.get_stop("TCS") == 100.0
    assert ts.get_direction("TCS") == SHORT


def test_short_stop_ratchets_down_when_rolling_high_falls():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=SHORT)

    ts.update_on_candle_close("TCS", candle_low=97.0, candle_high=98.0)
    ts.update_on_candle_close("TCS", candle_low=95.0, candle_high=96.0)
    # Window is [100, 98, 96] here (start's high still counted),
    # max is 100 -- stop should NOT have moved yet.
    assert ts.get_stop("TCS") == 100.0

    ts.update_on_candle_close("TCS", candle_low=93.0, candle_high=94.0)
    # Window now [98, 96, 94] (100 fell out) -- max is 98, lower
    # than current stop of 100 -- ratchets down.
    assert ts.get_stop("TCS") == 98.0


def test_short_stop_never_moves_up_on_a_higher_candle():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=SHORT)
    ts.update_on_candle_close("TCS", 94.0, 95.0)
    ts.update_on_candle_close("TCS", 91.0, 92.0)
    ts.update_on_candle_close("TCS", 89.0, 90.0)
    stop_before = ts.get_stop("TCS")
    assert stop_before < 100.0

    # A sharp bounce candle -- must not drag the stop back up.
    ts.update_on_candle_close("TCS", 98.0, 110.0)

    assert ts.get_stop("TCS") == stop_before


def test_short_is_hit_true_only_at_or_above_the_current_stop():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=SHORT)

    assert ts.is_hit("TCS", 99.5) is False
    assert ts.is_hit("TCS", 100.0) is True
    assert ts.is_hit("TCS", 101.0) is True


# -- shared behaviour --

def test_symbol_with_no_active_stop_is_never_hit():
    ts = TrailingStopEngine(window=3)
    assert ts.is_hit("NOPE", 0.01) is False
    assert ts.get_stop("NOPE") is None
    assert ts.get_direction("NOPE") is None
    assert ts.update_on_candle_close("NOPE", 50.0, 51.0) is None


def test_clear_removes_the_symbols_state():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)
    ts.clear("TCS")

    assert ts.get_stop("TCS") is None
    assert ts.is_hit("TCS", 1.0) is False


def test_export_state_then_load_state_reproduces_the_same_long_stop():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=LONG)
    ts.update_on_candle_close("TCS", 105.0, 106.0)
    ts.update_on_candle_close("TCS", 108.0, 109.0)
    ts.update_on_candle_close("TCS", 110.0, 111.0)
    stop_before = ts.get_stop("TCS")

    snapshot = ts.export_state()

    restarted = TrailingStopEngine(window=3)
    restarted.load_state(snapshot)

    assert restarted.get_stop("TCS") == stop_before
    assert restarted.get_direction("TCS") == LONG

    # And the restored rolling window must still behave the
    # same way going forward -- not silently reset.
    restarted.update_on_candle_close("TCS", 50.0, 51.0)  # sharp pullback
    assert restarted.get_stop("TCS") == stop_before  # unmoved


def test_export_state_then_load_state_reproduces_the_same_short_stop():
    ts = TrailingStopEngine(window=3)
    ts.start("TCS", 100.0, direction=SHORT)
    ts.update_on_candle_close("TCS", 94.0, 95.0)
    ts.update_on_candle_close("TCS", 91.0, 92.0)
    ts.update_on_candle_close("TCS", 89.0, 90.0)
    stop_before = ts.get_stop("TCS")

    snapshot = ts.export_state()

    restarted = TrailingStopEngine(window=3)
    restarted.load_state(snapshot)

    assert restarted.get_stop("TCS") == stop_before
    assert restarted.get_direction("TCS") == SHORT

    restarted.update_on_candle_close("TCS", 98.0, 150.0)  # sharp bounce
    assert restarted.get_stop("TCS") == stop_before  # unmoved


def test_load_state_defaults_missing_direction_to_long_for_old_snapshots():
    """A snapshot saved before shorts existed has no 'direction'
    key -- must restore as LONG, not crash."""
    ts = TrailingStopEngine(window=3)
    ts.load_state({"TCS": {"stop": 100.0, "recent_lows": [100.0]}})

    assert ts.get_stop("TCS") == 100.0
    assert ts.get_direction("TCS") == LONG
