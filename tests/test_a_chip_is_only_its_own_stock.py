"""
==========================================================
A stock's chip must be built from that stock's cards only
==========================================================

    "0 knowlede is far better than half knowledge"
    "so pls do not miss or club one data to other stock"
    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"
                                -- operator, 8 August 2026

WHAT THIS PROTECTS
------------------
Measured on the real store, 8 August 2026:

    SIEMENS   22 messages fed its chip, 4 of them about ENRIN
              (Siemens Energy India, a separate listed company)

    and quoted INSIDE the SIEMENS chip:
        "a 22% YoY net profit rise to Rs 518 Cr as soft like-for-like
         fashion volume growth"

    -- which is TRENT. A retailer's like-for-like fashion volumes
    scored into an engineering company's earnings verdict, producing
    AVOID at -1.2.

    GLAND     14 messages, 5 about NEULANDLAB -> "Revenue +2008% YoY"
    TOTAL     38 messages, 5 about DMART

560 of 1,824 single-stock cards carried a symbol that disagreed with
the card's own hashtag.

These tests use the SAME similar-name pairs that actually collided,
because a gate that passes on invented data proves nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core import subject


# ---------------------------------------------------------------
# The real collisions
# ---------------------------------------------------------------
def test_uno_minda_is_not_minda_corp():
    """Two different listed companies, one confusable name."""
    card = "#UNOMINDA - WEAK RESULTS - UNO MINDA AUTO reports Q1"
    assert subject.is_about("UNOMINDA", card) is True
    assert subject.is_about("MINDACORP", card) is False


def test_welspun_corp_is_not_welspun_enterprises():
    card = "#WELENT - WEAK RESULTS - WELSPUN ENTERPRISES Q1 FY27"
    assert subject.is_about("WELENT", card) is True
    assert subject.is_about("WELCORP", card) is False


def test_siemens_energy_is_not_siemens():
    """The pair that put TRENT's numbers in SIEMENS's chip."""
    card = "#ENRIN Siemens Energy India Q1 results, PAT up 22%"
    assert subject.is_about("ENRIN", card) is True
    assert subject.is_about("SIEMENS", card) is False


def test_gland_does_not_inherit_neuland():
    card = "#NEULANDLAB Neuland Laboratories Q1 CONS NET PROFIT"
    assert subject.is_about("NEULANDLAB", card) is True
    assert subject.is_about("GLAND", card) is False


def test_the_word_total_in_a_dmart_card_is_not_the_ticker_TOTAL():
    card = "#DMART Avenue Supermarts: total revenue up 18% YoY"
    assert subject.is_about("DMART", card) is True
    assert subject.is_about("TOTAL", card) is False


# ---------------------------------------------------------------
# List cards belong to nobody
# ---------------------------------------------------------------
def test_the_week_ahead_calendar_is_evidence_about_no_one():
    """It names 155 companies. It is about all of them, so it is
    about none of them, and it must not feed a single stock's chip."""
    card = ("The Week Ahead: Earnings Calendar Key companies: "
            "#BHARTIARTL #SBIN #LICI #TITAN #ONGC #DIVISLAB #HAL "
            "#HINDALCO #GRASIM #TRENT")
    for symbol in ("BHARTIARTL", "SBIN", "TRENT", "HINDALCO"):
        assert subject.is_about(symbol, card) is False, (
            f"{symbol} took the earnings calendar as evidence about "
            f"itself")


def test_two_stocks_on_one_card_is_still_allowed():
    """A genuine comparison card naming two companies is about both.
    Only a LIST (5+) is disqualified."""
    card = "#HDFCBANK and #ICICIBANK both report margin expansion"
    assert subject.is_about("HDFCBANK", card) is True
    assert subject.is_about("ICICIBANK", card) is True


# ---------------------------------------------------------------
# Topic hashtags are not companies
# ---------------------------------------------------------------
def test_a_topic_hashtag_does_not_make_a_card_subjectless():
    """#STOCKSTOWATCH is a topic. The card is still about HAL."""
    card = "#STOCKSTOWATCH #HAL wins order from Ministry of Defence"
    assert subject.is_about("HAL", card) is True


def test_a_card_with_only_topic_tags_is_about_nobody():
    card = "#MORNINGMARKETWITHDTT Nifty opens flat, LICI in focus"
    assert subject.is_about("LICI", card) is False


# ---------------------------------------------------------------
# Punctuation must not split a real match
# ---------------------------------------------------------------
def test_M_and_M_matches_its_underscored_hashtag():
    card = "#M_M Mahindra & Mahindra Q1 results"
    assert subject.is_about("M&M", card) is True


# ---------------------------------------------------------------
# The filter, not just the predicate
# ---------------------------------------------------------------
def test_only_keeps_the_stocks_own_cards():
    messages = [
        ("Earnings Pulse", "#SIEMENS Siemens Ltd Q1 PAT up"),
        ("Earnings Pulse", "#ENRIN Siemens Energy India Q1"),
        ("Day Trader Telugu", "#TRENT 22% YoY net profit rise to Rs 518 Cr"),
    ]
    kept = subject.only("SIEMENS", messages)
    assert len(kept) == 1
    assert "Siemens Ltd" in kept[0][1]


def test_audit_explains_why_a_chip_went_blank():
    """A chip that vanishes must be able to say why."""
    messages = [("x", "#ENRIN Siemens Energy Q1"),
                ("x", "#TRENT fashion volumes soft")]
    got = subject.audit("SIEMENS", messages)
    assert got["kept"] == 0
    assert got["dropped"] == 2
    assert "SIEMENS" in got["why"]


def test_it_never_raises_on_junk():
    """This runs on OCR output. It must not be the thing that breaks."""
    for junk in (None, "", "   ", "###", "#", 12345, b"bytes"):
        assert subject.is_about("INFY", junk) in (True, False)
    assert subject.only("INFY", None) == []
    assert subject.only(None, [("a", "#INFY")]) == []


# ---------------------------------------------------------------
# The wiring -- the gate has to be IN the path, not merely exist
# ---------------------------------------------------------------
def test_the_dashboard_actually_applies_the_gate():
    """core/result_tag.py was written, validated, and imported by
    nothing for a day. That must not happen to this one."""
    import inspect

    from dashboard import state
    src = inspect.getsource(state)
    assert "subject.only(" in src, (
        "core/subject.py exists but dashboard/state.py does not use it "
        "-- the chips are still built from mentions")
    # and it must run BEFORE the read, not after
    before = src.split("result_read.read(")[0]
    assert "subject.only(" in before[-1500:], (
        "the gate is applied after the chip is already built")
