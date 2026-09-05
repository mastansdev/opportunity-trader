"""A message about sectors is about the market, not about one company.

    "this 'SECTORS TO WATCH OMCs, Paint, Aviation...' statement is
     generalised one which suit the whole market regime. if war news or
     trump statement & escalation then whole market regime will shift &
     crude price surge damages the sectors mentioned omcs, paints,
     aviation. if de-escalates this statement is positive. whats so
     complex in this?"          -- the operator, 5 September 2026

Nothing, and the publisher says so in the heading. This message:

    SECTORS TO WATCH OMCs, Paint, Aviation-Oil Declines For 3rd
    Session  Cochin Shipyard, Mazgaon Dock, GRSE-India plans to add
    100 new vessels  Block Deal Today-Groww, Welspun Corp...

is three stories about a dozen companies, and it was filed as NEWS
against COCHINSHIP, ATULAUTO, ASHOKLEY and WELCORP -- one event each,
as though something had been published about that company.

is_digest() missed it because the companies are named in plain English
rather than as #TICKERS, so the three-ticker test found none, and
"sectors to watch" was not among the headings that mark a roundup.

A single-company card is untouched: "STSCK IN NEWS WELSPUN CORP Co &
Perma-Pipe sign MoU" carries no roundup heading and still files.
"""

from core.stock_events import is_digest

SECTOR_NOTE = ("SECTORS TO WATCH OMCs, Paint, Aviation-Oil Declines For 3rd "
               "Session Cochin Shipyard, Mazgaon Dock, GRSE-India plans to "
               "add 100 new vessels over next 5 years Block Deal Today-"
               "Groww, Welspun Corp Hind Copper")
OTHER_SECTORS = ("Other Sectors To Watch Metals-Strong China Manufacturing "
                 "PMI Data, But Hawkish Commentary")
ONE_COMPANY = ("STSCK IN NEWS WELSPUN CORP INVESTOR CALL ON 217,200 CR "
               "ORDER -- See huge demand for pipes")
TAKEOVER = ("TBZ: CO PROMOTER SELLS 74.12% STAKE TO GRT JEWELLERS FOR "
            "Rs 1,033.71 CRORE; OPEN OFFER TO FOLLOW")
ORDER_WIN = ("WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER IN "
             "COMPANY HISTORY VALUED AT USD 1.8 BN")


def test_a_sector_roundup_is_not_news_about_one_company():
    """THE case. It named a dozen companies and was filed against four
    of them, one event each."""
    assert is_digest(SECTOR_NOTE) is True


def test_the_other_heading_the_same_channel_uses():
    assert is_digest(OTHER_SECTORS) is True


def test_a_single_company_card_still_files():
    """The whole point of the guard is that it refuses roundups without
    refusing real stock news. 95 cards in the store carry this shape."""
    assert is_digest(ONE_COMPANY) is False


def test_a_takeover_still_files():
    assert is_digest(TAKEOVER) is False


def test_an_order_win_still_files():
    assert is_digest(ORDER_WIN) is False


def test_the_heading_is_matched_however_it_is_cased():
    for text in ("sectors to watch banking stocks",
                 "SECTOR TO WATCH: metals",
                 "Other Sectors To Watch Metals"):
        assert is_digest(text) is True, text
