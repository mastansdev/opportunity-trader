"""
The P&L must be built from what actually filled.

    "check the calculation part of closed positions too"
                                        -- operator, 29 July 2026

THE 11x BUG
-----------
Every execution call returns

    {"success", "order_id", "price", "intent_price", "slippage_rs"}

where `price` is the FILL and `intent_price` is what the engine asked
for. core/engine.py discarded the whole dict and carried on using its
own intended price. Slippage was modelled, printed to the console, and
written to fills.db -- then dropped before it reached the P&L.

Measured over one real session:

    gross on the fills          Rs  1,843.94
    modelled slippage           Rs 19,334.01
    reported by the dashboard   Rs 21,177.95

The reported figure was the gross PLUS the cost that should have been
subtracted. A paper run exists to estimate what live trading would do;
one that deletes its own costs estimates nothing.
"""

import pytest

from core.engine import Engine


class _Result(dict):
    pass


def test_the_fill_price_is_used_not_the_intent():
    got = Engine._filled_at({"success": True, "price": 99.10,
                             "intent_price": 100.0}, 100.0)
    assert got == 99.10


def test_a_missing_price_falls_back_to_the_intent():
    """An executor that does not report a fill is not a reason to lose
    the trade -- but it must not silently invent one either."""
    assert Engine._filled_at({"success": True}, 100.0) == 100.0
    assert Engine._filled_at(None, 100.0) == 100.0
    assert Engine._filled_at({}, 100.0) == 100.0


def test_a_junk_price_falls_back_rather_than_zeroing_the_trade():
    """A zero fill is a broken response, not a free trade. Taking it at
    face value would report an infinite profit."""
    assert Engine._filled_at({"price": 0}, 100.0) == 100.0
    assert Engine._filled_at({"price": -5}, 100.0) == 100.0
    assert Engine._filled_at({"price": "abc"}, 100.0) == 100.0
    assert Engine._filled_at({"price": None}, 100.0) == 100.0


def test_slippage_now_reduces_the_reported_profit():
    """The arithmetic the bug hid. Buy slips up, sell slips down, and
    both cost money -- so the honest P&L must be BELOW the intended
    one, never above it."""
    intended_buy, intended_sell = 100.0, 110.0
    filled_buy = Engine._filled_at({"price": 100.5}, intended_buy)
    filled_sell = Engine._filled_at({"price": 109.4}, intended_sell)
    qty = 100

    on_paper = (intended_sell - intended_buy) * qty      # 1000
    honest = (filled_sell - filled_buy) * qty            # 890
    assert honest < on_paper
    assert round(on_paper - honest, 2) == 110.0, (
        "the difference IS the slippage, and it was being dropped")


@pytest.mark.parametrize("site", [
    "result = self.execution.buy(",
    "result = self.execution.sell(",
])
def test_every_execution_call_keeps_its_result(site):
    """Six call sites. A future one that drops the result reintroduces
    the bug silently, because nothing else changes on screen."""
    src = open("core/engine.py", encoding="utf-8").read()
    assert site in src


def test_no_execution_call_throws_its_result_away():
    src = open("core/engine.py", encoding="utf-8").read()
    for line in src.splitlines():
        stripped = line.strip()
        if stripped.startswith("self.execution.buy(") or \
                stripped.startswith("self.execution.sell("):
            raise AssertionError(
                f"an execution call ignores its return value: {stripped}. "
                f"That is the 11x P&L bug -- the fill price is in there.")


def test_the_entry_price_is_rebound_before_the_position_is_recorded():
    """Everything downstream -- the stop, the target, the R, the P&L --
    is measured FROM the entry price. Recording the intended one puts
    the error into every number the trade ever produces."""
    # SCOPED TO _enter(). 5 August 2026 -- adopt_position() also writes
    # open_positions[symbol], and it sits above _enter() in the file, so
    # an unscoped find() grabbed the wrong one. Adoption has no fill to
    # resolve: the position already exists at the broker and its price
    # came from Dhan, not from an order this process sent.
    import inspect

    from core.engine import Engine
    src = inspect.getsource(Engine._enter)
    rebind = src.find("price = self._filled_at(result, price)")
    record = src.find('self.open_positions[symbol] = {')
    assert -1 not in (rebind, record)
    assert rebind < record, (
        "the fill must be resolved BEFORE the position is written")
