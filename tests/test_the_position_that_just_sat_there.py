"""
==========================================================
32 trades, minus 30,444, and no rule at all
==========================================================

    "entries, exits all are worrking but not as we wanted"
    seats "filled as instant as possible but not right stocks"
                                    -- the operator, 10/14 September 2026

Measured over 7-10 September, 95 trades, against the minute candles:

    BUYING_DRIED_UP   46 trades   +68,770 gross   books the winners
    TRAILING_STOP                  fires correctly at -3.06/-3.43%
    MANUAL_EXIT       32 trades   -30,444 gross   NO RULE AT ALL

Those 32 were flattened BY HAND at 15:11-15:22. They drifted at -1 to
-2% all session: never far enough to reach the -3% stop, never up
enough for the buying check, which takes winners only and says why --
"A losing trade belongs to the stop."

The flaw is that a position drifting sideways-down for six hours does
not belong to the stop either. The stop never comes. It belongs to
NOTHING, and the seat it holds is the seat the next real opportunity
needed: the book was full for 290 of the session's 306 minutes.

Only 7 of those 32 ever reached +1.0% at any point. That is the
measurement: a position that has not shown 1% in 45 minutes is not
slow, it is wrong.

WHAT THIS RULE MUST NEVER DO is take a winner early. It is asked AFTER
_buying_dried_up(), and it refuses anything at or above entry, so the
two can never both own a position.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

import pytest

from core.engine import EXIT_REASON_DRIFTED, Engine

ENTRY = 100.0
ENTERED = "2026-09-14 09:30:00"


class _Trail:
    def __init__(self, peak):
        self._peak = peak

    def get_peak(self, symbol):
        return self._peak


def _engine(price_peak=100.4, entry=ENTRY, qty=100):
    """An engine with one open position and nothing else wired."""
    engine = Engine.__new__(Engine)
    engine.open_positions = {
        "ABC": {"entry_price": entry, "qty": qty, "entry_time": ENTERED},
    }
    engine.trailing_stop = _Trail(price_peak)
    engine.exits = []
    engine._exit = lambda symbol, price, reason, tick_time: \
        engine.exits.append((symbol, price, reason))
    return engine


def _later(minutes):
    return datetime.fromisoformat(ENTERED) + timedelta(minutes=minutes)


# ---------------------------------------------------------------
# IT FIRES
# ---------------------------------------------------------------

def test_a_position_that_never_worked_gives_the_seat_back():
    """THE CASE. 45 minutes, best was +0.4%, and it is losing."""
    engine = _engine(price_peak=100.4)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is True
    assert engine.exits == [("ABC", 98.5, EXIT_REASON_DRIFTED)]


def test_it_is_tagged_so_it_can_be_counted():
    """Its own reason, so these can be judged against the MANUAL_EXIT
    trades they replace rather than blurred into the stop."""
    assert EXIT_REASON_DRIFTED == "DRIFTED_NO_MOVE"


# ---------------------------------------------------------------
# IT MUST NEVER TAKE A WINNER
# ---------------------------------------------------------------

def test_it_refuses_a_position_in_profit():
    """Anything at or above entry belongs to the trail and the buying
    check. This is the line that keeps the two rules apart."""
    engine = _engine(price_peak=100.4)
    assert engine._drifted_without_working("ABC", 100.5, _later(45)) is False
    assert engine.exits == []


def test_it_refuses_at_exactly_entry():
    engine = _engine(price_peak=100.4)
    assert engine._drifted_without_working("ABC", ENTRY, _later(45)) is False


def test_a_position_that_once_worked_is_never_touched_again():
    """It reached +1.2% at some point, so the trail owns it from there
    -- even though it is losing now. This rule is for the ones that
    never did anything, not for giving up on a pullback."""
    engine = _engine(price_peak=101.2)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False
    assert engine.exits == []


def test_the_threshold_is_the_high_water_not_the_price_now():
    engine = _engine(price_peak=101.0)     # exactly +1.0%
    assert engine._drifted_without_working("ABC", 97.0, _later(60)) is False


# ---------------------------------------------------------------
# IT MUST HAVE HAD TIME, AND A READING
# ---------------------------------------------------------------

def test_it_will_not_judge_a_young_position():
    """Below the checkpoint it is reading the noise around its own
    entry -- the reason the buying check waits fifteen minutes."""
    engine = _engine(price_peak=100.4)
    assert engine._drifted_without_working("ABC", 98.5, _later(44)) is False
    assert engine.exits == []


def test_no_peak_means_no_action():
    """No reading, no action. A missing peak means the trail is not
    running for this position, and that is never read as 'sell'."""
    engine = _engine(price_peak=None)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False


def test_a_trail_that_raises_is_not_a_sell_signal():
    class _Boom:
        def get_peak(self, symbol):
            raise RuntimeError("no trail")
    engine = _engine()
    engine.trailing_stop = _Boom()
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False


def test_an_unknown_entry_time_is_not_judged():
    engine = _engine(price_peak=100.4)
    engine.open_positions["ABC"]["entry_time"] = None
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False


def test_a_position_that_is_not_open_is_not_an_error():
    engine = _engine()
    assert engine._drifted_without_working("NOPE", 98.5, _later(45)) is False


# ---------------------------------------------------------------
# THE SWITCH, AND WHERE IT SITS
# ---------------------------------------------------------------

def test_it_can_be_turned_off_without_touching_anything_else(monkeypatch):
    """Provisional: measured on the four sessions it was chosen on, so
    it must be removable in one line."""
    monkeypatch.setattr("config.DRIFT_EXIT_ENABLED", False)
    engine = _engine(price_peak=100.4)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False
    assert engine.exits == []


def test_the_settings_are_read_at_call_time(monkeypatch):
    """He changes these between sessions. A value bound at import would
    describe the last run."""
    engine = _engine(price_peak=100.4)
    monkeypatch.setattr("config.DRIFT_EXIT_AFTER_MINUTES", 120)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is False
    monkeypatch.setattr("config.DRIFT_EXIT_AFTER_MINUTES", 30)
    assert engine._drifted_without_working("ABC", 98.5, _later(45)) is True


def test_it_is_asked_after_the_buying_check():
    """Order is the safety. The buying check owns every position in
    profit; this one is only ever handed a loser."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "engine.py").read_text(encoding="utf-8")
    buying = src.index("if self._buying_dried_up(symbol, price, tick_time):")
    drifted = src.index(
        "if self._drifted_without_working(symbol, price, tick_time):")
    assert buying < drifted
