"""
==========================================================
CDSL was bought and sold eleven seconds apart.
==========================================================

    "fix the seat timing"          -- operator, 23 August 2026

THE PROBLEM IS REAL. 20 August: the bot's first rank-1 was STAR at
09:30, which lost. SOLARA did not reach rank 1 until 10:24 and closed
+16.4%. Seats are spent in the first minutes and the good names
surface later. Measured over 20 sessions, filling the same three seats
from the board as it stood at each hour:

    commit at   Rs/trade   win%
    09:45         -279     31.8
    10:30         -115     40.0
    13:00          -64     46.7
    14:00          -19     51.7

Patience raises the win rate steadily. Nothing is reliably positive,
so this is a DIRECTION, not a discovery.

A TIME LADDER IS NOT THE ANSWER

STAGED_POSITION_LIMITS was exactly that, and was flattened on 27 July:
"a strongly bullish tape produced two trades before 10:00 and nothing
after, because both early seats were spent by 09:26". It throttles the
whole day to fix one hour. Reintroducing it would repeat a mistake
this repository already made and already understood.

ROTATION IS THE RIGHT MECHANISM, AND IT WAS UNCONSTRAINED

Give a seat up when something clearly better appears. It churned
because it could swap on almost nothing -- a 0.4% edge and NO minimum
holding period:

    12:49:37  PAPER BUY  CDSL 47 @ 1390.80
    12:49:48  CDSL rotated OUT for URBANCO

Median hold across every ROTATED_OUT trade on record: 2.3 minutes.
20% won. They lost Rs 1,860 between them.

So: the edge is 2.0% (five times what it was) and a position gets 45
minutes to work before its seat can be taken. SOLARA at 10:24 beat
STAR by far more than 2% and arrived an HOUR later -- a genuine
hand-over survives both rules. The 11-second CDSL swap cleared 0.4%
and nothing else.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import datetime, timedelta

import config

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------
# THE SETTINGS
# ---------------------------------------------------------------

def test_the_edge_is_no_longer_a_twitch():
    """0.4% was crossed by noise. SOLARA beat STAR by far more."""
    assert config.ROTATION_MIN_STRENGTH_EDGE >= 0.02


def test_a_position_gets_time_to_work():
    """Long enough that a real hand-over survives it and a twitch does
    not. SOLARA arrived an hour after the seats were filled."""
    assert config.ROTATION_MIN_HOLD_MINUTES >= 30


def test_rotation_is_OFF():
    """---- HE STOPPED IT. 31 August 2026. ----

        "we stopped rotation trading"              -- the operator

    This asserted ON, with the reasoning that leaving it off was
    shipping a fix that never runs. The fix ran. What it did on 21
    August, its last trading day: NCC out after 23 minutes, URBANCO
    after 13, JSFB after 4, CDSL after ELEVEN SECONDS -- four of the
    five trades that day, and three of the four then ran without us.

    His call, and he had already made it. The setting simply never
    followed."""
    assert config.ENABLE_SLOT_ROTATION is False


def test_the_daily_swap_cap_survives():
    """Even a well-behaved rotation pays brokerage twice each time."""
    assert config.ROTATION_MAX_PER_DAY <= 5


# ---------------------------------------------------------------
# THE HOLD IS ENFORCED, NOT JUST CONFIGURED
# ---------------------------------------------------------------

def test_the_hold_is_checked_in_the_rotation_path():
    """A setting nothing reads is a comment. This is the whole fix."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _maybe_rotate_out"):
               src.find("def _daily_realized_pnl")]
    assert "ROTATION_MIN_HOLD_MINUTES" in body, (
        "the minimum hold is configured but never checked")
    assert "entry_time" in body


def test_the_hold_is_measured_the_same_way_as_no_progress():
    """One way to compute holding time. A second would drift from the
    first, which this codebase has been bitten by repeatedly."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    assert src.count("total_seconds() / 60.0") >= 2


def test_a_missing_entry_time_does_not_crash_the_tick():
    """An adopted or restored position may carry no entry_time. The
    rotation check must survive it -- it runs on the tick path."""
    src = (ROOT / "core" / "engine.py").read_text(encoding="utf-8")
    body = src[src.find("def _maybe_rotate_out"):
               src.find("def _daily_realized_pnl")]
    assert "if entry_time is not None" in body
    assert "TypeError" in body


# ---------------------------------------------------------------
# THE LADDER STAYS FLAT
# ---------------------------------------------------------------

def test_the_time_ladder_was_not_reintroduced():
    """It was tried, it starved a bullish tape, and it was removed on
    27 July with the reason recorded. The seat-timing evidence does not
    justify repeating it."""
    limits = config.STAGED_POSITION_LIMITS
    assert len(limits) == 1, (
        "a time ladder is back -- see config.py, 27 July 2026")


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "config.py").read_text(encoding="utf-8")
    assert "SOLARA" in src and "ELEVEN SECONDS" in src.upper()
