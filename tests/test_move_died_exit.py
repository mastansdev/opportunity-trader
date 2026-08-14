"""
==========================================================
Exit once the move is gone -- the other half of the sentence
==========================================================

    "ride untill the momentum stays - exit once it gone ruthlessly +
     repeat the process on only high setups"
                                -- operator, core ideology

WHAT WAS MISSING
----------------
The bot had five exits -- stop, trailing stop, ATR trail, fixed
target, circuit proximity, dead money -- and not one of them answers
"the move is finished".

core/ranker.py's liveness() has known since 4 August. It is what
demoted RBA, +18.2% on the day, which made its high at 09:16 and did
nothing for five hours. It was used to RANK and never to EXIT.

The cost, measured on 5 August: of nineteen reconstructed trades,
SEVENTEEN reached neither their stop nor their target. Every one was
held to the bell by default, not by decision.

THE THREE CONDITIONS, ALL REQUIRED
----------------------------------
    1. IN PROFIT by at least 0.5R. Below that it is the stop's
       business, and two exits competing over one trade is how a
       declared stop gets quietly replaced by a tighter undeclared one.
    2. liveness() says "fading".
    3. more than 4.5% off the day's extreme.

4.5% is deliberately WIDER than the ranker's 3.0% entry threshold.
Refusing to open a position costs nothing; closing one he is in costs
brokerage and a slot. A position gets more rope than a candidate.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import datetime

import pytest

from core.engine import (EXIT_REASON_MOVE_DIED, MOVE_DIED_MIN_GAIN_R,
                         MOVE_DIED_OFF_EXTREME_PCT)


class FakeMarketData:
    def __init__(self, high, low):
        self._e = {"high": high, "low": low}

    def day_extremes(self, _symbol=None):
        return dict(self._e)


class Spy:
    """The Engine's _check_move_died, run against a stub engine.

    Bound off the REAL class -- not reimplemented here. A copy of the
    logic would pass while the shipped method was broken.
    """

    def __init__(self, high, low, entry=100.0, stop=96.0, direction="LONG",
                 qty=10):
        from core.engine import Engine
        self.open_positions = {"X": {"entry_price": entry,
                                     "initial_stop": stop,
                                     "direction": direction, "qty": qty}}
        self.market_data = FakeMarketData(high, low)
        self.exited = []
        self._check_move_died = Engine._check_move_died.__get__(self)

    def _bot_may_close(self, _symbol, _what):
        return True

    def _exit(self, symbol, price, reason, _at):
        self.exited.append((symbol, price, reason))


def run(price, high=110.0, low=99.0, **kw):
    spy = Spy(high, low, **kw)
    fired = spy._check_move_died("X", price, datetime(2026, 8, 5, 14, 0))
    return fired, spy


# ---------------------------------------------------------------
# 1. THE CASE IT EXISTS FOR
# ---------------------------------------------------------------
def test_a_winner_whose_move_has_finished_is_closed():
    """Ran 100 -> 110, gave back to 104. Up 1R, 5.5% off the high and
    no longer moving. Bank it."""
    fired, spy = run(104.0)
    assert fired is True
    assert spy.exited[0][2] == EXIT_REASON_MOVE_DIED


def test_it_is_still_riding_while_the_move_is_on():
    """At 109.5, half a percent off the high. This is the FIRST half of
    his sentence and must not be broken by the second."""
    fired, spy = run(109.5)
    assert fired is False
    assert spy.exited == []


# ---------------------------------------------------------------
# 2. IT NEVER COMPETES WITH THE STOP
# ---------------------------------------------------------------
def test_a_losing_position_is_left_to_the_stop():
    """Entry 100, stop 96, now 97. Deeply off the high and fading --
    but this is the stop's trade. Firing here would be a second,
    tighter, undeclared stop."""
    fired, spy = run(97.0)
    assert fired is False


def test_a_position_barely_in_profit_is_left_alone():
    """Needs 0.5R = +2.00 on a 4.00 risk. At +1.50 it has not earned
    an exit of its own yet."""
    fired, _ = run(101.5)
    assert fired is False


def test_exactly_at_the_gain_threshold_qualifies():
    entry, stop = 100.0, 96.0
    price = entry + MOVE_DIED_MIN_GAIN_R * (entry - stop)     # 102.00
    fired, _ = run(price, high=110.0, entry=entry, stop=stop)
    assert fired is True


# ---------------------------------------------------------------
# 3. THE GIVEBACK HAS TO BE REAL
# ---------------------------------------------------------------
def test_just_inside_the_threshold_keeps_riding():
    high = 110.0
    price = high * (1 - (MOVE_DIED_OFF_EXTREME_PCT - 0.6) / 100.0)
    fired, _ = run(price, high=high)
    assert fired is False


def test_a_position_gets_more_rope_than_a_candidate():
    """The ranker refuses a NEW name at 3.0% off its high. An open
    position must not be closed at the same number, or every entry
    would be stopped out by its own entry rule."""
    from core.ranker import MAX_OFF_EXTREME_PCT
    assert MOVE_DIED_OFF_EXTREME_PCT > MAX_OFF_EXTREME_PCT


# ---------------------------------------------------------------
# 4. A SHORT MEASURES AGAINST THE LOW
# ---------------------------------------------------------------
def test_a_short_is_measured_against_the_days_low():
    """Sold 100, fell to 90, bounced to 95. Up 1.25R, 5.6% off the low.
    Same logic, other extreme -- using the HIGH here would never fire
    for a short at all."""
    fired, spy = run(95.0, high=101.0, low=90.0,
                     entry=100.0, stop=104.0, direction="SHORT")
    assert fired is True
    assert spy.exited[0][2] == EXIT_REASON_MOVE_DIED


# ---------------------------------------------------------------
# 5. IT CANNOT BREAK A TICK
# ---------------------------------------------------------------
def test_no_extremes_recorded_means_no_opinion():
    spy = Spy(None, None)
    assert spy._check_move_died("X", 104.0, datetime.now()) is False


def test_a_broken_market_data_does_not_raise():
    class Boom:
        def day_extremes(self, _s=None):
            raise RuntimeError("feed gone")
    spy = Spy(110.0, 99.0)
    spy.market_data = Boom()
    assert spy._check_move_died("X", 104.0, datetime.now()) is False


def test_an_unknown_symbol_is_not_an_error():
    spy = Spy(110.0, 99.0)
    assert spy._check_move_died("NOTHELD", 104.0, datetime.now()) is False


def test_a_position_with_no_recorded_stop_is_skipped():
    """Without the initial stop there is no risk to measure 0.5R
    against, and guessing one would invent the threshold."""
    spy = Spy(110.0, 99.0)
    spy.open_positions["X"]["initial_stop"] = None
    assert spy._check_move_died("X", 104.0, datetime.now()) is False


def test_the_operators_hold_is_respected():
    """_bot_may_close is his switch. It outranks this."""
    spy = Spy(110.0, 99.0)
    spy._bot_may_close = lambda *a: False
    assert spy._check_move_died("X", 104.0, datetime.now()) is False
    assert spy.exited == []


# ---------------------------------------------------------------
# 6. IT IS ACTUALLY ON THE TICK PATH
# ---------------------------------------------------------------
def test_the_exit_runs_on_every_tick():
    """An exit rule nothing calls is the entire reason this session
    happened."""
    import inspect

    from core.engine import Engine
    src = inspect.getsource(Engine.process_tick)
    assert "_check_move_died(" in src, (
        "liveness() is back to being a ranking input only")


def test_it_runs_after_the_dead_money_check():
    """A position that never worked is dead money, not a finished
    move. Both would otherwise claim the same trade."""
    import inspect

    from core.engine import Engine
    src = inspect.getsource(Engine.process_tick)
    assert src.index("_check_no_progress(") < src.index("_check_move_died(")
