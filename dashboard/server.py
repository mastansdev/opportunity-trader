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

import uvicorn
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

from config import (
    DASHBOARD_HOST,
    DASHBOARD_PORT,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
)
from core.logger import decision, diagnostic, warn
from dashboard.access_token import get_or_create_token

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
INDEX_PATH = os.path.join(STATIC_DIR, "index.html")

# The exact placeholder line index.html ships with -- build_app()
# replaces it with the real token ONLY when the request proved it
# knows the operator token already (see module docstring).
_TOKEN_PLACEHOLDER = 'window.__OPERATOR_TOKEN__ = "";'


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

    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        _index_html = f.read()

    def _token_matches(candidate) -> bool:
        if operator_token is None:
            return True
        return candidate == operator_token

    @app.get("/", response_class=HTMLResponse)
    def index(token: str = ""):
        if _token_matches(token):
            html = _index_html.replace(
                _TOKEN_PLACEHOLDER,
                f'window.__OPERATOR_TOKEN__ = "{operator_token or ""}";',
            )
        else:
            html = _index_html  # placeholder stays empty -- view-only
        # No-store, 2026-07-24: the operator restarted the bot with a
        # new dashboard (the "Resume New Entries" button) but the
        # browser kept serving the OLD cached page -- the button, and
        # the corrected banner text, never showed. Telling the browser
        # never to cache this HTML means a restart's UI changes are
        # always picked up on the next plain refresh, no hard-reload
        # needed. (The page pulls all live data over the websocket
        # anyway, so there's nothing to gain from caching the shell.)
        return HTMLResponse(html, headers={"Cache-Control": "no-store"})

    @app.post("/api/refresh_gainers_losers")
    def refresh_gainers_losers():
        """2026-07-24 dashboard revamp -- the manual "Refresh now"
        button. Forces the (server-throttled) Top-50 gainers/losers
        and sector heatmap to rebuild immediately. Read-only data
        refresh, so no operator token required (works on view-only
        links too)."""
        dashboard_state.force_gainers_losers_refresh()
        return {"success": True}

    @app.get("/api/snapshot")
    def snapshot():
        """Plain REST fallback alongside the WebSocket feed --
        handy for debugging without opening the page, and for
        tests that don't want to exercise a websocket. Read-only,
        no token required -- same as the WebSocket feed."""
        return dashboard_state.get_snapshot()

    def _require_operator(request: Request):
        if not _token_matches(request.headers.get("X-Operator-Token", "")):
            raise HTTPException(
                status_code=403,
                detail="View-only link -- this action needs the operator link.",
            )

    @app.post("/api/buy/{symbol}")
    def buy(symbol: str, request: Request):
        _require_operator(request)
        symbol = symbol.upper()
        if master_loader.get_by_symbol(symbol) is None:
            return {"success": False, "error": f"Unknown symbol: {symbol}"}
        trade_controller.request_buy(symbol)
        decision(f"[DASHBOARD] Manual BUY requested: {symbol}")
        return {"success": True}

    @app.post("/api/sell/{symbol}")
    def sell(symbol: str, request: Request):
        _require_operator(request)
        symbol = symbol.upper()
        trade_controller.request_exit(symbol)
        decision(f"[DASHBOARD] Manual SELL requested: {symbol}")
        return {"success": True}

    @app.post("/api/short/{symbol}")
    def short(symbol: str, request: Request):
        """Per-row SHORT button on the Top 50 Losers table -- opens
        a NEW short position (mirrors buy() above, direction
        flipped), unlike sell() which only ever EXITS an existing
        one. See trading/trade_controller.py's docstring."""
        _require_operator(request)
        symbol = symbol.upper()
        if master_loader.get_by_symbol(symbol) is None:
            return {"success": False, "error": f"Unknown symbol: {symbol}"}
        trade_controller.request_short(symbol)
        decision(f"[DASHBOARD] Manual SHORT requested: {symbol}")
        return {"success": True}

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

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket):
        # Live data is READ-ONLY by nature -- the websocket only
        # ever pushes snapshots, it can't be used to act on
        # anything, so it stays open to view-only visitors too.
        await websocket.accept()
        try:
            while True:
                await websocket.send_json(dashboard_state.get_snapshot())
                await asyncio.sleep(DASHBOARD_REFRESH_INTERVAL_SECONDS)
        except WebSocketDisconnect:
            diagnostic("[DASHBOARD] Client disconnected.")

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
        base = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
        decision(
            f"[DASHBOARD] Your control link (buttons work): "
            f"{base}/?token={operator_token}\n"
            f"[DASHBOARD] Safe to share -- view only, no buttons: {base}/"
        )
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
