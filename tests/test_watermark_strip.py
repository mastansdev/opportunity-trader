"""
==========================================================
The tweet, not the account that posted it
==========================================================

    "DAY TRADER TELUGU ... WILL POST/FORWARD ONLY IMAGES FROM X WHICH
     ARE USEFUL FOR OUR CAUSE & EFFECT ON STOCKS + RESULTS + NDTV LIST"
                                    -- operator, 1 August 2026

The images are the value, and they are SCREENSHOTS. Every one carries
the publisher's watermark above the news, and the OCR mangles it a
different way each time. Measured on the store: 26 event headlines
opened with it, so the chip and the stock card both spent their first
forty characters saying REDBOXINDIA.

THREE SHAPES, ALL VERBATIM
--------------------------
    H#IQWithCNBCTV18 | #SJVN reports its Q1 results...
    #1QWithCNBCTV18 | #CenturyPly reports its Q1...
    HONCNBCTV18 ¢ L&T Order Inflows Have Remained Strong...

    a= RedboxGlobal India @ i= @REDBOXINDIA SYRMA SGS: Q1 CONS...
    De eReDBOXINDIA SYRMA SGS: CO SAYS CONFIDENT OF EXCEEDING...
    Be oReDBOXINDIA VIKRAN ENGINEERING: SECURES 2120.69 CRORE...

    cNec CNBC-TV18 @& #1QWithCNBCTV18 | #Vedanta reports...   <- BOTH

"IQWithCNBCTV18" came back seven different ways, so the patterns key
on the part the OCR keeps: CNBCTV18, and REDBOXINDIA.

WHY A PUBLISHER-SPECIFIC RULE IS ALLOWED HERE
---------------------------------------------
Two publisher-specific rules were written and REVERTED the same day --
an all-caps guard that would have silenced most of a channel, and a
hashtag-only rule that dropped 938 true symbols. Both were rejected
because they DECIDED something and could lose a true link.

This one cannot. It removes a PREFIX and nothing else. At worst it
leaves the headline exactly as it found it.

THE GUARD IS POSITION
---------------------
One real story in the same batch reads

    IDFC FIRST Bank is presenting the Fintech Cohort of LeapToUnicorn
    Season 4, in association with CNBC-TV18

CNBC is the SUBJECT there, not the watermark. It survives because the
rule only ever matches at the front.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.stock_events import events_from_message, strip_x_header


# ---------------------------------------------------------------
# 1. THE CAMPAIGN TAG, ALL SEVEN WAYS THE OCR WROTE IT
# ---------------------------------------------------------------
@pytest.mark.parametrize("raw,starts", [
    ("H#IQWithCNBCTV18 | #SJVN reports its Q1 results", "#SJVN"),
    ("HIQWithCNBCTV18 | #GAIL reports its Q1 results", "#GAIL"),
    ("#1IQWithCNBCTV18 | #ABCapital reports its Q1", "#ABCapital"),
    ("#1QWithCNBCTV18 | #CenturyPly reports its Q1", "#CenturyPly"),
    ("#IQWIthCNBCTV18 | #Gillette reports its Q1", "#Gillette"),
    ("#IQWITHCNBCTV18 NIM Will Further Decline By 5 bps", "NIM"),
    ("HONCNBCTV18 ¢ L&T Order Inflows Have Remained Strong", "L&T"),
])
def test_the_campaign_tag_comes_off(raw, starts):
    assert strip_x_header(raw).startswith(starts)


# ---------------------------------------------------------------
# 2. THE HANDLE, ALL SIX WAYS
# ---------------------------------------------------------------
@pytest.mark.parametrize("raw,starts", [
    ("a= RedboxGlobal India @ i= @REDBOXINDIA SYRMA SGS TECH: Q1 CONS",
     "SYRMA"),
    ("De eReDBOXINDIA SYRMA SGS: CO SAYS CONFIDENT OF EXCEEDING", "SYRMA"),
    ("Be oReDBOXINDIA VIKRAN ENGINEERING: SECURES 2120.69 CRORE", "VIKRAN"),
    ("Oe eReDBOXINDIA ERIS LIFESCIENCE: Q1 CONS NET PROFIT", "ERIS"),
    ("= RedboxGlobal India @ i= @REDBOXINDIA INDOSTAR CAPITAL", "INDOSTAR"),
    ("ae RedboxGlobal India @ i= @REDBOXINDIA DEVYANI INTERNATIONAL",
     "DEVYANI"),
])
def test_the_handle_comes_off(raw, starts):
    assert strip_x_header(raw).startswith(starts)


def test_two_watermarks_stacked_both_come_off():
    """The first attempt left this one untouched: the junk prefix
    pattern used \\S and could not cross the space in "cNec CNBC"."""
    raw = "cNec CNBC-TV18 @& #1QWithCNBCTV18 | #Vedanta reports its Q1"
    assert strip_x_header(raw).startswith("#Vedanta")


# ---------------------------------------------------------------
# 3. WHAT IT MUST NEVER TOUCH
# ---------------------------------------------------------------
def test_a_story_ABOUT_cnbc_survives_whole():
    """THE ONE THAT MATTERS. CNBC is the subject of this sentence, not
    a watermark on it."""
    real = ("IDFC FIRST Bank is presenting the Fintech Cohort of "
            "LeapToUnicorn Season 4, in association with CNBC-TV18")
    assert strip_x_header(real) == real


@pytest.mark.parametrize("real", [
    "Reliance bags Rs 2,205 crore order from HAL",
    "#GHCL - Excellent Results",
    "Clean Science inks 5-year supply deal with Kemin Industries",
    "DABUR: CO AIMS DOUBLE-DIGIT VOLUME GROWTH IN FY27",
    "",
])
def test_ordinary_news_is_returned_exactly_as_it_arrived(real):
    assert strip_x_header(real) == real


def test_it_can_only_ever_shorten_from_the_front():
    """The whole reason this publisher-specific rule is allowed where
    two others were reverted: it decides nothing and can lose nothing
    but a prefix."""
    for raw in ("a= RedboxGlobal India @ i= @REDBOXINDIA SYRMA SGS: Q1",
                "H#IQWithCNBCTV18 | #SJVN reports",
                "Reliance bags Rs 2,205 crore order from HAL"):
        out = strip_x_header(raw)
        assert raw.endswith(out), "it removed something other than a prefix"


def test_a_line_that_is_only_a_watermark_does_not_become_junk():
    assert strip_x_header("a= RedboxGlobal India @\ni= @REDBOXINDIA") == ""


# ---------------------------------------------------------------
# 4. END TO END, THROUGH THE EVENT BUILDER
# ---------------------------------------------------------------
class Matcher:
    def symbols_in(self, text):
        return ["SYRMA"] if "SYRMA" in text else []

    def names_in(self, text):
        return []


def test_the_stored_headline_starts_at_the_news():
    """It has to happen when the event is BUILT. By the time the
    headline is stored it is one line, the breaks are gone, and no
    line-based rule can find the header again."""
    card = ("a= RedboxGlobal India @\n"
            "i= @REDBOXINDIA\n"
            "SYRMA SGS TECH: Q1 CONS NET PROFIT 1B RUPEES VS 700M (YOY)\n")
    event = events_from_message(Matcher(), ocr_text=card,
                                at="2026-08-01T09:00",
                                channel="Day Trader Telugu")[0]
    assert event["headline"].startswith("SYRMA SGS TECH:")
    assert "REDBOX" not in event["headline"].upper()
