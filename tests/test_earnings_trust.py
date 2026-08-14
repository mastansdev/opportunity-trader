"""
==========================================================
The fact, not the label
==========================================================

    "as a human we cannot grasp all image data & trade decision
     right? bot will fill that gap by giving me correct info rather
     than pasting simple chips at why"
                                    -- operator, 1 August 2026

CDSL, Q1 FY27, 1 August 2026 at 12:44. Two cards from the same
publisher, minutes apart, pointing opposite ways:

    EARNINGS BRIEF   GREAT     "Strong standalone on dividend income"
    FinAI grid       Weak      OPM -333 bps

The panel showed exactly this, and nothing else:

    REPORTING TODAY
    PULSE: Weak results
    up 2.1%

Three failures in one row.

1. THE SECOND CARD WAS INVISIBLE. Stored, counted in the support
   tally, never shown. The row read as a settled negative when the
   publisher itself had not settled it.

2. THE GREAT PILL WAS NOT A GRADE. classify() was handed the grade the
   CALLER passed -- None -- while the row underneath was written with
   grade_of(), which reads the card. So the brief was filed kind=NEWS
   grade=GREAT: a result the panel does not treat as one.

3. THE DECIDING FACT WAS THROWN AWAY. The brief printed it plainly:

       EARNINGS QUALITY | ONE-OFF
       DISTORTION FLAGS  ACCOUNTING - ONE-OFFS
       Dividend income from subsidiary: Rs 39.5 Cr
       CAN EARNINGS BE TRUSTED?
       Headline is misleading; standalone operating profit fell
       despite revenue growth.

   ONE-OFF was not in the earnings-quality word list, the distortion
   section was never read, and the trust footer was never read.

WHY 39.5 CRORE DECIDES IT
-------------------------
    PAT printed       118 Cr    +15% YoY
    of which one-off   39.5 Cr  dividend from the subsidiary
    left over         ~78 Cr    against 102 Cr a year before

Standalone operating profit was -4% YoY on +11% revenue. The +15%
headline is the number that puts a stock in the gainers list. The
one-off is the reason it is there.

WHAT THIS DOES NOT DO
---------------------
It does not decide which card is right. It repeats what the publisher
printed, in the place the operator is already looking, and scores the
disagreement at zero. Which side wins is outcome tracking's question.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.shortlist import ShortlistBuilder, _lead_fact, _source_name
from core.stock_events import (distortion_flags, events_from_message,
                               quality_signals, trust_summary, trust_verdict)

# The CDSL brief, as OCR returns it.
BRIEF = """Earnings Pulse EARNINGS BRIEF CDSL Q1 FY27
GREAT
Strong standalone on dividend income; consolidated results more moderate.
GROWTH MARGINS CASH FLOW QUALITY
Rising Compressing Healthy Great
PERFORMANCE DRIVERS
Standalone Rev +11% YoY, Op Profit -4% YoY
Subsidiary dividend income boosted standalone results
EARNINGS QUALITY | ONE-OFF
PAT driven by one-off dividend
Core operating profit (standalone) declined YoY
DISTORTION FLAGS ACCOUNTING - ONE-OFFS
Dividend income from subsidiary: Rs 39.5 Cr
RED FLAGS NUMERICAL / STRUCTURAL
Pending litigation (Anugrah) with unknown liability
CAN EARNINGS BE TRUSTED?
Headline is misleading; standalone operating profit fell despite revenue growth.
earningspulse.ai AI-generated summary - Not investment advice
"""

# The same card shape on a quarter with nothing wrong with it.
HONEST = """EARNINGS BRIEF ABC Q1 FY27
GREAT
GROWTH MARGINS CASH FLOW QUALITY
Rising Expanding Healthy Excellent
EARNINGS QUALITY | CLEAN
No one-off items
DISTORTION FLAGS
None flagged
CAN EARNINGS BE TRUSTED?
Yes, the numbers hold up; growth is broadly reliable.
earningspulse.ai
"""


class Matcher:
    def symbols_in(self, text):
        return ["CDSL"] if "CDSL" in text else []

    def names_in(self, text):
        return []


class Events:
    def __init__(self, rows):
        self.rows = rows

    def recent(self, limit=None, hours=None, scope=None):
        return self.rows


def rank(rows):
    builder = ShortlistBuilder(stock_events=Events(rows))
    return builder.rank([{"symbol": "CDSL", "ltp": 1331.9,
                          "change_pct": 2.1, "sector": "Capital Markets"}],
                        top=5, today="2026-08-01")["rows"][0]


def chips(rows):
    return " || ".join(rank(rows)["why"])


PULSE_WEAK = {"symbol": "CDSL", "kind": "RESULT", "at": "2026-08-01T12:44",
              "grade": "WEAK", "source": "Earnings Pulse",
              "headline": "PULSE: Weak | Sales +13% YoY, OPM -333 bps"}
BRIEF_GREAT = {"symbol": "CDSL", "kind": "RESULT", "at": "2026-08-01T12:44",
               "grade": "GREAT", "source": "Earnings 360",
               "headline": "ONE-OFF: Dividend income from subsidiary: "
                           "Rs 39.5 Cr -- EARNINGS BRIEF CDSL Q1 FY27 GREAT"}


# ---------------------------------------------------------------
# 1. THE CARD'S OWN WARNING IS READ
# ---------------------------------------------------------------
def test_one_off_is_an_earnings_quality_reading():
    """It was not in the list, and it is the only one that changes a
    purchase. CLEAN, MIXED, POOR, WEAK and DIRTY were."""
    assert quality_signals(BRIEF)["earnings_quality"] == "ONE-OFF"


def test_the_flagged_amount_survives_with_its_number():
    """"a one-off was flagged" is a label. "Rs 39.5 Cr" is a number
    the operator can subtract from the printed profit himself."""
    flags = distortion_flags(BRIEF)
    assert flags and "39.5 Cr" in flags[0]
    assert "Dividend income" in flags[0]


def test_the_trust_footer_is_read_and_believed():
    got = trust_verdict(BRIEF)
    assert got["trusted"] is False
    assert "misleading" in got["note"]


def test_a_clean_card_is_not_turned_into_a_warning():
    """A false warning is worse than no warning -- it talks the
    operator out of a good trade, and there is no way to notice."""
    assert trust_verdict(HONEST)["trusted"] is True
    assert distortion_flags(HONEST) == []
    assert trust_summary(HONEST) is None


def test_none_flagged_means_nothing_is_wrong():
    assert distortion_flags("DISTORTION FLAGS\nNone flagged\n") == []


def test_an_ordinary_message_has_no_sections_and_no_opinion():
    plain = "CDSL wins an order worth Rs 40 Cr from a state agency."
    assert trust_verdict(plain) is None
    assert distortion_flags(plain) == []
    assert trust_summary(plain) is None


# ---------------------------------------------------------------
# 2. THE CHIP CARRIES THE FACT
# ---------------------------------------------------------------
def test_the_chip_leads_with_the_amount():
    assert trust_summary(BRIEF) == ("ONE-OFF: Dividend income from "
                                    "subsidiary: Rs 39.5 Cr")


def test_the_one_off_outranks_the_gauges():
    """"margins Compressing" is a direction. An amount is arithmetic
    the operator can do himself, so it takes the 80 characters."""
    event = events_from_message(Matcher(), ocr_text=BRIEF,
                                at="2026-08-01T12:44",
                                channel="Earnings Pulse")[0]
    assert event["headline"].startswith("ONE-OFF: Dividend income")


def test_the_pill_is_the_grade_and_the_card_is_a_result():
    """It was filed kind=NEWS grade=GREAT -- graded, but not treated
    as a result, because classify() never saw the grade."""
    event = events_from_message(Matcher(), ocr_text=BRIEF,
                                at="2026-08-01T12:44",
                                channel="Earnings Pulse")[0]
    assert event["grade"] == "GREAT"
    assert event["kind"] == "RESULT"


# ---------------------------------------------------------------
# 3. THE PANEL SHOWS BOTH CARDS
# ---------------------------------------------------------------
def test_the_second_card_was_invisible_and_now_is_not():
    shown = chips([PULSE_WEAK, BRIEF_GREAT])
    assert "CONFLICT" in shown
    assert "Weak" in shown and "Great" in shown


def test_the_conflict_names_both_sources():
    shown = chips([PULSE_WEAK, BRIEF_GREAT])
    assert "Pulse says Weak" in shown
    assert "360 says Great" in shown


def test_the_deciding_fact_reaches_the_panel():
    """The whole point. A conflict says LOOK; this says look AT WHAT."""
    assert "Rs 39.5 Cr" in chips([PULSE_WEAK, BRIEF_GREAT])


def test_the_disagreement_moves_the_score_by_nothing():
    """Which card is right is what outcome tracking will measure.
    Asserting it here would be inventing an answer."""
    assert rank([PULSE_WEAK, BRIEF_GREAT])["score"] == \
        rank([PULSE_WEAK])["score"]


def test_two_cards_that_agree_raise_no_conflict():
    agreeing = dict(BRIEF_GREAT, grade="WEAK")
    assert "CONFLICT" not in chips([PULSE_WEAK, agreeing])


def test_two_quarters_are_not_a_disagreement():
    """A Weak card on Mar-26 and a Great card on Jun-26 are two
    results, not a conflict. Without the day bound the chip would
    land on half the panel."""
    old = dict(BRIEF_GREAT, at="2026-07-28T12:44")
    assert "CONFLICT" not in chips([PULSE_WEAK, old])


# ---------------------------------------------------------------
# 4. RAW OCR MUST NEVER BECOME A CHIP
# ---------------------------------------------------------------
def test_only_a_parsers_own_label_is_promoted():
    """Everything before the separator is raw OCR unless one of our
    parsers put it there. Raw OCR in a chip is how a panel becomes
    unreadable in the one minute it has to be read."""
    assert _lead_fact("CDSL Ltd -- the depository reported today") is None
    assert _lead_fact("") is None
    assert _lead_fact(None) is None


def test_clean_science_does_not_get_a_chip_off_its_own_name():
    """CLEAN is a real NSE ticker. A bare CLEAN in the pattern would
    turn that company's every headline into a chip of raw text."""
    assert _lead_fact("CLEAN Science reports Q1 -- revenue up 8%") is None
    assert _lead_fact("CLEAN | Rising, Expanding -- EARNINGS BRIEF") == \
        "CLEAN | Rising, Expanding"


@pytest.mark.parametrize("headline,expected", [
    ("ONE-OFF: Dividend Rs 39.5 Cr -- card text", "ONE-OFF: Dividend Rs 39.5 Cr"),
    ("WATCH: margins Compressing -- card text", "WATCH: margins Compressing"),
    ("MISS EBITDA Margin -- card text", "MISS EBITDA Margin"),
    ("PAT +203% vs est -- card text", "PAT +203% vs est"),
])
def test_the_labels_a_parser_writes_are_all_promoted(headline, expected):
    assert _lead_fact(headline) == expected


def test_a_channel_name_is_short_enough_to_fit_two_in_one_chip():
    assert _source_name("Earnings Pulse") == "Pulse"
    assert _source_name("Earnings 360") == "360"
    assert _source_name(None) == "one card"
    assert len(_source_name("A Very Long Channel Name Indeed")) <= 14


# ---------------------------------------------------------------
# 5. THE ALL-CLEAR LINE, AS THE OCR ACTUALLY RETURNS IT
# ---------------------------------------------------------------
# Read off the 25 briefs stored on 1 August 2026. The space after
# "No" is eaten more often than not, and three of the six flagged
# cards were cards saying nothing was wrong.
@pytest.mark.parametrize("line", [
    "Noexceptional items in Q1 FY27",
    "Noone-off items apparent",
    "Nosignificant one-off distortions",
    "No material one-off items",
    "None flagged",
    "No significant one-off gains distorting",
])
def test_a_card_saying_nothing_is_wrong_raises_no_flag(line):
    card = f"EARNINGS QUALITY | CLEAN\nDISTORTION FLAGS\n> {line}\n"
    assert distortion_flags(card) == [], (
        "a card reporting an all-clear was becoming a warning chip")


def test_an_amount_beats_the_all_clear():
    """"No significant one-off items, but a forex loss of Rs 400 Cr"
    says both things, and the 400 Cr is the half worth reading."""
    card = ("EARNINGS QUALITY | CLEAN\nDISTORTION FLAGS\n"
            "> No significant one-off items, but forex loss of Rs 400 Cr\n")
    assert distortion_flags(card) == [
        "No significant one-off items, but forex loss of Rs 400 Cr"]


def test_a_real_flag_survives_a_reassurance_on_the_line_above():
    """This dropped the WHOLE section on the first line that said
    "no one-off items" -- deleting the evidence rather than merely
    failing to read it. One stored card lost a real flag that way."""
    card = ("EARNINGS QUALITY | ONE-OFF\nDISTORTION FLAGS\n"
            "> Noexceptional items in Q1 FY27\n"
            "> Segment reporting structure redefined\n")
    assert distortion_flags(card) == ["Segment reporting structure redefined"]
