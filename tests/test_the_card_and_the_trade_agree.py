"""What his phone says is what the trade does.

    "even it disagree (that also made by us right). we need to make
     bot understand & book profits not wait until close every day &
     loose the money"                 -- operator, 29 August 2026

Two independent sizing rules were live at once, and nobody had ever
put them side by side. Walking one real trade through both on
29 August:

    TCS at Rs 3,000        alert card      the trade
    shares                         21              40
    stop                     2,937.50        2,859.53
    risk                     Rs 2,500        Rs 5,619

His phone showed less than half the loss the position actually
carried, and a share count half its size. Nothing in a P&L would ever
have revealed it -- both numbers are individually reasonable, they
were simply computed by different code from different rules.

core/position_plan.py now sizes from the MTF margin, the way
core/engine.py always did, and both derive the stop distance from the
rupee risk over that share count. Same inputs, same arithmetic.

This file is the only thing standing between that and it happening
again, so it compares the two paths directly rather than asserting
either one's numbers.
"""

import pytest

import config
import core.engine as engine_module
from core.engine import Engine, LONG
from core.mtf_margin import MtfMarginBook
from core.position_plan import plan

MARGIN_PCT = 0.25          # what Dhan answers for a liquid large cap


def _margin_book(pct=MARGIN_PCT):
    """A margin book wired the way main.py wires it, with Dhan stubbed."""
    return MtfMarginBook(
        calculator=lambda sec_id, price, qty: {
            "data": {"insufficientBalance": 0,
                     "totalMargin": price * qty * pct}})


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(engine_module, "compute_atr",
                        lambda candles, period: 12.0)
    eng = Engine(mtf_margin=_margin_book())
    eng.candle_engine.last_n_closed = lambda symbol, n: [
        {"high": 3006.0, "low": 2994.0, "close": 3000.0}] * n
    monkeypatch.setattr(Engine, "_market_regime", lambda self: "BOTH")
    return eng


@pytest.mark.parametrize("price", [3000.0, 1400.0, 660.0, 150.0])
def test_the_card_and_the_trade_agree_on_everything(engine, price):
    """Shares, stop and rupees at risk. All three, on every price."""
    card = plan(price, "BUY", day_low=price * 0.97, day_high=price * 1.01,
                atr=price * 0.02, symbol="TESTCO", margin_pct=MARGIN_PCT)
    assert card["ok"], card

    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, price)
    assert stop is not None, "the engine refused a trade the card offered"

    assert qty == card["qty"], (
        f"card says {card['qty']} shares, the trade takes {qty}")
    assert stop == pytest.approx(card["stop"], abs=0.02), (
        f"card stops at {card['stop']}, the trade stops at {stop}")
    assert (price - stop) * qty == pytest.approx(card["risk_rs"], abs=1.0)


def test_the_rupees_at_risk_are_the_number_he_set(engine):
    """Not a percentage that happens to fall out of the chart."""
    from core.rules import RISK_PER_TRADE_RS

    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 3000.0)
    assert (3000.0 - stop) * qty == pytest.approx(RISK_PER_TRADE_RS, abs=1.0)


def test_neither_side_promises_a_target_the_other_will_not_take(engine):
    """One dial feeds both. Empty means the trail is the exit."""
    card = plan(3000.0, "BUY", day_low=2900.0, day_high=3010.0, atr=70.0,
                symbol="TESTCO", margin_pct=MARGIN_PCT)
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 3000.0)
    if config.TARGET_REWARD_BY_REGIME:
        assert card["target"] is not None and target is not None
    else:
        assert card["target"] is None, "the card printed a phantom target"
        assert target is None, "the trade took a target the card never showed"


def test_a_stock_too_expensive_for_the_budget_is_refused_by_both(engine):
    """Disagreement includes one path taking a trade the other refuses."""
    card = plan(90000.0, "BUY", day_low=88000.0, day_high=90500.0,
                atr=1800.0, symbol="TESTCO", margin_pct=1.0,
                budget_rs=10000.0)
    assert card["ok"] is False


def test_the_engine_refuses_rather_than_moving_the_stop_out_of_bounds(
        engine, monkeypatch):
    """A size that would put the stop inside the noise is not taken.

    The width follows the share count now, so an unusually large
    position would drive the stop toward zero. Both paths refuse at
    the same bound instead of quietly trading a hair-thin stop -- the
    SWIGGY fault of 24 July, arriving from the other direction.
    """
    # Rs 10 of risk spread over 40 shares is a 25-paise stop on a
    # Rs 3,000 share -- 0.008%, far under the floor.
    monkeypatch.setattr(engine_module, "RISK_PER_TRADE_RS", 10.0)
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 3000.0)
    assert stop is None and qty is None
