"""
Tests for OrbEngine.merge_official -- the range that was always too
narrow, 2026-07-29.

The operator checked the bot's own recorded candles against Dhan's
charts. Prices matched to the paisa -- SMLMAH's circuit-locked minute
came back 4,566.00 / 4,566.00 / 4,566.00 / 4,566.00 on both. The
RANGES did not match, and they were wrong in one direction only:

    symbol      bot high   Dhan high     bot low    Dhan low
    INFY        1,151.80    1,152.00    1,128.50    1,128.40
    COFORGE     1,745.60    1,748.00    1,714.70    1,713.00

Always narrower. Never wider. A snapshot feed cannot see the extreme
that happens between two snapshots.

Why it matters: COFORGE's real range topped at 1,748.00 while the bot
believed 1,745.60, so a price of 1,746 fired a breakout while the stock
was still inside its actual range.
"""

from datetime import datetime

import pytest

from core.orb_engine import OrbEngine


def _t(hour, minute, second=0):
    return datetime(2026, 7, 29, hour, minute, second)


def _coforge():
    """The real COFORGE numbers from 29 July, ticks only."""
    orb = OrbEngine()
    orb.update("COFORGE", 1745.60, _t(9, 16))
    orb.update("COFORGE", 1714.70, _t(9, 20))
    return orb


# ---------------------------------------------------------------
# It fixes the real case
# ---------------------------------------------------------------

def test_the_exchange_high_is_adopted_when_our_ticks_missed_it():
    orb = _coforge()
    assert orb.get_range("COFORGE")["high"] == 1745.60

    orb.merge_official("COFORGE", high=1748.00, low=1713.00, tick_time=_t(9, 25))

    assert orb.get_range("COFORGE")["high"] == 1748.00
    assert orb.get_range("COFORGE")["low"] == 1713.00


def test_a_price_inside_the_real_range_no_longer_looks_like_a_breakout():
    """The whole point, stated as the operator would: 1,746 is NOT a
    breakout, because the stock traded at 1,748 during the window."""
    orb = _coforge()
    orb.merge_official("COFORGE", 1748.00, 1713.00, _t(9, 25))
    assert 1746.00 < orb.get_range("COFORGE")["high"]


# ---------------------------------------------------------------
# It can only ever WIDEN
# ---------------------------------------------------------------

def test_it_never_narrows_the_range():
    """A stale or lagging quote must not shrink a range our own ticks
    genuinely saw. Narrowing would invent breakouts rather than
    prevent them -- the exact fault being fixed, in reverse."""
    orb = _coforge()
    orb.merge_official("COFORGE", high=1700.00, low=1740.00, tick_time=_t(9, 25))
    assert orb.get_range("COFORGE")["high"] == 1745.60
    assert orb.get_range("COFORGE")["low"] == 1714.70


def test_a_zero_or_missing_value_changes_nothing():
    orb = _coforge()
    for high, low in ((0, 0), (None, None), ("", ""), ("junk", "junk")):
        orb.merge_official("COFORGE", high, low, _t(9, 25))
    assert orb.get_range("COFORGE")["high"] == 1745.60
    assert orb.get_range("COFORGE")["low"] == 1714.70


# ---------------------------------------------------------------
# Only inside the window -- this is the dangerous edge
# ---------------------------------------------------------------

def test_after_the_window_closes_the_session_high_is_ignored():
    """Dhan's high is the running SESSION high. It equals the opening
    range only while the window is open. Applied at 11:00 it would
    silently turn the ORB into a whole-day range and destroy the
    strategy."""
    orb = _coforge()
    orb.update("COFORGE", 1740.00, _t(9, 31))       # closes the range
    orb.merge_official("COFORGE", high=1900.00, low=1600.00,
                       tick_time=_t(11, 0))
    assert orb.get_range("COFORGE")["high"] == 1745.60
    assert orb.get_range("COFORGE")["low"] == 1714.70


def test_a_completed_range_is_never_touched_again():
    orb = _coforge()
    orb.update("COFORGE", 1740.00, _t(9, 31))
    orb.merge_official("COFORGE", 1748.00, 1713.00, _t(9, 25))
    assert orb.get_range("COFORGE")["high"] == 1745.60


def test_before_the_open_it_does_nothing():
    orb = OrbEngine()
    orb.update("COFORGE", 1745.60, _t(9, 16))
    orb.merge_official("COFORGE", 1900.00, 1600.00, _t(9, 10))
    assert orb.get_range("COFORGE")["high"] == 1745.60


def test_a_symbol_with_no_range_yet_is_not_invented():
    """No tick has ever arrived for it. A quote alone must not
    manufacture an opening range out of nothing."""
    orb = OrbEngine()
    orb.merge_official("NEVERSEEN", 100.0, 90.0, _t(9, 20))
    assert orb.get_range("NEVERSEEN") is None


def test_no_tick_time_is_survivable():
    orb = _coforge()
    orb.merge_official("COFORGE", 1748.00, 1713.00, None)
    assert orb.get_range("COFORGE")["high"] == 1745.60


# ---------------------------------------------------------------
# The INFY case, end to end
# ---------------------------------------------------------------

def test_infy_29_july_reproduced():
    orb = OrbEngine()
    orb.update("INFY", 1151.80, _t(9, 15))
    orb.update("INFY", 1128.50, _t(9, 22))
    orb.merge_official("INFY", 1152.00, 1128.40, _t(9, 29))
    got = orb.get_range("INFY")
    assert got["high"] == pytest.approx(1152.00)
    assert got["low"] == pytest.approx(1128.40)
