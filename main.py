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

import queue
import os
import sys
import threading
import time
from datetime import datetime, time as dtime

from config import (
    DHAN_CLIENT_ID,
    DHAN_ACCESS_TOKEN,
    EXCHANGE_SEGMENT, MTF_MARGIN_PER_POSITION_RS,
    SQUARE_OFF_TIME, FORCE_SQUARE_OFF_AT_CLOSE,
    MARKET_CLOSE,
    KEEP_DASHBOARD_AFTER_CLOSE, DASHBOARD_AFTER_CLOSE_EXIT_AT,
    ORB_WINDOW_END,
    TOP_N_MOMENTUM_MODE, ENABLE_MOMENTUM_LOCK,
    HEARTBEAT_INTERVAL_SECONDS,
    DASHBOARD_REFRESH_INTERVAL_SECONDS,
)
from core import single_instance
from core.master_loader import MasterLoader
from core.market_data import MarketData
from core.dhan_time import parse_ltt_to_ist
from core.engine import Engine
from core.momentum_universe import MomentumUniverse
from core.circuit_monitor import CircuitMonitor
from core.index_monitor import IndexMonitor, is_index_segment
from core.candle_recorder import CandleRecorder
from core import feed_watch
from core import tick_ohlc
from core import dhan_auth
from core.stock_memory import StockMemory
from core.trade_memory import TradeMemory
from core.breakout_feed import BreakoutFeed
from core.mtf_margin import MtfMarginBook, dhan_margin_calculator
from core.signal_journal import SignalJournal
from core.results_gate import ResultsGate
from core import corporate_actions
from config import ENABLE_INDEX_FEED, INDEX_INSTRUMENTS, ENABLE_CANDLE_RECORDING
from config import MAX_OPEN_POSITIONS
from config import (
    ENABLE_ANNOUNCEMENT_WATCHER, ANNOUNCEMENT_POLL_SECONDS,
    ANNOUNCEMENT_LOOKBACK_HOURS, ENABLE_FILING_PDF_READING,
    ENABLE_NEWS_WATCHER, NEWS_POLL_SECONDS,
)
from core.announcement_watcher import AnnouncementWatcher
from core.results_ingest import ResultsIngestor, requests_downloader
from core.news_watcher import NewsWatcher
from core.market_flows import MarketFlows
from config import ENABLE_STOCK_MEMORY, ENABLE_TRADE_MEMORY
from config import EARNINGS_CALENDAR
# For the startup banner only. The order path reads this itself in
# trading/execution.py -- this must never become a second place that
# DECIDES the mode, only a place that reports it.
from config import TRADING_MODE
from core import broker_funds
# Orders leave via the static IP; everything else stays on the home
# connection. See core/order_route.py for why that split exists.
from core import order_route
from config import ORDER_PROXY
from core.logger import decision, diagnostic, warn, log_file_path
from core import auto_entry
from core import state_store
from trading.portfolio import Portfolio
from core.sector_monitor import SectorMonitor
from dashboard.state import DashboardState
from dashboard.server import start_dashboard, stop_dashboard


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


SQUARE_OFF_T = _parse_hhmm(SQUARE_OFF_TIME)
MARKET_CLOSE_T = _parse_hhmm(MARKET_CLOSE)
AFTER_CLOSE_EXIT_T = _parse_hhmm(DASHBOARD_AFTER_CLOSE_EXIT_AT)
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


# ---- THE PORT PROBE LIVED HERE, AND KILLING IT WAS THE POINT ----
#
# _another_bot_is_already_running(port) asked "is something listening
# on 8000?". core/single_instance.py replaced it on 13 August because
# on Windows a second socket binds straight over a listening one, so
# the probe saw nothing and waved the second bot through.
#
# It was left in place, called by nobody, for one more day. That was
# the expensive part. tests/test_single_instance.py still patched it:
#
#     monkeypatch.setattr(main, "_another_bot_is_already_running",
#                         lambda *a, **k: True)
#     with pytest.raises(SystemExit):
#         main.main()
#
# monkeypatch.setattr succeeds against a function that exists, whether
# or not anything calls it. So the patch did nothing, main() consulted
# the real guard, found no other bot, AND STARTED ONE -- inside the
# test suite. On 16 August that test ran for twenty minutes with a
# live tick worker and a full ranker before it was traced with py-spy.
# On a morning with ALERT_ONLY_MODE off it would have been a second
# bot on his Dhan account, started by pytest.
#
# A dead function that a test still patches is not harmless. Deleting
# it turns that patch into an AttributeError -- loud, instant, and at
# collection time.

def main():
    # ---- ONE BOT AT A TIME, AND THIS IS THE FIRST LINE ----------
    # Refuses rather than warns. A warning at 09:00 scrolls off the
    # screen in seconds, and the failure it precedes is two processes
    # trading the same account.
    #
    # ---- IT USED TO REFUSE SECOND. 16 August 2026. ----
    #
    # The token block now below this ran BEFORE the guard, so a second
    # bot asked Dhan for a token on its way to being turned away. Dhan
    # allows one mint every two minutes, so the process with no right
    # to start could spend the quota belonging to the one that did --
    # which is the rate-limit refusal he pasted on 13 August.
    #
    # tests/test_single_instance.py asserted the opposite from the day
    # it was written -- "must not connect to Dhan, open a database or
    # bind a socket on the way to refusing" -- and the assertion was
    # never true. It patched the guard out and never watched the
    # ordering. Nothing may go above this line.
    # ---- THE PORT WAS THE WRONG QUESTION. 13 August 2026. ----
    #
    #     "i'm having 2 terminals only  1 - main.py & 2- collector.py"
    #
    # He had two terminals and THREE processes. A main.py from 07:30 had
    # outlived its window and was still running an hour later -- full
    # heartbeat, circuit monitor over 1,314 symbols, ranker every few
    # seconds -- with no window and no way to notice.
    #
    # This guard existed and did not fire, because it asked "is
    # something listening on port 8000?" and on WINDOWS a second socket
    # can bind over a listening one. The bind succeeds, the newer
    # process takes the port, and the probe a moment earlier saw
    # nothing. The second bot then owned the dashboard he was watching
    # while the first one traded invisibly.
    #
    # A port also answers the wrong question: the dashboard can be down
    # while the engine runs, which is exactly what the 07:30 process
    # was doing.
    #
    # core/single_instance.py asks the decisive one instead -- is that
    # pid still running, and is it still a main.py. See its docstring
    # for why core/runlock.py's age-based staleness is wrong here (a
    # session outlives its two-hour bar by design).
    busy, who = single_instance.held_by_another()
    if busy:
        warn("")
        warn("=" * 66)
        warn("  ANOTHER BOT IS ALREADY RUNNING.")
        warn("=" * 66)
        warn(f"  {who} is a live main.py on this machine.")
        warn("")
        warn("  Two bots on one Dhan account would BOTH place orders,")
        warn("  and whichever stops LAST overwrites the other's book.")
        warn("")
        warn("  Closing a terminal window does NOT stop it -- the")
        warn("  process keeps running with no window. Check with:")
        warn("      tasklist /FI \"IMAGENAME eq python.exe\"")
        warn("  and stop it with:")
        warn(f"      taskkill /PID {who.split()[1] if len(who.split()) > 1 else '<pid>'} /F")
        warn("")
        warn("  Refusing to start. Nothing was changed.")
        sys.exit(1)
    single_instance.claim()

    # ---- THE TOKEN, ONCE, HERE --------------------------------
    # 11 August 2026. If DHAN_TOTP_SECRET is set the bot mints its own
    # 24-hour token from Dhan and he never touches it again; if it is
    # not, or if the mint fails for any reason, this is exactly the
    # DHAN_ACCESS_TOKEN from .env and the morning runs as it always
    # has. See core/dhan_auth.py for why the API-key toggle is NOT the
    # automatic option it appears to be.
    #
    # This is BELOW the guard on purpose -- see the note up there.
    dhan_token = dhan_auth.access_token() or DHAN_ACCESS_TOKEN
    decision(dhan_auth.describe())

    if not DHAN_CLIENT_ID or not dhan_token:
        warn(
            "DHAN_CLIENT_ID / DHAN_ACCESS_TOKEN missing. "
            "Copy .env.example to .env and fill them in."
        )
        sys.exit(1)

    # ---- IT CHECKS ITSELF. 5 August 2026. ----
    #
    #   "py tools/dhan_token.py ?? & py tools/dry_run_live_path.py ?"
    #   "why i need to ask you ? why i need to mention to check this or
    #    that , run that , find out.???? & i cannot spoon feed
    #    everything right?"
    #
    # He is right. A tool he has to remember to run is a tool that gets
    # run on the days nothing is wrong. Every defect found on 5 August
    # was found because he asked.
    #
    # tools/dry_run_live_path.py walks all thirteen junctions -- token
    # expiry, static IP, master, ticks, both reason stores, the ranker,
    # the order path, positions AND holdings, the exits -- with a fake
    # broker. It places nothing and needs no market, so it costs a few
    # seconds at startup and nothing else.
    #
    # It REPORTS. It does not refuse: a junction this cannot see is
    # still possible, and a preflight that blocks the open on its own
    # false positive would be worse than the problem. The one thing
    # that genuinely cannot be automated is generating the token --
    # "out of bot scope = dhan tokens , nse related things i'll do
    # manually" -- so it says so, loudly, with the expiry time.
    try:
        from tools.dry_run_live_path import main_ as _preflight
        _preflight()
    except Exception as exc:                               # noqa: BLE001
        warn(f"[PREFLIGHT] The self-check could not run ({exc}). "
             f"Starting anyway -- but nothing has been verified.")

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

    # THE BANNER SAID "PAPER" ON A LIVE MORNING.
    #
    # 31 July 2026, first live session. The very first line of the
    # console read "(PAPER, equity only)" -- hardcoded when there was
    # only one mode -- while forty lines further down the same startup
    # printed "LIVE TRADING. Orders placed from here are REAL."
    #
    # The word at the top of the screen is the one glanced at all day.
    # It must be the truth, not a leftover.
    decision(f"Opportunity Trader -- Layer 1 "
             f"({str(TRADING_MODE).upper()}, equity only)")
    # Say WHERE this process is writing. One file per pid now, so there
    # must never be a question of which log to read -- the 2026-07-28
    # audit read a file three processes were tearing into and got three
    # findings wrong because of it.
    decision(f"[LOG] This session writes to {log_file_path()}")

    master_loader = MasterLoader()
    total = master_loader.load()
    decision(
        f"[MASTER_LOADER] Loaded {total} symbols from the verified "
        f"master database (data/master_stocks.csv)."
    )

    # SUBSCRIBE = YES only (core/subscribe_list.py). Stocks the morning
    # run marked NO -- T2T, ETFs, sub-Rs 200, illiquid, narrow price
    # band, going ex-split today, unclassified -- are excluded from the
    # FEED itself, not merely blocked at entry. That matters: a T2T name
    # on the feed still consumes a subscription slot and still lands in
    # the gainers/losers table, and a stock whose price scale changed
    # overnight would poison sector strength and the breadth regime read
    # with a fake -80%. They stay in master_loader for sector
    # lookups; they just never tick.
    blocked = master_loader.blocked_symbols()
    resolved = {
        symbol: master_loader.security_id(symbol)
        for symbol in master_loader.all_symbols()
    }
    if not resolved:
        warn("No universe symbols resolved. Nothing to trade. Exiting.")
        sys.exit(1)

    if master_loader.has_subscribe_column:
        decision(
            f"Universe resolved: {len(resolved)} subscribed, "
            f"{len(blocked)} marked NO by the morning run."
        )
    else:
        decision(f"Universe resolved: {len(resolved)} symbols.")
        warn(
            "No SUBSCRIBE column in data/master_stocks.csv -- every symbol "
            "is being subscribed, including any T2T names that cannot be "
            "traded intraday at all. Run 'py tools/morning_universe.py' "
            "before the open to build today's list."
        )

    # security_id -> symbol, the reverse of `resolved` above. Built
    # once, here, and reused by both the circuit monitor (below) and
    # the WebSocket feed's on_message handler (further down) -- one
    # source of truth for the mapping, not two copies drifting apart.
    security_id_to_symbol = {v: k for k, v in resolved.items()}

    market_data = MarketData()

    # THE BOOK'S CAPITAL COMES FROM THE BROKER IN LIVE.
    #
    # 31 July 2026. Portfolio() defaulted to config.PAPER_STARTING_
    # CAPITAL -- Rs 10,00,000 -- in BOTH modes, so the first live
    # dashboard showed ten lakh against an account holding a few
    # hundred rupees. available_capital gates sizing, so that is not a
    # display bug: the book would approve positions the account cannot
    # pay for, and each broker rejection would arrive mid-session
    # looking like a different fault.
    #
    # The Dhan client is built HERE, above the portfolio, rather than
    # thirty lines below where it used to be. Nothing else changed
    # about it -- DhanContext and the REST client are offline to
    # construct and no request leaves the machine until a method is
    # called. core/broker_funds.py makes exactly one call, and only
    # in LIVE.
    dhan_context = DhanContext(DHAN_CLIENT_ID, dhan_token)
    dhan_rest_client = DhanRestClient(dhan_context)
    portfolio = Portfolio(
        starting_capital=broker_funds.starting_capital(dhan_rest_client))

    # TWO CLIENTS, ON PURPOSE. See core/order_route.py.
    #
    #   dhan_rest_client   -- funds, quotes, circuit monitor.
    #                         Leaves over the HOME connection, because
    #                         reads need no static IP and because the
    #                         same machine must look residential to
    #                         NSE and the news sites.
    #
    #   dhan_order_client  -- orders only. Leaves via the static IP
    #                         that SEBI requires, when ORDER_PROXY is
    #                         configured.
    #
    # Identical objects when ORDER_PROXY is None, so a paper day and an
    # un-proxied live day behave exactly as before.
    dhan_order_client = DhanRestClient(
        DhanContext(DHAN_CLIENT_ID, dhan_token))
    order_route.route_orders_through(dhan_order_client, ORDER_PROXY)
    decision(f"[ROUTE] {order_route.describe(ORDER_PROXY)}")

    sector_monitor = SectorMonitor(market_data, master_loader)
    # TOP_N_MOMENTUM_MODE (config.py) -- wired in unconditionally,
    # same pattern as sector_monitor above: the object
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
    # Built above now, before the portfolio, because the book's opening
    # capital is read from this same client in LIVE. Re-binding it here
    # a second time would have been harmless but it would have made two
    # places look like the source of truth.
    circuit_monitor = CircuitMonitor(dhan_rest_client.quote_data, EXCHANGE_SEGMENT)

    # Clean-corpus recorder (2026-07-25) -- writes every closed candle
    # of this session to the replay bench's store, so the strategy can
    # be validated across many REAL sessions. Buffered + fail-safe; it
    # can never break tick processing. See core/candle_recorder.py.
    candle_recorder = None
    if ENABLE_CANDLE_RECORDING:
        candle_recorder = CandleRecorder()
        decision("[RECORDER] Recording this session's candles for replay.")

    # STOCK MEMORY (2026-07-25) -- what the bot KNOWS about each of the
    # 750 before it trades any of them. Refreshed from NSE/BSE corporate
    # actions at startup so a split/dividend ex-date is known BEFORE the
    # open, not discovered as a fake -80% crash (JLHL, 2026-07-24).
    # Entirely fail-open: a failed fetch just leaves the memory as-is.
    stock_memory = None
    if ENABLE_STOCK_MEMORY:
        try:
            stock_memory = StockMemory()
            corporate_actions.refresh(
                stock_memory, known_symbols=set(resolved.keys())
            )
        except Exception as exc:
            warn(f"[MEMORY] Stock memory unavailable this session: {exc}")
            stock_memory = None

    # LEARNING LOOP -- records every completed trade with the context
    # it was taken in. Observation only; nothing reads it back yet.
    trade_memory = None
    if ENABLE_TRADE_MEMORY:
        try:
            trade_memory = TradeMemory()
            decision(
                f"[LEARN] Trade memory active -- {trade_memory.count()} "
                f"past trades remembered."
            )
        except Exception as exc:
            warn(f"[LEARN] Trade memory unavailable this session: {exc}")

    # ---- Market calendar + results calendar -------------------------
    # Operator, 2026-07-26: the bot should know trading holidays, and
    # which stock reports on which date. Both are read ONCE here and
    # collapsed into plain in-memory structures -- no database touches
    # the tick path. Both fail open: an unreachable NSE just means the
    # bot knows nothing extra, which is exactly today's behaviour.
    earnings_calendar = dict(EARNINGS_CALENDAR)
    try:
        from core.market_calendar import refresh as refresh_calendar
        market_calendar = refresh_calendar()
        today = datetime.now().date()
        if not market_calendar.is_trading_day(today):
            # Operator, 2026-07-26: "Holiday = no trading of that day."
            # So EXIT, rather than starting a feed that will never tick.
            # Starting anyway would leave the dashboard up showing a
            # frozen, empty market and the console filling with feed-
            # staleness warnings -- an hour later you cannot tell that
            # from a real outage.
            why = market_calendar.reason(today)
            nxt = market_calendar.next_trading_day(today)
            decision(f"[CALENDAR] {today} is not a trading day ({why}). "
                     f"Next session: {nxt}. Nothing to do -- exiting.")
            # ---- IT EXITED WITHOUT SAYING HOW TO LOOK. 16 Aug 2026 ----
            #
            #     "py main.py started but it exited as today is non
            #      market day(weekend-sunday)"
            #
            # The exit is right and stays. The reasoning above -- "a
            # dashboard showing a frozen, empty market" -- was written
            # when the dashboard WAS the live movers table. It is not
            # any more: the Brain tab reads 14,000 stored events, Watch
            # is his own list, Post is the closed book, and none of
            # them needs a tick. He was sent to look at one and had no
            # way to get there.
            #
            # tools/dashboard_preview.py already serves exactly this
            # and has since it was written. It was simply never named
            # at the one moment he needs it.
            from dashboard.access_token import get_or_create_token
            from config import DASHBOARD_HOST as _H, DASHBOARD_PORT as _P
            decision("")
            decision("  To review stored data on a non-trading day:")
            decision("      py tools/dashboard_preview.py --no-fetch")
            decision(f"      http://{_H}:{_P}/board"
                     f"?token={get_or_create_token()}")
            decision("  Brain, Watch and Post work with the market shut.")
            decision("")
            sys.exit(0)
    except Exception as exc:
        warn(f"[CALENDAR] Market calendar unavailable ({exc}).")

    # Bound BEFORE the try. `results` is now also handed to the dashboard
    # 500 lines below, and if this block raises, the name would never
    # exist -- a NameError at startup, caused by a calendar refresh that
    # the bot is perfectly able to run without.
    results = None
    try:
        from core.results_calendar import refresh as refresh_results
        results = refresh_results(known_symbols=set(resolved))
        # Live NSE board meetings OVERLAY the hand-typed config dict --
        # union, not replacement, so a name typed in by hand is never
        # lost just because NSE's feed missed it.
        for day, symbols in results.as_calendar_dict().items():
            earnings_calendar[day] = set(
                earnings_calendar.get(day, ())) | set(symbols)
        reporting_today = earnings_calendar.get(
            datetime.now().date().isoformat(), ())
        if reporting_today:
            decision(f"[RESULTS] {len(reporting_today)} stock(s) report "
                     f"today -- no entries in them: "
                     + ", ".join(sorted(reporting_today)[:12])
                     + ("..." if len(reporting_today) > 12 else ""))
    except Exception as exc:
        warn(f"[RESULTS] Results calendar unavailable ({exc}). Falling "
             f"back to config.EARNINGS_CALENDAR only.")

    # Fresh Breakouts panel (2026-07-28). Records every structural
    # signal the engine produces -- including the ones it refuses -- so
    # the operator can see what the bot SAW, not just what it took.
    # Observation only: it never gates a trade.
    breakout_feed = BreakoutFeed()

    # Every structural signal, taken or refused, written to disk --
    # the Fresh Breakouts panel is memory only and dies at 15:30, so
    # six months of refused setups were deleted daily and the question
    # "are the real movers being ignored?" could never be answered.
    signal_journal = SignalJournal()

    # Operator's sizing rule (core/mtf_margin.py, 2026-07-28): a fixed
    # Rs 1 lakh of his OWN margin per position, share count falling out
    # of whatever margin Dhan requires for that stock. The rate is ASKED
    # of Dhan via /margincalculator with product_type="MTF" -- the same
    # figure his order screen shows -- never estimated from a table that
    # would go stale silently.
    #
    # If the client is missing or the call fails, sizing falls back to
    # own cash only: Rs 1 lakh buys Rs 1 lakh of stock. Under-leveraging
    # costs opportunity; over-leveraging on a bad number can trigger
    # Dhan's own liquidation.
    # RESULTS GATE (core/results_gate.py, 2026-07-28).
    #
    # Built EMPTY here, before the Engine, and its two feeds attached
    # further down once the announcement watcher and quarterly store
    # exist. NOT reordered: moving those constructions above the Engine
    # is exactly what caused "cannot access local variable 'quarterly'"
    # on 2026-07-28 and killed the whole filings feed on a day 65
    # companies reported.
    #
    # Until both feeds are attached it blocks every reporting stock --
    # the same behaviour as the old rule, which is the safe direction.
    results_gate = ResultsGate(earnings_calendar=earnings_calendar)

    # 2026-07-29: this said `dhan`, a name that does not exist anywhere
    # in this file. The REST client is dhan_rest_client, built at line
    # ~207. Every run therefore raised NameError, the except below
    # swallowed it, and the bot silently sized on OWN CASH with NO
    # LEVERAGE -- from the day the rule was written until it was caught
    # in the console output on 29 July:
    #
    #     WARNING: [MTF] Margin sizing unavailable
    #              (name 'dhan' is not defined)
    #
    # The operator's rule is Rs 1 lakh of MARGIN, which on COFORGE at
    # 1,686 is 225 shares and Rs 3.79 lakh of stock. What he actually
    # got was Rs 1 lakh of STOCK -- 57 shares. Roughly a quarter of the
    # intended position, every trade, for days.
    mtf_margin = None
    try:
        mtf_margin = MtfMarginBook(
            calculator=dhan_margin_calculator(dhan_rest_client,
                                              EXCHANGE_SEGMENT))
        decision("[MTF] Margin sizing active -- asking Dhan per stock, "
                 f"Rs {MTF_MARGIN_PER_POSITION_RS:,.0f} of margin per position.")
    except Exception as exc:                               # noqa: BLE001
        warn(f"[MTF] Margin sizing unavailable ({exc}). Positions will be "
             f"sized on own cash only -- no leverage.")
        mtf_margin = MtfMarginBook(calculator=None)

    engine = Engine(
        portfolio=portfolio, sector_monitor=sector_monitor,
        momentum_universe=momentum_universe, circuit_monitor=circuit_monitor,
        market_data=market_data, candle_recorder=candle_recorder,
        stock_memory=stock_memory, trade_memory=trade_memory,
        breakout_feed=breakout_feed, mtf_margin=mtf_margin,
        signal_journal=signal_journal,
        results_gate=results_gate,
        earnings_calendar=earnings_calendar,
        # 31 July 2026. THIS LINE IS THE WHOLE LIVE PATH.
        #
        # dhan_rest_client was built at the top of this function and
        # given to the circuit monitor and the MTF margin calculator.
        # It was never given to the Engine, so Execution() had no
        # broker and LIVE mode refused to start -- correctly, and for
        # the first time, on the morning it was first switched on.
        #
        # In PAPER this argument is ignored: trading/execution.py only
        # looks at it when TRADING_MODE is LIVE. Passing it always is
        # what stops the two modes from being different code paths
        # that get tested different amounts.
        dhan_client=dhan_order_client,
    )

    (
        saved_orb_ranges,
        saved_positions,
        saved_trailing_stops,
        saved_portfolio,
        saved_entry_blocks,
        saved_momentum_universe,
    ) = state_store.load()
    # The "feed went dark inside this symbol's own opening range" flag
    # (core/market_data.py). Restored SEPARATELY from the tuple above --
    # see state_store.load_orb_unreliable() for why. Without this, a
    # restart forgot which ranges were untrustworthy and the bot took
    # structural entries it had already refused that morning (TBZ,
    # 2026-07-27: flagged 09:16, bought 14:59).
    saved_orb_unreliable = state_store.load_orb_unreliable()
    if saved_orb_unreliable:
        market_data.load_orb_unreliable(saved_orb_unreliable)
        decision(
            f"[STATE] Restored {len(saved_orb_unreliable)} symbol(s) whose "
            f"opening range is unreliable -- no structural entries in them "
            f"today."
        )
    if saved_orb_ranges:
        engine.orb_engine.load_state(saved_orb_ranges)

    # TODAY'S CLOSED TRADES, restored 30 July 2026.
    #
    # Performance and Closed Trades are both built from
    # engine.closed_positions, which lived only in memory. Every restart
    # emptied them -- four on 30 July alone -- so the panel reported the
    # day as whatever had happened since the last restart, and looked
    # exactly like a quieter day rather than a truncated record.
    #
    # Date-guarded inside load_closed_positions(): yesterday's trades are
    # not today's performance.
    saved_closed = state_store.load_closed_positions()
    if saved_closed:
        engine.closed_positions.extend(saved_closed)
        decision(
            f"[STATE] Restored {len(saved_closed)} closed trade(s) from "
            f"earlier today -- the day's performance is not reset by a "
            f"restart."
        )
    # CARRY WHAT WE OWN ACROSS DAYS, 30 July 2026.
    #
    # config.FORCE_SQUARE_OFF_AT_CLOSE is False on purpose -- the operator
    # moved to MTF to hold for days, and square-off is MIS machinery that
    # closed TVSMOTOR and CUB on 28 July for exactly that reason. So the
    # bot HELD positions overnight, reported them loudly at 15:15... and
    # then state_store.load()'s date guard threw them away at the next
    # 09:00. Two halves of one feature, written on different days,
    # contradicting each other. In PAPER mode there is no broker to
    # reconcile against, so the positions simply stopped existing.
    #
    # load_holdings() reads the same file WITHOUT the date guard and can
    # only ever return what we own -- never an opening range, never the
    # momentum lock, never session counters. Those genuinely do expire at
    # midnight and their date guard is correct: yesterday's high is not
    # today's breakout level.
    if not saved_positions:
        carried, carried_stops, opened_on = state_store.load_holdings()
        if carried:
            saved_positions = carried
            saved_trailing_stops = saved_trailing_stops or carried_stops
            decision(
                f"[CARRY] Restored {len(carried)} position(s) held since "
                f"{opened_on} (MTF -- square-off is OFF). Opening ranges "
                f"and the momentum lock were NOT restored; those are "
                f"today's business."
            )
            for symbol, position in sorted(carried.items()):
                decision(f"[CARRY]   {symbol} {position.get('direction', '')} "
                         f"qty={position.get('qty')} "
                         f"entry={position.get('entry_price')}")
    if saved_positions:
        engine.load_positions(saved_positions)
    if saved_trailing_stops:
        engine.trailing_stop.load_state(saved_trailing_stops)
    if saved_portfolio:
        # ---- THE BROKER OWNS THE CAPITAL IN LIVE. 5 August 2026. ----
        #
        #   "dashboard is still showing paper mode - random pnl,
        #    margins"
        #
        # Line 339 asks Dhan and gets the truth -- Rs 2,64,395 on
        # 5 August, and the log says so. Then this line overwrote it
        # with whatever was in session_state.json: Rs 5,73,783 of
        # capital and Rs -6,324 of "realized P&L" that were left over
        # from paper running, and which never happened with real money.
        #
        # Restoring a saved BALANCE is only correct in PAPER, where the
        # file is the only record there is. In LIVE the broker is the
        # record and the file is a stale copy of it.
        if str(TRADING_MODE).upper() == "LIVE":
            keep = {"starting_capital": portfolio.starting_capital,
                    "available_capital": portfolio.starting_capital,
                    "realized_pnl": 0.0}
            restored = dict(saved_portfolio)
            restored.update(keep)
            portfolio.load_state(restored)
            decision(f"[FUNDS] Capital taken from Dhan "
                     f"(Rs {portfolio.starting_capital:,.2f}), not from the "
                     f"saved file. Realized P&L starts at zero for this "
                     f"session -- the broker's own book is the record.")
        else:
            portfolio.load_state(saved_portfolio)
        # RESTART SAFETY (2026-07-25): hand the engine the P&L already
        # realized earlier today so the daily loss/goal guardrails cover
        # the WHOLE session. Without this, a restart reset the counter to
        # zero and re-armed the loss switch -- the bot could lose its
        # full daily limit, restart, and lose it again.
        engine.seed_daily_pnl(getattr(portfolio, "realized_pnl", 0.0))

    # A deliberate "stop new entries" must survive a restart -- a crash
    # or reconnect should never silently resume trading (2026-07-25).
    if engine.trade_controller.restore_pause_state():
        warn(
            "[PAUSED] New entries are STILL PAUSED from an earlier "
            "session. Click Resume on the dashboard to start trading."
        )
    if saved_entry_blocks:
        engine.load_entry_blocks(saved_entry_blocks)
    if saved_momentum_universe:
        momentum_universe.load_state(saved_momentum_universe)

    # 2026-07-29: rotation count and the already-announced news
    # set. Without these a mid-session restart gave the bot five
    # fresh swaps and re-announced every filing it had already
    # reported.
    engine.load_session_counters(state_store.load_session_counters())
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

    # ---- MAKE DHAN'S RESTING STOPS MATCH WHAT WE ACTUALLY HOLD ----
    #
    # 2 August 2026. This is the exact moment trading/broker_stop.py
    # cannot trust its own memory: the process has just started, so its
    # record of resting orders is empty -- while Dhan's is not.
    #
    # Two things go wrong if this does not run, and the second is the
    # dangerous one:
    #
    #   a position with no resting stop   the crash we restarted from
    #                                     left it unprotected
    #   a resting stop with no position   it will SELL stock that is
    #                                     not held. On MTF that is a
    #                                     short nobody asked for.
    #
    # It cancels only orders carrying our own tag. A Forever Order the
    # operator placed by hand in the Dhan app is reported and left
    # alone -- this bot does not reach into his account and remove a
    # protection he set himself.
    if getattr(engine, "broker_stop", None) is not None \
            and engine.broker_stop.enabled:
        try:
            from config import HARD_STOP_FROM_ENTRY_PCT
            from trading.broker_stop import hard_stop_price
            engine.broker_stop.reconcile(
                engine.open_positions,
                hard_stop_for=lambda _s, pos: hard_stop_price(
                    pos.get("entry_price"), pos.get("direction", "LONG"),
                    HARD_STOP_FROM_ENTRY_PCT),
            )
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] Startup reconcile failed ({exc}). "
                 f"Whether anything is protected at Dhan is UNKNOWN -- "
                 f"check the terminal before trading.")

    # Mutable holder, not a plain variable -- the feed thread gets
    # REPLACED on reconnect (the watchdog below does
    # `feed, feed_thread = start_feed()` again), and this lambda is
    # handed to DashboardState/system-health BEFORE that thread even
    # exists yet (dashboard_state is built before start_feed() runs
    # for the first time below). A dict box means the closure always
    # reads whatever the CURRENT thread is at refresh time, not
    # whatever existed at construction time.
    feed_state = {"thread": None}

    # Index monitor (Nifty/BankNifty/Midcap/VIX) built here so the
    # dashboard can read it; the feed subscription for it is added to
    # `instruments` further below. See core/index_monitor.py.
    # ---- THE DICT WAS BEING FLIPPED. 3 August 2026. ----
    #
    # config.INDEX_INSTRUMENTS is {security_id: name} -- "13": "nifty".
    # IndexMonitor's own docstring asks for exactly that:
    #
    #     "id_to_name: {security_id (str) -> dashboard name}"
    #
    # This comprehension read `for name, sec_id in ...items()`, which
    # names the KEY "name" and the VALUE "sec_id" -- so it handed the
    # monitor {"nifty": "13"}, backwards. Every lookup by security id
    # missed, and the subscribe below asked the feed for an instrument
    # whose id was the string "nifty".
    #
    # Nothing ever errored. The tiles simply said "needs index feed"
    # forever, which was then diagnosed twice as wrong security ids --
    # and the ids were emptied out of config both times.
    index_monitor = IndexMonitor(
        dict(INDEX_INSTRUMENTS)
    ) if ENABLE_INDEX_FEED else None
    index_ids = index_monitor.index_security_ids() if index_monitor else set()
    # COLLISIONS ARE EXPECTED AND HARMLESS NOW. 2026-07-30.
    #
    # This block used to REFUSE any index id that also existed as an
    # equity, because the router keyed on the id alone and a collision
    # silently deleted that stock from the bot -- ABB (13) and ADANIENT
    # (25) produced no candles at all on 2026-07-28.
    #
    # The router now keys on (segment, id), so IDX_I 13 and NSE_EQ 13 are
    # different instruments and both are handled correctly. Refusing the
    # id is no longer a safety measure -- it is a bug, because 13 and 25
    # are NIFTY 50 and NIFTY BANK, the two most important tiles on the
    # panel, and ABB and ADANIENT are permanent members of this universe.
    # Keeping the old guard would mean those two indices could never be
    # configured at all.
    #
    # So the overlap is now reported once, as information, and nothing is
    # dropped. If a tile ever shows a stock's price again, this line is
    # the first place to look -- but the routing test in
    # tests/test_index_monitor.py should fail long before that.
    _equity_ids = {str(v) for v in resolved.values()}
    _collisions = {i for i in index_ids if str(i) in _equity_ids}
    if _collisions:
        shared = sorted(f"{i}={security_id_to_symbol.get(str(i), '?')}"
                        for i in _collisions)
        decision(f"[INDEX] Index ids also present as equities: "
                 f"{', '.join(shared)}. Handled -- the tick router keys "
                 f"on (segment, id), so these are distinct instruments.")

    # Live announcements, 2026-07-27 (core/announcement_watcher.py).
    # Before this, the results calendar was refreshed ONCE at startup and
    # never again -- Canara Bank filed around noon and at 13:50 the bot
    # still had no idea. TMB did 98% of its volume and its whole +12.1%
    # after 13:00 that same day. A once-a-day read cannot see any of it.
    #
    # Own daemon thread, never the tick path. Its output feeds two
    # readers: the shortlist (a stock that filed 20 minutes ago jumps to
    # the top with the reason attached) and the dashboard panel.
    #
    # A RESULTS filing is handed straight to core/results_ingest.py,
    # which downloads the attached PDF and reads the statement out of it.
    # That PDF is the ONLY source with the figures: the announcement text
    # carries none (seven real filings on 2026-07-27 averaged 130
    # characters of boilerplate), and bse.resultsSnapshot lags by hours
    # and gives no year-ago quarter. The PDF has all three quarters at
    # full precision -- verified against MOLD-TEK's Q1 FY27 filing, whose
    # table this parser reads as +26.31% QoQ sales while page 1 of the
    # same document says 26.32% in prose.
    # Quarterly numbers (core/quarterly_results.py), 2026-07-27. The
    # calendar knows WHO reports, the watcher knows a filing LANDED --
    # this is the only one that knows whether the numbers were better.
    # KFINTECH (+9.2%) and ACUTAAS (-Rs 1,593 for us) both filed that
    # week; nothing else in the bot could tell them apart.
    #
    # Read-only here. Populated by tools/fetch_quarterly.py, so an empty
    # store just means the shortlist shows no grade -- never a failure.
    #
    # MUST BE BUILT BEFORE the announcement watcher: the ResultsIngestor
    # writes into it. Ordered the other way round on 2026-07-28 and the
    # whole filings feed died at startup with "cannot access local
    # variable 'quarterly'" -- on a day 65 companies were reporting.
    quarterly = None
    try:
        from core.quarterly_results import QuarterlyResults
        quarterly = QuarterlyResults()
        decision(f"[FINANCIALS] {quarterly.count()} quarters on record "
                 f"across {len(quarterly.symbols())} symbols.")
    except Exception as exc:                               # noqa: BLE001
        warn(f"[FINANCIALS] Quarterly store unavailable ({exc}). The "
             f"shortlist will show events without their numbers.")

    # ---- READS THE FILINGS. DOES NOT FETCH THEM. 3 August 2026. ----
    #
    #     "why still NEWS is printing in main.py terminal ? ... in live
    #      markets only 2 terminals - main.py & news"
    #     "PLS DO NOT COMBINE MAIN.PY"
    #
    # This took days longer than the Telegram split for one reason:
    # Telegram already had a database. AnnouncementWatcher kept
    # `self._today` in memory, so moving the polling out would have
    # taken the DATA with it -- and results_gate reads this to decide
    # whether 83 reporting stocks may be traded. Not a blank panel; the
    # trading loop losing an input it gates on.
    #
    # core/feed_store.py is that database now. The collector polls NSE
    # and writes; this process opens the same file read-only and every
    # caller downstream -- results_gate, the engine, the dashboard --
    # sees the same three methods it always saw.
    announcement_watcher = None
    results_ingestor = None
    if ENABLE_ANNOUNCEMENT_WATCHER:
        try:
            from core.feed_store import StoredAnnouncements
            announcement_watcher = StoredAnnouncements()
            decision(f"[FILINGS] (pid {os.getpid()}) Reading "
                     f"{announcement_watcher.store.count('announcement')} "
                     f"stored filing(s). This process does NOT fetch them.")
        except Exception as exc:                           # noqa: BLE001
            warn(f"[NEWS] Filing store unreadable ({exc}). "
                 f"The shortlist will fall back to the results calendar.")
            announcement_watcher = None

    # Attach the results gate's two feeds now that both exist. Until
    # this point it blocks every reporting stock; from here it can tell
    # "reports today, numbers not out yet" (block) from "filed and
    # graded STRONG" (allow -- the trade the whole strategy is about).
    results_gate.announcements = announcement_watcher
    results_gate.quarterly = quarterly

    # The learning loop's REASON columns (2026-07-28). Same two feeds,
    # attached to the engine read-only: at every entry it stamps what
    # was KNOWN about the stock at that moment, so "does a reason beat
    # no reason" can finally be measured instead of argued.
    # Observation only -- none of this gates a trade.
    engine.announcements = announcement_watcher
    if announcement_watcher is not None and quarterly is not None:
        decision("[RESULTS_GATE] Live -- a reporting stock is blocked "
                 "until its numbers land, then allowed only if they are "
                 "STRONG or GOOD.")
    else:
        warn("[RESULTS_GATE] Feeds missing -- every reporting stock will "
             "be blocked today, same as the old rule.")

    # High-conviction news (core/news_watcher.py). Filings are not the
    # whole story -- on 2026-07-27 the day's two biggest moves, GANDHAR
    # -11.6% (plant flood) and CARTRADE +10.8% (UBS initiation), were
    # both invisible to a filings-only feed.
    # Read, not fetched -- same split as the filings above. The RSS
    # polling lives in tools/collector.py with the nine channels.
    news_watcher = None
    if ENABLE_NEWS_WATCHER:
        try:
            from core.feed_store import StoredNews
            news_watcher = StoredNews()
            decision(f"[NEWSFEED] (pid {os.getpid()}) Reading "
                     f"{news_watcher.store.count('news')} stored item(s). "
                     f"This process does NOT poll the feeds.")
        except Exception as exc:                           # noqa: BLE001
            warn(f"[NEWSFEED] News store unreadable ({exc}).")
            news_watcher = None

    # Second half of the reason capture -- news, alongside the filings
    # attached above. With both wired the engine can stamp
    # "news:ORDER_WIN, filed:RESULTS, results:STRONG" onto a trade at
    # the moment it opens.
    engine.news_feed = news_watcher
    if news_watcher is not None or announcement_watcher is not None:
        decision("[LEARN] Reason capture live -- every trade now records "
                 "WHY it was taken, not just what it made.")
    else:
        warn("[LEARN] No news or filings feed -- trades will record "
             "had_reason=0 for everything, and the reason study cannot "
             "start.")

    # FII/DII (core/market_flows.py). NSE publishes these once, after
    # the close, so this is always about a COMPLETED session -- context,
    # never a trigger. Fetched on its own thread so a slow NSE response
    # cannot delay startup.
    # % change everywhere now measured vs PREVIOUS CLOSE, like NSE.
    # circuit_monitor's REST snapshot is the single source of prev_close
    # the dashboard already uses; handing it to these two makes every
    # number on the screen agree with NSE and with each other.
    sector_monitor.set_snapshot_provider(engine.get_circuit_snapshot)
    momentum_universe.set_snapshot_provider(engine.get_circuit_snapshot)

    market_flows = MarketFlows()
    threading.Thread(target=market_flows.refresh, name="flows",
                     daemon=True).start()

    # Overnight world + NSE pre-open. Both were built as standalone
    # tools; from 29 July they also feed the dashboard. Neither can
    # block a trade -- a failed fetch means an empty panel.
    from core.premarket import PreMarket
    from core.preopen import PreOpen
    from core.nse_quotes import requests_fetcher as nse_fetcher
    try:
        premarket = PreMarket(fetcher=None)      # reads what the 08:45 run stored
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[PREMARKET] Not available ({exc}).")
        premarket = None
    try:
        preopen = PreOpen(fetcher=None)          # reads what the 09:12 run stored
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[PREOPEN] Not available ({exc}).")
        preopen = None

    # Which stocks are in NIFTY 50 and which are in F&O, so the
    # pre-open group buttons filter for real. Read from the disk cache
    # here and NEVER fetched during the session -- membership changes
    # twice a year and the pre-open window is twelve minutes long.
    # `py tools/index_members.py` refreshes it.
    try:
        from core.index_members import IndexMembers
        index_members = IndexMembers()
        status = index_members.status()
        if status["counts"]:
            decision(f"[INDEX] Membership: {status['counts']} "
                     f"(as of {status['fetched_at']}).")
        else:
            warn("[INDEX] No index membership on disk -- the NIFTY 50 "
                 "and F&O pre-open buttons will not appear. Fix with: "
                 "py tools/index_members.py")
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[INDEX] Not available ({exc}).")
        index_members = None

    # The operator's four Telegram channels, on the dashboard instead
    # of a second screen. Optional in every direction: no telethon, no
    # credentials or no login and this is None, the panel says so, and
    # nothing else is affected. READ ONLY -- see
    # dashboard/state.py's build_telegram() for why it stops at the
    # screen and never reaches the engine.
    # News -> which stocks it touches.
    #
    # ---- THIS LINE SAID "ON" FOR A WEEK WHILE IT WAS OFF. ----
    #      12 August 2026.
    #
    # It printed "OFF (no API key)" as the only failure it knew about,
    # and asked status()["reasoning_on"], which only checked the key.
    # The real blocker was config.AI_ENABLED = False -- switched off on
    # 10 August after every call returned "credit balance is too low".
    # Key present, switch off, so this printed ON every morning.
    #
    # Measured: 6-11 August reasoned 0 of 1,561 stories. Every link in
    # that window is a keyword match with direction UNKNOWN, and
    # core/ranker.py refuses those outright ("reason is a lookup, not a
    # mechanism"). The ranked lane went a week with no reasons while
    # the startup log said the reasoning was running.
    #
    # It now names the blocker, because "OFF" without a cause sends him
    # looking for the wrong thing -- the key was never the problem.
    #
    # (The comment here also pointed at tools/news_impact_backfill.py
    # "once the key exists". That tool has never existed. The reasoning
    # is inline in NewsImpact.record(); nothing backfills.)
    news_impact = None
    try:
        from core.news_impact import NewsImpact
        news_impact = NewsImpact(master_loader=master_loader)
        status = news_impact.status()
        if status.get("reasoning_on"):
            decision(f"[IMPACT] {status['news']} stories, "
                     f"{status['links']} stock links, "
                     f"{status['reasoned']} reasoned. Reasoning ON.")
        else:
            warn(f"[IMPACT] {status['news']} stories, {status['links']} "
                 f"stock links -- REASONING OFF. "
                 f"{status.get('blocked_by') or ''} "
                 f"Stories are stored and linked by keyword, so the "
                 f"ranker will refuse them as 'a lookup, not a "
                 f"mechanism'.")
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[IMPACT] Not available ({exc}).")

    def _optional_morning_brief():
        """core/morning_brief.py, or None. Never raises -- an absent
        briefing must not stop a trading session starting."""
        try:
            from core.morning_brief import MorningBrief, anthropic_client
            client = anthropic_client()
            if client is None:
                decision("[BRIEF] No ANTHROPIC_API_KEY -- the morning brief "
                         "panel will say so. Nothing else is affected.")
            return MorningBrief(client=client)
        except Exception as exc:                               # noqa: BLE001
            warn(f"[BRIEF] Not available ({exc}).")
            return None

    # ================================================================
    # TELEGRAM DOES NOT LIVE HERE ANY MORE.  3 August 2026
    # ================================================================
    #
    #   "TODAY WORK BELONGS TO TELEGRAM REPAIR & KEEPING MAIN.PY AS
    #    STANDALONE RUN + REMAINING RUN IN OTHER TERMINALS ......
    #    PLS DO NOT COMBINE MAIN.PY"
    #                                       -- operator, 3 August 2026
    #
    # He asked for this repeatedly before the first live session and I
    # kept it inside main.py. Everything that went wrong that morning
    # came from that one decision:
    #
    #   08:19  nightly's telegram step reported "ok 0.0 min" and read
    #          nothing -- the lock detected its own process
    #   08:51  main.py started; its 96-hour catch-up walked channel 2
    #          of 9 at 3.5 min a page, with the market opening at 09:15
    #   08:55  the catch-up skipped, the first poll's AI grading then
    #          blocked startup for another twelve minutes
    #   09:03  the Telethon client, connected on the MAIN thread, was
    #          used by the POLLER thread and refused: "the asyncio
    #          event loop must not change after connection". All nine
    #          channels dead for the whole session.
    #
    # Four failures, one cause: a chat reader sharing a process, a
    # thread and a startup sequence with a trading engine. None of it
    # is Telegram's fault and none of it belongs in front of a tick
    # feed.
    #
    # So main.py now READS events and never collects them. It opens no
    # Telethon session, holds no reader lock, runs no OCR, spends
    # nothing on grading, and cannot be delayed by any of it.
    #
    #     Terminal 1:  py main.py             trading
    #     Terminal 2:  py tools/collector.py  Telegram
    #
    # The two share data/stock_events.db and nothing else. The
    # collector is the only writer. If it dies, the chips stop
    # updating and not one thing about the trading loop changes.
    events_store = None
    try:
        from core.stock_events import StockEvents
        events_store = StockEvents()
        status = events_store.status()
        decision(f"[EVENTS] (pid {os.getpid()}) Reading "
                 f"{status.get('total', 0)} stored event(s). "
                 f"This process does NOT collect them.")
        decision("[EVENTS] Run the collector in its own terminal: "
                 "py tools/collector.py")
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[EVENTS] Event store unreadable ({exc}). Chips will be "
             f"empty; trading is unaffected.")

    # ---- A READER, NOT A COLLECTOR. 3 August 2026. ----
    #
    #     "PLS DO NOT COMBINE MAIN.PY"
    #     "FII/DII = news pulse"
    #
    # Setting this to None kept main.py standalone and also switched off
    # every READ of what the collector had already written. FII/DII is
    # posted by News Pulse and stored in data/telegram.db, and the
    # dashboard's flow panel falls back to from_telegram() -- which was
    # being handed None and returning None, every second, all session.
    # That is why the tile has been empty since the split.
    #
    # TelegramFeed(client=None) starts no client, joins no channel and
    # writes nothing. recent() is a SELECT. It is the same arrangement
    # as StockEvents above: the collector is the only writer, this
    # process only reads, and if the collector dies the numbers stop
    # updating and the trading loop is untouched.
    telegram = None
    try:
        from core.telegram_feed import TelegramFeed
        telegram = TelegramFeed(client=None)
        decision(f"[TELEGRAM] (pid {os.getpid()}) Read-only view of "
                 f"data/telegram.db. This process does NOT collect.")
    except Exception as exc:                                   # noqa: BLE001
        warn(f"[TELEGRAM] Store unreadable ({exc}). FII/DII and the "
             f"message panel will be empty; trading is unaffected.")
        telegram = None

    dashboard_state = DashboardState(
        engine, market_data, master_loader,
        portfolio=portfolio, sector_monitor=sector_monitor,
        index_monitor=index_monitor,
        announcement_watcher=announcement_watcher,
        quarterly_results=quarterly,
        news_watcher=news_watcher,
        market_flows=market_flows,
        # 2026-07-29 -- "everything that bot knows must shown in
        # dashboard". These three were built and never reachable from
        # the screen: the operator's own trade history per stock, the
        # 18 overnight world numbers, and NSE's pre-open book.
        trade_memory=trade_memory,
        premarket=premarket,
        preopen=preopen,
        index_members=index_members,
        telegram=telegram,
        news_impact=news_impact,
        # Overnight brief -- OPINION, recorded, never acted on. None
        # without ANTHROPIC_API_KEY, and the panel says so.
        morning_brief=_optional_morning_brief(),
        # Who reports today. Loaded at startup since the beginning and
        # used by the shortlist, but never a panel of its own until the
        # operator asked for "Results, Corporate actions of the day".
        results_calendar=results,
        # The same REST quote the circuit monitor already uses. Fills
        # NIFTY, BANKNIFTY, VIX and the sector tiles with the last
        # close BEFORE 09:15 -- the tick feed has not spoken yet and
        # the tiles used to read "no feed" through the whole hour he
        # spends deciding. 4 August 2026.
        index_quote=dhan_rest_client.quote_data,
        # 183 dividends/splits/demergers with ex-dates. Wired into
        # main.py since the start, never handed to the dashboard --
        # so a veto the bot applies was invisible to the operator.
        stock_memory=stock_memory,
        get_feed_alive=lambda: (
            feed_state["thread"].is_alive() if feed_state["thread"] else None
        ),
    )

    def on_accepted_tick(symbol, price, tick_time, cum_volume=None):
        # ---- WHICH SUBSCRIPTIONS ARE ACTUALLY ALIVE. 8 Aug 2026 ----
        # 19 stocks are subscribed with ids Dhan itself confirmed and
        # have never stored a single bar -- MOTHERSON traded 115 million
        # shares on 7 August and our tape has nothing. Nothing offline
        # can separate "Dhan never sent it" from "we dropped it", so
        # core/feed_watch.py measures it live and says so at 09:45.
        feed_watch.saw(resolved.get(symbol))
        engine.process_tick(
            symbol, resolved[symbol], price, tick_time, cum_volume
        )
        feed_watch.report(resolved, now=tick_time)

    market_data.on_new_tick(on_accepted_tick)

    # dhan_context/security_id_to_symbol were already built above,
    # alongside circuit_monitor -- reused here for the WebSocket feed,
    # not rebuilt.
    # 2026-07-24 (evening) Change 2 -- QUOTE mode instead of Ticker so
    # each message carries day-cumulative "volume" (Ticker mode is
    # LTP/LTT only). Quote still delivers LTP and LTT unchanged, so
    # everything downstream keeps working; we just additionally read
    # volume for the breakout volume-surge filter. NOTE: this feed-mode
    # change can't be validated offline -- needs a live smoke-test.
    # The volume path is fail-open end to end, so if Quote somehow
    # doesn't deliver volume, the filter simply does nothing.
    instruments = [
        (MarketFeed.NSE, security_id, MarketFeed.Quote)
        for security_id in resolved.values()
    ]

    # 2026-07-24 -- Market indices (Nifty / BankNifty / Midcap / India
    # VIX) on the IDX segment, in FULL mode so we get both LTP and a
    # prev-close packet to compute % change. Kept OUT of the stock
    # pipeline entirely (see on_message routing below). Fail-open: a
    # wrong id just never populates its tile. index_monitor was built
    # up near DashboardState so the dashboard can read it.
    if index_monitor:
        # .keys(), not .values(). See the comment on IndexMonitor above:
        # this asked the feed to subscribe to instruments called "nifty"
        # and "banknifty", which are names, not security ids. The feed
        # accepted them without complaint and delivered nothing.
        index_subs = sorted(INDEX_INSTRUMENTS.keys())
        instruments += [
            (MarketFeed.IDX, sec_id, MarketFeed.Full)
            for sec_id in index_subs
        ]
        # SAY IT. A subscription that silently delivers nothing is what
        # kept these tiles blank for a week, through two wrong
        # diagnoses. If the count here is right and the tiles are still
        # empty, the problem is downstream of this line -- which is
        # worth knowing in one glance rather than one evening.
        decision(f"[INDEX] Subscribed {len(index_subs)} index/indices on "
                 f"the IDX segment: {', '.join(index_subs)}")

    # ==========================================================
    # 2026-07-24 revamp -- tick RECEIVING decoupled from tick
    # PROCESSING (root fix for ISSUES_LOG #13, the SONACOMS false
    # breakout). Before this, on_message() ran the ENTIRE pipeline
    # (candle building, ORB update, every entry gate) synchronously
    # on the same thread that reads the WebSocket -- at 09:15:00,
    # when ~750 symbols post their opening trade within a second or
    # two, that single thread fell 15-30s behind and 646 symbols
    # went "stale" in one minute, with real prices lost inside the
    # gap. Now on_message() ONLY parses and enqueues (microseconds),
    # so the socket reader is always ready for the next frame, and a
    # single dedicated worker drains the queue in strict arrival
    # order -- same sequential, single-threaded engine processing as
    # before (no new engine-side thread-safety burden), just no
    # longer blocking the socket.
    #
    # received_at is captured AT ENQUEUE and passed as on_tick()'s
    # now= -- staleness then measures DELIVERY lag (feed -> us),
    # which is the real data-integrity signal, not processing
    # backlog (a queued-but-delivered tick is late, not lost --
    # candles/ORB key off the tick's own exchange timestamp anyway).
    # ==========================================================
    tick_queue = queue.Queue()

    # One-shot latch for the field dump below. A list because the
    # handler is a closure and must not need a `global`.
    _packet_keys_logged = []

    def _route_index_packet(security_id, message):
        """Everything that happens to an IDX_I packet, and nothing else
        ever touches it.

        Called only when is_index_segment(message) is true, so a stock
        can never arrive here however its id numbers out.
        """
        if not index_monitor.owns(security_id, message):
            # An IDX packet whose id is not in INDEX_INSTRUMENTS. Logged
            # with its LEVEL, because the level is what identifies an
            # index by eye -- Nifty near 24,000, BankNifty near 52,000,
            # VIX between 8 and 20. This is how the real ids get
            # confirmed instead of guessed a third time.
            #
            # It must NOT fall through to the stock pipeline. Before the
            # segment check existed it did, so an unconfigured IDX id
            # that collided with a stock id would have written an INDEX
            # LEVEL into that stock's candles -- the same collision as
            # the ABB bug, running the other way.
            index_monitor.note_unknown(security_id, message)
            return

        # Dhan names the previous close differently by packet type --
        # "close_price" on a Full packet, "prev_close" elsewhere.
        # Reading only one of them left every index tile showing
        # "needs index feed" all through 2026-07-27 even though ticks
        # were arriving. Try each in turn.
        def _num(*keys):
            for k in keys:
                v = message.get(k)
                if v not in (None, "", 0):
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
            return None

        ltp = _num("LTP", "ltp", "last_price", "LTP_price")
        # Dhan's Quote packet calls the previous close "close".
        pc = _num("close", "close_price", "prev_close",
                  "prev_close_price", "previous_close")
        index_monitor.on_index_tick(security_id, ltp=ltp, prev_close=pc)
        index_monitor.note_packet(security_id, message)

    def on_message(_instance, message):
        try:
            security_id = str(message.get("security_id"))

            # ==================================================
            # SEGMENT FIRST, THEN ID. 2026-07-30.
            # ==================================================
            # Index security ids and equity security ids are separate
            # numbering spaces and they collide:
            #
            #   IDX_I 13 = NIFTY 50      NSE_EQ 13 = ABB INDIA
            #   IDX_I 25 = NIFTY BANK    NSE_EQ 25 = ADANI ENTERPRISES
            #
            # This used to read `if security_id in index_ids:` and ran
            # BEFORE the symbol lookup, so on 2026-07-28 every ABB and
            # ADANIENT tick was captured by the index monitor and
            # returned early. Both were subscribed, both were in the
            # universe, and neither produced one candle, opening range or
            # gainers row all session. Nothing errored.
            #
            # An INDEX packet never reaches the stock pipeline, and a
            # STOCK packet never reaches the index monitor, whatever the
            # ids happen to be. See core/index_monitor.py.
            if index_monitor is not None and is_index_segment(message):
                _route_index_packet(security_id, message)
                return

            symbol = security_id_to_symbol.get(security_id)
            if symbol is None:
                return

            # ONE-TIME FIELD DUMP, 30 July 2026. The operator asked
            # "what all info we are getting & we really using them" and
            # nobody could answer it from the code: this handler reads
            # LTP, LTT and volume, and whatever else the Quote packet
            # carries has never been written down. Logged once per
            # session, for the first real stock packet only, so the
            # answer is a fact in the log instead of a guess.
            if not _packet_keys_logged:
                _packet_keys_logged.append(True)
                try:
                    used = {"LTP", "LTT", "volume"}
                    keys = sorted(message.keys())
                    decision(f"[FEED] Quote packet fields: {keys}")
                    spare = [k for k in keys if k not in used
                             and k not in ("security_id", "exchange_segment",
                                           "type")]
                    if spare:
                        decision(f"[FEED] Arriving but UNUSED: {spare} "
                                 f"-- sample: "
                                 f"{ {k: message.get(k) for k in spare[:6]} }")
                except Exception:                          # noqa: BLE001
                    pass

            price = float(message.get("LTP", 0) or 0)
            if price <= 0:
                return

            # ---- THE EXCHANGE'S OWN OHLC, OFF THE TICK. 10 Aug ----
            #
            #     "i want our bot must work aligned with NSE website in
            #      calculating gap , down, %'s."
            #
            # Every Quote packet carries close / open / high / low, and
            # `close` is the PREVIOUS close -- the exact denominator NSE
            # uses. The startup banner has printed them as "Arriving but
            # UNUSED" every session while circuit_monitor polled REST
            # for the same four numbers.
            #
            # This only REMEMBERS them, and core/tick_ohlc.py measures
            # the two sources against each other. Nothing is replaced
            # until the drift is a number rather than my opinion.
            tick_ohlc.remember(symbol, message)

            ltt_raw = message.get("LTT")
            tick_time = parse_ltt_to_ist(ltt_raw) or datetime.now()

            # Change 2: day-cumulative volume from Quote mode. Missing
            # / unparseable -> None, and the whole volume path fails
            # open, so a bad or absent value never affects trading.
            try:
                cum_volume = message.get("volume")
                cum_volume = int(cum_volume) if cum_volume is not None else None
            except (TypeError, ValueError):
                cum_volume = None

            tick_queue.put((symbol, price, tick_time, datetime.now(), cum_volume))

        except Exception as e:
            warn(f"Tick handling error: {e}")

    def _tick_worker(stop_event):
        """Drains tick_queue sequentially -- the ONE thread that
        drives market_data/engine, exactly the role the feed thread
        itself played before the 2026-07-24 decoupling. A per-tick
        exception is logged and skipped (one bad tick must never
        kill the whole processing loop -- the old inline try/except
        gave the same guarantee)."""
        while not stop_event.is_set():
            try:
                symbol, price, tick_time, received_at, cum_volume = tick_queue.get(
                    timeout=1.0
                )
            except queue.Empty:
                continue
            try:
                market_data.on_tick(
                    symbol, price, tick_time, now=received_at,
                    cum_volume=cum_volume,
                )
            except Exception as e:
                warn(f"Tick processing error ({symbol}): {e}")

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

    # Declared before start_feed() so the receive loop can tell a
    # shutdown reset from a mid-session one -- see _run() below.
    stop_event = threading.Event()

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
        def _run():
            """feed.run() with the shutdown reset swallowed.

            WinError 10054 -- "An existing connection was forcibly
            closed by the remote host" -- lands here every time the
            process stops. It is not an error: the bot closes the
            socket, Dhan's end notices, and the SDK's receive loop
            surfaces the reset as an unhandled exception on a daemon
            thread. Python then prints a full traceback during
            shutdown, which is the last thing on screen and looks
            exactly like a crash.

            Two different meanings need two different treatments:

              stopping   the reset is expected. Say one quiet line.
              running    the watchdog below restarts the feed within
                         five seconds, and that IS worth a warning.
            """
            try:
                feed.run()
            except (ConnectionResetError, OSError) as exc:
                if stop_event.is_set():
                    diagnostic(f"[FEED] Socket closed during shutdown "
                               f"({type(exc).__name__}). Expected.")
                else:
                    warn(f"[FEED] Connection lost mid-session: {exc}. "
                         f"The watchdog will restart the feed.")
            except Exception as exc:                       # noqa: BLE001
                # Anything else is genuinely unexpected and must not be
                # swallowed silently -- but it still must not print a
                # bare traceback from a daemon thread.
                warn(f"[FEED] Receive loop stopped: "
                     f"{type(exc).__name__}: {exc}")

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return feed, thread

    # The tick-processing worker (see _tick_worker's docstring above)
    # -- started BEFORE the feed so no early tick ever sits in the
    # queue with nothing draining it.
    tick_worker_thread = threading.Thread(
        target=_tick_worker, args=(stop_event,), daemon=True
    )
    tick_worker_thread.start()

    reader_thread = threading.Thread(
        target=_command_reader, args=(engine, stop_event), daemon=True
    )
    reader_thread.start()

    def _print_dashboard_banner():
        """SAY WHERE IT IS, and say it once.

        ---- ONE LINK, COMPLETE. 4 August 2026. ----
            "why can't bot print the complete link ?"
            "only one universal screen required for now"

        ---- IT NAMED THE WRONG PAGE. 12 August 2026. ----
        For two days this printed:

            BOARD  (one table, Pre/Live/Post) :  .../board
            OLD    (all panels, fallback)     :  .../?token=...

        Then I "fixed" it to print "/" instead, having decided app.html
        was the newest page because its FILE TIMESTAMP was the most
        recent -- which it was only because I had spent the afternoon
        editing it. The route docstrings say the opposite:

            app.html    "The React screen. 6 August 2026."
            board.html  "ONE table. 9 August 2026."   <- the newer one

        board.html reads fewer snapshot fields ON PURPOSE -- "one
        verdict not six chips", "no more top 50/20/10 gainers tables".
        I counted fields and called his design incompleteness.

        One link. It is the board. The token is on it because /board
        draws no BUY control without one.
        """
        try:
            from config import DASHBOARD_HOST, DASHBOARD_PORT
            from dashboard.access_token import get_or_create_token
            base = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}"
            token = get_or_create_token()
            decision("=" * 66)
            decision("  DASHBOARD")
            decision(f"      {base}/board?token={token}")
            decision("=" * 66)
        except Exception as exc:                               # noqa: BLE001
            warn(f"[DASHBOARD] Could not print the link ({exc}). It is "
                 f"still served -- see config.DASHBOARD_PORT.")


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

    # ==========================================================
    # THE SCREEN COMES UP FIRST.  12 August 2026.
    # ==========================================================
    #
    #     "main.py is running but no dashboard link is printed till now"
    #
    # It was printed -- 5 minutes and 12 seconds after startup began,
    # under 5,400 log lines. Measured on the 22:36 run:
    #
    #     22:36:18  startup begins, token minted
    #     22:36:34  feed starts connecting
    #     22:38:38  "Feed error, retrying: no close frame received"
    #     22:40:28  "Feed error, retrying: no close frame received"
    #     22:41:30  DASHBOARD  http://127.0.0.1:8000/board?token=...
    #
    # Two feed retries, 124s and 81s. start_feed() ran at line 1519 and
    # start_dashboard() at 1535, so the dashboard did not merely go
    # UNADVERTISED for five minutes -- it did not EXIST. Nothing was
    # listening on the port.
    #
    # The dashboard needs none of it. dashboard_state, trade_controller
    # and master_loader are all built hundreds of lines above; the page
    # reads a snapshot and the feed only fills that snapshot in.
    #
    # So the order is inverted. The screen is the operator's only
    # window into this process, and holding it behind the component
    # MOST LIKELY TO BE SLOW OR BROKEN is backwards -- a feed that
    # cannot connect is the moment he most needs to see the panel that
    # says so.
    #
    # Buying early is already refused elsewhere: a manual BUY requires
    # a live feed (tests/test_manual_buy_needs_a_feed.py) and automated
    # entries need ALERT_ONLY off, which now starts True.
    # ---- AND refresh() BLOCKS TOO. Measured 22:52, same evening. ----
    #
    # Moving this whole block above start_feed() was not enough. The
    # FIRST refresh() builds every panel -- shortlist reference for
    # 2,382 symbols, liquidity for 2,484, the watchlist, the sectors --
    # and takes MINUTES on its own. Called before start_dashboard(), it
    # kept the port shut for all of them:
    #
    #     22:52:38  startup begins
    #     22:53:02  circuit monitor started
    #     22:53:04  [WATCHLIST] ... last line for four minutes
    #               port 8000: nothing listening
    #
    # The server does not need a full snapshot to start. state.py
    # initialises _snapshot to {"ready": False} and every page already
    # handles that -- it is what "loading" on the board is for.
    #
    # So: listen FIRST, tell him the address, then fill the panels in.
    # A screen that says "loading" is infinitely more use than a
    # refused connection, because the first one tells him the bot is
    # alive.
    dashboard_server, dashboard_thread = start_dashboard(
        dashboard_state, engine.trade_controller, master_loader
    )
    _print_dashboard_banner()

    # ---- THE PHONE. 17 August 2026. ----
    #
    #     "our bot needs telegram command center with alerting user
    #      about the opportunities & commands to buy,sell,exitall"
    #
    # A SECOND FRONT DOOR, NOT A SECOND ORDER PATH. Every command ends
    # at the same trade_controller the dashboard BUY button calls, so
    # ALERT_ONLY_MODE, the daily loss cap and every entry gate still
    # apply -- core/telegram_desk.py never builds an order and never
    # speaks to Dhan.
    #
    # It is also the least important thing in this process: start()
    # returns False and says why if the token or chat id is missing,
    # and the poll runs on a daemon thread that cannot delay a tick.
    telegram_desk = None
    try:
        from core.telegram_desk import TelegramDesk
        telegram_desk = TelegramDesk(
            controller=engine.trade_controller,
            state=dashboard_state,
            engine=engine,
            master_loader=master_loader)
        telegram_desk.start()
        # ---- AND THE ALERTS GO OUT OF IT. 18 August 2026. ----
        #
        #     "why i didn't get any alerts to buy stocks in telegram ?"
        #
        # Because of this one missing line. The desk could send since
        # yesterday and the Engine has been writing buy alerts since
        # 31 July, and nothing introduced them. TIINDIA, NEOGEN, PCBL
        # and ACE were all alerted this morning -- to a log file.
        #
        # This is an assignment and not a subscription on purpose:
        # there is exactly ONE listener, so an alert cannot be sent
        # twice, and setting it here rather than inside the Engine
        # keeps core/engine.py with no knowledge that Telegram exists.
        engine.on_alert = telegram_desk.push
    except Exception as exc:                               # noqa: BLE001
        warn(f"[TG] Telegram desk not started ({exc}). Everything else "
             f"is unaffected.")
    dashboard_state.refresh()  # panels fill in; the port is already open

    feed, feed_thread = start_feed()
    feed_state["thread"] = feed_thread

    sector_monitor.refresh()   # so the first heartbeat's panic picture isn't empty by default
    # The running half of the morning checklist. See core/morning_ready.py.
    # disarm() is injected rather than reaching into the Engine from
    # inside the guard, so it can be driven in a test without one.
    from core.morning_ready import LiveGuard as _LiveGuard

    def _disarm_for_dead_feed():
        engine.alert_only = True
        engine.breakout_armed = False

    _live_guard = _LiveGuard(disarm=_disarm_for_dead_feed, say=decision)

    # The dashboard and its banner now run BEFORE start_feed() --
    # see the note there for why. Nothing to do here.

    squared_off = False
    last_heartbeat = time.monotonic()
    last_dashboard_refresh = time.monotonic()
    last_tick_count = 0
    feed_dead_since = None
    # Did the session end because the market closed, or because something
    # stopped it? Only the first earns the after-close review hold -- a
    # Ctrl+C means the operator wants the process GONE, and holding it
    # open would be arguing with him.
    closed_normally = False

    try:
        while True:
            now = datetime.now().time()

            # Dashboard snapshot refresh -- its own cadence, decoupled
            # from the heartbeat/state-save cadence, so tightening or
            # loosening one never affects the other.
            if time.monotonic() - last_dashboard_refresh >= DASHBOARD_REFRESH_INTERVAL_SECONDS:
                dashboard_state.refresh()
                last_dashboard_refresh = time.monotonic()

                # ---- THE CHECKLIST IS NOT ONLY A DOOR. 7 Aug 2026. ----
                #
                # /api/bot_trading/on refuses to arm while a morning
                # input is missing. It checked ONCE, at the moment he
                # armed it, and never looked again -- so a collector
                # that dies at 11:00 leaves the bot buying at 11:30 on
                # news that stopped arriving half an hour earlier, with
                # nothing but a red panel he may not be watching.
                #
                # Three consecutive failures, not one: the channels go
                # quiet for long stretches and a 20-minute silence at
                # 14:00 is a normal afternoon. One good check resets it.
                #
                # Disarming stops NEW entries only. Stops, trails,
                # targets and the circuit guard keep running on
                # everything already held.
                try:
                    _live_guard.poll(armed=not engine.alert_only)
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[GUARD] Could not check the feed ({exc}). "
                         f"Trading continues -- watch the panel.")

                # ---- THE JOIN. 5 August 2026. ----
                #
                #   "the purpose of bot is not fulfilled right? even
                #    after bringing all food near mouth . you can't
                #    take the food!"
                #
                # core/ranker.py was read by dashboard/state.py and by
                # NOTHING else. Every gate he asked for -- the reason,
                # the volume, the sector lead, liveness, MTF, the
                # Rs 1,500 risk sizing -- produced a table on a web
                # page and stopped there. The Engine, the only thing
                # that can place an order, had never heard of it.
                #
                # This hands those same rows to the Engine's own entry
                # path. ALERT_ONLY_MODE still governs everything: while
                # it is True this alerts and records and places
                # nothing. Building the join and removing the safety
                # are separate decisions and must not arrive together.
                try:
                    # get_snapshot(), not snapshot(). Checked against the
                    # real class before this shipped, which is the whole
                    # discipline: five method names in this project have
                    # been written from memory and every one was wrong.
                    _snap = dashboard_state.get_snapshot() or {}
                    _ranked = _snap.get("ranked")
                    _rows = (_ranked or {}).get("rows") or []
                    # ---- THE EARLY-BIRD LANE JOINS THE SAME DOOR. ----
                    #      12 August 2026.
                    # core/auto_entry.early_rows() (graded overnight,
                    # 09:15-09:30, its own reason + volume + "making
                    # highs" gates -- see dashboard/state.py's
                    # build_early()) was fully built and never called
                    # from here. Shaped identically to a ranked row, so
                    # take() applies every one of its own gates to it
                    # too -- nothing about this list is trusted more
                    # than the standard one. The ranker's own refusal
                    # list is a separate snapshot key and is never
                    # merged in here -- it stays display-only.
                    _early = _snap.get("early")
                    _rows = _rows + ((_early or {}).get("rows") or [])
                    if _rows:
                        auto_entry.take(
                            _rows, engine,
                            now=datetime.now(),
                            security_id_of=master_loader.security_id,
                            held=set(engine.open_positions),
                            # ---- CASH, NOT THE NUMBER 3. 8 Aug 2026. ----
                            # The engine sizes the book from the balance
                            # (core/capital.py) and falls back to
                            # MAX_OPEN_POSITIONS when it cannot read it.
                            # This path was passing the constant directly
                            # and overriding that entirely.
                            max_positions=engine._position_ceiling(),
                            alert=engine._manual_alert,
                            enter=engine._enter,
                        )
                except Exception as exc:                   # noqa: BLE001
                    warn(f"[RANKED] Could not route the ranker's picks "
                         f"({exc}). The panel is unaffected.")

            if not squared_off and now >= SQUARE_OFF_T:
                if FORCE_SQUARE_OFF_AT_CLOSE:
                    engine.flatten_all(market_data.get_latest_price)
                else:
                    # MTF, 2026-07-28. Positions are CARRIED, not
                    # liquidated -- see config.FORCE_SQUARE_OFF_AT_CLOSE.
                    # Report exactly what is being held overnight and
                    # what it is worth, so the operator decides with
                    # numbers rather than discovering it at 09:15.
                    engine.report_carry_forward(market_data.get_latest_price)
                squared_off = True
            # #0 belt-and-suspenders, 2026-07-24 (evening): the primary
            # fix blocks structural entries on tick_time >= SQUARE_OFF_T
            # (core/engine.py), so nothing new should open past 15:15.
            # But flatten_all was one-shot, so if ANY straggler ever
            # slipped in (clock skew, a tick mid-processing when the
            # first flatten ran), it sat open forever. Now: once past
            # square-off, re-flatten on any loop where the book isn't
            # empty. Cheap (a dict check), and it can't loop-buy because
            # entries are already time-gated off.
            elif squared_off and engine.open_positions \
                    and FORCE_SQUARE_OFF_AT_CLOSE:
                engine.flatten_all(market_data.get_latest_price)

            # TOP_N_MOMENTUM_MODE (config.py): lock the top-25-
            # gainers/top-25-losers shortlist exactly once, right
            # when the ORB window closes -- same one-shot-guard
            # pattern as squared_off above, except the guard here is
            # the universe's own is_locked() rather than a separate
            # bool, so a restart that already restored a saved lock
            # (state_store.load() above) never re-locks a possibly-
            # different list.
            # 2026-07-29: OFF. This froze a 25/25 list at 09:30 that
            # nothing has read for weeks -- see config's
            # ENABLE_MOMENTUM_LOCK for the three-session measurement of
            # why no hour is a good hour to freeze one.
            if ENABLE_MOMENTUM_LOCK and not momentum_universe.is_locked() \
                    and now >= ORB_WINDOW_END_T:
                momentum_universe.lock()

            if now >= MARKET_CLOSE_T:
                # The TRADING day ends here and always has. What changed
                # on 30 July 2026 is only what happens to the process
                # afterwards -- see KEEP_DASHBOARD_AFTER_CLOSE in config
                # and the review hold at the end of the finally block.
                decision("Market closed. Trading has stopped for the day.")
                closed_normally = True
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

            # ---- ASK WHAT BECAME OF THE ORDERS THAT TIMED OUT ----
            #      3 August 2026.
            #
            # An order that does not confirm in ten seconds is not
            # finished, and until today nothing ever looked again. The
            # YASHO order at 09:17:34 filled late and became 24 shares
            # that no stop, no trail and no panel knew about.
            #
            # On the heartbeat rather than the tick loop: it is a REST
            # call on the account the orders go through, and it only has
            # to be faster than the operator's patience, not faster than
            # the market. Never raises -- a follow-up check must not be
            # able to stop the session it is protecting.
            try:
                _executor = getattr(engine, "execution", None)
                _executor = getattr(_executor, "executor", _executor)
                _resolve = getattr(_executor, "resolve_in_flight", None)
                if _resolve is not None:
                    for _late in _resolve() or []:
                        warn(f"[LATE FILL] {_late['symbol']} "
                             f"{_late['side']} {_late['qty']} @ "
                             f"{_late['price']} (order {_late['order_id']}) "
                             f"-- it is at Dhan and NOT in the bot's book. "
                             f"Reconcile before trading it again.")
            except Exception as _exc:                      # noqa: BLE001
                diagnostic(f"[LIVE] in-flight sweep skipped ({_exc}).")

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
                    f"feed alive: {feed_thread.is_alive()} | "
                    f"tick queue backlog: {tick_queue.qsize()} | "
                    f"tick worker alive: {tick_worker_thread.is_alive()}"
                )
                # 2026-07-29: flush the signal journal here too. It
                # was only written at shutdown, so a crash or a killed
                # window lost the whole day's record of what the bot
                # saw and refused -- which is the one thing that
                # cannot be reconstructed afterwards.
                if signal_journal is not None:
                    signal_journal.flush()

                last_heartbeat = time.monotonic()
                last_tick_count = tick_count

                # Same cadence as the heartbeat -- breadth-based, not
                # tick-hot (core/sector_monitor.py's own docstring),
                # so this is exactly the right rhythm for it.
                sector_monitor.refresh()

                # ---- ASK DHAN AGAIN. 18 August 2026. ----
                #
                #     "BOT IS NOT CHECKING THE DHAN ACCOUNT. WHY?"
                #
                # Reading the balance ONCE at startup is still "not
                # checking" by 14:00 -- and he trades from the Dhan app
                # himself during the session, so the figure moves
                # without this process doing anything at all.
                #
                # This updates the DISPLAY, not the book's purse. The
                # sizing capital is fixed at open deliberately, so a
                # position cannot change size underneath itself
                # mid-session. Reporting and sizing are separate here
                # on purpose and stay separate.
                try:
                    broker_funds.refresh(dhan_rest_client)
                except Exception as exc:                   # noqa: BLE001
                    diagnostic(f"[FUNDS] Could not refresh the balance "
                               f"({type(exc).__name__}). The last good "
                               f"reading stands, with its own timestamp.")

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
                    orb_unreliable=market_data.export_orb_unreliable(),
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
            orb_unreliable=market_data.export_orb_unreliable(),
            session_counters=engine.export_session_counters(),
            # Today's closed trades. Without this the Performance panel
            # and the Closed Trades table showed only what had happened
            # since the last restart -- and on 30 July there were four.
            closed_positions=list(engine.closed_positions),
        )
        # ORDER CHANGED, 30 July 2026. The dashboard used to be stopped
        # FIRST here (fastest to stop, no Dhan sockets of its own). It is
        # now stopped LAST, because of the review hold at the bottom of
        # this block: the whole point is that the page survives the
        # trading session, and it cannot survive a stop_dashboard() that
        # runs before the hold.
        #
        # The reason the old ordering existed -- the previous bot's Ctrl+C
        # hang -- is not affected. That fix was the should_exit+join-with-
        # timeout pattern INSIDE stop_dashboard(), not the position of the
        # call. Every thread here is still either joined with a timeout or
        # a daemon, so the process can always exit.
        #
        # The feed closes here, before any hold. A live Dhan WebSocket
        # held open all night to serve a read-only page would be an
        # unnecessary connection, an unnecessary risk, and unnecessary
        # noise in Dhan's logs.
        _safe_close_feed(feed, timeout=5)
        # 2026-07-29: close the candles that were still OPEN. A candle
        # only closes when a tick from the next minute arrives, and at
        # the end of the day there is no next tick -- so the final
        # minutes were silently discarded. The operator's own check
        # caught it: every one of 666 symbols stopped at 15:27 on a day
        # the market traded to 15:30.
        try:
            leftover = engine.candle_engine.close_open_candles()
            if leftover:
                decision(f"[CANDLE] Closed {len(leftover)} candle(s) that "
                         f"were still open at shutdown -- the last minutes "
                         f"of the session are no longer lost.")
                if candle_recorder is not None:
                    for symbol, candle in leftover:
                        candle_recorder.record(symbol, candle)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[CANDLE] Could not close the open candles ({exc}).")

        # Flush any buffered candles so the session's data is complete
        # in the replay store even on a mid-session Ctrl+C.
        if candle_recorder is not None:
            candle_recorder.close()
        if signal_journal is not None:
            signal_journal.close()
        if announcement_watcher is not None:
            announcement_watcher.stop(timeout=3)
        if results_ingestor is not None:
            results_ingestor.stop(timeout=3)
        if news_watcher is not None:
            news_watcher.stop(timeout=3)
        decision("Trading session closed. Everything is saved.")

        # ----------------------------------------------------------------
        # AFTER-CLOSE REVIEW HOLD -- 30 July 2026
        #
        #     "but main.py will auto close after market timings right?"
        #
        # It did, and that quietly made the POST-MARKET tab unreachable.
        # Closed trades, performance and the refusal breakdown could only
        # be read while the market was open -- exactly when nobody wants
        # to read them.
        #
        # By the time this runs, the trading day is over in every sense
        # that matters: the feed is closed, state is saved, the circuit
        # poller is stopped, every watcher is stopped, and no order path
        # is alive. What remains is the HTTP server holding a page over
        # numbers that can no longer change. That is a review screen, and
        # keeping it up costs one idle thread.
        # ----------------------------------------------------------------
        # ---- IT SCORES ITSELF. 4 August 2026. ----
        #
        #   "again why manual runs? why can't bot do itself."
        #
        # No good reason. I told him to run build_daily_history.py and
        # then verify_picks.py by hand after every close, in that
        # order, or the second one reports nothing. That is a sequence
        # a machine should own -- and one he will eventually forget on
        # the day the answer matters.
        #
        # ---- CTRL+C AFTER THE CLOSE IS STILL AFTER THE CLOSE. 5 Aug ----
        #
        #     "CTRL+C main.py closed . no score card found ..."
        #
        # closed_normally is only set when the LOOP reaches 15:30 by
        # itself. He stopped the process at 16:10, after the market had
        # shut, and got nothing -- on the first day of Phase 1, the one
        # day the scorecard was the entire point.
        #
        # How the process ended is not the question. Whether the trading
        # day is over is. A Ctrl+C at 11:00 must still skip it (the day
        # is not scoreable yet); a Ctrl+C at any time past the close must
        # not.
        if closed_normally or datetime.now().time() >= MARKET_CLOSE_T:
            _score_the_day()

        if KEEP_DASHBOARD_AFTER_CLOSE and closed_normally:
            _hold_dashboard_for_review(dashboard_state)

        stop_dashboard(dashboard_server, dashboard_thread, timeout=5)
        # Let the next start in. Only removes a lock THIS process owns,
        # so a genuinely running second bot keeps its claim.
        #
        # A lock left behind is not fatal either way: the next start
        # checks whether the pid is ALIVE, so a crash that skips this
        # line leaves a dead pid that the guard reads straight through.
        # That is the whole reason it checks liveness instead of age --
        # see core/single_instance.py.
        single_instance.release()
        decision("Shutdown complete.")


def _score_the_day():
    """Build today's bars, then report how the bot's picks did.

    ==========================================================
        "again why manual runs? why can't bot do itself."
                                -- operator, 4 August 2026
    ==========================================================

    Two steps in a fixed order: tools/build_daily_history.py writes
    today's closes from the bhavcopy, and tools/verify_picks.py reads
    the decision log against them. Run the second first and it
    correctly refuses to report -- which is the right behaviour and a
    terrible thing to rediscover by hand at 16:00.

    WRAPPED SO IT CANNOT COST THE SESSION. This runs after the feed is
    closed, state is saved and every order path is dead, so there is
    nothing left to protect except the shutdown itself. A scorecard
    that fails must print why and let the process exit cleanly.
    """
    decision("=" * 66)
    decision("  SCORING THE DAY -- no clicks needed")
    decision("=" * 66)
    try:
        from tools.build_daily_history import main as build_bars
    except Exception as exc:                               # noqa: BLE001
        warn(f"[REVIEW] Could not load the bar builder ({exc}). "
             f"Run py tools/build_daily_history.py by hand.")
        return
    try:
        build_bars()
    except Exception as exc:                               # noqa: BLE001
        # NSE publishes the bhavcopy on its own schedule. Missing it is
        # normal at 15:35 and not an error worth alarming him about --
        # but it does mean the scorecard below cannot be produced, and
        # THAT has to be said plainly rather than shown as zero.
        warn(f"[REVIEW] Today's bars are not available yet ({exc}). "
             f"The scorecard needs them -- run "
             f"py tools/verify_picks.py later this evening.")
        return
    try:
        from tools.verify_picks import main as verify
        verify()
    except Exception as exc:                               # noqa: BLE001
        warn(f"[REVIEW] Could not score the picks ({exc}).")

    _run_nightly()


def _run_nightly():
    """The rest of the after-close chain, without being asked.

    ==========================================================
        "complete the wherever automation can be done. give me
         only which cannot be automated."
                                -- operator, 4 August 2026
    ==========================================================

    tools/nightly.py already chains the steps; it just waited to be
    typed. Everything here reads or writes files the trading process
    has finished with, so it costs nothing but shutdown time.

    TELEGRAM IS DELIBERATELY EXCLUDED. tools/collector.py owns
    data/telegram.db and is the only process allowed to write it. Two
    writers on a Windows drive corrupted that store on 2 August, and
    nightly's telegram step is a second writer. The collector is
    already polling the channels continuously, so the step has nothing
    left to catch up on anyway.
    """
    try:
        from tools.nightly import STEPS, run
    except Exception as exc:                               # noqa: BLE001
        warn(f"[NIGHTLY] Not available ({exc}). "
             f"Run py tools/nightly.py by hand.")
        return

    decision("=" * 66)
    decision("  AFTER-CLOSE CHAIN -- liquidity, universe, master data")
    decision("=" * 66)
    for step in STEPS:
        if step[0] == "telegram":
            # See the docstring. The collector owns that store.
            continue
        try:
            run(step)
        except Exception as exc:                           # noqa: BLE001
            # One failing step must not stop the rest. "universe" runs
            # LAST and reads everything above it, so losing "discover"
            # should still leave tomorrow's list built from what we do
            # have -- degraded, and said so, rather than absent.
            warn(f"[NIGHTLY] Step '{step[0]}' failed ({exc}). Continuing.")


def _hold_dashboard_for_review(dashboard_state):
    """Keep the dashboard served after the close, then stop itself.

    The trading day is already fully over when this is called -- feed
    closed, state saved, no order path alive. This adds nothing but
    process lifetime, so the POST-MARKET tab has a screen to live on.

    It ends in one of two ways:

      Ctrl+C            -- the operator is done reviewing.
      09:00 next day    -- it stops itself, and this is the part that
                           matters. A process left running overnight has
                           a CLOSED feed and yesterday's opening ranges.
                           Still serving at 09:15 it would look live and
                           be dead, and every number on it would be
                           plausible. A banner was the alternative and it
                           was rejected for the right reason: a banner is
                           a thing you have to notice.

    The snapshot is told it is stale so the page can say so, but the
    auto-exit is what is actually relied on.
    """
    try:
        dashboard_state.mark_session_ended()
    except Exception as exc:                               # noqa: BLE001
        # The hold is worth having even without the banner.
        warn(f"[REVIEW] Could not flag the page as after-close ({exc}).")

    try:
        from config import DASHBOARD_HOST, DASHBOARD_PORT
        where = f"http://{DASHBOARD_HOST}:{DASHBOARD_PORT}/"
    except Exception:                                      # noqa: BLE001
        where = "the dashboard"

    decision(
        f"[REVIEW] Trading is finished. The dashboard stays up at {where} "
        f"so the POST-MARKET tab can be read -- closed trades, "
        f"performance, and why the bot said no."
    )
    decision(
        f"[REVIEW] Nothing can trade from here: the feed is closed and "
        f"the numbers are frozen at the close. Press Ctrl+C when done. "
        f"It will stop itself at {DASHBOARD_AFTER_CLOSE_EXIT_AT} so a "
        f"stale page can never be mistaken for tomorrow's live session."
    )

    try:
        while True:
            # Only ever exits FORWARD past the cutoff. Checking
            # `now >= 09:00` alone would fire instantly when the hold
            # starts after a same-day close, so the guard is that the
            # clock has to have crossed midnight first -- i.e. we are in
            # the small hours, at or past the cutoff.
            now = datetime.now().time()
            if MARKET_CLOSE_T > now >= AFTER_CLOSE_EXIT_T:
                warn(
                    f"[REVIEW] {DASHBOARD_AFTER_CLOSE_EXIT_AT} reached -- "
                    f"stopping. This page is yesterday's session and the "
                    f"feed has been closed all night. Start main.py again "
                    f"for today."
                )
                return
            time.sleep(5)
    except KeyboardInterrupt:
        decision("\n[REVIEW] Closing the review dashboard (Ctrl+C).")


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
