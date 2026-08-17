"""
==========================================================
The catalyst window: measured, and NOT changed
==========================================================

    "measure it against trade_memory first"
                                -- operator, 16 August 2026

He asked whether a catalyst should stay valid for more than one
session, after TVSMOTOR rallied +590 rs on a business update the bot
had read, reasoned and scored 0.85 -- and never bought, because
core/why_moving.py drops any event not dated today.

WHAT THE MEASUREMENT FOUND

trade_memory could not answer it. 134 closed trades, and
days_since_results -- the exact column for this question -- was NULL on
every one, because core/engine.py hardcoded None where it is stamped.
Segmented, the book is also not what it looks like:

    STRUCTURAL_LONG_BREAKOUT   n=62   +2,982   45% win   <- the bot
    MANUAL_BUY_DASHBOARD       n=52  -15,786   38% win
    ADOPTED_FROM_BROKER        n=19  -69,766   11% win

So it was proxied across 715 stored POSITIVE reasoned catalysts,
measured against daily_candles:

    hold        n     avg      median   up%
    1 session  703   +0.26%   -0.02%    50%
    2 sessions 703   +0.67%   +0.19%    53%
    3 sessions 702   +0.72%   +0.41%    56%
    5 sessions 688   +1.01%   +0.48%    56%

Day one is the WORST holding period there is -- a median of -0.02% and
a coin flip. The move keeps going for days. That supports the change.

AND THEN THE SPLIT THAT KILLED IT

Measured from the day-1 close, held to day 5, split on whether the
stock was still extending:

    day 1 UP   (extending)  n=346   +0.63%   50% up
    day 1 DOWN (faded)      n=342   +0.78%   58% up

The stocks that FADED did better over the following week than the ones
still rising -- the opposite of opportunity rule 3, "making highs".
Confidence does not rank either: 0.70-0.79 (+0.88%) beat 0.80+
(+0.45%).

So extending the window and keeping the "still extending" filter would
select the WEAKER half of a +0.70% average, against round-trip charges
and a 1.8-3% stop. That is not an edge, it is a coin flip with costs.

---- AND THEN THE CHECK I SHOULD HAVE RUN FIRST ----

Every number above is RAW. None of it was compared to what the market
did over the same days. Benchmarked against the median stock, same
start date, same horizon:

    hold        n     stock   market   EXCESS   beat market
    1 session  659   +0.27%   +0.22%   +0.05%      43%
    3 sessions 658   +0.79%   +0.79%   -0.00%      45%
    5 sessions 652   +1.05%   +0.94%   +0.12%      47%

THE CATALYST HAS NO MEASURABLE EDGE OVER THE MARKET. The "+1.01% at
five sessions" that looked like a reason to widen the window was
almost entirely the market drifting up over June-August 2026, and
fewer than half of catalyst stocks beat the median stock. Beta
reported as signal, by me, until it was benchmarked.

THE DAY-2 DIP, measured on request and benchmarked the same way --
event day, next session closes DOWN, buy that close:

    group                        n    EXCESS   beat market
    day-2 DIP (faded)  +3d     328    +0.02%      52%
    day-2 POP (extend) +3d     328    +0.09%      42%
    day-2 DIP (faded)  +5d     324    +0.06%      52%
    day-2 POP (extend) +5d     325    +0.29%      46%

Also nothing. +0.06% excess is inside the round-trip charge on a
Rs 1.2 lakh position. The POP shows a higher MEAN with a WORSE hit
rate, which is the signature of a few large winners carrying a
losing median -- the opposite of what a Rs 1,500 fixed-risk book
wants.

WHAT THIS DOES AND DOES NOT SAY. The window is June-August 2026, one
regime, one rising market, and 715 catalysts that are not independent
of each other. It does not prove the catalysts are worthless -- they
explain WHY a stock is moving, which is what the reason gate uses them
for. It says that as a PREDICTOR of the next five sessions, over this
sample, they carry no excess return worth a stop.

NOTHING ABOUT THE ENTRY RULES WAS CHANGED.

What changed is that days_since_results is now stamped on every
position, so the next time this question is asked it can be answered
on the bot's OWN fills instead of a proxy.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import date

import pytest

from core import runup

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_field_is_actually_stamped_now():
    """THE ONE THAT MATTERS. It was hardcoded None since it was
    written, which is why 134 trades could not answer the question."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    block = src[src.find('"days_since_results": None'):
                src.find("def _no_reason_refusal")]
    assert "runup.reported_on" in block, (
        "days_since_results is still never populated -- the next "
        "measurement will be a proxy again")
    assert "within_days=180" in block, (
        "it uses runup's 12-day RUN-UP window, which writes None for "
        "any result older than a fortnight")


def test_reported_on_still_defaults_to_the_runup_window():
    """The new parameter must not have changed what every existing
    caller sees. A run-up into a result three weeks old is not a
    run-up."""
    assert runup.reported_on("TVSMOTOR", on_date=date(2026, 8, 14)) is None
    got = runup.reported_on("TVSMOTOR", on_date=date(2026, 8, 14),
                            within_days=180)
    assert got == date(2026, 7, 21), got


def test_a_wider_window_gives_a_real_number():
    when = date(2026, 8, 14)
    got = runup.reported_on("TVSMOTOR", on_date=when, within_days=180)
    assert (when - got).days == 24


def test_the_freshness_rule_is_UNCHANGED():
    """He asked for a measurement, not a change. If the one-session
    window ever moves it must be a deliberate decision with its own
    argument -- not something that drifted in behind a measurement
    that did not support it.
    """
    src = (ROOT / "core" / "why_moving.py").read_text(encoding="utf-8")
    assert "if on_date and not at.startswith(str(on_date)):" in src, (
        "the one-session catalyst window changed. The measurement of "
        "16 August did NOT support widening it: the still-extending "
        "half returned +0.63% at 50% up, worse than the faded half.")


def test_the_measurement_is_written_down_where_it_will_be_found():
    """A number nobody can find is a number that gets re-derived
    wrongly. The counter-evidence lives beside the rule it argues
    about."""
    doc = __doc__ or ""
    assert "day 1 UP" in doc and "day 1 DOWN" in doc
    assert "+0.63%" in doc and "+0.78%" in doc
    # The market-adjusted correction must stay beside the raw numbers.
    # Without it the raw +1.01% reads as an edge, which is how it was
    # first reported -- wrongly.
    assert "EXCESS" in doc and "no measurable edge" in doc.lower()
    assert "day-2 DIP" in doc
