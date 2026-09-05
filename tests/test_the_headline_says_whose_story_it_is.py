"""
==========================================================
A speaker is not a company, and neither is a customer
==========================================================

    "artson is BSE stock"       -- the operator, 5 September 2026

That one line settles what this is. The universe is NSE -- the master
carries EQ, BE, SM, ST and RR series and nothing else -- so ARTSON is
correctly absent, and there is nothing to add to fix it.

But RedboxGlobal India and Day Trader Telugu carry news about
BSE-listed companies routinely, and every one of those arrives with a
subject the bot cannot resolve. So every one is a candidate to be filed
against whichever NSE name the sentence happens to mention:

    ARTSON LTD: CO. RECEIVES PURCHASE ORDER WORTH 7.17 CR ...
      SUPPLY OF 24 VESSELS FOR NTPC NABINAGAR      -> filed as NTPC

ARTSON won that order. NTPC is where the boilers go. OrderBook Pulse
tagged the same order #ARTSON and got it right, so the bot held both
answers and believed the wrong one.

The same shape, worse, on the macro wire:

    U.S. CENTCOM: FACT: NO SHIPS HAVE HIT MINES   -> filed as FACT
    U.S CENTCOM: CLAIM: IRAN'S ISLAMIC ...        -> filed as ROUTE
    FED'S WARSH: UNDERLYING INFLATION IS MOVING   -> filed as HEALTHY
    U.S. ENERGY SECRETARY WRIGHT: 17 MLN BARRELS
      OIL FLOWED THROUGH STRAIT OF HORMUZ         -> filed as OIL
    VANCE ON VENEZUELA: INCREASED OIL PRODUCTION  -> filed as OIL
    SOURCE: NSE  (an FII/DII activity table)      -> filed as BSE

A CENTCOM statement was a published reason for a fertiliser company and
a Fed speech one for a stock called HEALTHY. A published reason is
MANDATORY before the ranker will evaluate a stock at all, so these do
not sit on a panel -- they OPEN THE DOOR, and there are ten seats
behind it.

WHAT WAS ALREADY RIGHT, and why this is narrow. Replayed through the
live code, 196 wire headlines whose subject the bot RECOGNISES landed
on that subject, 196 of 196. Only the unrecognised ones go wrong. And
"any subject that fails to resolve" would be too blunt: FLY SBS
AVIATION is FLYSBS in the master, spelled without the spaces, and
BLOCK DEAL ALERT: EPLLTD is a label followed by a real stock. Both are
filed correctly today and must stay that way.

MEASURED ACROSS ALL 2,022 STORED MESSAGES: nine refusals, every one of
them a false reason, and not one true event lost.

Author : H&M Opportunity Trader
==========================================================
"""

from core.stock_events import (events_from_message,
                               subject_is_not_a_company, wire_subject)


class Matcher:
    """Knows the NSE universe. Does not know ARTSON, which is BSE."""

    KNOWN = {"NTPC", "FACT", "ROUTE", "OIL", "HEALTHY", "BSE", "HAL",
             "FLYSBS", "EPL", "HEALTHCARE"}

    def symbols_in(self, text):
        up = str(text).upper()
        return [s for s in self.KNOWN
                if __import__("re").search(r"(?<!\w)" + s + r"(?!\w)", up)]

    def names_in(self, text):
        return []


def filed(text):
    out = events_from_message(Matcher(), text=text,
                              at="2026-09-05T09:00", channel="x")
    return sorted({e.get("symbol") for e in (out or []) if e.get("symbol")})


# ------------------------------------------------------------------
# the customer is not the subject
# ------------------------------------------------------------------

def test_the_order_does_not_go_to_the_customer():
    """The row that started this, verbatim."""
    assert filed(
        "ARTSON LTD: CO. RECEIVES PURCHASE ORDER WORTH 7.17 CR FROM "
        "L&T - MHI POWER BOILERS; SUPPLY OF 24 VESSELS FOR NTPC "
        "NABINAGAR BOILERS; EXECUTION DEADLINES SET FOR 2027") == []


def test_a_known_subject_is_still_filed():
    """196 of 196 already landed correctly. Nothing about that changes."""
    assert filed("NTPC: CO. COMMISSIONS 660 MW UNIT AT NABINAGAR") == ["NTPC"]


# ------------------------------------------------------------------
# a speaker is not a company
# ------------------------------------------------------------------

def test_a_military_statement_is_not_company_news():
    assert filed("U.S. CENTCOM: FACT: NO SHIPS HAVE HIT MINES IN THE "
                 "STRAIT OF HORMUZ") == []
    assert filed("U.S CENTCOM: CLAIM: IRAN'S ISLAMIC REVOLUTIONARY "
                 "GUARD SEIZED A TANKER") == []


def test_a_central_banker_is_not_company_news():
    assert filed("FED'S WARSH: MUST BE CONFIDENT UNDERLYING INFLATION "
                 "IS MOVING TO OBJECTIVE") == []


def test_a_minister_talking_about_oil_is_not_oil_india():
    assert filed("U.S. ENERGY SECRETARY WRIGHT: OVER 17 MLN BARRELS OIL "
                 "FLOWED THROUGH STRAIT OF HORMUZ ON MONDAY") == []


def test_a_politician_on_a_country_is_not_company_news():
    assert filed("VANCE ON VENEZUELA: ALREADY SEEING INCREASED OIL "
                 "PRODUCTION") == []


def test_a_data_table_credited_to_a_source_is_not_company_news():
    assert filed("SOURCE: NSE FIIs AND DIIs TRADING ACTIVITY ON NSE, "
                 "BSE AND MSEI") == []


# ------------------------------------------------------------------
# but the MESSAGE survives -- it is the stock that goes
# ------------------------------------------------------------------

def test_a_speaker_keeps_its_market_reading():
    """    "NSE (FII/DII activity table) = our FII & DII amounts ; not
            BSE or NSE ... stocks"              -- the operator

    A statement by CENTCOM or the Fed is real market context. The first
    version of this rule returned nothing at all, which is right about
    the attribution and wrong about the content -- the store already
    holds 3,703 MACRO rows and 154 FLOW rows, all MARKET scope with no
    symbol, and these are exactly that.

    A MARKET row carries no symbol and opens no door:
    REQUIRE_A_REASON_ALWAYS is asked per stock.
    """
    out = events_from_message(
        Matcher(),
        text="U.S. ENERGY SECRETARY WRIGHT: OVER 17 MLN BARRELS OIL "
             "FLOWED THROUGH STRAIT OF HORMUZ ON MONDAY",
        at="2026-09-05T09:00", channel="x")
    assert out, "the market reading was thrown away with the stock"
    assert all(e.get("scope") == "MARKET" for e in out)
    assert all(not e.get("symbol") for e in out)


def test_a_country_heading_is_not_a_speaker():
    """Day Trader Telugu heads its daily flows card "India: Cash Market
    Flows". A country prefix proves nothing -- matching it threw the
    card away, FII and DII amounts included."""
    assert not subject_is_not_a_company("India: Cash Market Flows")
    assert subject_is_not_a_company("U.S. CENTCOM: anything")


def test_the_flows_card_survives_its_bullets():
    """Two bulleted technical levels made is_digest() call it a
    roundup. That rule exists to stop a FIGURE landing on the wrong
    COMPANY, and this card names no company -- there is nothing to
    protect against and the numbers were the price.

    70 messages on the store, 66 of them market context."""
    card = ("India: Cash Market Flows\n"
            "Fil -2346 Cr\n"
            "Dil +4977 Cr\n"
            "F&O Cues\n"
            "Fils sell 926 Cr in Index Futures\n"
            "Options Data Suggests Nifty Range b/w 23700-24200\n"
            "Technical Levels\n"
            "- Nifty 100 DMA of 24028 important level to track\n"
            "- Nifty Bank 20 DMA key level to conquer 57548")
    out = events_from_message(Matcher(), ocr_text=card,
                              at="2026-09-04T03:24", channel="x")
    assert out, "the FII and DII amounts were thrown away"
    assert all(e.get("scope") == "MARKET" for e in out)


def test_a_recap_of_companies_is_still_refused():
    """The guard that must not be loosened. This also names no company
    and also classifies MARKET -- scope does not separate them, the
    KIND does. An ORDER about companies the bot could not name is a
    story it does not understand, not market context."""
    recap = ("Daily Highlights\n#AAA wins an order\n"
             "#BBB reports results\n#CCC falls 5%\n")
    assert events_from_message(Matcher(), text=recap,
                               at="2026-09-05T09:00", channel="x") == []


# ------------------------------------------------------------------
# and what must NOT be caught
# ------------------------------------------------------------------

def test_a_name_the_matcher_spells_differently_still_files():
    """FLY SBS AVIATION is FLYSBS in the master, without the spaces. A
    blanket "unresolvable subject" rule would throw this away."""
    assert filed("FLY SBS AVIATION: CO INCORPORATES A WHOLLY OWNED "
                 "SUBSIDIARY. FLYSBS") == ["FLYSBS"]


def test_a_label_followed_by_a_real_stock_still_files():
    assert filed("BLOCK DEAL ALERT: EPL SHARES CHANGE HANDS") == ["EPL"]


def test_an_ordinary_company_headline_is_untouched():
    assert filed("HAL: CO. DELIVERS THE FIRST TEJAS MK1A TO THE IAF") \
        == ["HAL"]


# ------------------------------------------------------------------
# the helpers, on their own
# ------------------------------------------------------------------

def test_the_subject_is_read_off_the_front():
    assert wire_subject("ARTSON LTD: CO. RECEIVES ORDER") == "ARTSON LTD"
    assert wire_subject("no colon here at all") is None


def test_a_speaker_is_recognised_without_a_matcher():
    for text in ("U.S. CENTCOM: anything",
                 "FED'S WARSH: anything",
                 "VANCE ON VENEZUELA: anything",
                 "SOURCE: NSE"):
        assert subject_is_not_a_company(text), text
    assert not subject_is_not_a_company("NTPC: CO. COMMISSIONS UNIT")
