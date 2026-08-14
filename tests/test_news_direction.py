"""
==========================================================
The button has to match the news
==========================================================

    "never assume-give clarity on every item residing in bot =
     dashboard"                     -- operator, 3 August 2026

Two defects on the LIVE tab's News panel, both found by reading what
the payload already carried.

STANCE WAS COMPUTED AND THROWN AWAY
-----------------------------------
core/news_watcher.py runs classify_stance() on every row and returns
POSITIVE, NEGATIVE or NEUTRAL. The word appeared in index.html ZERO
times. So this:

    "Jefferies downgrades TCS to Underperform"   -> NEGATIVE

arrived with a green BUY button, identical to an order win. The bot
knew the direction and did not say it.

THE BUTTON ACTED ON A STOCK HE WAS NOT LOOKING AT
-------------------------------------------------
The cell printed every symbol -- "TCS, INFY, WIPRO" -- and the single
button carried symbols[0]. Clicking it bought TCS while he read about
three companies, with nothing on screen saying which one it meant.

AND ONE I ALMOST SHIPPED
------------------------
My first version returned BUY for every row without a stance. Five
categories have no stance because their sign is fixed by the category,
and two of those are DISASTER and REGULATORY. That would have put a
green BUY button on a factory fire.

Author : H&M Opportunity Trader
==========================================================
"""

import re

import pytest

from core.news_watcher import STANCE_RULES, classify_stance

PAGE = "dashboard/static/index.html"


def html():
    return open(PAGE, encoding="utf-8").read()


def block():
    src = html()
    return src[src.index("const NEWS_FIXED"):src.index("const newsRow =")]


# ---------------------------------------------------------------
# 1. THE ENGINE ALREADY KNEW
# ---------------------------------------------------------------
@pytest.mark.parametrize("kind,headline,stance", [
    ("BROKER", "Jefferies downgrades TCS to Underperform", "NEGATIVE"),
    ("BROKER", "Morgan Stanley upgrades SBIN to Overweight", "POSITIVE"),
    ("BROKER", "Jefferies maintains Hold on Infosys", "NEUTRAL"),
    ("GUIDANCE", "Company cuts FY27 revenue outlook", "NEGATIVE"),
    ("MANAGEMENT", "CFO resigns with immediate effect", "NEGATIVE"),
])
def test_the_engine_returns_a_direction(kind, headline, stance):
    assert classify_stance(kind, headline) == stance


def test_only_four_categories_carry_a_stance():
    assert set(STANCE_RULES) == {"BROKER", "GUIDANCE", "LEGAL", "MANAGEMENT"}


# ---------------------------------------------------------------
# 2. THE SCREEN NOW USES IT
# ---------------------------------------------------------------
def test_the_panel_reads_the_stance():
    src = html()
    assert 'r.stance === "NEGATIVE"' in src
    assert 'r.stance === "POSITIVE"' in src


def test_negative_news_offers_a_sell_not_a_buy():
    body = block()
    assert 'if (r.stance === "NEGATIVE") return "SELL";' in body
    assert 'if (r.stance === "POSITIVE") return "BUY";' in body


def test_a_genuine_non_event_offers_nothing():
    """     "Jefferies maintains Hold" is a real non-event.

    Same rule the causes panel settled on: where the bot has no
    direction, it offers no action."""
    body = block()
    assert 'if (r.stance === "NEUTRAL") return null;' in body
    assert "no clear direction" in html()


# ---------------------------------------------------------------
# 3. A FIRE IS NOT A BUY
# ---------------------------------------------------------------
def test_a_disaster_is_never_a_buy():
    """The version I wrote first returned BUY for every stanceless row,
    and DISASTER is stanceless."""
    body = block()
    assert 'DISASTER: "SELL"' in body
    assert 'REGULATORY: "SELL"' in body


def test_an_order_win_is_a_buy():
    assert 'ORDER_WIN: "BUY"' in block()


def test_the_genuinely_two_sided_categories_get_no_button():
    """A block deal is a strategic buyer arriving or a promoter
    leaving. A QIP is growth capital or dilution. The bot has no view
    and says so by offering nothing."""
    body = block()
    fixed = re.search(r"const NEWS_FIXED = \{([^}]*)\}", body).group(1)
    assert "DEAL" not in fixed
    assert "FUND_RAISE" not in fixed


def test_every_kind_is_either_mapped_or_deliberately_left_out():
    """A category nobody thought about would silently get no button and
    look like a bug rather than a decision."""
    kinds = set(re.findall(r'\("([A-Z_]{4,})", re\.compile',
                           open("core/news_watcher.py", encoding="utf-8").read()))
    body = block()
    fixed = set(re.findall(r"(\w+): \"(?:BUY|SELL)\"", body))
    handled = fixed | set(STANCE_RULES) | {"DEAL", "FUND_RAISE"}
    assert kinds <= handled, kinds - handled


# ---------------------------------------------------------------
# 4. THE BUTTON NAMES ITS STOCK
# ---------------------------------------------------------------
def test_every_symbol_in_the_row_gets_its_own_button():
    body = html()[html().index("const newsButtons"):]
    body = body[:body.index("const newsRow =")]
    assert "syms.map(" in body
    assert "r.symbols && r.symbols.length" in body


def test_a_multi_stock_row_says_which_button_is_which():
    body = html()[html().index("const newsButtons"):]
    body = body[:body.index("const newsRow =")]
    assert "syms.length > 1" in body


def test_a_row_with_no_symbol_does_not_produce_a_ghost_button():
    """filter(Boolean) -- an empty symbols list must not render
    data-buy="undefined"."""
    body = html()[html().index("const newsButtons"):]
    body = body[:body.index("const newsRow =")]
    assert ".filter(Boolean)" in body


def test_filed_today_is_deliberately_left_neutral():
    """     "both KFINTECH (+9.2%) and ACUTAAS (a loss for us) filed
             results the same week and nothing in the subject separated
             them."

    That reasoning still holds, so Filed Today keeps a single BUY and
    is NOT given a direction from the filing category."""
    src = html()
    assert "Colour marks the category, never a recommendation." in src
