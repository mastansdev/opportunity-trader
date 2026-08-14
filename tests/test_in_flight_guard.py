"""
==========================================================
One order per symbol at a time
==========================================================

    "u said we will buy in mtf only - 1st click no response & no way to
     check in dashboard, then i clicked the second one. now both orders
     gave me loss of huge amount"
                                    -- operator, 3 August 2026

THE MORNING, FROM THE LOG
-------------------------
    09:17:23  Sending BUY YASHO qty=24 MARKET (MTF), intent 4114.10
    09:17:34  order 23126080314805 still not confirmed after 10s.
              It may yet fill. CHECK YOUR DHAN APP.
    09:18:12  (clicked again)
    09:18:14  LIVE BUY YASHO qty=23 @ 4173.00     <- Rs 59 higher
    09:29:43  [MISSED_STOP] exiting at 3956.50

Then the first order filled too. He held 24 shares the bot had never
heard of, and had paid a worse average for the privilege.

TWO THINGS WERE MISSING, AND ONE IS NOT ENOUGH
----------------------------------------------
SHOWING him the in-flight order (tests/test_orders_panel.py) is the
first half. It is not sufficient: ten seconds of silence looks exactly
like a click that did nothing, and a man watching a position move will
click again. So the second click is REFUSED while the first is
unresolved.

REMEMBERING the order is the second half. "not confirmed in time" used
to be the end of the story -- the bot said it and forgot it. Now it is
kept, re-checked on every heartbeat, and a late fill is announced
loudly instead of becoming an invisible position.

WHAT MUST NOT HAPPEN
--------------------
The guard must clear itself. A symbol blocked forever because one order
once timed out would be a second bug wearing the first one's clothes --
so the record is dropped the instant Dhan says FILLED or CANCELLED, and
a broker that cannot be reached leaves it in flight rather than
guessing either way.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from trading.live_execution import LiveExecution


class Dhan:
    """Just enough of the Dhan client for the in-flight paths."""

    def __init__(self, status="PENDING", price=4114.10, qty=24):
        self.status = status
        self.price = price
        self.qty = qty
        self.asked = 0
        self.raises = False

    def get_order_by_id(self, order_id):
        self.asked += 1
        if self.raises:
            raise RuntimeError("connection reset")
        return {"data": {"orderStatus": self.status,
                         "averageTradedPrice": self.price,
                         "filledQty": self.qty}}


def live(dhan=None):
    ex = LiveExecution.__new__(LiveExecution)
    import threading
    ex.dhan = dhan or Dhan()
    ex._lock = threading.Lock()
    ex._in_flight = {}
    return ex


def stranded(ex, symbol="YASHO", side="BUY", qty=24, order_id="23126080314805"):
    """The exact state the bot was in at 09:17:34."""
    ex._in_flight[symbol] = {"order_id": order_id, "tag": "OTtag",
                             "side": side, "qty": qty,
                             "at": "2026-08-03T09:17:34"}


# ---------------------------------------------------------------
# 1. THE RECORD
# ---------------------------------------------------------------
def test_an_unresolved_order_is_remembered_against_its_symbol():
    ex = live()
    stranded(ex)
    got = ex.in_flight("YASHO")
    assert got["order_id"] == "23126080314805"
    assert got["side"] == "BUY" and got["qty"] == 24


def test_a_symbol_with_nothing_outstanding_is_clear():
    assert live().in_flight("URBANCO") is None


def test_the_lookup_is_case_insensitive():
    ex = live()
    stranded(ex)
    assert ex.in_flight("yasho") is not None


def test_the_whole_map_is_available_for_the_panel():
    ex = live()
    stranded(ex)
    stranded(ex, symbol="ABCAPITAL", order_id="999")
    assert set(ex.in_flight()) == {"YASHO", "ABCAPITAL"}


def test_the_map_is_a_copy_not_the_live_dict():
    """A panel iterating this while the trading thread writes to it is
    a crash waiting for a busy morning."""
    ex = live()
    stranded(ex)
    ex.in_flight()["YASHO"]["qty"] = 9999
    assert ex.in_flight("YASHO")["qty"] == 24


# ---------------------------------------------------------------
# 2. IT RESOLVES, AND IT CLEARS
# ---------------------------------------------------------------
def test_a_late_fill_is_reported_so_it_can_be_put_in_the_book():
    """The 24 YASHO shares nothing knew about."""
    ex = live(Dhan(status="TRADED", price=4114.10, qty=24))
    stranded(ex)
    got = ex.resolve_in_flight()
    assert len(got) == 1
    assert got[0]["symbol"] == "YASHO"
    assert got[0]["qty"] == 24 and got[0]["price"] == 4114.10


def test_a_filled_order_stops_blocking_the_symbol():
    ex = live(Dhan(status="TRADED"))
    stranded(ex)
    ex.resolve_in_flight()
    assert ex.in_flight("YASHO") is None


@pytest.mark.parametrize("status", ["CANCELLED", "REJECTED"])
def test_a_dead_order_clears_without_claiming_a_fill(status):
    ex = live(Dhan(status=status))
    stranded(ex)
    assert ex.resolve_in_flight() == []
    assert ex.in_flight("YASHO") is None


def test_an_order_still_pending_stays_in_flight():
    ex = live(Dhan(status="PENDING"))
    stranded(ex)
    assert ex.resolve_in_flight() == []
    assert ex.in_flight("YASHO") is not None


def test_a_broker_we_cannot_reach_leaves_it_in_flight():
    """Refusing a click is cheap. Assuming an order died when it is
    live is how you end up long twice."""
    dhan = Dhan()
    dhan.raises = True
    ex = live(dhan)
    stranded(ex)
    assert ex.resolve_in_flight() == []
    assert ex.in_flight("YASHO") is not None


def test_resolving_never_raises_into_the_trading_loop():
    dhan = Dhan()
    dhan.raises = True
    ex = live(dhan)
    stranded(ex)
    ex.resolve_in_flight()      # must not raise


# ---------------------------------------------------------------
# 3. THE SECOND CLICK
# ---------------------------------------------------------------
def test_the_dashboard_refuses_a_buy_while_one_is_in_flight():
    """     "then i clicked the second one"

    Showing him the pending order is not enough -- silence looks like a
    click that did nothing. The refusal is the part that stops it."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find("ONE ORDER PER SYMBOL AT A TIME"):]
    block = block[:block.find("trade_controller.request_buy")]
    assert 'getattr(executor, "in_flight", None)' in block
    assert '"success": False' in block
    assert "would buy it twice" in block


def test_the_refusal_names_the_outstanding_order():
    """"No" is not an answer when he is holding a moving position. The
    message has to say WHAT is outstanding so he can go and look."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find("ONE ORDER PER SYMBOL AT A TIME"):]
    block = block[:block.find("trade_controller.request_buy")]
    for part in ("order_id", "ORDERS panel", "Dhan app"):
        assert part in block, part


def test_a_failed_in_flight_check_does_not_block_trading():
    """The guard must not become a new way to refuse a good order."""
    src = open("dashboard/server.py", encoding="utf-8").read()
    block = src[src.find("ONE ORDER PER SYMBOL AT A TIME"):]
    block = block[:block.find("trade_controller.request_buy")]
    assert "Not blocking on it" in block


# ---------------------------------------------------------------
# 4. SOMETHING ACTUALLY CALLS IT
# ---------------------------------------------------------------
def test_the_trading_loop_sweeps_for_late_fills():
    """Built, tested and never called is this project's oldest bug."""
    src = open("main.py", encoding="utf-8").read()
    assert "resolve_in_flight" in src
    block = src[src.find("ASK WHAT BECAME OF THE ORDERS THAT TIMED OUT"):]
    block = block[:block.find("last_heartbeat >=")]
    assert "LATE FILL" in block
    assert "NOT in the bot's book" in block
    assert "except Exception" in block, (
        "a follow-up check must never be able to stop the session it "
        "exists to protect")


def test_the_timeout_path_records_the_order():
    """The moment that used to be the end of the story."""
    src = open("trading/live_execution.py", encoding="utf-8").read()
    block = src[src.find('if state == "UNCONFIRMED":'):]
    block = block[:block.find("if state in DEAD:")]
    assert "self._in_flight[symbol]" in block
    assert "IN FLIGHT" in block
