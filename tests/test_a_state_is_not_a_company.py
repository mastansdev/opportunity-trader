"""
==========================================================
Tamil Nadu is a state. TNPL is a paper mill.
==========================================================

    "for me all info must be tagged properly & never mis ,
     duplicate , thats it"
                                -- the operator, 5 September 2026

core/telegram_feed.names_in() recognises a company by the FIRST TWO
WORDS of its name. Two words is normally a good safeguard -- "Aarti"
alone would tag half the exchange. It fails completely when those two
words are a place:

    TAMIL NADU NEWSPRINT & PAPERS   ->   pair (TAMIL, NADU)

so any message mentioning the state named the paper mill. Counted on
data/stock_events.db: 18 events filed against TNPL, and EIGHT of them
are the state --

    "Ops at arm Del Monte Food, Tamil Nadu plant halted"   SUNDROP
    "Network partner stores in Rajasthan, Tamil Nadu"      OLAELEC
    "US FDA conducted inspection at arm in Tamil Nadu"     CAPLINPOINT
    "SECURES 119.85 CRORE ORDER FROM NHAI"                 BRGIL

WHY THIS IS NOT COSMETIC. A published reason is MANDATORY before the
ranker will evaluate a stock at all -- REQUIRE_A_REASON_ALWAYS. So a
false reason does not merely look wrong on a panel; it OPENS THE DOOR.
A paper mill was being put in front of the ranker on days when somebody
else built a road, and 44% of everything the bot believed about TNPL
was about somewhere it happens to be.

A false reason is worse than a missing one. A missing one costs an
opportunity; a false one spends a seat, and there are ten.

THE FIX: where a company's first two words are a place, the THIRD word
is required. A company whose name is ONLY a place keeps its pair --
there is no third word to ask for, and nothing else it could be.

Author : H&M Opportunity Trader
==========================================================
"""

import pytest

from core.master_loader import MasterLoader
from core.telegram_feed import TelegramFeed


@pytest.fixture(scope="module")
def feed():
    loader = MasterLoader()
    loader.load()
    return TelegramFeed(master_loader=loader)


def test_the_state_alone_names_nobody(feed):
    """The eight false rows, in one line."""
    assert feed.names_in("Ops at arm Del Monte Food, Tamil Nadu plant "
                         "halted due to accident") == []


def test_the_company_is_still_found(feed):
    """The guard must not cost the true match it exists to protect."""
    assert "TNPL" in feed.names_in("Tamil Nadu Newsprint and Papers Ltd")


def test_every_false_row_measured_on_the_store_is_gone(feed):
    """Each of these put a reason on TNPL. Verbatim from the store."""
    for text in (
            "Network partner stores are present in Rajasthan, Tamil Nadu, "
            "Bihar",
            "US FDA conducted inspection at arm in Tamil Nadu",
            "CO RECEIVES TERMINATION OF 205.89 CRORE WORK ORDER IN "
            "TAMIL NADU",
            "CO SECURES 119.85 CRORE ORDER FROM NHAI FOR TAMIL NADU "
            "HIGHWAY",
            "TVS INDUSTRIAL AND LOGISTICS PARKS PLANS RS 1,000 CRORE "
            "INVESTMENT IN TAMIL NADU"):
        assert "TNPL" not in feed.names_in(text), text


def test_the_other_states_too(feed):
    """The same shape, not just the one that was measured."""
    for text in ("new plant in Andhra Pradesh",
                 "expanding across Uttar Pradesh",
                 "a facility in West Bengal",
                 "office in New Delhi"):
        found = feed.names_in(text)
        assert not found, f"{text} -> {found}"


def test_an_ordinary_two_word_company_is_untouched(feed):
    """The pair rule is right for everything that is not a place, and
    this is the check that the fix stayed narrow."""
    assert "AARTIIND" in feed.names_in("Aarti Industries Ltd reported")


def test_the_place_list_is_stated_not_guessed():
    """A gazetteer nobody can read is a rule nobody can check."""
    assert ("TAMIL", "NADU") in TelegramFeed._PLACE_PAIRS
    assert ("WEST", "BENGAL") in TelegramFeed._PLACE_PAIRS
