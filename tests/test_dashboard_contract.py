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

def test_shortlist_reads_only_fields_that_exist():
    """The exact bug. Every one of these was read and none was sent."""
    src = _read(INDEX)
    body = _shortlist_function(src)
    read = set(re.findall(r'\br\.([a-z_][a-z0-9_]*)', body))
    unknown = read - SHORTLIST_ROW
    assert not unknown, (
        f"index.html's shortlist reads {sorted(unknown)}, which core/shortlist.py "
        f"never sends. In JavaScript a misspelt field is `undefined` and "
        f"`if (undefined)` is silently false, so the tag just never renders "
        f"and nothing complains. It emits: {sorted(SHORTLIST_ROW)}")


def test_shortlist_displays_the_why_chips():
    """`why` is the whole point of the panel -- it is the difference
    between "PCBL moved 15%" and "PCBL moved 15% because it filed results
    a minute ago, the numbers were STRONG, it reports today, and 26x
    volume says the move may already be priced".

    v2 ignored the field completely.
    """
    body = _shortlist_function(_read(INDEX))
    assert re.search(r'\br\.why\b', body), (
        "index.html's shortlist never reads r.why, so every reason chip the "
        "bot computed is dropped before it reaches the screen.")


def test_shortlist_shows_the_score_it_ranks_by():
    """Rows are ordered by score. Showing the order without the number
    means the operator cannot tell a 33 from a 21."""
    body = _shortlist_function(_read(INDEX))
    assert re.search(r'\br\.score\b', body)


def test_shortlist_shows_the_veto():
    """A veto is why the bot will NOT act on something that is otherwise
    on the list. Hiding it makes the list look like a buy list."""
    body = _shortlist_function(_read(INDEX))
    assert re.search(r'\br\.veto\b', body)


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


def test_every_payload_panel_reaches_the_screen():
    src = _read(INDEX)
    unreferenced = set()
    for key in PAYLOAD_PANELS:
        if key in NOT_DISPLAYED_ON_PURPOSE:
            continue
        if not re.search(r'[\.\["\']' + re.escape(key) + r'\b', src):
            unreferenced.add(key)
    assert not unreferenced, (
        f"the bot computes {sorted(unreferenced)} and index.html never shows "
        f"it. Either render it, or add it to NOT_DISPLAYED_ON_PURPOSE with "
        f"a reason. A panel the operator cannot see is work the bot did "
        f"for nobody.")


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


def test_the_helper_actually_isolates_one_function():
    """If _shortlist_function ever grabbed the whole file, every test
    above would pass for the wrong reason."""
    body = _shortlist_function(_read(INDEX))
    assert "const shortlistRow" in body
    assert body.count("const shortlistRow") == 1
    assert len(body) < len(_read(INDEX)) / 2


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


@pytest.mark.parametrize("path", [INDEX])
def test_markup_tags_are_balanced(path):
    """One missing close tag is a blank page, and nothing in the console
    says so -- the browser silently re-nests and moves on."""
    src = _read(path)
    start = src.find("<body>")
    end = src.find("<script>window.__OPERATOR")
    body = src[start:end if end != -1 else len(src)]
    opens = _Counter(_re.findall(r"<(" + "|".join(_STRUCTURAL) + r")\b", body))
    closes = _Counter(_re.findall(r"</(" + "|".join(_STRUCTURAL) + r")>", body))
    bad = {t: (opens[t], closes[t]) for t in set(list(opens) + list(closes))
           if opens[t] != closes[t]}
    assert not bad, (
        f"{path} has unbalanced markup {bad}. A missing close tag inside a "
        f"display:none section blanks the page with no console error.")


@pytest.mark.parametrize("path", [INDEX])
def test_scripts_are_not_trapped_inside_the_layout(path):
    """The drawer and the scripts must sit OUTSIDE <main>.

    This is the third-blank-page check, adapted. In v3 the trap was an
    unclosed `section.tab` carrying display:none; index.html has no tabs
    yet -- it is one column inside a single <main> -- so the equivalent
    check is that <main> is closed and every script tag comes after it.
    Nothing that paints may inherit a hidden ancestor.
    """
    src = _read(path)
    open_main = src.find("<main")
    close_main = src.rfind("</main>")
    assert open_main != -1, f"{path} has no <main>"
    assert close_main > open_main, (
        f"{path}: <main> is never closed -- everything after it inherits "
        f"whatever the browser re-nests it into")
    for match in _re.finditer(r"<script\b", src):
        assert match.start() < open_main or match.start() > close_main, (
            f"{path}: a <script> at offset {match.start()} sits inside "
            f"<main>. If an ancestor is ever hidden or unclosed the page "
            f"renders blank with nothing in the console.")


def test_every_id_the_script_writes_to_exists():
    """A getElementById() on an element that is not in the markup returns
    null, and the next .innerHTML throws -- which kills that panel and,
    before panel() wrapped them, killed every panel after it too.

    THIS TEST WAS BROKEN AND PASSED ANYWAY, 30 July 2026. It split the
    file on the string '<script>window.__OPERATOR' -- which does not
    exist. index.html has ONE <script> tag and the token placeholder sits
    inside it, on a later line. find() returned -1, so `script` was the
    last CHARACTER of the file and `used` was always the empty set. It
    could never fail. It was found only when a real orphan appeared
    (#caBox, whose markup moved into the Results box) and the test stayed
    green -- a test that cannot fail is worse than no test, because it is
    counted as coverage.

    The guard against that recurring is the assert on len(used) below: if
    the split ever breaks again, the test says so instead of passing.
    """
    src = _read(INDEX)
    split = src.find("<script>")
    assert split != -1, "index.html has no <script> tag"
    markup, script = src[:split], src[split:]
    have = set(_re.findall(r'id="([A-Za-z0-9_]+)"', markup))
    used = set(_re.findall(r'getElementById\("([A-Za-z0-9_]+)"\)', script))
    used |= set(_re.findall(r'\$\("([A-Za-z0-9_]+)"\)', script))
    assert len(used) > 40, (
        f"only {len(used)} element lookups found in the script -- the "
        f"split is wrong again and this test is passing vacuously")

    # Created at runtime by another renderer's innerHTML, so they are
    # legitimately absent from the static markup.
    # Nodes the page BUILDS rather than ships. The side nav, the
    # reversal panel and the side hint are inserted at the top of the
    # LIVE tab at load -- deliberately, so that 39 existing panels did
    # not have to be re-laid by hand the evening before he traded on
    # them. They are as real as any node in the markup; they simply are
    # not in it.
    #
    # otReversal and otMoving joined this list on 3 August 2026, when
    # the chip row began looking them up as jump targets. Both are
    # created EARLIER IN THE SAME PASS -- section 2b builds them, the
    # chips are wired at the end of the same function -- so the lookup
    # can never return null. They were already runtime nodes; nothing
    # about them changed except that something now reads them.
    BUILT_AT_RUNTIME = {"footerClock",
                        # The red "THIS PAGE IS NOT UPDATING" bar,
                        # 13 August 2026. Created by renderTrouble()
                        # with createElement the first time a render
                        # throws -- deliberately NOT in the markup, so
                        # a healthy page carries no hidden error banner
                        # waiting to be un-hidden by a styling mistake.
                        "otTrouble",
                        "otSideHint", "otReversal", "otReversalBody",
                        "otReversalBadge",
                        "otMoving", "otMovingBody", "otMovingBadge",
                        "otCallsBody", "otCallsBadge",
                        "otBookBody", "otBookBadge",
                        "otSectorTile", "otSectorList", "otCapTile",
                        # Written into otTopStrip's innerHTML by
                        # awarenessTile(), exactly as otSectorTile and
                        # otSectorList are. 3 August 2026.
                        "otAware", "otAwareList",
                        # ALL / NIFTY 50 / F&O, appended to otSideNav by
                        # renderUniverseBar() the same way the side nav
                        # itself is built. otSideNav joins the list for
                        # the same reason otReversal did: it is created
                        # by section 2b of the layout pass, and now
                        # something reads it. 4 August 2026.
                        "otUniBar", "otSideNav"}
    missing = sorted(used - have - BUILT_AT_RUNTIME)
    assert not missing, (
        f"the script writes to ids that do not exist: {missing}. Each one "
        f"throws on every refresh, is swallowed by panel()'s catch, and "
        f"fills the console with noise that hides the next real error.")


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


def test_there_are_exactly_three_tabs():
    src = _read(INDEX)
    assert src.count('class="tab"') == 3
    assert src.count("</section>") == 3, (
        "section opens and closes must match. An unclosed .tab carries "
        "display:none over everything the browser re-nests inside it, and "
        "that is the 29 July blank page.")


def test_every_tab_has_a_nav_button_and_vice_versa():
    src = _read(INDEX)
    buttons = set(_re.findall(r'data-tab="([A-Za-z0-9_]+)"', src))
    assert buttons == set(TABS), (
        f"nav buttons {sorted(buttons)} do not match tabs {sorted(TABS)} -- "
        f"a tab with no button is unreachable, and a button with no tab "
        f"hides everything when clicked")


@pytest.mark.parametrize("box,tab", sorted(PANEL_HOME.items()))
def test_each_panel_lives_in_its_tab(box, tab):
    src = _read(INDEX)
    assert f'id="{box}"' in src, f"{box} has vanished from the markup"
    assert f'id="{box}"' in _tab_slice(src, tab), (
        f"{box} is not inside #{tab}. It will render into a node the "
        f"operator cannot reach.")


@pytest.mark.parametrize("box", PINNED)
def test_the_pinned_header_is_outside_every_tab(box):
    """Market-wide truth does not belong to a tab. P&L, margin, the
    indices, breadth and the daily guardrail are as true on PRE-MARKET as
    on LIVE, and having to change tab to see whether the tape is with you
    is the opposite of what tabs are for."""
    src = _read(INDEX)
    assert f'id="{box}"' in src
    for tab in TABS:
        assert f'id="{box}"' not in _tab_slice(src, tab), (
            f"{box} sits inside #{tab}, so it vanishes on every other tab")


def test_the_open_tab_is_chosen_by_the_clock():
    """At 09:00 the operator wants the gaps; at 16:00 the day's result.
    A manual click must then win for the rest of the session -- the timer
    may not yank the page away from someone reading it."""
    src = _read(INDEX)
    assert "function tabForNow()" in src
    assert "TAB_PINNED" in src
    assert "setInterval(() => { if (!TAB_PINNED)" in src, (
        "the tab timer must check TAB_PINNED, or it overrides the "
        "operator's own choice every minute")


# ---------------------------------------------------------------
# PRE-MARKET, TO ORDER
# ---------------------------------------------------------------
#     "three tables in screen -- World markets & commodities ; Events
#      already happened, and scheduled (+/- 7 days events) in middle ;
#      Results, Corporate actions of the day
#      next tables -- Pre-open gaps collected ; NEWS Collected
#      only two tables - thats it for now."

def test_pre_market_has_exactly_five_tables_three_then_two():
    src = _read(INDEX)
    pre = _tab_slice(src, "tabPre")
    assert pre.count('class="grid-3"') == 1, "the top row must be three-up"
    assert pre.count('class="grid-2"') == 1, "the second row must be two-up"
    found = pre.count('class="panel compact"')
    assert found == 5, (
        f"PRE-MARKET must hold exactly five tables, found {found} "
        f"-- 'thats it for now'")


def test_pre_market_boxes_are_compact_and_scroll_capped():
    """"all boxes are bigger than it needed". They were -- each grew to
    fit its content, so one long table pushed the whole tab off screen."""
    src = _read(INDEX)
    assert ".panel.compact" in src
    assert ".scroll-cap { max-height" in src, (
        "boxes must scroll inside themselves, not push the page down")
    pre = _tab_slice(src, "tabPre")
    capped = pre.count('class="scroll-cap')
    assert capped == 8, (
        f"every PRE-MARKET box must be capped, {capped} of 8 are. "
        f"(counted on the class attribute -- 'scroll-cap-tall' contains "
        f"'scroll-cap', so a substring count double-counts. Eight since "
        f"1 August 2026: gaps, world markets, commodities, rates, "
        f"events, results, news, market news)")
    assert "position:sticky" in src, (
        "a scrolled table with no sticky header is unreadable")


def test_events_are_windowed_to_seven_days():
    src = _read(INDEX)
    body = _renderer(src, "calendar", "results_corpactions")
    assert "days_away <= 7" in body, "the +/- 7 day window is not applied"
    assert "recent" in body, "events that already happened must still show"
    assert "beyond" in body, (
        "if nothing falls inside 7 days the NEXT event must still show -- "
        "an empty box and a quiet fortnight look identical otherwise")


def test_results_and_corporate_actions_share_one_box():
    src = _read(INDEX)
    body = _renderer(src, "results_corpactions", "preopen")
    assert "snap.results_today" in body, "results of the day are not read"
    assert "snap.corporate_actions" in body, "ex-dates are not read"
    assert "held_reporting_today" in body, (
        "a held position reporting today can gap overnight -- it must be "
        "named, not left to be spotted in a list")


def test_the_preopen_table_shows_who_is_waiting():
    """    "we get info like buyers are waiting here ; Sellers are waiting
           here do u remember ? Redington it showed Buyers are waiting"

    core/preopen.py has collected totalBuyQuantity / totalSellQuantity
    since it was written. The panel showed IEP, gap and matched quantity
    and dropped every bit of it. REDINGTON on 30 July: 640,418 buys
    against 146,196 sells.

    ---- TWO CORRECTIONS, 3 August 2026 ----

    1. This docstring used to call those fields "the orders left
       UNMATCHED when the auction settled". They are not. NSE's own
       specification says the feed carries "total buy and sell quantity
       of the scrip" -- the WHOLE book across every price level,
       including bids far below the indicative price. That distinction
       is the likely reason MUTHOOTFIN showed 2.7x more buyers under a
       -7.81% gap and then fell anyway.

    2. The ratio is now computed in dashboard/state.py's
       _preopen_top(), so the row reads r.waiting and r.waiting_times
       rather than the raw quantities. The requirement is unchanged --
       the panel must say who is waiting -- but the arithmetic moved
       off the page.
    """
    src = _read(INDEX)
    body = _renderer(src, "preopen", "prenews")
    for field in ("waiting", "waiting_times"):
        assert field in body, f"the pre-open table drops r.{field}"
    assert "more buyers" in body or "more \" + r.waiting" in body, (
        "'imbalance +0.63' is not a sentence anyone reads at 09:10")
    # The legacy full-list branch still reads the raw imbalance.
    assert "imbalance" in body
    assert "balanced" in body, (
        "a 52/48 book must not be called 'buyers waiting' -- that makes "
        "the column noise")


def test_the_preopen_panel_does_not_call_it_unmatched():
    """NSE publishes the TOTAL book, not the residual. Describing it as
    'unmatched' on screen tells him a bid 20% below the price is
    somebody who tried to buy and could not."""
    body = _renderer(_read(INDEX), "preopen", "prenews")
    assert "sell unmatched" not in body
    assert "total buy and sell quantity" in body


def test_the_preopen_panel_is_two_tabs_of_ten():
    """    "Pre-open is printing all universe stocks why?"
           "Gap threshold - top 10 gainers /losers"

    2,224 rows on his real file, not filtered to what he can trade."""
    body = _renderer(_read(INDEX), "preopen", "prenews")
    assert "po.top" in body
    assert "data-potab" in body
    assert "GAP UP" in body and "GAP DOWN" in body


def test_pre_market_news_is_one_row_per_stock():
    """---- REWRITTEN 1 August 2026 ----

        "News collected - now it is a hell of mess with repeated items
         without clarity ... i need a clean table with
         Symbol  News (here details)  Time
         and mostly if the same stock gets more news, results from our
         sources. simply add them next to news column . not to print a
         separate line alone."

    The merge still happens and both sources still keep their labels --
    that part of the old contract stands and is asserted below. What
    changed is WHERE: core/news_table.py does the grouping in Python,
    because doing it in the renderer meant the browser held the only
    copy of the logic and nothing could test it.

    Measured on the real store that day: 300 stored messages produced
    300 paragraphs. Now 140 stock rows and 128 market items, with
    every message still reachable.
    """
    src = _read(INDEX)
    body = _renderer(src, "prenews", "__none__")
    assert "snap.news_table" in body, "the grouped table is not read"
    assert "it.source" in body, (
        "each ITEM must keep its own source -- 'from which sources we "
        "got them & at what time' is the point of the cell")
    assert "it.time" in body, "each item must keep its own clock"
    assert "pmnBox" in body, (
        "market commentary names no stock and must keep its own "
        "section -- mixed in, it is what made the panel unreadable")


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


def test_the_search_box_is_in_the_header_not_in_a_tab():
    src = _read(INDEX)
    assert 'id="searchInput"' in src
    head_start, head_end = src.find("<header>"), src.find("</header>")
    assert head_start < src.find('id="searchInput"') < head_end, (
        "the search box must live inside <header>, next to PAPER MODE")


def test_search_covers_the_whole_universe_not_just_the_screen():
    src = _read(INDEX)
    assert '"/api/symbols"' in src, (
        "the search box must call /api/symbols -- the master file. "
        "Searching snapshot rows only finds stocks already on screen, "
        "which is a filter, not a search.")
    body = src[src.find("function searchFor("):src.find("function drawSearchResults(")]
    for field in ("symbol", "name", "sector"):
        assert field in body, (
            f"searchFor() ignores {field}, so a company name or sector "
            f"finds nothing")


def test_search_ranks_symbol_prefix_first():
    src = _read(INDEX)
    body = src[src.find("function searchFor("):]
    assert "startsWith(needle)" in body
    assert "pre.concat(" in body, "the ranked buckets are not joined"


def test_enter_opens_the_top_hit_without_an_arrow_key():
    assert "SEARCH_HITS[SEARCH_SEL >= 0 ? SEARCH_SEL : 0]" in _read(INDEX), (
        "Enter must take the top hit when nothing is highlighted")


def test_a_dead_search_box_names_its_own_cause():
    """30 July 2026. The box printed "search unavailable" and the operator
    asked what it meant. The answer was that /api/symbols did not exist on
    the RUNNING process -- the HTML is re-read from disk on every page
    load, but FastAPI routes are built once at startup, so a new panel
    needs F5 and a new endpoint needs a restart."""
    src = _read(INDEX)
    assert "function searchUnavailable(" in src
    assert "r.status === 404" in src
    assert "search needs a bot restart" in src
    chain = src[src.find('fetch("/api/symbols")'):src.find("function searchFor(")]
    assert chain.count("searchUnavailable(") >= 4, (
        "the 404, non-OK, empty-index and network-failure paths must all "
        "report themselves")
    assert ".catch((e) => searchUnavailable(" in chain


def test_the_drawer_exists_and_sits_outside_every_tab():
    src = _read(INDEX)
    for box in ("drawer", "drawerBody", "drawerSymbol", "drawerBack", "drawerClose"):
        assert f'id="{box}"' in src, f"the drawer is missing #{box}"
        for tab in TABS:
            assert f'id="{box}"' not in _tab_slice(src, tab), (
                f"#{box} is inside #{tab} -- it would only open on one tab")


@pytest.mark.parametrize("section", sorted(CARD_SECTIONS))
def test_every_card_section_reaches_the_drawer(section):
    body = _drawer_script(_read(INDEX))
    assert _re.search(r"\bc\." + section + r"\b", body), (
        f"renderCard() never reads c.{section}, so that whole section of "
        f"what the bot knows is fetched and thrown away")


@pytest.mark.parametrize("section", sorted(CARD_FIELDS))
def test_the_drawer_reads_only_card_fields_that_exist(section):
    body = _drawer_script(_read(INDEX))
    alias = _re.search(r"const (\w+) = c\." + section + r"\b", body)
    if alias is None:
        pytest.skip(f"{section} is read inline, not via a local alias")
    read = set(_re.findall(r"\b" + alias.group(1) + r"\.([a-z_][a-z0-9_]*)", body))
    unknown = read - CARD_FIELDS[section]
    assert not unknown, (
        f"the drawer reads {sorted(unknown)} off the {section} section, "
        f"which core/stock_card.py never sends. It emits: "
        f"{sorted(CARD_FIELDS[section])}")


def test_symbols_in_tables_are_clickable():
    """A drawer nothing opens is a drawer nobody sees. The listener must
    be delegated -- every row is thrown away and rebuilt on each refresh,
    so a listener bound to a row dies with the row."""
    src = _read(INDEX)
    assert src.count("data-stock=") >= 5, (
        f"only {src.count('data-stock=')} clickable symbols")
    assert 'document.addEventListener("click"' in src
    assert 'closest("[data-stock]")' in src


def test_a_missing_value_shows_a_dash_not_undefined():
    """    "WHY (if any thing supports it will go here. if no data
           available simply --)" """
    src = _read(INDEX)
    kv = src[src.find("const kv = "):src.find("const dsec = ")]
    assert "—" in kv and "undefined" in kv


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


def test_gainers_come_first_then_losers_stacked():
    """"first Gainers table / next Losers table", and stacked, because
    "not side by side one after another as more data will make table so
    clumsy"."""
    live = _tab_slice(_read(INDEX), "tabLive")
    g, l = live.find("<h2>Gainers"), live.find("<h2>Losers")
    assert g != -1 and l != -1, "one of the two tables is missing"
    assert g < l, "Losers is rendered before Gainers"
    between = live[g:l]
    assert "grid-2" not in between and "grid-3" not in between, (
        "the two tables must stack, not sit side by side -- each carries "
        "eight columns including a wrapping Why cell")


@pytest.mark.parametrize("column", MOVER_COLUMNS)
def test_both_tables_carry_every_column_asked_for(column):
    live = _tab_slice(_read(INDEX), "tabLive")
    head = live[live.find("<h2>Gainers"):live.find("<h2>Losers")]
    assert f">{column}<" in head or f'">{column}</th>' in head, (
        f"the Gainers table has no {column} column")


def test_one_direction_per_table():
    """A table offering both directions on every row is a table you can
    misread in a hurry."""
    src = _read(INDEX)
    body = src[src.find("const moverRow = "):src.find('panel("movers"')]
    assert 'data-buy=' in body and 'data-short=' in body
    assert 'r.direction !== "SHORT"' in body, (
        "the action must be chosen by the row's own direction, not by "
        "which table it happens to be rendered into")


def test_movers_is_a_left_join_so_a_reasonless_mover_still_shows():
    """The whole point of merging. A stock up 14% that the shortlist
    never scored must still appear -- with an em dash, per the operator's
    standing rule "if no data available simply --"."""
    state = open("dashboard/state.py", encoding="utf-8").read()
    fn = state[state.find("def build_movers(self):"):state.find("def _build_announcements")]
    assert "reasons.get(row.get(\"symbol\"))" in fn, (
        "movers must be built from the 50 MOVERS with reasons attached, "
        "not from the scored shortlist filtered down -- the second drops "
        "every mover the shortlist never scored")
    src = _read(INDEX)
    body = src[src.find("const moverRow = "):src.find('panel("movers"')]
    assert "r.score == null" in body, "a missing score must render as a dash"

    # The RULE, not the line that happened to implement it. This used to
    # assert the literal '(r.why || []).length ?' and broke on 31 July
    # when the chips moved into whyCell() -- while the behaviour it was
    # guarding was still correct. A test that fails on a refactor it
    # should not care about teaches people to edit tests without
    # reading them.
    cell = src[src.find("function whyCell("):]
    cell = cell[:cell.find("\n}")]
    assert "empty-note" in cell and "mdash" in cell, (
        "a mover with no reasons must still render, with an em dash -- "
        '"if no data available simply --"')
    assert cell.find("if (!why.length)") < cell.find("support"), (
        "the empty case must be answered before anything reads the "
        "backing count")


def test_fifty_a_side():
    state = open("dashboard/state.py", encoding="utf-8").read()
    fn = state[state.find("def build_movers(self):"):state.find("def _build_announcements")]
    assert fn.count("GAINERS_LOSERS_COUNT") == 2, (
        "both sides must be capped by the same constant (50)")


def test_the_orb_attempt_count_uses_the_operators_notation():
    """    "breakouts ORB count (1time =^ , 2nd ^^..)" """
    src = _read(INDEX)
    body = src[src.find("const orbMark = "):src.find("const moverRow = ")]
    assert '"^".repeat(' in body, "the caret notation is not used"
    assert "title=" in body, (
        "past two carets the count stops being readable at a glance -- "
        "the tooltip has to carry the plain sentence")
    state = open("dashboard/state.py", encoding="utf-8").read()
    fn = state[state.find("def build_movers(self):"):state.find("def _build_announcements")]
    assert '"LONG"' in fn and '"SHORT"' in fn, (
        "a gainer's attempts are LONG attempts and a loser's are SHORT -- "
        "asking the feed about the wrong side reports a level the stock "
        "is not testing")


def test_the_old_duplicate_panels_are_gone():
    """Two panels describing the same 50 stocks differently was the
    problem, so neither may survive the merge."""
    live = _tab_slice(_read(INDEX), "tabLive")
    # Checked on the ELEMENT IDS, not the old headings: a comment
    # explaining where a panel went legitimately mentions its name, and
    # asserting on prose makes the test fail on its own documentation.
    for gone in ('id="shortlistRows"', 'id="gainersRows"', 'id="losersRows"',
                 'id="shortlistThin"', 'id="glUpdatedAt"'):
        assert gone not in live, f"{gone} survived the merge"
    assert live.count("<h2>Top 50") == 0, "the old combined panel is still there"


def test_the_sector_heatmap_still_has_its_data():
    """gainers_losers feeds the heatmap as well. Removing the TABLES must
    not have unwired the payload underneath them."""
    src = _read(INDEX)
    assert "gl.sector_gainers" in src and "gl.sector_losers" in src
    state = open("dashboard/state.py", encoding="utf-8").read()
    assert '"gainers_losers": gainers_losers' in state
    # _timed() wraps it since 3 Sep -- the panel must still be
    # built and still feed the snapshot, which the two asserts
    # above and below already prove.
    assert "self._build_gainers_losers" in state


# ---------------------------------------------------------------
# READABILITY
# ---------------------------------------------------------------
#     "pls use standard fonts , colours which can be easily readable"

def test_chips_are_theme_variables_not_hardcoded_dark_hexes():
    """The chips carried hardcoded dark hexes -- fine on the dark theme,
    and on the light theme they rendered as saturated blocks of navy,
    maroon and brown on white. That is the eye strain reported twice."""
    src = _read(INDEX)
    for chip in ("sl-news", "sl-crowded", "sl-quiet", "sl-up", "sl-down", "sl-veto"):
        rule = src[src.find(f"  .{chip} "):]
        rule = rule[:rule.find("\n")]
        assert "var(--chip-" in rule, (
            f".{chip} still hardcodes its colours: {rule.strip()}")
    # twice as a definition (dark, light) and once where it is used
    assert src.count("--chip-news-bg") == 3, (
        "each chip colour must be defined once per theme -- dark and "
        "light -- and read once by the rule that uses it")


def test_the_font_stack_is_standard_and_needs_no_download():
    src = _read(INDEX)
    assert "font-family: system-ui" in src
    assert "@import" not in src and "fonts.googleapis" not in src, (
        "a dashboard that waits on a webfont shows a blank table at 09:15")


def test_numbers_line_up_column_wise():
    assert "tabular-nums" in _read(INDEX), (
        "proportional digits make a price column jitter as it ticks")


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

def test_a_transcript_is_labelled_never_silently_merged():
    """A machine reading a screenshot and a person typing a sentence are
    not the same kind of evidence. Presenting them identically would
    launder one into the other."""
    src = _read(INDEX)
    assert "const msgBody = " in src, "no shared message-body renderer"
    body = src[src.find("const msgBody = "):src.find("const shortlistRow = ")]
    assert "r.ocr_text" in body, "the transcript is never read"
    assert "read from image" in body, (
        "a transcript must be labelled as one")
    assert "ocr-tag" in body


def test_a_typed_message_and_its_picture_are_both_shown():
    """OrderBook Pulse posts a sentence AND a card. Showing only one
    throws away half the message."""
    src = _read(INDEX)
    body = src[src.find("const msgBody = "):src.find("const shortlistRow = ")]
    assert "if (typed && read)" in body, (
        "when a message has both, both must render")


def test_an_unread_picture_says_so():
    """An empty row looks like a message with nothing in it. That is not
    what happened -- nobody has read it yet."""
    src = _read(INDEX)
    body = src[src.find("const msgBody = "):src.find("const shortlistRow = ")]
    assert "image not read yet" in body
    assert "telegram_ocr.py" in body, "say what to run about it"


def test_the_live_message_panel_uses_the_shared_renderer():
    """One definition. Two panels each formatting messages their own way
    is how one of them silently stops showing transcripts."""
    src = _read(INDEX)
    start = src.find('getElementById("tgBox")')
    assert start != -1, "#tgBox is never written to"
    assert "msgBody(" in src[start - 900:start + 900], (
        "the tgBox panel formats messages itself instead of using "
        "msgBody()")


def test_the_premarket_news_table_still_says_when_a_machine_read_it():
    """---- NARROWED 1 August 2026, AND THE PROMISE KEPT ----

    pnBox used to render full message bodies through msgBody(), which
    is why it shared that renderer. It now renders a GROUPED table --
    one row per stock, a trimmed headline per item -- because the full
    bodies averaged 211 characters and 300 of them were the mess the
    operator asked to have cleaned up.

    What must NOT be lost in the trimming is the label. A machine
    reading a screenshot and a human typing a sentence are not the same
    kind of evidence, and the operator has to be able to tell which he
    is looking at. msgBody() says "read from image"; so does this.
    """
    src = _read(INDEX)
    body = _renderer(src, "prenews", "__none__")
    assert "it.from_image" in body, (
        "an OCR'd card is no longer distinguishable from a typed post")
    assert "read from image" in body
    assert "ocr-tag" in body


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


def test_the_drawer_shows_transcripts_too():
    """The per-stock card is where "why is this moving" gets answered."""
    body = _drawer_script(_read(INDEX))
    assert "msgBody(m)" in body


def test_the_payload_actually_carries_it():
    """The screen cannot show a field the builder never sends."""
    feed = open("core/telegram_feed.py", encoding="utf-8").read()
    assert '"ocr_text": (r["ocr_text"]' in feed, (
        "recent() must hand out the transcript as its own field")
    assert '"ocr_text" in r.keys()' in feed, (
        "an older database has no such column -- reading it blindly "
        "would raise on every refresh")


def test_the_drawer_shows_what_has_happened():
    """    "upon clicking on stock name the box opening right now is not
           showing any data"

    The event section is the answer to that. It carries the CHANNELS --
    a graded result seconds after a filing, an order win with its value
    and customer -- which is data no other section on the card has.
    """
    body = _drawer_script(_read(INDEX))
    assert "const ev = c.events;" in body, "the drawer never reads c.events"
    assert "What has happened" in body
    for field in ("kind", "grade", "value_cr", "counterparty", "headline"):
        assert f"e.{field}" in body, f"the event section drops {field}"
    assert "from_image" in body, (
        "an event read off a screenshot must say so -- it is a different "
        "kind of evidence from a typed message")
