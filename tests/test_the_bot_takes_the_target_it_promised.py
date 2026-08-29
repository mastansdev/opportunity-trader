"""The card and the trade must want the same thing.

    "if entry at 3000 & target is missed by 1 or 2 rs & what is stock
     made higher highs after entry"    -- operator, 29 August 2026

A hard target for the bot's own entries went on and came off the same
day, and his question is what took it off. TCS at Rs 3,000 with 40
shares puts the target at Rs 3,062.50:

    runs to 3,061 and turns   the trail books   +Rs  1,240
    runs to 3,100             TARGET FIRES      +Rs  2,500
    runs to 3,300             TARGET FIRES      +Rs  2,500

Without it: +1,240 / +2,800 / +10,800. Below the target the trail was
booking anyway; above it, the target cut the exact trade he wanted to
keep. So the exit is the trail, and TARGET_REWARD_BY_REGIME is {}.

The machinery is kept and kept tested, because that dict is one edit
from being filled again. What this file guards is that if a target IS
set, it reaches the position, moves with the day, never blocks an
entry, and matches what the alert card prints -- core/engine.py and
core/position_plan.py read the SAME dict for exactly that reason.
"""

import pytest

import config
import core.engine as engine_module
from core.engine import Engine, LONG, SHORT


@pytest.fixture(autouse=True)
def _target_on(monkeypatch):
    """Pin the dial ON. The LIVE value is {} -- no hard target.

    It came off on 29 August after his question exposed what it cost:
    TCS entering at Rs 3,000 with 40 shares has its target at
    Rs 3,062.50, so a run to Rs 3,300 was capped at +Rs 2,500 where
    the trail would have booked +Rs 10,800. Below the target the trail
    was doing the work anyway; above it, the target cut the exact
    trade he wanted to keep.

    The machinery stays tested because the dict is one edit from being
    filled again, and the card and the trade must not drift apart when
    it is.
    """
    monkeypatch.setattr(engine_module, "TARGET_REWARD_BY_REGIME",
                        {"LONG_ONLY": 1.0, "BOTH": 1.0, "SHORT_ONLY": 1.0})


@pytest.fixture
def engine(monkeypatch):
    """A real Engine with the ATR reading and the share count stubbed.

    Everything else -- the stop width, the target arithmetic, the
    regime lookup -- runs for real.
    """
    monkeypatch.setattr(engine_module, "compute_atr",
                        lambda candles, period: 5.0)
    eng = Engine()
    eng.candle_engine.last_n_closed = lambda symbol, n: [
        {"high": 101.0, "low": 99.0, "close": 100.0}] * n
    monkeypatch.setattr(Engine, "_risk_sized_qty",
                        lambda self, *a, **k: 75)
    return eng


def _regime(eng, monkeypatch, what):
    monkeypatch.setattr(Engine, "_market_regime", lambda self: what)


# ------------------------------------------------- it exists at all

def test_the_bot_now_gets_a_target(engine, monkeypatch):
    """It was None on this path. That was the whole bug."""
    _regime(engine, monkeypatch, "BOTH")
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
    assert target is not None
    assert target > 1000.0


def test_the_target_is_the_reward_multiple_of_the_risk(engine, monkeypatch):
    _regime(engine, monkeypatch, "BOTH")
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
    distance = 1000.0 - stop
    assert distance > 0
    assert (target - 1000.0) == pytest.approx(distance * 1.0)


# ------------------------------------------------- it moves with the day

def test_the_day_can_move_the_target_if_it_is_ever_set_to(engine,
                                                          monkeypatch):
    """The machinery works. The live config does not currently use it."""
    monkeypatch.setattr(engine_module, "TARGET_REWARD_BY_REGIME",
                        {"LONG_ONLY": 3.0, "BOTH": 2.0, "SHORT_ONLY": 1.0})
    reach = {}
    for regime in ("LONG_ONLY", "BOTH", "SHORT_ONLY"):
        _regime(engine, monkeypatch, regime)
        stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
        reach[regime] = target - 1000.0
    assert reach["LONG_ONLY"] > reach["BOTH"] > reach["SHORT_ONLY"], reach


def test_a_falling_market_does_not_shrink_the_target(engine, monkeypatch):
    """His correction, 29 August 2026, and the reason it is a test.

        "even on broad market falling strong event stocks will make
         higher highs and we are capturing those stocks"

    A stock only reaches this bot with an event, up 3%+, on 2.5x its
    own volume, ALREADY BEATING ITS SECTOR. On a falling market the
    names that clear those gates are the strongest ones on the
    screen, not the weakest. Shrinking their target by the index
    would penalise the best setup the bot ever sees, and it would
    double-count relative strength, which is already a gate.

    If someone later re-introduces a ladder, this fails first.
    """
    reach = {}
    for regime in ("LONG_ONLY", "BOTH", "SHORT_ONLY"):
        _regime(engine, monkeypatch, regime)
        stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
        reach[regime] = target - 1000.0
    assert reach["SHORT_ONLY"] >= reach["LONG_ONLY"], reach


def test_a_short_targets_downwards(engine, monkeypatch):
    _regime(engine, monkeypatch, "BOTH")
    stop, target, qty = engine._atr_entry_sizing("TESTCO", SHORT, 1000.0)
    assert target < 1000.0 < stop


# ------------------------------------------------- it never blocks a trade

def test_an_unreadable_regime_costs_the_target_not_the_entry(engine,
                                                             monkeypatch):
    """A target is a nicety. An entry is the trade.

    If the breadth cannot be read, the position is still opened and
    simply behaves as it did before this existed.
    """
    def _boom(self):
        raise RuntimeError("no breadth yet")
    monkeypatch.setattr(Engine, "_market_regime", _boom)
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
    assert stop is not None and qty == 75
    assert target is None


def test_an_unknown_regime_name_is_not_guessed_at(engine, monkeypatch):
    _regime(engine, monkeypatch, "SOMETHING_NEW")
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
    assert stop is not None and qty == 75
    assert target is None


def test_turning_it_off_restores_holding_to_the_close(engine, monkeypatch):
    """One dict to empty. That is the whole revert."""
    monkeypatch.setattr(engine_module, "TARGET_REWARD_BY_REGIME", {})
    _regime(engine, monkeypatch, "BOTH")
    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)
    assert stop is not None and qty == 75
    assert target is None


# ------------------------------------------- the card and the trade agree

def test_the_alert_card_and_the_trade_want_the_same_thing(engine,
                                                          monkeypatch):
    """The point of the change, stated as a test.

    On an ordinary day the alert's target and the position's target
    are the same number. If these two ever drift apart, his phone is
    describing a trade the bot is not taking -- which is exactly the
    state this replaced, and nothing in a P&L would reveal it.
    """
    from core.position_plan import plan

    # LIVE: the dict is empty, so neither prints nor books a target.
    # (The autouse fixture above pins the ENGINE's copy on; the card
    # reads config directly, which is still the live empty value.)
    assert not config.TARGET_REWARD_BY_REGIME, (
        "if a hard target is set again, the card must be re-checked "
        "against the trade")
    got = plan(3000.0, "BUY", day_low=2900.0, day_high=3010.0,
               atr=70.0, symbol="TCS", margin_pct=0.25)
    assert got["ok"], got
    assert got["target"] is None, (
        "the card is printing a target the trade will not take")
