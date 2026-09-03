"""---- THE DESK IS THE DASHBOARD NOW. 2 September 2026. ----

    "this is better than current dashboard"
    "make this my real dashboard with remaining tabs"
                                            -- the operator

/desk answers the five questions a trader actually asks, in the order
they are asked: where am I, what is moving, what would I do about it,
what am I holding, what have I done. The other seven tabs sit behind
it as reference.

WHAT THIS FILE DEFENDS

The failure this project keeps repeating is a layer that changed and a
layer that consumes it that did not -- so these tests do not check
that desk.html exists. They check that the route serves it, that the
operator token reaches it (without the token the page draws no BUY
control at all, which is how "the switch does nothing" starts), that
"/" actually lands there, and that /board is STILL REACHABLE, because
the rule since 6 August is that a new page goes beside the working one
and never in place of it. If the desk is wrong at 09:15 he types
/board and keeps trading.
"""

from fastapi.testclient import TestClient

from dashboard.server import build_app
from tests.test_dashboard_server import (_FakeDashboardState,
                                         _FakeMasterLoader,
                                         _FakeTradeController)

TOKEN = "s3cret"


def _client(operator_token=None, snapshot=None):
    app = build_app(_FakeDashboardState(snapshot), _FakeTradeController(),
                    _FakeMasterLoader(("TCS",)), operator_token=operator_token)
    return TestClient(app)


def test_the_desk_is_served():
    res = _client().get("/desk")
    assert res.status_code == 200
    assert "Opportunity Trader" in res.text


def test_the_desk_carries_all_eight_tabs():
    """He asked for the new design WITH the remaining tabs. A screen
    that dropped one would lose him a place he already reads."""
    body = _client().get("/desk").text
    for tab in ("live", "pre", "trade", "post", "watch", "brain",
                "tg", "refused"):
        assert f'data-tab="{tab}"' in body, f"the {tab} tab is missing"


def test_without_the_token_the_desk_draws_no_buy_button():
    """A read-only page must refuse at the BUTTON, not at the endpoint.
    The placeholder stays empty and IS_OPERATOR is false."""
    body = _client(operator_token=TOKEN).get("/desk").text
    assert 'window.__OPERATOR_TOKEN__ = "";' in body
    assert TOKEN not in body


def test_with_the_token_the_desk_can_trade():
    """The exact bug /board had on 11 August: served raw, placeholder
    never replaced, so the page drew "view only" on every row and the
    screen was useless to a man who trades by hand."""
    body = _client(operator_token=TOKEN).get(f"/desk?token={TOKEN}").text
    assert f'window.__OPERATOR_TOKEN__ = "{TOKEN}";' in body


def test_the_front_door_lands_on_the_desk():
    res = _client().get("/", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "/desk"


def test_the_front_door_carries_the_token_through():
    """Dropping it turns a working screen into a read-only one."""
    res = _client(operator_token=TOKEN).get(f"/?token={TOKEN}",
                                            follow_redirects=False)
    assert res.headers["location"] == f"/desk?token={TOKEN}"


def test_the_old_board_is_still_reachable():
    """BESIDE the working one, never in place of it. If the desk is
    wrong on a live morning, this is the way back."""
    assert _client().get("/board").status_code == 200


def test_the_desk_never_500s_on_a_half_built_snapshot():
    """The page polls /api/snapshot every 3 seconds, including before
    the first build finishes and after the session ends. Every section
    it reads may legitimately be absent."""
    client = _client(snapshot={"ready": False})
    assert client.get("/desk").status_code == 200
    assert client.get("/api/snapshot").status_code == 200


# ==========================================================
# THE BOARD IS THE BOT'S OWN LIST
# ==========================================================
#
#     "does bot's dashboard is used to buy or not?"
#                                     -- operator, 2 September 2026
#
# It is. main.py hands core.auto_entry.take() exactly
# snapshot["ranked"].rows + snapshot["early"].rows, so those two lists
# ARE the bot's shopping list -- if a stock is not on them, the bot
# cannot buy it.
#
# The first version of this page drew snapshot["shortlist"], a third
# and different key. That is a screen showing one thing while the bot
# acts on another, and 2 September has the proof: JINDRILL and
# SPORTKING were bought at 09:16 and 09:20 and appear in the picks
# table zero times all day. COALINDIA was bought at 09:17 and first
# reached the ranked board at 09:18 -- a minute AFTER the order.
#
# These tests read desk.html as text, on purpose. The failure they
# guard against is a key name, and a key name is exactly what a
# mocked payload would let me get wrong twice.

def _desk():
    return _client().get("/desk").text


def test_the_board_reads_the_two_lists_the_bot_buys_from():
    body = _desk()
    assert 'rowsOf(d.ranked)' in body, (
        "the board does not read snapshot['ranked'] -- the list "
        "main.py hands to auto_entry.take()")
    assert 'rowsOf(d.early)' in body, (
        "the board does not read snapshot['early'] -- the 09:15-09:30 "
        "lane, which bought 3 of 6 trades on 2 September")


def test_the_board_does_not_draw_the_shortlist_instead():
    """shortlist is a different key and the bot never sees it. It may
    only stand in when the bot's own lists are absent."""
    body = _desk()
    assert body.count("rowsOf(d.shortlist)") <= 1, (
        "shortlist is being drawn as the board in more than the one "
        "fallback position")
    assert "boardRows(d)" in body, "the board is not built by boardRows()"


def test_the_early_lane_is_marked_on_the_row():
    """Two doors, and he must be able to see which one a name came
    through -- the early lane has its own gates and its own record."""
    assert "EARLY LANE" in _desk()


# ==========================================================
# THE STOCK POPUP
# ==========================================================
#
#     "no link to check about stock details as old dashboard had. on
#      clicking on stock name pop shows the data of the stock with
#      orderflow - buying pressure. & remaining details"
#     "fold why & history into popup, drop the links. add results too"
#                                    -- operator, 2 September 2026

def test_the_popup_reads_all_four_endpoints():
    """One click, four reads. Fetched on open and never on the
    3-second poll: a session is 375 minutes and carrying the flow
    series for every row would put tens of thousands of points through
    the socket once a second to draw a chart nobody has opened."""
    body = _desk()
    for path in ("/api/stock/", "/api/flow/", "/api/why/", "/api/history/"):
        assert path in body, f"the popup never reads {path}"


def test_the_price_row_is_on_the_trade_panel():
    """     "there is no data of stock price details prev.close open
             high low cmp show them on THE TRADE PANEL" """
    body = _desk()
    assert "function priceRow(" in body
    for label in ("Prev close", "Open", "High", "Low", "CMP"):
        assert label in body, f"the trade panel does not show {label}"


def test_prev_close_is_fetched_not_computed():
    """It is not on the board row. Deriving it from change_pct would
    put a number on screen the exchange never printed -- and it must
    not wait for the popup either, or the cell reads as missing data
    rather than unfetched."""
    body = _desk()
    assert "function needPrev(" in body, (
        "prev close is not fetched when the panel draws")
    assert "prev_close" in body


def test_a_thin_book_is_not_drawn_as_a_confident_reading():
    """core/order_flow.still_buying() returns None below
    FLOW_MIN_BOOK_PCT because "a guess must not overrule a gate". A
    green bar drawn off 30% of the book is the same lie, in colour."""
    body = _desk()
    assert "classified" in body, "the popup never says how much was read"
    assert "60" in body, "the 60% bar is not named anywhere on the page"


def test_the_external_links_are_gone():
    """     "fold why & history into popup, drop the links."

    A link that leaves the screen mid-session is a link he does not
    click. /api/links and /api/tag were the old page's way out."""
    body = _desk()
    assert "/api/links" not in body
    assert "/api/tag" not in body


def test_one_cleaner_for_headlines_everywhere():
    """Telegram and filings carry emoji, a #SYMBOL prefix and a long
    tail. Two copies of the trimming drifted once already and left a
    star in the popup while the board row was clean."""
    assert "function clean(" in _desk()


# ==========================================================
# THE SEARCH BOX
# ==========================================================
#
#     "where is the search bar to check the stocks & recent event
#      info as i used to check in old dashboard"
#                                    -- operator, 2 September 2026
#
# /api/symbols has carried the docstring "for the header search box"
# since it was written, and the desk shipped without the box. 1,945
# symbols with name and sector, identity only -- no prices, no
# positions, nothing that could place or close anything.

def test_the_search_box_is_on_the_page():
    body = _desk()
    assert 'id="q"' in body, "there is no search input"
    assert "/api/symbols" in body, "the search reads no symbol index"


def test_search_reaches_stocks_that_are_not_on_the_board():
    """The whole point. The board is what qualified TODAY; he needs to
    look up a name that did not -- which is most of the 1,945."""
    body = _desk()
    assert "function runSearch(" in body
    assert "boardRows" not in body.split("function runSearch(")[1][:800], (
        "the search is filtering the board instead of the universe")


def test_a_search_hit_opens_the_same_popup():
    """One card, one code path. A second, thinner card for searched
    stocks is how the two drift until they disagree."""
    body = _desk()
    tail = body.split("function pickHit(")[1][:300]
    assert "openStock(" in tail, "a search hit does not open the stock card"


def test_the_search_says_how_many_it_knows_when_it_finds_nothing():
    """An empty dropdown reads as a broken box. Naming the count says
    the search worked and the name is genuinely not there."""
    assert "It watches" in _desk()


# ==========================================================
# THE 3% STOP
# ==========================================================

def test_the_stop_is_three_percent_on_every_path():
    """     "keep 3 % as stop loss after entry"

    Three files derive an entry stop. If they disagree the alert and
    the position disagree -- the TCS fault of 29 August. One dial.
    """
    from config import FIXED_STOP_PCT
    from core.atr import entry_stop_pct
    from core.position_plan import plan

    assert FIXED_STOP_PCT == 3.0
    assert entry_stop_pct("ANY") == 3.0
    got = plan(1000.0, "BUY", day_low=900.0, margin_pct=0.25, symbol="ANY")
    assert got["ok"], got
    assert got["stop"] == 970.0, got["stop"]
    assert got["stop_pct"] == 3.0


def test_a_fixed_width_still_obeys_the_bounds():
    """3.0 sits inside MIN/MAX, but a badly chosen number must still be
    caught by the same guards as everything else."""
    from core.rules import MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT
    from config import FIXED_STOP_PCT
    assert MIN_STOP_DISTANCE_PCT <= FIXED_STOP_PCT <= MAX_STOP_DISTANCE_PCT


# ==========================================================
# THE SWITCH SHOWS WHICH ONE IS TRUE
# ==========================================================
#
#     "if i click OFF = then bot show green color on OFF box . now ON
#      must not show any color"
#     "i clicked on OFF but color part not showed as i want"
#                                    -- operator, 3 September 2026
#
# TWO bugs, one behind the other.
#
# The first was colour: OFF painted itself RED, which reads as an
# error rather than as the state he just chose, and with neither box
# green he could not tell at a glance which was live.
#
# The second was worse and hid behind it. /api/snapshot returns
#
#     bot_trading: {on: false, mode: "PAPER", ...}
#
# and this page read it as `!!d.bot_trading`. An object is ALWAYS
# truthy in JavaScript, so the switch reported a CONSTANT: ON green
# for ever, whatever he clicked. The same read decided which trades
# went in the paper table and which in the real one, so that was
# wrong too, silently.
#
# The shape changed under a reader that assumed a boolean -- the same
# fault as prev_close, as shortlist-versus-ranked, as `close` in the
# feed backfill. Assert the source, because a truthiness bug throws
# no error and shows no stack.

def test_the_switch_reads_the_object_not_its_truthiness():
    body = _desk()
    assert "function switchIsOn(" in body, (
        "the page has no helper that unpacks bot_trading")
    # The phrase appears in the comment that explains the bug, so
    # look for it as CODE: an assignment, not prose.
    for bad in ("= !!d.bot_trading", "=!!d.bot_trading"):
        assert bad not in body, (
            "bot_trading is read as a boolean somewhere -- it is an "
            "object, and an object is always truthy")


def test_every_reader_of_the_switch_goes_through_it():
    body = _desk()
    assert body.count("switchIsOn(d)") >= 2, (
        "the trade tables and the switch must read the mode the same "
        "way, or one of them is wrong")


def test_the_active_side_is_the_coloured_one():
    """Green means THIS IS THE MODE, not 'good'. OFF green is paper,
    ON green is real, and the button text carries which."""
    body = _desk()
    assert ".sw button.active{" in body
    assert ".sw button.off{" not in body, (
        "OFF still has its own red style -- it reads as an error")
    assert 'on ? "active" : ""' in body
    assert 'on ? "" : "active"' in body
