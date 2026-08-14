"""
==========================================================
Two questions from one screenshot
==========================================================

    "why divis, SHADOWFAX, AETHER, YASHO are not showing EXCEPTIONAL?
     in watchlist & why this Reports today is not showing stocks?"
                                    -- operator, 2 August 2026

Two separate faults, both found by measuring the live store rather
than reading the code and guessing.


1. THE TIER WAS BUILT AND NEVER DRAWN
-------------------------------------
All four names were in stock_events.db, all four EXCEPTIONAL, filed
by tools/load_canslim.py the same night:

    AETHER  DIVISLAB  SHADOWFAX  YASHO   -- 4 of 90

core/reporting.watchlist() carried the symbol and the call and
nothing else, so the tier reached the gainers table as a collapsed
why-chip and reached the watchlist not at all.

FOURTH TIME. `support` on 31 July, `chain` and the watchlist itself
on 2 August, now the tier. Every one of them built, tested, and
invisible.

Three of the four are additionally not IN the results watchlist, and
that part is correct: AETHER, SHADOWFAX and YASHO all reported DURING
Friday's session, so the market has answered them. DIVISLAB reported
after the close and is on the unpriced list, which is where the tier
now shows.


2. THE CARD DOES NOT ALWAYS CARRY THE SPLIT
-------------------------------------------
core/recap_card.py's docstring said all three During/After cards
carry the columns. Counted on every such card in the store:

    RECAP      6 cards    6 with the split
    TODAY     12 cards    3 with the split
    TOMORROW   7 cards    2 with the split

On a busy day the card is a two-column table. On 2 August it named
two companies and printed no columns at all -- so rows_from_card()
refused it whole and "Reports today" showed nothing while the card
sat in the store saying PERSISTENT.

Ten of nineteen forward cards were being dropped. Re-reading the raw
store recovered them; the raw store is why that was possible.

    "do not throw away any information we are receiving"

The refusal is KEPT for the recap, where the split decides whether
the market has already priced the result. Calling a DURING company
"not yet priced" would push the operator into a finished move.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.canslim import TIERS, stored_tiers
from core.recap_card import (AFTER, DURING, RECAP, TODAY, TOMORROW, UNKNOWN,
                             headline_for, rows_from_card)
from core.reporting import counts, watchlist
from core.watchlist import from_results

KNOWN = {"PERSISTENT", "BIRLACABLE", "DIVISLAB", "AETHER", "YASHO",
         "SHADOWFAX", "CORONA", "MARUTI"}

# The real 2 August card, as it is stored. No columns anywhere on it.
FLAT_CARD = (
    "\U0001F4C5 Today Earnings - 02 Aug, 2026\n"
    "Key companies reporting results: #PERSISTENT #BIRLACABLE\n"
    "@earnings_pulse\nTODAY\nEARNINGS\n"
    "02 Aug, 2026 - 2 Companies\nPERSISTENT BIRLACABLE\nxX @market_pulse_ai")

SPLIT_CARD = (
    "EARNINGS PULSE RECAP\n31 Jul, 2026\n"
    "During Market\n@ AETHER @ YASHO\n"
    "After Market\n@ DIVISLAB @ CORONA")


# ---------------------------------------------------------------
# 1. THE FORWARD CARD WITH NO COLUMNS IS NOT THROWN AWAY
# ---------------------------------------------------------------
def test_a_forward_card_without_columns_still_names_its_companies():
    got = rows_from_card(FLAT_CARD, known=KNOWN)
    assert {r["symbol"] for r in got} == {"PERSISTENT", "BIRLACABLE"}
    assert {r["when"] for r in got} == {UNKNOWN}


def test_the_headline_says_the_card_did_not_say():
    """It must not read DURING. DURING is the side that puts a stock on
    screen at 09:15, and inventing it is inventing the one fact we do
    not have."""
    line = headline_for({"symbol": "PERSISTENT", "when": UNKNOWN},
                        kind=TODAY)
    assert "did not say during or after" in line
    assert "DURING THE SESSION" not in line
    assert line.startswith("REPORTS")


def test_a_recap_without_columns_is_still_refused():
    """THE HALF THAT MUST NOT CHANGE. On the recap the split decides
    whether the market has already priced the result. A DURING company
    called "not yet priced" walks the operator into a finished move."""
    flat_recap = "EARNINGS PULSE RECAP\n31 Jul, 2026\n@ AETHER @ YASHO"
    assert rows_from_card(flat_recap, known=KNOWN) == []


def test_the_split_card_still_splits():
    got = {r["symbol"]: r["when"] for r in rows_from_card(SPLIT_CARD,
                                                          known=KNOWN)}
    assert got == {"AETHER": DURING, "YASHO": DURING,
                   "DIVISLAB": AFTER, "CORONA": AFTER}


def test_the_master_still_gates_every_ticker():
    """The mismatch rule. OCR turns BAJAJFINSV into BAJAJFINSY, and a
    fragment is indistinguishable from a symbol once it is stored."""
    assert rows_from_card(FLAT_CARD, known=None) == []
    assert rows_from_card(FLAT_CARD, known=set()) == []
    only = rows_from_card(FLAT_CARD, known={"PERSISTENT"})
    assert [r["symbol"] for r in only] == ["PERSISTENT"]


def test_a_string_date_from_sqlite_does_not_crash_the_backfill():
    """tools/build_stock_events.py reads `at` straight out of SQLite, so
    the fallback arrives as a string. It went unnoticed while these
    cards returned no rows; the moment they returned rows the backfill
    died on .strftime. Third time a stored datetime has come back as a
    string in this project."""
    from core.recap_card import recap_date
    assert recap_date("no date here", "2026-08-02T02:30:10+00:00").day == 2
    assert recap_date("no date here", "2026-08-02").month == 8
    assert recap_date("no date here", "not a date at all") is None


# ---------------------------------------------------------------
# 2. THE UNSTATED SIDE REACHES THE PANEL
# ---------------------------------------------------------------
@pytest.fixture
def db(tmp_path):
    path = tmp_path / "events.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (symbol TEXT, kind TEXT, headline TEXT)")
    conn.executemany(
        "INSERT INTO events VALUES (?, 'REPORTED', ?)",
        [("PERSISTENT",
          "REPORTS (03 Aug) -- the card did not say during or after "
          "the close"),
         ("MARUTI", "REPORTS DURING THE SESSION (03 Aug) -- live today"),
         ("DIVISLAB",
          "REPORTED AFTER CLOSE (31 Jul) -- not yet priced by the market")])
    conn.commit()
    conn.close()
    return str(path)


def test_an_unstated_company_is_kept_in_its_own_bucket(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3))
    today = view["reporting_today"]
    assert [r["symbol"] for r in today[UNKNOWN]] == ["PERSISTENT"]
    assert [r["symbol"] for r in today[DURING]] == ["MARUTI"]
    assert counts(view)["today_unstated"] == 1


def test_the_unstated_bucket_survives_into_the_catalyst_list(db):
    from datetime import date
    view = watchlist(events_db=db, on=date(2026, 8, 3))
    rows = {r["symbol"]: r for r in from_results(view)}
    assert "PERSISTENT" in rows, "dropped between reporting and watchlist"
    assert "did not say when" in rows["PERSISTENT"]["detail"]


# ---------------------------------------------------------------
# 3. THE TIER TRAVELS
# ---------------------------------------------------------------
def test_the_tier_reaches_every_watchlist_row(db):
    from datetime import date
    tiers = {"DIVISLAB": "EXCEPTIONAL", "MARUTI": "WEAK"}
    view = watchlist(events_db=db, on=date(2026, 8, 3), tiers=tiers)
    assert view["unpriced_from_last_close"][0]["tier"] == "EXCEPTIONAL"
    assert view["reporting_today"][DURING][0]["tier"] == "WEAK"
    # and out the far end, on the catalyst list the panel draws
    rows = {r["symbol"]: r for r in from_results(view)}
    assert rows["DIVISLAB"]["tier"] == "EXCEPTIONAL"
    assert rows["PERSISTENT"]["tier"] is None, \
        "a name with no tier is a blank, never a guess"


def test_stored_tiers_reads_the_newest_load():
    """load_canslim files a fresh row every night and the tier can
    change between them. Reading an older one shows a tier the
    operator's own export no longer says."""
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE events (symbol TEXT, at TEXT, kind TEXT, "
                 "source TEXT, headline TEXT)")
    conn.executemany("INSERT INTO events VALUES (?,?,'SETUP','CANSLIM',?)", [
        ("AETHER", "2026-08-01T23:00", "CANSLIM WEAK -- 30 of 90 (01 Aug)"),
        ("AETHER", "2026-08-02T23:00",
         "CANSLIM EXCEPTIONAL -- 4 of 90 today (02 Aug)")])
    conn.commit()
    conn.close()
    try:
        assert stored_tiers(path) == {"AETHER": "EXCEPTIONAL"}
    finally:
        os.unlink(path)


def test_stored_tiers_never_raises_on_a_missing_store(tmp_path):
    # Not under data/: sqlite3.connect() creates the file it is given,
    # and this left an empty data/there-is-no-such-file.db behind.
    assert stored_tiers(str(tmp_path / "no-such-store.db")) == {}


# ---------------------------------------------------------------
# 4. THE PANEL DRAWS IT
# ---------------------------------------------------------------
def test_the_panel_draws_the_tier_chip():
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("const TIER_CLS"):]
    block = block[:block.find("const col =")]
    for tier in TIERS:
        assert tier in block, f"{tier} has no colour on the watchlist"
    assert "r.tier" in block


def test_weak_is_not_drawn_as_a_warning():
    """Their own guide: the tier counts how many of three frameworks
    AGREE. WEAK means they disagree, not that the company is bad, and
    a red chip would read as the opposite."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find("const TIER_CLS"):]
    block = block[:block.find("};", block.find("const TIER_CLS"))]
    assert "WEAK:\"sl-down\"" not in block.replace(" ", "")
    assert "EXCEPTIONAL:\"sl-up\"" in block.replace(" ", "")


def test_the_unstated_names_are_marked_on_the_panel():
    """They are shown in the DURING column because an unknown time must
    be on screen from the open -- and marked, because the card never
    said."""
    page = open("dashboard/static/index.html", encoding="utf-8").read()
    block = page[page.find('panel("watchlist"'):]
    block = block[:block.find('panel("alerts"')]
    assert "unstated(today.UNKNOWN)" in block
    assert "unstated(tomorrow.UNKNOWN)" in block
    assert "r.unstated" in block


def test_the_state_layer_feeds_the_tiers_in():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert "from core.canslim import stored_tiers as canslim_tiers" in src
    assert "reporting_watchlist(calls=calls, tiers=tiers)" in src
    block = src[src.find("tiers = canslim_tiers()"):]
    block = block[:block.find("watch = reporting_watchlist")]
    assert "except Exception" in block, \
        "a missing CANSLIM load must not take the watchlist with it"
