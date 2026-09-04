"""How long does asking Dhan for MTF margin actually take?

    "add that timing"           -- the operator, 4 September 2026

dashboard/state._mtf_for() asks this for every ranked row, so a cold
cache costs one network round trip per stock inside the board rebuild.
The docstring in core/mtf_margin.py has claimed "~300ms" since it was
written and nobody had ever measured it.

It matters now because his static IP is not renewed and Dhan refuses
every call. A refusal that returns instantly costs nothing. A refusal
that TIMES OUT costs the full timeout per stock, and a hundred new
stocks is a hundred timeouts -- which would be the difference between
a 50-second rebuild and a 344-second one.

So it is measured rather than argued about, and the number reaches him
in the log lines that already print, plus one running total.
"""

import time

import pytest

from core.mtf_margin import MtfMarginBook


class _Slow:
    """A calculator that takes a known amount of time, like a timeout."""

    def __init__(self, seconds, answer=None):
        self.seconds = seconds
        self.answer = answer
        self.calls = 0

    def __call__(self, security_id, price, quantity):
        self.calls += 1
        time.sleep(self.seconds)
        if self.answer is None:
            raise RuntimeError("403 -- static IP not renewed")
        return self.answer


def test_a_book_that_has_asked_nothing_reports_no_average():
    """An average over nothing is not a number."""
    book = MtfMarginBook(calculator=None)
    assert book.timing_summary() == {
        "calls": 0, "failures": 0, "spent_ms": 0.0, "avg_ms": None}


def test_the_time_a_refused_call_costs_is_recorded():
    """THE measurement. A call that fails still consumed the time."""
    book = MtfMarginBook(calculator=_Slow(0.05), cache_seconds=600)
    book.margin_pct("ANYSTOCK", "1234", 100.0)
    got = book.timing_summary()
    assert got["calls"] == 1
    assert got["failures"] == 1, "a refused call must count as a failure"
    assert got["avg_ms"] >= 40, (
        f"the 50ms the call took was not recorded ({got['avg_ms']}ms)")


def test_the_cache_means_the_second_ask_costs_nothing():
    """The reason a slow call is survivable: it is paid once per stock
    per cache window, not once per rebuild."""
    slow = _Slow(0.05)
    book = MtfMarginBook(calculator=slow, cache_seconds=600)
    book.margin_pct("ANYSTOCK", "1234", 100.0)
    book.margin_pct("ANYSTOCK", "1234", 100.0)
    assert slow.calls == 1, "the second ask went to the network"
    assert book.timing_summary()["calls"] == 1


def test_each_stock_is_paid_for_separately():
    """A hundred NEW stocks on the board is a hundred calls, which is
    the cost the rebuild actually pays."""
    slow = _Slow(0.01)
    book = MtfMarginBook(calculator=slow, cache_seconds=600)
    for symbol in ("AAA", "BBB", "CCC"):
        book.margin_pct(symbol, "1", 100.0)
    assert book.timing_summary()["calls"] == 3


def test_a_successful_call_is_timed_too_and_is_not_a_failure():
    # The book asks for ONE share, so on a Rs 100 stock the notional
    # is Rs 100 and a Rs 25 margin is 25% -- about 4x, which is what
    # Dhan quoted on most of his stocks on 4 September.
    answer = {"data": {"totalMargin": 25.0}}
    book = MtfMarginBook(calculator=_Slow(0.01, answer), cache_seconds=600)
    pct = book.margin_pct("GOODSTOCK", "1234", 100.0)
    got = book.timing_summary()
    assert got["calls"] == 1
    assert got["failures"] == 0
    assert got["avg_ms"] > 0
    assert pct == pytest.approx(0.25), "25 of 100 is a 4x margin"


def test_clearing_the_book_resets_the_meter_too():
    """Otherwise the average silently spans two sessions."""
    book = MtfMarginBook(calculator=_Slow(0.01), cache_seconds=600)
    book.margin_pct("ANYSTOCK", "1234", 100.0)
    book.clear()
    assert book.timing_summary()["calls"] == 0
