"""
==========================================================
Two screens, two jobs -- and neither goes blind
==========================================================

    "we are not even doing 5 - 10% of their working dashboard.
     still we can't create one dashboard since 1 month."
                                -- operator, 12 August 2026
    "if we want we can open the full right? or like tabs dashboard?"
                                -- operator, 13 August 2026

Measured on 13 August: FOUR pages, 10,710 lines, and he used one.

    board.html    1,061 lines   14 fields   /board          <- his
    app.html      1,306 lines   35 fields   /  /app
    index.html    6,893 lines   42 fields   /full
    screen.html   1,450 lines   28 fields   /screen  /old

A month of effort split four ways. The startup banner pointed at the
wrong page twice in two days, and on 12 August he was told to "watch
the broker_stop panel" when that panel was on a page he had left.

NOT COLLAPSED INTO ONE
----------------------
board.html is deliberately thin. His brief on 8 August was "one verdict
not six chips" and "no more top 50/20/10 gainers tables". Forcing
index.html's 42 panels into it would undo the thing he asked for.

So: two screens, two jobs.

    /board   TRADING      one table, one verdict, decide and click
    /full    DIAGNOSTICS  every panel, opened when something looks off

app.html and screen.html were deleted -- a third and fourth page doing
neither job. Every route they held redirects to /board, carrying the
token, because a redirect that drops it turns a working screen into a
read-only one.

WHAT THIS FILE GUARDS
---------------------
  1. The trading screen can still draw a row and act on it.
  2. The diagnostics screen still carries what the board leaves out.
  3. You can get from either to the other without typing a URL.
  4. The retired routes never serve a page again.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard" / "static"
BOARD = STATIC / "board.html"
FULL = STATIC / "index.html"
STATE = ROOT / "dashboard" / "state.py"


# ---------------------------------------------------------------
# 1. THE TRADING SCREEN
# ---------------------------------------------------------------
#: Without these /board cannot draw a row or tell him it is safe.
#: Deliberately SHORT -- it is one table by design, and a long list
#: here would be the "six chips" he asked to be rid of.
BOARD_MUST_READ = {
    "gainers_losers": "the rows themselves",
    "ranked": "the verdict and the reason on each row",
    "bot_trading": "is the bot armed",
    "open_positions": "what he is holding",
    "broker_stop": "is there a stop at Dhan, or does it die with "
                   "this process",
}


@pytest.mark.parametrize("field", sorted(BOARD_MUST_READ))
def test_the_trading_screen_reads_it(field):
    text = BOARD.read_text(encoding="utf-8", errors="replace")
    assert field in text, (
        f"board.html never reads snapshot['{field}'] -- "
        f"{BOARD_MUST_READ[field]}. That is the screen he trades from.")


@pytest.mark.parametrize("field", sorted(BOARD_MUST_READ))
def test_the_snapshot_publishes_what_the_board_reads(field):
    """A page reading a field state.py stopped publishing renders an
    empty cell forever and looks like a working panel with no data."""
    state = STATE.read_text(encoding="utf-8", errors="replace")
    assert f'"{field}"' in state, (
        f"dashboard/state.py no longer publishes '{field}'")


# ---------------------------------------------------------------
# 2. THE DIAGNOSTICS SCREEN
# ---------------------------------------------------------------
#: The board is thin ON PURPOSE, so these live on /full. Losing them
#: from BOTH screens is how a bot goes blind -- the 12 August fault,
#: where a panel existed in state.py and on no page he opened.
FULL_MUST_READ = {
    "journal": "why the bot said no -- his main diagnostic",
    "actions": "every click, sent or failed",
    "alerts": "what the engine wanted to tell him",
    "announcements": "filings as they land",
    "performance": "did it make money",
    "system_health": "is the feed alive",
    "knowledge": "is the bot's own data fresh and understood",
    "risk_filters": "what is blocked and why",
    "corporate_actions": "the JLHL split fix, visible",
}


@pytest.mark.parametrize("field", sorted(FULL_MUST_READ))
def test_the_diagnostics_screen_reads_it(field):
    text = FULL.read_text(encoding="utf-8", errors="replace")
    assert field in text, (
        f"index.html never reads snapshot['{field}'] -- "
        f"{FULL_MUST_READ[field]}. It is not on /board either, so the "
        f"bot computes it and nobody can see it.")


# ---------------------------------------------------------------
# 3. YOU CAN GET BETWEEN THEM
# ---------------------------------------------------------------

def test_the_board_links_to_the_diagnostics_screen():
    text = BOARD.read_text(encoding="utf-8", errors="replace")
    assert 'id="tofull"' in text, (
        "the board has no link to /full -- he has to remember a URL")
    assert '"/full"' in text


def test_the_diagnostics_screen_links_back():
    text = FULL.read_text(encoding="utf-8", errors="replace")
    assert 'id="otToBoard"' in text, (
        "/full has no way back to the trading screen")


@pytest.mark.parametrize("page,element,target", [
    (BOARD, "tofull", "/full"),
    (FULL, "otToBoard", "/board")])
def test_the_link_carries_the_token(page, element, target):
    """A link that drops the token lands him on a read-only screen,
    where the BUY button and the ON switch simply are not drawn. That
    reads as "the dashboard is broken".

    Checks the MECHANISM, not proximity: board.html sets the href in a
    script at the bottom of the file, so a window measured forwards
    from the anchor tag finds nothing and proves nothing.
    """
    text = page.read_text(encoding="utf-8", errors="replace")
    assert element in text, f"{page.name} has no {element} link"
    # The href must be built from the CURRENT page's token, so a
    # view-only link stays view-only on the far side.
    assert 'URLSearchParams(location.search).get("token")' in text, (
        f"{page.name} does not read the token off its own URL")
    assert target in text, f"{page.name} does not point at {target}"
    built = [line for line in text.splitlines()
             if ".href" in line and target in line]
    assert built, (
        f"{page.name} never assigns an href pointing at {target}")
    assert any("token" in line for line in built), (
        f"{page.name} builds the {target} link without the token -- he "
        f"lands on a screen with no BUY button and no ON switch")


# ---------------------------------------------------------------
# 4. THE RETIRED PAGES STAY RETIRED
# ---------------------------------------------------------------

@pytest.mark.parametrize("gone", ["app.html", "screen.html"])
def test_the_duplicate_pages_are_not_back(gone):
    assert not (STATIC / gone).exists(), (
        f"{gone} is back. Four pages is how a month of work split four "
        f"ways and the banner pointed at the wrong one twice.")


@pytest.mark.parametrize("route", ["/", "/app", "/screen", "/old"])
def test_the_retired_routes_redirect_to_the_board(route):
    from fastapi.testclient import TestClient

    from dashboard.server import build_app

    class _State:
        engine = None

        def get_snapshot(self):
            return {"ready": True}

    client = TestClient(build_app(_State(), None, None, operator_token=None),
                        follow_redirects=False)
    response = client.get(route)
    assert response.status_code in (301, 302, 307, 308), (
        f"{route} still serves a page of its own")
    assert response.headers.get("location", "").startswith("/board")


def test_a_redirect_keeps_the_token():
    from fastapi.testclient import TestClient

    from dashboard.server import build_app

    class _State:
        engine = None

        def get_snapshot(self):
            return {"ready": True}

    client = TestClient(build_app(_State(), None, None, operator_token=None),
                        follow_redirects=False)
    location = client.get("/?token=abc123").headers.get("location", "")
    assert "token=abc123" in location, (
        "the redirect dropped the token -- he lands on a view-only "
        "board with no BUY button and no ON switch")


def test_both_screens_are_still_served():
    from fastapi.testclient import TestClient

    from dashboard.server import build_app

    class _State:
        engine = None

        def get_snapshot(self):
            return {"ready": True}

    client = TestClient(build_app(_State(), None, None, operator_token=None))
    for route in ("/board", "/full"):
        assert client.get(route).status_code == 200, route
