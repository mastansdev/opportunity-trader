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
    py tools/dashboard_preview.py            # real (stale) broker data
    py tools/dashboard_preview.py --demo     # no broker needed

--demo, added 2026-07-26
------------------------
The plain preview shows real quote data, but with no trading loop the
book is empty -- so POSITIONS, the seats strip, the RS/ORB columns and
the "Why No Trade" funnel all sit in their empty states, which is
exactly what you cannot review.

--demo drives the REAL Engine with synthetic ticks: real
core/strategy.py cross detection, real gates, real ATR sizing, real
gate log. Nothing about the dashboard is faked -- only the PRICES going
in. Real universe symbols are used, so the daily-trend badges resolve
against genuinely stored history.

Because the prices are invented, the page shows a loud red DEMO DATA
banner for as long as it runs. A screenshot of a demo session is
otherwise indistinguishable from a real one, and this project has
already been burned once by a number that looked real and was not.

No Dhan credentials are needed in --demo.

Author : H&M Opportunity Trader
==========================================================
"""

import sys
import time
from datetime import datetime, timedelta

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


def _demo_session(engine, symbols, day=None, market_data=None):
    """
    Feed the REAL engine a synthetic morning so every panel has
    something in it.

    Nothing here bypasses the engine: each symbol gets a genuine
    09:15-09:30 opening range built tick by tick, then a move that
    either clears the boundary with conviction or does not. What
    happens next -- entry, decline, which gate -- is entirely the
    engine's own decision, which is the point. The gate funnel that
    comes out is real logic on invented prices.

    Deliberately mixed so the funnel is not one-sided:
      - clean long breakouts   -> should enter
      - clean short breakdowns -> should enter (regime permitting)
      - grazes                 -> declined
      - one blocked symbol     -> a stated-reason rejection
      - one post-square-off cross
    """
    day = day or datetime.now().replace(hour=0, minute=0, second=0,
                                        microsecond=0)

    def t(hh, mm, ss=0):
        return day + timedelta(hours=hh, minutes=mm, seconds=ss)

    def tick(symbol, sid, price, when, cum):
        """
        Every tick goes to BOTH the engine and market_data -- the
        dashboard reads CMP/MTM from market_data, so skipping it leaves
        every position showing a P&L of exactly zero.

        `now=when` is essential and not obvious. market_data measures
        staleness as (now - tick_time), and these ticks are stamped
        09:15 while the wall clock says evening -- so with the real
        clock every symbol is hours stale, trips
        is_orb_window_unreliable(), and nothing trades. Passing the
        simulated clock is what makes the replay coherent rather than a
        feed outage. (The gate log named ORB_UNRELIABLE as the cause of
        exactly that, twice, while this was being written.)
        """
        engine.process_tick(symbol, sid, price, when, cum)
        if market_data is not None:
            try:
                market_data.on_tick(symbol, price, when, now=when,
                                    cum_volume=cum)
            except Exception:           # noqa: BLE001 -- preview only
                pass

    plan = []
    for i, symbol in enumerate(symbols):
        base = 250.0 + i * 37.0          # above the Rs 200 floor
        # "novol" is the one that produces a NEAR MISS: a clean, decisive
        # breakout carrying no volume surge, so it passes every selection
        # rule and dies on mechanics -- which is exactly the bucket the
        # panel exists to show.
        kind = ("long", "short", "novol", "long", "blocked",
                "short", "novol", "late")[i % 8]
        plan.append((symbol, str(1000 + i), base, kind))

    # 1. opening range, 09:15 -> 09:30, DENSELY.
    #
    # Two ticks a minute, not one every five. core/market_data.py's
    # is_orb_window_unreliable() correctly refuses to trust an opening
    # range built from a gappy feed -- the SONACOMS incident -- and a
    # sparse synthetic feed trips it for all 16 symbols, which is the
    # gate doing exactly its job. Worth leaving this comment: the first
    # version of this demo produced zero trades and the gate log named
    # ORB_UNRELIABLE as the reason within seconds.
    cum = 10_000
    for minute in range(15, 30):
        for half in (0, 30):
            # a shape with a real high and low inside the window
            wave = 1.0 + 0.012 * ((minute - 15) % 6 - 2.5) / 2.5
            for symbol, sid, base, _ in plan:
                tick(symbol, sid, base * wave, t(9, minute, half), cum)
            cum += 300
    for symbol, sid, base, _ in plan:
        tick(symbol, sid, base * 1.004, t(9, 30, 0), cum)

    # 2. a few quiet candles -- primes the volume average. Prices are
    # nudged every candle: three identical closes in a row would trip
    # the frozen-feed guard, which is correct behaviour and not what we
    # are trying to look at here.
    for n, minute in enumerate(range(31, 36)):
        cum += 900
        for symbol, sid, base, _ in plan:
            tick(symbol, sid, base * (1.004 + n * 0.0002),
                                t(9, minute, 0), cum)

    for symbol, sid, base, kind in plan:
        if kind == "blocked":
            engine._block_entry(
                symbol, "LONG",
                "demo: blocked to show a stated-reason rejection")

    # 3. THE NEAR-MISSES GO FIRST, while seats are still free. A
    # candidate only reaches the volume/margin gates if it gets past
    # BOOK_FULL, so if the clean breakouts filled the book first there
    # would be no near-misses on the panel at all.
    #
    # Note the cumulative volume does NOT move here: a decisive price
    # break carrying no extra volume is precisely the MOIL/TATASTEEL
    # drift the volume filter exists to reject.
    for n, minute in enumerate((36, 37)):
        for symbol, sid, base, kind in plan:
            if kind == "novol":
                tick(symbol, sid, base * (1.030 + n * 0.0004),
                     t(9, minute, 0), cum)

    # 4. then the real moves
    cum += 40_000                        # a surge, so the volume gate passes
    moves = {
        "long":    1.030,                # clears the 09:15-09:30 high
        "short":   0.968,                # breaks the low
        "novol":   1.031,
        "blocked": 1.030,
        "late":    1.004,                # does nothing until after 15:15
    }
    for n, minute in enumerate((38, 39, 40)):
        for symbol, sid, base, kind in plan:
            engine.process_tick(symbol, sid,
                                base * (moves[kind] + n * 0.0003),
                                t(9, minute, 0), cum)
        cum += 5_000

    # 5. let the open book MOVE, so MTM/RR/stops are worth looking at.
    # Deliberately stops before 10:10: the no-progress exit fires at 30
    # minutes, and a preview with an empty POSITIONS table defeats the
    # point.
    for n, minute in enumerate((42, 45, 48, 52, 56)):
        for symbol, sid, base, kind in plan:
            if kind in ("long", "blocked"):
                drift = 1.030 + (n + 1) * 0.004      # running
            elif kind == "short":
                drift = 0.968 - (n + 1) * 0.003
            else:
                drift = moves[kind] + n * 0.0004
            tick(symbol, sid, base * drift,
                                t(9, minute, 0), cum)
            cum += 400

    # 6. one cross after the hard square-off -> the SQUARE_OFF gate
    for symbol, sid, base, kind in plan:
        if kind == "late":
            tick(symbol, sid, base * 1.05, t(15, 20, 0), cum)
            tick(symbol, sid, base * 1.052, t(15, 21, 0), cum)


def _run_demo():
    from core.gate_log import GateLog

    decision("=" * 62)
    decision("  DASHBOARD PREVIEW -- DEMO DATA")
    decision("=" * 62)
    decision("  Real engine, real gates, real sizing. INVENTED PRICES.")
    decision("  Nothing on this page is a real trade or a real number.")
    decision("  For layout review only.")
    decision("-" * 62)

    master_loader = MasterLoader()
    master_loader.load()
    # Real symbols, so the daily-trend badges resolve against the
    # history actually stored in data/daily_candles.db.
    symbols = master_loader.all_symbols()[:16]

    market_data = MarketData()
    engine = Engine(market_data=market_data, gate_log=GateLog())

    _demo_session(engine, symbols, market_data=market_data)

    decision(f"  Demo session done: {len(engine.open_positions)} open, "
             f"{len(engine.closed_positions)} closed.")
    snap = engine.get_gate_log() or {}
    summary = (snap.get("summary") or {})
    decision(f"  Gate funnel: {summary.get('candidates', 0)} candidates, "
             f"{summary.get('entries', 0)} traded, "
             f"{summary.get('rejected', 0)} declined.")

    dashboard_state = DashboardState(
        engine, market_data, master_loader,
        get_feed_alive=lambda: None, demo=True,
    )
    # Freeze the panel's clock inside the simulated session. Without
    # this the seats strip reads the real evening clock and reports
    # "cap 0 -- no new entries after 15:00", which is true of right now
    # and false of the 09:56 session on the screen.
    demo_now = datetime.now().replace(hour=9, minute=56, second=0,
                                      microsecond=0)
    dashboard_state._clock = lambda: demo_now
    dashboard_state.refresh()
    dashboard_server, dashboard_thread = start_dashboard(
        dashboard_state, engine.trade_controller, master_loader
    )
    decision("")
    decision("  Open http://127.0.0.1:8000   (Ctrl+C to stop)")

    try:
        while True:
            time.sleep(DASHBOARD_REFRESH_INTERVAL_SECONDS)
            dashboard_state.refresh()
    except KeyboardInterrupt:
        decision("\nStopping demo preview (Ctrl+C)...")
    finally:
        stop_dashboard(dashboard_server, dashboard_thread, timeout=5)
        decision("Shutdown complete.")


def main():
    if "--demo" in sys.argv:
        return _run_demo()

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

    dashboard_state = DashboardState(
        engine, market_data, master_loader,
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
