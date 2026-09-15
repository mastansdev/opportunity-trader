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
# ---------------------------------------------------------------
# 3. A FIRE IS NOT A BUY
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 4. THE BUTTON NAMES ITS STOCK
# ---------------------------------------------------------------
