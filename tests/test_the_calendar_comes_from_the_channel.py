"""
==========================================================
The results gate had an empty list
==========================================================

    "result gate = same as now , only block that stock/s on their
     result day , to know which stock earnings pulse channel post that
     image. this settles i think"
                                -- the operator, 5 September 2026

He is describing what core/results_gate.py already does. It blocks a
stock only on its own result day, only until the numbers land, and lets
it through on GOOD or STRONG. Nothing about the RULE needed changing.

WHAT WAS BROKEN IS THE LIST. earnings_calendar is built in main.py from
NSE board meetings plus a hand-typed dict, and on the morning he said
this, data/results_calendar.db held:

    last_refresh        2026-08-31
    due from today on   0

Zero. So the gate blocked nobody, and core/morning_ready.py -- reading
the same table -- reported "out of season, nothing due" on a day a
company was reporting.

Earnings Pulse publishes the list, and the CAPTION carries it in plain
text, so no picture-reading is needed to know WHO:

    "Tomorrow's Calendar - 05 Sep, 2026
     Key companies reporting results: #MOLBIO"

BOTH SHAPES ARE READ, because they fail differently: the daily post is
exact but exists only if it was collected; the weekly one covers the
day the daily was missed. Measured on the store, 9 daily and 16 weekly
cards, and after this the gate sees MOLBIO today, BLEL and SHIPROCKET
on Monday, GAJA on Thursday and LALITHAA on Friday.

THE GRID SCRAMBLES, AND THAT IS WHY RANK EXISTS. A flat transcript of a
grid loses which company sits under which day. The 24 August card came
out as

    ARDEE MVELECTRO AFTER CLOSE AFTER CLOSE
    WEDNESDAY, AUGUST 26  TUESDAY, AUGUST 25  MILKYMIST
    AFTER CLOSE  MONDAY, AUGUST 31

so splitting on day headings put MILKYMIST on the 25th. The operator
read the same card and said what it means:

    "tuesday = ardee; mvelectro / wednesday = jnpr /
     monday (next week) = MILKYMIST"

The cards published on the 25th, 26th and 27th agree with him. So the
newest card wins, and a dated daily post beats any grid.

NEVER GUESS A SYMBOL. A tag the master does not carry is logged and
stored nowhere. Inventing one here would put a stock on a results
blackout it is not on, and this gate REFUSES entries.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import date, datetime, timezone

import pytest

from core.results_calendar import (ResultsCalendar, fetch_from_telegram,
                                   telegram_calendar_rows)


def _store(rows):
    """A telegram.db holding just these messages."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (channel TEXT, message_id TEXT,"
                 " at TEXT, text TEXT, ocr_text TEXT)")
    for i, (at, text, ocr) in enumerate(rows):
        conn.execute("INSERT INTO messages VALUES (?,?,?,?,?)",
                     ("Earnings Pulse", str(i), at, text, ocr))
    conn.commit()
    conn.close()
    return path


DAILY = ("2026-09-04T14:31:09+00:00",
         "\U0001F4C5 Tomorrow's Calendar - 05 Sep, 2026 "
         "Key companies reporting results: #MOLBIO @earnings_pulse",
         "TOMORROW'S CALENDAR 05 Sep, 2026 - 1 Companies molbio MOLBIO")

WEEKLY = ("2026-09-05T02:30:31+00:00",
          "THE WEEK AHEAD: Earnings Calendar Key companies: "
          "#LALITHAA #SHIPROCKET #GAJA #BLEL @earnings_pulse",
          "EARNINGS PULSE: THE WEEK AHEAD SEPTEMBER 7-11 Q1 FY27 "
          "EARNINGS MONDAY, SEPTEMBER 7 SHIPROCKET BLEL 9,894 Cr "
          "1,925 Cr MID CAP SMALL CAP AFTER AFTER THURSDAY, "
          "SEPTEMBER 10 GAJA 2,283 Cr SMALL CAP AFTER FRIDAY, "
          "SEPTEMBER 11 LALITHAA 17,256 Cr MID CAP AFTER")

# The one that came out of the reader scrambled.
SCRAMBLED = ("2026-08-24T02:30:19+00:00",
             "THE WEEK AHEAD: Earnings Calendar Key companies: "
             "#JNPR #MILKYMIST #ARDEE #MVELECTRO @earnings_pulse",
             "EARNINGS PULSE: THE WEEK AHEAD AUGUST 25-31 Q1 FY27 "
             "EARNINGS ARDEE MVELECTRO AFTER CLOSE AFTER CLOSE "
             "WEDNESDAY, AUGUST 26 TUESDAY, AUGUST 25 MILKYMIST "
             "AFTER CLOSE MONDAY, AUGUST 31")

CORRECTED = ("2026-08-25T02:30:19+00:00",
             "THE WEEK AHEAD: Earnings Calendar Key companies: "
             "#MILKYMIST #JNPR @earnings_pulse",
             "EARNINGS PULSE: THE WEEK AHEAD AUGUST 26-31 Q1 FY27 "
             "EARNINGS WEDNESDAY, AUGUST 26 JNPR 14,795 Cr MID CAP "
             "AFTER MONDAY, AUGUST 31 MilkyMist MILKYMIST 15,320 Cr "
             "MID CAP AFTER")


# ------------------------------------------------------------------
# reading the channel
# ------------------------------------------------------------------

def test_the_daily_post_names_one_date():
    rows = dict(telegram_calendar_rows(db_path=_store([DAILY])))
    assert rows == {"MOLBIO": date(2026, 9, 5)}


def test_the_weekly_post_splits_by_day():
    rows = dict(telegram_calendar_rows(db_path=_store([WEEKLY])))
    assert rows == {"SHIPROCKET": date(2026, 9, 7),
                    "BLEL": date(2026, 9, 7),
                    "GAJA": date(2026, 9, 10),
                    "LALITHAA": date(2026, 9, 11)}


def test_the_newest_card_settles_a_scrambled_one():
    """His reading of that card: tuesday = ardee, mvelectro /
    wednesday = jnpr / monday next week = MILKYMIST."""
    rows = dict(telegram_calendar_rows(
        db_path=_store([SCRAMBLED, CORRECTED])))
    assert rows["MILKYMIST"] == date(2026, 8, 31)
    assert rows["JNPR"] == date(2026, 8, 26)


def test_a_company_the_grid_cannot_place_gets_no_date():
    """In the scrambled card ARDEE and MVELECTRO appear BEFORE any day
    heading, so there is nothing to attach them to. Leaving them out is
    the right answer: a company put on a results blackout it is not on
    would be REFUSED an entry it should have had.

    They are not lost -- the daily post places them, which is the whole
    reason both shapes are read. See the test below."""
    rows = dict(telegram_calendar_rows(db_path=_store([SCRAMBLED])))
    assert "ARDEE" not in rows
    assert "MVELECTRO" not in rows


def test_the_daily_post_places_what_the_grid_could_not():
    """The two shapes fail differently, which is why both are read."""
    daily_25 = ("2026-08-24T14:30:00+00:00",
                "Tomorrow's Calendar - 25 Aug, 2026 Key companies "
                "reporting results: #ARDEE #MVELECTRO",
                "TOMORROW'S CALENDAR 25 Aug, 2026 - 2 Companies")
    rows = dict(telegram_calendar_rows(
        db_path=_store([SCRAMBLED, daily_25, CORRECTED])))
    assert rows["ARDEE"] == date(2026, 8, 25)
    assert rows["MVELECTRO"] == date(2026, 8, 25)
    assert rows["MILKYMIST"] == date(2026, 8, 31)
    assert rows["JNPR"] == date(2026, 8, 26)


def test_a_dated_daily_post_beats_a_grid():
    """The daily post states ONE date for the whole message -- there is
    no grid to scramble, so it wins even against a newer weekly card."""
    grid = ("2026-09-06T02:30:00+00:00",
            "THE WEEK AHEAD: Earnings Calendar Key companies: #MOLBIO",
            "THE WEEK AHEAD MONDAY, SEPTEMBER 7 MOLBIO")
    rows = dict(telegram_calendar_rows(db_path=_store([DAILY, grid])))
    assert rows["MOLBIO"] == date(2026, 9, 5)


def test_the_header_bounds_the_week():
    """    "ON TOP OF THE IMG = HEADER PART MENTIONS THE SAME DETAILS
            WEEK AHEAD RESULTS."                -- the operator

    The header states the week the card covers, and it is the only
    independent check available on a card whose grid the reader has
    scrambled. A day heading read as a date outside that week did not
    come from this card.
    """
    wrong = ("2026-09-05T02:30:31+00:00",
             "THE WEEK AHEAD: Earnings Calendar Key companies: "
             "#SHIPROCKET #GAJA",
             "EARNINGS PULSE: THE WEEK AHEAD SEPTEMBER 7-11 Q1 FY27 "
             "EARNINGS MONDAY, SEPTEMBER 7 SHIPROCKET "
             # a heading the reader mangled into another month
             "THURSDAY, DECEMBER 10 GAJA")
    rows = dict(telegram_calendar_rows(db_path=_store([wrong])))
    assert rows["SHIPROCKET"] == date(2026, 9, 7)
    assert "GAJA" not in rows, "a date outside the stated week was kept"


def test_a_card_with_no_readable_header_is_still_used():
    """Refusing every card whose header blurred would cost far more
    than the one misread it protects against."""
    noheader = ("2026-09-05T02:30:31+00:00",
                "THE WEEK AHEAD: Earnings Calendar Key companies: #GAJA",
                "MONDAY, SEPTEMBER 7 GAJA 2,283 Cr SMALL CAP")
    rows = dict(telegram_calendar_rows(db_path=_store([noheader])))
    assert rows["GAJA"] == date(2026, 9, 7)


def test_a_week_that_crosses_a_month_is_read():
    """"THE WEEK AHEAD AUGUST 31-SEPTEMBER 2" is a real header."""
    crossing = ("2026-08-27T02:30:15+00:00",
                "THE WEEK AHEAD: Earnings Calendar Key companies: "
                "#LEAPIND #TECHNOCRAF",
                "EARNINGS PULSE: THE WEEK AHEAD AUGUST 31-SEPTEMBER 2 "
                "Q1 FY27 EARNINGS MONDAY, AUGUST 31 LEAPIND 7,046 Cr "
                "MID CAP AFTER WEDNESDAY, SEPTEMBER 2 TECHNOCRAF "
                "1,364 Cr SMALL CAP AFTER")
    rows = dict(telegram_calendar_rows(db_path=_store([crossing])))
    assert rows["LEAPIND"] == date(2026, 8, 31)
    assert rows["TECHNOCRAF"] == date(2026, 9, 2)


def test_a_message_with_no_hashtag_is_ignored():
    """The caption hashtags are the ONLY source of a company here. A
    transcript is never used to invent one."""
    nameless = ("2026-09-04T14:31:00+00:00",
                "Tomorrow's Calendar - 05 Sep, 2026",
                "TOMORROW'S CALENDAR 05 Sep, 2026 SOMECOMPANY")
    assert telegram_calendar_rows(db_path=_store([nameless])) == []


def test_an_unreadable_store_is_not_a_failure():
    """A chat feed must never be able to stop the NSE refresh."""
    assert telegram_calendar_rows(db_path="Z:/nowhere/telegram.db") == []


# ------------------------------------------------------------------
# writing it where the gate reads
# ------------------------------------------------------------------

@pytest.fixture()
def calendar(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return ResultsCalendar()


def test_the_dates_reach_the_calendar(calendar):
    written = fetch_from_telegram(
        calendar, known_symbols={"MOLBIO", "SHIPROCKET", "BLEL",
                                 "GAJA", "LALITHAA"},
        db_path=_store([DAILY, WEEKLY]))
    assert written == 5
    seen = calendar.as_calendar_dict(frm=date(2026, 9, 1), days=20)
    assert "MOLBIO" in seen["2026-09-05"]
    assert {"SHIPROCKET", "BLEL"} <= set(seen["2026-09-07"])


def test_a_symbol_the_master_does_not_carry_is_never_stored(calendar):
    """Inventing one would blacklist a stock from trading on a day it
    does not report, and this gate REFUSES entries."""
    written = fetch_from_telegram(
        calendar, known_symbols={"MOLBIO"},
        db_path=_store([DAILY, WEEKLY]))
    assert written == 1
    seen = calendar.as_calendar_dict(frm=date(2026, 9, 1), days=20)
    assert "2026-09-07" not in seen


def test_it_is_actually_called_by_the_refresh():
    """The fault this codebase keeps producing is machinery that exists
    and is never called."""
    import io
    src = io.open("core/results_calendar.py", encoding="utf-8").read()
    body = src[src.index("def refresh(calendar=None"):]
    assert "fetch_from_telegram(calendar" in body
    assert body.index("fetch_from_telegram(calendar") < \
        body.index("needs_refresh(today)"), \
        "reading a local sqlite file has nothing to throttle, and "\
        "skipping it is how the store came to say 0 due"
