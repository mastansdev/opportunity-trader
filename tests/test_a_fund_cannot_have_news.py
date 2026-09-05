"""
==========================================================
A fund is not a company
==========================================================

The last of the mis-tagging work, and it turned out to be one bug
wearing two costumes.

WHAT WAS SEEN. Two separate-looking faults:

    AAYUSH WELLNESS: CO. LAUNCHES LUNG CARE TABLETS TO ENTER
      Rs 18,913 CR RESPIRATORY HEALTHCARE MARKET   -> filed as HEALTHCARE

    a Telugu post about gold and silver prices      -> filed as SILVER

WHAT THEY ACTUALLY ARE. Neither of those tickers is a company:

    HEALTHCARE  MIRAE ASSET MUTUAL FUND - NIFTY 500 HEALTHCARE ETF
    HEALTHY     ADITYA BIRLA SUN LIFE MF - ... NIFTY ...
    SILVER      ADITYA BIRLA SUN LIFE MUTUAL FUND - SILVER ETF
    DEFENCE     MIRAE ASSET MUTUAL FUND - BSE INDIA DEFENCE ETF

The master carries 29 ETFs and mutual funds, and ELEVEN of them have a
ticker that is an ordinary English word: CONSUMER, DEFENCE, DIVIDEND,
ENERGY, HEALTHCARE, HEALTHY, METAL, SILVER, SMALLCAP, TECH, VALUE.
Measured on the store, 22 messages were matched to a fund.

WHY THIS IS A CATEGORY, NOT A WORD LIST. There has been a word list
since 6 August -- _WORD_TICKERS, fifteen entries, added after CURRENT,
VALUE and TOTAL took more result images than TRENT did. It works, and
it is the wrong shape for this: it has to be extended by hand every
time a fund house launches an ETF, and the next one called POWER or
BANK arrives without anyone noticing.

A FUND CANNOT HAVE NEWS. It wins no orders, files no results, holds no
board meetings, makes no announcements. Every rule in this bot is about
something that HAPPENED to a company, so a fund in the news matcher can
only ever produce a wrong answer. Excluding the category settles all of
them at once, and settles the ones not launched yet.

NOT THE SAME QUESTION AS SUBSCRIBE. A blocked COMPANY belongs in the
matcher -- "being barred from trading ACMESOLAR is no reason to fail to
notice that it just reported excellent results". A fund is not blocked;
it is not a company.

AFTER: 0 messages matched to a fund, and every real company still
matches, ACC LIMITED included.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.master_loader import MasterLoader
from core.stock_events import _for_matching
from core.telegram_feed import TelegramFeed
from core.universe_builder import looks_like_a_fund


@pytest.fixture(scope="module")
def feed():
    loader = MasterLoader()
    loader.load()
    return TelegramFeed(master_loader=loader)


def found(feed, text):
    return sorted(set(feed.symbols_in(_for_matching(text))
                      + feed.names_in(_for_matching(text))))


# ------------------------------------------------------------------
# the detector
# ------------------------------------------------------------------

def test_the_name_is_what_gives_a_fund_away():
    """The symbol test cannot see a fund called HEALTHCARE."""
    assert looks_like_a_fund(
        "HEALTHCARE",
        "MIRAE ASSET MUTUAL FUND - MIRAE ASSET NIFTY 500 HEALTHCARE ETF")
    assert looks_like_a_fund(
        "SILVER", "ADITYA BIRLA SUN LIFE MUTUAL FUND - SILVER ETF")
    assert looks_like_a_fund("HEALTHCARE") is False, \
        "the symbol alone says nothing -- that is the whole problem"


def test_a_real_company_is_not_a_fund():
    assert not looks_like_a_fund("ACC", "ACC LIMITED")
    assert not looks_like_a_fund("HAL", "HINDUSTAN AERONAUTICS LIMITED")
    assert not looks_like_a_fund("GOLDIAM", "GOLDIAM INTERNATIONAL LTD")
    assert not looks_like_a_fund("MCX", "MULTI COMMODITY EXCHANGE")


def test_an_asset_manager_is_a_company():
    """    "ABSLAMC = ADITYA BIRLA SUN LIFE AMC LIMITED"
                                            -- the operator

    He said it the minute the first version shipped. An AMC is a listed
    OPERATING COMPANY -- results, board meetings, mandates. The FUND is
    the product it sells.

    HDFCAMC, ICICIAMC, CRAMC and ABSLAMC survived the first draft only
    because the master abbreviates them, which is luck. GAJA spells it
    out and was silenced -- and GAJA reports on 10 September, on the
    calendar the results gate reads.
    """
    for sym, name in (("ABSLAMC", "ADIT BIRL SUN LIF AMC LTD"),
                      ("HDFCAMC", "HDFC AMC LIMITED"),
                      ("ICICIAMC", "ICICI PRUDENTIAL AMC LTD"),
                      ("CRAMC", "CANARA ROBECO AMC LIMITED"),
                      ("GAJA", "GAJA ALTERNATIVE ASSET MANAGEMENT "
                               "LIMITED")):
        assert not looks_like_a_fund(sym, name), f"{sym} is a company"


def test_a_saree_shop_is_not_a_state_development_loan():
    """`"SDL" in "SSDL"` is True, so SARASWATI SAREE DEPOT LIMITED read
    as a fund. Harmless while this only wrote a proposal a human
    reviewed; not harmless once the news matcher started asking it.

    Tightening the substring cannot work -- ETF must match at the end
    of GOLDETF and SDL must not at the end of SSDL, and nothing in the
    letters separates those. The NAME does, so when there is one it is
    the whole answer."""
    assert not looks_like_a_fund("SSDL", "SARASWATI SAREE DEPOT LIMITED")
    assert looks_like_a_fund(
        "GOLDETF", "MIRAE ASSET MUTUAL FUND - MIRAE ASSET GOLD ETF")


def test_the_old_symbol_test_still_works():
    """NSE's own list is the primary defence and this is the fallback.
    Nothing about that changes."""
    assert looks_like_a_fund("NIFTYBEES")
    assert looks_like_a_fund("GOLDETF")
    assert looks_like_a_fund("GSEC10ADD")


# ------------------------------------------------------------------
# and the matcher
# ------------------------------------------------------------------

def test_the_wellness_story_no_longer_names_an_etf(feed):
    """The case that started it, verbatim."""
    assert found(feed,
                 "AAYUSH WELLNESS: CO. LAUNCHES LUNG CARE TABLETS TO "
                 "ENTER 18913 CR RESPIRATORY HEALTHCARE MARKET") == []


def test_ordinary_words_no_longer_name_a_fund(feed):
    for text in ("Gold fell 2% and silver slipped on the day",
                 "Defence stocks rallied on the order announcement",
                 "Smallcap index up 1.2% today",
                 "The energy sector led the gains",
                 "A healthy quarter across the board"):
        assert found(feed, text) == [], text


def test_every_fund_is_out_of_the_matcher(feed):
    known = feed._known_symbols(hashtag=True)
    for sym in ("HEALTHCARE", "HEALTHY", "SILVER", "DEFENCE", "SMALLCAP",
                "NIFTYADD", "GOLDETF", "MONIFTY500"):
        assert sym not in known, f"{sym} is a fund and is still matchable"


def test_real_companies_still_match(feed):
    """The check that the fix stayed narrow. A category rule that also
    silenced real companies would be far worse than the problem."""
    for text, want in (
            ("HAL: CCS APPROVAL ON MULTI ROLE HELICOPTER", "HAL"),
            ("SAIL: CO ACCELERATES CAPEX PLAN", "SAIL"),
            ("NTPC: COMMISSIONS 660 MW UNIT AT NABINAGAR", "NTPC"),
            ("BEML: CO SECURES RUPEES 181 CR VANDE BHARAT ORDER", "BEML"),
            ("#MOLBIO reports Q1 FY27 results", "MOLBIO"),
            ("Aarti Industries Ltd reported Q1", "AARTIIND"),
            ("ACC LIMITED: CO REPORTS Q1 CEMENT VOLUMES UP 8%", "ACC")):
        assert want in found(feed, text), text


def test_the_asset_managers_still_match(feed):
    """His case, end to end: an AMC's news must still reach it."""
    known = feed._known_symbols(hashtag=True)
    for sym in ("ABSLAMC", "HDFCAMC", "ICICIAMC", "CRAMC", "GAJA",
                "SSDL"):
        assert sym in known, f"{sym} is a company and was silenced"


def test_gaja_can_still_carry_its_results(feed):
    """GAJA is on the results calendar for 10 September. A company the
    gate is watching must be able to carry the news that lifts the
    block."""
    assert "GAJA" in found(feed, "#GAJA reports Q1 FY27 results")


def test_a_blocked_company_is_still_matched(feed):
    """A fund is excluded because it is not a company. A company the
    bot may not TRADE is a different question entirely, and its news
    still matters."""
    known = feed._known_symbols(hashtag=True)
    loader = feed.master_loader
    blocked = [s for s in loader.all_symbols(include_blocked=True)
               if s not in set(loader.all_symbols())]
    assert blocked, "no blocked symbols to check against"
    kept = [s for s in blocked if s in known]
    assert kept, "blocked companies were dropped from the matcher too"
