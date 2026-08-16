"""
==========================================================
During the session, or after the close
==========================================================

    "what about watchlist = stocks reporting results during markets /
     after markets = todays + next day watchlist"
                                    -- operator, 2 August 2026

The split was already in the store -- 462 REPORTED events carry DURING
or AFTER. There was no panel for it, and build_results_today() merged
the two into one "reporting today" list, which hides the only part
that changes what you do:

    DURING   the move happens while you are watching
    AFTER    the market is shut when the numbers land, so nothing can
             be traded on them until the next open -- which is the
             early-bird window he has been asking for since Friday

THE TENSE IS THE TRAP
---------------------
Three cards carry the same words and mean different things:

    TODAY EARNINGS        REPORTS  ...   has NOT reported yet
    TOMORROW'S CALENDAR   REPORTS  ...   has NOT reported yet
    EARNINGS PULSE RECAP  REPORTED ...   already out

A watchlist built from the recap would list companies whose numbers
are already public as though they were still ahead of you. So the
forward list reads only future-tense headlines, and the recap is used
for exactly one thing: which of the last close's reporters are still
unanswered by the tape.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import sqlite3
from datetime import date

import pytest

from core.reporting import AFTER, DURING, counts, rows, watchlist


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "events.db")
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, "
                 "symbol TEXT, kind TEXT, headline TEXT)")
    for symbol, head in [
        # Forward -- have NOT reported yet.
        ("AETHER", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("MARUTI", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
        ("DIXON", "REPORTS AFTER CLOSE (03 Aug) -- moves the next session"),
        ("TITAN", "REPORTS DURING THE SESSION (04 Aug) -- live today"),
        ("SBIN", "REPORTS AFTER CLOSE (04 Aug) -- moves the next session"),
        # Backward -- already out.
        ("CORONA", "REPORTED AFTER CLOSE (31 Jul) -- not yet priced "
                   "by the market"),
        ("GLENMARK", "REPORTED AFTER CLOSE (31 Jul) -- not yet priced "
                     "by the market"),
        ("ABCAPITAL", "REPORTED DURING THE SESSION (31 Jul)"),
        # Noise the query must ignore.
        ("XYZ", "PULSE: Excellent results"),
    ]:
        kind = "REPORTED" if head.startswith("REPORT") else "RESULT"
        conn.execute("INSERT INTO events (symbol, kind, headline) "
                     "VALUES (?,?,?)", (symbol, kind, head))
    conn.commit()
    conn.close()
    return path


MONDAY = date(2026, 8, 3)


# ---------------------------------------------------------------
# 1. THE SPLIT
# ---------------------------------------------------------------
def test_today_is_split_by_the_close(db):
    got = watchlist(events_db=db, on=MONDAY)["reporting_today"]
    assert [r["symbol"] for r in got[DURING]] == ["AETHER", "MARUTI"]
    assert [r["symbol"] for r in got[AFTER]] == ["DIXON"]


def test_tomorrow_is_its_own_list(db):
    got = watchlist(events_db=db, on=MONDAY)["reporting_tomorrow"]
    assert [r["symbol"] for r in got[DURING]] == ["TITAN"]
    assert [r["symbol"] for r in got[AFTER]] == ["SBIN"]


def test_a_company_never_appears_on_both_sides(db):
    view = watchlist(events_db=db, on=MONDAY)
    for key in ("reporting_today", "reporting_tomorrow"):
        during = {r["symbol"] for r in view[key][DURING]}
        after = {r["symbol"] for r in view[key][AFTER]}
        assert not during & after


def test_the_counts_are_reported(db):
    # today_unstated / tomorrow_unstated arrived on 2 August, when the
    # 02 Aug card turned out to name PERSISTENT with no During / After
    # columns at all. Ten of the nineteen forward cards look like that.
    assert counts(watchlist(events_db=db, on=MONDAY)) == {
        "today_during": 2, "today_after": 1, "today_unstated": 0,
        "tomorrow_during": 1, "tomorrow_after": 1, "tomorrow_unstated": 0,
        "unpriced": 2}


# ---------------------------------------------------------------
# 2. THE TENSE
# ---------------------------------------------------------------
def test_a_company_that_has_already_reported_is_not_on_the_forward_list(db):
    """THE ONE THAT MATTERS. CORONA reported after Friday's close. Its
    numbers are public. Listing it as "reporting Monday" would have the
    operator waiting for something that already happened."""
    view = watchlist(events_db=db, on=MONDAY)
    forward = set()
    for key in ("reporting_today", "reporting_tomorrow"):
        for side in (DURING, AFTER):
            forward |= {r["symbol"] for r in view[key][side]}
    assert "CORONA" not in forward
    assert "GLENMARK" not in forward


def test_the_after_close_reporters_become_the_unpriced_list(db):
    got = watchlist(events_db=db, on=MONDAY)["unpriced_from_last_close"]
    assert {r["symbol"] for r in got} == {"CORONA", "GLENMARK"}


def test_a_past_during_session_reporter_is_not_a_watchlist_item(db):
    """ABCAPITAL reported inside Friday's session. It has been fully
    traded -- there is nothing left to be early to."""
    got = watchlist(events_db=db, on=MONDAY)["unpriced_from_last_close"]
    assert "ABCAPITAL" not in {r["symbol"] for r in got}


def test_events_of_other_kinds_are_ignored(db):
    every = rows(events_db=db, on=MONDAY)
    names = {r["symbol"] for r in every["forward"] + every["unpriced"]}
    assert "XYZ" not in names


# ---------------------------------------------------------------
# 3. THE CALL TRAVELS WITH IT
# ---------------------------------------------------------------
def test_a_stock_the_chain_has_read_carries_its_call(db):
    view = watchlist(events_db=db, on=MONDAY,
                     calls={"AETHER": "BUY", "DIXON": "AVOID"})
    during = {r["symbol"]: r["call"] for r in view["reporting_today"][DURING]}
    after = {r["symbol"]: r["call"] for r in view["reporting_today"][AFTER]}
    assert during["AETHER"] == "BUY"
    assert after["DIXON"] == "AVOID"


def test_no_call_is_not_a_gap(db):
    """Most of these have not reported yet, so there is nothing to
    call. None is the honest answer, not a missing value."""
    view = watchlist(events_db=db, on=MONDAY)
    assert view["reporting_today"][DURING][0]["call"] is None


# ---------------------------------------------------------------
# 4. IT CANNOT BREAK THE SNAPSHOT
# ---------------------------------------------------------------
def test_every_date_is_a_string(db):
    """"A date object is not JSON. One un-encodable value here is a 500
    for the whole snapshot, not just this panel." -- dashboard/state.py
    """
    view = watchlist(events_db=db, on=MONDAY,
                     calls={"AETHER": "BUY"})
    json.dumps(view)                      # raises if anything is a date
    for row in view["unpriced_from_last_close"]:
        assert isinstance(row["on"], str)


def test_a_missing_database_returns_empty_rather_than_raising(tmp_path):
    # ---- IT LEFT LITTER IN THE LIVE DATA FOLDER. 16 August 2026. ----
    #
    # This named "data/does-not-exist.db". sqlite3.connect() CREATES
    # the file it is handed, so every run left an empty database behind
    # in the directory that holds the bot's real memory -- found during
    # the store inventory alongside no-such-file-at-all.db and
    # there-is-no-such-file.db, all three written by tests.
    #
    # Harmless while they are empty, and exactly the reach that put a
    # one-character token into data/dhan_token.json on 13 August. The
    # path never needed to be under data/ at all.
    view = watchlist(events_db=str(tmp_path / "no-such-store.db"), on=MONDAY)
    assert counts(view)["today_during"] == 0
    json.dumps(view)


def test_the_panel_is_wired_and_guarded():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "reporting_watchlist(calls=calls, tiers=tiers)" in src
    assert '"watchlist": watch' in src
    block = src[src.find("watch = None"):]
    block = block[:block.find('return {"available": True')]
    assert "except Exception" in block, (
        "a failing watchlist must not take the results panel with it")
