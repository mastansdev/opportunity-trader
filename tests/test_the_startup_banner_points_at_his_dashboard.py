"""
==========================================================
The signpost must name the page he actually uses
==========================================================

    "main.py is running but no dashboard link is printed till now"
                                -- operator, 12 August 2026

The link WAS printed. It said this:

    BOARD  (one table, Pre/Live/Post) :  http://127.0.0.1:8000/board
    OLD    (all panels, fallback)     :  http://127.0.0.1:8000/?token=...

Both labels were wrong by 12 August:

    "/"       serves dashboard/static/app.html -- the React screen he
              uses, 46 snapshot fields, the only one still being built
              on. The banner called it OLD.
    "/board"  serves board.html, 20 snapshot fields, the THINNEST of
              the four pages. The banner called it the main one.

So the startup banner sent him to the least complete screen and told
him his own was obsolete. On a terminal scrolling past a thousand
startup lines, a line labelled OLD is a line you stop looking for --
which is why he reported no link at all.

This is the four-dashboard problem showing up in the one place that
decides which screen he opens.

Author : H&M Opportunity Trader
==========================================================
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN = ROOT / "main.py"


def test_the_dashboard_starts_before_the_feed():
    """---- THE SCREEN WAS HELD HOSTAGE BY THE FEED. 12 Aug 2026. ----

        "main.py is running but no dashboard link is printed till now"

    It was printed -- 5 minutes 12 seconds in, under 5,400 log lines.
    Measured on the 22:36 run:

        22:36:18  startup begins
        22:36:34  feed starts connecting
        22:38:38  "Feed error, retrying: no close frame received"
        22:40:28  "Feed error, retrying: no close frame received"
        22:41:30  DASHBOARD  http://127.0.0.1:8000/board?token=...

    start_feed() ran BEFORE start_dashboard(), so for five minutes the
    dashboard did not merely go unadvertised -- nothing was listening
    on the port at all.

    The dashboard needs none of the feed. Holding the operator's only
    window behind the component most likely to be slow or broken is
    backwards: a feed that cannot connect is exactly when he needs the
    panel that says so.
    """
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    started = src.index("dashboard_server, dashboard_thread = start_dashboard(")
    feed = src.index("feed, feed_thread = start_feed()\n    feed_state")
    assert started < feed, (
        "start_feed() runs before start_dashboard(). The dashboard will "
        "not exist until the feed connects, and the feed retries for "
        "minutes after hours.")


def test_the_port_opens_before_the_first_refresh():
    """---- refresh() BLOCKED IT TOO. 12 August 2026, 22:52. ----

    Hoisting the dashboard above start_feed() was not enough. The FIRST
    dashboard_state.refresh() builds every panel -- shortlist reference
    for 2,382 symbols, liquidity for 2,484, watchlist, sectors -- and
    takes minutes. Called before start_dashboard(), it held the port
    shut for all of them:

        22:52:38  startup begins
        22:53:04  [WATCHLIST] ... then nothing for four minutes
                  port 8000: connection refused

    The server needs no snapshot to start: state.py initialises
    _snapshot to {"ready": False} and every page renders that as
    "loading". A screen saying "loading" beats a refused connection,
    because it tells him the bot is alive.
    """
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    started = src.index("dashboard_server, dashboard_thread = start_dashboard(")
    refreshed = src.index("dashboard_state.refresh()", started)
    assert started < refreshed, (
        "dashboard_state.refresh() runs before start_dashboard(). The "
        "first refresh takes minutes and nothing will be listening on "
        "the port until it finishes.")


def test_the_banner_prints_right_after_the_dashboard_starts():
    """A link printed long after the server is up is a link he has
    stopped waiting for."""
    src = MAIN.read_text(encoding="utf-8", errors="replace")
    started = src.index("dashboard_server, dashboard_thread = start_dashboard(")
    printed = src.index("_print_dashboard_banner()", started)
    between = src[started:printed]
    assert between.count("\n") < 8, (
        "the banner is not printed immediately after the dashboard "
        "starts -- whatever runs in between delays the only line he "
        "is looking for")


def _banner():
    """The lines the banner actually PRINTS -- comments stripped.

    ---- THE TEST READ ITS OWN COMMENTS. 12 August 2026. ----
    First written to slice the raw source, which meant the block
    explaining what the OLD banner used to say -- and quoting it
    verbatim -- failed the test asserting the new one does not say it.
    Exactly the fault fixed in tests/test_morning_runner.py the same
    day, repeated within the hour.

    A test of what a program OUTPUTS must read the output, not the
    prose around it.
    """
    import ast

    src = MAIN.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) \
                and node.name == "_print_dashboard_banner":
            block = ast.get_source_segment(src, node) or ""
            break
    else:                                                   # pragma: no cover
        raise AssertionError(
            "main.py has no _print_dashboard_banner() -- the startup "
            "banner has been removed or renamed")
    # Comments and the docstring quote the OLD banner verbatim, so a
    # substring search over raw source finds text the program no longer
    # prints. Twice today a test of what a program OUTPUTS was written
    # against its prose and failed on its own explanation.
    body = "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("#"))
    tail = ast.parse(body.strip()).body[0]
    if (tail.body and isinstance(tail.body[0], ast.Expr)
            and isinstance(tail.body[0].value, ast.Constant)):
        tail.body = tail.body[1:]          # drop the docstring
    return ast.unparse(tail)


def test_the_banner_prints_the_board_with_a_token():
    """/board is the dashboard he moved to (board.html, 9 August).
    /board draws no BUY control without a token, so a link without one
    is a read-only screen he then has to fix by hand."""
    block = _banner()
    assert "/desk?token=" in block, (
        "the startup banner no longer prints /desk with a token on it. "
        "That is the page he uses -- see the route docstring in "
        "dashboard/server.py, 'THE DESK IS THE DASHBOARD NOW.'")


def test_it_does_not_call_his_dashboard_old():
    """The exact regression. app.html is the current page; a banner
    calling it OLD is why he stopped reading the line."""
    printed = _banner()
    assert "OLD" not in printed.upper(), (
        "the banner labels a dashboard OLD. `/` serves app.html, which "
        "is the newest page and the only one still being built on -- "
        "and a line that says OLD is a line he stops looking for.")


def test_it_does_not_send_him_to_a_page_he_has_left():
    """---- FIELD COUNT IS NOT COMPLETENESS. 12 August 2026. ----

    This test used to assert the OPPOSITE: that /board must not be
    printed first, because board.html reads 20 snapshot fields against
    app.html's 46. That reasoning was wrong twice over.

    board.html is the NEWER page (9 August; app.html is 6 August), and
    it reads fewer fields BY DESIGN --

        "one verdict not six chips"
        "no more top 50/20/10 gainers tables"

    -- so counting fields and calling the smaller number worse measured
    the design and marked it a defect.

    ---- AND THE PAGE HE IS ON CHANGED AGAIN. 2 September 2026 ----

        "this is better than current dashboard"
        "make this my real dashboard with remaining tabs"

    /desk replaced /board as the dashboard. board.html is still served
    and still works -- the rule since 6 August is that a new page goes
    beside the working one, never in place of it -- but it is no longer
    the one he opens, so it is no longer the one printed.

    The banner must name the page he is actually on. That sentence has
    outlived three pages now, which is the point of writing it down.
    """
    printed = _banner()
    lines = [l for l in printed.splitlines()
             if "decision(" in l and "{base}" in l]
    assert lines, "the banner prints no dashboard address at all"
    assert "/desk" in lines[0], (
        "the first address the banner prints is not /desk. The first "
        "one printed is the one he opens.")


def test_one_signpost_not_three():
    """"only one universal screen required for now" -- his words, 4
    August. A signpost with three arms is why a month went by with him
    unable to find his dashboard."""
    printed = _banner()
    addresses = re.findall(r'\{base\}(/[a-z]*)', printed)
    assert len(set(addresses)) == 1, (
        f"the banner advertises {sorted(set(addresses))}. Print one -- "
        f"the others are still served, but a startup banner is a "
        f"signpost, not an index.")


def test_a_failure_to_print_still_says_the_dashboard_is_up():
    """If the token lookup throws, he must not conclude the dashboard
    failed to start -- it is served either way.

    Checks the BEHAVIOUR (a warn that says it is still served), not an
    exact sentence: the message is split across two f-strings, so a
    substring match on the joined wording is a test of line wrapping.
    """
    printed = _banner()
    assert "warn(" in printed, (
        "a failure to print the link is silent -- he will read the "
        "absence as the dashboard having failed to start")
    assert "served" in printed, (
        "the failure message does not tell him the dashboard is still "
        "being served")
