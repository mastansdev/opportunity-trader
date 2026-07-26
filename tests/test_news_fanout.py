"""
News fan-out and routine-filing filters -- 2026-07-26.

Operator opened http://127.0.0.1:8050 and said the news build was "not at
all correct". The store held:

    12,831 rows from 1,034 real headlines  =  12.4 copies of each
    93% BROAD tier

The worst single case: one Vedanta trading-window notice stored against
264 symbols, including ABB, AMBER, ASHOKLEY and BAJAJ-AUTO -- every name
whose SECTOR / THEMES / COMMODITY_EXPOSURE mentions steel.
"""

import pytest

from news_bot.matching import is_routine_filing


# ---------------------------------------------------------------
# Routine filings carry no trading signal
# ---------------------------------------------------------------

@pytest.mark.parametrize("subject", [
    "Vedanta Limited has informed the Exchange regarding the Trading Window",
    "JINDAL STEEL LIMITED has informed the Exchange regarding Appointment of Mr X",
    "Tata Steel Limited has informed the Exchange about Disclosure under Regulation 30",
    "Company has informed about Schedule of analyst conference call",
    "Intimation of Investor Presentation",
    "Transcript of the earnings call",
    "Loss of share certificate",
    "Shareholding Pattern for the quarter",
    "Newspaper Publication of the audited financial results",
])
def test_routine_filings_are_dropped(subject):
    assert is_routine_filing(subject.upper()) is True


@pytest.mark.parametrize("subject", [
    "Financial Results for the quarter ended June 2026",
    "Unaudited Financial Results",
    "Company bags order worth Rs 500 crore",
    "Board approves stock split 1:5",
    "Plant fire halts production at the Gujarat unit",
    "Company receives USFDA approval for its facility",
])
def test_real_news_survives(subject):
    assert is_routine_filing(subject.upper()) is False


def test_results_beat_the_routine_markers():
    """'Financial Results' often shares a subject line with a routine
    phrase. The numbers must win -- unless it is only the newspaper copy
    of them."""
    assert is_routine_filing(
        "OUTCOME OF BOARD MEETING - FINANCIAL RESULTS AND RECORD DATE") is False
    assert is_routine_filing(
        "NEWSPAPER PUBLICATION OF FINANCIAL RESULTS") is True


def test_empty_text_is_not_routine():
    assert is_routine_filing("") is False
    assert is_routine_filing(None) is False


# ---------------------------------------------------------------
# A named company does not fan out to its whole sector
# ---------------------------------------------------------------

class _FakeLoader:
    """Two steel names and one unrelated electrical name that merely has
    'STEEL' in its theme text -- the ABB case."""

    ROWS = {
        "VEDL": dict({
            "SECURITY ID": "1", "SYMBOL": "VEDL",
            "COMPANY NAME": "VEDANTA LIMITED", "SECTOR": "METALS",
            "INDUSTRY": "STEEL", "CORE BUSINESS": "MINING",
            "BUSINESS_TYPE": "MANUFACTURER", "OWNERSHIP": "PRIVATE",
            "COMMODITY_EXPOSURE": "STEEL", "ECONOMIC_SENSITIVITY": "NONE",
            "KEYWORDS": "STEEL", "THEMES": "STEEL",
        }),
        "TATASTEEL": dict({
            "SECURITY ID": "2", "SYMBOL": "TATASTEEL",
            "COMPANY NAME": "TATA STEEL LIMITED", "SECTOR": "METALS",
            "INDUSTRY": "STEEL", "CORE BUSINESS": "STEEL",
            "BUSINESS_TYPE": "MANUFACTURER", "OWNERSHIP": "PRIVATE",
            "COMMODITY_EXPOSURE": "STEEL", "ECONOMIC_SENSITIVITY": "NONE",
            "KEYWORDS": "STEEL", "THEMES": "STEEL",
        }),
        "ABB": dict({
            "SECURITY ID": "3", "SYMBOL": "ABB",
            "COMPANY NAME": "ABB INDIA LIMITED", "SECTOR": "CAPITAL GOODS",
            "INDUSTRY": "ELECTRICAL", "CORE BUSINESS": "AUTOMATION",
            "BUSINESS_TYPE": "MANUFACTURER", "OWNERSHIP": "MNC",
            "COMMODITY_EXPOSURE": "STEEL", "ECONOMIC_SENSITIVITY": "NONE",
            "KEYWORDS": "AUTOMATION", "THEMES": "STEEL",
        }),
    }

    def all_symbols(self, include_blocked=False):
        return list(self.ROWS)

    def get_by_symbol(self, symbol):
        return self.ROWS.get(symbol)

    def load(self):
        return len(self.ROWS)


class _Item:
    def __init__(self, title, summary="", known_symbol=None):
        self.title = title
        self.summary = summary
        self.known_symbol = known_symbol


@pytest.fixture
def matcher():
    from news_bot.matching import NewsMatcher
    return NewsMatcher(loader=_FakeLoader())


def test_a_named_company_does_NOT_fan_out(matcher):
    """THE bug. A Vedanta filing is about Vedanta -- not about ABB."""
    result = matcher.match(_Item(
        "Vedanta Limited reports a fire at its smelter",
        known_symbol="VEDL"))
    symbols = {m.symbol for m in result.matches}
    assert symbols == {"VEDL"}
    assert "ABB" not in symbols
    assert "TATASTEEL" not in symbols


def test_company_name_in_the_text_also_stops_the_fan_out(matcher):
    result = matcher.match(_Item("TATA STEEL LIMITED wins a large order"))
    assert {m.symbol for m in result.matches} == {"TATASTEEL"}


def test_sector_news_naming_NOBODY_still_fans_out(matcher):
    """This is what BROAD is for. 'Steel prices surge' names no company,
    and there the whole sector genuinely is the story."""
    result = matcher.match(_Item("Steel prices surge on new import duty"))
    symbols = {m.symbol for m in result.matches}
    assert symbols == {"VEDL", "TATASTEEL", "ABB"}
    assert all(m.tier == "BROAD" for m in result.matches)


def test_a_routine_filing_produces_no_matches_at_all(matcher):
    result = matcher.match(_Item(
        "Vedanta Limited has informed the Exchange regarding the Trading "
        "Window closure", known_symbol="VEDL"))
    assert result.matches == []


# ---------------------------------------------------------------
# Short symbols that are also ordinary English words
# ---------------------------------------------------------------

def test_a_lowercase_english_word_is_not_a_ticker(matcher):
    """
    Found 2026-07-26 by the fan-out fix itself: "Crude oil prices surge"
    matched the symbol OIL (Oil India), and because that counted as a
    COMPANY hit it suppressed the whole genuine sector story. Same family
    as "ban" inside "Bank".
    """
    from news_bot.matching import NewsMatcher

    class L(_FakeLoader):
        ROWS = dict(_FakeLoader.ROWS)
        ROWS["OIL"] = dict(_FakeLoader.ROWS["VEDL"],
                           **{"SYMBOL": "OIL", "SECURITY ID": "9",
                              "COMPANY NAME": "OIL INDIA LIMITED"})

    m = NewsMatcher(loader=L())
    hits = m.match(_Item("Crude oil prices surge on supply concerns"))
    assert "OIL" not in {x.symbol for x in hits.matches}


def test_an_UPPERCASE_ticker_still_matches():
    """Real tickers appear in caps in headlines."""
    from news_bot.matching import NewsMatcher

    class L(_FakeLoader):
        ROWS = dict(_FakeLoader.ROWS)
        ROWS["OIL"] = dict(_FakeLoader.ROWS["VEDL"],
                           **{"SYMBOL": "OIL", "SECURITY ID": "9",
                              "COMPANY NAME": "OIL INDIA LIMITED"})

    m = NewsMatcher(loader=L())
    hits = m.match(_Item("OIL reports a 20% jump in quarterly profit"))
    assert "OIL" in {x.symbol for x in hits.matches}


def test_the_company_NAME_is_still_case_insensitive():
    """Only the ticker is case-sensitive. 'Oil India Limited' in normal
    title case must still be caught."""
    from news_bot.matching import NewsMatcher

    class L(_FakeLoader):
        ROWS = dict(_FakeLoader.ROWS)
        ROWS["OIL"] = dict(_FakeLoader.ROWS["VEDL"],
                           **{"SYMBOL": "OIL", "SECURITY ID": "9",
                              "COMPANY NAME": "OIL INDIA LIMITED"})

    m = NewsMatcher(loader=L())
    hits = m.match(_Item("Oil India Limited wins an exploration block"))
    assert "OIL" in {x.symbol for x in hits.matches}
