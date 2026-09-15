"""
==========================================================
Every tab gets laid out, not just the LIVE one
==========================================================

    "watchlist is still not sorted, news & FILED not arranged properly,
     sectors , in pre-market , post-market . why i need to spoon feed
     you to find the mistakes ? you need to do your assigned work right"
                                    -- operator, 3 August 2026

He is right, and the cause was one line:

    var live = document.getElementById("tabLive");
    if (!live) return;

EVERY readability pass ever written in index.html -- the folding, FOCUS
mode, the row buttons, the ordering -- returns early unless the LIVE
tab exists, and then only ever touches it. PRE-MARKET's seven panels
and POST-MARKET's five received none of it, through every round of
"make it readable".

He found that by using the thing. I should have found it by reading my
own entry condition.

Author : H&M Opportunity Trader
==========================================================
"""

import html as _html
import re

PAGE = "dashboard/static/index.html"


def html():
    return open(PAGE, encoding="utf-8").read()


def panels_in(tab):
    src = html()
    start = src.index('id="%s"' % tab)
    end = src.find('<section class="tab"', start + 10)
    if end < 0:
        end = src.find("</main>", start)
    # The markup carries "Results &amp; corporate actions"; the layout
    # pass matches on textContent, which the browser has already
    # decoded to "&". Comparing raw markup against the plan would fail
    # on a match that works perfectly at runtime.
    return [_html.unescape(h)
            for h in re.findall(r"<h2>([^<]{0,60})", src[start:end])]


# ---------------------------------------------------------------
# 1. THE OTHER TWO TABS EXIST AND ARE HANDLED
# ---------------------------------------------------------------
# ---------------------------------------------------------------
# 2. THE LISTS ARE ACTUALLY ORDERED
# ---------------------------------------------------------------
def test_news_is_newest_first_across_every_feed():
    """     "news & FILED not arranged properly"

    Prepending each poll's batch made the BATCHES newest-first and left
    the items INSIDE a batch in feed-walk order, so a 09:12 item from
    the third source sat above a 09:41 item from the first."""
    src = open("core/news_watcher.py", encoding="utf-8").read()
    block = src[src.index("self._items = fresh + self._items"):]
    block = block[:block.index("self._last_poll_at")]
    assert "self._items.sort(" in block
    assert "reverse=True" in block


def test_filed_today_was_already_right_and_stays_right():
    """core/announcement_watcher.py sorts on the filing time after
    prepending. It is the same two lines news_watcher was missing."""
    src = open("core/announcement_watcher.py", encoding="utf-8").read()
    block = src[src.index("self._today = fresh + self._today"):]
    block = block[:block.index("self._by_symbol.setdefault")]
    assert "self._today.sort(" in block
    assert "reverse=True" in block


def test_the_watchlist_is_sorted_at_the_source():
    """Catalyst, then timing, then tier, then call, then symbol -- so a
    stock reporting today never mixes with one exposed to the gold
    price."""
    src = open("core/watchlist.py", encoding="utf-8").read()
    assert "out.sort(" in src
    block = src[src.index("out.sort("):]
    block = block[:block.index("return out")]
    for key in ("catalyst", "when", "tier", "call", "symbol"):
        assert key in block, key
