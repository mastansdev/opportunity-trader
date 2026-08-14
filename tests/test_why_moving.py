"""
==========================================================
Both drawers get opened -- the SHILPAMED test
==========================================================

    "i brought the required sources to bot , & u couldn't do the
     proper work?"                  -- operator, 5 August 2026

WHAT WENT WRONG
---------------
Two stores hold "why is this stock moving":

    news_memory.db    written from newswire stories
    stock_events.db   written from the PRO channels

core/ranker.py read the first and had never once opened the second --
the one carrying the grades he pays for and says are the only source
he trusts.

SHILPAMED, 5 August, +12.63%, the best name of the day. All the ranker
could see was:

    reason: "matched on: SHILPAMED"    direction: UNKNOWN

which is the keyword matcher reporting its own work. It was refused
"reason is a lookup, not a mechanism" and never appeared. In the other
store, at 13:51 IST -- three minutes before the stock moved -- three
PRO channels had graded it GOOD.

41% of all reason rows in news_memory are that "matched on:" shape, so
this was never about one unlucky stock. Opening both stores made 100
more of the day's 949 moving stocks visible.

THE RULES LOCKED HERE
---------------------
1. A lookup is not a reason. "matched on: X" must be refused.
2. The PRO channels rank above the newswire.
3. TODAY only -- yesterday's result is not why it is moving now.
4. Nothing crosses symbols. "pls make sure these chips & related
   stocks are never mis matched as they are the one we trust."
5. A grade that points nowhere (MIXED, OK) is not a direction.

Author : H&M Opportunity Trader
==========================================================
"""

from core.why_moving import (NEGATIVE, POSITIVE, UNKNOWN, direction_of_grade,
                             from_events, from_news, is_a_real_reason, why)


# ---------------------------------------------------------------
# 1. A LOOKUP IS NOT A REASON
# ---------------------------------------------------------------
def test_the_matcher_naming_itself_is_not_a_reason():
    assert is_a_real_reason("matched on: SHILPAMED") is False
    assert is_a_real_reason("matched on: CRUDE, OIL") is False
    assert is_a_real_reason("Matched On: FEDERAL") is False


def test_a_fragment_too_short_to_contain_a_claim_is_refused():
    assert is_a_real_reason("up") is False
    assert is_a_real_reason("") is False
    assert is_a_real_reason(None) is False


def test_a_real_explanation_passes():
    assert is_a_real_reason(
        "PAT +51% vs est, OP +2% vs est, Sales -1% vs est") is True


def test_a_reason_that_merely_contains_the_words_is_not_refused():
    """The refusal is anchored at the START. A genuine sentence that
    happens to say 'matched' must survive."""
    assert is_a_real_reason(
        "Order win matched the guidance given at the last concall") is True


# ---------------------------------------------------------------
# 2. THE PRO CHANNELS RANK FIRST
# ---------------------------------------------------------------
SHILPAMED_EVENTS = [
    {"at": "2026-08-05T08:22:26+00:00", "kind": "RESULT", "grade": "GOOD",
     "source": "Earnings 360",
     "headline": "CLEAN | Rising, Expanding, Healthy -- #SHILPAMED Q1 FY27"},
    {"at": "2026-08-05T08:21:43+00:00", "kind": "RESULT", "grade": "GOOD",
     "source": "Earnings Pulse",
     "headline": "#SHILPAMED - Good Results - Shilpa Medicare"},
]
SHILPAMED_NEWS = [
    {"reason": "matched on: SHILPAMED", "direction": "UNKNOWN",
     "confidence": 0.5},
]


def test_the_day_it_was_missed():
    """The whole bug, in one assertion."""
    got = why(events=SHILPAMED_EVENTS, news_hits=SHILPAMED_NEWS,
              on_date="2026-08-05")
    assert got is not None, "SHILPAMED is invisible again"
    assert got["direction"] == POSITIVE
    assert "matched on" not in got["text"].lower()


def test_the_old_behaviour_would_still_fail():
    """Proof the test above is testing something. The newswire store
    alone has no usable answer for SHILPAMED."""
    assert from_news(SHILPAMED_NEWS) is None


def test_a_pro_grade_outranks_a_newswire_reason():
    news = [{"reason": "Some broker note repeated by a wire service",
             "direction": "POSITIVE", "confidence": 0.5}]
    got = why(events=SHILPAMED_EVENTS, news_hits=news, on_date="2026-08-05")
    assert got["source"].startswith("PRO channel")
    assert got["weight"] == 0.9


def test_an_explicit_ai_verdict_outranks_the_grade():
    """A verdict was written about THIS event. A grade is a category."""
    events = [{"at": "2026-08-05T08:00:00+00:00", "kind": "RESULT",
               "grade": "GOOD", "source": "Earnings Pro",
               "headline": "#X - Good Results",
               "ai_direction": "POSITIVE", "ai_confidence": 0.95,
               "ai_reason": "Margin expansion on a 51% PAT beat"}]
    got = from_events(events, on_date="2026-08-05")
    assert got["text"].startswith("Margin expansion")
    assert got["weight"] == 0.95


def test_the_newswire_is_used_when_the_channels_are_silent():
    news = [{"reason": "Better-than-expected quarterly earnings signal "
                       "stronger margins", "direction": "POSITIVE",
             "confidence": 0.75}]
    got = why(events=[], news_hits=news, on_date="2026-08-05")
    assert got["source"] == "news"
    assert got["direction"] == POSITIVE


def test_no_answer_anywhere_is_still_no_answer():
    """"without any thing stock doesn't move" -- silence must stay
    silence, not become a weak yes."""
    assert why(events=[], news_hits=[], on_date="2026-08-05") is None
    assert why(events=None, news_hits=None) is None


# ---------------------------------------------------------------
# 3. TODAY ONLY
# ---------------------------------------------------------------
def test_yesterdays_result_is_not_why_it_is_moving_today():
    stale = [{"at": "2026-08-04T08:21:43+00:00", "kind": "RESULT",
              "grade": "GOOD", "source": "Earnings Pulse",
              "headline": "#X - Good Results, a whole day ago"}]
    assert from_events(stale, on_date="2026-08-05") is None


def test_without_a_date_the_newest_graded_event_wins():
    """For the stock card, where 'what happened to this company' is the
    question rather than 'why is it moving right now'."""
    stale = [{"at": "2026-08-04T08:21:43+00:00", "kind": "RESULT",
              "grade": "GOOD", "source": "Earnings Pulse",
              "headline": "#X - Good Results, a whole day ago"}]
    assert from_events(stale) is not None


# ---------------------------------------------------------------
# 4. A GRADE THAT POINTS NOWHERE IS NOT A DIRECTION
# ---------------------------------------------------------------
def test_the_grades_that_carry_a_direction():
    for grade in ("EXCELLENT", "GREAT", "GOOD"):
        assert direction_of_grade(grade) == POSITIVE
    for grade in ("WEAK", "POOR"):
        assert direction_of_grade(grade) == NEGATIVE


def test_mixed_and_ok_are_not_a_direction():
    """core/ranker.py refuses a reason that contradicts the move. A
    grade pointing nowhere must not be dressed up as one that does."""
    for grade in ("MIXED", "OK", "", None, "banana"):
        assert direction_of_grade(grade) == UNKNOWN


def test_an_ungraded_news_event_is_kept_but_never_given_a_direction():
    """---- CHANGED DELIBERATELY. 8 August 2026. ----

    This used to assert None: an event with no grade was dropped.
    That rule was written for result cards, where a grade always
    exists, and it silently discarded EVERY company news item.

        "decngold has news"                      -- operator

    DECNGOLD moved +8.87% on 6 August. The bot had the reason stored
    and correctly tagged -- "DECCAN GOLD: CO. PRODUCES FIRST GOLD DORE
    AT ALTYN TOR PROJECT IN KYRGYZSTAN" -- and threw it away here.
    News is an entry reason in his rules:

        "NEWS = ONLY POSITIVE NEWS WHICH WILL GIVE SOME POINTS TO
         GRAB & EXIT"

    So news is now kept. What has NOT changed is the guard this test
    was really protecting: the direction is never guessed from a
    headline. It stays UNKNOWN, and core/ranker.py still refuses a
    reason that contradicts the move.

    The weight is deliberately below a graded result's 0.9 -- a
    headline is weaker evidence than a channel's verdict."""
    events = [{"at": "2026-08-05T09:00:00+00:00", "kind": "NEWS",
               "grade": None, "source": "News Pulse", "symbol": "TESTCO",
               "headline": "Company issues a routine clarification"}]
    got = from_events(events, on_date="2026-08-05")
    assert got is not None, "news is an entry reason and was dropped"
    assert got["direction"] == "UNKNOWN", (
        "a direction was invented from a headline")
    assert got["weight"] < 0.9, "news outranked a graded result"


def test_a_scanner_listing_is_still_not_a_reason():
    """The regression the news change caused, and its fix.

    Breakouts posts a directory entry, not a story:
        "#NAVINFLUOR.NS NAVINFLUOR.NS Navin Fluorine Inte, NSE,
         Large-cap 39037 cr, Basic Materials- Chemicals"

    Long enough to look like a headline, and it says only that the
    stock exists. It replaced NAVINFLUOR's real result card until
    scanner sources were excluded."""
    events = [{"at": "2026-08-05T09:00:00+00:00", "kind": "NEWS",
               "grade": None, "source": "Breakouts", "symbol": "NAVINFLUOR",
               "headline": "#NAVINFLUOR.NS NAVINFLUOR.NS Navin Fluorine "
                           "Inte, NSE, Large-cap 39037 cr"}]
    assert from_events(events, on_date="2026-08-05") is None


# ---------------------------------------------------------------
# 5. NOTHING CROSSES SYMBOLS OR SCOPES
# ---------------------------------------------------------------
def test_a_market_wide_event_is_never_attached_to_one_stock():
    """     "so pls do not miss or club one data to other stock"

    MACRO and MARKET_ANSWER are about the market. Quoting one as the
    reason a single stock is moving is exactly that mistake."""
    for kind in ("MACRO", "MARKET_ANSWER", "FLOW"):
        events = [{"at": "2026-08-05T09:00:00+00:00", "kind": kind,
                   "grade": "GOOD", "source": "News Pulse",
                   "headline": "Nifty rallies on softer US inflation print"}]
        assert from_events(events, on_date="2026-08-05") is None, kind


def test_a_graded_event_with_no_headline_gives_nothing():
    """The grade is the claim; the headline carries the detail. With no
    detail there is nothing to show him beside the stock."""
    events = [{"at": "2026-08-05T09:00:00+00:00", "kind": "RESULT",
               "grade": "GOOD", "source": "Earnings Pulse", "headline": ""}]
    assert from_events(events, on_date="2026-08-05") is None


# ---------------------------------------------------------------
# 6. THE SHAPE THE RANKER ALREADY READS
# ---------------------------------------------------------------
def test_it_returns_exactly_what_mechanism_of_promises():
    """core/ranker.py reads .text / .weight / .direction. A new field
    name here would be a silent no-op."""
    got = why(events=SHILPAMED_EVENTS, news_hits=[], on_date="2026-08-05")
    assert set(got) >= {"text", "weight", "direction"}
    assert isinstance(got["text"], str) and got["text"]
    assert isinstance(got["weight"], float)
    assert got["direction"] in (POSITIVE, NEGATIVE, UNKNOWN)


def test_the_text_clears_the_rankers_own_lookup_gate():
    """Whatever comes back must survive the gate that killed SHILPAMED,
    or this fix moved the failure instead of removing it."""
    from core.ranker import NOT_A_REASON
    got = why(events=SHILPAMED_EVENTS, news_hits=SHILPAMED_NEWS,
              on_date="2026-08-05")
    low = got["text"].lower()
    assert not any(bad in low for bad in NOT_A_REASON)
    assert len(got["text"]) >= 15


def test_junk_rows_do_not_crash_it():
    """These stores are written by scrapers and OCR."""
    for junk in ([None], ["a string"], [{}], [{"kind": "RESULT"}], 0, ""):
        assert why(events=junk, news_hits=junk) is None


# ---------------------------------------------------------------
# 7. THE DASHBOARD REALLY CALLS IT
# ---------------------------------------------------------------
def test_the_ranking_path_actually_uses_this():
    """A module nothing imports is what the last four hours were
    about."""
    import inspect

    from dashboard.state import DashboardState
    code = inspect.getsource(DashboardState._mechanism_for)
    assert "why_moving" in code
    assert "stock_events" in code, "it must open the PRO channel store"
    assert "news_impact" in code, "the newswire store is still a source"
