"""
==========================================================
Tests -- Stock Memory (per-stock corporate-action facts)
==========================================================

The operator's own proposal: the bot must KNOW what is happening to a
share before it trades it. The concrete case these tests pin down is
JLHL on 2026-07-24 -- a 2:10 split that the bot read as an -80% crash
because our previous close was the unadjusted one.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import date, timedelta

from core.corporate_actions import classify_purpose, _parse_date
from core.stock_memory import StockMemory


def _mem(tmp_path):
    return StockMemory(url="sqlite:///" + os.path.join(str(tmp_path), "m.db"))


TODAY = date(2026, 7, 24)


# ---------------------------------------------------------------
# Storing facts
# ---------------------------------------------------------------

def test_remembers_a_fact_once(tmp_path):
    m = _mem(tmp_path)
    assert m.remember("JLHL", "SPLIT", TODAY, "2:10", "NSE") is True
    assert m.remember("JLHL", "SPLIT", TODAY, "2:10", "NSE") is False   # dedup
    assert m.count() == 1


def test_symbol_and_action_are_normalised(tmp_path):
    m = _mem(tmp_path)
    m.remember(" jlhl ", "split", TODAY)
    assert m.facts_for("JLHL", TODAY)[0]["action_type"] == "SPLIT"


def test_incomplete_facts_are_refused(tmp_path):
    m = _mem(tmp_path)
    assert m.remember("", "SPLIT", TODAY) is False
    assert m.remember("JLHL", "", TODAY) is False
    assert m.remember("JLHL", "SPLIT", None) is False
    assert m.count() == 0


# ---------------------------------------------------------------
# THE JLHL CASE -- the reason this module exists
# ---------------------------------------------------------------

def test_jlhl_split_is_flagged_as_price_distorting(tmp_path):
    """2026-07-24: JLHL did a 2:10 split. The bot saw -80% and ranked it
    the day's biggest loser. With memory, it is known and excluded."""
    m = _mem(tmp_path)
    m.remember("JLHL", "SPLIT", TODAY, "Face value split 2:10", "NSE")
    distorting = m.price_distorting_symbols(TODAY)
    assert "JLHL" in distorting
    assert "SPLIT" in distorting["JLHL"][0]


def test_dividend_also_distorts_the_price(tmp_path):
    """A stock going ex-dividend opens lower by the dividend. That is
    not weakness and shorting it is a mistake."""
    m = _mem(tmp_path)
    m.remember("ITC", "DIVIDEND", TODAY, "Interim dividend Rs 6", "NSE")
    assert "ITC" in m.price_distorting_symbols(TODAY)


def test_informational_actions_do_not_block(tmp_path):
    """A board meeting is memory, not a veto."""
    m = _mem(tmp_path)
    m.remember("TCS", "BOARD_MEETING", TODAY, "Q1 results", "NSE")
    assert "TCS" not in m.price_distorting_symbols(TODAY)
    assert m.facts_for("TCS", TODAY)          # but it IS remembered


def test_the_window_covers_the_day_before_and_after(tmp_path):
    """The distortion straddles the ex-date: the day BEFORE is when the
    old close becomes stale."""
    m = _mem(tmp_path)
    m.remember("JLHL", "SPLIT", TODAY)
    assert "JLHL" in m.price_distorting_symbols(TODAY - timedelta(days=1))
    assert "JLHL" in m.price_distorting_symbols(TODAY + timedelta(days=1))
    assert "JLHL" not in m.price_distorting_symbols(TODAY + timedelta(days=5))


def test_unrelated_days_are_clean(tmp_path):
    m = _mem(tmp_path)
    m.remember("JLHL", "SPLIT", TODAY)
    assert m.price_distorting_symbols(date(2026, 8, 20)) == {}


# ---------------------------------------------------------------
# Parsing the exchanges' messy strings
# ---------------------------------------------------------------

def test_purpose_classification_covers_the_real_formats():
    assert classify_purpose("Face Value Split From Rs.10/- To Rs.2/-") == "SPLIT"
    assert classify_purpose("Bonus issue 1:1") == "BONUS"
    assert classify_purpose("Interim Dividend - Rs 4/- per share") == "DIVIDEND"
    assert classify_purpose("Rights Issue") == "RIGHTS"
    assert classify_purpose("Scheme of Arrangement") == "DEMERGER"
    assert classify_purpose("Sub-Division of shares") == "SPLIT"
    # Not price-affecting -> not classified at all
    assert classify_purpose("Analyst meet") is None
    assert classify_purpose("") is None
    assert classify_purpose(None) is None


def test_date_parsing_handles_exchange_formats():
    assert _parse_date("24-Jul-2026") == date(2026, 7, 24)
    assert _parse_date("2026-07-24") == date(2026, 7, 24)
    assert _parse_date("24/07/2026") == date(2026, 7, 24)
    assert _parse_date("garbage") is None
    assert _parse_date(None) is None
