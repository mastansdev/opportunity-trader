"""
==========================================================
The panel that would have saved Rs 11,000
==========================================================

    "no NIFTY 50, BANKNIFTY, ORDERS TABLE = EXECUTED, PENDING,
     CANCELLED"
    "u said we will buy in mtf only - 1st click no response & no way to
     check in dashboard, then i clicked the second one. now both orders
     gave me loss of huge amount"
                                    -- operator, 3 August 2026

WHAT HAPPENED, FROM THE LOG
---------------------------
    09:17:23  Sending BUY YASHO qty=24 MARKET (MTF), intent 4114.10
    09:17:34  order 23126080314805 still not confirmed after 10s.
              It may yet fill. CHECK YOUR DHAN APP.
    09:18:12  (he clicked BUY again)
    09:18:14  LIVE BUY YASHO qty=23 @ 4173.00
    09:29:43  [MISSED_STOP] exiting at 3956.50

The first order was sitting at the exchange, unconfirmed, and there was
NOWHERE ON THE DASHBOARD to see that. The page knew about positions and
about the bot's own book, and had never once asked the broker what
orders were outstanding. So "did my click do anything?" had no answer,
and the only way to find out was to click again.

Both filled. He was long twice at a worse average and the bot knew
about neither.

THE RULE THIS FILE PINS
-----------------------
An order that is not finished must be VISIBLE and must be COUNTED.
"Could not ask the broker" and "you have no orders" are different
sentences and must never be drawn the same way -- the first means look
at your phone, the second means relax, and confusing them is how this
happened.

An UNKNOWN status counts as in flight. Calling something finished when
it is not is the mistake that cost money; the reverse costs a glance.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from dashboard.state import DashboardState


class Executor:
    def __init__(self, rows):
        self.rows = rows
        self.asked = 0

    def orders(self):
        self.asked += 1
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


class Engine:
    def __init__(self, rows):
        self.execution = Executor(rows)


def state_with(rows):
    """A DashboardState with nothing but an order reader wired."""
    state = DashboardState.__new__(DashboardState)
    state.engine = Engine(rows)
    return state


def order(symbol, status, qty=10, **kw):
    row = {"tradingSymbol": symbol, "transactionType": "BUY",
           "quantity": qty, "orderStatus": status,
           "orderId": "id-" + symbol, "productType": "MTF"}
    row.update(kw)
    return row


# ---------------------------------------------------------------
# 1. THE MORNING, REPLAYED
# ---------------------------------------------------------------
def test_an_unconfirmed_order_is_visible_and_counted():
    """The whole reason this panel exists. At 09:17 this row existed at
    Dhan and appeared nowhere on his screen."""
    got = state_with([order("YASHO", "PENDING", 24)]).build_orders()
    assert got["available"] is True
    assert got["n_pending"] == 1
    assert got["pending"][0]["symbol"] == "YASHO"


def test_both_yasho_orders_are_separable():
    """One in flight, one filled -- exactly the state at 09:18:14, and
    the difference he could not see."""
    got = state_with([
        order("YASHO", "PENDING", 24),
        order("YASHO", "TRADED", 23, averageTradedPrice=4173.00),
    ]).build_orders()
    assert got["n_pending"] == 1 and got["n_filled"] == 1
    assert got["filled"][0]["price"] == 4173.00


@pytest.mark.parametrize("status", [
    "PENDING", "TRANSIT", "PART_TRADED", "TRIGGER_PENDING", "MODIFIED",
])
def test_every_in_flight_word_dhan_uses_counts_as_pending(status):
    assert state_with([order("X", status)]).build_orders()["n_pending"] == 1


@pytest.mark.parametrize("status", ["TRADED", "EXECUTED", "COMPLETE"])
def test_a_finished_order_is_not_pending(status):
    got = state_with([order("X", status)]).build_orders()
    assert got["n_filled"] == 1 and got["n_pending"] == 0


@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED", "EXPIRED"])
def test_a_dead_order_is_its_own_bucket(status):
    got = state_with([order("X", status)]).build_orders()
    assert got["n_cancelled"] == 1 and got["n_pending"] == 0


def test_an_unknown_status_is_treated_as_still_in_flight():
    """Calling something finished when it is not is the expensive
    mistake. The reverse costs a glance."""
    got = state_with([order("X", "SOME_NEW_DHAN_WORD")]).build_orders()
    assert got["n_pending"] == 1
    assert got["pending"][0]["status"] == "SOME_NEW_DHAN_WORD"


def test_a_rejection_carries_its_reason():
    got = state_with([order("SPORTKING", "REJECTED",
                            omsErrorDescription="insufficient margin")
                      ]).build_orders()
    assert "insufficient margin" in got["cancelled"][0]["why"]


# ---------------------------------------------------------------
# 2. "COULD NOT ASK" IS NOT "NO ORDERS"
# ---------------------------------------------------------------
def test_an_unreachable_broker_is_not_an_empty_order_book():
    got = state_with(None).build_orders()
    assert got["available"] is False
    assert "not" in got["note"].lower()


def test_a_broker_that_raises_does_not_take_the_panel_down():
    got = state_with(RuntimeError("connection reset")).build_orders()
    assert got["available"] is False
    assert "connection reset" in got["note"]


def test_paper_mode_says_so_rather_than_showing_nothing():
    state = DashboardState.__new__(DashboardState)
    state.engine = type("E", (), {"execution": object()})()
    got = state.build_orders()
    assert got["available"] is False
    assert "PAPER" in got["note"]


def test_an_empty_book_is_available_and_empty():
    """Genuinely no orders. Different from every case above."""
    got = state_with([]).build_orders()
    assert got["available"] is True
    assert got["n_pending"] == got["n_filled"] == got["n_cancelled"] == 0


# ---------------------------------------------------------------
# 3. IT MUST NOT HAMMER THE ACCOUNT ORDERS GO THROUGH
# ---------------------------------------------------------------
def test_the_broker_is_not_asked_on_every_refresh():
    """The dashboard refreshes every second. Being rate-limited at the
    moment he needs to see a pending order is the failure this throttle
    prevents."""
    state = state_with([order("X", "PENDING")])
    for _ in range(20):
        state.build_orders()
    assert state.engine.execution.asked == 1


# ---------------------------------------------------------------
# 4. IT REACHES THE PAGE
# ---------------------------------------------------------------
def test_the_payload_carries_the_orders():
    """Built, tested and invisible is this project's oldest bug -- the
    watchlist, the broker panel and the chain summary all shipped that
    way. The wire is asserted here."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    # Takes his open book now, so a filled order can be labelled
    # HOLDING or CLOSED rather than just TRADED. 3 August 2026.
    assert '"orders": self.build_orders(open_positions),' in src


def test_the_page_renders_them_and_never_hides_them():
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "function renderOrders" in html
    assert "renderOrders(snap.orders)" in html
    assert 'id="otOrders"' in html
    # Outside the tab sections, so it shows on every tab, and NOT inside
    # a fold -- an in-flight order must never be one click away.
    assert html.index('id="otOrders"') < html.index('id="tabNav"')
    assert '"otOrders"' not in html[html.index("var FOLD = ["):
                                    html.index("var FOLD = [") + 400]


def test_the_indices_are_on_screen_at_all_times():
    """     "no NIFTY 50, BANKNIFTY"

    They were in the payload all along, inside Market Intelligence --
    which is now folded, so they went from hard to find to impossible."""
    html = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "function renderTopStrip" in html
    assert 'id="otTopStrip"' in html
    assert html.index('id="otTopStrip"') < html.index('id="tabNav"')
    for name in ("NIFTY 50", "BANKNIFTY", "MIDCAP", "INDIA VIX"):
        assert name in html


def test_the_broker_read_exists_on_the_executor():
    src = open("trading/live_execution.py", encoding="utf-8").read()
    assert "def orders(self):" in src
    assert "get_order_list()" in src
