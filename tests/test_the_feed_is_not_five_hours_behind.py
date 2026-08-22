"""
==========================================================
"STILL RECOVERING history" -- while it was 6 minutes behind.
==========================================================

    "i lost too many opportunities till today since bot started"
                                -- operator, 21 August 2026

21 August, 12:36. The bot was restarted with the day's fixes and
refused to arm:

    {"success": false,
     "error": "not ready to trade: STILL RECOVERING history -- it is
               storing posts up to 6h old."}

The collector was current. data/telegram.db's newest message was
stamped 2026-08-21T07:00:34+00:00 -- 12:30:34 IST, SIX MINUTES old,
and the 'feed alive' check on the same screen said so: "last message
stored 2 min ago".

ONE LINE, AND IT DELETED THE TIMEZONE

    datetime.fromisoformat(str(value).replace("+00:00", ""))

It removed the offset and kept the digits, so 07:00:34+00:00 became a
naive 07:00:34 and was compared against a LOCAL datetime.now() of
12:36. IST is UTC+5:30, so EVERY message read exactly 5h30m older
than it was.

WHY THAT MATTERS MORE THAN IT LOOKS

CATCH_UP_STILL_RUNNING_HOURS is 6.0. With a constant +5.5h error the
gate really fired at THIRTY MINUTES of true lag, not six hours -- and
the median of the last 25 stored posts crosses thirty minutes on any
quiet channel. The arming gate was effectively closed all day.

'feed alive' was right on the same screen because it reads seen_at,
which is written in local time. Only the checks reading `at` -- the
POSTED time, which is UTC -- were wrong.

The identical UTC/IST confusion cost a day in the events store on
19 August (tests/test_the_news_reaches_the_record.py). Converting is
the fix. Deleting the offset never was.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
from datetime import datetime, timedelta, timezone

from core.morning_ready import _parse

ROOT = pathlib.Path(__file__).resolve().parents[1]

IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------
# THE CASE
# ---------------------------------------------------------------

def test_a_utc_stamp_becomes_local_time():
    """THE MESSAGE THAT BLOCKED HIM. 07:00:34 UTC is 12:30:34 IST."""
    got = _parse("2026-08-21T07:00:34+00:00")
    assert got is not None
    expect = datetime(2026, 8, 21, 7, 0, 34, tzinfo=timezone.utc)
    assert got == expect.astimezone().replace(tzinfo=None)


def test_a_current_feed_does_not_read_as_hours_old():
    """The whole failure in one assertion: a post from a minute ago
    must not measure as 5h30m."""
    now = datetime.now(timezone.utc) - timedelta(minutes=1)
    age_h = (datetime.now() - _parse(now.isoformat())).total_seconds() / 3600
    assert age_h < 0.5, f"a one-minute-old post measured {age_h:.2f}h old"


def test_the_offset_is_not_simply_deleted():
    """Deleting it is what caused this. Pinned against the PARSED
    TREE, not the text -- the docstring of _parse quotes the broken
    line to explain it, and a grep cannot tell an explanation from an
    instruction. That mistake was made twice in one day before this
    was written this way.
    """
    import ast

    src = (ROOT / "core" / "morning_ready.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.FunctionDef) and n.name == "_parse")

    # everything the function DOES, with its docstring dropped
    body = fn.body[1:] if (fn.body and isinstance(fn.body[0], ast.Expr)
                           and isinstance(fn.body[0].value, ast.Constant)
                           ) else fn.body
    code = chr(10).join(ast.unparse(n) for n in body)

    assert "+00:00" not in code, "the offset is being deleted again"
    assert "astimezone" in code, "it is not converting to local time"


# ---------------------------------------------------------------
# EVERY SHAPE THE STORE ACTUALLY WRITES
# ---------------------------------------------------------------

def test_a_naive_stamp_is_left_alone():
    """seen_at is written in local time with no offset. Shifting it
    would break the 'feed alive' check that was working."""
    assert _parse("2026-08-21T12:34:28") == datetime(2026, 8, 21, 12, 34, 28)


def test_a_non_utc_offset_is_converted_too():
    """+05:30 is already IST -- it must come back as the same clock
    time, not shifted again."""
    got = _parse("2026-08-21T12:30:34+05:30")
    expect = datetime(2026, 8, 21, 7, 0, 34, tzinfo=timezone.utc)
    assert got == expect.astimezone().replace(tzinfo=None)


def test_a_space_separated_stamp_still_parses():
    assert _parse("2026-08-21 12:34:28") == datetime(2026, 8, 21, 12, 34, 28)


def test_junk_is_None_not_an_exception():
    """A readiness check that throws blocks arming with a stack trace
    instead of a sentence."""
    for bad in (None, "", "not-a-date", 12345, [], {}, "2026-13-45"):
        assert _parse(bad) is None


def test_whitespace_does_not_defeat_it():
    assert _parse("  2026-08-21T12:34:28  ") == datetime(2026, 8, 21, 12, 34, 28)


# ---------------------------------------------------------------
# THE GATE ITSELF
# ---------------------------------------------------------------

def test_the_threshold_was_not_moved_to_hide_the_bug():
    """The tempting fix was to raise CATCH_UP_STILL_RUNNING_HOURS past
    the 5.5h error, which would have left the check meaningless and
    unable to spot a REAL catch-up."""
    from core import morning_ready
    assert morning_ready.CATCH_UP_STILL_RUNNING_HOURS == 6.0


def test_a_real_catch_up_is_still_caught():
    """The control. A genuine history walk stores posts many hours old
    and must still block arming."""
    old = datetime.now(timezone.utc) - timedelta(hours=20)
    age_h = (datetime.now() - _parse(old.isoformat())).total_seconds() / 3600
    assert age_h > 6.0, "a 20-hour-old post no longer reads as stale"


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "morning_ready.py").read_text(encoding="utf-8")
    body = src[src.find("def _parse"):src.find("def check(")]
    assert "IST" in body and "5h30m" in body
