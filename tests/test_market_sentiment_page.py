"""
==========================================================
258 rows the panel never saw
==========================================================

    "are we utilizing all what we have from PRO? we get almost every
     details as instant as possible."
                                    -- operator, 1 August 2026

He asked repeatedly. This was the largest single answer, and it was no.

     52 pages received
    258 stock rows printed on them
      3 events produced

Earnings Pulse publishes "Market Sentiment for <date> Reportings" the
morning after results, in numbered parts. Every row is one company:

    2. Adani Enterp. (ADANIENT) Pulse: Weak
       Sentiment: Negative
       Market Reality: During-hours release: Adani Enterprises shares
       slipped 0.44% after reporting a Q1 FY27 consolidated net loss of
       Rs 1,160.23 Cr due to a one-time exceptional settlement charge
       of Rs 2,644 Cr, despite revenue surging 50% YoY to Rs 33,546 Cr.

The PRO membership calls this layer "market confirmation and your
safety blanket". It is the only source in the system that says the
grade and the tape pointed OPPOSITE ways.

WHY 258 BECAME 3
----------------
events_from_message() refuses any message naming three or more
companies -- "A MESSAGE ABOUT THREE COMPANIES IS ABOUT NONE OF THEM."

That rule is correct, and correct for its stated reason: a news RECAP
pairs the wrong figure with the wrong company. It is wrong here for
the same reason it was wrong on the expectations page -- this is a
TABLE. Every row carries its own symbol, grade and sentence.

Second time the same rule ate a structured page. The first cost 23
expectations. This cost 258 rows.

THE BUG THIS FILE EXISTS TO PREVENT
-----------------------------------
The first version of disagrees() compared the grade against the row's
"Sentiment:" word. AHCL, 30 July, proves that is wrong:

    Pulse: Weak
    Sentiment: Positive
    Market Reality: shares FELL 7.4% in profit booking despite Q1
                    FY27 net profit rising to Rs 4.8 Cr

Sentiment says Positive. The stock fell 7.4%. "Sentiment" is the
publisher reading the RESULT, not the tape. Comparing against it would
have printed "MARKET DISAGREES ... market positive" on a stock the
market had just sold 7.4%.

It now reads the number out of the Market Reality sentence. 226 rows
on the tradeable universe, 80 with a recoverable move, 20 genuine
disagreements.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.market_sentiment import (disagrees, headline_for, is_sentiment_page,
                                   price_move, rows_from_page)

# Verbatim from telegram.db, OCR damage included: the diamond bullet
# came back as "«", and "During" as "Ouring" on some rows.
PAGE = """Market Sentiment for July 29 Reportings
Part 1: IT & Consumer Giants
1. Adani Ports (ADANIPORTS) Pulse: OK Sentiment: Positive
Market Reality: During-hours release: Adani Ports & SEZ shares traded flat (-
0.11%) post-earnings as Q1 FY27 EBITDA grew 19% YoY.
2. Adani Enterp. (ADANIENT) Pulse: Weak
Sentiment: Negative
Market Reality: During-hours release: Adani Enterprises shares slipped 0.44%
after reporting a Q1 FY27 consolidated net loss of Rs 1,160.23 Cr.
3. Asian Paints (ASIANPAINT) Pulse: Great
Sentiment: Positive
Market Reality: During-hours release: Asian Paints shares held steady (+0.11%)
after Q1 FY27 consolidated net profit rose 40% YoY.
4. Go Fashion (I) (GOCOLORS) Pulse: Weak
Sentiment; Mixed
« Market Reality: During-hours release: Go Fashion shares surged 6.79% as
Q1 FY27 revenue held up.
5. Anion Healthcare (AHCL) Pulse: Weak
Sentiment: Positive
« Market Reality: During-hours release: Anion Healthcare shares fell 7.4% in
profit booking despite Q1 FY27 net profit rising to Rs 4.8 Cr.
"""


@pytest.fixture(scope="module")
def rows():
    return rows_from_page(PAGE)


def _by(rows, symbol):
    return next(r for r in rows if r["symbol"] == symbol)


# ---------------------------------------------------------------
# 1. THE PAGE IS RECOGNISED AND READ ROW BY ROW
# ---------------------------------------------------------------
def test_the_page_is_recognised():
    assert is_sentiment_page(PAGE)
    assert not is_sentiment_page("#GHCL - Excellent Results")
    assert not is_sentiment_page("")


def test_every_row_is_read(rows):
    assert [r["symbol"] for r in rows] == [
        "ADANIPORTS", "ADANIENT", "ASIANPAINT", "GOCOLORS", "AHCL"]


def test_the_grade_belongs_to_its_own_row(rows):
    """THE ONE THAT MATTERS. Five companies on one page, five grades.
    Pairing the wrong grade with the wrong company is the exact failure
    the three-company rule was written to prevent -- so reading the
    page must not reintroduce it."""
    assert _by(rows, "ADANIENT")["pulse"] == "WEAK"
    assert _by(rows, "ASIANPAINT")["pulse"] == "GREAT"
    assert _by(rows, "ADANIPORTS")["pulse"] == "OK"


def test_the_ticker_is_the_last_bracket_not_the_first(rows):
    """"Go Fashion (I) (GOCOLORS)" -- the printed NAME carries its own
    brackets. Taking the first would file the row against "I"."""
    assert _by(rows, "GOCOLORS")["name"].startswith("Go Fashion")
    assert not any(r["symbol"] == "I" for r in rows)


def test_a_damaged_semicolon_still_reads_the_sentiment(rows):
    """OCR returns "Sentiment;" and "'Sentiment:" about as often as
    the real thing."""
    assert _by(rows, "GOCOLORS")["sentiment"] == "MIXED"


def test_the_release_timing_is_kept(rows):
    """"During-hours" or "After-hours" -- the publisher's own answer to
    the 88%-after-12:30 problem, per company."""
    assert _by(rows, "ADANIENT")["released"] == "During-hours"


def test_the_reality_sentence_survives_the_line_breaks(rows):
    got = _by(rows, "ADANIENT")["reality"]
    assert "slipped 0.44%" in got
    assert "1,160.23 Cr" in got


def test_a_row_whose_grade_is_not_a_grade_is_refused():
    """A grade guessed off a broken line is the thing this project
    keeps deleting."""
    broken = ("Market Sentiment for July 29 Reportings\n"
              "1. Something (ABCD) Pulse: Ouring\n")
    assert rows_from_page(broken) == []


def test_an_unknown_ticker_is_dropped_when_a_universe_is_given():
    """OCR turns M&M into M_M. There is no honest way to guess which
    company a ticker that does not exist refers to."""
    got = rows_from_page(PAGE, known={"ADANIENT", "ASIANPAINT"})
    assert {r["symbol"] for r in got} == {"ADANIENT", "ASIANPAINT"}


# ---------------------------------------------------------------
# 2. THE PRICE MOVE -- WHERE THE TAPE ACTUALLY SPEAKS
# ---------------------------------------------------------------
@pytest.mark.parametrize("symbol,expected", [
    ("ADANIENT", -0.44),      # "slipped 0.44%"
    ("GOCOLORS", +6.79),      # "surged 6.79%"
    ("AHCL", -7.4),           # "fell 7.4%"
    ("ASIANPAINT", +0.11),    # "held steady (+0.11%)"
    ("ADANIPORTS", -0.11),    # "traded flat (-0.11%)" across a linebreak
])
def test_the_move_is_read_with_its_sign(rows, symbol, expected):
    assert price_move(_by(rows, symbol)) == pytest.approx(expected)


def test_a_row_with_no_stated_move_returns_none():
    page = ("Market Sentiment for July 29 Reportings\n"
            "1. Something (ADANIENT) Pulse: Good\n"
            "Sentiment: Positive\n"
            "Market Reality: After-hours release: results were in line.\n")
    assert price_move(rows_from_page(page)[0]) is None


# ---------------------------------------------------------------
# 3. DISAGREEMENT IS JUDGED ON THE TAPE, NEVER ON THE WORD
# ---------------------------------------------------------------
def test_the_sentiment_word_is_not_the_market(rows):
    """AHCL. Pulse Weak, Sentiment Positive, stock DOWN 7.4%.

    Comparing the grade against the Sentiment word would call this a
    disagreement and print "market positive" beside a 7.4% fall. The
    grade and the tape actually AGREE -- weak quarter, stock sold."""
    ahcl = _by(rows, "AHCL")
    assert ahcl["sentiment"] == "POSITIVE"
    assert price_move(ahcl) == pytest.approx(-7.4)
    assert not disagrees(ahcl)
    assert "TAPE AGREED" in headline_for(ahcl)


def test_a_real_disagreement_is_caught(rows):
    """GOCOLORS. Weak quarter, stock up 6.79%."""
    row = _by(rows, "GOCOLORS")
    assert disagrees(row)
    assert headline_for(row).startswith("TAPE DISAGREED: Weak result")
    assert "+6.79%" in headline_for(row)


def test_a_flat_day_is_not_an_answer(rows):
    """ASIANPAINT rose 0.11% on a Great quarter. Calling that a
    disagreement would manufacture a signal out of a flat tape."""
    row = _by(rows, "ASIANPAINT")
    assert not disagrees(row)
    assert "TAPE FLAT" in headline_for(row)


def test_no_move_means_no_verdict():
    page = ("Market Sentiment for July 29 Reportings\n"
            "1. Something (ADANIENT) Pulse: Weak\n"
            "Sentiment: Positive\n"
            "Market Reality: After-hours release: results were in line.\n")
    row = rows_from_page(page)[0]
    assert not disagrees(row)
    assert headline_for(row).startswith("MARKET REACTION")


# ---------------------------------------------------------------
# 4. HOW IT REACHES THE PANEL
# ---------------------------------------------------------------
def test_the_page_is_read_before_the_three_company_rule():
    """The rule that ate 258 rows. This is a table, not a recap."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    page_at = src.find("if is_sentiment_page(body):")
    rule_at = src.find("if len(symbols) >= 3:")
    assert 0 < page_at < rule_at


def test_market_answer_is_a_kind_the_store_accepts():
    from core.stock_events import USEFUL_KINDS
    assert "MARKET_ANSWER" in USEFUL_KINDS


def test_the_row_never_repeats_the_publishers_grade_as_evidence():
    """The row carries the same grade the result card already filed.
    Grading it again would count one opinion as two sources, which is
    what the support tally exists to prevent."""
    src = open("core/stock_events.py", encoding="utf-8").read()
    block = src[src.find("if is_sentiment_page(body):"):]
    block = block[:block.find("if is_digest(body):")]
    assert '"grade": None' in block


def test_the_chip_scores_nothing():
    """The move is YESTERDAY's and already in the price. Scoring it
    would reward a stock for having moved -- the "bought near the upper
    circuit" mistake the operator named himself."""
    src = open("core/shortlist.py", encoding="utf-8").read()
    block = src[src.find('elif (kind == "MARKET_ANSWER"'):]
    block = block[:block.find('elif kind == "CONCALL"')]
    assert "0.0" in block
