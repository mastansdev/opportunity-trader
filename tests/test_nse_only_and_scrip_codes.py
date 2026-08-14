"""
==========================================================
The two chips he will trade, and the exchange he trades on
==========================================================

    "pls make sure these chips & related stocks are never mis matched
     as they are the one we trust for now until another month or by
     next results season"

    "pls make sure we will trade only NSE listed stocks"
                                    -- operator, 1 August 2026

He read tools/outcome_report.py and decided to trust exactly two
chips: PULSE EXCELLENT and CLEAN brief. Everything else on the panel
is context. So a wrong symbol on those two is no longer a cosmetic
bug -- it is the bug.

WHAT THE AUDIT OF THOSE 180 EVENTS FOUND
----------------------------------------
    hashtag                  169   93.9%
    company name               5    2.8%
    bare ticker only           1    0.6%
    NO evidence in headline    5    2.8%

Six were wrong, and one was a root-cause bug worth its own test:

    BSE   <- a card tagged #BSE_543980
    BSE   <- a card tagged #BSE_526935

Those are BSE SCRIP CODES for two other companies. The token pattern
had no underscore, so "#BSE_543980" split into "#BSE" and "543980",
and BSE Ltd -- which had not even reported -- collected two GREAT
quarters that belonged to somebody else.

THE SUFFIX DECIDES, AND THE DISTINCTION IS NOT COSMETIC
-------------------------------------------------------
    #BSE_543980   digits  -> an instrument identifier we cannot
                             resolve. Match nothing.
    #VHLTD_RE     letters -> Viceroy Hotels' rights entitlement, on
    #CGCL_RE                 Viceroy's own Q1 story. Same company.
                             Dropping it would lose a true link.
    #UEL_         empty   -> a trailing underscore off a garbled
                             calendar image. Still UEL.

Measured over the whole store, in isolation: SIX links removed, all
BSE, and none added.

NSE ONLY
--------
Enforced in three places and asserted here so it stays that way:

    config.EXCHANGE_SEGMENT = "NSE_EQ"       every order carries it
    InstrumentMaster.resolve()               NSE + EQUITY or nothing
    verify_master_database.py -> preflight   fails LIVE on a miss

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest


# ---------------------------------------------------------------
# 1. A SCRIP CODE IS NOT A TICKER
# ---------------------------------------------------------------
class Feed:
    """The real matcher, with a known-symbol set we control."""

    def __init__(self, known):
        from core.telegram_feed import TelegramFeed
        self.feed = TelegramFeed(client=None)
        self.feed._symbols = set(known)
        self.feed._symbols_tagged = set(known)
        self.feed._names = {}

    def __call__(self, text):
        return self.feed.symbols_in(text)


KNOWN = {"BSE", "VHLTD", "CGCL", "UEL", "GHCL", "HCG", "M&M", "CLEAN"}


@pytest.fixture
def symbols_in():
    return Feed(KNOWN)


@pytest.mark.parametrize("text", [
    "🟢 #BSE_543980 — Q1 FY27 Solid start to the year",
    "🟢 #BSE_526935 — Q1 FY27 Strong quarter with operating leverage",
])
def test_a_numeric_scrip_code_matches_nothing(symbols_in, text):
    """THE ONE THAT MATTERS. Two other companies' GREAT quarters were
    filed against BSE Ltd, which had not reported at all."""
    assert "BSE" not in symbols_in(text)


@pytest.mark.parametrize("text,expected", [
    ("📈 #VHLTD_RE Viceroy Hotels reported a Q1 net profit", "VHLTD"),
    ("🚀 #CGCL_RE Capri Global Capital is collaborating with OpenAI", "CGCL"),
])
def test_a_rights_entitlement_is_still_the_company(symbols_in, text, expected):
    """_RE is the same company's rights entitlement. Dropping it would
    lose a true link, which is the trade this codebase refuses to
    make."""
    assert expected in symbols_in(text)


def test_a_trailing_underscore_from_bad_ocr_still_resolves(symbols_in):
    """Verbatim from a garbled calendar image:
    "WONOAPOWER -«UEL_—«=SPAUSHAKLTD. «GELDING = KABRAEXTRU"
    """
    assert "UEL" in symbols_in("WONOAPOWER -«UEL_ «GELDING KABRAEXTRU")


def test_an_ordinary_hashtag_is_untouched(symbols_in):
    assert symbols_in("#GHCL - Excellent Results") == ["GHCL"]


def test_the_token_pattern_carries_the_underscore():
    """Without it the split happens before any rule can see it."""
    src = open("core/telegram_feed.py", encoding="utf-8").read()
    body = src[src.index("def symbols_in"):]
    body = body[:body.index("\n    def ", 10)]
    assert "A-Za-z0-9&_" in body, (
        "the token class must include '_' or #BSE_543980 splits into "
        "#BSE before anything can judge it")


# ---------------------------------------------------------------
# 2. NSE ONLY
# ---------------------------------------------------------------
def test_every_order_carries_the_nse_segment():
    from config import EXCHANGE_SEGMENT
    assert EXCHANGE_SEGMENT == "NSE_EQ"


def test_the_scrip_master_resolves_nse_equity_and_nothing_else():
    """A symbol that is not NSE EQUITY gets no security id, so it can
    never be subscribed to or ordered."""
    src = open("core/instrument_master.py", encoding="utf-8").read()
    assert 'SEM_EXM_EXCH_ID"] == "NSE"' in src
    assert 'SEM_INSTRUMENT_NAME"] == "EQUITY"' in src
    assert "return None" in src, "an unresolvable symbol must be refused"


def test_live_execution_uses_the_configured_segment_only():
    """If a second segment ever appears here it should be a decision
    someone made, not a default that drifted."""
    src = open("trading/live_execution.py", encoding="utf-8").read()
    found = set(re.findall(r"exchange_segment\s*=\s*([A-Za-z_.]+)", src))
    assert found <= {"EXCHANGE_SEGMENT", "self.segment"}, (
        f"live orders reference an unexpected segment: {found}")
    assert '"BSE_EQ"' not in src


def test_the_daily_verifier_fails_the_morning_on_a_non_nse_symbol():
    """preflight reads the proof file and refuses to start LIVE if a
    symbol could not be found on NSE."""
    src = open("tools/verify_master_database.py", encoding="utf-8").read()
    assert "not_found" in src and "clean" in src
    pre = open("tools/preflight.py", encoding="utf-8").read()
    assert "verify" in pre.lower()


# ---------------------------------------------------------------
# 3. THE TWO TRUSTED CHIPS
# ---------------------------------------------------------------
def test_the_two_chips_he_trades_are_the_ones_measured():
    """If these labels are ever renamed, tools/outcome_report.py stops
    reporting on the only two chips he acts on -- silently."""
    from core.outcomes import chips_for
    assert chips_for({"kind": "RESULT", "grade": "EXCELLENT",
                      "headline": "x"}) == ["PULSE EXCELLENT"]
    assert chips_for({"kind": "NEWS",
                      "headline": "CLEAN | Rising, Expanding, Healthy"}) \
        == ["CLEAN brief"]


def test_a_card_label_still_cannot_become_clean_science():
    """The other five of the six mismatches. CLEAN is Clean Science's
    ticker AND the word every honest brief prints."""
    from core.stock_events import _for_matching
    card = ("#NITTAGELA — Q1 FY27 Profit jumps 30% YoY\n"
            "EARNINGS QUALITY DISTORTION FLAGS ACCOUNTING - ONE-OFFS\n"
            "CLEAN\n")
    assert "CLEAN" not in _for_matching(card)
    assert "NITTAGELA" in _for_matching(card)
