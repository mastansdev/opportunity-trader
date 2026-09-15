"""
The dashboard must show what the bot knows.

    "you need to display what ever the bot is knowing = user needs to
     know right? once i can see everything, then only we both can work
     together & make the best use of the dashboard & Bot for trading
     otherwise it will be another show piece for sale without customers"
                                    -- operator, 30 July 2026

WHAT WENT WRONG, AND WHY A TEST HAD TO EXIST
--------------------------------------------
dashboard/static/index.html's shortlist panel read these field names:

    r.results_grade   r.filing_kind   r.news_kind
    r.volume_mult     r.blocked_reason r.does    r.reason

core/shortlist.py emits none of them. It emits:

    symbol sector ltp change_pct score vol_ratio veto grade news
    financials why s_no

So every tag rendered as nothing. The panel LOOKED fine -- symbol,
price, change -- and silently dropped `why`, the array that holds every
reason the stock is on the list:

    FILED RESULTS 1m ago
    STRONG: sales +8% QoQ, PAT +30% QoQ
    REPORTING TODAY
    CROWDED 26x -- likely already priced
    below 50d avg
    vol 4.9x

The bot knew all six. The operator saw none. Nothing errored, no console
warning, no empty state -- a misspelt field in JavaScript is just
`undefined`, and `if (undefined)` is quietly false. That is the entire
failure mode, and it is invisible by construction.

WHAT THIS FILE CHECKS
---------------------
1. Every field the HTML reads off a payload row EXISTS in the payload.
   A typo becomes a failing test instead of a blank column.

2. Fields the payload carries that NO panel displays are reported.
   Not all of them are failures -- some are internal -- so the ones
   deliberately not shown are listed explicitly and everything else
   fails. Adding data to the payload without surfacing it now requires
   saying so out loud.

This is the operator's rule turned into arithmetic. It cannot prove a
panel is READABLE, only that nothing is silently dropped.
"""

import re

import pytest

INDEX = "dashboard/static/index.html"


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


# ---------------------------------------------------------------
# ground truth -- what each builder actually emits
# ---------------------------------------------------------------
# Taken from the `return {...}` / `append({...})` of each builder, NOT
# from what the HTML hopes for. If a builder changes, this changes with
# it and the test says so.

SHORTLIST_ROW = {
    # core/shortlist.py, ranked.append(...)
    "symbol", "sector", "ltp", "change_pct", "score", "vol_ratio",
    "veto", "grade", "news", "financials", "why", "s_no",
}

# The chips the operator must be able to see. Each is produced by
# core/shortlist.py and each answers a different question, which is why
# collapsing them into one "reason" string is not good enough.
WHY_CHIP_SOURCES = (
    "FILED ",            # a filing landed, with minutes-ago
    "REPORTING TODAY",   # results are due today
    "CROWDED",           # volume says it is already priced
    "quiet",             # volume says it may not be noticed yet
    "below 50d avg",     # trend context
)


# ---------------------------------------------------------------
# 1. the HTML must not read fields that do not exist
# ---------------------------------------------------------------

# ---------------------------------------------------------------
# 2. nothing the bot knows may be dropped without saying so
# ---------------------------------------------------------------

# The 28 top-level keys dashboard/state.py._build() returns.
PAYLOAD_PANELS = {
    "ready", "updated_at", "capital", "advances", "declines", "unchanged",
    "universe_size", "gainers_losers", "shortlist", "breakouts", "actions",
    "announcements", "news", "market_intelligence", "book_analytics",
    "open_positions", "closed_positions", "risk_filters", "performance",
    "system_health", "entries_paused", "alerts", "signal_counts",
    "premarket", "preopen", "calendar", "telegram", "news_impact",
    "movers", "results_today",
    # added during 30 July and all now rendered in index.html
    "morning_brief", "corporate_actions", "journal", "fifty_two_week",
}

# Deliberately not rendered, with the reason. Anything NOT listed here
# and not referenced by the HTML fails the test below -- so silently
# adding a panel to the payload and forgetting the screen is caught.
NOT_DISPLAYED_ON_PURPOSE = {
    "ready": "a readiness flag, not information",
    "updated_at": "shown in the header, read via a different path",
    "morning_brief": "AI panels dropped on the operator's instruction",
    "shortlist": "no longer its own panel -- it is the source of the "
                 "score/grade/veto/why joined onto the Gainers and "
                 "Losers tables, which build_movers() reads directly",
    "fifty_two_week": "not surfaced in this layout yet",
    "signal_counts": "the journal panel shows taken/refused in full",
}


# ---------------------------------------------------------------
# 3. the ONE dashboard
# ---------------------------------------------------------------
# 30 July 2026. v2.html and v3.html are deleted and their routes removed:
#
#     "we will use this dashboard only as per choice. it is good & do the
#      job for now. remaining pls delete them."
#
# Everything built during the day was moved INTO index.html first, because
# it was missing 11 of 30 payload panels -- including `alerts`, which is
# where ALERT_ONLY_MODE writes. With the bot set to report instead of
# trade, that one gap would have meant the bot announcing every signal to
# a screen that was not listening.

# ---------------------------------------------------------------
# helpers
# ---------------------------------------------------------------

def _shortlist_function(src):
    """The body of the shortlist ROW renderer in index.html.

    Scoped deliberately to one renderer. Checking the whole file would
    pass because some OTHER panel happens to mention `why`, which is
    exactly the kind of false reassurance that let the original bug live.

    index.html declares it as an arrow template -- `const shortlistRow =
    (r) => ...` -- not as `function shortlist(...)`, so the slice runs to
    the next top-level declaration.
    """
    start = src.find("const shortlistRow")
    assert start != -1, "index.html has no shortlistRow renderer"
    nxt = min(
        (i for i in (src.find("\nconst ", start + 1),
                     src.find("\nfunction ", start + 1)) if i != -1),
        default=len(src))
    return src[start:nxt]


# ---------------------------------------------------------------
# THE MARKUP MUST BE BALANCED
# ---------------------------------------------------------------
# 30 July 2026, and this is the third blank page of the day. The cause was
# a missing </section>: three sections opened, two closed. `section.tab`
# carries `display:none`, so the unclosed one swallowed everything the
# browser parsed after it -- and the JavaScript was PERFECT. It parsed, it
# ran, it filled every panel in a headless harness. The page was blank
# because the markup around it was broken.
#
# Every check I had was on the script. None was on the HTML. So this is
# the cheap structural check that would have caught it in one second
# instead of an hour, and it applies to both dashboards.

import re as _re
from collections import Counter as _Counter

_STRUCTURAL = ("div", "header", "nav", "main", "section", "footer",
               "table", "thead", "tbody", "tr")


# ---------------------------------------------------------------
# THE TABS
# ---------------------------------------------------------------
#     "in tabs only ... i want clean & as simple as possible minimalist
#      dashboard with every details on click"
#
# The restructure MOVED panels, it did not rewrite them. The failure
# these guard against is not ugly markup -- it is a panel that quietly
# ends up in no tab at all, which looks exactly like the panel working,
# because a node with no visible ancestor renders perfectly into nothing.

TABS = ("tabPre", "tabLive", "tabPost")

# Every render target, and the tab it must live under. Moving a panel
# between tabs means moving it here too -- that is the point: the layout
# becomes a thing you change on purpose.
PANEL_HOME = {
    # PRE-MARKET -- RE-LAID 1 August 2026. The pre-open gaps table is
    # the tab now and everything else sits under it:
    #
    #     "page focus on pre-market gap ups & gap downs with chips of
    #      why? ... remaining all tables/boxes can be adjusted below
    #      these Pre-open gaps table."
    #
    # The single "World markets & commodities" box became three, to
    # order -- whichever list was longest used to push the other two
    # below the fold, and a panel you have to scroll to find the dollar
    # does not get read at 09:05.
    "poBox": "tabPre",
    "wmBox": "tabPre", "cmBox": "tabPre", "fxBox": "tabPre",
    "calBox": "tabPre", "rcBox": "tabPre",
    "pnBox": "tabPre", "pmnBox": "tabPre",
    # LIVE -- the trading day
    "alertsBox": "tabLive", "openRows": "tabLive",
    "gainRows": "tabLive", "loseRows": "tabLive", "moversThin": "tabLive",
    "breakoutRows": "tabLive", "mapBox": "tabLive", "tgBox": "tabLive",
    "newsRows": "tabLive", "annRows": "tabLive",
    "sectorHeatGainers": "tabLive", "sectorHeatLosers": "tabLive",
    "bookExposure": "tabLive", "panicSectors": "tabLive",
    # POST-MARKET -- the result, and why it turned out that way
    "closedRows": "tabPost", "jrBox": "tabPost",
    "actionLogRows": "tabPost", "healthGrid": "tabPost",
}

# Pinned above the tab bar, true on every tab.
#     "along with top section these items will be fixed on top
#      irrespective of tab we are in"
PINNED = ("topbarStats", "statCards", "pausedBanner", "endedBanner",
          "searchInput", "mktGrid", "breadthRow", "dailyGoalFill")


def _tab_slice(src, tab_id):
    start = src.find(f'id="{tab_id}"')
    assert start != -1, f"index.html has no #{tab_id}"
    end = src.find("</section>", start)
    assert end != -1, f"#{tab_id} is never closed -- that blanks the page"
    return src[start:end]


# ---------------------------------------------------------------
# PRE-MARKET, TO ORDER
# ---------------------------------------------------------------
#     "three tables in screen -- World markets & commodities ; Events
#      already happened, and scheduled (+/- 7 days events) in middle ;
#      Results, Corporate actions of the day
#      next tables -- Pre-open gaps collected ; NEWS Collected
#      only two tables - thats it for now."

def test_the_grouped_news_table_reads_both_sources():
    """    "news = we had RSS, TELEGRAM CHANNELS"

    The merge moved to Python; the contract did not move with it, so
    it is asserted where the work now happens."""
    state = _read("dashboard/state.py")
    body = state[state.index("def _build_news_table"):]
    body = body[:body.index("\n    def ", 10)]
    assert "news_watcher" in body, "RSS is not read"
    assert "self.telegram" in body, "the Telegram channels are not read"
    assert "rss_rows=" in body and "telegram_rows=" in body


# ---------------------------------------------------------------
# THE SEARCH BOX AND THE DRAWER
# ---------------------------------------------------------------
#     "pls add search option on top of the screen (may be next to PAPER
#      MODE)"
#
# The box searches the MASTER FILE, not the snapshot: a box that only
# finds what is already rendered is a filter, and the reason to type a
# symbol is that it is NOT in front of you. And a result needs somewhere
# to land -- index.html had no drawer at all, so /api/stock/{symbol} had
# eight sections of data and no reader.

CARD_SECTIONS = {"business", "price", "today", "results", "news",
                 "history", "position", "memory",
                 # 30 July 2026 -- the typed event memory, which is what
                 # made the drawer stop opening empty.
                 "events"}

CARD_FIELDS = {
    "business": {"name", "sector", "industry", "does", "type", "ownership",
                 "commodity_exposure", "economic_sensitivity", "themes",
                 "tradeable", "not_tradeable_because"},
    "price": {"last", "prev_close", "open", "high", "low", "volume",
              "upper_circuit", "lower_circuit", "change_pct",
              "pct_to_upper", "pct_to_lower"},
    "today": {"orb_high", "orb_low", "orb_complete", "blocked", "attempt",
              "volume_multiple"},
    "results": {"period", "grade", "summary", "sales_qoq", "pat_qoq",
                "sales_yoy", "pat_yoy", "opm_bps_qoq"},
    "history": {"trades", "wins", "win_rate", "pnl", "avg_pnl"},
    "position": {"qty", "entry_price", "entry_time", "entry_reason",
                 "stop", "yours"},
    "memory": {"actions", "count"},
    "events": {"rows", "count"},
}


def _renderer(src, name, next_name):
    """The body of one panel("name", () => {...}) block.

    Matched on the full registration, not the bare name: a comment that
    MENTIONS panel("results_corpactions") sits above panel("calendar"),
    so a plain find() sliced backwards and returned nothing -- and an
    empty slice passes any "not in" test and fails any "in" test for the
    wrong reason.
    """
    start = src.find(f'  panel("{name}", () => {{')
    assert start != -1, f'index.html has no panel("{name}") renderer'
    end = src.find(f'  panel("{next_name}", () => {{', start)
    return src[start:end if end != -1 else len(src)]


def _drawer_script(src):
    """renderCard()'s OWN body, not everything after it.

    ---- 3 August 2026 ----
    This used to return src[start:] -- the whole rest of the file --
    on the assumption that renderCard was the last thing in it. That
    stopped being true the evening the LIVE tab was split in two, and
    the contract tests immediately reported that the drawer was reading
    `business.class` and `business.dataset` off the stock card.

    It was not. Those are `b.classList` and `b.dataset` in the side-
    switching code that now sits below renderCard, swept in by a slice
    that never had an end.

    A test that widens its own scope as the file grows will keep
    inventing failures like that one. This walks the braces and returns
    the function, which is what it always meant.
    """
    start = src.find("function renderCard(")
    assert start != -1, "index.html has no renderCard() -- the drawer is dead"
    depth, i = 0, src.index("{", start)
    for j in range(i, len(src)):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                return src[start:j + 1]
    raise AssertionError("renderCard() has unbalanced braces")


# ---------------------------------------------------------------
# GAINERS AND LOSERS -- the one integrated table
# ---------------------------------------------------------------
#     "Shortlist what moved, and why -- ranked from here we will do as
#      per my order (top 50 stocks on each side)
#      Gainers | In Gainers only Buy option
#      Symbol Sector LTP Change% Score Why . breakouts ORB count
#      (1time =^ , 2nd ^^..)
#      losers make two tables after Gainers Table (always need clarity)
#      | In losers only Short option
#      everything will be integrated into this one table neatly"
#      "first Gainers table / next Losers table"
#      "not side by side one after another as more data will make table
#       so clumsy"
#
# Two panels used to describe the same 50 stocks differently: a 25-row
# scored Shortlist and a plain 50-a-side Gainers/Losers table with no
# reasons on it at all. Neither was complete -- the shortlist dropped
# anything under MIN_SCORE, so a stock up 14% with nothing filed behind
# it vanished from the only view that carried reasons.

MOVER_COLUMNS = ("#", "Symbol", "Sector", "LTP", "Change%", "Score", "ORB", "Why")


def test_fifty_a_side():
    state = open("dashboard/state.py", encoding="utf-8").read()
    fn = state[state.find("def build_movers(self):"):state.find("def _build_announcements")]
    assert fn.count("GAINERS_LOSERS_COUNT") == 2, (
        "both sides must be capped by the same constant (50)")


# ---------------------------------------------------------------
# READABILITY
# ---------------------------------------------------------------
#     "pls use standard fonts , colours which can be easily readable"

# ---------------------------------------------------------------
# THE TRANSCRIPTS HAVE TO REACH THE SCREEN
# ---------------------------------------------------------------
#     "terminal is printing.... can we see them in our dashboard?"
#                                     -- operator, 30 July 2026
#
# 77 of Day Trader Telugu's 90 messages are pictures with no text. The
# OCR work made them readable and the transcripts went to a terminal and
# nowhere else -- which is the same failure as every other panel built
# this week: the bot knew something the operator could not see.

def test_the_news_table_marks_an_ocr_item_at_the_source():
    """The flag has to be set where the two are still distinguishable
    -- by the time the browser sees it, text and transcript have been
    collapsed into one string."""
    from core.news_table import build

    out = build(telegram_rows=[
        {"text": "", "ocr_text": "#GHCL — Q1 FY27\nExceptional gain here.",
         "channel": "Earnings 360", "at": "2026-08-01T07:51:00",
         "symbols": ["GHCL"]},
        {"text": "#GHCL - OK Results", "ocr_text": "",
         "channel": "Earnings Pulse", "at": "2026-08-01T07:00:00",
         "symbols": ["GHCL"]},
    ])
    items = out["stocks"][0]["items"]
    assert items[0]["from_image"] is True
    assert items[1]["from_image"] is False


def test_the_payload_actually_carries_it():
    """The screen cannot show a field the builder never sends."""
    feed = open("core/telegram_feed.py", encoding="utf-8").read()
    assert '"ocr_text": (r["ocr_text"]' in feed, (
        "recent() must hand out the transcript as its own field")
    assert '"ocr_text" in r.keys()' in feed, (
        "an older database has no such column -- reading it blindly "
        "would raise on every refresh")


