"""
==========================================================
What was priced in, before the result
==========================================================

    "None of it knows what the market already expected? we have
     covered by one of our pro channel right? every thing in one page"
                                    -- operator, 1 August 2026

He was right, and it had been arriving for days. Earnings Pro
publishes a Pre-Earnings Market Expectations page before each session:

    CLEAN BULLISH
    Steady volume growth in high-margin HALS and backward integration
    support mid-single digit profit expansion.
    - Q1 FY27 Revenue estimated at ~264 cr (+8.5% YoY), PAT at ~74 cr

    APLAPOLLO NEUTRAL
    Volume contraction tests full-year growth guidance.

    AMJLAND BEARISH
    Market sentiment remains weak with a 'Sell' rating.

A stance, the reasoning and often the consensus figure -- per stock,
BEFORE the numbers land.

WHY IT MATTERS
--------------
Measured on the 151 graded results held that day, the grade pointed
the WRONG WAY one time in five: UEL weak and +7.3%, DHANBANK great and
-6.3%. Without the hurdle, a weak quarter and a weak quarter everybody
already feared are indistinguishable.

WHY IT WAS BEING THROWN AWAY
----------------------------
is_digest() drops any message naming three or more tickers, because a
news recap pairs the wrong number with the wrong company. Correct for
a recap, exactly wrong for a TABLE where every stock carries its own
verdict on its own lines.

23 expectations across three pages, discarded.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import (
    events_from_message, expectations_from_page, is_digest,
    is_expectation_page)

# Verbatim from the page, OCR damage included -- the real one splits
# CLEAN into "CL EAN".
PAGE = """earningspulse.ai
01 Aug 2026 - Q1FY27 - Page 1 of 3
Pre-Earnings Market Expectations
35 expected results - 23 with expectation coverage - STAGE preview
AMJLAND BEARISH
Market sentiment remains weak with a 'Sell' rating
amid lack of specific forward guidance.
e No formal guidance
01 Aug 2026
CL EAN BULLISH
Steady volume growth in high-margin HALS and
backward integration support mid-single digit profit expansion.
@ Qi FY27 Revenue estimated at ~ 264 cr (+8.5% YoY), PAT at ~ 74 cr
01 Aug 2026
APLAPOLLO NEUTRAL
Volume contraction tests full-year growth guidance, though
structural steel leadership provides downside support.
01 Aug 2026
"""


class Matcher:
    def symbols_in(self, text):
        return []

    def names_in(self, text):
        return []


# ---------------------------------------------------------------
# 1. THE TABLE IS READ
# ---------------------------------------------------------------
def test_the_page_is_recognised():
    assert is_expectation_page(PAGE) is True


def test_every_stock_gets_its_own_stance():
    got = {e["symbol"]: e["stance"] for e in expectations_from_page(PAGE)}
    assert got == {"AMJLAND": "BEARISH", "CLEAN": "BULLISH",
                   "APLAPOLLO": "NEUTRAL"}


def test_a_ticker_split_by_ocr_is_repaired():
    """The real page reads "CL EAN BULLISH". Dropping that row would
    lose the stock most in need of the entry."""
    assert any(e["symbol"] == "CLEAN"
               for e in expectations_from_page(PAGE))


def test_the_reasoning_is_kept():
    """The stance alone says little. "Volume contraction tests
    full-year growth guidance" is the part the operator reads."""
    got = {e["symbol"]: e["note"] for e in expectations_from_page(PAGE)}
    assert "Volume contraction" in got["APLAPOLLO"]
    assert "264 cr" in got["CLEAN"], "the consensus figure must survive"


def test_the_repeated_date_stamp_is_not_reasoning():
    got = {e["symbol"]: e["note"] for e in expectations_from_page(PAGE)}
    assert not got["AMJLAND"].endswith("01 Aug 2026")


# ---------------------------------------------------------------
# 2. IT MUST NOT BE MISTAKEN FOR A DIGEST
# ---------------------------------------------------------------
def test_the_page_would_otherwise_be_dropped_as_a_digest():
    """The rule that was discarding it. Kept as evidence that the
    expectation check has to come FIRST, not as a suggestion that
    is_digest is wrong -- it is right about recaps."""
    many = PAGE + "#AAA #BBB #CCC\n"
    assert is_digest(many) is True


def test_the_expectation_check_runs_before_the_digest_check():
    events = events_from_message(Matcher(), ocr_text=PAGE,
                                 at="2026-08-01T03:00", channel="Earnings Pro")
    assert len(events) == 3, "a table is not a digest"
    assert all(e["kind"] == "EXPECTATION" for e in events)


def test_an_ordinary_recap_is_still_dropped():
    """The guard must not be loosened for everything with tickers in
    it. A recap really does pair the wrong number with the wrong
    company."""
    recap = ("Daily Highlights\n"
             "#AAA wins an order\n#BBB reports results\n#CCC falls 5%\n")
    assert events_from_message(Matcher(), text=recap,
                               at="2026-08-01T03:00", channel="x") == []


# ---------------------------------------------------------------
# 3. SHOWN, NOT SCORED
# ---------------------------------------------------------------
def test_an_expectation_scores_nothing():
    """A BULLISH expectation that then MISSES is a sell. Scoring the
    expectation positive would have the sign backwards half the
    time -- it is context for reading the result, not evidence about
    the stock."""
    from core.shortlist import ShortlistBuilder

    class Events:
        def __init__(self, rows):
            self.rows = rows

        def recent(self, limit=None, hours=None, scope=None):
            return self.rows

    def rank_with(rows):
        builder = ShortlistBuilder(stock_events=Events(rows))
        return builder.rank([{"symbol": "CLEAN", "ltp": 100.0,
                              "change_pct": 3.0, "sector": "Chemicals"}],
                            top=5, today="2026-08-01")["rows"][0]

    # CLEAN is a real stock, so other chips -- a results date, a
    # corporate action -- contribute on their own. Comparing WITH
    # against WITHOUT isolates what the expectation itself is worth,
    # which is the only number this test is about.
    without = rank_with([])
    with_it = rank_with([{"symbol": "CLEAN", "kind": "EXPECTATION",
                          "at": "2026-08-01T03:00",
                          "headline": "EXPECTED BULLISH: steady volume"}])
    assert any("EXPECTED BULLISH" in w for w in with_it["why"])
    assert with_it["support"] == without["support"], (
        "an expectation is context, not evidence")
    assert with_it["score"] == without["score"], (
        "a BULLISH expectation that then MISSES is a sell -- scoring it "
        "positive would have the sign backwards half the time")
