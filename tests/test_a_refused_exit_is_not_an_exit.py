"""---- THE ONE PATH NOBODY CHECKED. 31 August 2026. ----

_enter() has tested this since the day it was written:

    if not result.get("success"):
        return

_exit() never did. It pulled the fill price out of the result and
carried on -- telling the portfolio, removing the position from the
book, appending a closed trade, writing to trade memory -- whether or
not the order had actually been placed.

In PAPER it cannot bite; the paper executor always succeeds. In LIVE it
is the worst outcome this bot can produce. Dhan refuses orders for real
reasons: margin, a frozen scrip, a price band, or a market that has
moved to the closing auction, which every F&O stock does at 15:15.

The bot would then believe it was flat while still holding the shares.
No stop watching it. No exit rule watching it. No row anywhere saying
it exists. The position would only surface the next time somebody
compared the book against Dhan by hand.

This is the same fault the repository forbids in three other places --
"claim a stop is resting when the API call failed", "report success
when the broker never answered" -- arriving where nobody had looked.

THE CHECK GOES BEFORE THE PORTFOLIO. Booking the P&L and then bailing
out would leave the trade counted AND the position open, which is worse
than either failure on its own.
"""

from datetime import datetime

import pytest

from core import engine as eng


class _Execution:
    """A broker that can be told to refuse."""

    def __init__(self, refuse=False, error="rejected: insufficient margin"):
        self.refuse = refuse
        self.error = error
        self.calls = []

    def sell(self, security_id, symbol, price, qty, reason="", at_time=None):
        self.calls.append(("SELL", symbol, qty))
        if self.refuse:
            return {"success": False, "error": self.error}
        return {"success": True, "price": price, "intent_price": price}

    buy = sell


class _Portfolio:
    def __init__(self):
        self.booked = []

    def on_sell(self, entry, exit_price, qty):
        self.booked.append((entry, exit_price, qty))
        return (exit_price - entry) * qty

    on_cover = on_sell


def _engine(refuse=False):
    """A REAL Engine, not a stand-in.

    The first version of this built one with Engine.__new__ and filled
    in attributes by hand, and every run found another it had missed --
    post_exit, trailing_stop, _exit_all_snapshot. Chasing them one at a
    time produces a fixture that passes because it is incomplete, which
    is exactly the FakeQuarterly trap: a test double that proved a
    behaviour the real object had never once produced.
    """
    from tests.test_engine import _engine as build

    e = build()
    e.execution = _Execution(refuse=refuse)
    e.portfolio = _Portfolio()
    e.open_positions["ASHOKA"] = {
        "security_id": "1", "symbol": "ASHOKA", "qty": 100,
        "entry_price": 120.0, "direction": eng.LONG,
        "entry_time": datetime(2026, 8, 31, 9, 20),
    }
    e.closed_positions = []
    return e


# ------------------------------------------------------- it refuses

def test_a_refused_sell_leaves_the_position_open():
    """The whole finding. The bot must not believe it is flat."""
    e = _engine(refuse=True)
    e._exit("ASHOKA", 126.85, "BUYING_DRIED_UP", datetime(2026, 8, 31, 11, 9))
    assert "ASHOKA" in e.open_positions, (
        "the position was removed from the book on an order the broker "
        "refused -- the bot now thinks it is flat and is not")


def test_a_refused_sell_books_no_profit_and_no_loss():
    """The check has to come BEFORE the portfolio. Booking the P&L and
    then bailing would leave the trade counted and the position open."""
    e = _engine(refuse=True)
    e._exit("ASHOKA", 126.85, "BUYING_DRIED_UP", datetime(2026, 8, 31, 11, 9))
    assert e.portfolio.booked == [], "P&L was booked for a trade that never happened"
    assert e.closed_positions == [], "a closed trade was recorded for it"


def test_the_order_was_still_attempted():
    """It must try. Refusing to send is a different bug."""
    e = _engine(refuse=True)
    e._exit("ASHOKA", 126.85, "STOP", datetime(2026, 8, 31, 11, 9))
    assert e.execution.calls == [("SELL", "ASHOKA", 100)]


def test_the_next_tick_can_try_again():
    """Same shape as flatten_all()'s missing-price branch: it says so
    and retries, rather than falsifying the book."""
    e = _engine(refuse=True)
    e._exit("ASHOKA", 126.85, "STOP", datetime(2026, 8, 31, 11, 9))
    e.execution.refuse = False
    e._exit("ASHOKA", 126.50, "STOP", datetime(2026, 8, 31, 11, 10))
    assert "ASHOKA" not in e.open_positions
    assert len(e.closed_positions) == 1


# ------------------------------------------------- it does not overreach

def test_a_successful_sell_still_closes_normally():
    e = _engine(refuse=False)
    e._exit("ASHOKA", 126.85, "BUYING_DRIED_UP", datetime(2026, 8, 31, 11, 9))
    assert "ASHOKA" not in e.open_positions
    assert len(e.closed_positions) == 1
    assert e.portfolio.booked


def test_an_executor_that_reports_no_success_key_is_trusted():
    """A missing key means the executor does not report one -- not that
    the order failed. Inventing a failure out of an unfamiliar shape
    would strand every position behind a stub that returns None."""
    assert eng._order_went_through({}) is True
    assert eng._order_went_through(None) is True
    assert eng._order_went_through({"price": 100.0}) is True
    assert eng._order_went_through({"success": True}) is True
    assert eng._order_went_through({"success": False}) is False


def test_only_an_explicit_false_counts_as_a_refusal():
    """Not falsy -- False. An executor returning success=0 or "" would
    be a shape nobody has written, and guessing at it is how a working
    exit gets blocked."""
    assert eng._order_went_through({"success": 0}) is True
    assert eng._order_went_through({"success": ""}) is True


# ----------------------------------------------- entry already did this

def test_the_entry_path_has_always_checked():
    """The asymmetry is the finding. This is here so the two paths
    cannot drift apart again."""
    import inspect

    enter = inspect.getsource(eng.Engine._enter)
    assert 'result.get("success")' in enter

    exit_src = inspect.getsource(eng.Engine._exit)
    assert "_order_went_through(result)" in exit_src, (
        "the exit path no longer checks whether the order went through")
