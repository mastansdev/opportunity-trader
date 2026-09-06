"""
==========================================================
A remainder, not a quota
==========================================================

    "on monthly 5L target & in case day -1 bot booked 70 K then
     remaining 4.3L on remaining days & so on. not like averaging each
     day targets. as market may give more opportunites in some days &
     less in other days"
                                -- the operator, 6 September 2026

THE INSTRUCTION IS THE SECOND HALF OF THAT SENTENCE. 5,00,000 over 21
sessions is 23,810 a day, and that figure lies in both directions: it
makes a quiet Tuesday read as a failure, and it calls a day finished
at noon while the market is still handing out NIACLs. His own record
says so plainly -- 2 September lost 6,376 and 4 September made 11,794,
and no single per-day number describes both.

So progress() divides by NOTHING. There is deliberately no "needed per
day" field, because the moment one exists it gets read as a target and
somebody forces a trade on a thin morning to reach it. A test below
fails if such a field ever appears.

AND IT STOPS NOTHING, which is the rule he set on 1 September:

    "there is no fixed time ,price or fixed limitations to follow.
     this is stock market not our own shop to do as we want."

config.DAILY_PROFIT_TARGET_RS was stripped of its power for exactly
this reason and now only announces. This is the same shape one level
up. The only figure that still halts anything is DAILY_MAX_LOSS_RS,
which he chose against his real account and which fires on money
already lost -- and which does not apply in paper at all.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os
import sqlite3
import tempfile
from datetime import date

import pytest

from core import monthly_target as mt


@pytest.fixture()
def book(tmp_path):
    """A month with a losing start and one good day -- his September."""
    path = str(tmp_path / "trade_memory.db")
    conn = sqlite3.connect(path)
    # The columns _booked() reads to price the charges. A trade with
    # no entry/exit cannot be priced, and is counted at gross and said
    # so -- see monthly_target._charges().
    conn.execute("CREATE TABLE trade_memory (id INTEGER PRIMARY KEY, "
                 "trade_date TEXT, symbol TEXT, pnl REAL, "
                 "entry_price REAL, exit_price REAL, qty INTEGER, "
                 "direction TEXT, entry_time TEXT, exit_time TEXT)")
    for day, pnl in (("2026-09-01", -6090.0), ("2026-09-02", -6376.0),
                     ("2026-09-03", 1870.0), ("2026-09-04", 11794.0)):
        conn.execute("INSERT INTO trade_memory (trade_date, symbol, pnl) "
                     "VALUES (?,?,?)", (day, "X", pnl))
    conn.commit()
    conn.close()
    return path


ON = date(2026, 9, 6)


# ------------------------------------------------------------------
# the remainder
# ------------------------------------------------------------------

def test_it_reports_what_is_left_not_what_is_due(book):
    got = mt.progress(now=ON, target=500000.0, db_path=book)
    assert got["booked"] == pytest.approx(1198.0)
    assert got["remaining"] == pytest.approx(498802.0)


def test_his_own_example(book):
    """"day -1 bot booked 70 K then remaining 4.3L"."""
    path = book
    conn = sqlite3.connect(path)
    conn.execute("DELETE FROM trade_memory")
    conn.execute("INSERT INTO trade_memory (trade_date, symbol, pnl) "
                 "VALUES ('2026-09-01', 'X', 70000.0)")
    conn.commit()
    conn.close()
    got = mt.progress(now=ON, target=500000.0, db_path=path)
    assert got["booked"] == 70000.0
    assert got["remaining"] == 430000.0


def test_there_is_no_per_day_figure(book):
    """The whole instruction. A "needed per day" field would be read
    as a target within a week, and forcing a trade on a thin morning
    to reach it is the exact behaviour he ruled out."""
    got = mt.progress(now=ON, target=500000.0, db_path=book)
    for key in got:
        assert "per_day" not in key
        assert "needed" not in key
        assert "daily" not in key
    # and the remainder is never silently divided by the days left
    assert got["remaining"] / max(1, got["days_left"]) not in got.values()


def test_one_line_per_day_never_an_average(book):
    got = mt.progress(now=ON, target=500000.0, db_path=book)
    days = {d["day"]: d["pnl"] for d in got["days"]}
    assert days["2026-09-02"] == -6376.0
    assert days["2026-09-04"] == 11794.0
    assert got["best"]["day"] == "2026-09-04"
    assert got["worst"]["day"] == "2026-09-02"


def test_it_counts_sessions_not_calendar_days(book):
    got = mt.progress(now=ON, target=500000.0, db_path=book)
    # September 2026 has 30 days; nothing like 30 sessions.
    assert 18 <= got["sessions"] <= 23
    assert got["days_done"] + got["days_left"] == got["sessions"]


def test_a_month_already_met_does_not_read_as_finished(book):
    got = mt.line(now=ON, target=1000.0, db_path=book)
    assert "goal is met" in got
    assert "Nothing stops" in got


def test_an_unreadable_book_is_quiet_not_an_error():
    got = mt.progress(now=ON, target=500000.0,
                      db_path=os.path.join(tempfile.mkdtemp(), "gone.db"))
    assert got["booked"] == 0
    assert got["remaining"] == 500000.0


# ------------------------------------------------------------------
# and it decides nothing
# ------------------------------------------------------------------

def test_the_rebuild_never_computes_the_month():
    """---- HIS CONSTRAINT, 6 September 2026. ----

        "but none of these process must slow down my bot trade path or
         trading mechanism at all. i'm telling about all the panels
         rebuilds or any other things"

    The board rebuild is the slowest thing the bot does -- 42 seconds
    at the middle, 82 at the tail -- and the entry path reads it. A
    table nobody is looking at must not be paid for on every cycle.

    So the month is NOT in the payload. It has its own endpoint and
    the tab asks for it when it is opened.
    """
    state = io.open("dashboard/state.py", encoding="utf-8").read()
    assert "monthly_target" not in state, \
        "the month is being computed on every board rebuild"
    server = io.open("dashboard/server.py", encoding="utf-8").read()
    assert '@app.get("/api/month")' in server, \
        "no endpoint -- the tab would have nothing to ask"
    page = io.open("dashboard/static/desk.html", encoding="utf-8").read()
    assert 'fetch("/api/month")' in page
    assert 'b.dataset.tab === "month"' in page, \
        "the tab exists and never loads itself"


def test_the_month_tab_shows_what_he_asked_for():
    """"date no of trades profit/loss remaining target" -- plus the
    one column that cannot be won by luck."""
    page = io.open("dashboard/static/desk.html", encoding="utf-8").read()
    block = page[page.index("function loadMonth"):][:1600]
    for column in ("Date", "Trades", "Profit / loss", "Remaining target",
                   "Without its best two"):
        assert column in block, f"the month table has no {column} column"
    assert 'data-tab="month"' in page


def test_no_gate_reads_the_month():
    for path in ("core/rules.py", "core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/why_moving.py",
                 "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "monthly_target" not in src, \
            f"{path} reads the monthly target -- that was never decided"


def test_the_close_actually_prints_it():
    """The fault this codebase keeps producing is machinery nothing
    calls. This one has a line in the day's close."""
    src = io.open("main.py", encoding="utf-8").read()
    assert "monthly_target import line" in src


def test_the_only_thing_that_still_stops_the_day():
    """DAILY_PROFIT_TARGET_RS announces. MONTHLY_TARGET_RS announces.
    DAILY_MAX_LOSS_RS is the one that halts, and he chose it."""
    import config
    assert config.MONTHLY_TARGET_RS == 5_00_000.0
    assert config.DAILY_MAX_LOSS_RS == 12000.0
    src = io.open("core/engine.py", encoding="utf-8").read()
    assert "monthly_target" not in src
