"""
==========================================================
The scorecard must not depend on HOW he stopped the bot
==========================================================

    "CTRL+C  main.py closed . no score card found ..."
                                -- operator, 5 August 2026

WHAT WENT WRONG
---------------
5 August was the first day of Phase 1. Twenty-seven picks were
recorded across the session and the only question that mattered was
whether they made money. He stopped main.py after the close and got
nothing.

_score_the_day() was guarded by `closed_normally`, a flag set in
exactly one place: when the main loop itself reaches 15:30 and breaks.
A KeyboardInterrupt skips that line, so Ctrl+C -- the way a person
actually stops a program -- silently disabled the scorecard forever.

I wrote that guard on 4 August and told him the bot would score itself
from then on. It would only ever have scored itself on a day he walked
away from the keyboard.

THE RULE
--------
How the process ended is not the question. Whether the trading day is
over is.

    Ctrl+C at 11:00   ->  no scorecard. The day is not finished and a
                          part-day number would be worse than none.
    Ctrl+C at 16:10   ->  scorecard. The market is shut; the picks are
                          final whatever the exit path was.
    loop reaches 15:30 -> scorecard, as before.

Author : H&M Opportunity Trader
==========================================================
"""

import re

SRC = open("main.py", encoding="utf-8").read()


def _code():
    """main.py with comments and docstrings stripped.

    Six times now I have asserted against prose I wrote in a comment
    and called the feature tested.
    """
    text = re.sub(r'"""[\s\S]*?"""', "", SRC)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    return text


def _guard():
    """The line that decides whether the day gets scored."""
    code = _code()
    at = code.find("_score_the_day()")
    assert at > 0, "main.py no longer calls _score_the_day()"
    head = code.rfind("if ", 0, at)
    return code[head:at]


# ---------------------------------------------------------------
# 1. THE GUARD IS NOT closed_normally ALONE
# ---------------------------------------------------------------
def test_the_clock_decides_not_the_exit_path():
    guard = _guard()
    assert "MARKET_CLOSE_T" in guard, (
        "The scorecard is gated on how the process ended, not on "
        "whether the market is shut. Ctrl+C after the close will "
        "produce nothing -- exactly what happened on 5 August.")


def test_a_normal_close_still_scores():
    """The 15:30 path must not have been traded away for the fix."""
    assert "closed_normally" in _guard()


def test_it_reads_the_clock_at_shutdown_not_at_import():
    """`datetime.now()`, evaluated when the process stops.

    A module-level timestamp would freeze at 08:45 and every session
    would look like it ended before the open.
    """
    assert "datetime.now()" in _guard()


# ---------------------------------------------------------------
# 2. A MID-SESSION CTRL+C MUST STILL SKIP IT
# ---------------------------------------------------------------
def test_the_condition_is_at_or_after_the_close():
    """>= MARKET_CLOSE_T, not != and not <.

    Stopping the bot at 11:00 to change a setting must not write a
    half-day scorecard into the record and call it the day.
    """
    guard = _guard()
    assert re.search(r">=\s*MARKET_CLOSE_T", guard), guard


def test_the_two_conditions_are_an_or_not_an_and():
    """Either route qualifies. Requiring both would restore the bug
    and add a second one."""
    guard = _guard()
    assert " or " in guard and " and " not in guard, guard


# ---------------------------------------------------------------
# 3. THE ORDER INSIDE IT IS STILL FIXED
# ---------------------------------------------------------------
def test_bars_are_built_before_the_picks_are_scored():
    """verify_picks reads the archive build_daily_history writes.
    Reversed, it correctly reports nothing -- and 'nothing' is what a
    silent failure looks like too."""
    body = SRC[SRC.find("def _score_the_day"):SRC.find("def _run_nightly")]
    assert body.index("build_daily_history") < body.index("verify_picks")


def test_a_missing_bhavcopy_says_so_instead_of_showing_zero():
    """NSE publishes on its own schedule. 'Not available yet' is an
    answer; a scorecard of zeroes is a lie."""
    body = SRC[SRC.find("def _score_the_day"):SRC.find("def _run_nightly")]
    assert "not available yet" in body.lower()


def test_scoring_cannot_break_the_shutdown():
    """It runs after the feed is closed and state is saved. Nothing it
    does may stop the process exiting cleanly."""
    body = SRC[SRC.find("def _score_the_day"):SRC.find("def _run_nightly")]
    assert body.count("except Exception") >= 3, (
        "each step of the chain needs its own guard")
