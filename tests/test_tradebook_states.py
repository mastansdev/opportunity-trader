"""
==========================================================
The tradebook, readable without moving the mouse
==========================================================

    "TRADEBOOK IS NOT VISIBLE AS IT IS IN SMALL BOX . write some logic
     to color code them without moving the mouse to check everytime.
     like i click on buy = stock appears in trade book with green color
     until i close that once i sell it from open position change the
     color back to normal . or any other distinct one . user must
     recognise that trade is executed or not."
                                    -- operator, 3 August 2026

His instinct is right and the reason is worth naming: THE ORDER BOOK
ALONE CANNOT ANSWER THE QUESTION HE IS ASKING. "TRADED" tells him an
order filled at 09:18. It does not tell him whether he is still
carrying it now, and that is the difference between history and money
at risk.

So the order status is crossed with his open book:

    WAITING    at the exchange, unconfirmed. The YASHO state -- the
               silence that made him click BUY a second time and cost
               him Rs 11,000 on the first live day.
    FAILED     rejected. The dangerous one: he thinks he is in, he is
               not, and nothing else on the screen says otherwise.
    HOLDING    filled AND still in the book. Live money.
    CLOSED     filled, round trip done.
    CANCELLED  he pulled it.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


def raw():
    return {
        "available": True,
        "pending": [{"symbol": "BOSCHLTD", "side": "SELL", "qty": 4,
                     "status": "PENDING", "at": "09:20"}],
        "filled": [
            {"symbol": "TITAN", "side": "BUY", "qty": 28, "price": 3540,
             "status": "TRADED", "at": "09:16"},
            {"symbol": "ABCAPITAL", "side": "SELL", "qty": 100, "price": 268,
             "status": "TRADED", "at": "09:40"}],
        "cancelled": [
            {"symbol": "YASHO", "side": "BUY", "qty": 24, "status": "REJECTED",
             "at": "09:18", "why": "insufficient margin"},
            {"symbol": "SHADOWFAX", "side": "BUY", "qty": 10,
             "status": "CANCELLED", "at": "09:50"}],
        "n_pending": 1, "n_filled": 2, "n_cancelled": 2,
    }


def label(book=None):
    st = DashboardState.__new__(DashboardState)
    return st._label_orders(raw(), book if book is not None else {})


def state_of(out, symbol):
    return next(r["state"] for r in out["rows"] if r["symbol"] == symbol)


# ---------------------------------------------------------------
# 1. FILLED IS NOT THE SAME AS HELD
# ---------------------------------------------------------------
def test_a_filled_order_he_still_holds_reads_as_holding():
    """     "i click on buy = stock appears in trade book with green
             color until i close that" """
    assert state_of(label({"TITAN": {}}), "TITAN") == "HOLDING"


def test_the_same_order_reads_as_closed_once_he_sells_it():
    """     "once i sell it from open position change the color back to
             normal"

    Same order, same TRADED status, different answer -- because the
    question is about the book, not the order."""
    assert state_of(label({}), "TITAN") == "CLOSED"


def test_a_filled_order_for_something_not_held_is_closed():
    assert state_of(label({"TITAN": {}}), "ABCAPITAL") == "CLOSED"


def test_the_book_may_arrive_as_a_dict_or_a_list():
    """open_positions is a dict keyed by symbol in the payload, and a
    list of rows in several tests. Reading only one shape is how the
    shock builder broke ten tests an hour ago."""
    assert state_of(label({"TITAN": {}}), "TITAN") == "HOLDING"
    assert state_of(label([{"symbol": "TITAN"}]), "TITAN") == "HOLDING"


# ---------------------------------------------------------------
# 2. THE TWO THAT NEED HIM
# ---------------------------------------------------------------
def test_an_unconfirmed_order_is_waiting():
    """The YASHO state. An order sitting at the exchange shows up
    nowhere else on the screen, and that silence made him click BUY a
    second time."""
    assert state_of(label(), "BOSCHLTD") == "WAITING"


def test_a_rejected_order_is_not_filed_with_the_cancelled_ones():
    """Cancelling is something he did. Rejection is something that
    happened TO him, and it means he is not in a trade he thinks he is
    in."""
    out = label()
    assert state_of(out, "YASHO") == "FAILED"
    assert state_of(out, "SHADOWFAX") == "CANCELLED"


def test_the_ones_that_need_action_are_at_the_top():
    """A rejected order four rows down is a rejected order he will not
    see."""
    out = label({"TITAN": {}})
    assert [r["state"] for r in out["rows"]][:2] == ["WAITING", "FAILED"]


def test_one_number_says_whether_anything_needs_him():
    out = label({"TITAN": {}})
    assert out["needs_eyes"] == 2          # one waiting, one failed
    assert out["counts"]["HOLDING"] == 1


def test_a_clean_book_needs_nothing():
    st = DashboardState.__new__(DashboardState)
    quiet = {"available": True, "pending": [], "cancelled": [],
             "filled": [{"symbol": "TITAN", "status": "TRADED"}],
             "n_pending": 0, "n_filled": 1, "n_cancelled": 0}
    out = st._label_orders(quiet, {"TITAN": {}})
    assert out["needs_eyes"] == 0


# ---------------------------------------------------------------
# 3. IT NEVER PRETENDS
# ---------------------------------------------------------------
def test_could_not_ask_is_left_alone():
    """     "available: False means WE COULD NOT ASK, which must never
             be drawn the same way as 'you have no orders'." """
    st = DashboardState.__new__(DashboardState)
    out = st._label_orders({"available": False, "note": "no broker"}, {})
    assert out["available"] is False
    assert "rows" not in out


# ---------------------------------------------------------------
# 4. WHAT REACHES THE GLASS
# ---------------------------------------------------------------
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


