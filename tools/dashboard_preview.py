"""
==========================================================
Dashboard Preview (dev-only, works outside market hours)
==========================================================

Standalone script for browsing/testing the live dashboard
WITHOUT the full trading loop. main.py's own loop checks
`now >= MARKET_CLOSE_T` on its very first pass through the
top of the loop, before it ever sleeps -- correct, deliberate
behaviour for the real bot (never keep trading, or even keep
the dashboard up, past market close), but it means running
main.py after 15:30 IST gets you a dashboard that's alive for
a fraction of a second and then gone before a browser can even
load the page. This script is the fix for THAT specific
problem -- iterating on dashboard layout/data changes on your
own schedule, not the market's.

What actually runs here:
  - core/circuit_monitor.py's REST poll against Dhan's real
    /marketfeed/quote endpoint -- this keeps working outside
    market hours too (it's a plain HTTP request, not a live
    feed), it just returns the last session's OHLC/circuit-
    limit/LTP data rather than numbers moving in real time.
    That's exactly what you'd want to see when the market
    itself is shut -- the Top Gainers/Losers table, risk
    filters, etc. all populate from real (if stale) data, not
    fabricated numbers.
  - dashboard/server.py, wired to a bare Engine() with no
    news_gate/portfolio/sector_monitor/momentum_universe --
    every one of those is fully optional (see core/engine.py's
    own docstring), so the dashboard's other panels just show
    their empty/zero states, same as a fresh session before
    any of those pieces are wired in.

What does NOT run: the Dhan WebSocket tick feed, News Bot, or
any trading/order logic whatsoever. No orders can be placed
from this script even via the dashboard's manual BUY/SELL
buttons -- TradeController's request flags would be set, but
nothing ever calls engine.process_tick() to act on them, so
they're inert here. Safe to leave running indefinitely.

Runs until Ctrl+C -- no market-hours shutdown.

Usage (from the project root -- NOT from inside tools/):
    python tools/dashboard_preview.py

Author : H&M Opportunity Trader
==========================================================
"""

import sys
import time

# Same fix as tools/verify_master_database.py -- running a script
# that lives INSIDE tools/ puts tools/ itself on sys.path[0], not
# the project root, so `from config import ...` / `from core...`
# below would fail with "No module named 'config'" otherwise. This
# only works if the script is actually launched from the project
# root (see Usage above) -- inserting "." only helps if "." IS the
# root.
sys.path.insert(0, ".")

from config import (
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN,
    EXCHANGE_SEGMENT,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
)
from core.master_loader import MasterLoader
from core.market_data import MarketData
from core.engine import Engine
from core.circuit_monitor import CircuitMonitor
from core.logger import decision, warn
from dashboard.state import DashboardState
from dashboard.server import start_dashboard, stop_dashboard


def main():
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        warn(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing. "
            "Copy .env.example to .env and fill them in."
        )
        sys.exit(1)

    from dhanhq import DhanContext, dhanhq as DhanRestClient

    decision(
        "Opportunity Trader -- Dashboard Preview "
        "(dev-only: no trading, no market-hours gate, Ctrl+C to stop)"
    )

    master_loader = MasterLoader()
    total = master_loader.load()
    decision(f"[MASTER_LOADER] Loaded {total} symbols.")

    resolved = {
        symbol: master_loader.security_id(symbol)
        for symbol in master_loader.all_symbols()
    }
    security_id_to_symbol = {v: k for k, v in resolved.items()}

    dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
    dhan_rest_client = DhanRestClient(dhan_context)
    circuit_monitor = CircuitMonitor(dhan_rest_client.quote_data, EXCHANGE_SEGMENT)

    # No ticks will ever arrive (no WebSocket feed here) -- this
    # exists only because DashboardState's constructor requires a
    # market_data object. Advances/declines/day-open-based panels
    # will just show their empty state; unrelated to this preview's
    # purpose (the gainers/losers table doesn't read from this at
    # all -- it reads engine.get_circuit_snapshot() instead). Built
    # before Engine below so it can be wired in the same way main.py
    # does (Engine.market_data -- see core/engine.py's
    # _process_pending_manual_exits() docstring).
    market_data = MarketData()

    # No portfolio/sector_monitor/momentum_universe -- all optional and
    # none of them matter for previewing layout.
    engine = Engine(circuit_monitor=circuit_monitor, market_data=market_data)

    # The news gate IS wired, 2026-07-26. The "Today's Major Events"
    # strip sits at the TOP of the dashboard now, and previewing a
    # layout with its headline panel permanently empty is worse than
    # not previewing at all. Read-only, no broker, works out of hours.
    news_gate = None
    try:
        from core.news_gate import NewsGate
        news_gate = NewsGate()
        news_gate.refresh()
    except Exception as exc:
        warn(f"[PREVIEW] News gate unavailable ({exc}). The events "
             f"strip will render empty.")

    dashboard_state = DashboardState(
        engine, market_data, master_loader,
        news_gate=news_gate,
        get_feed_alive=lambda: None,
    )

    circuit_monitor.start(security_id_to_symbol)
    decision(
        f"[CIRCUIT_MONITOR] Started -- polling "
        f"{len(security_id_to_symbol)} symbols. Works outside market "
        f"hours too -- expect the LAST session's data, not live "
        f"movement, until the next real session opens."
    )

    dashboard_state.refresh()
    dashboard_server, dashboard_thread = start_dashboard(
        dashboard_state, engine.trade_controller, master_loader
    )

    decision("Dashboard preview running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(DASHBOARD_REFRESH_INTERVAL_SECONDS)
            dashboard_state.refresh()
    except KeyboardInterrupt:
        decision("\nStopping dashboard preview (Ctrl+C)...")
    finally:
        circuit_monitor.stop()
        stop_dashboard(dashboard_server, dashboard_thread, timeout=5)
        decision("Shutdown complete.")


if __name__ == "__main__":
    main()
