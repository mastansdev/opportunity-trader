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


def test_the_labels_are_recomputed_even_when_the_orders_are_cached():
    """The broker rows are cached for a few seconds; his book is not. A
    row still showing HOLDING after he exited would be a lie with money
    behind it."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    block = src[src.index("def build_orders"):src.index("ORDER_STATE_RANK")]
    assert "return self._label_orders(cached, open_positions)" in block
    assert block.count("return cached") == 0


def test_the_payload_passes_his_open_book_in():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"orders": self.build_orders(open_positions),' in src


# ---------------------------------------------------------------
# 4. WHAT REACHES THE GLASS
# ---------------------------------------------------------------
def _html():
    return open("dashboard/static/index.html", encoding="utf-8").read()


def test_the_state_is_carried_on_the_row_edge_not_only_in_words():
    """     "without moving the mouse to check everytime"

    Colour on the left border makes the panel readable from its shape.
    A pill repeats it for anyone who does look."""
    src = _html()
    for cls in ("ot-tb-waiting", "ot-tb-failed", "ot-tb-holding",
                "ot-tb-closed", "ot-tb-cancelled"):
        assert "." + cls in src, cls
    block = src[src.index(".ot-tb {"):src.index(".ot-tb-pill {")]
    assert "border-left" in block


def test_every_state_gets_a_different_colour():
    src = _html()
    assert ".ot-tb-waiting   { border-left-color:var(--amber)" in src
    assert ".ot-tb-failed    { border-left-color:var(--red)" in src
    assert ".ot-tb-holding   { border-left-color:var(--green)" in src


def test_only_the_unresolved_row_moves():
    """One moving thing on a trading screen, and it is the one that is
    not finished. Anything else animating is noise."""
    src = _html()
    assert "@keyframes otBreathe" in src
    assert ".ot-tb-waiting .ot-tb-pill { animation: otBreathe" in src
    # And it respects the accessibility setting.
    assert "prefers-reduced-motion" in src


def test_the_three_stacked_tables_are_gone():
    """Three headings and three tables in a 300px column is three
    headings and no room."""
    src = _html()
    block = src[src.index("ONE LIST, COLOUR-CODED"):]
    block = block[:block.index("</script>")]
    assert "IN FLIGHT —" not in block
    assert "o.rows" in block


def test_the_summary_line_says_it_in_one_glance():
    src = _html()
    block = src[src.index("ONE LIST, COLOUR-CODED"):]
    block = block[:block.index("</script>")]
    for word in ("waiting", "failed", "holding", "closed", "cancelled"):
        assert '"' + word + '"' in block, word


def test_nothing_below_the_readable_floor():
    """The panel he could not read is not fixed by making it smaller."""
    src = _html()
    import re
    block = src[src.index("THE TRADEBOOK, READABLE ACROSS THE ROOM"):]
    block = block[:block.index("prefers-reduced-motion")]
    sizes = [float(m) for m in re.findall(r"font-size:\s*([0-9.]+)px", block)]
    assert sizes and min(sizes) >= 12, sizes
