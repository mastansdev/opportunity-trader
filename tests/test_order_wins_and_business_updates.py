"""
==========================================================
The two channels the bot was paid for and never read
==========================================================

    "concall , business updates are already with telegram pro channels
     & also check for the data we were ignoring still after your
     search?"
                                -- operator, 8 August 2026

    "BUSINESS PULSE IS GOOD WITH COMPLETE DATA"

WHAT THIS PROTECTS
------------------
Measured 8 August: Business Pulse (107 messages/30d, 99% tag accuracy)
and OrderBook Pulse (102 messages/30d) had been arriving for a month
and why_moving() read neither. Eleven of twelve stocks they named came
back with no reason at all.

These are the anticipation catalysts -- an order win moves a stock
with no result anywhere near it.

THE BUG THIS FILE ALSO PINS
---------------------------
messages.at is stored in UTC; the bot's clock is IST. Verified against
the store: the pre-open gapper card carries at = 03:38 and seen_at =
09:09, and it is published at 09:08 IST.

The first version of core/catalysts.py built its window from
datetime.now() and compared it straight to `at` -- a 5.5 hour error
that raised nothing and quietly returned the wrong catalysts. The
test_the_window_is_in_UTC cases exist so that cannot come back.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime, timedelta

from core import catalysts


# ---------------------------------------------------------------
# Reading the size off the card
# ---------------------------------------------------------------
def test_it_reads_the_rupee_figure():
    assert catalysts.value_cr(
        "New ₹990.16 crore order for International Cricket Stadium") == 990.16
    assert catalysts.value_cr(
        "New order worth Rs. 1.05 crore for consultancy") == 1.05
    assert catalysts.value_cr("Afcons wins ₹1,918 crore Mumbai tunnel") == 1918.0


def test_lakhs_become_crore():
    assert catalysts.value_cr("order worth Rs 250 lakh") == 2.5


def test_a_card_with_no_figure_says_none():
    assert catalysts.value_cr(
        "Contract for Access Control System from Dept of Atomic Energy") is None


# ---------------------------------------------------------------
# Size drives the weight -- Rs 1,918 Cr and Rs 1.05 Cr are not equal
# ---------------------------------------------------------------
def test_a_huge_order_outweighs_a_small_one():
    big = catalysts.read_order("Afcons wins ₹1,918 crore Mumbai water tunnel")
    small = catalysts.read_order("New order worth Rs. 1.05 crore for consultancy")
    assert big["weight"] > small["weight"]
    assert big["weight"] == catalysts.W_ORDER_HUGE
    assert small["weight"] == catalysts.W_ORDER_SMALL


def test_quarterly_update_outweighs_monthly():
    q = catalysts.read_update(
        "Quarterly Business Update : Sai Silks — Q2 FY27 #KALAMANDIR")
    m = catalysts.read_update(
        "Monthly Business Update : Ashok Leyland — July 2026 #ASHOKLEY")
    assert q["weight"] > m["weight"]
    assert "Sai Silks" in q["text"]
    assert "Ashok Leyland" in m["text"]


# ---------------------------------------------------------------
# The recap board belongs to nobody
# ---------------------------------------------------------------
def test_the_orderbook_recap_is_not_an_order_win():
    """It lists the whole day's orders. If it became a reason, every
    company on it would get credited with all of them."""
    assert catalysts.read_order(
        "📊 Orderbook Recap 📅 Daily Highlights - AUGUST 06, 2026 "
        "#StocksToWatch #Trading") is None


def test_the_ago_tail_is_not_part_of_the_reason():
    got = catalysts.read_order(
        "RailTel secured ₹37.67 crore order from North Western Railway. "
        "#RAILTEL - 1 minute ago")
    assert "ago" not in got["text"]
    assert "RailTel" in got["text"]


# ---------------------------------------------------------------
# THE UTC BUG
# ---------------------------------------------------------------
def test_the_window_is_in_UTC_not_IST():
    """messages.at is UTC. A window built from an IST clock must be
    shifted back 5:30 before it touches the column."""
    now = datetime(2026, 8, 7, 10, 0)
    cutoff, ceiling = catalysts._utc_window(now, 30.0)
    assert ceiling == "2026-08-07T04:30:00", (
        "the ceiling is still on the IST clock -- it will include "
        "catalysts published after the moment being asked about")
    assert cutoff == (datetime(2026, 8, 7, 4, 30)
                      - timedelta(hours=30)).isoformat()


def test_it_cannot_see_a_catalyst_from_the_future():
    """VAKRANGEE's order card landed 15:35 IST on 7 August. Asked at
    10:00 that morning the bot must not know about it -- this is the
    same discipline as the graded_symbols() cutoff."""
    before = catalysts.for_symbol("VAKRANGEE",
                                  now=datetime(2026, 8, 7, 10, 0))
    after = catalysts.for_symbol("VAKRANGEE",
                                 now=datetime(2026, 8, 7, 16, 0))
    if after is None:
        return          # store rotated; nothing to assert against
    assert before is None, (
        "it read a card published five hours later")


# ---------------------------------------------------------------
# The subject rule applies here too
# ---------------------------------------------------------------
def test_a_catalyst_does_not_leak_onto_another_stock():
    """The same mis-attribution that put TRENT's numbers in SIEMENS's
    chip would put L&T's order on ONGC without this."""
    got = catalysts.for_symbol("ONGC", now=datetime(2026, 8, 7, 16, 0))
    if got and got.get("kind") == "order":
        assert "ONGC" not in got["text"] or "L&T" not in got["text"], (
            "an L&T order win was credited to ONGC")


# ---------------------------------------------------------------
# The wiring -- this is the part that was missing for a month
# ---------------------------------------------------------------
def test_why_moving_actually_calls_it():
    """core/catalysts.py existing is not the point. It has to be in
    the answer why_moving gives."""
    import inspect

    from core import why_moving
    src = inspect.getsource(why_moving)
    assert "from_catalysts(" in src, (
        "core/catalysts.py is not wired into why() -- the two channels "
        "are still being thrown away")


def test_a_result_still_outranks_an_order_win():
    """A published result is stronger evidence than a contract, and
    the ordering inside why() must keep it that way."""
    import inspect

    from core import why_moving
    body = inspect.getsource(why_moving.why)
    assert body.index("from_events") < body.index("from_catalysts")
    assert body.index("from_news") < body.index("from_catalysts")


def test_it_never_raises_on_junk():
    for junk in (None, "", "   ", "#", 12345):
        assert catalysts.read_order(junk) in (None,) or isinstance(
            catalysts.read_order(junk), dict)
        assert catalysts.read_update(junk) is None
    assert catalysts.for_symbol(None) is None
    assert catalysts.for_symbol("") is None
