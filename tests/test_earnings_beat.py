"""
==========================================================
The FinAI card -- the one thing that knows what was EXPECTED
==========================================================

31 July 2026. GAIL reported. Earnings Pulse posted about it four times
in sixteen minutes and the bot scored one of them:

    08:41  #GAIL - Excellent Results        RESULT  EXCELLENT   scored
    08:52  #GAIL - Excellent Results        RESULT  EXCELLENT   scored
    08:54  #GAIL - Strong Beat  + card      NEWS    (none)      IGNORED
    08:57  CNBC: Net Profit 4,292 Cr        NEWS    (none)      IGNORED

The one that was ignored was the best one. Its grid carries the
ANALYST ESTIMATE beside the reported figure:

    Metric  QoQ   YoY  Jun'26    Est      dEst
    Sales   16%   17%  41350.2   37688.3  +10%
    OP     388%   93%   7097.9    2287.7  +210%
    PAT    215%   96%   4671.0    1543.9  +203%

core/quarterly_results.py compares this quarter to the last one. It
can say PAT went from 1,482 to 4,671 crore. It cannot say the street
expected 1,543 -- and "tripled" versus "tripled when nobody saw it
coming" are not the same trade.

THE TRAP THIS FILE EXISTS TO HOLD SHUT
--------------------------------------
The card carries TWO ratings side by side and they are about different
things:

    Algo Pulse: Weak  |  Verdict: BEAT

Algo Pulse is a price read. Verdict is the quarter. The first version
of this parser matched on "pulse" and graded SYRMA's "Blowout quarter
with revenue surging 67% YoY and PAT more than doubling" as WEAK.
VOLTAMP's "Stellar margin recovery" went the same way. Only the
backfill caught it, because the nonsense sat next to the headline.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import (
    classify, estimate_beat, estimate_summary, grade_of)

# Verbatim OCR of the card Earnings Pulse posted for GAIL at 08:54 on
# 31 July 2026, mangling included -- "FinAl" for FinAI, "AEst" for
# dEst, "oP" for OP, "Q0Q" for QoQ. Cleaning it up would test a card
# we never actually receive.
GAIL_CARD = (
    "GAIL (india) (oe)\n"
    "ot Fv27 FinAl Rating : Strong Beat ies\n"
    "Metric Q0Q YoY Jun'26 Est AEst Mar'26 Jun'25\n"
    "Sales 16% 17% 41350.2 37688.3 +10% 35,706 35,429\n"
    "oP 388% 93% 7097.9 2287.7 +210% 1,454 3,669\n"
    "PAT 215% 96% 4671.0 1543.9 +203% 1,482 2,382\n"
    "CMP :177 | Mega-Cap (1.1L Cr) | P/E: 15.2"
)

SYRMA_CARD = (
    "#SYRMA - Earnings - Q1 FY27\n"
    "Blowout quarter with revenue surging 67% YoY and PAT more than "
    "doubling, wildly beating estimates.\n"
    "SYRMA\nQl FY27\n"
    "Algo Pulse: Weak | Verdict: BEAT\n"
)


# ---------------------------------------------------------------
# 1. ALGO PULSE IS NOT AN EARNINGS GRADE
# ---------------------------------------------------------------
def test_a_weak_algo_pulse_does_not_make_a_beat_a_weak_quarter():
    """The regression that matters most in this file.

    SYRMA on 30 July: "Algo Pulse: Weak | Verdict: BEAT" over the word
    "Blowout". Grading that WEAK would push a genuinely outstanding
    quarter DOWN the ranking -- worse than not reading the card at all.
    """
    assert grade_of(SYRMA_CARD) == "GOOD"


@pytest.mark.parametrize("text,expected", [
    ("Algo Pulse: Weak | Verdict: BEAT", "GOOD"),
    ("Algo Pulse: Great | Verdict: BEAT", "GOOD"),
    ("Algo Pulse: Great | Verdict: MISS", "WEAK"),
])
def test_only_the_verdict_column_speaks_about_the_results(text, expected):
    assert grade_of(text) == expected


# ---------------------------------------------------------------
# 2. THE BEAT VOCABULARY
# ---------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("#GAIL - Strong Beat", "EXCELLENT"),
    ("FinAI Rating : Strong Beat", "EXCELLENT"),
    ("FinAl Rating : Strong Beat", "EXCELLENT"),   # as OCR returns it
    ("FinAI Rating : Strong Miss", "POOR"),
    ("#ABC - In-Line", "OK"),
    ("#XYZ - Miss", "WEAK"),
    ("Company beat street estimates for Q1", "GOOD"),
    ("Infosys missed expectations on margins", "WEAK"),
])
def test_beat_and_miss_are_translated_into_the_existing_grades(text, expected):
    """Mapped onto the six words the score already speaks, rather than
    adding four new ones. core/shortlist.py PULSE_SCORE knows
    EXCELLENT/GREAT/GOOD/OK/WEAK/POOR; a second vocabulary would be a
    second table to keep in step, and one of them would drift."""
    assert grade_of(text) == expected


def test_the_old_results_wording_still_works():
    """The channel's original format must not regress."""
    assert grade_of("#GAIL - Excellent Results - 22 seconds ago") == "EXCELLENT"
    assert grade_of("#SJVN - Good Results - 11 seconds ago") == "GOOD"
    assert grade_of("#SUNPHARMA - Weak Results") == "WEAK"


# ---------------------------------------------------------------
# 3. "BEAT" IS AN ORDINARY ENGLISH WORD
# ---------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "Nifty beats Asian peers as banks rally",
    "India beat Australia in the final",
    "SEBI commission reviews emissions norms",
])
def test_the_word_beat_outside_a_rating_is_not_a_result(text):
    """A loose \\bbeat\\b would turn a cricket score into an earnings
    grade. The word has to arrive in a verdict context."""
    kind, _ = classify(text, has_symbol=False)
    assert kind != "RESULT"
    assert grade_of(text) is None


# ---------------------------------------------------------------
# 4. THE NUMBERS OFF THE GRID
# ---------------------------------------------------------------
def test_the_estimates_are_read_off_the_real_card():
    beats = estimate_beat(GAIL_CARD)
    assert set(beats) == {"Sales", "OP", "PAT"}
    assert beats["PAT"]["reported"] == 4671.0
    assert beats["PAT"]["estimate"] == 1543.9
    assert beats["PAT"]["vs_estimate_pct"] == pytest.approx(202.5, abs=0.6)
    assert beats["OP"]["vs_estimate_pct"] == pytest.approx(210.3, abs=0.6)
    assert beats["Sales"]["vs_estimate_pct"] == pytest.approx(9.7, abs=0.6)


def test_the_card_is_graded_and_typed_as_a_result():
    assert classify(GAIL_CARD, has_symbol=True)[0] == "RESULT"
    assert grade_of(GAIL_CARD) == "EXCELLENT"


def test_the_summary_leads_with_the_bottom_line():
    """The card OCRs into 300 characters of grid and the headline is
    cut at 200. Before this, the operator read "GAIL (india) (oe) ot
    Fv27 FinAl Rating :" -- the numbers were past the truncation."""
    summary = estimate_summary(GAIL_CARD)
    # Computed, not read: 4671/1543.9 = 202.5%. The card rounds
    # it to 203; ours is the arithmetic.
    assert summary.startswith("PAT +202% vs est")
    assert "OP +210% vs est" in summary


def test_a_message_that_is_not_a_card_yields_nothing():
    """Returns {} rather than guessing. Most messages are not cards."""
    assert estimate_beat("#GAIL - Strong Beat") == {}
    assert estimate_summary("Reliance bags Rs 2,205 crore order") is None


# DIVISLAB, 1 August 2026. The card printed +11% and +21%; Tesseract
# read the PLUS SIGN AS A FOUR.
DIVISLAB_OCR = """Metric QoQ Jun'26 Est A Est Mar'26 Jun'25
Sales 9% 28% 3080 2785.8 411% 2,831 2,410
OP 34% 72% 1255 929.5 +35% 934 729
PAT 20% 66% 902 744 421% 751 545
"""


def test_the_surprise_is_computed_not_read():
    """THE CHIP SAID "PAT +421% vs est".

    A plausible-looking, completely wrong figure on the operator's
    screen -- the one thing this program must never produce. The
    percentage is derivable from two numbers OCR reads reliably,
    because they are plain digits with no glyph a "4" resembles:

        902 / 744 - 1 = 21.2%

    So it is worked out rather than trusted.
    """
    got = estimate_beat(DIVISLAB_OCR)
    assert got["PAT"]["vs_estimate_pct"] == pytest.approx(21.2, abs=0.2)
    assert got["Sales"]["vs_estimate_pct"] == pytest.approx(10.6, abs=0.2)
    assert got["OP"]["vs_estimate_pct"] == pytest.approx(35.0, abs=0.2)


def test_a_mangled_percentage_does_not_cost_the_row():
    """The first fix REJECTED any row whose printed figure disagreed,
    which threw away two correct rows out of three -- the numbers were
    fine, only the percentage was mangled."""
    assert set(estimate_beat(DIVISLAB_OCR)) == {"Sales", "OP", "PAT"}


def test_a_row_whose_numbers_disagree_is_dropped():
    """The printed figure still earns its place as a CHECK. If it
    matches neither the arithmetic nor the known plus-as-four
    mangling, something else on that row was scanned wrong and the row
    is not used."""
    bad = "Sales 9% 28% 3080 2785.8 -60% 2,831 2,410\n"
    assert "Sales" not in estimate_beat(bad)


def test_a_half_read_row_is_skipped_rather_than_half_stored():
    """OCR drops columns. A row missing its estimate must produce no
    entry at all -- a wrong estimate is worse than no estimate."""
    broken = "Metric QoQ YoY Jun'26 Est\nPAT 215% 96% 4671.0\n"
    assert "PAT" not in estimate_beat(broken)
