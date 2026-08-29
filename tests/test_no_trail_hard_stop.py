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


# ---- THIS FILE TESTS THE FLAT 2.5%. 29 August 2026. ----
#
# config.FIXED_STOP_PCT was set to 2.0 on 29 August and REVERTED the
# same day: it had been chosen and measured on the same eight
# sessions, and on eleven it had never seen it was worse than the ATR
# rule it replaced. The dial is None again and VOLATILITY_SCALED_STOP
# is live.
#
# It is still pinned off here, because the flat rule below is one
# line from being reachable again and must keep being proved. The
# mechanism -- that a fixed width, if ever set, reaches BOTH the
# alert and the position -- lives in
# tests/test_one_width_and_he_picked_it.py.
@pytest.fixture(autouse=True)
def _flat_stop(monkeypatch):
    monkeypatch.setattr(engine_module, "FIXED_STOP_PCT", None)
    # ---- AND THE TRAIL WENT BACK ON. 29 August 2026. ----
    # ENABLE_BOT_TRAILING_STOP is True again, to be measured forward
    # in paper against his fading-into-the-close problem. This file
    # documents the no-trail design and the July table behind it, so
    # it keeps testing that -- one flag away, exactly as before.
    monkeypatch.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", False)
    # This file pins exact stop LEVELS from the flat-2.5% rule.
    # config.STOP_FROM_RISK_AND_SIZE moves the width to fit the share
    # count instead; pinned off so the rule below keeps being proved.
    monkeypatch.setattr(engine_module, "STOP_FROM_RISK_AND_SIZE", False)


def test_the_entry_width_does_not_change_when_the_trail_is_switched_on():
    """Two questions, one flag, until 29 August 2026.

    _atr_entry_sizing() used to branch on ENABLE_BOT_TRAILING_STOP for
    the WIDTH as well as the ratchet, and that branch sized from a
    ONE-MINUTE ATR against a 1% floor. Turning the trail on therefore
    collapsed the entry stop to 1.00% for every stock at every ATR --
    on names whose DAILY range is around 3.9% -- and tripled every
    position, because qty is risk divided by that distance.

    VOLATILITY_SCALED_STOP now decides the width on its own terms.
    This asserts the two are independent, which is the only thing
    stopping that from happening again.
    """
    import config

    widths = {}
    for trail in (False, True):
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(engine_module, "ENABLE_BOT_TRAILING_STOP", trail)
            mp.setattr(engine_module, "compute_atr",
                       lambda candles, period: 0.5)
            engine = Engine()
            engine.candle_engine.last_n_closed = lambda symbol, n: [
                {"high": 661.0, "low": 659.0, "close": 660.0}] * n
            mp.setattr(Engine, "_risk_sized_qty", lambda self, *a, **k: 75)
            stop, _target, _qty = engine._atr_entry_sizing(
                "RELIANCE", LONG, 660.0)
            widths[trail] = round(660.0 - stop, 4)
    assert widths[True] == widths[False], (
        f"the trail flag moved the entry width: {widths}")
    assert config.VOLATILITY_SCALED_STOP, (
        "this test assumes the volatility-scaled width is the live one")


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
    # The target was None on this path until 29 August 2026. The
    # alert card had always printed one and the trade ignored it;
    # see config.TARGET_REWARD_BY_REGIME. The STOP is what this
    # test is about and it is unchanged.
    import config
    if config.TARGET_REWARD_BY_REGIME:
        from core.rules import MIN_REWARD_MULTIPLE
        assert target == pytest.approx(1000.0 + MIN_REWARD_MULTIPLE * 25.0)
    else:
        assert target is None, "the exit is the trail, not a target"


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
