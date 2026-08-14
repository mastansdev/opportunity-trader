"""
Tests for core/results_gate.py.

THE BUG: engine.py refused an entry on ANY stock reporting results
today, silently. The operator's entire strategy is the opposite --
"entry only on real reasons: results genuinely better than previous
quarter". CUB reported on 2026-07-28 and went +8.47%; the old rule
would have refused it. 27 companies reported that day, 52 the next.

The first test is CUB, because if the gate still blocks that trade
nothing else about this module matters.
"""

from datetime import date

import pytest

from core.results_gate import ResultsGate

TODAY = date(2026, 7, 28)
CAL = {"2026-07-28": {"CUB", "COFORGE", "CHOLAFIN", "AMBUJACEM"}}


class FakeAnnouncements:
    def __init__(self, filed=()):
        self._filed = {s: {"kind": "RESULTS"} for s in filed}

    def for_symbol(self, symbol):
        return self._filed.get(symbol)


class FakeQuarterly:
    def __init__(self, grades=None):
        self._grades = grades or {}

    def compare(self, symbol):
        g = self._grades.get(symbol)
        if g is None:
            return None, None
        # grade() reads sales/pat out of the QoQ block
        strong = {"sales": 30.0, "pat": 60.0}
        good = {"sales": 8.0, "pat": 9.0}
        weak = {"sales": -12.0, "pat": -20.0}
        mixed = {"sales": 12.0, "pat": -15.0}
        return {"STRONG": strong, "GOOD": good,
                "WEAK": weak, "MIXED": mixed}[g], None


def _gate(filed=(), grades=None):
    return ResultsGate(earnings_calendar=CAL,
                       announcements=FakeAnnouncements(filed),
                       quarterly=FakeQuarterly(grades))


# ---------------------------------------------------------------
# The trade the whole module exists for
# ---------------------------------------------------------------

def test_CUB_is_allowed_once_it_has_filed_and_graded_well():
    """Reported 2026-07-28 and went +8.47%. The old rule refused it."""
    gate = _gate(filed=("CUB",), grades={"CUB": "STRONG"})
    assert gate.allows("CUB", TODAY) is True
    assert gate.block_reason("CUB", TODAY) is None


def test_a_GOOD_grade_is_enough():
    gate = _gate(filed=("COFORGE",), grades={"COFORGE": "GOOD"})
    assert gate.allows("COFORGE", TODAY) is True


# ---------------------------------------------------------------
# The half of the old rule that was RIGHT
# ---------------------------------------------------------------

def test_before_the_filing_lands_it_still_blocks():
    """A company scheduled for 14:00 has not reported at 09:20. Entering
    before the numbers is the coin flip the original rule was for."""
    gate = _gate(filed=(), grades={})
    assert gate.allows("CUB", TODAY) is False
    assert "not out yet" in gate.block_reason("CUB", TODAY)


def test_filed_but_not_yet_read_still_blocks():
    """The PDF has not been parsed, so the outcome is still unknown."""
    gate = _gate(filed=("CUB",), grades={})
    assert gate.allows("CUB", TODAY) is False
    assert "not read yet" in gate.block_reason("CUB", TODAY)


def test_a_WEAK_grade_blocks():
    gate = _gate(filed=("CHOLAFIN",), grades={"CHOLAFIN": "WEAK"})
    assert gate.allows("CHOLAFIN", TODAY) is False
    assert "WEAK" in gate.block_reason("CHOLAFIN", TODAY)


def test_a_MIXED_grade_blocks():
    """No edge either way is not a reason to trade."""
    gate = _gate(filed=("AMBUJACEM",), grades={"AMBUJACEM": "MIXED"})
    assert gate.allows("AMBUJACEM", TODAY) is False


# ---------------------------------------------------------------
# Stocks not reporting are untouched
# ---------------------------------------------------------------

def test_a_stock_not_reporting_today_is_never_blocked():
    gate = _gate()
    assert gate.allows("TVSMOTOR", TODAY) is True
    assert gate.block_reason("TVSMOTOR", TODAY) is None


def test_the_same_stock_is_free_the_day_after_it_reported():
    gate = _gate()
    assert gate.allows("CUB", date(2026, 7, 29)) is True


# ---------------------------------------------------------------
# FAIL CLOSED -- every unknown blocks
# ---------------------------------------------------------------

def test_no_announcement_feed_means_block_not_allow():
    """Missing data must never quietly widen the door."""
    gate = ResultsGate(earnings_calendar=CAL, announcements=None,
                       quarterly=FakeQuarterly({"CUB": "STRONG"}))
    assert gate.allows("CUB", TODAY) is False


def test_no_quarterly_store_means_block_not_allow():
    gate = ResultsGate(earnings_calendar=CAL,
                       announcements=FakeAnnouncements(("CUB",)),
                       quarterly=None)
    assert gate.allows("CUB", TODAY) is False


def test_a_raising_announcement_feed_does_not_crash_the_tick_path():
    class Explodes:
        def for_symbol(self, symbol):
            raise RuntimeError("feed down")
    gate = ResultsGate(earnings_calendar=CAL, announcements=Explodes(),
                       quarterly=FakeQuarterly({"CUB": "STRONG"}))
    assert gate.allows("CUB", TODAY) is False


def test_a_raising_quarterly_store_does_not_crash_the_tick_path():
    class Explodes:
        def compare(self, symbol):
            raise RuntimeError("db locked")
    gate = ResultsGate(earnings_calendar=CAL,
                       announcements=FakeAnnouncements(("CUB",)),
                       quarterly=Explodes())
    assert gate.allows("CUB", TODAY) is False


def test_a_missing_date_never_blocks():
    assert _gate().allows("CUB", None) is True


def test_an_empty_calendar_blocks_nothing():
    gate = ResultsGate(earnings_calendar={},
                       announcements=FakeAnnouncements(),
                       quarterly=FakeQuarterly())
    assert gate.allows("CUB", TODAY) is True


# ---------------------------------------------------------------
# Logging discipline
# ---------------------------------------------------------------

def test_the_allow_is_announced_only_once_per_symbol():
    """It fires on every candle close. One line, not four hundred."""
    gate = _gate(filed=("CUB",), grades={"CUB": "STRONG"})
    for _ in range(50):
        gate.allows("CUB", TODAY)
    assert gate._logged == {"CUB"}
