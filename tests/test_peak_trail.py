"""
How a winning position is protected, 2026-07-28 and 2026-08-08.

TWO RULES LIVE IN THIS FILE, and both are tested, because the first one
solved a real problem before the second one replaced it.

RULE 1 -- the 2.5% peak trail (2026-07-28)
------------------------------------------
Replaced a 5-candle rolling-low ratchet that crept the stop up during
flat stretches, so an ordinary pause ended the trade:

    AFFLE       peaked +Rs 3,087, exited +Rs 590. Gave back Rs 2,497 in
                eight minutes. Simply holding beat it by Rs 886.
    NILKAMAL    entered 09:36, out 09:53 for +0.51%. Went on to +7.63%.
    KALYANKJIL  stopped at 597.50. Closed at 608.85.

2.5% was measured: of 51 stocks that finished up 2%+ that session, the
worst pullback along the way had a median of 1.84% and a 75th
percentile of 2.50%. A 1% trail was hit in 45 of the 51 winners.

RULE 2 -- book 1:1 on a retrace from near the target (2026-08-08)
-----------------------------------------------------------------
    "in 2:1 ration if the stock is falling after reaching nearby rs &
     started retrace back book at 1:1 profit (something is better than
     nothing)"

Rule 1 was measured against a flat 2.5%, before there was a measured
target. Once core/exit_plan.py set the target at 2R -- 3.6% at the
standard 1.8% stop -- the 2.5% trail sat BELOW the halfway mark of the
target it was supposed to protect. Any ordinary pullback ended the
trade for almost nothing:

    DEEPAKNTR  7 Aug   entry 1774.90  peak 1832.70 (+3.26%, 1.81R)
                       2.5% trail     1786.88 (+0.68%)  <- booked
                       1:1 lock       1806.85 (+1.80%)  <- books now

Measured on the recorded tape, 12 trades, 09:30 entries:

    2.5% peak trail    +0.42%
    1:1 lock rule      +4.33%

The lock is BOUNDED, which the trail never was. A trade can only end at
the target (+2R), the stop (-1R), the lock (+1R), or the close. At most
one times the risk is ever handed back from the peak.

WHY RULE 1 IS STILL HERE
------------------------
ENABLE_ONE_TO_ONE_LOCK = False restores it exactly, and its own tests
still run under that flag. A rule that solved a real problem is not
deleted because a better one arrived; it is kept proven and reachable.
"""

import pytest

from core.trailing_stop import TrailingStopEngine, LONG, SHORT
from config import PEAK_TRAIL_PCT


# The standard planned stop -- core/exit_plan.STOP_PCT, the 75th
# percentile dip across 7,709 stock-days. Positions are SIZED on this
# number, so it has to be the number they are stopped on too.
STOP_PCT = 0.018


def _long(entry=1000.0, stop_pct=STOP_PCT):
    """A long position opened with its PLANNED stop, as the live path
    passes it: core/exit_plan.py measures it, core/auto_entry.py buys
    quantity to match."""
    ts = TrailingStopEngine()
    ts.start("TEST", round(entry * (1 - stop_pct), 2),
             direction=LONG, entry_price=entry)
    return ts


def _old_rule(monkeypatch):
    import core.trailing_stop as ts_mod
    monkeypatch.setattr(ts_mod, "ENABLE_ONE_TO_ONE_LOCK", False)


# ---------------------------------------------------------------
# RULE 2: the stop the position was sized on is the stop it gets
# ---------------------------------------------------------------

def test_the_planned_stop_is_the_stop_the_trade_actually_gets():
    """The old code overwrote the caller's seed with a flat 2.5%, so a
    position sized on 1.8% of risk was stopped on 2.5% of it. "One
    times the risk" meant two different numbers in the same trade."""
    ts = _long(1000.0)
    assert ts.get_stop("TEST") == pytest.approx(982.0)


def test_nothing_moves_until_the_stock_has_run_one_and_a_half_times_its_risk():
    """A stop that creeps from the first tick is the 2.5% trail under a
    new name, and it is what turned DEEPAKNTR's +3.26% into +0.68%."""
    ts = _long(1000.0)
    for price in (1005.0, 1010.0, 1020.0, 1026.0):     # up to +1.44R
        ts.update_on_price("TEST", price)
        assert ts.get_stop("TEST") == pytest.approx(982.0)


def test_at_one_and_a_half_times_the_risk_the_stop_locks_one_to_one():
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1027.0)                 # +1.5R exactly
    assert ts.get_stop("TEST") == pytest.approx(1018.0)


def test_a_retrace_after_the_lock_books_a_profit_not_a_scratch():
    """His rule, in one test. Something is better than nothing."""
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1033.0)                 # ran 1.83R
    assert not ts.is_hit("TEST", 1025.0)               # still breathing
    assert ts.is_hit("TEST", 1017.0)                   # books +1.7%
    assert ts.get_stop("TEST") > 1000.0                # ABOVE the entry


def test_the_lock_holds_until_the_old_target_then_starts_trailing():
    """The lock is a FLOOR, not a ceiling. 8 August 2026.

        "we want money in either money thats it"

    Between 1.5R and 2R nothing moves -- the trade is protected at 1:1
    and left alone. Past 2R the stop follows 1.5R behind the high, with
    no cap, because a hard exit at 2R made the best trade of the month
    pay the same as an ordinary one. Measured: -0.095R per trade with
    the cap, +0.006R with the trail, across 8,230 setups.
    """
    ts = _long(1000.0)
    risk = 18.0
    ts.update_on_price("TEST", 1000.0 + risk * 1.6)      # 1.6R
    locked = ts.get_stop("TEST")
    assert locked == pytest.approx(1018.0)               # +1R

    ts.update_on_price("TEST", 1000.0 + risk * 1.9)      # still under 2R
    assert ts.get_stop("TEST") == locked

    ts.update_on_price("TEST", 1000.0 + risk * 4.0)      # 4R -- trailing
    assert ts.get_stop("TEST") == pytest.approx(1045.0)  # +2.5R

    ts.update_on_price("TEST", 1000.0 + risk * 8.0)      # 8R
    assert ts.get_stop("TEST") == pytest.approx(1117.0)  # +6.5R


def test_the_trail_never_steps_back_below_the_lock():
    """At exactly 2R a 1.5R trail computes to +0.5R -- below the 1:1 the
    trade already earned. A stop that moves backwards is not a trail."""
    ts = _long(1000.0)
    risk = 18.0
    ts.update_on_price("TEST", 1000.0 + risk * 1.7)
    ts.update_on_price("TEST", 1000.0 + risk * 2.0)
    assert ts.get_stop("TEST") >= 1018.0


def test_the_stop_never_moves_down():
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1030.0)
    high_water = ts.get_stop("TEST")
    ts.update_on_price("TEST", 1005.0)
    ts.update_on_price("TEST", 1000.0)
    assert ts.get_stop("TEST") == high_water


def test_a_flat_stretch_does_not_move_the_stop():
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1030.0)
    before = ts.get_stop("TEST")
    for _ in range(200):
        ts.update_on_price("TEST", 1029.0)
    assert ts.get_stop("TEST") == before


def test_a_wider_planned_stop_moves_the_lock_with_it():
    """R is the stock's own risk, not a fixed percentage. A name given a
    3% stop must run further before anything locks."""
    ts = _long(1000.0, stop_pct=0.03)
    ts.update_on_price("TEST", 1030.0)                 # only +1.0R
    assert ts.get_stop("TEST") == pytest.approx(970.0)
    ts.update_on_price("TEST", 1045.0)                 # +1.5R
    assert ts.get_stop("TEST") == pytest.approx(1030.0)


# ---------------------------------------------------------------
# The real trades that produced rule 1 -- still protected by rule 2
# ---------------------------------------------------------------

def test_AFFLE_would_not_have_been_stopped_at_1627():
    """Real trade, 2026-07-28: entry 1,622.90, peak 1,648, exited
    1,627.70 for Rs 590 of a Rs 3,087 profit.

    The peak is +1.55%, only 0.86R, so nothing locks and the planned
    stop at 1,593.68 stands. The exit that cost Rs 2,497 never fires --
    the same answer rule 1 gave, from a different direction."""
    ts = _long(1622.90)
    ts.update_on_price("TEST", 1648.00)
    assert ts.get_stop("TEST") == pytest.approx(1593.68, abs=0.5)
    assert not ts.is_hit("TEST", 1627.70)


def test_NILKAMAL_survives_the_dip_that_ended_the_real_trade():
    """Entry 1,839, stopped at 1,835.50 after 8 minutes. It closed at
    1,968. The planned stop sits at 1,805.90 -- nowhere near 1,835."""
    ts = _long(1839.00)
    assert not ts.is_hit("TEST", 1835.50)
    assert ts.get_stop("TEST") == pytest.approx(1805.90, abs=0.5)


def test_DEEPAKNTR_books_1_8_pct_instead_of_0_68_pct():
    """7 August, the trade that produced this rule. Entry 1,774.90,
    peak 1,832.70, then back through 1,806."""
    ts = _long(1774.90)
    ts.update_on_price("TEST", 1832.70)                # ran 1.81R
    assert ts.get_stop("TEST") == pytest.approx(1806.85, abs=0.05)
    assert ts.is_hit("TEST", 1806.00)
    booked = (1806.85 - 1774.90) / 1774.90 * 100
    assert booked == pytest.approx(1.80, abs=0.05)


def test_a_genuine_reversal_still_exits():
    """Wider must not mean absent. A stock that runs and rolls over hard
    still ends the trade -- at the lock if it got there, at the planned
    stop if it did not."""
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1010.0)                 # never reached 1.5R
    assert ts.is_hit("TEST", 981.0)


# ---------------------------------------------------------------
# Safety
# ---------------------------------------------------------------

def test_an_unknown_symbol_returns_None_not_a_crash():
    assert TrailingStopEngine().update_on_price("NOPE", 100.0) is None


def test_a_zero_price_does_not_move_the_stop():
    ts = _long(1000.0)
    before = ts.get_stop("TEST")
    ts.update_on_price("TEST", 0)
    ts.update_on_price("TEST", None)
    assert ts.get_stop("TEST") == before


def test_a_missing_entry_price_leaves_the_seeded_stop_alone():
    """No entry means R cannot be computed. That must never widen a
    stop -- it leaves it exactly where the caller put it."""
    ts = TrailingStopEngine()
    ts.start("TEST", 900.0, direction=LONG, entry_price=None)
    ts.update_on_price("TEST", 2000.0)
    assert ts.get_stop("TEST") == 900.0


def test_shorts_are_untouched_by_the_lock():
    """He does not short, and the measurement was long-only. SHORT keeps
    the 2.5% peak trail exactly as it was."""
    ts = TrailingStopEngine()
    ts.start("TEST", 1100.0, direction=SHORT, entry_price=1000.0)
    assert ts.get_stop("TEST") == pytest.approx(1000.0 * (1 + PEAK_TRAIL_PCT))
    ts.update_on_price("TEST", 900.0)
    assert ts.get_stop("TEST") == pytest.approx(900.0 * (1 + PEAK_TRAIL_PCT))


def test_a_short_stop_never_moves_up():
    ts = TrailingStopEngine()
    ts.start("TEST", 1100.0, direction=SHORT, entry_price=1000.0)
    ts.update_on_price("TEST", 900.0)
    low_water = ts.get_stop("TEST")
    ts.update_on_price("TEST", 980.0)
    assert ts.get_stop("TEST") == low_water


# ---------------------------------------------------------------
# RULE 1 stays reachable, and stays proven
# ---------------------------------------------------------------

def test_the_old_trail_still_starts_exactly_the_trail_below_entry(monkeypatch):
    _old_rule(monkeypatch)
    ts = _long(1000.0)
    assert ts.get_stop("TEST") == pytest.approx(1000.0 * (1 - PEAK_TRAIL_PCT))


def test_the_old_trail_still_lifts_the_stop_on_a_new_high(monkeypatch):
    _old_rule(monkeypatch)
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1100.0)
    assert ts.get_stop("TEST") == pytest.approx(1100.0 * (1 - PEAK_TRAIL_PCT))


def test_the_old_trail_still_reaches_breakeven_by_itself(monkeypatch):
    """Operator's own question, 28 July: should the stop jump to the buy
    price at +2.5%? Under rule 1 it already did, with no special case."""
    _old_rule(monkeypatch)
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1025.0)
    assert ts.get_stop("TEST") < 1000.0
    ts.update_on_price("TEST", 1027.0)
    assert ts.get_stop("TEST") > 1000.0


def test_the_old_trail_still_gives_up_a_2_5_pct_reversal(monkeypatch):
    """CUB dipped 4.4% before delivering 8.9%. Rule 1 gave that one up."""
    _old_rule(monkeypatch)
    ts = _long(1000.0)
    ts.update_on_price("TEST", 1100.0)
    assert ts.is_hit("TEST", 1070.0)


def test_turning_the_peak_trail_off_restores_the_old_seeded_stop(monkeypatch):
    """The pre-July-28 rule stays intact and reachable too."""
    import core.trailing_stop as ts_mod
    monkeypatch.setattr(ts_mod, "ENABLE_PEAK_TRAIL", False)
    ts = TrailingStopEngine()
    ts.start("TEST", 900.0, direction=LONG, entry_price=1000.0)
    assert ts.get_stop("TEST") == 900.0
