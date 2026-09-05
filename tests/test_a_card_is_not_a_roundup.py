"""
==========================================================
One company is not a roundup
==========================================================

    "for me all info must be tagged properly & never mis ,
     duplicate , thats it"
                                -- the operator, 5 September 2026

THE TRAP THIS CLOSES

Day Trader Telugu posts single-company cards. The free picture-reader
transcribes one like this:

    STSCK IN NEWS  VEDANTA  e Reappoints Arun Misra as Executive
    Director  e Vedanta Semiconductors...

Two things in that text are accidents of a weak reader. "STSCK" is a
misread of STOCKS, and those "e" characters are bullets it could not
resolve. Both accidents are the ONLY reason the card survives today:
"stocks in news" is in the DIGEST pattern, and two bullets is a roundup
by the bullet rule.

Improve the reading -- one API key does it -- and the heading and the
bullets both resolve, the card becomes a "roundup", and it is refused.
Silently: no error, no log line. Measured on the store by replaying
every card message through the live path with the reading corrected:

    the rule as it stood      20 of 21 stocks lose their reason
    the rule in this file      3 of 21, and all three were a
                               separate matcher bug, since fixed

Twenty stocks -- ANGELONE, BRIGADE, COALINDIA, POWERGRID, RELIANCE,
WELCORP and the rest -- would have stopped reaching the door that
decides whether the bot may even look at them. A published reason is
MANDATORY before a stock is evaluated, so this is not a display bug.

WHY COUNTING COMPANIES IS THE RIGHT TEST

Measured through the live path on 5 September, with the refusal
switched off so it reported what it FOUND rather than what it refused:

    the 9 roundups   ->  8 name no company at all, 1 names two
    the 108 cards    ->  one company each

A card names its company once, at the top, and every bullet after it is
about that same company. Bullets, headings and emoji are decoration.
The number of subjects is the thing itself.

WHAT MUST NOT BREAK, and why each guard exists

  * ZERO companies is not one. A recap of #AAA, #BBB and #CCC resolves
    to no master symbol, and letting that through filed "Daily
    Highlights #AAA wins an order #BBB reports results" as a single
    ORDER event with no company on it. tests/test_expectation_page.py
    caught it the same hour. The escape needs a subject to protect.

  * A ROUNDUP WITH LEDE LINES stays refused however few names resolve.
    Day Trader Telugu's morning list --

        KPI Green - CFO Salim Yahoo ceases as CFO from Sept 2
        KSH Intl. - Received Unit 3 factory licence renewal till 2030
        FACT - Received communication from the Chemicals Ministry

    -- has no bullets, no tickers and no emoji, and eight such messages
    were held back by the heading alone. Two lines that each start a new
    subject is a roundup whatever the heading says.

Author : H&M Opportunity Trader
==========================================================
"""

from core.stock_events import is_digest


# The real thing, as the reader will transcribe it once it is better.
CARD = ("STOCKS IN NEWS\nVEDANTA\n"
        "• Reappoints Arun Misra as Executive Director w.e.f. August 1\n"
        "• Vedanta Semiconductors update")

CARD_TODAY = ("STSCK IN NEWS VEDANTA e Reappoints Arun Misra as "
              "Executive Director e Vedanta Semiconductors update")

ROUNDUP = ("Stocks in News\n"
           "KPI Green - CFO Salim Yahoo ceases as CFO and KMP from Sept 2\n"
           "KSH Intl. - Received Unit 3 factory licence renewal till 2030\n"
           "FACT - Received communication from the Chemicals Ministry")

RECAP = ("Daily Highlights\n#AAA wins an order\n#BBB reports results\n"
         "#CCC falls 5%\n")


# ------------------------------------------------------------------
# the card survives -- today, and after the reading improves
# ------------------------------------------------------------------

def test_one_company_is_not_a_roundup():
    assert is_digest(CARD, companies=1) is False


def test_the_card_survives_the_reading_being_fixed():
    """The whole point. Heading resolves, bullets resolve, and it is
    still a card because it is still about one company."""
    assert is_digest(CARD_TODAY, companies=1) is False
    assert is_digest(CARD, companies=1) is False


def test_the_old_rule_would_have_killed_it():
    """Kept as the record of what was actually wrong. Without the
    company count, the corrected text is refused."""
    assert is_digest(CARD) is True


# ------------------------------------------------------------------
# the roundup stays refused
# ------------------------------------------------------------------

def test_a_roundup_is_still_refused_when_no_name_resolves():
    """Eight of these were held back by the heading alone. The lede
    lines hold them now, so the heading is no longer load-bearing."""
    assert is_digest(ROUNDUP, companies=0) is True


def test_lede_lines_alone_are_enough():
    """No heading, no bullets, no tickers, no emoji -- just three lines
    that each start a new subject."""
    plain = ("KPI Green - CFO ceases as CFO and KMP from Sept 2, 2026\n"
             "KSH Intl. - Received Unit 3 factory licence renewal\n"
             "FACT - Received communication from the Ministry")
    assert is_digest(plain) is True


def test_a_roundup_naming_many_companies_is_refused():
    assert is_digest(ROUNDUP, companies=4) is True


def test_zero_companies_is_not_one():
    """A recap whose tickers resolve to nothing must NOT take the
    escape -- it was filed as a single ORDER event with no company."""
    assert is_digest(RECAP, companies=0) is True


# ------------------------------------------------------------------
# the historical damage, each case kept
# ------------------------------------------------------------------

def test_the_crocs_digest_is_still_refused():
    """Eight bulleted stories filed a Crocs revenue figure against
    MAHLIFE and SWIGGY with Rs 10,384 cr attached."""
    crocs = ("EARNINGS\n"
             "• Crocs Inc. reported Q2 FY26 revenue of $1.18 billion\n"
             "• Microsoft surged 9% after cloud beat\n"
             "• Swiggy narrows loss\n")
    assert is_digest(crocs, companies=2) is True


def test_the_sector_note_is_still_refused():
    """A regime note is not evidence about one company -- it was filed
    against COCHINSHIP, ATULAUTO, ASHOKLEY and WELCORP."""
    note = ("SECTORS TO WATCH OMCs, Paint, Aviation-Oil Declines For 3rd "
            "Session  Cochin Shipyard, Mazgaon Dock, GRSE-India plans to "
            "add 100 new vessels  Block Deal Today-Groww, Welspun Corp")
    assert is_digest(note, companies=4) is True


def test_three_tickers_is_still_a_digest():
    assert is_digest("#TATASTEEL #INFY #RELIANCE all report tomorrow") is True


def test_callers_without_a_count_are_unchanged():
    """tools/ and the audit scripts pass no count and must behave
    exactly as they did."""
    assert is_digest("Orderbook Recap\nDaily Highlights - JULY 28") is True
    assert is_digest("ACME wins a Rs 900 crore order from NHAI") is False


# ------------------------------------------------------------------
# and the wiring: the count has to be available when the question is
# asked, which means resolving BEFORE judging
# ------------------------------------------------------------------

def test_the_companies_are_resolved_before_the_digest_test():
    import io
    src = io.open("core/stock_events.py", encoding="utf-8").read()
    resolve_at = src.find("matcher.symbols_in(_for_matching(body))")
    judge_at = src.find("if is_digest(body, companies=")
    assert 0 < resolve_at < judge_at, \
        "the count must exist before the question is asked"
