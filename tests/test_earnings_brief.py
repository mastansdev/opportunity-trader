"""
==========================================================
Can this quarter be trusted?
==========================================================

    "the ultimate motive is to gather full confidence, evidence, & in
     why i must see before buying any share even a 1 stock share also.
     i need to see why? it is moving ; volumes ?, results? or any
     strong news?"                  -- operator, 1 August 2026

Earnings 360 and Earnings Pro publish a one-page brief per result. It
answers what core/quarterly_results.py structurally cannot:

    GROWTH    Rising        EARNINGS QUALITY   CLEAN
    MARGINS   Expanding     DISTORTION FLAGS   forex loss Rs 7 Cr
    CASH FLOW Healthy       RED FLAGS          none
    QUALITY   Excellent

Our own grader reads sales and profit. It cannot see a margin, a cash
flow or a one-off -- which is why it called APTUS STRONG on +19% YoY
profit on a day the stock fell 5.77% because provisions had doubled.

22 of these cards were sitting unread in telegram.db when this was
written.

THE FALSE WARNING THIS FILE EXISTS TO PREVENT
---------------------------------------------
The first parser allowed 80 characters of ANY character, newlines
included, between a label and its reading. The card prints:

    GROWTH MARGINS CASH FLOW QUALITY      <- four labels
    Rising Expanding Healthy Excellent    <- four readings

so on a card whose reading row OCR'd badly, "CASH FLOW" matched the
word "weak" from an unrelated section further down and produced

    WATCH: margins Compressing, cash flow Weak, quality Weak

on a card the channel itself had marked GREEN. A false warning is
worse than no warning -- it is the same confident-wrong-answer failure
as reading a filing's columns out of alignment, and it would have
talked the operator out of a good trade.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import grade_of, quality_signals, quality_summary

GREEN = "\U0001F7E2"
AMBER = "\U0001F7E1"
RED = "\U0001F534"

# Verbatim OCR of a real card, arrows and all.
CLEAN_CARD = """Earnings Pulse
Strong standalone with robust YoY growth
GREAT
GROWTH MARGINS CASH FLOW QUALITY
t Rising + Expanding ge Healthy Great
PERFORMANCE DRIVERS SEGMENT REALITY
EARNINGS QUALITY | CLEAN DISTORTION FLAGS ACCOUNTING - ONE-OFFS
= No one-off items apparent
"""

# The one that exposed the bug: a GREEN card whose reading row is
# unreadable, with the word "weak" appearing far below in prose.
HALF_READ_CARD = """Earnings Pulse
GROWTH MARGINS CASH FLOW QUALITY
drives growth Brokerage segment profit T 10% YoY
MARGIN DRIVERS BALANCE SHEET SIGNALS
Consolidated PBT margin J to 9.2%
EARNINGS QUALITY | ONE-OFF DISTORTION FLAGS ACCOUNTING - ONE-OFFS
weak comparison base and poor quality of the prior year
"""


# ---------------------------------------------------------------
# 1. THE FOUR GAUGES
# ---------------------------------------------------------------
def test_the_readings_are_taken_from_the_line_below_the_labels():
    got = quality_signals(CLEAN_CARD)
    assert got["growth"] == "Rising"
    assert got["margins"] == "Expanding"
    assert got["cash_flow"] == "Healthy"
    assert got["earnings_quality"] == "CLEAN"


def test_a_half_read_card_reports_NOTHING_rather_than_a_guess():
    """THE REGRESSION THAT MATTERS.

    Four labels, an unreadable reading row, and the word "weak" in
    prose further down. The first parser reported "cash flow Weak,
    quality Weak" on a card the channel had marked GREEN.
    """
    assert quality_signals(HALF_READ_CARD) == {} or \
        "cash_flow" not in quality_signals(HALF_READ_CARD), \
        "a reading must not be scavenged from unrelated prose"


def test_a_half_read_card_raises_no_warning_off_THE_GAUGES():
    """---- WIDENED 1 AUGUST 2026, AND THE ORIGINAL WAS TOO BROAD ----

    This asserted that a half-read card produces no WATCH at all. It
    passed for the wrong reason: ONE-OFF was missing from the earnings
    quality word list, so the line this card prints plainly --

        EARNINGS QUALITY | ONE-OFF

    -- read as nothing. When CDSL's brief made that omission expensive
    the word was added, and this test went red.

    The guard being defended is "do not scavenge a reading out of
    unrelated prose". This card has the word "weak" and the word
    "poor" in its last line, and neither may become a gauge. But the
    earnings-quality pill is not scavenged -- it is a delimited label
    with its value beside it, and reporting it is exactly right.

    So the assertion is now about the GAUGES, which is what the bug
    was, rather than about the whole summary.
    """
    summary = quality_summary(HALF_READ_CARD) or ""
    for gauge in ("growth", "margins", "cash flow"):
        assert gauge not in summary.lower(), (
            f"a reading scavenged from prose would talk the operator "
            f"out of a good trade: {summary!r}")
    assert quality_summary(HALF_READ_CARD) == "WATCH: earnings quality ONE-OFF"


def test_a_message_that_is_not_a_brief_yields_nothing():
    assert quality_signals("#GAIL - Excellent Results") == {}
    assert quality_summary("Reliance bags Rs 2,205 crore order") is None


# ---------------------------------------------------------------
# 2. THE WARNING LEADS
# ---------------------------------------------------------------
def test_a_bad_reading_becomes_a_WATCH():
    card = CLEAN_CARD.replace("t Rising + Expanding ge Healthy Great",
                              "t Rising J. Compressing v Weak OK")
    summary = quality_summary(card)
    assert summary.startswith("WATCH")
    assert "margins Compressing" in summary


def test_a_clean_card_says_so_briefly():
    assert quality_summary(CLEAN_CARD).startswith("CLEAN |")


def test_a_green_dot_and_a_compressing_margin_can_both_be_true():
    """BLUSPRING, 1 August. The channel's dot said green; the card's
    own text said "acquisition-driven revenue growth masks a
    significant drop in profitability". Both were right, and the chip
    that matters is the one the dot glosses over."""
    card = GREEN + " #BLUSPRING\n" + CLEAN_CARD.replace(
        "t Rising + Expanding ge Healthy Great",
        "+ Rising J. Compressing v Healthy OK")
    assert grade_of(card) == "GOOD"
    assert "Compressing" in quality_summary(card)


# ---------------------------------------------------------------
# 3. THE DOT IS THE GRADE
# ---------------------------------------------------------------
# A card carrying no verdict pill of its own, so the dot is the only
# reading available.
NO_PILL = CLEAN_CARD.replace("GREAT\n", "")


@pytest.mark.parametrize("dot,expected", [
    (GREEN, "GOOD"), (AMBER, "MIXED"), (RED, "WEAK"),
])
def test_the_traffic_light_grades_the_card(dot, expected):
    """It is in the message TEXT, not inside the picture -- so it needs
    no OCR and cannot be mangled by a bad scan. Chasing the OCR'd
    verdict word instead had reached 3 cards out of 12 and was about to
    become an evening of layout patterns."""
    assert grade_of(f"{dot} #NEUEON - Q1 FY27\n" + NO_PILL) == expected


def test_the_dot_is_used_when_the_card_offers_nothing_else():
    """This test used to assert "the dot BEATS the picture", and a red
    dot on a card reading GREAT returned WEAK.

    That was replaced on 1 August after TCC showed a GREEN dot on a
    card whose own verdict was WEAK. Letting either side win means
    picking a favourite between two readings of the same document;
    disagreement now returns MIXED, and the dot decides only when it is
    the sole reading available.
    """
    assert grade_of(RED + " #X\n" + NO_PILL) == "WEAK"


def test_a_card_that_disagrees_with_its_own_dot_grades_MIXED():
    """TCC, 1 August 2026. The channel opened with a GREEN dot and the
    card underneath said WEAK -- their headline contradicting their own
    detail.

    Taking the dot puts GOOD on that stock. Taking the pill means
    trusting OCR over a character that cannot be misread. Neither is
    defensible, so neither is chosen: a disagreement between two
    readings of the SAME card is the reason to look, and MIXED is the
    only honest word for it.

    Found by auditing what was already stored, after the operator
    asked "are we still getting misleading chips?" -- 1 of 22.
    """
    card = GREEN + " #TCC - Q1 FY27\nWEAK\n" + CLEAN_CARD.replace(
        "GREAT\n", "")
    assert grade_of(card) == "MIXED"


def test_a_card_that_agrees_with_its_dot_keeps_the_dot():
    """The disagreement rule must not swallow the ordinary case."""
    card = GREEN + " #X\nGREAT\n" + CLEAN_CARD.replace("GREAT\n", "")
    assert grade_of(card) == "GOOD"


def test_the_first_audit_of_this_was_circular():
    """A note rather than a test of behaviour.

    The first check compared our grade against the dot -- but our grade
    WAS the dot, so it reported zero contradictions and proved nothing.
    The real check compares the dot against the card's own verdict
    pill, which is what found TCC.

    Kept as a reminder that a passing audit is only worth the
    independence of the two things it compares.
    """
    from core.stock_events import DOT_GRADE
    assert DOT_GRADE[GREEN] == "GOOD"


def test_an_ordinary_message_is_unaffected():
    assert grade_of("Reliance bags Rs 2,205 crore order") is None
    assert grade_of("#GAIL - Excellent Results") == "EXCELLENT"


# ---------------------------------------------------------------
# 4. THE CARD'S OWN WORDS ARE NOT TICKERS
# ---------------------------------------------------------------
def test_the_word_CLEAN_is_not_matched_as_clean_science():
    """Of every word these briefs print, exactly one is a listed
    company: CLEAN -> CLEAN SCIENCE & TECH LTD. So "EARNINGS QUALITY |
    CLEAN" on a NEUEON brief filed the whole card against Clean
    Science."""
    from core.stock_events import events_from_message

    class Matcher:
        def symbols_in(self, text):
            return ["CLEAN"] if "CLEAN" in (text or "") else []

        def names_in(self, text):
            return []

    events = events_from_message(Matcher(), ocr_text=CLEAN_CARD,
                                 at="2026-08-01T03:00", channel="Earnings 360")
    assert not any(e["symbol"] == "CLEAN" for e in events), (
        "the quality label must not be read as a ticker")
