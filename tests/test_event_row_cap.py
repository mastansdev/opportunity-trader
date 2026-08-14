"""
==========================================================
The limit was already dropping events
==========================================================

    Measured 1 August 2026:

        rows in the 96-hour STOCK window : 2,058
        the limit the panel asked for    : 2,000

Fifty-eight events were being dropped before the panel ever saw them.
Silently, and always the OLDEST, because the query sorts newest first.
Nothing in the output said so: a stock whose only evidence fell off
the end simply had no chips, which looks exactly like a stock nothing
has happened to.

WHY THE STORE GREW PAST IT
--------------------------
The unique index on `events` includes the HEADLINE, so a parser
improvement writes a SECOND row rather than correcting the first. 389
stocks were carrying more than one version of the same event and 400
rows were older versions.

WHY THOSE ROWS WERE NOT COLLAPSED
---------------------------------
Three attempts were made and measured, and all three were rejected:

1. A bulk collapse tool. Its dry run offered to delete
   "INDIA-EU FTA WILL BE A GAME CHANGER" as a duplicate of a
   solar-power story, because market-wide events carry no symbol and
   its grouping key merged everything in the same second.

2. Making remember() UPDATE in place on
   (symbol, at, kind, source). tests/test_events_idempotent.py caught
   it in one run: "Deduplication that swallows real events is worse
   than the duplication it replaced."

3. Collapsing only same-source groups. Measured on the store: 286
   groups really are one story re-parsed, but 96 are DIFFERENT
   stories from one source in the same second. GOKULAGRO carries
   three separate tweets stamped 04:16:

       Gokul Agro Posts Q1FY27 Earnings with Revenue Crossing...
       Yatin Mota @yatinmota GOKUL AGRO up 6% post Q1 results...
       GOKUL AGRO RESOURCES Q1 EARNINGS REPORT CARD Metric...

   All three are real. Any of the three rules would have destroyed
   two of them.

THE FIX THAT IS SAFE
--------------------
Raise the cap and leave the rows alone. EVENT_WINDOW_HOURS is what
selects the window; the cap is a safety valve against a runaway store
and belongs far above the real volume, not just above it.

Reading a stale row costs milliseconds. Losing an event costs a trade.

Author : H&M Opportunity Trader
==========================================================
"""

import re

from core.shortlist import EVENT_ROW_CAP, EVENT_WINDOW_HOURS

SRC = open("core/shortlist.py", encoding="utf-8").read()


# ---------------------------------------------------------------
# 1. THE CAP IS ABOVE THE REAL VOLUME, WITH ROOM
# ---------------------------------------------------------------
def test_the_cap_clears_the_measured_volume_by_a_wide_margin():
    """2,058 rows in 96 hours on the day this was written. A cap set
    just above that is a cap that bites again next week."""
    assert EVENT_ROW_CAP >= 10 * 2058, (
        "the cap must be headroom, not a ceiling the store grows into")


def test_the_window_is_still_what_selects_the_events():
    """If the cap ever becomes the real filter, events start
    disappearing by age with nothing on screen to say so."""
    assert EVENT_WINDOW_HOURS == 96
    assert "hours=EVENT_WINDOW_HOURS" in SRC


def test_the_panel_asks_for_the_cap_not_a_bare_number():
    """The old 2000 was written inline, which is how it went unnoticed
    for as long as it did."""
    assert "limit=EVENT_ROW_CAP" in SRC
    assert "limit=2000" not in SRC


# ---------------------------------------------------------------
# 2. THE ROWS ARE NOT COLLAPSED, AND THE REASON IS RECORDED
# ---------------------------------------------------------------
def test_nothing_in_the_shortlist_deletes_an_event():
    """Three separate attempts to collapse duplicates were measured
    and rejected. If one ever lands, it lands somewhere it can be
    reviewed -- not quietly inside the panel builder."""
    assert not re.search(r"\bDELETE\s+FROM\b", SRC, re.I)


def test_the_event_store_does_not_replace_a_stored_headline():
    """The UPDATE that test_events_idempotent.py rejected. Kept out by
    a test rather than by memory."""
    events = open("core/stock_events.py", encoding="utf-8").read()
    body = events[events.index("def remember("):]
    body = body[:body.index("\n    def ", 10)]
    assert not re.search(r"\bUPDATE\s+events\b", body, re.I), (
        "remember() must INSERT only -- see the docstring for the two "
        "attempts that were reverted")


def test_the_newest_version_of_an_event_is_the_one_read():
    """What makes leaving the duplicates safe: with identical
    timestamps SQLite returns insertion order, so without `id DESC`
    the panel shows the OLDEST version of every corrected event."""
    events = open("core/stock_events.py", encoding="utf-8").read()
    assert events.count("ORDER BY at DESC, id DESC") >= 3
    assert "ORDER BY at DESC LIMIT" not in events
