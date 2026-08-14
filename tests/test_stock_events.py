"""
Per-stock event memory.

    "we will use only useful news, images and store them in memory
     linked to respective stocks."       -- operator, 30 July 2026

The bot held 368 messages, 224 stories and 256 images. All retrievable,
none usable: answering "has anything happened to KAYNES this week" meant
reading messages. This turns the useful ones into typed rows with the
numbers pulled out.

Most of these tests are bugs found on real data during the first four
runs of the builder, written down so they cannot come back.
"""

import pytest

from core.stock_events import (
    StockEvents, amount_in_crore, classify, counterparty, grade_of, is_digest,
)


# ---------------------------------------------------------------
# WHAT KIND OF THING IS THIS
# ---------------------------------------------------------------

def test_a_graded_result_is_a_result():
    kind, scope = classify("#AARTIIND - Good Results - 10 seconds ago",
                           grade="GOOD", has_symbol=True)
    assert (kind, scope) == ("RESULT", "STOCK")


def test_an_order_win_is_an_order():
    kind, scope = classify(
        "Astra Microwave secures Rs. 2205.23 Cr order from HAL.",
        has_symbol=True)
    assert (kind, scope) == ("ORDER", "STOCK")


def test_an_order_needs_both_a_verb_and_a_noun():
    """"wins" alone is a football result. "contract" alone is a legal
    document. Together they are a company winning work."""
    kind, _ = classify("India wins the toss", has_symbol=False)
    assert kind != "ORDER"


def test_institutional_flow_is_never_one_stock():
    kind, scope = classify(
        "FIIs were net buyers of Rs 3,623.51 Cr in equities today",
        has_symbol=True)
    assert scope == "MARKET", (
        "FII flow is the whole market's, whatever tickers the post "
        "happens to mention")
    assert kind == "FLOW"


def test_macro_is_kept_but_never_pinned_to_a_stock():
    """A Fed hold explains why everything moved. Pinning it to six
    housing-finance companies is how one headline produced 140 false
    links in July."""
    kind, scope = classify(
        "Federal Reserve holds interest rates steady", has_symbol=False)
    assert (kind, scope) == ("MACRO", "MARKET")


def test_an_analysts_opinion_is_not_an_event():
    """It may be worth reading. It is not something that HAPPENED."""
    kind, _ = classify(
        "BROKERAGE CALL CLSA gives an 'Underperform' rating for Asian "
        "Paints with a target price of Rs 1,900", has_symbol=True)
    assert kind == "OPINION"


def test_the_channel_owner_talking_about_his_product_is_noise():
    for text in ("I worked on the new Bulk Deal view as a user didn't like",
                 "Happy to see the validation on the recent upgrades",
                 "Must Watch Shorts https://youtube.com/shorts/RoNxBbk1yoM"):
        kind, _ = classify(text, has_symbol=False)
        assert kind == "NOISE", text


# ---------------------------------------------------------------
# DIGESTS -- FOUR SHAPES, ALL FOUND ON REAL DATA
# ---------------------------------------------------------------
# A message carrying several stories records NO event, because the
# extractor pairs the wrong number with the wrong company:
#
#     3,404.57 cr from Kuwait     two unrelated stories, joined
#     10.00 cr from July          a date read as a counterparty
#
# A wrong number is worse than a missing one. A missing one looks
# missing.

def test_a_recap_is_a_digest():
    assert is_digest("Orderbook Recap\nDaily Highlights - JULY 28, 2026")


def test_a_bullet_list_is_a_digest():
    """"Crocs Inc. reported Q2 FY26 revenue of $1.18 billion" was
    recorded against MAHLIFE and SWIGGY with Rs 10,384 cr attached,
    because one post carried eight bulleted stories."""
    assert is_digest("EARNINGS\n• Crocs reported Q2\n• Microsoft surged 9%")


def test_three_tickers_make_a_digest():
    """A single story is about a single company, whatever formatting it
    arrives in."""
    assert is_digest("#TATASTEEL #INFY #RELIANCE all report tomorrow")


def test_emoji_separated_stories_are_a_digest():
    """News Pulse separates stories with a leading emoji rather than a
    bullet. TORNTPOWER was recorded against a Strait of Hormuz story
    that way."""
    assert is_digest("\U0001F30D IRGC targeted a US base "
                     "\U0001F1EE\U0001F1F3 Bank of England holds rates "
                     "\U0001F4C8 ByteDance restructured its AI business")


def test_a_single_story_is_not_a_digest():
    assert not is_digest(
        "Astra Microwave secures Rs. 2205.23 Cr order from HAL. #ASTRAMICRO")


# ---------------------------------------------------------------
# THE NUMBERS
# ---------------------------------------------------------------

@pytest.mark.parametrize("text,crore", [
    ("wins Rs 1,600 crore order", 1600.0),
    ("secures INR 3,404.57 crore project funding", 3404.57),
    ("Rs. 2205.23 Cr order from HAL", 2205.23),
    ("order worth Rs 91.57 Crores for civil works", 91.57),
    ("a Rs 250 lakh contract", 2.5),
])
def test_amounts_come_out_in_crore(text, crore):
    assert amount_in_crore(text) == crore


def test_a_bare_number_is_not_an_amount():
    """"25-30 crore orders per quarter" is a count of orders, not money
    -- but "targeting 25" with no currency marker must not become a
    figure at all."""
    assert amount_in_crore("targeting 25 per quarter") is None
    assert amount_in_crore("no numbers here") is None


def test_a_missing_amount_is_none_not_a_guess():
    """"wins optical fibre export order" is still an order."""
    assert amount_in_crore("HFCL wins optical fibre export order") is None


def test_the_counterparty_is_read_when_the_sentence_says_it():
    assert counterparty("Rs 5.26 crore order from Indian Railways.") \
        == "Indian Railways"


def test_a_month_is_never_a_customer():
    """"from July" came out of a digest and looked like a counterparty."""
    assert counterparty("highlights from July 28") is None


def test_the_grade_is_read_from_the_words_when_no_column_has_it():
    assert grade_of("#ASAHISONG - Excellent Results") == "EXCELLENT"
    assert grade_of("anything at all", given="weak") == "WEAK"
    assert grade_of("no grade here") is None


# ---------------------------------------------------------------
# THE STORE
# ---------------------------------------------------------------

def test_events_are_stored_and_read_back_per_stock(tmp_path):
    store = StockEvents(db_path=str(tmp_path / "e.db"))
    assert store.remember("ASTRAMICRO", "2026-07-30T13:47", "ORDER",
                          "secures Rs 2205.23 Cr order from HAL",
                          value_cr=2205.23, counterparty="HAL")
    rows = store.for_symbol("ASTRAMICRO")
    assert len(rows) == 1
    assert rows[0]["value_cr"] == 2205.23
    assert rows[0]["counterparty"] == "HAL"


def test_rerunning_the_builder_does_not_double_everything(tmp_path):
    """Re-running is how an improved matcher reaches yesterday's data.
    A backfill that doubles its rows on the second run is one nobody
    dares repeat."""
    store = StockEvents(db_path=str(tmp_path / "e.db"))
    args = ("KAYNES", "2026-07-30T13:41", "RESULT", "Excellent Results")
    assert store.remember(*args) is True
    assert store.remember(*args) is False
    assert len(store.for_symbol("KAYNES")) == 1


def test_noise_and_opinion_are_never_stored(tmp_path):
    store = StockEvents(db_path=str(tmp_path / "e.db"))
    assert store.remember("X", "2026-07-30", "NOISE", "youtube link") is False
    assert store.remember("X", "2026-07-30", "OPINION", "buy rating") is False
    assert store.for_symbol("X") == []


def test_market_context_is_kept_apart_from_stock_events(tmp_path):
    """A TIME BOMB, found 31 July 2026 at 13:47.

    This used to write both events at the hardcoded date "2026-07-30",
    which parses as midnight. market_context() and recent() look back
    36 HOURS. So the test passed all of 30 July, passed on the morning
    of the 31st, and started failing at roughly 12:00 that afternoon --
    the moment midnight-on-the-30th fell out of the window.

    Nothing was broken. The clock simply moved, and a test that had
    been green for a day went red in the middle of a live session,
    while unrelated work was being verified. That is the worst possible
    moment to be handed a false alarm.

    The subject here is SEPARATION -- market context must never be
    filed against a stock -- and separation has nothing to do with what
    day it is. So the events are written relative to NOW, which is what
    the code under test actually measures against.
    """
    from datetime import datetime, timedelta

    recent_enough = (datetime.now() - timedelta(hours=2)).isoformat()

    store = StockEvents(db_path=str(tmp_path / "e.db"))
    store.remember(None, recent_enough, "MACRO", "Fed holds rates",
                   scope="MARKET")
    store.remember("KAYNES", recent_enough, "RESULT", "Great", scope="STOCK")
    assert len(store.market_context()) == 1
    assert len(store.recent(scope="STOCK")) == 1
    assert store.for_symbol("KAYNES")[0]["kind"] == "RESULT"


def test_a_broken_database_costs_the_panel_not_the_session(tmp_path):
    store = StockEvents(db_path=str(tmp_path / "nested" / "e.db"))
    store.db_path = "/nonexistent/path/e.db"
    assert store.for_symbol("KAYNES") == []
    assert store.remember("K", "2026-07-30", "NEWS", "x") is False
