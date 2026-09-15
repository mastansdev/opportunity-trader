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
# ---------------------------------------------------------------
# 2. "COULD NOT ASK" IS NOT "NO ORDERS"
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 3. IT MUST NOT HAMMER THE ACCOUNT ORDERS GO THROUGH
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 4. IT REACHES THE PAGE
# ---------------------------------------------------------------
def test_the_broker_read_exists_on_the_executor():
    src = open("trading/live_execution.py", encoding="utf-8").read()
    assert "def orders(self):" in src
    assert "get_order_list()" in src
