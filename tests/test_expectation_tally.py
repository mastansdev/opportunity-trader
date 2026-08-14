"""
==========================================================
Growth is not the question. Was it ENOUGH?
==========================================================

APTUS, 31 July 2026:

    our arithmetic   STRONG: sales +15% YoY, PAT +19% YoY
    the market       -5.77%

Both are facts, and the second one is the one his money cared about.
Growth was real and it was not what the quarter was about -- the
provisions doubled. core/quarterly_results.py cannot see that, and no
amount of work on it ever will: it computes growth, and growth is not
the question a share price is asking.

WHAT THIS READS
---------------
Earnings Pro cards carry the question, answered, per metric:

    Tally Against Expectations
    THEME              STATUS   DETAILS
    Revenue            MET      within the expected 51,400-52,600 cr
    Net Profit (PAT)   MET      meeting the 3,345-3,791 cr expectation
    EBITDA Margin      MISS     8.2% vs the expected 9.8% to 10.4%

MARUTI is the APTUS shape said out loud: two metrics landed, one did
not, verdict MIXED. A grader reading only revenue and profit would
have called that quarter fine.

    "EARNINGS PRO (very important =they will provide all in detail of
     concall, guidance, market expectations in a single readable page)"
                                    -- operator, 1 August 2026

He was right about which channel mattered. It had been arriving and
being read by nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import (
    classify, expectation_tally, grade_of, tally_summary)

# Verbatim from the MARUTI Q1 FY27 card, OCR mangling included.
MARUTI = """MARUTI
Ql FY27
Algo Pulse: Weak | Verdict: MIXED
Revenue and PAT meet expectations, but EBITDA margins disappoint
Tally Against Expectations
THEME STATUS DETAILS
Consolidated Revenue from Operations was 52,460.8
Revenue MET crore (+35.9% YoY), perfectly within the expected
51,400-52,600 crore range.
Consolidated PAT stood at 3,446.9 crore (-9.1% YoY),
Net Profit (PAT) MET meeting the 3,345-3,791 crore expectation.
Calculated EBITDA margin came in lower at 8.2% vs the
EBITDA Margin MISS expected 9.8% to 10.4%, reflecting cost pressures.
"""


# ---------------------------------------------------------------
# 1. THE TALLY
# ---------------------------------------------------------------
def test_each_metric_is_read_with_its_status():
    got = expectation_tally(MARUTI)
    assert got == {"Revenue": "MET",
                   "Net Profit (PAT)": "MET",
                   "EBITDA Margin": "MISS"}


def test_the_summary_names_what_missed():
    """"One metric missed" is useless. "MISS EBITDA Margin" is the
    whole story, and it fits in a chip."""
    assert tally_summary(MARUTI) == "2 met | MISS EBITDA Margin"


def test_a_beat_is_named_too():
    text = MARUTI.replace("EBITDA Margin MISS", "EBITDA Margin BEAT")
    assert "BEAT EBITDA Margin" in tally_summary(text)


def test_a_message_with_no_tally_yields_nothing():
    """Most messages are not cards. Returning {} rather than guessing
    is the same rule the rest of this file follows."""
    assert expectation_tally("#GAIL - Excellent Results") == {}
    assert tally_summary("Reliance bags Rs 2,205 crore order") is None


def test_prose_that_merely_contains_MET_is_not_a_tally_row():
    """Without the theme filter this would read any sentence whose
    last capitalised word happens to sit before MET."""
    text = ("Tally Against Expectations\n"
            "The Board MET on Thursday to approve the results.\n"
            "The Chairman MET analysts afterwards.\n")
    assert expectation_tally(text) == {}


# ---------------------------------------------------------------
# 2. THE VERDICT WORDS THIS CHANNEL USES
# ---------------------------------------------------------------
def test_mixed_is_graded():
    """MARUTI's card produced grade=None until 1 August. MIXED is the
    honest answer when some metrics land and others do not -- which is
    most quarters."""
    assert grade_of(MARUTI) == "MIXED"


def test_met_is_not_a_beat():
    """"Exactly as expected" is neither good news nor bad, and calling
    it GOOD would put a green chip on a quarter that did nothing."""
    assert grade_of("Verdict: MET") == "OK"


def test_algo_pulse_still_does_not_set_the_grade():
    """MARUTI's card says "Algo Pulse: Weak | Verdict: MIXED". The
    first version of the beat parser read the wrong column and graded
    a blowout quarter as WEAK."""
    assert grade_of(MARUTI) == "MIXED", "Algo Pulse is not the verdict"


# ---------------------------------------------------------------
# 3. IT REACHES THE EVENT
# ---------------------------------------------------------------
class Matcher:
    def symbols_in(self, text):
        return ["MARUTI"] if "MARUTI" in (text or "").upper() else []

    def names_in(self, text):
        return []


def test_the_tally_leads_the_headline():
    """The chip shows about 80 characters. "MISS EBITDA Margin" is the
    reason a stock falls on a quarter that grew; the raw first line of
    the card is not."""
    from core.stock_events import events_from_message
    events = events_from_message(Matcher(), ocr_text=MARUTI,
                                 at="2026-07-31T10:00", channel="Earnings Pro")
    assert events, "the card must produce an event"
    assert events[0]["headline"].startswith("2 met | MISS EBITDA Margin")
    assert events[0]["kind"] == "RESULT"
    assert events[0]["grade"] == "MIXED"


def test_the_tally_outranks_the_estimate_grid():
    """A card can carry both. The tally answers "was it enough", the
    grid answers "by how much" -- and only one of those fits in a
    chip alongside the company name."""
    from core.stock_events import events_from_message
    both = MARUTI + (
        "\nMetric QoQ YoY Jun'26 Est AEst Mar'26 Jun'25\n"
        "Sales 16% 17% 41350.2 37688.3 +10% 35,706 35,429\n")
    events = events_from_message(Matcher(), ocr_text=both,
                                 at="2026-07-31T10:00", channel="Earnings Pro")
    assert events[0]["headline"].startswith("2 met | MISS")
