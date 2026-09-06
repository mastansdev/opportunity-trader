"""
==========================================================
It asks its own book, every night, and keeps the answers
==========================================================

    "yes - self performance upgrade, self improving"
    "again why manual runs? why can't bot do itself."
                        -- the operator, 6 Sep and 4 August 2026

WHAT IT FOUND ON ITS FIRST RUN, which is the argument for it existing:

    12 of 16 days lost money on everything except their best two trades

    MISSED_STOP_RECONCILED    7 trades   2 up   5 down    -22,296
    ROTATED_OUT              16 trades   4 up  12 down     -1,827
    BUYING_DRIED_UP          37 trades  28 up   9 down    +47,481

Two of those needed chasing and both came back mostly clean: ROTATED_
OUT last fired on 21 August and rotation has stayed off; MISSED_STOP_
RECONCILED is late July -- DEEPAKFERT alone was -13,498 on 30 July --
but one landed on 3 September, so it is not dead. None of that was
visible before, because nobody was asking.

THE FIRST QUESTION IS THE ONE THAT MATTERS. Every day on his book so
far, everything except the best two trades lost money:

    1 Sep   -6,235      3 Sep   -3,123
    2 Sep   -6,500      4 Sep  -12,882

Friday's profit IS NIACL and PURVA. So a day's P&L measures whether a
big mover turned up, not whether the bot got better. THE REST can only
be moved by getting better, so it is asked first.

EVERY NUMBER NEEDS AN n. A question with fewer than MIN_CASES says so
instead of answering, and names the stocks rather than pretending a
handful is a rate. Every parameter fitted on 18-27 August died on the
eleven sessions it had not seen; this is the same discipline written
into the asking.

NOTHING IS AVERAGED ACROSS STOCKS -- counts and rupee totals only.

IT DECIDES NOTHING, and the test at the bottom keeps it that way.

Author : H&M Opportunity Trader
==========================================================
"""

import io
import os
import sqlite3
import tempfile
from datetime import date

import pytest

from core import self_review as sr


@pytest.fixture()
def book(tmp_path):
    """Four days shaped like his own: the best two carry the day."""
    path = str(tmp_path / "trade_memory.db")
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE trade_memory (
        id INTEGER PRIMARY KEY, trade_date TEXT, entry_time TEXT,
        symbol TEXT, pnl REAL, exit_reason TEXT, door TEXT,
        mcap_band TEXT, reason_kind TEXT, move_age_min REAL,
        run_up_pct REAL)""")
    rows = [
        # day        symbol      pnl     exit           door
        ("2026-09-04", "NIACL", 14577.0, "BUYING_DRIED_UP", "news"),
        ("2026-09-04", "PURVA", 10099.0, "BUYING_DRIED_UP", "news"),
        ("2026-09-04", "RESPONIND", -4833.0, "TRAILING_STOP", "surge"),
        ("2026-09-04", "SKIPPER", -3153.0, "TRAILING_STOP", "surge"),
        ("2026-09-03", "BRIGADE", 3406.0, "BUYING_DRIED_UP", "news"),
        ("2026-09-03", "ALEMBICLTD", -2581.0, "TRAILING_STOP", "surge"),
    ]
    for day, sym, pnl, exit_reason, door in rows:
        conn.execute(
            "INSERT INTO trade_memory (trade_date, symbol, pnl, "
            "exit_reason, door) VALUES (?,?,?,?,?)",
            (day, sym, pnl, exit_reason, door))
    conn.commit()
    conn.close()
    return path


ON = date(2026, 9, 6)


# ------------------------------------------------------------------
# the question that matters
# ------------------------------------------------------------------

def test_it_asks_what_the_day_made_without_its_best_two(book):
    got = sr.ask(now=ON, since_days=30, db_path=book)
    rest = [a for a in got["answers"]
            if "without its best two" in a["question"]][0]
    days = {d["day"]: d for d in rest["days"]}
    friday = days["2026-09-04"]
    assert friday["total"] == pytest.approx(16690.0)
    # NIACL and PURVA taken out, the rest lost
    assert friday["rest"] == pytest.approx(-7986.0)


def test_a_profitable_day_can_still_be_bleeding(book):
    """Friday made money and its other trades lost. That is the whole
    reason this question is asked first."""
    got = sr.ask(now=ON, since_days=30, db_path=book)
    rest = [a for a in got["answers"]
            if "without its best two" in a["question"]][0]
    bleeding = [d for d in rest["days"] if d["rest"] < 0 < d["total"]]
    assert bleeding, "a day that profited while its rest bled was missed"


# ------------------------------------------------------------------
# every number needs an n
# ------------------------------------------------------------------

def test_too_few_cases_is_said_not_answered(book):
    got = sr.ask(now=ON, since_days=30, db_path=book)
    doors = [a for a in got["answers"] if a["question"] == "which door paid"][0]
    assert doors["n"] == 6
    assert doors["enough"] is False
    assert "not a finding" in doors["answer"]


def test_a_small_group_names_the_stocks(book):
    """A handful is a list of names, never a rate."""
    got = sr.ask(now=ON, since_days=30, db_path=book)
    doors = [a for a in got["answers"] if a["question"] == "which door paid"][0]
    surge = [g for g in doors["groups"] if g["value"] == "surge"][0]
    assert "RESPONIND" in surge["names"]


def test_a_field_that_started_recording_today_says_so(book):
    got = sr.ask(now=ON, since_days=30, db_path=book)
    for question in ("did arriving late cost anything",
                     "which size of company paid",
                     "which kind of reason paid"):
        answer = [a for a in got["answers"] if a["question"] == question][0]
        assert answer["enough"] is False
        assert "6 September 2026" in answer["answer"]


def test_nothing_is_averaged_across_stocks(book):
    """Counts and rupee totals only -- "not stock working mechanism"."""
    got = sr.ask(now=ON, since_days=30, db_path=book)
    for answer in got["answers"]:
        for group in answer.get("groups", ()):
            assert set(group) >= {"n", "up", "down", "total"}
            assert "mean" not in group and "median" not in group
            assert "average" not in group


# ------------------------------------------------------------------
# self improving -- it keeps what it said
# ------------------------------------------------------------------

def test_tonights_answers_are_kept(book, tmp_path):
    store = str(tmp_path / "self_review.db")
    got = sr.ask(now=ON, since_days=30, db_path=book)
    assert sr.keep(got, store=store) == len(got["answers"])
    seen = sr.trend("which door paid", store=store)
    assert seen and seen[0]["day"] == ON.isoformat()


def test_asking_twice_on_one_day_does_not_double_up(book, tmp_path):
    store = str(tmp_path / "self_review.db")
    for _ in range(3):
        sr.keep(sr.ask(now=ON, since_days=30, db_path=book), store=store)
    assert len(sr.trend("which door paid", store=store)) == 1


def test_the_trend_is_what_makes_it_self_improving(book, tmp_path):
    """One night's answer is a fact. Ten nights of the same answer is
    a finding. An answer that flips every night was never real."""
    store = str(tmp_path / "self_review.db")
    for day in (date(2026, 9, 4), date(2026, 9, 5), ON):
        sr.keep(sr.ask(now=day, since_days=30, db_path=book), store=store)
    seen = sr.trend("which door paid", limit=10, store=store)
    assert [s["day"] for s in seen] == ["2026-09-06", "2026-09-05",
                                        "2026-09-04"]


# ------------------------------------------------------------------
# and it decides nothing
# ------------------------------------------------------------------

def test_it_runs_at_the_close_without_being_asked():
    src = io.open("main.py", encoding="utf-8").read()
    assert "self_review.run()" in src, \
        "the review exists and nothing ever runs it -- the fault this "\
        "codebase keeps producing"


def test_no_gate_reads_the_review():
    for path in ("core/rules.py", "core/ranker.py", "core/auto_entry.py",
                 "core/engine.py", "core/why_moving.py",
                 "core/results_gate.py"):
        src = io.open(path, encoding="utf-8").read()
        assert "self_review" not in src, \
            f"{path} reads the self review -- that was never decided"


def test_an_unreadable_book_is_quiet_not_an_error():
    got = sr.ask(now=ON, db_path=os.path.join(tempfile.mkdtemp(), "no.db"))
    assert got["trades"] == 0
    assert got["answers"]


def test_the_bar_is_the_one_already_in_use():
    """One idea, one threshold -- the same n the opportunity memory
    waits for before it will call anything measured."""
    from core.opportunity import PAYOFF_MIN_CASES
    assert sr.MIN_CASES == PAYOFF_MIN_CASES
