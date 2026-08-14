"""
==========================================================
An empty book is not a missing book
==========================================================

    Traceback (most recent call last):
      File "main.py", line 1400, in main
        dashboard_state.refresh()
      File "dashboard/state.py", line 2236, in build_book
        symbol = str(entry.get("tradingSymbol")
    AttributeError: 'str' object has no attribute 'get'
                                    -- 4 August 2026, 07:35

WHAT HAPPENED
-------------
LiveExecution.positions() read:

    return (response or {}).get("data") or response or []

Dhan answers {"data": [], "remarks": "", "status": "success"} when you
hold nothing. An empty list is FALSY, so the `or` chain skipped it and
returned THE ENVELOPE. Iterating a dict yields its keys, so build_book
received the strings 'data', 'remarks' and 'status' and died on the
first .get().

It could only ever fire on a day the operator was completely flat. He
closed everything on 3 August, and the next morning main.py would not
start.

THE PART THAT IS MINE
---------------------
This is the SAME idiom that hid Dhan's refusal reason in
core/broker_funds.py, which I had fixed a few hours earlier the same
night. I fixed the one instance in front of me and never searched for
the pattern. grep found it again in orders() -- where build_orders
guards its own iteration, so instead of crashing it would have shown an
EMPTY ORDER BOOK on a morning with orders in it. Quieter and worse.

None still means "could not ask". [] means "you hold nothing". Those
two must never merge -- the panel draws them differently on purpose.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from trading.live_execution import LiveExecution


class Dhan:
    def __init__(self, reply):
        self.reply = reply

    def get_positions(self):
        return self.reply

    def get_order_list(self):
        return self.reply


def broker(reply):
    ex = LiveExecution.__new__(LiveExecution)
    ex.dhan = Dhan(reply)
    return ex


FLAT = {"data": [], "remarks": "", "status": "success"}
ONE = {"data": [{"tradingSymbol": "TITAN", "netQty": 28}], "status": "success"}


# ---------------------------------------------------------------
# 1. THE CRASH
# ---------------------------------------------------------------
@pytest.mark.parametrize("method", ["positions", "orders"])
def test_a_flat_book_returns_an_empty_list_not_the_envelope(method):
    got = getattr(broker(FLAT), method)()
    assert got == []


@pytest.mark.parametrize("method", ["positions", "orders"])
def test_iterating_the_result_never_yields_a_string(method):
    """The whole failure in one line: for entry in broker -> 'data'."""
    for row in getattr(broker(FLAT), method)():
        assert isinstance(row, dict), row


@pytest.mark.parametrize("method", ["positions", "orders"])
def test_a_real_row_still_comes_through(method):
    got = getattr(broker(ONE), method)()
    assert got[0]["tradingSymbol"] == "TITAN"


@pytest.mark.parametrize("method", ["positions", "orders"])
def test_a_refusal_is_not_read_as_holdings(method):
    refused = {"data": "", "remarks": "bad token", "status": "failure"}
    assert getattr(broker(refused), method)() == []


@pytest.mark.parametrize("method", ["positions", "orders"])
def test_a_bare_list_is_passed_through(method):
    assert getattr(broker([{"tradingSymbol": "X"}]), method)() == \
        [{"tradingSymbol": "X"}]


# ---------------------------------------------------------------
# 2. "COULD NOT ASK" IS STILL ITS OWN ANSWER
# ---------------------------------------------------------------
@pytest.mark.parametrize("method", ["positions", "orders"])
def test_none_means_could_not_ask(method):
    """     "'we could not ask' must never be drawn as 'you hold
             nothing'." """
    assert getattr(broker(None), method)() is None


@pytest.mark.parametrize("method", ["positions", "orders"])
def test_a_raised_call_is_none_not_empty(method):
    class Angry:
        def get_positions(self):
            raise RuntimeError("no route")
        get_order_list = get_positions

    ex = LiveExecution.__new__(LiveExecution)
    ex.dhan = Angry()
    assert getattr(ex, method)() is None


# ---------------------------------------------------------------
# 3. THE PANEL SURVIVES A BAD SHAPE ANYWAY
# ---------------------------------------------------------------
def test_build_book_refuses_to_iterate_a_dict():
    """A broker reply is somebody else's data structure. The reader is
    fixed, and the panel no longer trusts it blindly either."""
    import types
    from dashboard.state import DashboardState

    class Ex:
        def positions(self):
            return FLAT                      # the un-normalised envelope

    st = DashboardState.__new__(DashboardState)
    st.engine = types.SimpleNamespace(execution=Ex())
    st.market_data = types.SimpleNamespace(get_latest_price=lambda s: None)
    st.master_loader = types.SimpleNamespace(get_by_symbol=lambda s: None)
    out = st.build_book({})
    assert out["rows"] == []


# ---------------------------------------------------------------
# 4. THE IDIOM IS GONE FROM BOTH READERS
# ---------------------------------------------------------------
def test_neither_reader_uses_the_falsy_or_chain_any_more():
    """Found the second one by searching for the pattern instead of
    waiting for it to fire. That search is the lesson, not the fix."""
    src = open("trading/live_execution.py", encoding="utf-8").read()
    code = "\n".join(line for line in src.splitlines()
                     if not line.strip().startswith("#"))
    assert 'get("data") or response or []' not in code
