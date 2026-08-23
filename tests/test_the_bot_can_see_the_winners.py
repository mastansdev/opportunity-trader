"""
==========================================================
22 of the day's top 50 gainers were invisible to the bot.
==========================================================

    "fix the coverage first"      -- operator, 23 August 2026

20 August, the top ten gainers:

    KJMCFIN    +20.0%   not in the master at all
    SAMBANDAM  +20.0%   not in the master at all
    KRONOX     +20.0%   SUBSCRIBE=NO, "awaiting sector classification"
    MYSORPETRO +20.0%   SUBSCRIBE=NO, same
    BANARISUG  +17.2%   SUBSCRIBE=NO, same

KRONOX is the same stock whose open-offer filing was wired into the
reason path the day before. The bot could finally explain why it was
moving and still had no tick data for it.

262 symbols carried that reason. SIX are genuinely trusts or ETFs. The
other 256 are ordinary companies whose master row was never filled in
-- COMPANY NAME is just the ticker repeated -- and 100 of those trade
over Rs 2cr a day: JNPR Rs 82.8cr, SYNCOMF Rs 17.4cr, ONMOBILE
Rs 16.7cr. BANARISUG sat in there labelled a "new listing"; Bannari
Amman Sugars has been listed for decades.

TWO QUESTIONS, ONE RULE

The gate conflated "may we WATCH this stock" with "may we TRADE it".
The stated intent -- "never traded until a human fills in the sector"
-- is about the second, and it is enforced downstream where the sector
gates live. Blocking the FEED made the stock invisible to every alert,
every panel and every finder as well.

WHY NOT JUST FILL IN THE SECTOR

There is nothing to fill it from. NSE's equityMetaInfo returns the
company name and ISIN and no industry field at all. Guessing a sector
from a company name would be inventing data, which is the habit this
codebase keeps having to unlearn.

So: watch it if it is liquid enough to trade, at a HIGHER bar than a
classified stock, because we know less about it.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

from core.subscribe_list import (UNCLASSIFIED_MIN_TURNOVER_RS,
                                 UNCLASSIFIED_REASON, decide)

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _bhav(turnover_cr, close=300.0, series="EQ"):
    return {"series": series, "close": close,
            "turnover": turnover_cr * 10 ** 7}


# ---------------------------------------------------------------
# THE STOCKS IT WAS MISSING
# ---------------------------------------------------------------

def test_a_liquid_unclassified_stock_is_watched():
    """THE KRONOX CASE. +20% on a filing the bot had already learned
    to read, and no tick data for it."""
    ok, why = decide("KRONOX", bhav=_bhav(9.3), sector="")
    assert ok is True, why


def test_jnpr_at_82_crore_a_day_is_watched():
    """The largest of the 100 liquid names that were excluded."""
    assert decide("JNPR", bhav=_bhav(82.8), sector="")[0] is True


# ---------------------------------------------------------------
# THE BAR IS HIGHER, NOT ABSENT
# ---------------------------------------------------------------

def test_a_thin_unclassified_stock_stays_off_the_feed():
    """A feed slot is a real resource. We know less about these, so
    they answer a higher bar -- not no bar."""
    ok, why = decide("TINY", bhav=_bhav(0.4), sector="")
    assert ok is False
    assert why == UNCLASSIFIED_REASON


def test_the_unclassified_bar_is_above_the_ordinary_one():
    from core.subscribe_list import MIN_TURNOVER_RS
    assert UNCLASSIFIED_MIN_TURNOVER_RS > MIN_TURNOVER_RS


def test_no_bhavcopy_means_it_is_still_refused():
    """No turnover reading is not permission. It is the absence of one."""
    assert decide("UNKNOWN", bhav=None, sector="")[0] is False


# ---------------------------------------------------------------
# NOTHING THAT WAS EXCLUDED FOR A REAL REASON IS LET IN
# ---------------------------------------------------------------

def test_an_etf_is_still_refused_however_liquid():
    ok, why = decide("NIFTYBEES", bhav=_bhav(500.0), sector="",
                     excluded={"NIFTYBEES"})
    assert ok is False and "ETF" in why


def test_surveillance_still_refuses_an_unclassified_stock():
    """The governance question outranks liquidity, classified or not."""
    ok, why = decide("SHADY", bhav=_bhav(50.0), sector="",
                     remarks={"SHADY": "GSM STAGE - 1"})
    assert ok is False and "surveillance" in why


def test_a_corporate_action_still_refuses_it():
    ok, why = decide("SPLITCO", bhav=_bhav(50.0), sector="",
                     corporate_actions={"SPLITCO"})
    assert ok is False and "corporate action" in why


def test_a_narrow_price_band_still_refuses_it():
    ok, why = decide("BANDED", bhav=_bhav(50.0), sector="",
                     bands={"BANDED": 5.0})
    assert ok is False and "band" in why


def test_a_classified_stock_is_unaffected():
    """The ordinary path must behave exactly as before."""
    assert decide("NCC", bhav=_bhav(9.3), sector="INFRASTRUCTURE")[0] is True
    assert decide("THIN", bhav=_bhav(0.4), sector="INFRASTRUCTURE")[0] is False


def test_the_reason_is_written_down_where_it_broke():
    src = (ROOT / "core" / "subscribe_list.py").read_text(encoding="utf-8")
    assert "KRONOX" in src and "top 50 gainers" in src
