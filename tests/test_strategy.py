"""
Decision-correctness tests for Strategy. This is the class
of test the old bot was missing: not "did it run", but "did
it make the RIGHT call for a known scenario."
"""

from datetime import datetime

from core.orb_engine import OrbEngine
from core.strategy import Strategy


def _t(hh, mm, ss=0):
    return datetime(2026, 7, 22, hh, mm, ss)


def _orb_with_range(high=110.0, low=100.0):
    orb = OrbEngine()
    orb.update("TCS", low, _t(9, 15, 0))
    orb.update("TCS", high, _t(9, 20, 0))
    orb.update("TCS", 105.0, _t(9, 29, 59))
    orb.update("TCS", 105.0, _t(9, 30, 0))  # marks complete
    return orb


def _prime(strategy, symbol="TCS", close=105.0):
    """Change 1 (restart-seeding): a signal only fires once a symbol
    has been primed by at least one observed candle. These unit tests
    prime with an inside-range candle first, so the NEXT candle's
    cross is a genuine fresh cross."""
    strategy.note_candle_close(
        symbol, {"open": close, "high": close, "low": close, "close": close}
    )


def test_buy_signal_fires_on_candle_close_above_orb_high():
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)
    _prime(strategy)

    closed_candle = {"open": 108.0, "high": 112.0, "low": 107.0, "close": 111.0}

    assert strategy.is_buy_signal("TCS", closed_candle, already_open=False) is True


def test_no_signal_if_wick_touched_high_but_candle_closed_below():
    """
    The exact case the spec calls out: a fake poke above
    the roof must NOT trigger, only a genuine close.
    """
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)

    closed_candle = {"open": 108.0, "high": 115.0, "low": 107.0, "close": 109.5}

    assert strategy.is_buy_signal("TCS", closed_candle, already_open=False) is False


def test_no_signal_before_orb_range_is_complete():
    orb = OrbEngine()
    orb.update("TCS", 100.0, _t(9, 20, 0))  # range started, NOT complete
    strategy = Strategy(orb)

    closed_candle = {"open": 100.0, "high": 200.0, "low": 100.0, "close": 200.0}

    assert strategy.is_buy_signal("TCS", closed_candle, already_open=False) is False


def test_no_signal_if_position_already_open():
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)

    closed_candle = {"open": 108.0, "high": 112.0, "low": 107.0, "close": 111.0}

    assert strategy.is_buy_signal("TCS", closed_candle, already_open=True) is False


def test_no_signal_without_a_closed_candle():
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)

    assert strategy.is_buy_signal("TCS", None, already_open=False) is False


# -- short signal, mirror of every case above --

def test_short_signal_fires_on_candle_close_below_orb_low():
    orb = _orb_with_range(low=100.0)
    strategy = Strategy(orb)
    _prime(strategy)

    closed_candle = {"open": 101.0, "high": 102.0, "low": 97.0, "close": 98.0}

    assert strategy.is_short_signal("TCS", closed_candle, already_open=False) is True


def test_no_short_signal_if_wick_touched_low_but_candle_closed_above():
    orb = _orb_with_range(low=100.0)
    strategy = Strategy(orb)

    closed_candle = {"open": 101.0, "high": 102.0, "low": 95.0, "close": 100.5}

    assert strategy.is_short_signal("TCS", closed_candle, already_open=False) is False


def test_no_short_signal_before_orb_range_is_complete():
    orb = OrbEngine()
    orb.update("TCS", 100.0, _t(9, 20, 0))  # range started, NOT complete
    strategy = Strategy(orb)

    closed_candle = {"open": 100.0, "high": 100.0, "low": 1.0, "close": 1.0}

    assert strategy.is_short_signal("TCS", closed_candle, already_open=False) is False


def test_no_short_signal_if_position_already_open():
    orb = _orb_with_range(low=100.0)
    strategy = Strategy(orb)

    closed_candle = {"open": 101.0, "high": 102.0, "low": 97.0, "close": 98.0}

    assert strategy.is_short_signal("TCS", closed_candle, already_open=True) is False


def test_no_short_signal_without_a_closed_candle():
    orb = _orb_with_range(low=100.0)
    strategy = Strategy(orb)

    assert strategy.is_short_signal("TCS", None, already_open=False) is False


def test_buy_and_short_signals_are_mutually_exclusive_on_the_same_candle():
    """A single candle can't close both above the high and below
    the low -- sanity check that both signals agree with reality
    on an ordinary inside-range candle."""
    orb = _orb_with_range(high=110.0, low=100.0)
    strategy = Strategy(orb)

    closed_candle = {"open": 104.0, "high": 106.0, "low": 103.0, "close": 105.0}

    assert strategy.is_buy_signal("TCS", closed_candle, already_open=False) is False
    assert strategy.is_short_signal("TCS", closed_candle, already_open=False) is False


# -- #0b: fire ONCE on the fresh cross, not every candle beyond the range --

def test_buy_signal_fires_only_on_the_fresh_cross_not_while_it_stays_above():
    """2026-07-24 (evening): the standing-signal fix. First close
    above the high fires; a SECOND candle still above (with
    note_candle_close recording the state in between) must NOT
    re-fire -- that's the instant-refill bug."""
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)
    _prime(strategy)
    above = {"open": 111.0, "high": 113.0, "low": 111.0, "close": 112.0}

    # First cross fires.
    assert strategy.is_buy_signal("TCS", above, already_open=False) is True
    strategy.note_candle_close("TCS", above)

    # Still above on the next candle -> no fresh cross -> no signal.
    still_above = {"open": 112.0, "high": 114.0, "low": 112.0, "close": 113.0}
    assert strategy.is_buy_signal("TCS", still_above, already_open=False) is False


def test_buy_signal_re_fires_after_price_returns_inside_then_crosses_again():
    """Going back inside the range resets the memory, so a genuine
    SECOND breakout later in the day is a fresh cross and fires."""
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)
    _prime(strategy)

    above = {"open": 111.0, "high": 113.0, "low": 111.0, "close": 112.0}
    assert strategy.is_buy_signal("TCS", above, already_open=False) is True
    strategy.note_candle_close("TCS", above)

    inside = {"open": 108.0, "high": 109.0, "low": 107.0, "close": 108.0}
    strategy.note_candle_close("TCS", inside)  # back inside -> memory resets

    again = {"open": 111.0, "high": 113.0, "low": 111.0, "close": 112.0}
    assert strategy.is_buy_signal("TCS", again, already_open=False) is True


def test_restart_seeding_a_stock_already_above_its_range_does_not_fire_on_first_candle():
    """Change 1, 2026-07-24 (evening): the KPITTECH restart case. On a
    fresh (restarted) Strategy, a stock already trading ABOVE its ORB
    high must NOT be treated as a fresh breakout on the first candle
    seen -- that first candle only primes the memory. Only a genuine
    LATER cross (back inside, then out again) may fire."""
    # KPITTECH's real ORB high today was 556.70; the _orb_with_range
    # fixture builds the range under symbol "TCS", so use that symbol
    # here with KPITTECH's numbers.
    orb = _orb_with_range(high=556.7)
    strategy = Strategy(orb)

    # Restart at 2pm: first candle seen is already way above the line
    # (KPITTECH ~583). Must NOT fire -- just primes.
    already_above = {"open": 583.0, "high": 584.0, "low": 582.0, "close": 583.0}
    assert strategy.is_buy_signal("TCS", already_above, already_open=False) is False
    strategy.note_candle_close("TCS", already_above)

    # Still above on the next candle -> still no fresh cross.
    still_above = {"open": 583.0, "high": 585.0, "low": 583.0, "close": 584.0}
    assert strategy.is_buy_signal("TCS", still_above, already_open=False) is False
    strategy.note_candle_close("TCS", still_above)

    # It drops back INSIDE the range...
    back_inside = {"open": 550.0, "high": 551.0, "low": 549.0, "close": 550.0}
    strategy.note_candle_close("TCS", back_inside)

    # ...then genuinely breaks out again -> THAT is a real fresh cross.
    fresh_break = {"open": 557.0, "high": 560.0, "low": 557.0, "close": 559.0}
    assert strategy.is_buy_signal("TCS", fresh_break, already_open=False) is True


def test_state_updates_even_while_a_position_is_open_so_no_refill_on_close():
    """The critical case: note_candle_close runs EVERY candle,
    including while a position is open (when is_buy_signal isn't
    called). So when the position later closes with price still
    above the range, there's no fresh cross and it won't re-fire."""
    orb = _orb_with_range(high=110.0)
    strategy = Strategy(orb)
    _prime(strategy)

    above = {"open": 111.0, "high": 113.0, "low": 111.0, "close": 112.0}
    assert strategy.is_buy_signal("TCS", above, already_open=False) is True

    # Position open now -> engine only calls note_candle_close, not
    # is_buy_signal -- state still advances.
    strategy.note_candle_close("TCS", above)
    strategy.note_candle_close("TCS", {"open": 113.0, "high": 115.0, "low": 113.0, "close": 114.0})

    # Position closes; price still above the range. No fresh cross.
    still_above = {"open": 114.0, "high": 116.0, "low": 114.0, "close": 115.0}
    assert strategy.is_buy_signal("TCS", still_above, already_open=False) is False
