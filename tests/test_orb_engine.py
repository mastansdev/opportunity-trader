"""
Decision-correctness tests for OrbEngine. Each test asserts
a SPECIFIC right answer for a known tick sequence -- not
just "it ran without an exception."
"""

from datetime import datetime

from core.orb_engine import OrbEngine


def _t(hh, mm, ss=0):
    return datetime(2026, 7, 22, hh, mm, ss)


def test_range_is_high_and_low_of_the_window():
    orb = OrbEngine()

    orb.update("TCS", 100.0, _t(9, 15, 0))
    orb.update("TCS", 105.0, _t(9, 20, 0))
    orb.update("TCS", 98.0, _t(9, 25, 0))
    orb.update("TCS", 102.0, _t(9, 29, 59))

    rng = orb.get_range("TCS")
    assert rng == {"high": 105.0, "low": 98.0}


def test_premarket_tick_never_enters_the_range():
    orb = OrbEngine()

    # A wild pre-open price that must NOT affect the range.
    orb.update("TCS", 500.0, _t(9, 10, 0))
    orb.update("TCS", 100.0, _t(9, 15, 0))
    orb.update("TCS", 101.0, _t(9, 20, 0))

    rng = orb.get_range("TCS")
    assert rng["high"] == 101.0
    assert rng["low"] == 100.0


def test_tick_after_window_does_not_move_the_range():
    orb = OrbEngine()

    orb.update("TCS", 100.0, _t(9, 15, 0))
    orb.update("TCS", 110.0, _t(9, 25, 0))

    # This tick is after the window closes and is a new
    # extreme -- it must NOT change the frozen range.
    orb.update("TCS", 999.0, _t(9, 45, 0))

    rng = orb.get_range("TCS")
    assert rng["high"] == 110.0


def test_range_marked_complete_only_after_window_end():
    orb = OrbEngine()

    orb.update("TCS", 100.0, _t(9, 20, 0))
    assert orb.is_complete("TCS") is False

    orb.update("TCS", 101.0, _t(9, 30, 0))
    assert orb.is_complete("TCS") is True


def test_unknown_symbol_returns_none_not_a_crash():
    orb = OrbEngine()
    assert orb.get_range("NOPE") is None
    assert orb.is_complete("NOPE") is False


def test_export_state_then_load_state_reproduces_the_same_ranges():
    """
    This is what makes a restart after 09:30 survivable --
    without it, a fresh OrbEngine has no memory of a symbol's
    range and permanently refuses to build one once the
    window has already closed on it.
    """
    orb = OrbEngine()
    orb.update("TCS", 100.0, _t(9, 15, 0))
    orb.update("TCS", 105.0, _t(9, 20, 0))
    orb.update("TCS", 98.0, _t(9, 25, 0))
    orb.update("TCS", 101.0, _t(9, 30, 0))  # marks TCS complete

    snapshot = orb.export_state()

    restarted = OrbEngine()
    restarted.load_state(snapshot)

    assert restarted.get_range("TCS") == {"high": 105.0, "low": 98.0}
    assert restarted.is_complete("TCS") is True

    # And critically: a late tick after 09:30, on the restarted
    # instance, must still not move the recovered range.
    restarted.update("TCS", 999.0, _t(9, 45, 0))
    assert restarted.get_range("TCS")["high"] == 105.0
