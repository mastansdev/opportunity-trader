"""
Tests for trading/slippage.py and the paper fill path.

The bug: paper_execution.py filled at the EXACT intent price, instantly,
always. Six months of results were built on that, and paper results are
the yardstick every rule in this bot is measured against.

The first test is the one that matters -- slippage must always be
AGAINST you, in both directions. A model that ever helps is worse than
no model, because it would make the numbers look better than reality
rather than worse.
"""

from datetime import datetime

import pytest

from trading.slippage import (
    BUY, SELL, fill_price, slippage_pct, slippage_cost,
)
from trading.paper_execution import PaperExecution

CALM = datetime(2026, 7, 28, 11, 30)
OPEN_ = datetime(2026, 7, 28, 9, 20)
LIQUID = 500.0      # crores of day turnover
THIN = 3.0


def test_slippage_is_always_against_you():
    """THE property. A buy fills higher, a sell fills lower. Never the
    other way, or the model flatters the results instead of costing."""
    assert fill_price(100.0, BUY, LIQUID, CALM) > 100.0
    assert fill_price(100.0, SELL, LIQUID, CALM) < 100.0


def test_a_thin_stock_costs_more_to_trade_than_a_liquid_one():
    thin = fill_price(100.0, BUY, THIN, CALM)
    liquid = fill_price(100.0, BUY, LIQUID, CALM)
    assert thin > liquid


def test_unknown_liquidity_is_treated_as_THIN():
    """Absence of data about liquidity is not evidence of liquidity.
    The expensive assumption is the safe one."""
    assert slippage_pct(None, CALM) == slippage_pct(THIN, CALM)


def test_the_open_costs_more_than_the_rest_of_the_day():
    """Measured on this project: the operator clicked SUPREMEIND at
    ~3,385 and filled at 3,472.70. The open is where price runs away."""
    assert slippage_pct(LIQUID, OPEN_) > slippage_pct(LIQUID, CALM)


def test_the_opening_penalty_applies_to_thin_stocks_too():
    assert slippage_pct(THIN, OPEN_) > slippage_pct(THIN, CALM)


def test_cost_in_rupees_is_never_negative():
    filled = fill_price(100.0, BUY, THIN, OPEN_)
    assert slippage_cost(100.0, filled, 500, BUY) > 0
    assert slippage_cost(100.0, 100.0, 500, BUY) == 0.0


def test_a_sell_never_fills_below_zero():
    assert fill_price(0.02, SELL, THIN, OPEN_) > 0


def test_a_zero_or_missing_price_passes_straight_through():
    """A cost model must not be able to break an order."""
    assert fill_price(0, BUY, LIQUID, CALM) == 0
    assert fill_price(None, BUY, LIQUID, CALM) is None


def test_a_bad_timestamp_does_not_raise():
    assert fill_price(100.0, BUY, LIQUID, "not a time") > 100.0


def test_slippage_can_be_switched_off_for_like_for_like_backtests():
    import trading.slippage as sl
    original = sl.ENABLE_PAPER_SLIPPAGE
    sl.ENABLE_PAPER_SLIPPAGE = False
    try:
        assert fill_price(100.0, BUY, THIN, OPEN_) == 100.0
    finally:
        sl.ENABLE_PAPER_SLIPPAGE = original


# --------------------------------------------------------------
# The paper execution path
# --------------------------------------------------------------

def test_a_paper_buy_no_longer_fills_at_the_intent_price():
    ex = PaperExecution(turnover_lookup=lambda s: LIQUID)
    result = ex.buy(1, "COFORGE", 1648.10, 121, "TEST", at_time=CALM)
    assert result["price"] > 1648.10
    assert result["intent_price"] == 1648.10
    assert result["slippage_rs"] > 0


def test_a_paper_sell_fills_below_the_intent_price():
    ex = PaperExecution(turnover_lookup=lambda s: LIQUID)
    result = ex.sell(1, "COFORGE", 1648.30, 121, "TEST", at_time=CALM)
    assert result["price"] < 1648.30
    assert result["slippage_rs"] > 0


def test_a_broken_turnover_lookup_degrades_to_thin_not_a_crash():
    def explode(_symbol):
        raise RuntimeError("snapshot not ready")
    ex = PaperExecution(turnover_lookup=explode)
    result = ex.buy(1, "CUPID", 228.11, 876, "TEST", at_time=CALM)
    assert result["success"] is True
    assert result["price"] > 228.11


def test_no_turnover_lookup_at_all_still_works():
    ex = PaperExecution()
    assert ex.buy(1, "CUPID", 228.11, 876, "TEST", at_time=CALM)["success"]


def test_the_trade_log_records_the_price_PAID_not_the_price_wanted(monkeypatch):
    """Otherwise the P&L is a fiction and modelling slippage is
    pointless -- the whole cost would vanish at the last step."""
    captured = {}
    import trading.paper_execution as pe
    monkeypatch.setattr(
        pe, "log_trade",
        lambda side, sym, sid, qty, price, reason: captured.update(price=price),
    )
    ex = PaperExecution(turnover_lookup=lambda s: LIQUID)
    result = ex.buy(1, "COFORGE", 1648.10, 121, "TEST", at_time=CALM)
    assert captured["price"] == result["price"]
    assert captured["price"] != 1648.10
