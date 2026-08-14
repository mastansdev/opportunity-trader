"""
Daily history freshness -- 29 July 2026.

data/daily_candles.db and the bhavcopy folder both stopped at 27 July.
Two sessions behind, with nothing anywhere that downloads them.
tools/build_daily_history.py had existed all along; nobody ran it.

What it feeds: each stock's 50-day median volume, median turnover and
50-day moving average -- the Shortlist's "normals", including the
MIN_TURNOVER filter that keeps illiquid names out.

Two missing days out of fifty barely move a median, so the damage on
the day it was found was small. THE POINT IS DRIFT. Nothing was
stopping it. A month of this and the medians are genuinely wrong and
the thin-stock filter starts passing names it should refuse. Slow leaks
are the ones that run for six months unnoticed.
"""

from datetime import date

import pytest

from tools.preflight import _trading_days_behind


# ---------------------------------------------------------------
# Counting missed sessions
# ---------------------------------------------------------------

def test_the_real_case_from_29_july():
    """Newest bar 27 July, today the 29th. 28 July was a trading day
    and is missing -- one session behind."""
    assert _trading_days_behind(date(2026, 7, 27), date(2026, 7, 29)) == 1


def test_yesterdays_bar_at_this_mornings_check_is_current():
    """At 08:45 the newest bhavcopy NSE has published is yesterday's.
    Holding it is being up to date, not behind."""
    assert _trading_days_behind(date(2026, 7, 28), date(2026, 7, 29)) == 0


def test_a_weekend_is_not_a_missed_session():
    """Friday's bar read on Monday morning is current. Counting Sat and
    Sun as gaps would download nothing and warn every Monday, and a
    check that cries wolf trains you to ignore it."""
    assert _trading_days_behind(date(2026, 7, 24), date(2026, 7, 27)) == 0


def test_a_long_gap_is_counted_in_sessions_not_days():
    """Two full weeks away: 10 trading days, not 14."""
    assert _trading_days_behind(date(2026, 7, 13), date(2026, 7, 27)) == 9


def test_today_equals_the_newest_bar():
    assert _trading_days_behind(date(2026, 7, 29), date(2026, 7, 29)) == 0


def test_a_bar_in_the_future_never_reports_a_negative_gap():
    """Clock skew, or a bhavcopy stored under tomorrow's date. Should
    read as current rather than as a nonsense negative."""
    assert _trading_days_behind(date(2026, 8, 5), date(2026, 7, 29)) == 0


# ---------------------------------------------------------------
# The check itself must never stop the morning
# ---------------------------------------------------------------

def test_a_missing_database_warns_rather_than_crashing(tmp_path, monkeypatch):
    import tools.preflight as preflight
    monkeypatch.chdir(tmp_path)
    preflight._results.clear()
    preflight._check_daily_history(auto_fill=False)
    state, name, detail = preflight._results[-1]
    assert state == preflight.WARN
    assert "daily_candles.db missing" in detail


def test_no_fetch_reports_the_gap_without_downloading(tmp_path, monkeypatch):
    """Useful on a machine with no network, and the mode a test runs
    in -- it must never reach for NSE."""
    import sqlite3
    import tools.preflight as preflight
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    con = sqlite3.connect(tmp_path / "data" / "daily_candles.db")
    con.execute("create table daily_bars (date text)")
    con.execute("insert into daily_bars values ('2020-01-01')")
    con.commit()
    con.close()

    def explode(*a, **k):
        raise AssertionError("must not download in --no-fetch mode")

    monkeypatch.setattr("tools.build_daily_history.build", explode)
    preflight._results.clear()
    preflight._check_daily_history(auto_fill=False)
    state, _name, detail = preflight._results[-1]
    assert state == preflight.WARN
    assert "session(s) behind" in detail


def test_an_empty_table_is_reported_not_crashed(tmp_path, monkeypatch):
    import sqlite3
    import tools.preflight as preflight
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    con = sqlite3.connect(tmp_path / "data" / "daily_candles.db")
    con.execute("create table daily_bars (date text)")
    con.commit()
    con.close()

    preflight._results.clear()
    preflight._check_daily_history(auto_fill=False)
    assert preflight._results[-1][0] == preflight.WARN
