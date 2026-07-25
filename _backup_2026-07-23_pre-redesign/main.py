"""
==========================================================
Opportunity Trader -- Layer 1 entry point
==========================================================

Raw ORB structural breakout, PAPER mode, NSE equity only.
Manual exit only -- no automated stop loss, no target, no
trailing.

Console commands while running (type + Enter):
    exit SYMBOL   -- exit one open position
    exitall       -- exit everything now
    positions     -- print open positions
    Ctrl+C        -- clean shutdown (flattens nothing
                     automatically -- open positions stay
                     open on restart, resolved manually)

Author : H&M Opportunity Trader
==========================================================
"""

import sys
import threading
import time
from datetime import datetime, time as dtime

from config import (
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN,
    EXCHANGE_SEGMENT,
    SQUARE_OFF_TIME,
    MARKET_CLOSE,
    ORB_WINDOW_END,
    TOP_N_MOMENTUM_MODE,
    HEARTBEAT_INTERVAL_SECONDS,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
)
from core.master_loader import MasterLoader
from core.market_data import MarketData
from core.dhan_time import parse_ltt_to_ist
from core.engine import Engine
from core.momentum_universe import MomentumUniverse
from core.circuit_monitor import CircuitMonitor
from core.logger import decision, diagnostic, warn
from core import state_store
from core.news_gate import NewsGate
from news_bot import pipeline as news_pipeline
from news_bot.call_budget import CallBudget
from news_bot.config import POLL_INTERVAL_SECONDS as NEWS_POLL_INTERVAL_SECONDS
from news_bot.matching import NewsMatcher
from trading.portfolio import Portfolio
from core.sector_monitor import SectorMonitor
from dashboard.state import DashboardState
from dashboard.server import start_dashboard, stop_dashboard


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


SQUARE_OFF_T = _parse_hhmm(SQUARE_OFF_TIME)
MARKET_CLOSE_T = _parse_hhmm(MARKET_CLOSE)
ORB_WINDOW_END_T = _parse_hhmm(ORB_WINDOW_END)


def _command_reader(engine, stop_event):
    """Reads operator commands from stdin on a background thread."""
    while not stop_event.is_set():
        try:
            line = input().strip()
        except EOFError:
            return

        if not line:
            continue

        if line == "exitall":
            engine.trade_controller.request_exit_all()
            decision("Manual EXIT ALL requested.")

        elif line.startswith("exit "):
            symbol = line.split(" ", 1)[1].strip().upper()
            engine.trade_controller.request_exit(symbol)
            decision(f"Manual EXIT requested: {symbol}")

        elif line == "positions":
            if not engine.open_positions:
                decision("No open positions.")
            for symbol, pos in engine.open_positions.items():
                decision(
                    f"{symbol}: qty={pos['qty']} "
                    f"entry={pos['entry_price']:.2f}"
                )

        else:
            decision(f"Unknown command: {line!r}")


def _news_loop(stop_event, matcher, budget, news_gate):
    """
    Runs News Bot's full pipeline every POLL_INTERVAL_SECONDS,
    on its own thread, independent of the tick feed. A failure
    in any one cycle is caught and logged here -- News Bot is
    advisory-only (core/news_gate.py); it must never be able to
    take the main trading loop down with it.
    """
    while not stop_event.is_set():
        try:
            news_pipeline.run_once(matcher=matcher, budget=budget)
            news_gate.refresh()
        except Exception as e:
            warn(f"[NEWS_BOT] Pipeline cycle failed, will retry: {e}")

        stop_event.wait(NEWS_POLL_INTERVAL_SECONDS)


def main():
    if not DHAN_CLIENT_ID or not DHAN_ACCESS_TOKEN:
        warn(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing. "
            "Copy .env.example to .env and fill them in."
        )
        sys.exit(1)

    from dhanhq import DhanContext, MarketFeed
    # Aliased -- the WebSocket ticker class above is ALSO named
    # "MarketFeed" inside the dhanhq package, so importing the REST
    # client under its own bare name here would be fine (no clash),
    # but "DhanRestClient" keeps the two roles (WebSocket ticks vs
    # REST snapshot queries) unambiguous at every call site below.
    # This is the combined REST client (Order/Portfolio/quote_data/
    # etc. all in one) -- circuit_monitor only ever calls
    # .quote_data() on it (core/circuit_monitor.py's own docstring
    # explains why this has to be REST, not the WebSocket feed).
    from dhanhq import dhanhq as DhanRestClient

    decision("Opportunity Trader -- Layer 1 (PAPER, equity only)")

    master_loader = MasterLoader()
    total = master_loader.load()
    decision(
        f"[MASTER_LOADER] Loaded {total} symbols from the verified "
        f"master database (data/master_stocks.csv)."
    )

    resolved = {
        symbol: master_loader.security_id(symbol)
        for symbol in master_loader.all_symbols()
    }
    if not resolved:
        warn("No universe symbols resolved. Nothing to trade. Exiting.")
        sys.exit(1)

    decision(f"Universe resolved: {len(resolved)} symbols.")

    # security_id -> symbol, the reverse of `resolved` above. Built
    # once, here, and reused by both the circuit monitor (below) and
    # the WebSocket feed's on_message handler (further down) -- one
    # source of truth for the mapping, not two copies drifting apart.
    security_id_to_symbol = {v: k for k, v in resolved.items()}

    # News Bot setup -- reuses the already-loaded master_loader
    # (NewsMatcher only reloads if it's handed an empty one), so
    # this doesn't repeat the 750-row CSV read. Advisory-only via
    # news_gate; see core/news_gate.py's docstring for why.
    news_matcher = NewsMatcher(loader=master_loader)
    news_budget = CallBudget()
    news_gate = NewsGate()

    market_data = MarketData()
    portfolio = Portfolio()
    sector_monitor = SectorMonitor(market_data, master_loader)
    # TOP_N_MOMENTUM_MODE (config.py) -- wired in unconditionally,
    # same pattern as sector_monitor/news_gate above: the object
    # always exists, the config flag decides whether Engine actually
    # consults it (core/engine.py's _try_structural_entry()).
    momentum_universe = MomentumUniverse(market_data, master_loader)

    # Circuit monitor -- built here (before the WebSocket feed setup
    # further down) specifically because it needs its own, separate
    # Dhan connection: DhanContext itself is cheap/stateless to
    # construct twice, but the REST client (DhanRestClient) and the
    # WebSocket ticker (MarketFeed, further below) are two genuinely
    # different transports hitting two different Dhan endpoints, so
    # each gets its own client instance. See core/circuit_monitor.py's
    # docstring for why this has to be REST (/marketfeed/quote) and
    # can't reuse the WebSocket tick stream at all.
    dhan_context = DhanContext(DHAN_CLIENT_ID, DHAN_ACCESS_TOKEN)
    dhan_rest_client = DhanRestClient(dhan_context)
    circuit_monitor = CircuitMonitor(dhan_rest_client.quote_data, EXCHANGE_SEGMENT)

    engine = Engine(
        news_gate=news_gate, portfolio=portfolio, sector_monitor=sector_monitor,
        momentum_universe=momentum_universe, circuit_monitor=circuit_monitor,
    )

    (
        saved_orb_ranges,
        saved_positions,
        saved_trailing_stops,
        saved_portfolio,
        saved_entry_blocks,
        saved_momentum_universe,
    ) = state_store.load()
    if saved_orb_ranges:
        engine.orb_engine.load_state(saved_orb_ranges)
    if saved_positions:
        engine.load_positions(saved_positions)
    if saved_trailing_stops:
        engine.trailing_stop.load_state(saved_trailing_stops)
    if saved_portfolio:
        portfolio.load_state(saved_portfolio)
    if saved_entry_blocks:
        engine.load_entry_blocks(saved_entry_blocks)
    if saved_momentum_universe:
        momentum_universe.load_state(saved_momentum_universe)
    if (saved_orb_ranges or saved_positions or saved_trailing_stops
            or saved_portfolio or saved_entry_blocks or saved_momentum_universe):
        if saved_momentum_universe:
            n_long = len(saved_momentum_universe.get("long", []))
            n_short = len(saved_momentum_universe.get("short", []))
            momentum_note = f"locked ({n_long} long / {n_short} short)"
        else:
            momentum_note = "not yet locked"
        decision(
            f"[STATE] Recovered from earlier today: "
            f"{len(saved_positions or {})} open position(s), "
            f"{len(saved_orb_ranges or {})} ORB range(s), "
            f"{len(saved_trailing_stops or {})} trailing stop(s), "
            f"{len(saved_entry_blocks or {})} entry block(s), "
            f"portfolio: {'restored' if saved_portfolio else 'fresh'}, "
            f"momentum universe: {momentum_note}."
        )

    # Mutable holder, not a plain variable -- the feed thread gets
    # REPLACED on reconnect (the watchdog below does
    # `feed, feed_thread = start_feed()` again), and this lambda is
    # handed to DashboardState/system-health BEFORE that thread even
    # exists yet (dashboard_state is built before start_feed() runs
    # for the first time below). A dict box means the closure always
    # reads whatever the CURRENT thread is at refresh time, not
    # whatever existed at construction time.
    feed_state = {"thread": None}

    dashboard_state = DashboardState(
        engine, market_data, master_loader,
        news_gate=news_gate, portfolio=portfolio, sector_monitor=sector_monitor,
        get_feed_alive=lambda: (
            feed_state["thread"].is_alive() if feed_state["thread"] else None
        ),
    )

    def on_accepted_tick(symbol, price, tick_time):
        engine.process_tick(
            symbol, resolved[symbol], price, tick_time
        )

    market_data.on_new_tick(on_accepted_tick)

    # dhan_context/security_id_to_symbol were already built above,
    # alongside circuit_monitor -- reused here for the WebSocket feed,
    # not rebuilt.
    instruments = [
        (MarketFeed.NSE, security_id, MarketFeed.Ticker)
        for security_id in resolved.values()
    ]

    def on_message(_instance, message):
        try:
            security_id = str(message.get("security_id"))
            symbol = security_id_to_symbol.get(security_id)
            if symbol is None:
                return

            price = float(message.get("LTP", 0) or 0)
            if price <= 0:
                return

            ltt_raw = message.get("LTT")
            tick_time = parse_ltt_to_ist(ltt_raw) or datetime.now()

            market_data.on_tick(symbol, price, tick_time)

        except Exception as e:
            warn(f"Tick handling error: {e}")

    error_tracker = {"last_message": None}

    def on_connect(_instance):
        decision("[FEED] Connected to Dhan live feed.")
        error_tracker["last_message"] = None

    def on_close(_instance):
        warn("[FEED] Feed connection closed.")

    def on_error(_instance, error):
        message = str(error)
        # Edge-triggered, same reasoning as stale-tick warnings: a
        # broken feed can throw the same error every retry attempt --
        # print it once, not once per retry.
        if error_tracker.get("last_message") != message:
            warn(f"[FEED] Feed error, retrying: {message}")
            error_tracker["last_message"] = message
        else:
            diagnostic(f"[FEED] Feed error persists: {message}")

    def start_feed():
        """
        feed.run_forever() is misleadingly named -- it only connects
        and subscribes ONCE, then returns, silently. It does NOT
        receive ticks continuously and does NOT reconnect. feed.run()
        is the SDK's real continuous receive loop (with its own
        auto-reconnect on a dropped socket) -- that's what a thread
        meant to run all session needs.
        """
        feed = MarketFeed(
            dhan_context,
            instruments,
            version="v2",
            on_message=on_message,
            on_connect=on_connect,
            on_close=on_close,
            on_error=on_error,
        )
        thread = threading.Thread(target=feed.run, daemon=True)
        thread.start()
        return feed, thread

    stop_event = threading.Event()
    reader_thread = threading.Thread(
        target=_command_reader, args=(engine, stop_event), daemon=True
    )
    reader_thread.start()

    news_thread = threading.Thread(
        target=_news_loop,
        args=(stop_event, news_matcher, news_budget, news_gate),
        daemon=True,
    )
    news_thread.start()

    # Own poll thread, independent of the tick feed -- see
    # core/circuit_monitor.py's docstring. Started with the full
    # resolved universe so proximity data exists for every symbol a
    # structural entry could fire on, not just today's open
    # positions (which don't exist yet at startup anyway).
    circuit_monitor.start(security_id_to_symbol)
    decision(
        f"[CIRCUIT_MONITOR] Started -- polling {len(security_id_to_symbol)} "
        f"symbols for circuit-limit proximity."
    )

    feed, feed_thread = start_feed()
    feed_state["thread"] = feed_thread

    sector_monitor.refresh()   # so the first heartbeat's panic picture isn't empty by default
    dashboard_state.refresh()  # so the page has real data on its very first load
    dashboard_server, dashboard_thread = start_dashboard(
        dashboard_state, engine.trade_controller, master_loader
    )

    squared_off = False
    last_heartbeat = time.monotonic()
    last_dashboard_refresh = time.monotonic()
    last_tick_count = 0
    feed_dead_since = None

    try:
        while True:
            now = datetime.now().time()

            # Dashboard snapshot refresh -- its own cadence, decoupled
            # from the heartbeat/state-save cadence, so tightening or
            # loosening one never affects the other.
            if time.monotonic() - last_dashboard_refresh >= DASHBOARD_REFRESH_INTERVAL_SECONDS:
                dashboard_state.refresh()
                last_dashboard_refresh = time.monotonic()

            if not squared_off and now >= SQUARE_OFF_T:
                engine.flatten_all(market_data.get_latest_price)
                squared_off = True

            # TOP_N_MOMENTUM_MODE (config.py): lock the top-25-
            # gainers/top-25-losers shortlist exactly once, right
            # when the ORB window closes -- same one-shot-guard
            # pattern as squared_off above, except the guard here is
            # the universe's own is_locked() rather than a separate
            # bool, so a restart that already restored a saved lock
            # (state_store.load() above) never re-locks a possibly-
            # different list.
            if TOP_N_MOMENTUM_MODE and not momentum_universe.is_locked() \
                    and now >= ORB_WINDOW_END_T:
                momentum_universe.lock()

            if now >= MARKET_CLOSE_T:
                decision("Market closed. Shutting down.")
                break

            # Watchdog: the feed thread should run for the whole
            # session. If it ever dies (crash, not just a dropped
            # socket -- run()'s own loop already handles those) this
            # is the safety net that notices and restarts it, loudly,
            # instead of the bot quietly going stale with no ticks
            # and no error, which is exactly what happened before.
            if not feed_thread.is_alive():
                if feed_dead_since is None:
                    feed_dead_since = time.monotonic()
                    warn(
                        "[FEED] Feed thread is not running. "
                        "Restarting in 5s..."
                    )
                elif time.monotonic() - feed_dead_since >= 5:
                    feed, feed_thread = start_feed()
                    feed_state["thread"] = feed_thread
                    feed_dead_since = None
                    decision("[FEED] Feed thread restarted.")

            if time.monotonic() - last_heartbeat >= HEARTBEAT_INTERVAL_SECONDS:
                tick_count = market_data.get_tick_count()
                decision(
                    f"[HEARTBEAT] {datetime.now().strftime('%H:%M:%S')} | "
                    f"ticks: {tick_count} "
                    f"(+{tick_count - last_tick_count} in last "
                    f"{HEARTBEAT_INTERVAL_SECONDS}s) | "
                    f"open positions: {len(engine.open_positions)} | "
                    f"ORB ranges: {engine.orb_engine.range_count()} "
                    f"({engine.orb_engine.complete_count()} complete) | "
                    f"stale symbols flagged: "
                    f"{market_data.get_stale_warning_count()} | "
                    f"circuit-proximity flagged: "
                    f"{len(engine.get_circuit_flagged_symbols())} | "
                    f"feed alive: {feed_thread.is_alive()}"
                )
                last_heartbeat = time.monotonic()
                last_tick_count = tick_count

                # Same cadence as the heartbeat -- breadth-based, not
                # tick-hot (core/sector_monitor.py's own docstring),
                # so this is exactly the right rhythm for it.
                sector_monitor.refresh()

                # Same cadence as the heartbeat -- cheap, and bounds
                # how much state a crash could lose to ~60s instead
                # of the whole session.
                state_store.save(
                    engine.orb_engine.export_state(),
                    engine.export_positions(),
                    engine.trailing_stop.export_state(),
                    portfolio.export_state(),
                    engine.export_entry_blocks(),
                    momentum_universe.export_state(),
                )

            time.sleep(1)

    except KeyboardInterrupt:
        decision("\nStopping Opportunity Trader (Ctrl+C)...")

    finally:
        stop_event.set()
        # Own stop flag, separate from stop_event above -- see
        # core/circuit_monitor.py's start()/stop(). Daemon thread, so
        # process exit would reap it regardless, but stopping it
        # explicitly means no further doomed REST calls fire during
        # shutdown.
        circuit_monitor.stop()
        state_store.save(
            engine.orb_engine.export_state(),
            engine.export_positions(),
            engine.trailing_stop.export_state(),
            portfolio.export_state(),
            engine.export_entry_blocks(),
            momentum_universe.export_state(),
        )
        # Dashboard first (it's the fastest to stop and has no open
        # network connections to Dhan to worry about), then the feed.
        # This ordering, plus the should_exit+join pattern inside
        # stop_dashboard(), is the fix for the previous bot's Ctrl+C
        # hang -- every background thread here is either joined with
        # a timeout or a daemon thread, so the process can always
        # exit even if one piece misbehaves.
        stop_dashboard(dashboard_server, dashboard_thread, timeout=5)
        _safe_close_feed(feed, timeout=5)
        decision("Shutdown complete.")


def _safe_close_feed(feed, timeout=5):
    """
    feed.close_connection() can block. Run it on its own
    thread with a timeout so a second Ctrl+C during shutdown
    doesn't produce an unhandled crash.
    """
    done = threading.Event()

    def _close():
        try:
            feed.close_connection()
        except Exception as e:
            diagnostic(f"[SHUTDOWN] close_connection error: {e}")
        finally:
            done.set()

    threading.Thread(target=_close, daemon=True).start()

    try:
        done.wait(timeout=timeout)
    except KeyboardInterrupt:
        decision("Forcing exit without waiting for cleanup.")


if __name__ == "__main__":
    main()
