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

def broad_tier_on(fn):
    """BROAD (sector) matching is OFF by default -- see
    news_bot/config.py's NEWS_ENABLE_BROAD_TIER for the measurements.
    These tests are about what sector matching DOES when enabled, so
    they switch it on for their own duration."""
    import functools

    import news_bot.matching as _m

    @functools.wraps(fn)
    def wrapper(*a, **kw):
        old = _m.NEWS_ENABLE_BROAD_TIER
        _m.NEWS_ENABLE_BROAD_TIER = True
        try:
            return fn(*a, **kw)
        finally:
            _m.NEWS_ENABLE_BROAD_TIER = old
    return wrapper


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


@broad_tier_on
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


# ---------------------------------------------------------------
# A company we do NOT track must not spray its sector
# ---------------------------------------------------------------

def test_an_untracked_company_produces_silence(matcher):
    """
    2026-07-26, after the first fan-out fix. V-Mart is not in our 750, so
    nothing matched at COMPANY tier, so "Retail" fanned out and the story
    was stored as bullish/HIGH against RELIANCE, DMART and ABFRL.
    V-Mart's profit says nothing about Reliance.
    """
    result = matcher.match(_Item(
        "V-Mart Retail Q1 Results: Profit surges 40% to Rs 47 crore"))
    assert result.matches == []


def test_an_untracked_exchange_filing_produces_silence(matcher):
    """"Steel Strips Wheels Limited has informed the Exchange..." reached
    131 symbols, including ABB and ASHOKLEY."""
    result = matcher.match(_Item(
        "Steel Strips Wheels Limited has informed the Exchange regarding "
        "Allotment of shares"))
    assert result.matches == []


def test_is_company_story_recognises_the_real_shapes():
    from news_bot.matching import is_company_story
    for text in ("V-Mart Retail Q1 Results: Profit surges 40%",
                 "Steel Strips Wheels Limited has informed the Exchange",
                 "Ratnaveer Precision Engineering Limited has submitted to "
                 "the Exchange",
                 "Some Company Ltd announces expansion"):
        assert is_company_story(text) is True, text

    for text in ("Steel prices surge on new import duty",
                 "IT services sector sees strong hiring demand",
                 "RBI cuts repo rate by 25 bps"):
        assert is_company_story(text) is False, text


@broad_tier_on
def test_genuine_sector_news_is_still_kept_however_wide(matcher):
    """An earlier fix capped stories at 25 symbols and DELETED wider
    ones. Wrong -- real sector news is genuinely wide (crude oil hits 67
    names in the real universe). The harm was HIGH priority, not width."""
    result = matcher.match(_Item("Steel prices surge on new import duty"))
    assert {m.symbol for m in result.matches} == {"VEDL", "TATASTEEL", "ABB"}


# ---------------------------------------------------------------
# Sector news is context -- it must never veto a trade
# ---------------------------------------------------------------

def _classification(direction="bullish", confidence=90):
    return dict(direction=direction, confidence=confidence,
                materiality="material", reason="test")


def test_a_BROAD_match_can_never_be_HIGH():
    from news_bot.models import MatchResult
    from news_bot.priority import tier_for
    out = tier_for(MatchResult("RELIANCE", "SECTOR", "REFINING", "BROAD"),
                   _classification())
    assert out.priority == "MID"


def test_a_COMPANY_match_still_reaches_HIGH():
    from news_bot.models import MatchResult
    from news_bot.priority import tier_for
    out = tier_for(MatchResult("RELIANCE", "COMPANY_NAME", "RELIANCE",
                               "COMPANY"),
                   _classification())
    assert out.priority == "HIGH"


def test_a_COMPANY_match_still_needs_confidence_and_direction():
    from news_bot.models import MatchResult
    from news_bot.priority import tier_for
    m = MatchResult("RELIANCE", "COMPANY_NAME", "RELIANCE", "COMPANY")
    assert tier_for(m, _classification(confidence=40)).priority == "MID"
    assert tier_for(m, _classification(direction="neutral")).priority == "MID"


# ---------------------------------------------------------------
# News does not veto a trade (2026-07-26 operator call)
# ---------------------------------------------------------------

def test_news_blocking_is_OFF_by_default():
    """
    Operator: "URBAN = BAN ? keyword matching .. i guess we need to stop
    relying on news & trading for now until API i buy."

    That specific row was stale -- classified before the word-boundary
    fix -- but the judgement stands: a wrong bearish HIGH does not add
    noise, it REFUSES a trade, and a silent veto on a good setup costs
    more than the bad trade it prevents.
    """
    from config import ENABLE_NEWS_BLOCKING
    assert ENABLE_NEWS_BLOCKING is False


def test_the_engine_honours_the_flag():
    from core.engine import Engine
    assert Engine().enable_news_blocking is False
    assert Engine(enable_news_blocking=True).enable_news_blocking is True


def test_urban_no_longer_matches_ban():
    """The regression itself. 'ban' inside 'URBAN' produced a bearish
    80% HIGH on TVSMOTOR."""
    from news_bot.keyword_classifier import classify

    class _Item:
        def __init__(self, title):
            self.title = title
            self.summary = ""

    out = classify(_Item(
        "TVS MOTOR COMPANY LAUNCHES TVS ORBITER IN NEPAL A SMART, "
        "SUSTAINABLE, URBAN EV COMMUTE SOLUTION"))
    assert out["direction"] == "neutral"

    # ...and a real ban still registers
    out = classify(_Item("Government imposes export ban on the product"))
    assert out["direction"] == "bearish"


# ---------------------------------------------------------------
# A word list may never decide a trade
# ---------------------------------------------------------------
# Operator, 2026-07-26: "i do not want a hardcoded keyword/matchmaker
# decides & tell the brain bot to buy/sell or any decisions".

def _kw(direction="bullish", confidence=80, classifier="keyword"):
    return dict(direction=direction, confidence=confidence,
                materiality="material", reason="keyword match: dividend",
                classifier=classifier)


def _company():
    from news_bot.models import MatchResult
    return MatchResult("SHYAMMETL", "EXCHANGE_FILING", "SHYAMMETL",
                       "COMPANY")


def test_the_keyword_classifier_can_never_reach_HIGH():
    """HIGH is the level that blocks a trade."""
    from news_bot.priority import tier_for
    assert tier_for(_company(), _kw()).priority == "MID"


def test_the_paid_classifier_still_reaches_HIGH():
    from news_bot.priority import tier_for
    assert tier_for(_company(), _kw(classifier="haiku")).priority == "HIGH"


def test_a_missing_classifier_field_is_treated_as_paid():
    """Older rows and the AI path itself omit the field."""
    from news_bot.priority import tier_for
    payload = _kw()
    payload.pop("classifier")
    assert tier_for(_company(), payload).priority == "HIGH"


def test_the_two_headlines_the_operator_caught():
    """
    Neither is fixable by tuning a word list:

      "Ujjivan Small Finance BANK ... financial results"
           'ban' inside 'Bank'   -> bearish 80% HIGH
      "Intimation of Tax Deduction on Dividend"
           'dividend' is really there, the meaning is routine admin
    """
    from news_bot.keyword_classifier import classify
    from news_bot.priority import tier_for

    class _Item:
        def __init__(self, title):
            self.title = title
            self.summary = ""

    # 1. the boundary bug -- fixed at the lexicon
    bank = classify(_Item(
        "Ujjivan Small Finance Bank Limited has submitted to the "
        "Exchange, the financial results for the period ended Jun 30"))
    assert bank["direction"] == "neutral"

    # 2. NOT fixable by any word list -- the word is genuinely present.
    #    It must be stopped at priority instead.
    div = classify(_Item(
        "Shyam Metalics And Energy Limited has informed the Exchange "
        "about General Updates regarding Intimation of Tax Deduction "
        "on Dividend"))
    assert div["direction"] == "bullish"        # the lexicon still says so
    assert tier_for(_company(), div).priority == "MID"   # ...and it cannot act
