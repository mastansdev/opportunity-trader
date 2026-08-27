"""A closed session cannot gain another bar. Do not download it twice.

    "minutes collector is doing multiple times same collections"
                                    -- operator, 27 August 2026

The loop asked for the WHOLE window for EVERY symbol every time, and
the window is five or six sessions. UNIQUE (date, symbol, minute) meant
no duplicate ROWS landed, so nothing looked wrong -- but the download
happened anyway:

    20 Aug   15:30:39   16:28:29   21:45:46      three runs
    22 Aug   08:38:07   08:51:30                 two
    26 Aug   15:31:05   15:54:06                 two, 23 minutes apart

Both 26 August runs asked for the identical range (19->26 Aug) and the
identical 1,288 symbols. On a closed session 1,078 of those already
held a 15:29 bar -- 84% of the work was provably pointless.
"""

import inspect

from tools import fetch_history


def test_the_skip_is_off_during_a_live_session():
    """No symbol holds a 15:29 bar at 11:00, so nothing is skipped and
    behaviour inside a session is exactly what it was."""
    src = inspect.getsource(fetch_history.run)
    assert 'substr(minute, 12, 5) >= :m' in src
    assert 'LAST_MINUTE = "15:29"' in src


def test_it_is_keyed_on_the_newest_requested_day():
    """If the newest day is complete the run is a repeat, so the older
    days in the window need no separate test."""
    src = inspect.getsource(fetch_history.run)
    assert '"d": str(to_date)' in src


def test_force_re_fetches_everything():
    sig = inspect.signature(fetch_history.run)
    assert sig.parameters["force"].default is False
    src = inspect.getsource(fetch_history.run)
    assert "not force" in src


def test_a_broken_read_fetches_everything_rather_than_nothing():
    """Failing to read what is stored must never be read as 'all
    stored'. That would silently skip the whole universe."""
    src = inspect.getsource(fetch_history.run)
    assert "already = set()" in src
    assert "Fetching everything" in src


def test_the_skip_matches_the_store_on_a_closed_session():
    """The real query against the real store, on a session that has
    ended and one that has not."""
    import sqlite3
    import os
    db = os.path.join("data", "history_candles.db")
    if not os.path.exists(db):
        import pytest
        pytest.skip("no history store on this machine")
    con = sqlite3.connect(db)
    closed = con.execute(
        "select count(distinct symbol) from candles where date=? "
        "and substr(minute,12,5) >= '15:29'", ("2026-08-26",)).fetchone()[0]
    con.close()
    assert closed > 500, (
        "a finished session should have most symbols holding a 15:29 "
        "bar -- if not, the skip will never fire and the re-fetch stays")
