"""
==========================================================
Which way does the news point?
==========================================================

31 July 2026, on the operator's own screen, row 8 of the gainers:

    BAJFINANCE  up 8.10%  score 20.1
      NEWS BROKER: UBS issues 'sell' tag on Bajaj Finance
      [ BUY ]

UBS said SELL. The bot matched the right company, printed the words,
and added +4.0 -- because BROKER was one flat number and an upgrade
and a downgrade were worth the same.

Three more categories had the identical defect:

    GUIDANCE    "cuts FY27 guidance"        scored +3.0
    LEGAL       "wins arbitration award"    scored -4.0
    MANAGEMENT  "appoints new MD"           scored -2.0

The category answers WHAT happened. It was also being asked WHICH WAY
it cuts, which is a different question, and for these four the answer
is in the words rather than the category.

WHAT THIS FILE GUARDS
---------------------
That the sign is read, and that reading it never becomes a guess. A
NEUTRAL verdict is a real answer here: "Citi maintains Hold" is a
non-event and must score near zero rather than be forced positive or
negative.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.news_watcher import classify_impact, classify_stance
from core.shortlist import ShortlistBuilder


@pytest.fixture
def builder():
    """The scorer without any database behind it.

    _news_points() reads nothing but the item it is handed, so an
    unconstructed instance is enough and keeps the test honest about
    what it is exercising.
    """
    return ShortlistBuilder.__new__(ShortlistBuilder)


def _points(builder, headline):
    kind = classify_impact(headline)
    assert kind is not None, f"not classified at all: {headline}"
    return builder._news_points({"kind": kind, "headline": headline})


# ---------------------------------------------------------------
# 1. THE HEADLINE THAT WAS LIVE ON THE SCREEN
# ---------------------------------------------------------------
def test_the_bajaj_finance_sell_tag_scores_negative(builder):
    """The exact string from the 31 July dashboard. Before the fix this
    returned +4.0."""
    points, stance = _points(
        builder, "UBS issues 'sell' tag on Bajaj Finance before housing "
                 "unit board")
    assert stance == "NEGATIVE"
    assert points < 0, "a sell rating must not add to a long score"


def test_an_upgrade_and_a_downgrade_do_not_score_the_same(builder):
    """The whole bug in one assertion."""
    up, _ = _points(builder, "Morgan Stanley upgrades Infosys to Overweight")
    down, _ = _points(builder, "Jefferies downgrades Tata Power to Hold")
    assert up > 0 > down


# ---------------------------------------------------------------
# 2. THE OLD RATING IS NOT THE NEW ONE
# ---------------------------------------------------------------
def test_downgraded_to_hold_from_buy_is_negative(builder):
    """"downgrades to Hold from Buy" contains the word Buy.

    Reading rating words before the analyst ACTION would score this as
    good news, which is why the stance rules put upgrade/downgrade
    first. This is the test that pins that ordering.
    """
    points, stance = _points(builder,
                             "Motilal downgrades Titan to Hold from Buy")
    assert stance == "NEGATIVE"
    assert points < 0


@pytest.mark.parametrize("headline,expected", [
    ("CLSA cuts target price on Asian Paints to Rs 2,100", "NEGATIVE"),
    ("Nomura raises target price on Titan to Rs 4,500", "POSITIVE"),
    ("UBS initiates coverage on CarTrade with Buy, target Rs 4,000",
     "POSITIVE"),
    ("Goldman initiates coverage on ABC with Sell rating", "NEGATIVE"),
])
def test_target_moves_and_initiations(builder, headline, expected):
    assert classify_stance("BROKER", headline) == expected


# ---------------------------------------------------------------
# 3. NEUTRAL IS AN ANSWER, NOT A FAILURE
# ---------------------------------------------------------------
def test_maintaining_a_hold_is_close_to_nothing(builder):
    """A reiteration is not news. It must not be forced into a
    direction just because the sentence mentions a broker."""
    points, stance = _points(builder, "Citi maintains Neutral on HDFC Bank")
    assert stance == "NEUTRAL"
    assert abs(points) <= 1.0


# ---------------------------------------------------------------
# 4. THE OTHER THREE TWO-WAY CATEGORIES
# ---------------------------------------------------------------
def test_cutting_guidance_is_not_the_same_as_raising_it(builder):
    cut, _ = _points(builder, "Tata Power cuts FY27 guidance on weak demand")
    raise_, _ = _points(builder,
                        "Company raises FY27 revenue guidance after strong Q1")
    assert cut < 0 < raise_


def test_winning_a_case_is_good_news(builder):
    """The LEGAL category assumed every court story was a disaster. An
    arbitration award WON is a cash inflow."""
    points, stance = _points(
        builder, "XYZ wins arbitration award of Rs 450 crore against NHAI")
    assert stance == "POSITIVE"
    assert points > 0


def test_insolvency_is_still_bad_news(builder):
    """The fix must not flip the category. Most LEGAL news is bad and
    has to stay bad."""
    points, _ = _points(builder, "ABC Ltd admitted to insolvency by NCLT")
    assert points < 0


def test_a_cfo_resigning_is_negative(builder):
    """\\b does not match between the n of "resign" and its s.

    The first draft of the stance rules used \\bresign\\b and scored
    "Infosys CFO resigns with immediate effect" as NEUTRAL -- the exact
    kind of silent miss this whole change exists to remove.
    """
    points, stance = _points(builder,
                             "Infosys CFO resigns with immediate effect")
    assert stance == "NEGATIVE"
    assert points < 0


# ---------------------------------------------------------------
# 5. THE FIVE ONE-WAY CATEGORIES MUST NOT CHANGE
# ---------------------------------------------------------------
@pytest.mark.parametrize("headline", [
    "Fire breaks out at Gandhar Oil Silvassa plant",
    "SEBI bars ABC Ltd from the securities market",
])
def test_categories_with_a_fixed_sign_stay_negative(builder, headline):
    points, stance = _points(builder, headline)
    assert stance is None, "a fire is never good news; it needs no stance"
    assert points < 0


def test_an_order_win_is_still_positive(builder):
    points, stance = _points(builder,
                             "Reliance bags Rs 2,205 crore order from NTPC")
    assert stance is None
    assert points > 0


# ---------------------------------------------------------------
# 6. THE STANCE SURVIVES THE TRIP FROM COLLECTION TO SCORE
# ---------------------------------------------------------------
def test_an_item_with_no_stance_field_is_still_scored_correctly(builder):
    """Items reach the score from places other than the RSS watcher --
    a replayed session, a test, Telegram. Those have no stance field,
    and defaulting them to NEUTRAL would quietly restore the bug for
    every path except the one that was fixed."""
    points, stance = builder._news_points({
        "kind": "BROKER",
        "headline": "UBS issues 'sell' tag on Bajaj Finance"})
    assert stance == "NEGATIVE"
    assert points < 0


def test_a_stance_already_on_the_item_is_trusted(builder):
    points, stance = builder._news_points({
        "kind": "BROKER", "stance": "POSITIVE", "headline": ""})
    assert stance == "POSITIVE"
    assert points > 0
