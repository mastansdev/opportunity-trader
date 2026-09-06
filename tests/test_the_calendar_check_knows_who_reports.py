"""
==========================================================
It showed red for knowing the answer
==========================================================

    "3 morning_ready's calendar nag ? whats this"
                                -- the operator, 5 September 2026

He asked what that line was for, and on 6 September, run against the
live store, it BLOCKED:

    [BLOCKS] results calendar: last refreshed 2026-08-31 and 4
             company(ies) report in the days ahead but none today --
             the bot will not know which

It knew exactly which. The store held BLEL and SHIPROCKET for Monday
7 September, GAJA for Thursday and LALITHAA for Friday, by name, read
off the Earnings Pulse channel the day before. What was stale was the
NSE stamp, and the check was still reporting the stamp while claiming
to report the knowledge.

The comment sitting directly above that branch already had the rule
right -- "it still BLOCKS when something is due and nothing is known"
-- so this is the branch catching up with its own note.

WHY IT MATTERS EVEN THOUGH IT STOPS NO TRADE. morning_ready feeds the
dashboard, not the entry path; nothing here can refuse an order. But
it fires on every day where nobody reports today and somebody reports
later, which off-season is most days. A checklist that shows red while
the bot is right is how a real red gets scrolled past -- the same
reasoning that is already written into this file for the stale-stamp
case.

THE BLOCK IS KEPT for the case it was written for: rows are due and
not one of them carries a symbol. Then the bot really cannot say who.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import datetime

import pytest

from core import morning_ready


def _results_db(rows, last_refresh="2026-08-31"):
    """A results store holding (symbol, date) pairs."""
    path = os.path.join(tempfile.mkdtemp(), "results_calendar.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE results_events (id INTEGER PRIMARY KEY,"
                 " symbol TEXT, results_date TEXT)")
    conn.execute("CREATE TABLE results_meta (key TEXT PRIMARY KEY,"
                 " value TEXT)")
    for symbol, day in rows:
        conn.execute("INSERT INTO results_events (symbol, results_date)"
                     " VALUES (?,?)", (symbol, day))
    if last_refresh:
        conn.execute("INSERT INTO results_meta (key, value) "
                     "VALUES ('last_refresh', ?)", (last_refresh,))
    conn.commit()
    conn.close()
    return path


def _calendar_line(results_db, now):
    got = morning_ready.check(now=now, results_db=results_db)
    for check in got["checks"]:
        if check["name"] == "results calendar":
            return check
    raise AssertionError("no results calendar check was reported")


SUNDAY = datetime(2026, 9, 6, 7, 30)
MONDAY = datetime(2026, 9, 7, 8, 30)
TUESDAY = datetime(2026, 9, 8, 8, 30)

REAL = [("BLEL", "2026-09-07"), ("SHIPROCKET", "2026-09-07"),
        ("GAJA", "2026-09-10"), ("LALITHAA", "2026-09-11")]


# ------------------------------------------------------------------
# the day it went red
# ------------------------------------------------------------------

def test_it_does_not_block_when_it_knows_who_is_coming():
    line = _calendar_line(_results_db(REAL), SUNDAY)
    assert not line["blocks"], line["detail"]
    assert line["ok"]


def test_it_says_who_and_when():
    """"The calendar is fine" is not information, and he reads this
    line every morning."""
    line = _calendar_line(_results_db(REAL), SUNDAY)
    assert "BLEL" in line["detail"]
    assert "2026-09-07" in line["detail"]


def test_it_still_warns_that_the_nse_list_may_be_short():
    """Four names off one Telegram channel is not proof that four is
    all of them."""
    line = _calendar_line(_results_db(REAL), SUNDAY)
    assert "2026-08-31" in line["detail"]
    assert "may be more" in line["detail"]


# ------------------------------------------------------------------
# and the other days still read correctly
# ------------------------------------------------------------------

def test_the_day_itself_names_the_companies():
    line = _calendar_line(_results_db(REAL), MONDAY)
    assert not line["blocks"]
    assert "BLEL" in line["detail"] and "SHIPROCKET" in line["detail"]


def test_after_they_report_it_looks_further_ahead():
    line = _calendar_line(_results_db(REAL), TUESDAY)
    assert not line["blocks"]
    assert "GAJA" in line["detail"]
    assert "BLEL" not in line["detail"], "a company that already " \
        "reported is still being announced"


def test_an_empty_calendar_out_of_season_is_not_a_fault():
    line = _calendar_line(_results_db([]), SUNDAY)
    assert not line["blocks"]
    assert "nothing is due" in line["detail"]


def test_a_stamp_from_today_still_passes():
    line = _calendar_line(_results_db(REAL, last_refresh="2026-09-06"),
                          SUNDAY)
    assert not line["blocks"]


# ------------------------------------------------------------------
# what the block is actually for
# ------------------------------------------------------------------

def test_it_still_blocks_when_something_is_due_and_nobody_is_named():
    """Rows counted, no symbol on any of them. Then the bot really
    cannot say who reports, which is the case the check exists for."""
    line = _calendar_line(_results_db([(None, "2026-09-10"),
                                       ("", "2026-09-11")]), SUNDAY)
    assert line["blocks"], line["detail"]
    assert "will not know which" in line["detail"]


def test_this_check_cannot_stop_a_trade():
    """It feeds the dashboard. If it ever reaches the entry path that
    should be a decision, not a drift."""
    import io
    for path in ("core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "morning_ready" not in src, \
            "%s reads the morning checklist -- that was never decided" % path
