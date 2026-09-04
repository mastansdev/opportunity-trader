"""
==========================================================
Dashboard Server
==========================================================

FastAPI + WebSocket, run on its own background thread inside
the SAME process as the trading engine -- not a separate
process, so there is only ever one thing to shut down cleanly
(see dashboard/__init__.py's module docstring).

The server NEVER touches engine internals directly:
  - Reads only ever come from DashboardState.get_snapshot() --
    a cheap, thread-safe dict read, never rebuilt on demand
    here. The snapshot is rebuilt on a timer by the main loop
    (main.py), independent of how many browsers are watching.
  - Writes (BUY / SELL / EXIT ALL) only ever set a request flag
    on TradeController -- the actual action happens on the
    engine's own tick thread the next time a real tick for that
    symbol arrives, using whatever price that tick brings, same
    as every existing manual action in this bot. The server
    thread never opens or closes a position itself.

Operator-approved 2026-07-23: the dashboard can now be shared
with someone else (a different device, a different network
entirely) as VIEW-ONLY -- see dashboard/access_token.py for the
full reasoning. The short version: GET / only embeds the
operator token into the page when the correct ?token=... was
supplied, and every write endpoint independently re-checks that
token header regardless of what the page shows. Two links exist
in practice -- the operator's own control link (with ?token=...)
and a plain link that's safe to hand to anyone else.

Clean shutdown is the other half of this module's job. uvicorn
has no first-class documented way to be stopped from outside
when run on a background thread -- the verified community
pattern (confirmed against uvicorn 0.51 docs/discussions) is:
disable its own signal handling (only the MAIN thread should
react to Ctrl+C), then flip `should_exit` and JOIN the thread
on the way out. That's exactly what start_dashboard() /
stop_dashboard() below do -- this is the specific fix for the
previous bot's "Ctrl+C didn't work" failure.

Author : H&M Opportunity Trader
==========================================================
"""

import asyncio
import os
import threading
import time
from datetime import date, datetime, time as _time_cls

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, RedirectResponse

from config import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
    PRICE_PUSH_SECONDS,
)
from core.logger import decision, diagnostic, warn
from dashboard.access_token import get_or_create_token

def _json_safe(value):
    """Make any snapshot safe to serialise, at the door.

    JSON refuses the ENTIRE payload over one bad value, not just the
    offending field -- and on the websocket that means every panel
    blank, permanently, with the error visible only in the terminal
    the operator is not looking at. Two ways that has already
    happened here:

        NaN   an empty cell in master_stocks.csv comes back from
              pandas as the float NaN, which is TRUTHY and sails
              past every `or None` guard -- a 500 on the stock card
              for every symbol in the universe.

        set   risk_filters.circuit_flagged_symbols arrived as a set
              and killed every websocket push:
              "TypeError: Object of type set is not JSON
               serializable ... when serializing dict item
               'circuit_flagged_symbols'".

    The first version of this function handled only NaN, and the set
    got through it the same evening. So it now normalises by SHAPE
    rather than by the specific bug of the day: anything set-like
    becomes a sorted list, anything with a clock becomes a string,
    and anything else unknown becomes its own repr rather than an
    exception.

    This bot goes live with real money on 3 August. One stray value
    may cost a single field. It must never cost the operator his
    whole view of the market.
    """
    if isinstance(value, float):
        return value if value == value and value not in (
            float("inf"), float("-inf")) else None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (set, frozenset)):
        # Sorted so the panel does not reshuffle on every refresh.
        try:
            return [_json_safe(v) for v in sorted(value)]
        except TypeError:                                  # mixed types
            return [_json_safe(v) for v in value]
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    # NB: `time` is already the stdlib MODULE in this file, hence the
    # alias -- isinstance against a module raises TypeError.
    if isinstance(value, (datetime, date, _time_cls)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, bool)):
        return value
    # Anything else -- a Decimal, a numpy scalar, an object that only
    # exists because someone forgot to convert it. Show it rather than
    # lose the page over it.
    return str(value)


STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
# TWO SCREENS, 13 August 2026 -- see the redirect block below.
#   index.html  /full   DIAGNOSTICS, every panel
#   board.html  /board  TRADING, one table, one verdict
# app.html and screen.html were deleted the same day: a third and a
# fourth page doing neither job, 2,756 lines between them.
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")
# The new two-tab dashboard, 2026-07-29. A SEPARATE file on purpose:
# index.html works and opens a live session in the morning, and
# rewriting 1,446 lines of it the night before is exactly how that
# stops being true. Both are served; the old one is untouched.

# The exact placeholder line index.html ships with -- build_app()
# replaces it with the real token ONLY when the request proved it
# knows the operator token already (see module docstring).
_TOKEN_PLACEHOLDER = 'window.__OPERATOR_TOKEN__ = "";'


def _bot_trading_now(state):
    """Is the bot placing real orders? One boolean, one source.

    engine.alert_only IS the switch. Not config, not a cache, not a
    copy in the snapshot -- those are what drift, and every bug this
    control has ever had was two copies disagreeing rather than the
    button failing.

    Unknown is reported as unknown. Answering "off" when nothing can
    be read would tell him he is safe at the one moment we cannot say
    so, and he would stand down while the engine kept trading.
    """
    # ---- THE SWITCH MOVED. 31 August 2026. ----
    #
    #     "keep simple ON = REAL TRADES . OFF = PAPER TRADES"
    #
    # It used to be engine.alert_only, which answered "is it trading at
    # all". The bot always trades now, so that flag can no longer be
    # the switch -- it is False in both positions. The one source is
    # execution.live: True means his money, False means paper.
    #
    # The rule this docstring was written under still holds: ONE
    # source, read at call time, and unknown reported as unknown.
    engine = getattr(state, "engine", None)
    execution = getattr(engine, "execution", None)
    switch = getattr(execution, "live", None)
    if switch is None:
        return {"on": None, "known": False,
                "note": "no reading from the engine -- unknown, not off"}

    # ---- THE NOTE SAID "REAL" WHILE THE MODE SAID PAPER. 21 Aug ----
    #
    # He armed the bot at 07:51 in PAPER and the dashboard answered
    # "placing REAL orders". Nothing real was leaving the machine --
    # the note was hardcoded to the SWITCH and never read the MODE.
    #
    # This is the NILKAMAL fault pointing the other way. There, a
    # paper position quietly grew a real order. Here, a paper session
    # is labelled real. Both come from one flag being asked a question
    # it does not know the answer to, and the label is the thing he
    # reads to decide whether to stop everything.
    #
    # Read at CALL time. He edits the mode between sessions and a
    # value captured at import describes the last run, not this one.
    try:
        from config import TRADING_MODE
        mode = str(TRADING_MODE).upper()
    except Exception:                                       # noqa: BLE001
        mode = "UNKNOWN"
    # Can this process place a real order at all? A switch turned ON in
    # a process with no Dhan client would be the 21 August fault again
    # -- a paper session wearing a real label.
    can_go_live = getattr(execution, "_live", None) is not None

    if switch and can_go_live:
        note = "REAL trades -- your clicks reach the exchange"
    elif switch:
        note = (f"ON, but this process cannot place real orders "
                f"({getattr(execution, '_live_refused', None) or mode}) "
                f"-- everything is still on paper")
    else:
        note = "PAPER trades -- it trades fully, nothing reaches the broker"

    return {"on": bool(switch), "known": True,
            "open_positions": len(getattr(engine, "open_positions", {}) or {}),
            "mode": "LIVE" if (switch and can_go_live) else "PAPER",
            "placing_real_orders": bool(switch and can_go_live),
            "note": note,
            "resets_on_restart": True}


def build_app(dashboard_state, trade_controller, master_loader,
              operator_token=None):
    """
    Pure construction, no threads/sockets touched here -- this is
    what tests exercise directly via FastAPI's TestClient, no real
    server needed. operator_token=None disables the view-only gate
    entirely (every request is treated as the operator) -- used by
    existing tests/local-only setups that never call
    start_dashboard() directly.
    """
    app = FastAPI(title="Opportunity Trader Dashboard")

    # READ PER REQUEST, not once at startup. 2026-07-28: a UI fix was
    # deployed, the operator pressed F5 and Ctrl+Shift+R repeatedly, and
    # nothing changed -- the server was still serving the HTML it had
    # loaded into memory at boot. The Cache-Control: no-store added in
    # July only stops the BROWSER caching; it does nothing about the
    # server's own copy. An hour of a live session went into that.
    #
    # This is a local, single-operator dashboard. Re-reading a 60 KB file
    # per page load costs nothing and means a UI change is one refresh
    # away instead of one restart.
    def _load_index_html():
        try:
            with open(INDEX_PATH, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as exc:
            return f"<pre>dashboard/static/index.html unreadable: {exc}</pre>"

    def _token_matches(candidate) -> bool:
        if operator_token is None:
            return True
        return candidate == operator_token

    # ---- ONE SCREEN, ONE LINK. 4 August 2026. ----
    #
    #     "why all these ? only one universal screen required for now.
    #      no screen sharing to anyone."
    #     "keep same dashboard for both main & preview (by this only i
    #      can guide/request as per my requirement changes)"
    #
    # I had "/" on the old 39-panel page and the clean one parked at
    # /screen, so the bot printed three links and he had to know which
    # was which. He uses one page. It is now THE page, at "/", and both
    # main.py and dashboard_preview.py land on it -- so a change he asks
    # for shows up in the preview he checks it in.
    #
    # The old page is NOT deleted. It is at /full, unadvertised, because
    # it still carries panels the clean screen has not absorbed yet
    # (watchlist, some POST tables) and I am not throwing data away to
    # tidy a route.
    @app.get("/full", response_class=HTMLResponse)
    def index(token: str = ""):
        if _token_matches(token):
            html = _load_index_html().replace(
                _TOKEN_PLACEHOLDER,
                f'window.__OPERATOR_TOKEN__ = "{operator_token or ""}";',
            )
        else:
            html = _load_index_html()  # placeholder empty -- view-only
        # No-store, 2026-07-24: the operator restarted the bot with a
        # new dashboard (the "Resume New Entries" button) but the
        # browser kept serving the OLD cached page -- the button, and
        # the corrected banner text, never showed. Telling the browser
        # never to cache this HTML means a restart's UI changes are
        # always picked up on the next plain refresh, no hard-reload
        # needed. (The page pulls all live data over the websocket
        # anyway, so there's nothing to gain from caching the shell.)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    # ---- THE SCREEN. 4 August 2026. ----
    #
    #     "why making all clumsy ? you can make an excellent dashboard
    #      with clean UI"
    #     "THIS WILL BE A PLAIN ONE MAKE SURE TO KEEP THE TABS OF
    #      PRE | LIVE | POST AS INDIVIDUAL SCREENS."
    #
    # index.html carried 39 panels and every layout fix I made to it
    # added a fortieth; his screenshot was a page thousands of pixels
    # tall with the buttons lost near the top. This is the replacement,
    # and as of today it is the default route.
    #
    # /screen stays as an alias so the link he has bookmarked, and the
    # one printed by any terminal already running, still work.
    # ==========================================================
    # FOUR PAGES BECAME TWO SCREENS.  13 August 2026.
    # ==========================================================
    #
    #     "we are not even doing 5 - 10% of their working dashboard.
    #      still we can't create one dashboard since 1 month."
    #
    # Measured: four pages, 10,710 lines, and he used one of them.
    #
    #     board.html    1,061 lines   14 fields   /board   <- his
    #     app.html      1,306 lines   35 fields   /  /app
    #     index.html    6,893 lines   42 fields   /full
    #     screen.html   1,450 lines   28 fields   /screen  /old
    #
    # A month of work split four ways, and the startup banner pointed
    # at the wrong one twice in two days.
    #
    # NOT collapsed into ONE. /board is deliberately thin -- "one
    # verdict not six chips", "no more top 50/20/10 gainers tables"
    # (8 August). Forcing index.html's 42 panels into it would undo the
    # design he asked for. Two screens, two jobs:
    #
    #     /board   TRADING      one table, decide and click
    #     /full    DIAGNOSTICS  everything the bot knows
    #
    # app.html and screen.html were a third and fourth page doing
    # neither, so every route they held now lands on the board. The
    # token is carried through: dropping it turns a working screen into
    # a read-only one, which is how "the switch does nothing" starts.
    # ==========================================================
    # THE DESK IS THE DASHBOARD NOW.  2 September 2026.
    # ==========================================================
    #
    #     "this is better than current dashboard"
    #     "make this my real dashboard with remaining tabs"
    #
    # /desk answers the five questions a trader actually asks, in the
    # order they are asked -- where am I, what is moving, what would I
    # do about it, what am I holding, what have I done -- and keeps the
    # other seven tabs as reference behind it.
    #
    # /board IS STILL THERE, unchanged, and this file still serves it.
    # The rule this project has followed since 6 August stands: a new
    # page goes BESIDE the working one, never in place of it, because a
    # mistake here costs a session. He asked for the desk to be the
    # dashboard, so "/" points at it -- but if anything is wrong at
    # 09:15 the old board is one word away, with the same token.
    @app.get("/desk", response_class=HTMLResponse)
    def desk(token: str = ""):
        path = os.path.join(os.path.dirname(INDEX_PATH), "desk.html")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                html = handle.read()
        except OSError as exc:                             # noqa: BLE001
            return f"<pre>dashboard/static/desk.html unreadable: {exc}</pre>"
        # Same replacement, same placeholder, same rule as /board:
        # without the operator link the string stays empty and the page
        # draws no BUY control at all.
        if _token_matches(token):
            html = html.replace(
                _TOKEN_PLACEHOLDER,
                f'window.__OPERATOR_TOKEN__ = "{operator_token or ""}";')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/screen")
    @app.get("/old")
    @app.get("/")
    @app.get("/app")
    def _to_the_board(token: str = ""):
        where = "/desk" + (f"?token={token}" if token else "")
        return RedirectResponse(where, status_code=307)

    @app.post("/api/refresh_gainers_losers")
    def refresh_gainers_losers():
        """2026-07-24 dashboard revamp -- the manual "Refresh now"
        button. Forces the (server-throttled) Top-50 gainers/losers
        and sector heatmap to rebuild immediately. Read-only data
        refresh, so no operator token required (works on view-only
        links too)."""
        dashboard_state.force_gainers_losers_refresh()
        return {"success": True}

    # ---- HIS OWN WATCHLIST. 4 August 2026. ----
    #
    #   "GIVE ME OPTION TO ADD SOME STOCKS TO WATCHLIST TO TRACK IF I
    #    WANT" / "OPTION TO ADD/REMOVE"
    #
    # Token required, unlike the read-only endpoints: this writes a
    # file, and a view-only visitor must not be able to edit what he
    # is watching. It cannot place an order, so it is nowhere near the
    # trade path -- but it is still his, not everyone's.
    @app.post("/api/watchlist/{action}/{symbol}")
    def watchlist_edit(action: str, symbol: str, request: Request,
                       token: str = ""):
        # ---- IT WAS MISSED BY THE BOTH-SPELLINGS FIX. 16 August 2026 ----
        #
        # _require_operator() below learned on 5 August to accept the
        # X-Operator-Token HEADER *or* ?token=... , because the page
        # sent one and the server read the other, and the mismatch was
        # invisible only because no operator token was set.
        #
        # This route kept the query-only spelling. /board sends the
        # header on BUY, so the day he sets a token to hand somebody a
        # view-only link, every watchlist edit from his own operator
        # link would answer "read-only link" and he would have no idea
        # why. Same latent bug, one route later.
        #
        # It still ANSWERS rather than raising 403: this endpoint
        # cannot place an order, and a refusal he can read on the page
        # beats a status code he cannot.
        supplied = (request.headers.get("X-Operator-Token", "")
                    or token
                    or request.query_params.get("token", ""))
        if not _token_matches(supplied):
            return {"success": False, "error": "read-only link"}
        symbol = (symbol or "").upper().strip()

        # ---- IT WAS RETURNING 500. 4 August 2026. ----
        #
        #   "could not send: SyntaxError: Unexpected token 'I',
        #    "Internal S"... is not valid JSON"
        #
        # I wrote master_loader.known_symbols(). MasterLoader has
        # all_symbols() -- known_symbols() does not exist and never did.
        # The test passed because I ALSO wrote the fake loader it ran
        # against, and gave the fake the method I had invented. The
        # test confirmed my own error.
        #
        # Third time on this project: tools/dhan_token.py, release_all(),
        # InstrumentMaster.rows(). Naming from memory is the habit; a
        # fake built from the same memory is what stops the test
        # catching it.
        #
        # The whole body is wrapped now. This endpoint cannot place an
        # order, so nothing it does is worth a 500 -- an unreadable
        # crash page is strictly worse than a refusal he can read.
        try:
            store = dashboard_state.watchlist_store()

            if action == "add":
                # SAME UNIVERSE RULE AS EVERY OTHER PATH -- only NSE
                # names, or a typo sits on screen forever with no price.
                known = set(master_loader.all_symbols(include_blocked=True))
                if symbol not in known:
                    return {"success": False,
                            "error": f"{symbol} is not on our NSE board"}
                done = bool(store.add(symbol))
                if done:
                    getattr(dashboard_state, "refresh_watchlist_panel",
                            lambda: None)()
                return {"success": done}

            if action == "remove":
                done = bool(store.remove(symbol))
                # THE EDIT MUST REACH THE SCREEN, NOT JUST THE FILE.
                # /api/snapshot serves the payload the live loop built,
                # and build_watchlist() only runs inside a full
                # _build(). Without this the row stays on his screen
                # until the next one -- which is exactly why "i'm
                # unable to delete the stocks added in - Watch tab"
                # was true while every delete worked.
                if done:
                    getattr(dashboard_state, "refresh_watchlist_panel",
                            lambda: None)()
                return {"success": done}
            return {"success": False, "error": "add or remove only"}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[WATCHLIST] {action} {symbol} failed: {exc}")
            return {"success": False, "error": str(exc)}

    @app.get("/api/snapshot")
    def snapshot():
        """Plain REST fallback alongside the WebSocket feed --
        handy for debugging without opening the page, and for
        tests that don't want to exercise a websocket. Read-only,
        no token required -- same as the WebSocket feed.

        ---- IT RETURNED THE PAYLOAD RAW. 5 August 2026. ----
        Mid-session, this 500'd:

            ValueError: Out of range float values are not JSON
            compliant: nan ... when serializing dict item 'sector'

        The WEBSOCKET has always sent _json_safe(...). This endpoint
        never did -- so the same payload that the page renders happily
        killed every REST read. It went unnoticed because the page
        uses /ws and nothing else called this until a tool did.

        _json_safe exists precisely for this: one NaN from an empty
        cell in master_stocks.csv refuses the ENTIRE payload, not the
        offending field.
        """
        payload = dict(dashboard_state.get_snapshot() or {})

        # ---- THE SWITCH MUST NEVER COME FROM THE CACHE. 11 Aug 2026 ----
        #
        #     "now only ON ." / "it is not working at all"
        #
        # This returns the snapshot the LIVE LOOP builds. After the
        # close that loop ends -- _hold_dashboard_for_review keeps the
        # server up so he can read the day -- and the cached snapshot
        # freezes. Measured on his machine at 16:58: `as_of` sat at
        # 16:58:45 for 24 seconds while /api/bot_trading/off returned
        # success:true every time.
        #
        # So the endpoint accepted OFF, the engine WAS disarmed, and
        # the page kept reading on:true out of a frozen cache. He spent
        # an evening pressing a switch that worked, watching a screen
        # that could not change. I rewrote the button four times
        # looking for a bug that was never in the button.
        #
        # bot_trading is read straight off engine.alert_only and costs
        # nothing, so it is recomputed on every request. A control is
        # only as honest as the freshest reading behind it.
        payload["bot_trading"] = _bot_trading_now(dashboard_state)

        # And say plainly how old the REST of the payload is, so a
        # frozen board can never again look like a live one.
        payload["served_at"] = datetime.now().strftime("%H:%M:%S")
        return _json_safe(payload)

    # ---- ONE OPERATOR, ONE PAGE, ONE ADDRESS. 6 August 2026. ----
    #
    # I shipped the React screen on /app and left the old one on "/",
    # so main.py printed two links and he had to choose which to click
    # before he could look at a price. tests/test_access_token.py has
    # forbidden exactly that since the day he complained about it, and
    # it caught me -- three failures, all mine.
    #
    # The React screen IS the dashboard, so it answers on "/". The old
    # page stays reachable at /screen and /old as a fallback if the CDN
    # that serves React is ever unreachable at 09:15.
    @app.get("/board", response_class=HTMLResponse)
    def one_table_board(token: str = ""):
        """ONE table. 9 August 2026.

            "tomorrow we will fix the dashboard with only one table.
             no more top 50/20/10 gainers tables."

        Served at /board, NOT at "/", until he has seen it on a live
        morning. The same rule the React screen followed on 6 August:
        a new page is offered beside the working one, never in place of
        it, because a mistake here costs a session.
        """
        path = os.path.join(os.path.dirname(INDEX_PATH), "board.html")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                html = handle.read()
        except OSError as exc:                             # noqa: BLE001
            return f"<pre>dashboard/static/board.html unreadable: {exc}</pre>"

        # ---- THE BOARD CAN TRADE NOW. 11 August 2026. ----
        #
        #     "where is BUY button & QTY ?"
        #
        # /board was read-only because it was served raw -- the token
        # placeholder was never replaced, so IS_OPERATOR was false and
        # the page drew "view only" on every row. He trades by hand;
        # that made the whole screen useless to him.
        #
        # Same replacement, same placeholder, same rule as "/" and
        # /screen: without the operator link the string stays empty and
        # the page draws no BUY control at all -- refused at the button
        # rather than at the endpoint.
        if _token_matches(token):
            html = html.replace(
                _TOKEN_PLACEHOLDER,
                f'window.__OPERATOR_TOKEN__ = "{operator_token or ""}";')
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.get("/api/mode")
    def trading_mode():
        """PAPER or LIVE, straight from config.

        The page must never assume this. A dashboard showing PAPER
        while the bot is LIVE is the most dangerous label on the
        screen, and defaulting to the reassuring answer is exactly how
        that happens.
        """
        try:
            import config
            return {"mode": str(config.TRADING_MODE).upper(),
                    "armed": bool(getattr(
                        config, "I_UNDERSTAND_THIS_PLACES_REAL_ORDERS", False))}
        except Exception as exc:                           # noqa: BLE001
            return {"mode": "UNKNOWN", "error": str(exc)}

    @app.get("/api/price_check")
    def price_check():
        """Every symbol's price and % exactly as the bot holds it,
        unfiltered and unranked -- the bot's side of the NSE
        comparison (tools/nse_check.py, 2026-07-29).

        Read-only, no token required, same as /api/snapshot. Nothing
        here can place, close or modify anything.
        """
        return dashboard_state.price_check_rows()

    # The search box in the header, 30 July 2026.
    #
    #     "pls add search option on top of the screen"
    #
    # It searches the MASTER FILE, not the snapshot. Searching only what
    # is already on screen would be a filter, not a search -- the whole
    # value of a search box is asking about a stock that is NOT in front
    # of you. All 973 rows, name and sector included, so "cement" or
    # "Bosch" finds something even when the symbol is not remembered.
    #
    # Built once and cached: the master file does not change while the
    # bot is running, and rebuilding it per keystroke would put a
    # dataframe walk on the operator's typing.
    _symbol_index = {"rows": None}

    def _build_symbol_index():
        rows = []
        for symbol in master_loader.all_symbols(include_blocked=True):
            record = master_loader.get_by_symbol(symbol) or {}
            rows.append({
                "symbol": symbol,
                "name": _json_safe(record.get("COMPANY NAME")) or "",
                "sector": _json_safe(record.get("SECTOR")) or "",
                # Whether the bot is allowed to trade it at all. Shown in
                # the result so a search never implies tradeability it
                # does not have.
                "tradeable": symbol not in master_loader.blocked_symbols(),
            })
        rows.sort(key=lambda r: r["symbol"])
        return rows

    @app.get("/api/symbols")
    def symbols():
        """Every symbol the bot knows, for the header search box.

        Read-only, no token. Returns identity only -- no prices, no
        positions, nothing that could place or close anything.
        """
        if _symbol_index["rows"] is None:
            try:
                _symbol_index["rows"] = _build_symbol_index()
            except Exception as exc:                       # noqa: BLE001
                # A failure here must cost the search box, not the page.
                return {"count": 0, "symbols": [], "error": str(exc)}
        return {"count": len(_symbol_index["rows"]),
                "symbols": _symbol_index["rows"]}

    @app.get("/api/chip_stats")
    def chip_stats():
        """What each chip has been WORTH, measured, not typed in.

        The numbers in the chip tooltips were measured by hand on
        1 August and hardcoded. This serves the live ones so a chip
        cannot keep a reputation it stopped earning.

        Read-only, no token. First call returns {} and starts the
        measurement off-thread -- the panel keeps its fallbacks until
        the real numbers arrive. It can never block or break the page.
        """
        # dashboard/chip_stats.py, NOT dashboard/state.py --
        # tests/test_outcomes.py forbids the trading path from importing
        # the measurement, and it is right to.
        try:
            from dashboard import chip_stats as _cs
            return {"stats": _cs.current(), "ready": _cs.ready()}
        except Exception as exc:                           # noqa: BLE001
            return {"stats": {}, "ready": False, "error": str(exc)}

    @app.get("/api/knowledge")
    def knowledge():
        """What the bot knows, and whether it is allowed to use it.

            "bot is getting results, news. but i'm not sure whether bot
             knows it. stores it and reuses when ever the same situation
             arises."                     -- operator, 12 August 2026

        Eleven stores, ~200,000 rows, and until now the only way to
        answer that was to open a database. Each row here says how much
        is in the store, how fresh it is, and -- the column that matters
        -- whether it DECIDES (can stop a trade), SHOWS (screen only) or
        RECORDS (measured, consulted by nothing).

        Read-only and computes nothing; see core/knowledge.py. Served
        from the snapshot so it costs this endpoint no work at all.
        """
        try:
            snap = dashboard_state.get_snapshot() or {}
            got = snap.get("knowledge")
            if got:
                return got
            # Snapshot not built yet (first seconds after start).
            from core import knowledge as _k
            return _k.census()
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "stores": [],
                    "verdict": f"could not be read ({exc})"}

    @app.get("/api/why")
    def why_refused_today():
        """What the bot turned down today, and how often.

            "why it is not being used to predict the stock movement"
                                    -- operator, 16 August 2026

        THE STORE CANNOT NAME THE STOCK. data/decisions.db's refusals
        table is (date, at, reason, n) -- counts per reason, with no
        symbol column, 112,272 rows summing to millions of refusals.
        So "why was TVSMOTOR skipped" is not answerable from history
        and this endpoint does not pretend it is; /api/why/{symbol}
        below re-runs the gates LIVE instead.
        """
        try:
            import sqlite3
            from datetime import datetime
            con = sqlite3.connect("file:data/decisions.db?mode=ro", uri=True)
            today = datetime.now().strftime("%Y-%m-%d")
            rows = [{"reason": r[0], "n": r[1]} for r in con.execute(
                "SELECT reason, SUM(n) FROM refusals WHERE date = ? "
                "GROUP BY reason ORDER BY SUM(n) DESC", (today,))]
            if not rows:                      # before the first refresh
                rows = [{"reason": r[0], "n": r[1]} for r in con.execute(
                    "SELECT reason, SUM(n) FROM refusals GROUP BY reason "
                    "ORDER BY SUM(n) DESC LIMIT 15")]
                scope = "all time -- nothing refused yet today"
            else:
                scope = today
            picks = [dict(zip([c[0] for c in con.description], r))
                     for r in con.execute(
                         "SELECT symbol, rank, score, price, change_pct, "
                         "mechanism FROM picks WHERE date = ? "
                         "ORDER BY rank LIMIT 20", (today,))]
            con.close()
            return {"scope": scope, "reasons": rows, "picks": picks,
                    "note": "counts only -- the refusal store carries no "
                            "symbol. Ask /api/why/{symbol} for one stock."}
        except Exception as exc:                           # noqa: BLE001
            return {"scope": None, "reasons": [], "picks": [],
                    "error": str(exc)}

    @app.get("/api/why/{symbol}")
    def why_this_symbol(symbol: str):
        """Would this stock be refused RIGHT NOW, and by which gate.

        Re-runs the real gates rather than reading history, because
        history does not record the symbol. Every line is the same
        check core/auto_entry.py's refuse_reason() applies.
        """
        sym = str(symbol or "").upper().strip()
        out = {"symbol": sym, "checks": [], "verdict": None}
        try:
            known = set(master_loader.all_symbols())
            blocked = master_loader.blocked_symbols()
            in_universe = sym in known
            out["checks"].append({
                "gate": "in the tradeable universe", "ok": in_universe,
                "detail": ("subscribed" if in_universe
                           else blocked.get(sym, "not in master_stocks.csv"))})

            snap = dashboard_state.get_snapshot() or {}
            ranked = (snap.get("ranked") or {})
            row = next((r for r in (ranked.get("rows") or [])
                        if str(r.get("symbol", "")).upper() == sym), None)
            refused = next((r for r in (ranked.get("refused_rows") or [])
                            if str(r.get("symbol", "")).upper() == sym), None)

            if row:
                out["checks"].append({"gate": "cleared the ranker",
                                      "ok": True,
                                      "detail": row.get("mechanism") or ""})
                out["verdict"] = "on the board now"
            elif refused:
                why = (refused.get("blocked_reason")
                       or (refused.get("blocking") or [None])[0]
                       or "refused, reason not recorded on the row")
                out["checks"].append({"gate": "cleared the ranker",
                                      "ok": False, "detail": why})
                out["verdict"] = why
            else:
                out["checks"].append({
                    "gate": "reached the ranker at all", "ok": False,
                    "detail": "not in today's ranked or refused list -- it "
                              "did not move enough to be looked at, or no "
                              "tick has arrived"})
                out["verdict"] = ("never reached the ranker today")

            # THE ONE THAT EXPLAINS THE MULTI-DAY RALLIES.
            # core/why_moving.py:238 drops any event not dated today:
            # "Yesterday's result is not why a stock is moving today."
            # So a catalyst is a reason for exactly ONE session, and a
            # stock still climbing on day four has no reason at all.
            try:
                import sqlite3
                from datetime import datetime
                con = sqlite3.connect("file:data/stock_events.db?mode=ro",
                                      uri=True)
                today = datetime.now().strftime("%Y-%m-%d")
                latest = con.execute(
                    "SELECT at, kind, ai_direction, ai_reason FROM events "
                    "WHERE upper(symbol) = ? AND ai_reason IS NOT NULL "
                    "ORDER BY at DESC LIMIT 1", (sym,)).fetchone()
                con.close()
                if latest:
                    fresh = str(latest[0]).startswith(today)
                    out["checks"].append({
                        "gate": "has a reason DATED TODAY", "ok": fresh,
                        "detail": (f"{str(latest[0])[:10]} · "
                                   f"{latest[2] or '?'} · {latest[3] or ''}"
                                   + ("" if fresh else
                                      "  <-- older than today, so the live "
                                      "path cannot see it"))})
                else:
                    out["checks"].append({
                        "gate": "has a reason DATED TODAY", "ok": False,
                        "detail": "no reasoned event stored at all"})
            except Exception:                              # noqa: BLE001
                pass
            return out
        except Exception as exc:                           # noqa: BLE001
            out["error"] = str(exc)
            return out

    @app.get("/api/links/{symbol}")
    def stock_links(symbol: str):
        """Every group this stock belongs to, and who else is in it.

            "which company is linked what sector, theme, which raw
             material provider, end user of the products every thing
             in as same as bloomberg"      -- operator, 16 Aug 2026

        Bloomberg calls this SPLC and builds it from DISCLOSED supplier
        and customer relationships. That dataset is not here and cannot
        be derived from what is -- see core/sector_map.py, which says
        so rather than guessing.

        What this answers exactly: which companies share a sector, an
        industry, a theme, a raw material or an economic sensitivity.
        "Crude spikes -- who does that reach" is a real answer; "who
        supplies Tata Steel" is not, and the payload does not pretend
        otherwise.
        """
        try:
            from core import sector_map
            return sector_map.links_of(symbol)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[LINKS] {symbol} failed: {exc}")
            return {"symbol": symbol, "found": False, "groups": [],
                    "error": str(exc)}

    @app.get("/api/tag/{tag}")
    def tag_members(tag: str):
        """Who carries this tag -- the reverse of /api/links.

        Type STEEL and get the 241 names it reaches. `like` carries the
        near-misses so he never has to know the master's own spelling
        before he can ask: "crude" finds "CRUDE OIL".
        """
        try:
            from core import sector_map
            # ---- A TAG WITHOUT A DIRECTION IS A COIN FLIP. 18 Aug ----
            #
            #     "bot needs to know which companies are positive &
            #      negative . as of now there is no distinction"
            #
            # 71 symbols carry COPPER and exactly ONE of them is
            # helped when copper rises. `exact` alone handed him all
            # 71, liquid names first, which are the wrong 70.
            return {"tag": str(tag or "").upper(),
                    "exact": sector_map.carrying(tag),
                    "sides": sector_map.sides(tag),
                    "like": sector_map.like(tag)}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[TAG] {tag} failed: {exc}")
            return {"tag": tag, "exact": [], "like": [], "error": str(exc)}

    @app.get("/api/history/{symbol}")
    def event_history(symbol: str):
        """Every company event for one stock and what it led to.

        ---- HE WAS KEEPING THIS BY HAND. 19 August 2026. ----

            "still user doing manual updates/data maintainance which
             is not ideal to do so bot must maintain the complete
             record"

        All three stores were already on disk -- 15,130 events, 7,086
        results dates, 1.1M daily bars -- and nothing joined them.
        """
        try:
            from core import stock_memory
            return {"symbol": str(symbol or "").upper(),
                    "summary": stock_memory.track_record(symbol),
                    "events": stock_memory.event_record(symbol)}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[HISTORY] {symbol} failed: {exc}")
            return {"symbol": symbol, "events": [], "error": str(exc)}

    @app.get("/api/score")
    def signal_score():
        """What actually happened after every signal the bot recorded.

        ---- THE MEASUREMENT THAT WAS NEVER TAKEN. 18 Aug 2026. ----

        13,333 signals carrying `taken` and `refused_why`, 51 of them
        taken, and no column for what the price did next. This reads
        it back. Slow on purpose -- it walks 19M minute candles -- so
        it is a page he opens, never something the snapshot waits on.
        """
        try:
            from core import signal_journal
            return signal_journal.report()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SCORE] failed: {exc}")
            return {"available": False, "why": str(exc)}

    @app.get("/api/flow/{symbol}")
    def flow_for(symbol: str):
        """Today's buying and selling for one stock, minute by minute.

        ---- NOT ON THE SNAPSHOT. 30 August 2026. ----

        A session is up to 375 minutes. Carrying that for every row on
        the board would put tens of thousands of points through the
        websocket once a second to draw a chart nobody is looking at.
        This is fetched when he opens the card, and only then.

            series    [{"minute","cum","ltp"}] -- oldest first, with
                      the running total built on read
            now       the live reading, which is fresher than the
                      store: order_flow flushes every 30 seconds
            diverged  set when price kept making highs after the
                      buying stopped -- see core/order_flow.py

        Read-only, no token: it says nothing a price screen does not.
        """
        try:
            from core import order_flow

            name = str(symbol or "").upper()
            series = order_flow.session_series(name)
            return _json_safe({
                "symbol": name,
                "series": [{"minute": r["minute"], "cum": r["cum"],
                            "ltp": r["ltp"]} for r in series],
                "now": order_flow.pressure(name),
                "diverged": order_flow.divergence(name, series=series),
            })
        except Exception as exc:                           # noqa: BLE001
            warn(f"[FLOW] {symbol}: {exc}")
            return {"symbol": symbol, "series": [], "now": None,
                    "diverged": None, "why": str(exc)}

    @app.get("/api/stock/{symbol}")
    def stock_card(symbol: str):  # noqa: D401  (see _json_safe above)
        """Everything the bot knows about one stock.

        The operator's rule, 29 July 2026: "dashboard must contain all
        info from bot. recall the memory of any stock on demand".

        Read-only, no token. Nothing here can place or close anything.
        """
        return _json_safe(dashboard_state.card_for(symbol))

    def _require_operator(request: Request):
        # ---- THE PAGE AND THE SERVER DISAGREED. 5 August 2026. ----
        #
        #   "have you checked that toggle ? is it working both today
        #    created & the one u mentiond? broker-stop toggle."
        #
        # This read the X-Operator-Token HEADER and nothing else.
        # dashboard/static/screen.html has always sent the token as a
        # QUERY PARAMETER -- ?token=... -- on every button it has: BUY,
        # SELL, SHORT, EXIT ALL, the watchlist, and the two switches.
        #
        # It has never been caught because main.py passes no
        # operator_token at all, so _token_matches() returns True for
        # everything and the gate is off. The day a token is set -- the
        # first time he wants a view-only link for anyone -- every
        # button on the page returns 403 and the page reports "refused"
        # with no idea why.
        #
        # A security gate that is only correct while it is switched off
        # is not a gate. Both spellings are accepted now, and the query
        # parameter is the one the page actually sends.
        supplied = (request.headers.get("X-Operator-Token", "")
                    or request.query_params.get("token", ""))
        if not _token_matches(supplied):
            warn("[DASHBOARD] Action REFUSED -- view-only link used. "
                 "The click did nothing. Open the operator link.")
            trade_controller.note_action(
                False, "action refused -- view-only link, nothing was sent")
            raise HTTPException(
                status_code=403,
                detail="View-only link -- this action needs the operator link.",
            )

    @app.post("/api/buy/{symbol}")
    def buy(symbol: str, request: Request, qty: str = None):
        # EVERY attempt is logged, success AND failure (2026-07-28).
        # Before this, three paths returned without a single line: a 403,
        # an unknown symbol, and a request that never arrived. On that
        # day two BUY clicks vanished with no trace anywhere -- the
        # operator searched the terminal for SUPREMEIND and found
        # nothing, because nothing had been written. A silent failure
        # and a silent success looked identical.
        _require_operator(request)
        symbol = symbol.upper()
        if master_loader.get_by_symbol(symbol) is None:
            warn(f"[DASHBOARD] BUY REFUSED: {symbol} -- unknown symbol, "
                 f"not in the master database. Nothing was requested.")
            trade_controller.note_action(
                False, f"BUY {symbol} -- unknown symbol, nothing sent")
            return {"success": False, "error": f"Unknown symbol: {symbol}"}

        # ---- A BLOCKED STOCK HAS NO FEED. 2 August 2026. ----
        #
        #     "done, i agree with you. i can trade manually from
        #      dashboard."
        #
        # He said that about the 235 names the turnover bar keeps out,
        # and it was not true. main.py subscribes to SUBSCRIBE=YES rows
        # ONLY, and core/engine.py checks is_buy_requested() INSIDE the
        # per-symbol tick handler. A stock with no feed produces no
        # ticks, so the request would have sat in the queue forever:
        #
        #     screen says   "BUY requested: SKFINDIA"   success
        #     what happens   nothing, ever, with no error anywhere
        #
        # That is the exact failure this endpoint was rewritten on
        # 28 July to stop -- "a silent failure and a silent success
        # looked identical" -- and it had come back through a door
        # nobody had opened yet.
        #
        # Refused HERE and loudly, with the real reason off the master,
        # so he finds out in the same second rather than waiting on a
        # fill that cannot come. If he wants the stock tradeable, the
        # answer is the SUBSCRIBE column, not this button.
        blocked = master_loader.blocked_symbols()
        if symbol in blocked:
            why = blocked[symbol] or "marked NO in the master"
            warn(f"[DASHBOARD] BUY REFUSED: {symbol} is not subscribed "
                 f"today ({why}). It has NO live price feed, so nothing "
                 f"could be sent. Nothing was queued.")
            trade_controller.note_action(
                False, f"BUY {symbol} -- not subscribed today, no price feed")
            return {"success": False,
                    "error": (f"{symbol} is not on today's feed -- {why}. "
                              f"No price, so no order can be placed.")}

        want, bad = _wanted_qty(qty)
        if bad:
            warn(f"[DASHBOARD] BUY REFUSED: {symbol} -- {bad}. Nothing "
                 f"was requested.")
            trade_controller.note_action(False, f"BUY {symbol} -- {bad}")
            return {"success": False, "error": bad}

        # ---- ONE ORDER PER SYMBOL AT A TIME. 3 August 2026. ----
        #
        #     "1st click no response & no way to check in dashboard,
        #      then i clicked the second one. now both orders gave me
        #      loss of huge amount"
        #
        # 09:17:23  BUY YASHO 24 sent
        # 09:17:34  not confirmed after 10s -- CHECK YOUR DHAN APP
        # 09:18:12  clicked again
        # 09:18:14  BUY YASHO 23 filled at 4173, Rs 59 higher
        #
        # Then the first one filled too. He was long twice, at a worse
        # average, and the bot's book held neither.
        #
        # The panel now SHOWS an in-flight order. Showing is not enough:
        # he clicked at 09:18 because ten seconds of silence looks
        # exactly like a click that did nothing. So the second click is
        # REFUSED while the first is unresolved, and the refusal says
        # what is outstanding rather than just "no".
        #
        # It clears itself -- resolve_in_flight() drops the record the
        # moment Dhan says filled or dead, so a genuine second entry is
        # never blocked for longer than the truth takes to arrive.
        flight = None
        try:
            executor = getattr(engine, "execution", None)
            executor = getattr(executor, "executor", executor)
            checker = getattr(executor, "in_flight", None)
            flight = checker(symbol) if checker else None
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[DASHBOARD] in-flight check failed for {symbol} "
                       f"({exc}). Not blocking on it.")
        if flight:
            note = (f"{symbol} already has a {flight.get('side', 'BUY')} "
                    f"order at the exchange (id {flight.get('order_id')}, "
                    f"sent {flight.get('at')}) that has NOT come back yet. "
                    f"Check the ORDERS panel or your Dhan app -- sending "
                    f"another would buy it twice.")
            warn(f"[DASHBOARD] BUY REFUSED: {note}")
            trade_controller.note_action(
                False, f"BUY {symbol} -- an order is already in flight")
            return {"success": False, "error": note}

        trade_controller.request_buy(symbol, qty=want)
        how = f"{want} share(s)" if want else "the standard size"
        decision(f"[DASHBOARD] Manual BUY requested: {symbol} ({how})")
        trade_controller.note_action(True, f"BUY {symbol} -- {how}")
        return {"success": True, "qty": want}

    # ---- HOW MANY, NOT JUST WHICH. 2 August 2026. ----
    #
    # `qty` is optional everywhere. Left out, every one of these
    # behaves exactly as it did before today: a BUY is the standard
    # Rs 1 lakh size, a SELL is the whole position.
    #
    # A quantity that cannot be read as a positive whole number is
    # REFUSED rather than falling back to the default. On a sell, a
    # silent fallback would close the entire position when he meant to
    # trim half of it -- the failure would look like a fat finger of
    # his rather than a parse of ours.
    def _wanted_qty(raw):
        if raw is None or str(raw).strip() == "":
            return None, None
        try:
            qty = int(str(raw).strip())
        except (TypeError, ValueError):
            return None, f"qty {raw!r} is not a whole number"
        if qty <= 0:
            return None, f"qty {qty} must be positive"
        return qty, None

    @app.post("/api/sell/{symbol}")
    def sell(symbol: str, request: Request, qty: str = None):
        """Close a position, or PART of one.

            "ride untill the momentum stays - exit once it gone
             ruthlessly"

        Without qty this closes everything, exactly as before. With a
        qty smaller than the position it trims and lets the rest run --
        which is what riding a move usually means in practice, and the
        dashboard could not do it until today.
        """
        _require_operator(request)
        symbol = symbol.upper()
        want, bad = _wanted_qty(qty)
        if bad:
            warn(f"[DASHBOARD] SELL REFUSED: {symbol} -- {bad}. Nothing "
                 f"was requested.")
            trade_controller.note_action(False, f"SELL {symbol} -- {bad}")
            return {"success": False, "error": bad}
        trade_controller.request_exit(symbol, qty=want)
        how = f"{want} share(s)" if want else "the whole position"
        decision(f"[DASHBOARD] Manual SELL requested: {symbol} ({how})")
        trade_controller.note_action(True, f"SELL {symbol} -- {how}")
        return {"success": True, "qty": want}

    @app.post("/api/short/{symbol}")
    def short(symbol: str, request: Request, qty: str = None):
        """Per-row SHORT button on the Top 50 Losers table -- opens
        a NEW short position (mirrors buy() above, direction
        flipped), unlike sell() which only ever EXITS an existing
        one. See trading/trade_controller.py's docstring."""
        _require_operator(request)
        symbol = symbol.upper()
        if master_loader.get_by_symbol(symbol) is None:
            return {"success": False, "error": f"Unknown symbol: {symbol}"}
        want, bad = _wanted_qty(qty)
        if bad:
            trade_controller.note_action(False, f"SHORT {symbol} -- {bad}")
            return {"success": False, "error": bad}
        trade_controller.request_short(symbol, qty=want)
        decision(f"[DASHBOARD] Manual SHORT requested: {symbol}"
                 + (f" ({want} shares)" if want else ""))
        trade_controller.note_action(True, f"SHORT requested: {symbol}")
        return {"success": True, "qty": want}

    @app.post("/api/exit_all")
    def exit_all(request: Request, pause: bool = False):
        """
        2026-07-24: the dashboard's EXIT ALL button is a popup with
        two choices. ?pause=true is "Stop New Entries + Exit All" --
        automated entries are gated off and STAY off until the
        operator explicitly clicks "Resume New Entries" (the
        /api/resume_entries endpoint below). 2026-07-24 evening: the
        old auto-resume-when-flat was removed -- it re-opened 10
        positions the instant Exit All finished, defeating the whole
        button. Bare POST (pause defaults False) is "Exit All only" --
        the bot keeps trading normally throughout.
        """
        _require_operator(request)
        if pause:
            trade_controller.request_pause_new_entries()
        trade_controller.request_exit_all()
        decision(
            "[DASHBOARD] EXIT ALL requested from dashboard"
            + (" (new entries PAUSED until manually resumed)." if pause else ".")
        )
        return {"success": True}

    @app.post("/api/resume_entries")
    def resume_entries(request: Request):
        """Turn automated entries back on after a "Stop New Entries +
        Exit All". Paired with the paused-banner "Resume" button."""
        _require_operator(request)
        trade_controller.resume_new_entries()
        decision("[DASHBOARD] New entries RESUMED from dashboard.")
        return {"success": True}

    # ---- THE BROKER-SIDE STOP, SWITCHED WITHOUT A RESTART ----
    #
    #     "we can do this at live market too?"
    #     "without stopping main.py?"
    #                                -- operator, 2 August 2026
    #
    # It could not, and that was a real flaw: BROKER_STOP_ENABLED was
    # read once when the engine was built. The only way to switch it on
    # was to restart -- and a mid-session restart is precisely what you
    # do NOT want to be doing at the moment you have decided you want
    # more protection.
    #
    # Switching ON also protects what is ALREADY open. Turning it on
    # with running positions and doing nothing about them would be the
    # worst of both: he believes he is covered, and the trades opened
    # before the click are not.
    @app.post("/api/broker_stop/{state}")
    def broker_stop(state: str, request: Request):
        _require_operator(request)
        engine = getattr(dashboard_state, "engine", None)
        stop = getattr(engine, "broker_stop", None) if engine else None
        if stop is None:
            return {"success": False,
                    "error": "broker stop is not wired in this session"}
        want_on = str(state).lower() in ("on", "true", "1", "enable")
        try:
            if want_on:
                from config import HARD_STOP_FROM_ENTRY_PCT
                from trading.broker_stop import hard_stop_price
                out = stop.enable(
                    open_positions=getattr(engine, "open_positions", None),
                    hard_stop_for=lambda _s, pos: hard_stop_price(
                        pos.get("entry_price"), pos.get("direction", "LONG"),
                        HARD_STOP_FROM_ENTRY_PCT))
            else:
                # Cancels every resting order on the way out. Leaving
                # them would strand orders that nothing is left to
                # cancel at the exit -- and a stop resting against a
                # position that has closed SELLS STOCK NOT HELD.
                out = stop.disable(cancel_resting=True)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[DASHBOARD] Broker stop switch failed: {exc}")
            return {"success": False, "error": str(exc)}
        decision(f"[DASHBOARD] Broker-side stop switched "
                 f"{'ON' if want_on else 'OFF'} from the dashboard.")
        trade_controller.note_action(
            True, f"Broker stop {'ON' if want_on else 'OFF'}")
        return {"success": True, **out}

    @app.post("/api/bot_trading/{state}")
    def bot_trading(state: str, request: Request):
        """THE SWITCH. 5 August 2026.

            "you give me a control button in dashboard not in code
             files. control = bot trading on / off"
            "it must follow me . not i needs to go back on bot."

        ALERT_ONLY_MODE lived in config.py line 1406. Arming the bot
        meant editing a source file and restarting -- which is not a
        control, it is a deployment, and it cannot be undone in the
        two seconds that matter when something is going wrong.

        This flips engine.alert_only AT RUNTIME. OFF takes effect on
        the very next tick, with no restart and nothing to remember.

        It is deliberately NOT written back to config.py. A restart
        returns to ALERT_ONLY_MODE, which is the safe value: if the
        bot dies at 11:00 and comes back while he is away from the
        desk, it must come back watching, not trading.

        Turning it OFF never touches an open position. Stops, trails
        and targets keep running on everything already in the book --
        this governs NEW entries only. Abandoning live positions
        because he stopped new buying would be the opposite of
        control.
        """
        _require_operator(request)
        engine = getattr(dashboard_state, "engine", None)
        if engine is None:
            return {"success": False, "error": "no engine in this session"}
        want_trading = str(state).lower() in ("on", "true", "1", "enable")

        # ---- IT MUST NOT ARM ON INPUTS THAT HAVE NOT ARRIVED ----
        #      6 August 2026.
        #
        # The pre-open gapper card posted at 09:08 and reached the
        # store at 09:45 -- thirty minutes after the open. Row 1 of
        # his watchlist was empty for the whole first half hour, and
        # an empty Row 1 looks exactly like a morning with no good
        # results. Nothing on the screen said which it was.
        #
        # So arming is refused while a morning input is missing, and
        # the refusal SAYS WHAT IS MISSING. He can still override --
        # ?force=1 -- because it is his money and his judgement, but
        # he cannot do it by accident.
        if want_trading:
            try:
                from core import morning_ready
                readiness = morning_ready.check()
            except Exception:                              # noqa: BLE001
                readiness = None
            forced = str(request.query_params.get("force") or "").lower() \
                in ("1", "true", "yes")
            if readiness and not readiness["ready"] and not forced:
                return {"success": False,
                        "error": ("not ready to trade: "
                                  + "; ".join(readiness["why_not"])),
                        "not_ready": readiness["blocking"],
                        "checks": readiness["checks"],
                        "override": ("add &force=1 to arm anyway -- "
                                     "the bot will trade on incomplete "
                                     "inputs")}
        try:
            # ==========================================================
            # ON = REAL, OFF = PAPER.  31 August 2026.
            # ==========================================================
            #
            #     "keep simple ON = REAL TRADES . OFF = PAPER TRADES .
            #      all same entry, exits, capital allotted & everything
            #      same"                          -- the operator
            #
            # It used to mean TRADE / DO NOT TRADE, and OFF meant the
            # bot placed nothing at all -- not even a simulated fill.
            # That is the third state that produced 65 alerts and 0
            # trades on 31 August, and ten days with no record of
            # whether any signal was right.
            #
            # The bot now ALWAYS trades. alert_only stays off in both
            # positions; the switch chooses whose money, and nothing
            # else changes -- same entries, same exits, same sizing,
            # same capital.
            execution = getattr(engine, "execution", None)
            if execution is None:
                return {"success": False,
                        "error": "no execution path in this session"}
            # ---- ASK THE GATE. IT WAS WRITTEN TO BE ASKED. ----
            #                       4 September 2026, 23:00.
            #
            #     "fix the gate now"                -- the operator
            #
            # core/trading_gate.py was written this morning to answer
            # "may a REAL order be placed?" in ONE place, and the dead-
            # code audit he asked for that evening found that nothing
            # in the bot called it. The comment directly below this one
            # -- written the same morning -- already describes arming
            # ON in a PAPER process placing REAL orders. The purse was
            # fixed that day. The routing was not.
            #
            # Two checks, because they answer different questions:
            #
            #   refuse_to_arm_reason()  -> the switch must not go ON at
            #       all: LIVE, but the broker has not answered. Refused
            #       here so it reaches him as a sentence rather than as
            #       orders that quietly go nowhere.
            #
            #   trading/execution._live_executor() -> the outer bound.
            #       A PAPER process never places a real order however
            #       this flag is set. That one is enforced at the point
            #       every order routes through, so it cannot be bypassed
            #       by some future caller setting .live another way.
            from core.trading_gate import apply_switch
            armed, why = apply_switch(engine, want_trading)
            if not armed:
                return {"success": False, "error": why, "trading": False}
            # ---- THIS SWITCH ARMS THE RANKER. NOT THE BREAKOUT. ----
            # 6 August 2026. He turned this ON having been told the
            # ranker's rules and got eight breakout fills instead,
            # because both paths read alert_only. The breakout has its
            # own switch now, and this one always leaves it off.
            engine.breakout_armed = False

            # ---- THE PURSE FOLLOWS THE SWITCH. 4 September 2026. ----
            #
            #     "new dashboard is showing 5 L as available capital in
            #      both REAL / PAPER MODES which is not correct.
            #      PAPER = 5 Lakh, REAL = Dhan funds reflects"
            #
            # He found this before it cost anything. On 4 September the
            # paper purse became a fixed Rs 5 lakh so a session could
            # run with Dhan unreachable -- but the purse was chosen by
            # config.TRADING_MODE, read ONCE at startup, while THIS
            # switch is what trading/execution._route() actually reads.
            # So arming ON in a PAPER process placed REAL orders sized
            # against Rs 5 lakh of money that does not exist: ten seats
            # at Rs 50,000, Rs 2,00,000 a position.
            #
            # Two states, one switch, and the money moves with it:
            #
            #     ON  -> real orders, and the REAL Dhan balance
            #     OFF -> paper orders, and the fixed paper purse
            #
            # ARMING IS REFUSED IF DHAN DOES NOT ANSWER. His static IP
            # was not renewed that morning; ON would have sent orders to
            # a broker this process cannot reach. Sizing on a stale
            # figure is the specific failure being prevented.
            portfolio = getattr(dashboard_state, "portfolio", None)
            if portfolio is not None:
                from core import broker_funds
                if want_trading:
                    balance = broker_funds.refresh(
                        getattr(engine, "dhan_client", None))
                    if balance is None:
                        # TWO STATES. A refusal drops to PAPER, never to
                        # silence -- alert_only is the third state he
                        # abolished on 31 August after 65 alerts and 0
                        # trades, and tests/test_the_guard_stops_a_dead_
                        # feed.py fails the build for setting it True.
                        # The first version of this line did exactly
                        # that and would have left the bot placing
                        # nothing at all for the session.
                        execution.live = False
                        # SAY IT. A switch that does nothing and says
                        # nothing is indistinguishable from a broken
                        # page -- which is exactly how it looked when
                        # this refused on a client it never had.
                        warn("[GATE] Refusing to arm ON: Dhan did not "
                             "answer, so the real balance is unknown. "
                             "The switch stays OFF and the session "
                             "stays on paper.")
                        return {"success": False,
                                "error": ("Dhan did not answer, so the real "
                                          "balance is unknown. Refusing to "
                                          "arm -- a real order sized on a "
                                          "guess is the one thing this "
                                          "switch must never do."),
                                "still": "OFF -- paper"}
                    portfolio.starting_capital = float(balance)
                    portfolio.available_capital = float(balance)
                else:
                    from config import PAPER_STARTING_CAPITAL
                    portfolio.starting_capital = float(PAPER_STARTING_CAPITAL)
                    portfolio.available_capital = float(PAPER_STARTING_CAPITAL)
        except Exception as exc:                           # noqa: BLE001
            return {"success": False, "error": str(exc)}

        held = len(getattr(engine, "open_positions", {}) or {})
        if want_trading:
            # ---- IT SAID "REAL" IN PAPER, AND HE STOOD DOWN. ----
            #      24 August 2026.
            #
            #     "I CLICKED OFF ON DASHBOARD AS IT SHOWED REAL TRADING"
            #                                          -- operator
            #
            # This banner was hard-coded. Armed in PAPER at 14:45 it
            # announced "Orders placed from here are REAL", so he
            # disarmed the bot -- correctly, on what he was shown.
            # The snapshot beside it said placing_real_orders: False.
            #
            # The mode is read at CALL time, the same rule
            # _bot_trading_now() already follows: a value captured at
            # import once told him the opposite lie, that a LIVE
            # session was PAPER.
            # ---- SAY WHAT THE ROUTER WILL DO. 3 September 2026. ----
            #
            #     "the switch ON- REAL & OFF-PAPER both needed to
            #      reverify again ... but our work is not this i
            #      believe"                        -- the operator
            #
            # He is right, and it was worse than a wrong label. This
            # read config.TRADING_MODE and announced "nothing reaches
            # Dhan" on the strength of it. trading/execution._route()
            # NEVER READS TRADING_MODE:
            #
            #     switch OFF  ->  paper. Nothing reaches Dhan.
            #     switch ON   ->  Dhan, if this process has a live
            #                     executor at all.
            #
            # So with a Dhan client present and TRADING_MODE left at
            # PAPER -- which is exactly this machine -- pressing ON
            # routes REAL ORDERS while the terminal says fills are
            # simulated. The screen was telling him the opposite of
            # what the money was doing.
            #
            # /api/mode has always asked the right question. This now
            # asks the same one: not what the config says, but whether
            # this process can actually reach the exchange.
            _live = getattr(execution, "_live", None) is not None
            decision("=" * 62)
            if _live:
                decision("  BOT TRADING IS ON. Orders placed from here "
                         "are REAL.")
            else:
                decision("  BOT TRADING IS ON -- PAPER. This process has "
                         "no live executor, so nothing reaches Dhan.")
            decision("  Switched from the dashboard. A restart returns to "
                     "watching.")
            decision("=" * 62)
        else:
            # ---- THE WORDS WERE THE OLD RULE. 3 September 2026. ----
            #
            #     "bot opens with Default OFF = paper trade , after
            #      clicking ON = real trade mode . is this working
            #      right now or not"           -- the operator
            #
            # It IS working. engine.alert_only is set False in both
            # positions a few lines above, so the bot trades either
            # way, and execution.live picks whose money. This line
            # still described the rule that was removed on 31 August
            # -- "no new entries" -- and it is the reason he doubted a
            # switch that was doing exactly what he asked.
            #
            # A message that contradicts the code teaches him not to
            # trust the screen, which costs more than the bug would.
            decision(f"[DASHBOARD] Bot trading OFF -- PAPER. The bot "
                     f"keeps trading; fills are simulated and nothing "
                     f"reaches Dhan. {held} open position(s) keep "
                     f"their stops and trails.")
        trade_controller.note_action(
            True, f"Bot trading {'ON' if want_trading else 'OFF'}")
        return {"success": True, "trading": want_trading,
                "open_positions": held,
                "breakout_armed": False,
                "note": ("stops and trails keep running on open "
                         "positions either way; this arms the RANKED "
                         "list only -- breakout entries stay on alert")}

    @app.post("/api/breakout_trading/{state}")
    def breakout_trading(state: str, request: Request):
        """THE SECOND SWITCH, and it is separate on purpose.

        The structural breakout path buys a level break. It does not
        check that the stock is up 1%, that it is above its own open,
        that there is a written reason for the move, that it beats its
        sector, or that it is liquid enough for his size. Those are the
        RANKER's gates and the breakout has none of them.

        On 6 August one switch armed both and produced eight fills he
        did not want. So this exists, off by default, and turning the
        bot on never turns it on.
        """
        _require_operator(request)
        engine = getattr(dashboard_state, "engine", None)
        if engine is None:
            return {"success": False, "error": "no engine in this session"}
        want = str(state).lower() in ("on", "true", "1", "enable")
        if want and getattr(engine, "alert_only", True):
            return {"success": False,
                    "error": "turn bot trading ON first -- the breakout "
                             "cannot trade while the bot is watching"}
        engine.breakout_armed = want
        decision(f"[DASHBOARD] Breakout entries {'ARMED' if want else 'OFF'}"
                 f" -- these have no ranker gates.")
        trade_controller.note_action(
            True, f"Breakout entries {'ON' if want else 'OFF'}")
        return {"success": True, "breakout_armed": want}

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        # Live data is READ-ONLY by nature -- the websocket only
        # ever pushes snapshots, it can't be used to act on
        # anything, so it stays open to view-only visitors too.
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(
                    _json_safe(dashboard_state.get_snapshot()))
                await asyncio.sleep(DASHBOARD_REFRESH_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            diagnostic("[DASHBOARD] Client disconnected.")

    # ---- PRICES, AT TICK SPEED. 4 August 2026. ----
    #
    #     "even today i got confused no of times & felt that lag on
    #      price observations"
    #
    # He was reading a number three seconds behind the Dhan app sitting
    # next to it. The chain was:
    #
    #     tick -> snapshot rebuilt on a 1s timer (main.py)
    #          -> page polls that snapshot every 2s (screen.html)
    #          -> whole board's HTML thrown away and rebuilt
    #
    # None of those three delays are the feed. Ticks arrive live.
    #
    # This channel skips all of it. It reads market_data's price dict
    # directly -- no snapshot, no gainers/losers rebuild, no sector
    # maths -- and pushes ONLY the symbols whose price actually moved
    # since the last frame. On a quiet second that is an empty object;
    # in a burst it is a few dozen numbers. Either way it is kilobytes
    # against the full snapshot's hundreds.
    #
    # Deliberately SEPARATE from /ws rather than making /ws faster:
    # rebuilding the whole snapshot four times a second would put real
    # load on the same process that has to place his orders. The
    # expensive channel stays slow; the cheap one gets fast.
    @app.websocket("/ws/prices")
    async def ws_prices(websocket: WebSocket):
        # Read-only, like /ws -- a price can't be acted on, so no token.
        await websocket.accept()
        sent = {}
        try:
            while True:
                market_data = getattr(
                    getattr(dashboard_state, "engine", None),
                    "market_data", None)
                prices = (market_data.latest_prices()
                          if market_data is not None else {})

                # DELTAS. Re-sending 900 unchanged numbers four times a
                # second is how a "fast" channel becomes the slow one.
                changed = {s: p for s, p in prices.items()
                           if sent.get(s) != p}
                if changed:
                    sent.update(changed)
                    await websocket.send_json(changed)
                else:
                    # A heartbeat, so the page can tell "nothing moved"
                    # from "the socket is dead". Those must never look
                    # the same -- that is the frozen-board bug again.
                    await websocket.send_json({})
                await asyncio.sleep(PRICE_PUSH_SECONDS)
        except WebSocketDisconnect:
            diagnostic("[DASHBOARD] Price client disconnected.")
        except Exception as exc:                           # noqa: BLE001
            # ---- A CLOSED TAB IS NOT AN ERROR. 4 September 2026. ----
            #
            #     "WARNING:asyncio:socket.send() raised exception.
            #      is still printing"                  -- the operator
            #
            # Only WebSocketDisconnect was caught. That is the CLEAN
            # goodbye -- and a browser tab that is closed, refreshed or
            # put to sleep does not send one. The socket underneath
            # dies first, send_json raises at the transport level, and
            # asyncio logs it straight to the terminal, bypassing this
            # process's own logger entirely. He refreshed the desk all
            # afternoon on my instruction, and every stale connection
            # then complained four times a second.
            #
            # It was never a trading fault -- this is the display
            # socket, not the market feed -- but a warning that prints
            # every 250ms is how a log stops being read, which is the
            # same complaint he made about the results misread that has
            # printed every session since day one.
            #
            # Said ONCE per client, at diagnostic level, and the
            # coroutine ends so the connection is dropped rather than
            # written to for ever.
            diagnostic(f"[DASHBOARD] Price client went away "
                       f"({type(exc).__name__}). Dropping it.")

    return app


class _ManagedServer(uvicorn.Server):
    """
    Overrides uvicorn's own signal handling. Signal handlers only
    work reliably in the process's MAIN thread; this server runs
    on a background thread. Without this override, uvicorn either
    fails installing them or fights the main thread's own Ctrl+C
    handling. Only the main thread reacts to SIGINT/SIGTERM in
    this process -- exactly like the feed and news threads already
    do (see main.py's stop_event).
    """

    def install_signal_handlers(self):
        pass


def start_dashboard(dashboard_state, trade_controller, master_loader):
    """
    Starts the dashboard server on a background daemon thread.
    Returns (server, thread) -- stop with stop_dashboard(server,
    thread) on shutdown, never just letting the daemon thread die
    on process exit, so uvicorn gets a chance to close its sockets
    cleanly first.
    """
    operator_token = get_or_create_token()
    app = build_app(
        dashboard_state, trade_controller, master_loader,
        operator_token=operator_token,
    )
    config = uvicorn.Config(
        app,
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        log_level="warning",
        loop="asyncio",  # deterministic on Windows -- uvloop isn't available there anyway
    )
    server = _ManagedServer(config=config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait for the server to actually report ready before returning,
    # so main.py's startup log is trustworthy, not a guess.
    waited = 0.0
    while not server.started and waited < 10.0:
        time.sleep(0.05)
        waited += 0.05

    if server.started:
        # ---- IT PRINTS NO LINK AT ALL. 4 August 2026. ----
        #
        #   "why all these ? only one universal screen required for now.
        #    no screen sharing to anyone."
        #
        # He got FIVE lines on one start: three from here and a boxed
        # two from main.py. Both callers -- main.py and the preview --
        # already print their own banner, so this one was never the
        # answer, only the duplicate. Silence here; one box there.
        pass
    else:
        warn("[DASHBOARD] Server did not report ready within 10s.")

    return server, thread


def stop_dashboard(server, thread, timeout=5):
    """
    The verified clean-shutdown sequence: flip should_exit, then
    JOIN the thread so the process never exits while uvicorn is
    still mid-shutdown. This is specifically the fix for the
    previous bot's Ctrl+C hang.
    """
    server.should_exit = True
    thread.join(timeout=timeout)

    if thread.is_alive():
        warn(
            f"[DASHBOARD] Server thread did not stop within "
            f"{timeout}s -- forcing shutdown."
        )
        server.force_exit = True
        thread.join(timeout=timeout)
