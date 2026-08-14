"""
Tests for trading/live_execution.py -- the module that spends real money.

Every test here is about a way to LOSE money, not a way to make it. The
three that matter most:

  1. a market order cannot be un-filled, so a price that ran away must
     be refused BEFORE sending
  2. a timeout is NOT a rejection -- the order may have landed, and a
     blind retry buys the stock twice
  3. a bug that loops must hit a hard ceiling, not a hopeful one

Live trading starts 3 August. First real order 30 July.
"""

import pytest

from trading.live_execution import LiveExecution
from config import (
    LIVE_MAX_ORDER_VALUE_RS, LIVE_MAX_ORDERS_PER_DAY,
    LIVE_MAX_PRICE_DRIFT_PCT,
)


class FakeDhan:
    """Records what it was asked to do. Nothing leaves the machine."""

    def __init__(self, place=None, status=None, by_tag=None, raises=False):
        self.calls = []
        self._place = place or {"data": {"orderId": "ORD1"}}
        self._status = status or {"data": {"orderStatus": "TRADED",
                                           "averageTradedPrice": 1690.0,
                                           "filledQty": 225}}
        self._by_tag = by_tag
        self._raises = raises

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        if self._raises:
            raise TimeoutError("no reply")
        return self._place

    def get_order_by_id(self, order_id):
        return self._status

    def get_order_by_correlationID(self, tag):
        return self._by_tag


def _exec(dhan=None, live_price=1686.0, open_count=0):
    return LiveExecution(
        dhan or FakeDhan(),
        price_lookup=(lambda s: live_price) if live_price is not None else None,
        open_position_count=lambda: open_count,
    )


# ---------------------------------------------------------------
# 1. A MARKET ORDER CANNOT BE UN-FILLED
# ---------------------------------------------------------------

def test_a_price_that_ran_away_is_refused_before_sending():
    """2026-07-28, SUPREMEIND: the first click was lost, price ran
    ~3,385 -> 3,472.70 (+2.59%) before the second went through. As a
    live market order that is a real fill at a price never agreed to."""
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=3472.70)
    result = ex.buy(1, "SUPREMEIND", 3385.0, 57, "MANUAL")
    assert result["success"] is False
    assert "price moved" in result["error"]
    assert dhan.calls == []                 # NOTHING was sent


def test_a_small_drift_is_allowed_through():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=1686.0 * (1 + LIVE_MAX_PRICE_DRIFT_PCT / 2))
    assert ex.buy(11543, "COFORGE", 1686.0, 225, "MANUAL")["success"]
    assert len(dhan.calls) == 1


def test_no_price_feed_means_refuse_not_guess():
    """Refusing to send a market order blind is the safe direction."""
    dhan = FakeDhan()
    ex = LiveExecution(dhan, price_lookup=None)
    result = ex.buy(1, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["success"] is False
    assert dhan.calls == []


# ---------------------------------------------------------------
# 2. A TIMEOUT IS NOT A REJECTION
# ---------------------------------------------------------------

def test_a_timeout_never_resends_blindly():
    """The nightmare: the order landed, the reply was lost, the bot
    retries, and now two positions exist and one is known about."""
    dhan = FakeDhan(raises=True, by_tag=None)
    ex = _exec(dhan)
    result = ex.buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["success"] is False
    assert result["needs_human"] is True
    assert len(dhan.calls) == 1             # sent once, never twice


def test_a_timeout_that_DID_reach_dhan_is_reported_not_retried():
    dhan = FakeDhan(raises=True, by_tag={"data": {"orderId": "ORD9"}})
    ex = _exec(dhan)
    result = ex.buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["success"] is False
    assert result["order_id"] == "ORD9"
    assert result["needs_human"] is True
    assert len(dhan.calls) == 1


def test_every_order_carries_a_unique_tag():
    """The correlation ID is the only way to answer "did this land?"."""
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=100.0)
    ex.buy(1, "A", 100.0, 10, "M")
    ex.buy(2, "B", 100.0, 10, "M")
    tags = [c["tag"] for c in dhan.calls]
    assert len(set(tags)) == 2
    assert all(t.startswith("OT") for t in tags)


def test_an_unconfirmed_order_is_flagged_for_a_human(monkeypatch):
    """Never assume filled, never assume not filled."""
    import trading.live_execution as le
    monkeypatch.setattr(le, "LIVE_CONFIRM_TIMEOUT_SECONDS", 0.1)
    dhan = FakeDhan(status={"data": {"orderStatus": "PENDING"}})
    result = _exec(dhan).buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["success"] is False
    assert result["needs_human"] is True


def test_a_rejection_is_reported_plainly():
    dhan = FakeDhan(status={"data": {"orderStatus": "REJECTED"}})
    result = _exec(dhan).buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["success"] is False
    assert "reject" in result["error"].lower()


# ---------------------------------------------------------------
# 3. HARD CEILINGS -- guard rails against a BUG, not risk rules
# ---------------------------------------------------------------

def test_an_order_above_the_value_ceiling_is_refused():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=100.0)
    qty = int(LIVE_MAX_ORDER_VALUE_RS / 100.0) + 100
    result = ex.buy(1, "BIG", 100.0, qty, "MANUAL")
    assert result["success"] is False
    assert "ceiling" in result["error"]
    assert dhan.calls == []


def test_the_daily_order_count_is_capped():
    """A loop that fires fifty orders must be impossible, not unlikely."""
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=100.0)
    for _ in range(LIVE_MAX_ORDERS_PER_DAY + 5):
        ex.buy(1, "X", 100.0, 10, "MANUAL")
    assert len(dhan.calls) == LIVE_MAX_ORDERS_PER_DAY


def test_too_many_open_positions_blocks_a_new_one():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=100.0, open_count=99)
    assert ex.buy(1, "X", 100.0, 10, "MANUAL")["success"] is False
    assert dhan.calls == []


def test_zero_quantity_never_reaches_dhan():
    dhan = FakeDhan()
    assert _exec(dhan, live_price=100.0).buy(1, "X", 100.0, 0, "M")["success"] is False
    assert dhan.calls == []


# ---------------------------------------------------------------
# What actually gets sent
# ---------------------------------------------------------------

def test_it_sends_a_MARKET_order_on_the_MTF_product():
    """The operator's two decisions, 2026-07-28."""
    dhan = FakeDhan()
    _exec(dhan).buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    call = dhan.calls[0]
    assert call["order_type"] == "MARKET"
    assert call["product_type"] == "MTF"
    assert call["transaction_type"] == "BUY"
    assert call["quantity"] == 225


def test_a_fill_reports_the_real_traded_price_not_the_intent():
    dhan = FakeDhan(status={"data": {"orderStatus": "TRADED",
                                     "averageTradedPrice": 1690.0,
                                     "filledQty": 225}})
    result = _exec(dhan).buy(11543, "COFORGE", 1686.0, 225, "MANUAL")
    assert result["price"] == 1690.0
    assert result["intent_price"] == 1686.0
    assert result["slippage_rs"] == pytest.approx(900.0)


# ---------------------------------------------------------------
# The two switches
# ---------------------------------------------------------------

def test_live_mode_refuses_to_start_without_the_second_switch(monkeypatch):
    """One switch is one typo away from spending money by accident."""
    import trading.execution as ex_mod
    monkeypatch.setattr(ex_mod, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(ex_mod, "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS", False)
    with pytest.raises(RuntimeError, match="I_UNDERSTAND"):
        ex_mod.Execution(dhan_client=FakeDhan())


def test_live_mode_refuses_to_start_without_a_client(monkeypatch):
    """It must NOT quietly paper-trade a session believed to be real."""
    import trading.execution as ex_mod
    monkeypatch.setattr(ex_mod, "TRADING_MODE", "LIVE")
    monkeypatch.setattr(ex_mod, "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS", True)
    with pytest.raises(RuntimeError, match="no Dhan client"):
        ex_mod.Execution(dhan_client=None)


def test_paper_is_still_the_default():
    import trading.execution as ex_mod
    assert ex_mod.Execution().mode == "PAPER"


# ---------------------------------------------------------------
# FIRST CONTACT WITH THE REAL API -- 30 July
#
# A market order proves the plumbing by spending money. A limit order
# parked 10% away proves it by parking something you can look at in the
# Dhan app and cancel. Nothing fills, nothing is charged.
# ---------------------------------------------------------------

def test_the_test_order_is_priced_where_it_CANNOT_fill():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=1686.0)
    result = ex.place_test_limit(11543, "COFORGE", 1686.0, quantity=1)
    assert result["success"] is True
    call = dhan.calls[0]
    assert call["order_type"] == "LIMIT"
    assert call["quantity"] == 1
    assert call["price"] < 1686.0 * 0.95      # nowhere near the touch


def test_the_test_order_uses_the_MTF_product_like_a_real_one():
    """It has to exercise the SAME path a real order takes, or it
    proves nothing about the thing being tested."""
    dhan = FakeDhan()
    _exec(dhan).place_test_limit(11543, "COFORGE", 1686.0)
    assert dhan.calls[0]["product_type"] == "MTF"


def test_a_sell_test_order_is_parked_ABOVE_the_market():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=1686.0)
    ex.place_test_limit(11543, "COFORGE", 1686.0, side="SELL")
    assert dhan.calls[0]["price"] > 1686.0 * 1.05


def test_the_test_order_still_respects_the_value_ceiling():
    dhan = FakeDhan()
    ex = _exec(dhan, live_price=100.0)
    qty = int(LIVE_MAX_ORDER_VALUE_RS / 90.0) + 1000
    assert ex.place_test_limit(1, "X", 100.0, quantity=qty)["success"] is False
    assert dhan.calls == []


def test_a_test_order_timeout_is_checked_by_tag_not_retried():
    dhan = FakeDhan(raises=True, by_tag={"data": {"orderId": "ORD7"}})
    result = _exec(dhan).place_test_limit(11543, "COFORGE", 1686.0)
    assert result["success"] is False
    assert result["order_id"] == "ORD7"
    assert len(dhan.calls) == 1


def test_cancel_reports_a_failure_loudly_rather_than_silently():
    class NoCancel(FakeDhan):
        def cancel_order(self, order_id):
            raise RuntimeError("gateway down")
    result = _exec(NoCancel()).cancel("ORD1")
    assert result["success"] is False
    assert result["needs_human"] is True


def test_cancel_succeeds_when_dhan_accepts_it():
    class CanCancel(FakeDhan):
        def cancel_order(self, order_id):
            return {"data": {"orderStatus": "CANCELLED"}}
    assert _exec(CanCancel()).cancel("ORD1")["success"] is True


def test_positions_reads_from_DHAN_not_from_the_bots_own_book():
    """The bot's book can drift from reality after a restart or a fill
    it never saw. Dhan's cannot."""
    class WithPositions(FakeDhan):
        def get_positions(self):
            return {"data": [{"tradingSymbol": "COFORGE", "netQty": 225}]}
    assert _exec(WithPositions()).positions()[0]["netQty"] == 225


def test_positions_returns_None_when_dhan_cannot_be_reached():
    """None means "I do not know" -- never an empty list, which would
    read as "you hold nothing"."""
    class NoPositions(FakeDhan):
        def get_positions(self):
            raise RuntimeError("down")
    assert _exec(NoPositions()).positions() is None


def test_the_kill_switch_can_be_thrown():
    """Dhan's own emergency stop blocks ALL order placement at the
    broker -- so it still holds if the bot is what has gone wrong."""
    class WithKill(FakeDhan):
        def __init__(self): super().__init__(); self.killed = None
        def kill_switch(self, action): self.killed = action; return {"ok": True}
    dhan = WithKill()
    assert _exec(dhan).kill_switch(True)["success"] is True
    assert dhan.killed == "ACTIVATE"
