"""
==========================================================
A screen that says something, once
==========================================================

    "pls complete revamp our dashboard with worthy & neat readable
     layout not duplicate"
                                    -- operator, 2 August 2026

From his own screenshot of the live panel, three faults, all measured
against the real store rather than guessed at.

1. THE SAME SENTENCE, THREE TIMES
   NH and CONCORDBIO each appeared three times in the news block, the
   same wording every time. Counted:

        80   CANSLIM rows differing only by the date in brackets
       145   REPORTED rows re-filed by a later recap
        13   exact duplicates

   Most of it is mine, from that same day: tools/load_canslim.py ran
   on the 1st and again on the 2nd, and the recap parser re-files a
   company the forward card already named.

2. FORTY-FIVE ROWS SAYING ONE THING
   The blocked list ran to about forty-five rows, every one reading
   "reports today, numbers not out yet". It took more of the page than
   gainers and losers combined and carried a single fact.

3. NINE CARDS, EIGHT DASHES
   The money strip showed "—" eight times out of nine, and market
   intelligence five out of eight. Correct in paper mode -- there is
   no real cash and no margin -- and still the first thing the eye
   lands on.

WHAT IS NOT DONE HERE
---------------------
Nothing is deleted. The duplicate rows stay in stock_events.db, the
full blocked list stays in the snapshot, and every hidden tile is
named on a hover. _events_for()'s own comment is emphatic that
collapsing the STORE has failed repeatedly -- "losing an event costs
a trade" -- and that remains true. This is the display, and it is
reversible by removing one call.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

from core.shortlist import ShortlistBuilder, _newest_per_fact


def ev(symbol, at, kind, headline):
    return {"symbol": symbol, "at": at, "kind": kind,
            "headline": headline, "grade": None}


# ---------------------------------------------------------------
# 1. THE SAME FACT, ONCE
# ---------------------------------------------------------------
def test_a_tier_loaded_on_two_days_shows_once():
    """THE ONE THAT MATTERS, and it is my own bug from the same day.
    load_canslim ran on the 1st and the 2nd. Same tier, two rows."""
    rows = [
        ev("NH", "2026-08-02T23:00", "SETUP",
           "CANSLIM MIXED -- 41 of 90 today (02 Aug)"),
        ev("NH", "2026-08-01T23:00", "SETUP",
           "CANSLIM MIXED -- 41 of 90 today (01 Aug)"),
    ]
    kept = _newest_per_fact(rows)
    assert len(kept) == 1
    assert "02 Aug" in kept[0]["headline"], "the newest must win"


def test_a_recap_refiling_an_event_shows_once():
    rows = [
        ev("CORONA", "2026-08-01T18:00", "REPORTED",
           "REPORTED AFTER CLOSE (31 Jul) -- not yet priced by the market"),
        ev("CORONA", "2026-07-31T18:00", "REPORTED",
           "REPORTED AFTER CLOSE (31 Jul) -- not yet priced by the market"),
    ]
    assert len(_newest_per_fact(rows)) == 1


def test_two_genuinely_different_chips_from_one_card_both_survive():
    """The raw card and the parsed BEAT are different sentences and
    different information. Collapsing them would be the deduplication
    that keeps costing events."""
    rows = [
        ev("CONCORDBIO", "2026-07-31T12:49", "RESULT",
           "#CONCORDBIO — Earnings · Q1 FY27 Strong YoY growth"),
        ev("CONCORDBIO", "2026-07-31T12:49", "RESULT",
           "BEAT Revenue, EBITDA -- #CONCORDBIO — Earnings · Q1 FY27"),
    ]
    assert len(_newest_per_fact(rows)) == 2


def test_the_same_wording_under_two_kinds_is_two_facts():
    rows = [
        ev("X", "2026-08-02T10:00", "NEWS", "Order win Rs 900 cr"),
        ev("X", "2026-08-02T10:00", "ORDER", "Order win Rs 900 cr"),
    ]
    assert len(_newest_per_fact(rows)) == 2


def test_only_a_trailing_date_stamp_is_ignored():
    """"(02 Aug)" at the END is the loader's date. A date inside the
    sentence is part of the fact."""
    same = ShortlistBuilder._same_fact
    assert same(ev("X", "", "SETUP", "CANSLIM MIXED (02 Aug)")) == \
        same(ev("X", "", "SETUP", "CANSLIM MIXED (01 Aug)"))
    assert same(ev("X", "", "REPORTED", "REPORTED AFTER CLOSE (31 Jul) -- a")) != \
        same(ev("X", "", "REPORTED", "REPORTED AFTER CLOSE (30 Jul) -- a"))


def test_nothing_is_deleted_from_the_store():
    """_events_for()'s own comment: "Raised rather than deduplicated
    on purpose ... losing an event costs a trade." That is about the
    STORE, and it still stands. This is the read."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find("def _newest_per_fact"):]
    block = block[:block.find("class ShortlistBuilder")]
    # The SQL, not the word. The docstring says it DELETES NOTHING,
    # and the first version of this test failed on its own English --
    # the fifth time that has happened in this project.
    assert not re.search(r"\bDELETE\s+FROM\b", block, re.I)
    assert "conn" not in block and "execute(" not in block
    assert "DISPLAY ONLY" in block


def test_an_empty_list_is_handled():
    assert _newest_per_fact([]) == []
    assert _newest_per_fact(None) == []


# ---------------------------------------------------------------
# 2. FORTY-FIVE ROWS BECOME ONE LINE
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 3. A DASH IS NOT A NUMBER
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 4. THE WATCHLIST REACHES THE SCREEN -- 2 August 2026
# ---------------------------------------------------------------
#
#     "where is watchlist?"
#
# core/reporting.py and core/watchlist.py were built, wired into the
# snapshot and covered by 38 tests -- and nothing in index.html drew
# them. Built, tested, invisible.
#
# The THIRD time in two days: the chain summary reached the shortlist
# row and was never copied onto the gainers row, and broker_sync sat in
# the payload for a day with no panel. A backend that nobody renders is
# a backend that does not exist.

# ---------------------------------------------------------------
# 5. A ROW MUST NOT PUSH THE TABLE SIDEWAYS -- 2 August 2026
# ---------------------------------------------------------------
#
# From his screenshot with the calls working: expanding CONCORDBIO put
# a horizontal scrollbar under the gainers table and pushed LTP,
# CHANGE% and SCORE off the right edge.
#
# .chip-wrap already had flex-wrap. That was not the problem. A flex
# item does not shrink below its own content, so ONE chip carrying
#
#     "AI +: Strong top-line growth and margin expansion in Q1 FY27
#      typically translate to hi"
#
# widened the column and every other column gave way to it.

