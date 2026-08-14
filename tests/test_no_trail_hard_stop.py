"""
The exit rule after 29 July 2026: a hard stop, and nothing else.

MEASURED, not argued. 80 real trades from 27, 28 and 29 July replayed
against their own minute candles -- same entries every time, only the
exit rule changing. On the bot's own 35 structural entries:

    exit rule                  n    win     total   per trade
    what actually happened    35    43%    -1,252         -36
    1.5% trail                35    43%     8,856         253
    2.5% trail                35    46%    15,496         443
    3.5% trail                35    51%    21,374         611
    5.0% trail                35    51%    21,374         611
    7.5% trail                35    51%    21,374         611

The last three are identical because above 3.5% the trail never fires
at all. The finding is not "use a wider trail" -- it is "the trail
should not be there".

And the bot was never running the 2.5% the operator approved. Its 16
ATR-trail stop-outs fired at a median of 1.06% from the peak, maximum
1.93%, every single one under 2%.

The partial exit went the same way: 51% win / Rs 21,374 without it,
66% win / Rs 9,761 with it. Higher win rate, half the money.
"""

from datetime import datetime

import pytest

import core.engine as engine_module
from core.engine import Engine, LONG


def _t(hour, minute, second=0):
    return datetime(2026, 7, 29, hour, minute, second)


def _engine_with_position(entry=1000.0, qty=100):
    engine = Engine()
    engine.open_positions["TESTCO"] = {
        "symbol": "TESTCO", "security_id": "1", "direction": LONG,
        "entry_price": entry, "qty": qty,
        "entry_reason": engine_module.ENTRY_REASON_STRUCTURAL_LONG,
        "initial_stop": entry * 0.975,
        "atr_stop": entry * 0.975,
        "atr_extreme": entry,
        "fixed_target": None, "entry_time": _t(9, 31),
        "stop_mode": "ATR_TRAILING",
    }
    return engine


# ---------------------------------------------------------------
# The stop does not move
# ---------------------------------------------------------------

def test_the_stop_does_not_ratchet_up_on_a_winning_candle():
    """This is the change. The stop stays at 975 while the stock runs
    to 1,080 -- the trade is allowed to work."""
    engine = _engine_with_position()
    position = engine.open_positions["TESTCO"]

    engine._update_atr_trailing_on_candle_close("TESTCO", position, {
        "open": 1050.0, "high": 1080.0, "low": 1045.0,
        "close": 1075.0, "time": _t(10, 0),
    })

    assert position["atr_stop"] == 975.0


def test_the_stop_still_closes_a_losing_trade():
    """The protection is not removed, only the ratchet."""
    engine = _engine_with_position()
    engine._check_atr_trailing(
        "TESTCO", engine.open_positions["TESTCO"], 970.0, _t(10, 0))
    assert "TESTCO" not in engine.open_positions


def test_a_trade_that_runs_then_dips_is_no_longer_sold():
    """KAYNES, 29 July: in profit, dipped off its high, sold by the
    trail, then ran to 3,685. Under the new rule the dip does nothing
    because the stop never followed the price up."""
    engine = _engine_with_position()
    position = engine.open_positions["TESTCO"]

    engine._update_atr_trailing_on_candle_close("TESTCO", position, {
        "open": 1040.0, "high": 1060.0, "low": 1035.0,
        "close": 1055.0, "time": _t(10, 0),
    })
    engine._check_atr_trailing("TESTCO", position, 1030.0, _t(10, 5))

    assert "TESTCO" in engine.open_positions
    assert position["atr_stop"] == 975.0


# ---------------------------------------------------------------
# The stop is the operator's own number, not an ATR reading
# ---------------------------------------------------------------

def test_the_entry_stop_sits_2_and_a_half_percent_below_entry(monkeypatch):
    """Not an ATR reading. The bot's ATR trail measured 1.06% from the
    peak in practice, which is less than half what was agreed. With
    the trail gone this stop is the only protection, so it is the
    number the operator actually chose."""
    monkeypatch.setattr(engine_module, "compute_atr",
                        lambda candles, period: 0.1)
    engine = Engine()
    engine.candle_engine.last_n_closed = lambda symbol, n: [
        {"high": 100.0, "low": 99.0, "close": 100.0}] * (n)

    stop, target, qty = engine._atr_entry_sizing("TESTCO", LONG, 1000.0)

    assert stop == pytest.approx(975.0)
    assert target is None


def test_a_tiny_atr_can_no_longer_produce_a_hair_thin_stop(monkeypatch):
    """ACUTAAS and IGIL were stopped out on moves of 0.08% and 0.02%.
    Under a fixed 2.5% that cannot happen regardless of how quiet the
    candles are."""
    monkeypatch.setattr(engine_module, "compute_atr",
                        lambda candles, period: 0.0001)
    engine = Engine()
    engine.candle_engine.last_n_closed = lambda symbol, n: [
        {"high": 100.0, "low": 99.99, "close": 100.0}] * n

    stop, _target, _qty = engine._atr_entry_sizing("TESTCO", LONG, 500.0)
    assert stop == pytest.approx(487.5)


# ---------------------------------------------------------------
# Nothing was deleted -- both old paths are one flag away
# ---------------------------------------------------------------

def test_the_trail_comes_back_when_the_flag_is_set(monkeypatch):
    """Three sessions in one market mood is a measurement, not a
    proof. The old behaviour must remain reachable."""
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", True)
    monkeypatch.setattr(engine_module, "compute_atr",
                        lambda candles, period: 5.0)
    engine = _engine_with_position()
    position = engine.open_positions["TESTCO"]
    engine.candle_engine.last_n_closed = lambda symbol, n: [
        {"high": 100.0, "low": 99.0, "close": 100.0}] * n

    engine._update_atr_trailing_on_candle_close("TESTCO", position, {
        "open": 1050.0, "high": 1080.0, "low": 1045.0,
        "close": 1075.0, "time": _t(10, 0),
    })

    assert position["atr_stop"] > 975.0


def test_the_partial_exit_is_off_by_default():
    """23 of 35 trades reached the 2x ATR level. 16 kept going and the
    partial cost Rs 14,508; 7 reversed and it saved Rs 2,894. Two
    winners run for every one that turns."""
    from config import ENABLE_PARTIAL_EXIT
    assert ENABLE_PARTIAL_EXIT is False


def test_the_hard_stop_percentage_is_the_agreed_one():
    from config import HARD_STOP_FROM_ENTRY_PCT
    assert HARD_STOP_FROM_ENTRY_PCT == 0.025


# ---------------------------------------------------------------
# N6 -- the flag whose name lied, and the 09:30 lock
# ---------------------------------------------------------------

def test_the_honest_name_and_the_old_alias_agree():
    """TOP_N_MOMENTUM_MODE has nothing to do with a momentum list any
    more -- it selects the SIZING AND STOP path. Flipping it to False
    believing otherwise would silently change every entry's share count
    and stop, in 26 places across 7 files. ATR_ENTRY_SIZING is the
    honest name; the old one stays as an alias so nothing breaks and a
    search for it still lands on the explanation."""
    from config import ATR_ENTRY_SIZING, TOP_N_MOMENTUM_MODE
    assert TOP_N_MOMENTUM_MODE is ATR_ENTRY_SIZING


def test_the_0930_momentum_lock_is_off():
    """Measured over three sessions -- how many of the day's CLOSING
    top 20 were already top 20 at each hour:

        date             09:30    10:00    11:00    12:00    13:00    14:00
        2026-07-27        8/20     8/20    10/20    12/20    12/20    13/20
        2026-07-28        9/20    10/20    11/20    14/20    13/20    15/20
        2026-07-29        2/20     7/20     7/20     8/20     8/20     9/20

    At 09:30 about a third of the day's leaders are visible, and on
    29 July two of twenty. There is no good hour to freeze a list."""
    from config import ENABLE_MOMENTUM_LOCK
    assert ENABLE_MOMENTUM_LOCK is False


def test_nothing_reads_the_momentum_universe_for_eligibility():
    """The gate was removed weeks ago. If it ever comes back, it should
    be a decision rather than a reappearance."""
    source = open("core/engine.py", encoding="utf-8").read()
    assert "momentum_universe.is_eligible" not in source
