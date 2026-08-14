"""
==========================================================
A stock cannot trade outside its own day range
==========================================================

    "dashboard showing high & low of orb range right? & cmp is the
     live rate of stock"          -- operator, 13 August 2026

Two answers, and the second one was a defect he found by asking.

WHAT THE COLUMNS ARE
--------------------
High and Low are the DAY's high and low, from Dhan's quote `ohlc`
block via core/circuit_monitor.py. They are NOT the 09:15-09:30
opening range -- that lives in the engine and is not on this board.
CMP is the live traded price.

THE DEFECT
----------
Those two come from different sources at different rates.
_compute_gl_rows() prefers the LIVE TICK for last_price -- deliberately,
since 28 July, because right after the open the REST snapshot has a
prev_close but no LTP -- while open/high/low still come from the REST
quote, which lags by a poll cycle.

Measured at 10:36 on 100 live rows:

    CMP above the High   34
    CMP below the Low    29
    worst  SARDAEN  high 514.40  CMP 534.65   3.94% outside

63 rows out of 100 showed a stock trading outside its own day range,
on the screen used to decide entries.

THE FIX IS NOT INVENTED DATA
----------------------------
If a stock is trading at 534.65 then the day's high is AT LEAST
534.65 -- that is arithmetic, not an estimate. The range widens to
include the price already on the row; the REST value still wins
whenever it is genuinely the extreme.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest


class _Engine:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def get_circuit_snapshot(self):
        return self._snapshot


class _Loader:
    def get_by_symbol(self, symbol):
        return {"SECTOR": "IT"}


class _MarketData:
    """The LIVE TICK source. This is the half of the mismatch that is
    fresh -- _compute_gl_rows prefers it over the REST snapshot's
    last_price, which is exactly why the price can sit outside a
    lagging high/low."""

    def __init__(self, price):
        self._price = price

    def get_latest_price(self, symbol):
        return self._price


def _rows(quote):
    """One symbol through the real builder."""
    from dashboard.state import DashboardState

    state = DashboardState.__new__(DashboardState)
    state.engine = _Engine({"TCS": quote})
    state.master_loader = _Loader()
    state.market_data = _MarketData(quote.get("last_price"))
    return DashboardState._compute_gl_rows(state)


BASE = {"prev_close": 100.0, "open": 101.0, "high": 104.0, "low": 100.5,
        "upper_circuit_limit": None, "lower_circuit_limit": None,
        "volume": 1000}


def test_a_price_above_the_stale_high_widens_the_high():
    """THE REGRESSION. SARDAEN traded 3.94% above its own day high."""
    quote = dict(BASE, last_price=110.0)
    row = _rows(quote)[0]
    assert row["high"] >= row["ltp"], (
        f"day high {row['high']} is below the traded price {row['ltp']} -- "
        f"a stock cannot trade above its own high")
    assert row["high"] == 110.0


def test_a_price_below_the_stale_low_widens_the_low():
    quote = dict(BASE, last_price=95.0)
    row = _rows(quote)[0]
    assert row["low"] <= row["ltp"]
    assert row["low"] == 95.0


def test_a_price_inside_the_range_changes_nothing():
    """The REST value wins when it really is the extreme -- this must
    not quietly replace the day range with the last tick."""
    quote = dict(BASE, last_price=102.0)
    row = _rows(quote)[0]
    assert row["high"] == 104.0
    assert row["low"] == 100.5


def test_the_open_is_left_alone():
    """Only the RANGE is widened. The open is a fact about 09:15 and
    has nothing to do with the current price."""
    quote = dict(BASE, last_price=110.0)
    row = _rows(quote)[0]
    assert row["open"] == 101.0


def test_a_missing_high_falls_back_to_the_price():
    """Right after the open the REST quote often has no OHLC yet."""
    quote = dict(BASE, high=None, low=None, last_price=103.0)
    row = _rows(quote)[0]
    assert row["high"] == 103.0
    assert row["low"] == 103.0


@pytest.mark.parametrize("price", [110.0, 95.0, 102.0])
def test_the_invariant_holds_for_every_shape(price):
    row = _rows(dict(BASE, last_price=price))[0]
    assert row["low"] <= row["ltp"] <= row["high"], row
