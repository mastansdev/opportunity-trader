"""
The volume rule after 29 July 2026.

    "we need some confirmation before entries = ... 2) Volume"
    "what ? but without volume how the stock moves upside ?"
                                        -- operator, 29 July 2026

He is right that a stock cannot rise without volume. What the bot had
was not missing volume -- it was missing MEASUREMENT.

Dhan reports a running day total, and a candle's volume is the
difference between its first and last reading inside that minute. A
minute that received only ONE snapshot subtracts a number from itself
and reports zero. Counted across all three recorded sessions:

    27 Jul   28,123 of 235,348 candles  (11.9%)
    28 Jul   24,135 of 230,047 candles  (10.5%)
    29 Jul   25,931 of 229,470 candles  (11.3%)

Seven of the bot's 35 breakouts fired on such a minute -- IKS,
NAVINFLUOR, DEEPAKNTR, ENDURANCE, GILLETTE, IFBIND, GANECOS -- and the
old filter waved all seven through, because it could not tell "no
volume" from "not measured".

Two rules are held to here:

    1. A single-minute surge must stay visible as a single-minute
       surge. An early attempt averaged the breakout over five minutes
       and turned a real 3x spike into 1.4x, which would have refused
       exactly the trades worth taking.

    2. A breakout whose volume genuinely cannot be measured is now
       REFUSED, not allowed. That is the operator's change.
"""

import pytest

import core.engine as engine_module
from core.engine import Engine


def _engine_with_history(prior_volumes, breakout_volume):
    """A symbol with a known volume history and one breakout candle."""
    engine = Engine()
    history = [{"high": 100.0, "low": 99.0, "close": 100.0, "volume": v}
               for v in prior_volumes]
    breakout = {"high": 112.0, "low": 111.0, "close": 112.0,
                "volume": breakout_volume}
    engine.candle_engine.last_n_closed = lambda symbol, n: (
        history + [breakout])[-n:]
    return engine, breakout


# ---------------------------------------------------------------
# The normal path is untouched
# ---------------------------------------------------------------

def test_a_real_single_minute_surge_still_passes():
    """3x on the breakout minute. This must not be diluted away."""
    engine, breakout = _engine_with_history([100] * 20, 300)
    assert engine._breakout_has_volume("TCS", breakout) is True


def test_a_thin_drift_across_the_line_is_still_refused():
    """MOIL / TATASTEEL: 1.2x is a drift, not a breakout."""
    engine, breakout = _engine_with_history([100] * 20, 120)
    assert engine._breakout_has_volume("TCS", breakout) is False


# ---------------------------------------------------------------
# The zero-volume minute -- the actual bug
# ---------------------------------------------------------------

def test_a_zero_volume_minute_is_judged_on_the_window_not_waved_through():
    """IKS at 10:19 and six others. The minute reports 0 because one
    snapshot landed in it. The shares are in the neighbouring minutes,
    so the window can still judge the breakout."""
    engine, breakout = _engine_with_history([100] * 16 + [900] * 4, 0)
    # window = four 900s + the zero = 3,600 over 5 minutes = 720/min,
    # against an average of roughly 260 -> a genuine surge.
    assert engine._breakout_has_volume("TCS", breakout) is True


def test_a_zero_volume_minute_in_a_quiet_stretch_is_refused():
    """Same zero reading, but the window around it is ordinary. No
    surge, so no entry."""
    engine, breakout = _engine_with_history([100] * 20, 0)
    assert engine._breakout_has_volume("TCS", breakout) is False


def test_a_completely_silent_window_is_refused_not_allowed():
    """THE OPERATOR'S CHANGE. Five consecutive minutes with nothing,
    on a symbol that normally reports volume. Previously this returned
    True -- 'volume is a quality bonus, never a hard gate'. Now it is
    a refusal."""
    engine, breakout = _engine_with_history([100] * 16 + [0] * 4, 0)
    assert engine._breakout_has_volume("TCS", breakout) is False


def test_the_old_permissive_behaviour_is_one_flag_away(monkeypatch):
    monkeypatch.setattr(engine_module, "VOLUME_REQUIRED_FOR_ENTRY", False)
    engine, breakout = _engine_with_history([100] * 16 + [0] * 4, 0)
    assert engine._breakout_has_volume("TCS", breakout) is True


# ---------------------------------------------------------------
# The filter must never stop the bot outright
# ---------------------------------------------------------------

def test_a_feed_that_reports_no_volume_at_all_does_not_block_everything():
    """Ticker mode reports no volume for ANY symbol. That is a fact
    about the feed, not about this breakout -- refusing every trade
    because of it would simply stop the bot."""
    engine, breakout = _engine_with_history([None] * 20, None)
    assert engine._breakout_has_volume("TCS", breakout) is True


def test_too_little_history_to_judge_does_not_block():
    """Right after the open there is no average yet."""
    engine, breakout = _engine_with_history([100] * 2, 100)
    assert engine._breakout_has_volume("TCS", breakout) is True


def test_no_candle_at_all_is_survivable():
    assert Engine()._breakout_has_volume("TCS", None) is True


# ---------------------------------------------------------------
# The window helper itself
# ---------------------------------------------------------------

def test_the_window_sums_the_recent_minutes():
    engine, breakout = _engine_with_history([100] * 20, 50)
    assert engine._window_volume("TCS", breakout) == 100 * 4 + 50


def test_the_window_reports_None_when_there_is_genuinely_nothing():
    """None means 'no data', which is different from zero. A window
    returning 0 would read as a real measurement of no trading."""
    engine, breakout = _engine_with_history([0] * 20, 0)
    assert engine._window_volume("TCS", breakout) is None
