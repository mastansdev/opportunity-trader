"""
The trailing stop must never ratchet up to touching distance.

Operator-found live, 2026-07-27. Every position that day -- more than
twenty, manual and structural -- exited by TRAILING_STOP within two to
fifteen minutes at a price within 0.2% of entry:

    LAURUSLABS  in 1681.60  out 1681.60   9 min    0.00%
    CARTRADE    in 2893.40  out 2892.90  15 min   -0.02%
    ETERNAL     in  295.20  out  295.40   8 min   +0.07%
    LAURUSLABS  in 1717.50  out 1718.30   8 min   +0.05%

LAURUSLABS sold for exactly its purchase price and then ran to 1730.50.

Cause: the ratchet set the stop to min(recent candle lows) with no
minimum distance. MIN_STOP_DISTANCE_PCT was applied ONCE at entry and
never again, so within two or three quiet candles the stop had climbed
to within paise of the market.

Note this is the SECOND layer of the same bug. Earlier the same day the
seed floor was widened from 0.4% to 1.0% -- which changed nothing,
because the ratchet immediately walked the stop back up regardless.
Fixing a seed cannot fix a ratchet.
"""

import config
from core.trailing_stop import TrailingStopEngine


def test_stop_never_ratchets_closer_than_the_floor():
    """The LAURUSLABS case, with its real numbers."""
    e = TrailingStopEngine(window=3)
    entry = 1681.60
    e.start("LAURUSLABS", entry * (1 - config.MIN_STOP_DISTANCE_PCT))

    # three quiet candles whose lows sit just under the price -- exactly
    # what happened between 10:51 and 11:00
    for low, close in ((1679.0, 1682.0), (1680.5, 1682.5), (1681.0, 1682.0)):
        e.update_on_candle_close("LAURUSLABS", low, close + 1,
                                 reference_price=close)

    stop = e.get_stop("LAURUSLABS")
    assert stop <= 1682.0 * (1 - config.MIN_STOP_DISTANCE_PCT) + 1e-9, (
        f"stop ratcheted to {stop:.2f} against a price of 1682.00 -- "
        f"that is {100*(1682.0-stop)/1682.0:.2f}% away, floor is "
        f"{100*config.MIN_STOP_DISTANCE_PCT:.2f}%"
    )
    assert not e.is_hit("LAURUSLABS", entry), \
        "a tick back to the entry price must NOT be a stop-out"


def test_the_stop_still_follows_a_real_move_up():
    """The floor must not freeze the stop -- it still has to trail."""
    e = TrailingStopEngine(window=3)
    e.start("X", 99.0)
    start = e.get_stop("X")
    for low, close in ((101.0, 103.0), (104.0, 106.0), (107.0, 110.0)):
        e.update_on_candle_close("X", low, close + 1, reference_price=close)
    assert e.get_stop("X") > start, "stop failed to trail a genuine rally"
    assert e.get_stop("X") <= 110.0 * (1 - config.MIN_STOP_DISTANCE_PCT) + 1e-9


def test_the_stop_is_never_lowered():
    e = TrailingStopEngine(window=3)
    e.start("X", 99.0)
    e.update_on_candle_close("X", 108.0, 111.0, reference_price=110.0)
    high = e.get_stop("X")
    e.update_on_candle_close("X", 100.0, 102.0, reference_price=101.0)
    assert e.get_stop("X") == high, "stop was loosened on a pullback"


def test_short_side_is_mirrored():
    e = TrailingStopEngine(window=3)
    e.start("X", 101.0, direction="SHORT")
    for high, close in ((99.5, 98.0), (98.5, 97.5), (98.0, 97.0)):
        e.update_on_candle_close("X", high - 1, high, reference_price=close)
    stop = e.get_stop("X")
    assert stop >= 97.0 * (1 + config.MIN_STOP_DISTANCE_PCT) - 1e-9, (
        f"short stop ratcheted to {stop:.2f} against a price of 97.00"
    )
    assert not e.is_hit("X", 97.5)


def test_callers_that_pass_no_reference_keep_the_old_behaviour():
    """Deliberate: the replay bench and older tests call this without a
    reference price. They must not silently change meaning."""
    e = TrailingStopEngine(window=3)
    e.start("X", 90.0)
    e.update_on_candle_close("X", 95.0, 99.0)
    assert e.get_stop("X") is not None
