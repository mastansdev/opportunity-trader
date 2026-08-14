"""
==========================================================
Every company the channels name, and nothing else
==========================================================

    "yeah what ever the stocks we are not maintained in our master
     data base pls add them in our universe."
                                    -- operator, 2 August 2026

BIRLACABLE was on the 02 August calendar card, tagged in the caption
and printed on the picture, and the discovery tool never saw it --
it read the typed caption only, and that message's caption tag sat
alongside the picture where the rest of the names were.

THE THREE SOURCES
-----------------
    1  hashtags in the typed caption          the original
    2  hashtags in the image transcript       the channel's own ticker
    3  tokens inside the DURING / AFTER
       company blocks of a calendar card      a list of companies by
                                              construction

    candidates before   837    unknown   254
    candidates after  1,340    unknown   751

WHY NOT "READ ALL THE OCR"
--------------------------
Measured on the store, every ticker-shaped word in every transcript
is 14,052 unknown tokens, and the top of that list is:

    YOY 4871   REVENUE 3695   GROWTH 3565   THE 3299   AND 2774

Narrowed to the company blocks of the calendar cards it is 508, and
the real names fall out: BIRLACABLE, SHANTIGEAR, HAWKINCOOK,
HEIDELBERG, KAMDHENU, VISL, J_KBANK.

Prose still comes with it. That is safe here and only here, because
nothing in this tool decides anything -- Dhan's scrip master is the
judge, and Dhan does not list a company called THE.

THE TRAP THIS FIX WALKS INTO, AND THE GUARD
-------------------------------------------
A discovered row is written with COMPANY NAME set to the ticker,
because Dhan's compact master carries no company name. A one-word
COMPANY NAME of five characters or more becomes a SOLO entry in the
name index -- so HEIDELBERG would match any sentence about the German
city. That is the URBAN COMPANY bug of 1 August arriving 751 at a
time, on the panel he clicks BUY from.

So the name index refuses any COMPANY NAME equal to its own SYMBOL.
The TICKER index is untouched: #HEIDELBERG still resolves, which is
how these stocks are meant to be recognised.

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust"

Author : H&M Opportunity Trader
==========================================================
"""

import sys

import pytest

sys.path.insert(0, ".")

from core.telegram_feed import TelegramFeed
from tools.discover_stocks import _from_calendar_card, candidates

FLAT_CARD = (
    "\U0001F4C5 Today Earnings - 02 Aug, 2026\n"
    "Key companies reporting results: #PERSISTENT #BIRLACABLE\n"
    "TODAY\nEARNINGS\n02 Aug, 2026 - 2 Companies\n"
    "PERSISTENT BIRLACABLE\n@market_pulse_ai")

SPLIT_CARD = (
    "EARNINGS PULSE RECAP\n31 Jul, 2026\n"
    "During Market\n@ SHANTIGEAR @ YASHO\n"
    "After Market\n@ HAWKINCOOK @ CORONA")

BRIEF = ("#IPL - Weak Results\nIndia Pesticides\n"
         "Metric QoQ YoY Jun'26\nSales -6% -9% 252\nREVENUE PAT EPS GROWTH")


# ---------------------------------------------------------------
# 1. THE CALENDAR CARD GIVES UP ITS NAMES
# ---------------------------------------------------------------
def test_a_card_with_no_columns_still_yields_its_companies():
    got = _from_calendar_card(FLAT_CARD)
    assert "BIRLACABLE" in got and "PERSISTENT" in got


def test_a_card_with_columns_yields_both_sides():
    got = _from_calendar_card(SPLIT_CARD)
    assert "SHANTIGEAR" in got, "the DURING block was not read"
    assert "HAWKINCOOK" in got, "the AFTER block was not read"


def test_an_ordinary_result_brief_yields_nothing():
    """THE ONE THAT KEEPS THE FLOOD OUT. If this ever returns tokens,
    14,052 words of English prose join the candidate list and the tool
    starts asking Dhan about REVENUE and GROWTH."""
    assert _from_calendar_card(BRIEF) == []
    assert _from_calendar_card("") == []
    assert _from_calendar_card("just some news about a company") == []


def test_the_card_furniture_is_not_offered_as_a_company():
    got = _from_calendar_card(SPLIT_CARD)
    for word in ("EARNINGS", "PULSE", "RECAP", "DURING", "AFTER", "MARKET"):
        assert word not in got


# ---------------------------------------------------------------
# 2. THE CANDIDATE LIST READS THE PICTURE TOO
# ---------------------------------------------------------------
def test_candidates_reads_the_transcript_as_well_as_the_caption(tmp_path,
                                                                monkeypatch):
    import sqlite3

    import tools.discover_stocks as tool
    path = tmp_path / "telegram.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE messages (text TEXT, ocr_text TEXT)")
    conn.executemany("INSERT INTO messages VALUES (?, ?)", [
        ("#TYPEDONLY reports today", ""),
        ("", "#PICTUREONLY - Weak Results"),
        ("", FLAT_CARD),
    ])
    conn.commit()
    conn.close()
    monkeypatch.setattr(tool, "TELEGRAM_DB", str(path))
    got = tool.candidates()
    assert "TYPEDONLY" in got, "the caption source was lost"
    assert "PICTUREONLY" in got, "a hashtag on the picture was not read"
    assert "BIRLACABLE" in got, "the calendar card source was lost"


def test_a_broken_store_returns_nothing_rather_than_raising(monkeypatch,
                                                            tmp_path):
    # Not under data/: sqlite3.connect() creates the file it is given,
    # and this left an empty data/no-such-file-at-all.db behind.
    import tools.discover_stocks as tool
    monkeypatch.setattr(tool, "TELEGRAM_DB", str(tmp_path / "no-such-store.db"))
    assert tool.candidates() == {}


# ---------------------------------------------------------------
# 3. THE GUARD -- A PLACEHOLDER IS NOT A NAME
# ---------------------------------------------------------------
class FakeMaster:
    def __init__(self, rows):
        self._rows = rows

    def all_symbols(self, include_blocked=False):
        return list(self._rows)

    def get_by_symbol(self, symbol):
        return self._rows.get(symbol)


def _feed(rows):
    feed = TelegramFeed(client=None, master_loader=FakeMaster(rows),
                        db_path=":memory:", read_images=False)
    return feed


def test_a_discovered_row_never_becomes_a_name_the_matcher_hunts():
    """HEIDELBERG written as its own COMPANY NAME would match any
    sentence about the German city. 751 candidates, one URBANCO each.

    A discovered row is identity ONLY -- no SECTOR -- which is what
    marks it as a placeholder."""
    feed = _feed({"HEIDELBERG": {"COMPANY NAME": "HEIDELBERG",
                                 "SECTOR": ""}})
    assert feed.names_in(
        "the conference was held in Heidelberg last week") == []


def test_a_curated_stock_whose_name_is_its_ticker_still_matches():
    """THE ONE THE FIRST VERSION OF THIS GUARD BROKE. DOLLAR is a real
    company called DOLLAR, curated, tradeable, measured 37 fired and 37
    genuine. "name equals symbol" alone would have dropped it -- the
    missing half is that a placeholder has no SECTOR either."""
    feed = _feed({"DOLLAR": {"COMPANY NAME": "DOLLAR",
                             "SECTOR": "TEXTILES & APPAREL"}})
    assert feed.names_in("Dollar Industries posts strong Q1") == ["DOLLAR"]


def test_a_real_one_word_name_still_matches():
    """INDEGENE LIMITED really is a one-word name and must keep
    working -- the guard is about placeholders, not about one-word
    companies."""
    feed = _feed({"INDEGENE": {"COMPANY NAME": "INDEGENE LIMITED"}})
    assert feed.names_in("Indegene reported strong Q1 numbers") == \
        ["INDEGENE"]


def test_a_real_two_word_name_still_matches():
    feed = _feed({"AARTIIND": {"COMPANY NAME": "AARTI INDUSTRIES LIMITED"}})
    assert feed.names_in("Aarti Industries posted a beat") == ["AARTIIND"]


def test_the_ticker_still_resolves_for_a_discovered_stock():
    """The whole point of adding it. The NAME is refused; the SYMBOL
    is exactly how these companies are named on the cards."""
    feed = _feed({"HEIDELBERG": {"COMPANY NAME": "HEIDELBERG"}})
    assert "HEIDELBERG" in feed.symbols_in("#HEIDELBERG reports today")


# ---------------------------------------------------------------
# 4. WHAT GETS WRITTEN
# ---------------------------------------------------------------
def test_a_discovered_row_is_not_tradeable():
    """Identifiable and tradeable are different things. BIRLACABLE
    trades in the BE series under band 5 surveillance -- being able to
    read its results is not a reason to buy it at 4X on MTF.
    morning_universe.py decides tradeability by measuring turnover,
    and it should keep deciding it."""
    src = open("tools/discover_stocks.py", encoding="utf-8").read()
    block = src[src.find("for tag, count, sid in real:"):]
    assert 'row["SUBSCRIBE"] = "NO"' in block


def test_the_master_is_backed_up_before_it_is_touched():
    src = open("tools/discover_stocks.py", encoding="utf-8").read()
    assert "shutil.copy(MASTER_CSV, backup)" in src


def test_dhan_is_the_judge_not_a_keyword_list():
    """The prose that comes with the widened search is only safe
    because nothing here decides. If the tool ever writes a row without
    a security id from Dhan, THE and AND enter the master."""
    src = open("tools/discover_stocks.py", encoding="utf-8").read()
    assert "(real if security_id else not_listed)" in src
