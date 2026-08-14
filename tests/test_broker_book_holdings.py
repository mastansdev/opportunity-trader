"""
==========================================================
The overnight book is half the book -- and the dangerous half
==========================================================

    "bot is printing | tick worker alive: True
     WARNING: [BOOK] The bot's own book is behind Dhan: [...]
     Nothing is corrected automatically. py tools/reconcile.py
     --apply adopts Dhan's version."
                                -- operator, 5 August 2026

WHAT WENT WRONG
---------------
Dhan keeps two books. /positions is the INTRADAY one. An MTF or
delivery position bought yesterday is not in it -- overnight, on T+1,
it moves to /holdings.

The bot only ever asked /positions. So on the morning after every
overnight trade, Dhan appeared to hold nothing, the bot's own book
looked like an invention, and the one documented remedy --
`py tools/reconcile.py --apply` -- would have adopted Dhan's answer and
DELETED real positions carrying real money.

It fired at 07:06 on 5 August. It would have fired again at 07:00 the
next morning, and every morning after an overnight hold.

He trades MTF and holds overnight. That is the whole strategy. So the
one book the bot never read is the one his money actually lives in.

THE TWO RULES THIS LOCKS
------------------------
1. Ask BOTH. A quantity that is in holdings is a quantity he owns.
2. If EITHER question goes unanswered, refuse to conclude anything.
   None means "could not ask". [] means "the answer was nothing".
   Merging those two is what turns a dropped connection into data loss.

Author : H&M Opportunity Trader
==========================================================
"""

import inspect
import re

import pytest

from core.broker_sync import BrokerSync, _cost_of, _qty_of, compare


# ---------------------------------------------------------------
# 1. A HOLDINGS ROW COUNTS ITS SHARES DIFFERENTLY
# ---------------------------------------------------------------
def test_a_holdings_row_is_not_read_as_zero():
    """/holdings sends totalQty, not netQty. Read with the position
    spellings alone it came back 0 -- which compare() reads as 'the
    broker does not have this'."""
    assert _qty_of({"tradingSymbol": "CGPOWER", "totalQty": 100}) == 100


def test_available_and_t1_are_added_not_double_counted():
    """A holding part-settled: 60 available, 40 still in T+1. He owns
    100 shares, not 140 and not 60."""
    assert _qty_of({"availableQty": 60, "t1Qty": 40}) == 100


def test_total_qty_wins_over_the_parts():
    """totalQty IS the whole holding. Adding the parts to it would
    report twice what he owns."""
    assert _qty_of({"totalQty": 100, "availableQty": 60, "t1Qty": 40}) == 100


def test_an_intraday_row_still_reads_the_old_way():
    assert _qty_of({"netQty": -25}) == -25
    assert _qty_of({"buyQty": 50, "sellQty": 20}) == 30


def test_the_holdings_cost_field_is_understood():
    """No cost means no P&L on the panel -- a position shown flat when
    it is down 3% is worse than one shown as unknown."""
    assert _cost_of({"avgCostPrice": 871.7}) == 871.7


# ---------------------------------------------------------------
# 2. THE MORNING THAT NEARLY DELETED THE BOOK
# ---------------------------------------------------------------
def test_an_overnight_mtf_position_is_not_reported_missing():
    """07:06, 5 August. CGPOWER was bought yesterday on MTF. It has
    moved to holdings. /positions is empty.

    Read as one book, there is nothing to report."""
    bot = {"CGPOWER": {"qty": 100, "direction": "LONG"}}
    positions = []                                    # intraday: empty
    holdings = [{"tradingSymbol": "CGPOWER", "totalQty": 100,
                 "avgCostPrice": 871.7}]
    got = compare(bot, positions + holdings)
    assert got["only_in_bot"] == [], got["only_in_bot"]
    assert got["in_sync"] is True


def test_positions_alone_is_what_raised_the_false_alarm():
    """The bug, preserved. Without holdings the same book reports the
    position as one the broker does not have -- and that is the row
    reconcile.py --apply deletes."""
    bot = {"CGPOWER": {"qty": 100, "direction": "LONG"}}
    got = compare(bot, [])
    assert got["only_in_bot"] == [{"symbol": "CGPOWER", "bot_qty": 100}]


def test_a_symbol_in_both_books_is_summed():
    """100 held overnight, 50 more bought today. He is long 150."""
    bot = {"TCS": {"qty": 150, "direction": "LONG"}}
    rows = [{"tradingSymbol": "TCS", "netQty": 50},
            {"tradingSymbol": "TCS", "totalQty": 100}]
    assert compare(bot, rows)["in_sync"] is True


# ---------------------------------------------------------------
# 3. SILENCE IS NOT AN ANSWER
# ---------------------------------------------------------------
class _Executor:
    """Stands in for trading/live_execution.py."""

    def __init__(self, positions=(), holdings=()):
        self._positions = positions
        self._holdings = holdings

    def positions(self):
        return self._positions

    def holdings(self):
        return self._holdings

    def broker_book(self):
        if self._positions is None or self._holdings is None:
            return None
        return list(self._positions) + list(self._holdings)


def test_a_failed_holdings_read_never_reports_a_clean_book():
    """Positions answered, holdings did not. The honest answer is 'I
    do not know', never 'you hold nothing overnight'."""
    sync = BrokerSync(execution=_Executor(positions=[], holdings=None))
    got = sync.check({"CGPOWER": {"qty": 100, "direction": "LONG"}})
    assert got["available"] is False
    assert got["in_sync"] is None


def test_a_genuinely_empty_book_is_still_reported():
    """Nothing held anywhere is a real answer and must not be confused
    with a failed read."""
    sync = BrokerSync(execution=_Executor(positions=[], holdings=[]))
    got = sync.check({})
    assert got["available"] is True
    assert got["in_sync"] is True


def test_the_whole_book_is_preferred_over_positions_alone():
    sync = BrokerSync(execution=_Executor())
    assert sync._reader().__name__ == "broker_book"


def test_an_old_executor_without_broker_book_still_works():
    """PAPER, and any executor not yet carrying the new method."""
    class Old:
        def positions(self):
            return []
    assert BrokerSync(execution=Old())._reader().__name__ == "positions"


def test_paper_mode_reports_that_nothing_was_checked():
    class Paper:
        pass
    got = BrokerSync(execution=Paper()).check({})
    assert got["available"] is False
    assert got["in_sync"] is None


# ---------------------------------------------------------------
# 4. THE METHODS ARE REAL -- NOT NAMES I REMEMBERED
# ---------------------------------------------------------------
# Five times in this project I have called a method that did not
# exist, and the tests passed because I wrote the fake object too and
# gave it the name I had invented. These read the REAL classes.
def test_live_execution_really_has_these_methods():
    from trading.live_execution import LiveExecution
    names = {n for n, _ in inspect.getmembers(LiveExecution)}
    for needed in ("positions", "holdings", "broker_book"):
        assert needed in names, needed


def test_dhanhq_really_has_get_holdings():
    """The one call this whole fix rests on. If the SDK does not have
    it, everything above is decoration."""
    dhanhq = pytest.importorskip("dhanhq")
    assert hasattr(dhanhq.dhanhq, "get_holdings")


def test_broker_book_returns_none_if_either_half_fails():
    """Read off the real source, not a stub of it."""
    from trading.live_execution import LiveExecution
    code = inspect.getsource(LiveExecution.broker_book)
    code = re.sub(r'"""[\s\S]*?"""', "", code)
    assert code.count("is None") >= 2, code
    assert "return None" in code
