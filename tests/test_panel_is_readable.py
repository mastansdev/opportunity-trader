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
def test_the_blocked_list_is_grouped_by_reason():
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"blocked_by_reason": grouped' in src
    assert '"blocked_count": len(blocked)' in src


def test_the_full_blocked_list_is_still_in_the_snapshot():
    """tools/refused_review.py reads it, and "which stocks did the bot
    refuse today" is a question worth being able to ask."""
    src = open("dashboard/state.py", encoding="utf-8").read()
    assert '"blocked_symbols": blocked' in src


def test_the_panel_draws_the_grouped_version():
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    # byReason is assigned a few lines ABOVE the innerHTML, so the
    # slice starts at the comment block that introduces it.
    block = src[src.find("const byReason = risk.blocked_by_reason"):]
    block = block[:block.find('document.getElementById("frozenSymbols")')]
    assert "blocked_by_reason" in block
    assert "g.count" in block
    assert "g.symbols.join" in block, "the names must be on the hover"


def test_the_grouped_view_falls_back_rather_than_going_blank():
    """An older snapshot has no blocked_by_reason. Showing nothing
    would look like nothing was blocked, which is a different fact."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find('document.getElementById("blockedSymbols")'):]
    block = block[:block.find('document.getElementById("frozenSymbols")')]
    assert "risk.blocked_symbols.length" in block


# ---------------------------------------------------------------
# 3. A DASH IS NOT A NUMBER
# ---------------------------------------------------------------
def test_a_card_with_no_value_is_not_drawn():
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find("const known = cards.filter"):]
    block = block[:block.find("// -- breadth --")]
    assert 'c.value !== "—"' in block
    assert "hidden" in block


def test_a_zero_is_a_number_and_stays():
    """"Open Positions: 0" is a fact worth reading. Only an ABSENT
    value is hidden, and a filter on truthiness would have hidden the
    zero too."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find("const known = cards.filter"):]
    block = block[:block.find("// -- breadth --")]
    assert "c.value !== undefined" in block
    assert "!c.value" not in block, (
        "a truthiness test would hide a legitimate zero")


def test_the_hidden_count_is_shown_rather_than_the_cards_vanishing():
    """Four cards where there were nine would look like a broken
    panel."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "not available" in src
    assert "${hidden} more" in src


def test_the_market_tiles_use_the_explicit_na_marker():
    """mktCell() sets class "na" on every tile with no reading.
    Matching the em dash instead would break the day somebody changes
    the placeholder character."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert '_blank = (html) => /class="mkt-cell na"/.test(html)' in src
    assert 'class="mc-label">([^<]*)<' in src, (
        "the label regex must match the class mktCell actually emits")


def test_the_silent_tiles_are_named_not_deleted():
    """Four silent tiles reading "needs index feed" look like a quiet
    market. Naming them keeps it obvious the security ids are wrong --
    the same point the index_missing note already makes."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find("const live = cells.filter"):]
    block = block[:block.find("mktRegimeBadge")]
    assert "quiet.join" in block
    assert "no reading" in block


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

def test_the_watchlist_has_a_panel():
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert 'id="watchBox"' in src
    assert 'panel("watchlist"' in src


def test_the_panel_reads_the_key_the_snapshot_actually_uses():
    """dashboard/state.py hangs it off results_today. Reading
    snap.watchlist would find nothing and fail silently."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "(snap.results_today || {}).watchlist" in src
    state = open("dashboard/state.py", encoding="utf-8").read()
    assert '"watchlist": watch' in state


def test_during_and_after_are_separate_columns():
    """The only part that changes what you do. Merging them is what
    the old results panel did."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find('panel("watchlist"'):]
    block = block[:block.find('panel("alerts"')]
    assert "today.DURING" in block and "today.AFTER" in block
    assert "moves while you are watching" in block
    assert "moves at tomorrow's open" in block


def test_the_unpriced_column_comes_first():
    """It is the one you can still be early to."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find('box.innerHTML = `<div class="wl-grid">'):]
    block = block[:block.find("</div>`;")]
    assert block.find("Unpriced") < block.find("Reports today")


def test_a_name_carries_its_call():
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find('panel("watchlist"'):]
    block = block[:block.find('panel("alerts"')]
    for cls in ("chain-BUY", "chain-AVOID", "chain-WAIT"):
        assert cls in block


def test_an_empty_watchlist_says_what_to_run():
    """"nothing on the calendar" and "you have not fetched yet" are
    different facts, and the operator cannot tell them apart without
    being told."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find('panel("watchlist"'):]
    block = block[:block.find('panel("alerts"')]
    assert "telegram_catchup.py --apply" in block


def test_a_broken_watchlist_cannot_take_the_page_down():
    """Every panel is wrapped -- one failing render must not stop the
    rest of the dashboard drawing."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert "function panel(name, fn)" in src
    assert 'panel("watchlist", () => {' in src


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

def test_a_chip_cannot_be_wider_than_the_column():
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    block = src[src.find(".sl-chip {"):]
    block = block[:block.find(".sl-news")]
    assert "max-width" in block
    assert "text-overflow: ellipsis" in block


def test_the_call_itself_is_never_clipped():
    """Three letters. Ellipsising BUY into "BU…" would be worse than
    the scrollbar."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    assert ".sl-chain { max-width: none; }" in src


def test_the_clipped_text_is_kept_on_the_hover():
    """The standing rule is that nothing is thrown away. An ellipsis
    that loses the sentence would be exactly that."""
    src = open("dashboard/static/index.html", encoding="utf-8").read()
    chip = src[src.find("function chipHtml"):]
    chip = chip[:chip.find("function whyChips")]
    assert chip.count('title="${escapeHtml(w)}"') == 2, (
        "both the trusted-chip return and the general return must "
        "carry the full text on the hover")
