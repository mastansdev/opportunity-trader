"""
==========================================================
Not yet priced -- the evening recap grid
==========================================================

    "sorted list of results which will get impacted on monday market"
                                    -- operator, 1 August 2026

He is describing the one thing this card knows that nothing else does.
A result released AFTER 15:30 on Friday has not been priced -- the
market was shut. It moves Monday morning. That is the early-bird
window he asked for in the morning:

    "before the movement i need to trust as early bird not in a over
     crowded place after rally done"

     5 cards stored
   193 companies named on them
     0 events produced

Third structured page eaten by the three-company rule, after the
expectations page (23 lost) and the market sentiment pages (258 lost).

WHAT THIS REFUSES TO READ, AND WHY
----------------------------------
THE GRADE. It is printed on the card and it cannot be recovered.

The card is a table -- EXCELLENT / GREAT / GOOD / OK / WEAK down the
side, During Market / After Market across the top. OCR returns the
rating column as a detached stack ABOVE the title:

    EXCELLENT
    GREAT
    GOOD
    EARNINGS PULSE RECAP
    29 Jul, 2026
    During Market
    @ APCOTEXIND @ PCBL
    ...

Three rating words for five rating rows, with nothing tying any of
them to any company. On one of the five cards only three of the five
ratings survived at all.

Guessing a band would put a WEAK company under EXCELLENT on the table
he clicks BUY from. The grade is already stored correctly from the
individual brief cards, so this card would add nothing but risk.

WHAT IT DOES READ
-----------------
The During / After split, which survives cleanly and in order on all
five cards. 210 events recovered from 0.

AND IT IS HONEST ABOUT BEING PARTIAL
------------------------------------
The reader gets about HALF the card. The 31 July card shows roughly a
hundred companies and its OCR is 845 characters. DIVISLAB, GAEL and
SPORTKING -- all three printed under EXCELLENT / After Market -- are
not in the text at all.

So coverage() reports what was matched against what was mangled
(BAJAJFINSY for BAJAJFINSV, GMOCTTO for GMDCLTD, GBBROSLTD for
LGBBROSLTD). A panel showing 27 after-close names as though that were
the whole day would have him plan a morning around half a list.

Author : H&M Opportunity Trader
==========================================================
"""

from datetime import date

import pytest

from core.recap_card import (AFTER, DURING, coverage, headline_for,
                             is_recap_card, recap_date, rows_from_card)

# Verbatim shape from telegram.db, OCR damage included. Note the rating
# words stranded at the top, above the title, attached to nothing.
CARD = """EXCELLENT
GREAT
GOOD
EARNINGS PULSE RECAP
29 Jul, 2026
During Market
@ APCOTEXIND @ PCBL
@ ASIANPAINT §=@ INDOSTAR
@ ADANIPORTS §=@ MACPOWER
After Market
@ DABUR «© MTARTECH
@ REDINGTON @ EMUDHRA
@ EICHERMOT @ QUESS
@ BAJAJFINSY
"""

KNOWN = {"APCOTEXIND", "PCBL", "ASIANPAINT", "INDOSTAR", "ADANIPORTS",
         "MACPOWER", "DABUR", "MTARTECH", "REDINGTON", "EMUDHRA",
         "EICHERMOT", "QUESS", "BAJAJFINSV"}


@pytest.fixture(scope="module")
def rows():
    return rows_from_card(CARD, known=KNOWN)


# ---------------------------------------------------------------
# 1. THE CARD, AND ITS DATE
# ---------------------------------------------------------------
def test_the_card_is_recognised():
    assert is_recap_card(CARD)
    assert not is_recap_card("#GHCL - Excellent Results")
    assert not is_recap_card("")


def test_the_session_date_is_read():
    assert recap_date(CARD) == date(2026, 7, 29)


def test_a_missing_date_falls_back_rather_than_guessing():
    assert recap_date("EARNINGS PULSE RECAP\nDuring Market\n") is None
    assert recap_date("EARNINGS PULSE RECAP", date(2026, 8, 1)) == date(2026, 8, 1)


# ---------------------------------------------------------------
# 2. THE SPLIT -- THE WHOLE POINT
# ---------------------------------------------------------------
def test_during_and_after_land_on_the_right_side(rows):
    """THE ONE THAT MATTERS. A company on the wrong side of the close
    is a company he thinks is unpriced when the market has already
    answered it."""
    during = {r["symbol"] for r in rows if r["when"] == DURING}
    after = {r["symbol"] for r in rows if r["when"] == AFTER}
    assert during == {"APCOTEXIND", "PCBL", "ASIANPAINT", "INDOSTAR",
                      "ADANIPORTS", "MACPOWER"}
    assert after == {"DABUR", "MTARTECH", "REDINGTON", "EMUDHRA",
                     "EICHERMOT", "QUESS"}
    assert not during & after


def test_a_card_missing_a_heading_returns_nothing():
    """Without both headings in order there is no way to say which
    side of the close a company reported on -- and that is the only
    thing this card is read for."""
    assert rows_from_card("EARNINGS PULSE RECAP\n@ DABUR\n", known=KNOWN) == []
    assert rows_from_card("EARNINGS PULSE RECAP\nAfter Market\n@ DABUR\n"
                          "During Market\n@ PCBL\n", known=KNOWN) == []


# ---------------------------------------------------------------
# 3. THE GRADE IS REFUSED
# ---------------------------------------------------------------
def test_no_row_carries_a_grade(rows):
    """The rating words sit above the title, detached. Guessing which
    company belongs to which band is the mismatch rule."""
    for row in rows:
        assert set(row) == {"symbol", "when"}
        assert "grade" not in row
        assert "pulse" not in row


def test_the_rating_words_are_not_mistaken_for_companies(rows):
    """EXCELLENT, GREAT and GOOD are ticker-shaped and sit in the text
    like everything else."""
    names = {r["symbol"] for r in rows}
    for word in ("EXCELLENT", "GREAT", "GOOD", "MARKET", "DURING",
                 "AFTER", "EARNINGS", "PULSE", "RECAP"):
        assert word not in names


def test_the_store_is_never_handed_a_grade_from_this_card():
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("if is_recap_card(body):"):]
    block = block[:block.find("if is_digest(body):")]
    assert '"grade": None' in block


# ---------------------------------------------------------------
# 4. THE NSE GATE
# ---------------------------------------------------------------
def test_a_mangled_ticker_is_dropped(rows):
    """BAJAJFINSY is the reader's version of BAJAJFINSV. Storing it
    would create a company that does not exist."""
    assert "BAJAJFINSY" not in {r["symbol"] for r in rows}


def test_no_universe_means_no_rows():
    """An ungated read of this OCR fills the store with fragments, and
    a fragment is indistinguishable from a real symbol once stored."""
    assert rows_from_card(CARD, known=None) == []
    assert rows_from_card(CARD, known=set()) == []


# ---------------------------------------------------------------
# 5. IT ADMITS WHAT IT MISSED
# ---------------------------------------------------------------
def test_coverage_counts_what_the_reader_mangled():
    matched, unmatched = coverage(CARD, known=KNOWN)
    assert matched == 12
    assert unmatched >= 1, (
        "BAJAJFINSY is a company on the card that has been lost -- the "
        "panel has to be able to say the list is partial")


def test_coverage_is_zero_on_something_that_is_not_a_recap():
    assert coverage("#GHCL - Excellent Results", known=KNOWN) == (0, 0)


# ---------------------------------------------------------------
# 6. THE CHIP
# ---------------------------------------------------------------
def test_the_after_close_chip_says_it_is_unpriced():
    got = headline_for({"symbol": "DABUR", "when": AFTER}, on=date(2026, 7, 31))
    assert "AFTER CLOSE" in got
    assert "not yet priced" in got
    assert "31 Jul" in got


def test_the_during_chip_does_not_claim_to_be_unpriced():
    got = headline_for({"symbol": "PCBL", "when": DURING}, on=date(2026, 7, 31))
    assert "DURING THE SESSION" in got
    assert "not yet priced" not in got


def test_the_chip_scores_nothing():
    """"Reported after the close" says the market has not judged it --
    not that the numbers were good. The grade is a different chip and
    it is already on the row."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find('elif kind == "REPORTED"'):]
    block = block[:block.find('elif (kind == "MARKET_ANSWER"')]
    assert "0.0" in block


def test_reported_is_a_kind_the_store_accepts():
    from core.stock_events import USEFUL_KINDS
    assert "REPORTED" in USEFUL_KINDS


def test_the_card_is_read_before_the_three_company_rule():
    src = open("core/stock_events.py", encoding="utf-8").read()
    card_at = src.find("if is_recap_card(body):")
    rule_at = src.find("if len(symbols) >= 3:")
    assert 0 < card_at < rule_at


# ---------------------------------------------------------------
# 7. THE TWO FORWARD-LOOKING CARDS -- 2 August 2026
# ---------------------------------------------------------------
#
#     "shortly today they will send list of stocks which have results
#      on 03-Aug with same During Markets & After Market (this will
#      get sort out to focus on which stocks we needed = early bird)"
#
# The first version read only the 18:00 recap, which looks BACKWARD.
# Earnings Pulse sends the same split on two forward cards, and eight
# of them were already in the store, unread:
#
#     02:30  TODAY EARNINGS        who reports TODAY
#     14:30  TOMORROW'S CALENDAR   who reports TOMORROW
#     18:00  EARNINGS PULSE RECAP  who reported today
#
# 210 events -> 445.

from core.recap_card import RECAP, TODAY, TOMORROW, card_kind  # noqa: E402

TODAY_CARD = """TODAY EARNINGS
30 Jul, 2026 + 67 Companies
DURING MARKET HOURS
uM HYUNDAI IRFC VEDL EXIDEIND
AFTER MARKET HOURS
OAIFNANCE TATASTEEL TORNTPHARM MANKIND
"""

FWD_KNOWN = {"HYUNDAI", "IRFC", "VEDL", "EXIDEIND",
             "TATASTEEL", "TORNTPHARM", "MANKIND"}


@pytest.mark.parametrize("text,expected", [
    ("EARNINGS PULSE RECAP\n29 Jul, 2026\n", RECAP),
    ("TODAY EARNINGS\n30 Jul, 2026\n", TODAY),
    ("TOMORROW'S CALENDAR\n31 Jul, 2026\n", TOMORROW),
    ("TOMORROWS CALENDAR\n31 Jul, 2026\n", TOMORROW),
    ("#GHCL - Excellent Results", None),
    ("", None),
])
def test_each_card_type_is_identified(text, expected):
    assert card_kind(text) == expected


def test_the_hours_suffix_does_not_break_the_split():
    """The recap prints "After Market"; the forward cards print
    "AFTER MARKET HOURS"."""
    rows = rows_from_card(TODAY_CARD, known=FWD_KNOWN)
    during = {r["symbol"] for r in rows if r["when"] == DURING}
    after = {r["symbol"] for r in rows if r["when"] == AFTER}
    assert during == {"HYUNDAI", "IRFC", "VEDL", "EXIDEIND"}
    assert after == {"TATASTEEL", "TORNTPHARM", "MANKIND"}


def test_a_forward_card_never_claims_the_result_is_out():
    """THE ONE THAT MATTERS. Same split, opposite tense.

    On the RECAP, "after close" means it reported last night and the
    market never saw it -- trade it at this open. On TODAY EARNINGS it
    means it has NOT reported yet and will not until tonight. Using the
    recap wording would put a stock on the early-bird list before its
    numbers exist."""
    row = {"symbol": "TATASTEEL", "when": AFTER}
    back = headline_for(row, on=date(2026, 7, 30), kind=RECAP)
    fwd = headline_for(row, on=date(2026, 7, 30), kind=TODAY)

    assert back.startswith("REPORTED AFTER CLOSE")
    assert "not yet priced" in back

    assert fwd.startswith("REPORTS AFTER CLOSE")
    assert "moves the next session" in fwd
    assert "not yet priced" not in fwd


def test_a_forward_during_row_says_it_is_live_today():
    got = headline_for({"symbol": "HYUNDAI", "when": DURING},
                       on=date(2026, 7, 30), kind=TODAY)
    assert got.startswith("REPORTS DURING THE SESSION")
    assert "live today" in got


def test_the_store_passes_the_card_type_through():
    """headline_for defaults to RECAP. If stock_events forgot to pass
    the kind, every forward card would be written in the past tense
    and the early-bird list would fill with unreported companies."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    assert "which = card_kind(body)" in src
    assert "kind=which" in src
