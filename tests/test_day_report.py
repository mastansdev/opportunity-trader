"""---- WHAT HAPPENED TODAY, ONE TRADE AT A TIME. 31 August 2026. ----

    "i want report of every trade after market closed with details ,
     which stock , entry reason, entry time, entry price, exit price,
     reason, time & pnl of that trade. after exit change in stock all
     i need to see ."                                 -- the operator

Every field he named, plus the one that is actually hard: what the
stock did after the bot left. Nothing grouped, nothing averaged -- a
single session is not a population, and the middle of five numbers is
not a fact about any one of them.

The two things this caught the day it was written, both on 21 August
and both invisible until the report existed:

  * JBMA printed "IN 12:41 / OUT 09:17", which reads as an exit before
    the entry. It was opened on the 21st and stopped out on the 25th --
    four calendar days and a weekend, in a bot that is intraday only.
  * CDSL was bought and rotated out ELEVEN SECONDS later, which the
    report rounded to "held 0 min" and so read as a rounding artefact
    rather than a trade that never had a chance and still paid a full
    round trip in charges.
"""

import os
import sqlite3

import pytest

from tools import day_report


# ------------------------------------------------------------ fixtures

def _trades_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE trade_memory (
        id INTEGER PRIMARY KEY, symbol TEXT, direction TEXT,
        trade_date TEXT, entry_time TEXT, exit_time TEXT,
        entry_price REAL, exit_price REAL, qty INTEGER, pnl REAL,
        exit_reason TEXT, entry_reason TEXT, holding_minutes REAL)""")
    conn.executemany(
        "INSERT INTO trade_memory (symbol, direction, trade_date, "
        "entry_time, exit_time, entry_price, exit_price, qty, pnl, "
        "exit_reason, entry_reason, holding_minutes) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


def _candles_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE candles (date TEXT, symbol TEXT, "
                 "minute TEXT, o REAL, h REAL, l REAL, c REAL)")
    conn.executemany("INSERT INTO candles (date, symbol, minute, o, h, l, c) "
                     "VALUES (?,?,?,?,?,?,?)", rows)
    conn.commit()
    conn.close()


@pytest.fixture
def one_day(tmp_path, monkeypatch):
    t = tmp_path / "trades.db"
    c = tmp_path / "candles.db"
    _trades_db(t, [
        ("NCC", "LONG", "2026-08-21",
         "2026-08-21 09:59:46", "2026-08-21 10:22:51",
         149.18, 146.91, 169, -383.63, "ROTATED_OUT", "RANKED_SETUP", 23.08),
    ])
    _candles_db(c, [
        # before and during -- must be ignored entirely
        ("2026-08-21", "NCC", "2026-08-21T10:00", 149.0, 149.5, 148.0, 149.0),
        ("2026-08-21", "NCC", "2026-08-21T10:22", 147.0, 147.2, 146.0, 146.9),
        # after the exit
        ("2026-08-21", "NCC", "2026-08-21T10:30", 147.0, 150.37, 146.13, 148.0),
        ("2026-08-21", "NCC", "2026-08-21T15:29", 149.0, 149.9, 148.5, 149.93),
    ])
    monkeypatch.setattr(day_report, "TRADES_DB", str(t))
    monkeypatch.setattr(day_report, "CANDLES_DB", str(c))
    return "2026-08-21"


# --------------------------------------------- every field he asked for

def test_every_field_he_named_is_there(one_day):
    text = day_report.render(one_day, day_report.rows_for(one_day))
    for field in ("NCC",              # which stock
                  "RANKED_SETUP",     # entry reason
                  "09:59",            # entry time
                  "149.18",           # entry price
                  "146.91",           # exit price
                  "ROTATED_OUT",      # exit reason
                  "10:22",            # exit time
                  "-384"):            # pnl
        assert field in text, field


def test_after_the_exit_is_measured_from_the_exit_not_the_entry(one_day):
    """The candle at 10:00 is a HIGHER high than anything after the
    exit. Reading from the entry instead of the exit would quietly
    credit the bot with a move it was still holding through."""
    got = day_report.rows_for(one_day)[0]["next"]
    assert got["high"] == pytest.approx(150.37)
    assert got["close"] == pytest.approx(149.93)
    assert got["low"] == pytest.approx(146.13)


def test_all_three_readings_are_shown_never_just_the_good_one(one_day):
    """Showing only the high is how a person talks himself out of a
    stop loss; showing only the low is how he talks himself into
    holding losers. Both, always, plus the close."""
    text = day_report.render(one_day, day_report.rows_for(one_day))
    assert "closed" in text and "best" in text and "worst" in text


def test_the_percentages_are_against_the_exit_price(one_day):
    got = day_report.rows_for(one_day)[0]["next"]
    assert got["close_pct"] == pytest.approx((149.93 - 146.91) / 146.91 * 100)
    assert got["high_pct"] == pytest.approx((150.37 - 146.91) / 146.91 * 100)


# ------------------------------------------------- the two it caught

def test_a_position_held_overnight_is_shouted_about(tmp_path, monkeypatch):
    """JBMA: opened 21 August 12:41, stopped out 25 August 09:17. The
    clock alone printed "OUT 09:17", which reads as an exit before the
    entry and hides the only thing that matters -- an intraday bot
    carried a position over a weekend."""
    t = tmp_path / "t.db"
    _trades_db(t, [("JBMA", "LONG", "2026-08-21",
                    "2026-08-21 12:41:57", "2026-08-25 09:17:57",
                    665.23, 646.75, 93, -1718.64,
                    "FIXED_STOP_LOSS", "RANKED_SETUP", 5555.99)])
    monkeypatch.setattr(day_report, "TRADES_DB", str(t))
    monkeypatch.setattr(day_report, "CANDLES_DB", str(tmp_path / "none.db"))

    text = day_report.render("2026-08-21", day_report.rows_for("2026-08-21"))
    assert "2026-08-25 09:17" in text, "the exit date is hidden"
    assert "HELD PAST THE CLOSE" in text
    assert "3.9 days" in text


def test_eleven_seconds_does_not_round_to_zero_minutes():
    """CDSL was bought and rotated out 11 seconds later. "0 min" reads
    as a rounding artefact; it was a trade that never had a chance and
    paid a full round trip in charges anyway."""
    assert day_report._held(0.18447) == "11 sec"
    assert day_report._held(23.08) == "23 min"
    assert day_report._held(5555.99) == "3.9 days"
    assert day_report._held(None) == "?"


# ------------------------------------------------------- the honest gaps

def test_no_candles_after_the_exit_says_so_instead_of_showing_zero(
        tmp_path, monkeypatch):
    """An exit in the last minutes has no "after". Zero would read as
    "the stock did nothing", which is a different and false claim."""
    t = tmp_path / "t.db"
    _trades_db(t, [("X", "LONG", "2026-08-21",
                    "2026-08-21 15:20:00", "2026-08-21 15:29:00",
                    100.0, 101.0, 10, 10.0, "EOD", "RANKED_SETUP", 9.0)])
    monkeypatch.setattr(day_report, "TRADES_DB", str(t))
    monkeypatch.setattr(day_report, "CANDLES_DB", str(tmp_path / "none.db"))
    rows = day_report.rows_for("2026-08-21")
    assert rows[0]["next"] is None
    assert "nothing to judge it against" in day_report.render("2026-08-21", rows)


def test_a_day_with_no_trades_is_an_answer_not_a_blank(tmp_path,
                                                       monkeypatch):
    """31 August: 2,058 picks, 0 trades. The report must say that
    plainly rather than print an empty table that looks broken."""
    t = tmp_path / "t.db"
    _trades_db(t, [])
    monkeypatch.setattr(day_report, "TRADES_DB", str(t))
    monkeypatch.setattr(day_report, "CANDLES_DB", str(tmp_path / "none.db"))
    text = day_report.render("2026-08-31", day_report.rows_for("2026-08-31"))
    assert "closed no trades today" in text
    assert "finished answer" in text


def test_nothing_is_averaged(one_day):
    """His standing rule, three times over: no pooling, no averaging.
    The only arithmetic across trades is a COUNT."""
    text = day_report.render(one_day, day_report.rows_for(one_day))
    for banned in ("median", "average", "mean ", "avg"):
        assert banned not in text.lower(), banned


def test_it_survives_a_missing_candle_store(tmp_path, monkeypatch):
    """The minute store is written by an earlier nightly step. If that
    step failed, this one must still print the trades."""
    t = tmp_path / "t.db"
    _trades_db(t, [("NCC", "LONG", "2026-08-21",
                    "2026-08-21 09:59:46", "2026-08-21 10:22:51",
                    149.18, 146.91, 169, -383.63,
                    "ROTATED_OUT", "RANKED_SETUP", 23.08)])
    monkeypatch.setattr(day_report, "TRADES_DB", str(t))
    monkeypatch.setattr(day_report, "CANDLES_DB",
                        str(tmp_path / "does_not_exist.db"))
    text = day_report.render("2026-08-21", day_report.rows_for("2026-08-21"))
    assert "NCC" in text and "RANKED_SETUP" in text


# ------------------------------------------------------------- the csv

def test_the_csv_carries_the_same_numbers(one_day):
    csv = day_report.as_csv(one_day, day_report.rows_for(one_day))
    head, row = csv.splitlines()[0], csv.splitlines()[1]
    for column in ("entry_reason", "exit_reason", "pnl",
                   "high_after_pct", "low_after_pct"):
        assert column in head, column
    assert "NCC" in row and "RANKED_SETUP" in row


# ----------------------------------------------------- it actually runs

def test_it_is_in_the_after_close_chain():
    """A report nobody runs is a report that does not exist. And it
    must come AFTER the step that writes the minute store, or every
    trade reports "no candles" -- the one way this can be useless while
    looking fine."""
    from tools.nightly import STEPS

    names = [s[0] for s in STEPS]
    assert "dayreport" in names, "it never runs on its own"
    assert names.index("dayreport") > names.index("intraday"), (
        "it runs before the minute bars are stored, so every trade "
        "will report 'no candles left after the exit'")
