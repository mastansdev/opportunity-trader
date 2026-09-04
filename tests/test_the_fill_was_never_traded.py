"""A paper fill must be a price the stock actually traded at.

    "what about qty? i observe INOXWIND entry price is never traded at
     all. bot bought at high than today traded price at that time"
    "INOX WIND 76.5 is todays high till now"
                                   -- the operator, 4 September 2026

INOXWIND, 4 September. Intent 76.42, filled 76.57. The day's high was
76.50. 76.57 never printed on the exchange, so the position opened
underwater by construction and could only show a profit if the stock
went somewhere it had never been.

The cause: slippage was a PERCENTAGE applied to the intent price and
nothing compared the answer to the session's own range. Real slippage
moves you to a worse price THAT EXISTS -- the next level in the book.
It cannot invent one.

The fix keeps the penalty and caps it at the extreme the stock has
actually reached. Unknown range means no cap: guessing a range would
be the same mistake pointing the other way.
"""

from datetime import datetime

from trading.slippage import BUY, SELL, fill_price
from trading.paper_execution import PaperExecution

OPEN_ = datetime(2026, 9, 4, 9, 16)      # when INOXWIND was bought
CALM = datetime(2026, 9, 4, 11, 30)
THIN = 3.0
LIQUID = 500.0


# ----------------------------------------------------- the day itself

def test_INOXWIND_cannot_fill_above_the_high_it_traded():
    """THE case. 76.42 intent, 76.50 high -> at most 76.50."""
    got = fill_price(76.42, BUY, THIN, OPEN_, day_high=76.50)
    assert got <= 76.50, f"filled at {got}, above a high of 76.50"


def test_the_old_behaviour_really_did_invent_a_price():
    """Guards the test itself: without the cap this fill IS above the
    high, so the assertion above is testing the fix and not a tautology."""
    uncapped = fill_price(76.42, BUY, THIN, OPEN_)
    assert uncapped > 76.50


# --------------------------------------------- the property, in full

def test_a_buy_still_costs_something_when_there_is_room_below_the_high():
    """The cap is a ceiling, not a discount. A stock whose high is far
    above the intent pays the full modelled penalty."""
    capped = fill_price(100.0, BUY, THIN, CALM, day_high=200.0)
    plain = fill_price(100.0, BUY, THIN, CALM)
    assert capped == plain > 100.0


def test_the_cap_can_never_make_a_buy_cheaper_than_intent():
    """A high BELOW the intent price is contradictory data -- a bad
    feed row. It must not turn slippage into a rebate."""
    got = fill_price(100.0, BUY, THIN, CALM, day_high=90.0)
    assert got >= 100.0


def test_a_sell_cannot_fill_below_the_low_it_traded():
    got = fill_price(100.0, SELL, THIN, OPEN_, day_low=99.90)
    assert got >= 99.90


def test_the_cap_can_never_make_a_sell_dearer_than_intent():
    got = fill_price(100.0, SELL, THIN, CALM, day_low=110.0)
    assert got <= 100.0


def test_no_range_means_no_cap_not_a_guess():
    assert (fill_price(100.0, BUY, THIN, CALM, day_high=None)
            == fill_price(100.0, BUY, THIN, CALM))
    assert fill_price(100.0, BUY, THIN, CALM, day_high=0) > 100.0


# ------------------------------------------ through the paper executor

def test_the_paper_executor_caps_at_the_range_it_is_given():
    ex = PaperExecution(turnover_lookup=lambda s: THIN,
                        range_lookup=lambda s: (74.10, 76.50))
    result = ex.buy(1, "INOXWIND", 76.42, 654, "TEST", at_time=OPEN_)
    assert result["price"] <= 76.50
    assert result["price"] >= 76.42          # still against him


def test_a_dict_shaped_range_lookup_works_too():
    ex = PaperExecution(turnover_lookup=lambda s: THIN,
                        range_lookup=lambda s: {"low": 74.10, "high": 76.50})
    assert ex.buy(1, "INOXWIND", 76.42, 654, "T", at_time=OPEN_)["price"] <= 76.50


def test_a_broken_range_lookup_degrades_to_uncapped_not_a_crash():
    def explode(_symbol):
        raise RuntimeError("no tick yet")
    ex = PaperExecution(turnover_lookup=lambda s: THIN, range_lookup=explode)
    result = ex.buy(1, "INOXWIND", 76.42, 654, "TEST", at_time=OPEN_)
    assert result["success"] is True
    assert result["price"] > 76.42


def test_no_range_lookup_at_all_behaves_exactly_as_before():
    with_none = PaperExecution(turnover_lookup=lambda s: THIN)
    before = with_none.buy(1, "CUPID", 228.11, 876, "T", at_time=CALM)
    assert before["price"] > 228.11


# --------------------------------------------- the engine's own lookup

def test_the_engine_reads_the_range_off_the_FEED_not_the_snapshot():
    """core/tick_ohlc.py is written on every tick. The REST snapshot on
    4 September was missing volume for 54 of 100 rows and would have
    handed back a high older than the order it was capping."""
    from core import engine as engine_mod
    import inspect
    src = inspect.getsource(engine_mod.Engine._day_range)
    assert "tick_ohlc.of" in src


def test_the_engine_hands_the_range_to_the_executor():
    """The cap is worthless if nothing wires it in -- this bot's most
    repeated fault is machinery that exists and is never called."""
    from core import engine as engine_mod
    import inspect
    src = inspect.getsource(engine_mod.Engine.__init__)
    assert "range_lookup=self._day_range" in src
