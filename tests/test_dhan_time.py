"""
Decision-correctness tests for the LTT -> IST conversion.

This exists because the bug it replaces was silent and total --
twice, in two different ways:

1. datetime.fromisoformat() on a bare "HH:MM:SS" string raises
   on every tick (no date component).
2. CORRECTED 2026-07-23: this module used to also add a +5:30
   IST_OFFSET, on the (source-code-confirmed but live-false)
   assumption that Dhan's LTT is UTC. Live evidence during the
   first real session showed LTT is already IST -- see
   core/dhan_time.py's module docstring for exactly how that
   was confirmed (operator's own PC clock vs. a logged tick
   time, ~5:30 apart, matching the wrongly-added offset). That
   silent double-shift is why ORB ranges stayed empty and zero
   breakouts fired all morning despite ticks visibly flowing.
"""

from datetime import date, datetime

from core.dhan_time import parse_ltt_to_ist


def test_market_open_tick_maps_directly_to_market_open_ist():
    # LTT arrives already IST -- 09:15:00 in, 09:15:00 IST out.
    result = parse_ltt_to_ist("09:15:00", today=date(2026, 7, 23))
    assert result == datetime(2026, 7, 23, 9, 15, 0)


def test_square_off_tick_maps_directly_to_square_off_ist():
    result = parse_ltt_to_ist("15:15:00", today=date(2026, 7, 23))
    assert result == datetime(2026, 7, 23, 15, 15, 0)


def test_missing_ltt_returns_none_not_a_guess():
    assert parse_ltt_to_ist(None) is None
    assert parse_ltt_to_ist("") is None


def test_midday_tick_round_trip():
    result = parse_ltt_to_ist("12:00:00", today=date(2026, 7, 23))
    assert result == datetime(2026, 7, 23, 12, 0, 0)
