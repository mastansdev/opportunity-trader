"""
==========================================================
Gained 8k, booked 700
==========================================================

    "some stocks i observed, after gaining around 8k bot booked profit
     of 700 rs change by giving back almost all the mtm profits"
    "if we trade on slab wise like once mtm profit cross 5K then shift
     the Trailing stop loss to 5K price of that stock then increase for
     every 1 k upside movement"
                                    -- the operator, 14 September 2026

A LOCK ALREADY EXISTED AND COULD NOT BE REACHED. exit_plan.live_stop()
moves the stop to 1:1 once the trade runs NEAR_TARGET_R = 1.5R. Over
7-10 September almost nothing got there:

    peak MTM reached Rs 8,000 (about 6%)     1 of 95 trades
    peak MTM reached Rs 5,000 (about 3.7%)   8 of 95 trades

So the lock was real and unreachable, and a position that ran +2% and
came back had nothing holding it. Simulated on that book, the existing
lock changes the result by -211 to +663. It is not broken; the bar is
above where his trades live.

WHAT WAS MEASURED, replaying all 95 trades against the minute candles:

    his slab, arm Rs 3,000 / step Rs 1,000   +9,558
    as a percentage, arm 2.5% / give 0.5%    +8,059
    retuning the existing R parameters       +4,506
    a breakeven ratchet                      +1,476 (a wash)
    a proportional give-back                 -2,213 (all negative)

IT IS A PERCENTAGE, NOT RUPEES, and NOT because paper and live differ
-- they must not, and the slot is Rs 50,000 on both sides. It is
because MTF leverage runs 2x to 4.3x, so one Rs 50,000 slot buys
Rs 1.0-2.15 lakh of stock and Rs 5,000 is 5% of one position and 2.3%
of another. Rs 5,000 on a typical Rs 2 lakh position IS this 2.5%.

IT HANDS OVER AT 1.5R, which is the part that matters most and which
the sample could not have taught: a flat 0.5% give-back is TIGHTER
than the 1.5R trail once a trade runs, so at 4R it would close a
winner on an ordinary 0.5% pullback. Exactly one of 95 trades passed
6%, so the measurement is blind there. Rule 3 covers the gap below
1.5R and then gets out of the way.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

import core.trailing_stop as ts_mod

ENGINE = [v for v in vars(ts_mod).values()
          if isinstance(v, type) and hasattr(v, "_profit_lock")][0]
LOCK = ENGINE._profit_lock


# ---------------------------------------------------------------
# THE LOCK
# ---------------------------------------------------------------

def test_it_arms_once_the_gain_is_real():
    assert LOCK({"entry": 100.0, "peak": 103.0}) == pytest.approx(102.485)


def test_it_stays_out_of_the_way_below_the_arm():
    """Under the arm nothing moves -- the original rule intact. A stop
    that crept from the first tick is what turned DEEPAKNTR's +3.26%
    into +0.68%, and that lesson is not being unlearned."""
    assert LOCK({"entry": 100.0, "peak": 101.5}) is None
    assert LOCK({"entry": 100.0, "peak": 100.0}) is None


def test_the_boundary_arms():
    assert LOCK({"entry": 100.0, "peak": 102.5}) is not None
    assert LOCK({"entry": 100.0, "peak": 102.49}) is None


def test_once_armed_it_is_above_entry():
    """The whole point: a retrace then books a PROFIT. This is what the
    8k -> 700 trade never had."""
    assert LOCK({"entry": 100.0, "peak": 102.5}) > 100.0


def test_it_climbs_with_the_peak():
    """His 'increase for every 1k upside movement', continuously."""
    assert (LOCK({"entry": 100.0, "peak": 106.0})
            > LOCK({"entry": 100.0, "peak": 103.0}))


# ---------------------------------------------------------------
# AND IT GETS OUT OF THE WAY
# ---------------------------------------------------------------

def test_it_hands_over_once_the_one_to_one_lock_engages():
    """THE ONE THE SAMPLE COULD NOT TEACH. Past 1.5R the bounded
    R-relative design governs, or a 10% winner would be closed on a
    0.5% pullback."""
    assert LOCK({"entry": 100.0, "peak": 110.0, "locked": True}) is None


def test_it_still_speaks_before_the_handover():
    assert LOCK({"entry": 100.0, "peak": 103.0, "locked": False}) is not None


def test_the_handover_is_written_where_it_is_decided():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "trailing_stop.py").read_text(encoding="utf-8")
    body = src[src.index("def _profit_lock"):]
    body = body[:body.index("def _lock_at_one_to_one")]
    assert 'state.get("locked")' in body


# ---------------------------------------------------------------
# IT NEVER GUESSES, AND NEVER LOWERS A STOP
# ---------------------------------------------------------------

def test_it_never_answers_without_a_reading():
    for state in ({}, {"entry": 100.0}, {"peak": 103.0},
                  {"entry": 0, "peak": 103.0},
                  {"entry": "x", "peak": "y"},
                  {"entry": 100.0, "peak": None}):
        assert LOCK(state) is None


def test_it_only_ever_raises_the_stop():
    """A lock that could LOWER a stop is a giveaway."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "trailing_stop.py").read_text(encoding="utf-8")
    block = src[src.index("locked = self._profit_lock(state)"):]
    block = block[:block.index("\n        else:")]
    assert 'locked > state["stop"]' in block


def test_the_short_side_is_untouched():
    """LONG only -- he does not short, and a rule with no measurement
    behind it does not belong in the exit path."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "trailing_stop.py").read_text(encoding="utf-8")
    after = src[src.index("locked = self._profit_lock(state)"):]
    short = after[after.index("\n        else:"):]
    short = short[:short.index('return state["stop"]')]
    assert "self._profit_lock" not in short


# ---------------------------------------------------------------
# THE SWITCHES
# ---------------------------------------------------------------

def test_it_can_be_turned_off(monkeypatch):
    monkeypatch.setattr("config.PROFIT_LOCK_ENABLED", False)
    assert LOCK({"entry": 100.0, "peak": 110.0}) is None


def test_the_settings_are_read_at_call_time(monkeypatch):
    monkeypatch.setattr("config.PROFIT_LOCK_ARM_PCT", 9.0)
    assert LOCK({"entry": 100.0, "peak": 103.0}) is None
    monkeypatch.setattr("config.PROFIT_LOCK_ARM_PCT", 1.0)
    assert LOCK({"entry": 100.0, "peak": 103.0}) is not None


def test_the_same_rule_applies_whichever_way_the_switch_is_set():
    """His instruction, 14 September: no dual settings. Nothing in this
    rule reads the mode or the switch."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "core" / "trailing_stop.py").read_text(encoding="utf-8")
    body = src[src.index("def _profit_lock"):]
    body = body[:body.index("def _lock_at_one_to_one")]
    for forbidden in ("TRADING_MODE", "execution", ".live"):
        assert forbidden not in body
