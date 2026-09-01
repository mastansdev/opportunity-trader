"""
==========================================================
Dashboard State
==========================================================

Builds the single JSON-able snapshot the dashboard reads --
capital, advances/declines, sector colour, gainers/losers, open
and closed positions. Pure data assembly: engine, market_data,
master_loader and portfolio are read-only inputs, this
module never mutates any of them.

Advances/declines/sector-colour used to be measured off each
stock's OWN DAY OPEN (the first accepted tick since the bot's
last restart -- core/market_data.py). SWITCHED 2026-07-24,
operator instruction, to each symbol's PREVIOUS DAY CLOSE
instead: the day-open version was resetting to "change since
last restart" rather than "change since market open" on any
session that restarted mid-day (flagged in this file's own
history the evening before), and it was inconsistent with Top
50 Gainers/Losers and the Sector Heatmap, both already prev-
close based -- NSE's own advances/declines are prev-close too.
prev_close comes from core/circuit_monitor.py's already-running
REST snapshot (engine.get_circuit_snapshot()), the exact same
source _build_gainers_losers() reads -- no new polling, no
switching the live feed off Ticker mode. last_price still comes
from market_data's own tick feed when available (updates every
tick, not throttled to the REST poll's few-second cadence),
falling back to the REST snapshot's own LTP only if no tick has
arrived yet for that symbol. A symbol the snapshot hasn't
captured (REST poll hasn't reached it yet, or its prev_close was
unusable -- see circuit_monitor.py's _snapshot_row()) is counted
"unchanged" rather than guessed, same convention as the old day-
open version -- keeps the three published counts summing to the
full universe size, as specified.

Refreshed on a timer (main.py, config.DASHBOARD_REFRESH_INTERVAL_SECONDS),
never on every tick.

Positions and PnL are DIRECTION-AWARE (core/engine.py's LONG/
SHORT support) -- a SHORT's live/realized PnL is (entry - last),
the mirror image of a LONG's (last - entry). risk_filters
surfaces exactly why a stock did or didn't trade: which sectors
are panic-flagged (core/sector_monitor.py) and which symbols
have a news-contradiction or sector block active today
(core/engine.py's entry_blocked) -- the same "why" the operator
asked the whole dashboard for in the first place.

V2 additions (2026-07-23, Institutional_Dashboard_V2_Blueprint.pdf):
performance analytics, a sector heatmap, a news feed, and system
health. Every one of these is built from data the bot already
genuinely has -- no field on this dashboard is fabricated. The
opportunity queue (also part of that V2 pass) was REMOVED again
the same evening, operator instruction -- see
_build_gainers_losers()'s docstring for what replaced its spot in
the layout. Deliberately NOT built here, per an
explicit operator decision the same session: AI Verdict /
Confidence / Holding Reason / Brain Verdict (no per-trade AI
reasoning call exists anywhere in this bot -- News Bot's AI
classification is per NEWS ITEM, not per POSITION -- faking
this would be exactly the kind of silent, misleading UI this
whole project has avoided everywhere else), a Knowledge Graph
(no such subsystem exists), and BSE (config.py's
EXCHANGE_SEGMENT is NSE_EQ only, a permanent decision, not a
Layer 1 gap).

A fixed Target was briefly not universally "not applicable" --
the first TOP_N_MOMENTUM_MODE experiment (2026-07-23 night) gave
each position a real fixed_target price. SUPERSEDED 2026-07-24 by
ATR-based sizing (core/engine.py's _atr_entry_sizing()/
_check_atr_trailing()): momentum-mode positions now have NO fixed
target either, same as everywhere else -- fixed_target is None for
every NEW position regardless of mode, and only ever non-None on
an old fixed-bracket position restored from before the redesign.
The field (and the "stop" column's routing just below) stays,
surfaced per-position in open/closed positions below, so a
still-open pre-redesign trade keeps displaying correctly.
momentum_universe surfaces today's locked top-25-gainers/top-25-losers shortlist
(core/momentum_universe.py) so the operator can see exactly
which 50 symbols are eligible today, and whether the lock has
happened yet -- NOT the same feature as gainers_losers below
(that's TRADING eligibility, locked once at ORB_WINDOW_END;
this is a live DISPLAY table, always re-ranked, no trading
consequence).

REPLACED 2026-07-23 evening, operator instruction: the old ORB
Bullish/Bearish watchlist panel (symbols currently trading
beyond their ORB range) is gone -- "remove watchlist... TOP 50
GAINERS & TOP 50 LOOSERS in the place of watchlist." New
gainers_losers key, built by _build_gainers_losers() from
core/circuit_monitor.py's already-running REST poll snapshot
(engine.get_circuit_snapshot() -- OHLC/prev-close/volume/LTP
for the whole universe, the same data circuit-proximity
checking already fetches, no second poller). Ranked by
%-change vs each symbol's PREVIOUS DAY close (not day-open,
unlike advances/declines/sector-colour above -- this table
finally has that real reference, because circuit_monitor's
REST snapshot carries it), top/bottom GAINERS_LOSERS_COUNT
(config.py). Deliberately throttled to only re-rank every
GAINERS_LOSERS_REFRESH_SECONDS (operator's own choice, "every 5
mins") -- much slower than this module's own 1s refresh cycle,
cached and reused in between rather than recomputed on every
call.

Author : H&M Opportunity Trader
==========================================================
"""

import re
import threading
import zlib
import time
from datetime import datetime

from core.rules import SURGE_IS_A_REASON, SURGE_REASON_MIN_RATIO
from config import (
    REASON_CACHE_SECONDS,
    GAINERS_LOSERS_REFRESH_SECONDS, GAINERS_LOSERS_COUNT,
    SECTOR_GAINERS_LOSERS_MIN_SYMBOLS, SECTOR_GAINERS_LOSERS_REFRESH_SECONDS,
    SECTOR_HEATMAP_TOP_N, DAILY_PROFIT_TARGET_RS, DAILY_MAX_LOSS_RS,
    FII_NET_CR, DII_NET_CR,
    SANITY_BAND_MULTIPLE, CIRCUIT_LOCK_TOLERANCE_PCT, CIRCUIT_PROXIMITY_PCT,
    MARKET_BREADTH_REFRESH_SECONDS,
    SHORTLIST_REFRESH_SECONDS, SHORTLIST_COUNT, BREAKOUT_PANEL_COUNT,
    ANNOUNCEMENT_PANEL_COUNT, INDEX_EXPECTED_RANGE,
    MIN_TRADABLE_PRICE_RS,
)

from core import closed_book
from core.canslim import stored_tiers as canslim_tiers
from core.watchlist import build as watchlist_build
from core.watchlist import counts as watchlist_counts
from core.reporting import counts as reporting_counts
from core.reporting import watchlist as reporting_watchlist
from core.logger import warn, diagnostic, when_it_changes
from core.shortlist import ShortlistBuilder
from trading.charges import round_trip_charges, nights_between


def _adv(symbol):
    """Average daily traded value in crore, or 0. Fail-quiet."""
    try:
        from core.liquidity import adv
        return adv(symbol)
    except Exception:                                       # noqa: BLE001
        return 0.0


_HEADLINE_JUNK = re.compile(
    r"^[\W_]+|#\w+\s*[—–-]?\s*|\s*(?:→|->)\s*|\s*\+\s*Concall\b", re.U)


def _plain_headline(text):
    """Strip the plumbing out of a channel headline.

    ---- 3 August 2026 ----
    The impact store keeps the message exactly as the channel wrote it,
    which is right for the record and wrong for a panel:

        "🔄 #INDUSTOWER — Concall Recording → Concall Transcript + C"

    That is a routing note between two of the bot's own stages. It
    tells him nothing about why three stocks are moving. The stock
    names and the mechanism are on the rows underneath; the headline
    only has to say what happened.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    cleaned = _HEADLINE_JUNK.sub(" ", raw)
    cleaned = " ".join(cleaned.split())
    # If stripping left nothing useful, the original is still better
    # than a blank line.
    return cleaned if len(cleaned) > 8 else raw


# Words that mean "this headline is describing a FILE, not an event".
_PLUMBING = ("concall recording", "concall transcript", "concall summary",
             "press release", "investor presentation", "earnings brief",
             "transcript", "recording")


def _headline_for(story, stocks):
    """What happened, in words about the market rather than the pipeline.

    ---- 3 August 2026 ----
        "showing like same the news i do not want this type at all"

    The best row this panel produced all day arrived under the headline

        "INDUSTOWER — Concall Recording -> Concall Transcript + Summary"

    while the thing that actually moved three stocks was written on the
    rows below it: telecom towers shifting from lead-acid to
    lithium-ion. The panel was leading with the filename and burying
    the story.

    So when the headline is plumbing, the strongest stock's mechanism
    becomes the headline. It is the same text either way -- this only
    decides which line he reads first.
    """
    plain = _plain_headline(story.get("headline"))
    low = plain.lower()
    if any(word in low for word in _PLUMBING) or len(plain) < 12:
        for stock in stocks:
            why = str(stock.get("why") or "").strip()
            if len(why) > 20:
                return why[:180]
    return plain


def _coverage(symbol):
    """What the bot actually knows about this stock, in plain words.

    ---- 3 August 2026 ----

        "never assume-give clarity on every item residing in bot =
         dashboard"

    Every panel that offers a BUY button now carries this. It is not a
    score and not a recommendation -- it answers one factual question:
    has the bot ever seen this stock trade?

    YASHO had not. Zero minute candles, no traded value, and a BUY
    button on the first live day. 191 of the 946 tradeable names are in
    the same state.
    """
    value = _adv(symbol)
    if value <= 0:
        return {"known": False, "adv_cr": None,
                "note": "the bot has no price history for this stock"}
    return {"known": True, "adv_cr": round(value, 1),
            "note": f"trades about {value:,.0f} Cr a day"}


class _Snapshot:
    """Hands an already-built dict to something that expects a store.

    core/awareness.py asks its flow source for .snapshot(), because the
    real MarketFlows has one. The figure the dashboard actually shows
    comes from _build_institutional(), which falls through NSE ->
    News Pulse -> config. This adapter lets the panel and the ribbon
    read the SAME number instead of two different ones.
    """

    __slots__ = ("_data",)

    def __init__(self, data):
        self._data = data or {}

    def snapshot(self):
        return self._data

try:
    import psutil
except ImportError:  # pragma: no cover -- optional, system health degrades gracefully
    psutil = None


def _text(value):
    """A clean upper-case string, or "". NEVER raises on a NaN.

    ---- IT TOOK THE BOT DOWN AT STARTUP. 17 August 2026. ----

        AttributeError: 'float' object has no attribute 'upper'
        state.py:5956  name = (row.get("sector") or "").upper()

    pandas reads an empty SECTOR cell as float('nan'), and NaN IS
    TRUTHY -- so `nan or ""` returns the nan, not the "". Two guards
    in this file were written as `or ""` and neither could work:

        if not sector: continue        <- a NaN sector passed straight
                                          through and became a dict key
        (row.get("sector") or "").upper()   <- and then this crashed

    213 rows in data/master_stocks.csv have no SECTOR. Every one is
    SUBSCRIBE=NO -- ETFs and InvITs, MONIFTY500, GOLDETF, EMBASSY --
    and one of them reached the gainers list, which is enough.

    Same trap as core/master_loader.py's series gate the day before,
    where `str(x or "")` read "nan" and blocked a row it should have
    waved through. NaN is not falsy and never will be; the only safe
    test is value != value.
    """
    if value is None or value != value:            # None or NaN
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text.upper()


def _num(value):
    """A number, or None. Never a string and never a guess.

    Dhan returns quantities and prices as strings on some endpoints and
    numbers on others. A row that silently became "0" because "-1" was
    a str would report a short position as flat, which is the kind of
    quiet wrongness this file exists to avoid.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_time(value):
    """HH:MM:SS from a datetime OR from a string that used to be one.

    31 July 2026, 14:20. main.py crashed on startup:

        AttributeError: 'str' object has no attribute 'strftime'

    A closed trade (the NAZARA round trip) had been saved to
    data/session_state.json and restored on the next start. JSON has no
    datetime type, so state_store._json_safe() writes them as ISO
    strings and they come back as strings -- while this function had
    only ever been handed live datetime objects from memory.

    So the crash needed BOTH a completed trade AND a restart on the
    same day. Every restart before today happened with nothing closed
    yet, which is why it survived four restarts on 30 July and fired on
    the first one after a real round trip.

    It takes the dashboard down at STARTUP, so the operator loses the
    whole panel over a formatting detail -- and on a live afternoon
    that is the moment he most needs to see his book.

    Both shapes are accepted, and anything unrecognisable is shown as
    given rather than raising. A wrong-looking timestamp is a blemish;
    a traceback is a lost session.
    """
    if value is None:
        return None
    if hasattr(value, "strftime"):
        return value.strftime("%H:%M:%S")

    text = str(value).strip()
    if not text:
        return None
    # "2026-07-31T14:11:15.123456" or "2026-07-31 14:11:15"
    from datetime import datetime

    for shape in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                  "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S",
                  "%H:%M:%S"):
        try:
            return datetime.strptime(text, shape).strftime("%H:%M:%S")
        except ValueError:
            continue
    return text


def _signed_pnl(direction, entry_price, exit_or_last_price, qty):
    if direction == "SHORT":
        return (entry_price - exit_or_last_price) * qty
    return (exit_or_last_price - entry_price) * qty


def _is_plausible_move(change_pct, prev_close, upper_limit, lower_limit):
    """
    2026-07-24 -- False if |change_pct| is mathematically impossible
    under TODAY's own exchange circuit band, which caps how far a
    genuine intraday move can go (see config.SANITY_BAND_MULTIPLE's
    docstring for the JLHL split that motivated this). True (never
    flags) whenever circuit limits aren't available for this symbol
    -- absence of data is not evidence of a problem, same fail-open
    posture used everywhere else in this codebase for optional data.
    """
    if not upper_limit or not lower_limit or upper_limit <= lower_limit:
        return True
    if not prev_close:
        return True

    max_band_pct = max(
        abs(upper_limit - prev_close), abs(prev_close - lower_limit)
    ) / prev_close * 100

    return abs(change_pct) <= max_band_pct * SANITY_BAND_MULTIPLE


def _is_circuit_locked(last_price, upper_limit, lower_limit):
    """
    2026-07-24 -- True if last_price is sitting AT (not just near)
    either circuit limit, i.e. zero real order flow right now (see
    config.CIRCUIT_LOCK_TOLERANCE_PCT's docstring for the CEMPRO
    case that motivated this). False whenever circuit limits aren't
    available -- same fail-open posture as _is_plausible_move().
    """
    if last_price is None or not upper_limit or not lower_limit:
        return False
    if upper_limit > 0 and abs(last_price - upper_limit) / upper_limit <= CIRCUIT_LOCK_TOLERANCE_PCT:
        return True
    if lower_limit > 0 and abs(last_price - lower_limit) / lower_limit <= CIRCUIT_LOCK_TOLERANCE_PCT:
        return True
    return False


_DAILY_STORE = []


def _daily_store():
    """core/daily_store.DailyStore, opened once per process. None on
    failure -- a panel must never take the snapshot down."""
    if not _DAILY_STORE:
        try:
            from core.daily_store import DailyStore
            _DAILY_STORE.append(DailyStore())
        except Exception:                                  # noqa: BLE001
            _DAILY_STORE.append(None)
    return _DAILY_STORE[0]


def _rr(direction, entry_price, exit_or_last_price, initial_stop):
    """
    Risk:Reward, computed honestly from the stop actually seeded
    at entry (core/engine.py's "initial_stop" -- never the LIVE
    ratcheted stop, which only ever improves and would silently
    flatter every winning trade's RR). None if initial_stop is
    unknown (e.g. a position restored from a pre-RR-tracking
    snapshot) -- never guessed.
    """
    if initial_stop is None:
        return None

    risk = abs(entry_price - initial_stop)
    if risk == 0:
        return None

    reward = (exit_or_last_price - entry_price) if direction == "LONG" \
        else (entry_price - exit_or_last_price)

    return round(reward / risk, 2)


# 52-week band extremes, read ONCE per process. A year of daily bars is
# 1.08m rows; scanning them on a dashboard refresh is indefensible for a
# number that changes at most once a day. Module level rather than
# instance level because tools/dashboard_preview.py and the tests build
# several DashboardStates and each one would otherwise pay again.
_52W_CACHE = {"bands": None, "at": 0.0}


class DashboardState:

    def __init__(self, engine, market_data, master_loader,
                 portfolio=None, sector_monitor=None, get_feed_alive=None,
                 index_monitor=None, announcement_watcher=None,
                 quarterly_results=None, news_watcher=None,
                 market_flows=None, trade_memory=None, premarket=None,
                 preopen=None, index_members=None, telegram=None,
                 news_impact=None, morning_brief=None, stock_memory=None,
                 results_calendar=None, index_quote=None):
        # ---- THE INDICES BEFORE 09:15. 4 August 2026. ----
        #
        #   "what about indices data. why we need to wait till 09:15"
        #
        # He is right and there was no good answer. IndexMonitor fills
        # from the WebSocket tick feed, and the first tick of the day
        # arrives at the open -- so NIFTY, BANKNIFTY, VIX and all
        # fourteen sector tiles read "no feed" for the entire hour he
        # spends deciding what to trade.
        #
        # Dhan's REST quote endpoint answers outside market hours; it
        # is how tools/check_index_levels.py verified every security id
        # after the close. main.py already hands quote_data to the
        # circuit monitor. Passing the same callable here costs nothing
        # and fills the tiles with the last close until ticks start.
        self._index_quote = index_quote
        self._decisions = None
        # His own watchlist adds. Built lazily so a bad file
        # costs the panel and never the snapshot.
        self._watchlist = None
        self._idx_rest = {}
        self._idx_rest_at = 0.0
        self.engine = engine
        # core/stock_memory.py -- 183 dividends, splits, bonuses and
        # demergers with their ex-dates, scraped from BSE/NSE.
        #
        # WIRED INTO main.py SINCE THE START AND NEVER PASSED HERE. The
        # bot VETOES trades with it ("price-distorting corporate actions
        # in effect around today -- these will NOT be traded"), so the
        # operator could be refused a stock and have no way to see why.
        #
        # Found 30 July 2026 by auditing the import graph rather than
        # assuming. The v3 "Corporate actions" panel had been reading
        # s.actions -- which is the manual CLICK LOG, not corporate
        # actions at all.
        self.stock_memory = stock_memory
        # core/results_calendar.py -- who reports, and when. It has been
        # wired into main.py since the start and drives the shortlist's
        # "REPORTING TODAY" chip, but it was never a panel of its own,
        # so the operator could not ask the plain question "who reports
        # today" without reading it off a chip on a ranked list.
        #
        #     "Results, Corporate actions of the day"
        #                                 -- operator, 30 July 2026
        self.results_calendar = results_calendar
        # core/morning_brief.py -- three sentences about the overnight
        # session. OPINION, recorded so it can be judged later, and
        # nothing acts on it. Optional: no ANTHROPIC_API_KEY means no
        # brief, and the panel says so rather than showing a blank.
        #
        # Added to the payload 30 July 2026 because dashboard/static/v3.html
        # read s.morning_brief and the field did not exist -- the exact
        # ghost-field bug tests/test_dashboard_contract.py exists to
        # catch, caught by that test on the first run.
        self.morning_brief = morning_brief
        # Which stocks are in NIFTY 50 / F&O, so the pre-open
        # group buttons filter instead of pretending to.
        self.index_members = index_members
        # The operator's four Telegram channels. READ ONLY --
        # see build_telegram() for why it stops at the screen.
        self.telegram = telegram
        # News -> which stocks it touches. core/news_impact.py.
        self.news_impact = news_impact
        self.market_data = market_data
        self.master_loader = master_loader
        self.portfolio = portfolio
        self.sector_monitor = sector_monitor
        # Nifty/BankNifty/Midcap/VIX (core/index_monitor.py). None =
        # not wired -> Market Intelligence shows "needs feed" for them.
        self.index_monitor = index_monitor
        # Optional zero-arg callable -> bool, wired from main.py
        # (feed_thread.is_alive() is a local loop variable there,
        # this is the one piece of system health this module can't
        # derive from its own read-only inputs). None if not wired
        # -- system health just omits the field rather than guess.
        self.get_feed_alive = get_feed_alive

        # ==========================================================
        # "everything that bot knows must shown in dashboard"
        #                                 -- operator, 29 July 2026
        # ==========================================================
        # A principle, not a feature. Four times in one session the
        # answer to his question was "the bot knows, the screen
        # doesn't" -- results calendar, entry reasons, circuit bands,
        # and what a company actually does. Every source below exists
        # so that answer can never be given again.
        #
        # All optional. A missing one produces a missing SECTION,
        # never a wrong number.
        self.trade_memory = trade_memory
        self.premarket = premarket        # core/premarket.py  overnight world

        # core/results_calendar.py, opened on first use. Engine never
        # had a results_calendar attribute; see build_watchlist().
        self._results_calendar = None
        self._results_calendar_warned = False
        self.preopen = preopen            # core/preopen.py    09:00-09:12

        from core.stock_card import StockCard
        # core/stock_events.py -- the typed per-stock event memory.
        # Built lazily so a missing database costs the section, never the
        # dashboard.
        try:
            from core.stock_events import StockEvents
            self.stock_events = StockEvents()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[EVENTS] Not available: {exc}")
            self.stock_events = None

        # WIRED PROPERLY, 30 July 2026.
        #
        #     "upon clicking on stock name the box opening right now is
        #      not showing any data"
        #
        # It was not. StockCard was constructed WITHOUT telegram,
        # news_impact or signal_journal, so three of its eight sections
        # could only ever return None -- and those three are the ones
        # that answer "why is this moving". The card was not broken; it
        # was never handed the data. A constructor that silently accepts
        # None for its most valuable inputs is a quiet way to ship an
        # empty screen.
        self.stock_card = StockCard(
            stock_memory=stock_memory,
            engine=engine, market_data=market_data,
            master_loader=master_loader,
            quarterly_results=quarterly_results,
            announcement_watcher=announcement_watcher,
            news_watcher=news_watcher, trade_memory=trade_memory,
            telegram=telegram, news_impact=news_impact,
            signal_journal=getattr(engine, "signal_journal", None),
            stock_events=self.stock_events,
        )

        self._lock = threading.Lock()
        self._snapshot = {"ready": False}

        # After-close review mode, 30 July 2026. main.py now keeps the
        # dashboard served once trading has stopped, so the POST-MARKET
        # tab has a screen to live on:
        #
        #     "but main.py will auto close after market timings right?"
        #
        # It did, which meant the review tab could only be read during
        # the session. The flag lets the page say the numbers are frozen.
        # It is a LABEL, not a safeguard -- the safeguard is main.py's
        # own 09:00 auto-exit, because a banner is a thing you have to
        # notice and a dead process cannot mislead anyone at all.
        self._session_ended = None

        # Gainers/losers caches -- see _build_stock_gainers_losers()/
        # _build_sector_gainers_losers(). Kept on the instance (not
        # recomputed inside _build() every refresh) specifically so
        # each can be throttled to its OWN cadence, independent of
        # this module's own faster DASHBOARD_REFRESH_INTERVAL_SECONDS
        # cycle -- and, as of 2026-07-24, independent of EACH OTHER
        # too (GAINERS_LOSERS_REFRESH_SECONDS=60s for the stock table,
        # SECTOR_GAINERS_LOSERS_REFRESH_SECONDS=5s for the sector
        # heatmap -- previously one shared cache/cadence for both).
        self._gainers_losers_cache = None
        self._gainers_losers_built_at = 0.0
        self._sector_gainers_losers_cache = None
        self._sector_gainers_losers_built_at = 0.0

        # Market Breadth cache -- same reasoning, own cadence
        # (MARKET_BREADTH_REFRESH_SECONDS=5s, 2026-07-24). Previously
        # unthrottled (rebuilt every DASHBOARD_REFRESH_INTERVAL_SECONDS
        # cycle, i.e. every 1s) -- see _build_breadth().
        self._breadth_cache = None
        self._breadth_built_at = 0.0

        # Shortlist (core/shortlist.py), 2026-07-27. The panel that
        # answers "which of these 689 deserve thirty seconds of my
        # attention, and WHY" -- see that module's docstring for the
        # TMB/KFINTECH/CARTRADE evidence. Rebuilt on its own cadence,
        # same pattern as everything else here.
        #
        # Deliberately NOT locked once at 09:30 like
        # core/momentum_universe.py. Measured 2026-07-27: of the day's
        # closing top 20, only 12 were top 20 at 09:30. TMB sat at rank
        # 95 at noon and closed 2nd, with 98% of its volume after 13:00.
        # A frozen list cannot contain it.
        # core/announcement_watcher.py -- optional. When absent the
        # shortlist falls back to the results calendar, which knows the
        # DATE a company reports but not that it filed twenty minutes
        # ago. Both panels degrade rather than break.
        self.announcement_watcher = announcement_watcher
        # core/quarterly_results.py -- optional. Empty store means the
        # shortlist shows events without their numbers, which is where
        # this bot was all along; it is never a failure.
        self.quarterly_results = quarterly_results
        # core/news_watcher.py -- high-conviction news only. The filings
        # watcher would have missed both of 2026-07-27's biggest movers:
        # GANDHAR -11.6% (flood at its Silvassa plant) and CARTRADE
        # +10.8% (UBS initiation). Neither is a regulatory disclosure.
        self.news_watcher = news_watcher
        # core/market_flows.py -- FII/DII. config's FII_NET_CR and
        # DII_NET_CR were placeholders meant to be typed by hand and
        # never were, so the tile read "set in config (EOD)" every
        # session since the dashboard was built.
        self.market_flows = market_flows
        self._shortlist = ShortlistBuilder(
            announcement_watcher=announcement_watcher,
            quarterly_results=quarterly_results,
            news_watcher=news_watcher,
            # 30 July 2026 -- Earnings Pulse grades and OrderBook wins
            # now reach the score. They were collected all day and read
            # by nothing.
            stock_events=self.stock_events,
            # Who was still queued at 09:12 -- see _imbalance_for().
            preopen=preopen)
        # core/broker_sync.py -- "Both dhan platform & our dashboard
        # must be in synchronization no data mismatch". Reports, never
        # corrects: silently rewriting either book hides the event.
        try:
            from core.broker_sync import BrokerSync
            self.broker_sync = BrokerSync(
                execution=getattr(engine, "execution", None),
                # Marks hand-placed positions to market. Reuses the same
                # lookup the live order path uses for its drift check --
                # tick feed first, REST snapshot as fallback -- so the
                # panel and the order guard can never disagree about
                # what a stock is trading at.
                price_lookup=getattr(engine, "_live_price_for_order", None),
                # ---- SHOWN IS NOT PROTECTED. 5 August 2026. ----
                #
                #   "my goal is to stop manual trading & let the bot
                #    trade . do not ask me how ? thats your job"
                #
                # A position he opened at Dhan is now taken into the
                # bot's book with a stop, so the trailing stop, the
                # circuit guard and MOVE_DIED work on it. It places no
                # order and changes nothing at the broker -- the
                # position already exists.
                engine=engine,
                security_id_of=getattr(master_loader, "security_id", None),
                # ---- WATCH ONLY. 17 August 2026. ----
                #
                #     "corona, deepakfert, deepakntr, sbin, solarinds
                #      are my long positions in dhan"
                #
                # Those first three are in data/trade_memory.db as
                # CLOSED trades -- trailing-stop exits on 5 and 6
                # August, with losses written down. He still holds
                # them. ALERT_ONLY_MODE was on, so no order was ever
                # sent: the bot decided to exit, recorded the loss in
                # its permanent memory, and nothing happened at Dhan.
                # Each was recorded TWICE, re-adopted once per process
                # start, double-counting Rs 27,309.
                #
                # This flag was set True on 5 August, for a sentence he
                # meant at the time -- "my goal is to stop manual
                # trading & let the bot trade". He reversed it on the
                # 6th: "i told you too not track my old positions",
                # which added skip_symbols=_pre_existing. The flag
                # stayed on and only guarded what was open at STARTUP.
                #
                # core/broker_sync.py then grew an alert_only guard,
                # after adoption "sold all three out from under him".
                # That guard is real and it is not enough: it is tied
                # to the switch, so the day he arms the bot, adoption
                # resumes and it manages positions it did not open,
                # with a trailing stop calibrated for entries it chose.
                #
                # Asked directly on 17 August, he chose: watch only,
                # never manage or exit. So this is False regardless of
                # the switch. The positions still appear in the book
                # for book-keeping and still raise the "no stop at
                # Dhan" warning -- they simply get no stop from the
                # bot and no management.
                #
                # A DASHBOARD SHOULD NOT HAVE BEEN DOING THIS ANYWAY.
                # This is the display layer, and it was the only place
                # in the repo that turned adoption on -- broker_sync's
                # own default is False.
                adopt_with_stops=False)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SYNC] Not available: {exc}")
            self.broker_sync = None

        self._shortlist_cache = None
        self._shortlist_built_at = 0.0

    # --------------------------------------------------

    def refresh(self):
        """Rebuilds the snapshot, then swaps it in atomically --
        same pattern as NewsQueueReader.refresh()."""
        snapshot = self._build()
        with self._lock:
            self._snapshot = snapshot

    def force_gainers_losers_refresh(self):
        """2026-07-24 dashboard revamp -- the manual "Refresh now"
        button (dashboard/static/index.html). Clears the stock-G/L
        and sector-heatmap throttle timestamps so the next _build()
        recomputes them immediately instead of serving the (up to
        30s old) cache, then rebuilds the snapshot right away."""
        self._gainers_losers_built_at = 0.0
        self._sector_gainers_losers_built_at = 0.0
        self.refresh()

    def mark_session_ended(self):
        """Trading has stopped; the page is now a review screen.

        Called by main.py once the feed is closed and state is saved. It
        stamps the time so the banner can say WHEN the numbers froze
        rather than just that they did -- "frozen at 15:30" is a fact,
        "stale" is a mood.

        The final refresh here is deliberate: the last live refresh may
        have been up to a second before the close, and the closing trade
        belongs on the screen the operator reviews.
        """
        try:
            self.refresh()
        except Exception:                                  # noqa: BLE001
            # Say the session ended even if the last rebuild failed --
            # an unlabelled frozen page is worse than a stale one.
            pass
        stamp = datetime.now().strftime("%H:%M:%S")
        with self._lock:
            self._session_ended = stamp
            if isinstance(self._snapshot, dict):
                self._snapshot = dict(self._snapshot)
                self._snapshot["session_ended"] = stamp

    def get_snapshot(self):
        with self._lock:
            return self._snapshot

    def refresh_watchlist_panel(self):
        """Rebuild ONLY the watchlist, into the snapshot already served.

        ---- "I'M UNABLE TO DELETE" WAS TRUE, AND THE DELETE WORKED ----

            "i'm unable to delete the stocks added in - Watch tab"
                                    -- operator, 17 August 2026

        Every part of that path was correct and it still looked broken:

            the click handler        fires, confirms, POSTs
            /api/watchlist/remove    returns {"success": true}
            core/watchlist_store.py  drops the row and saves the file

        and the stock stayed on his screen. /api/snapshot returns the
        payload THE LIVE LOOP BUILDS -- deliberately, so the page and
        the engine can never disagree -- and build_watchlist() only
        runs inside a full _build(). Until the next one, the panel is
        the old list. Reproduced: the store lost GAIL, and the
        snapshot still showed GAIL, MARICO, AUROPHARMA and BHARTIARTL,
        three of them removed sessions earlier.

        So he pressed remove, nothing changed, and pressed it again.
        Every press worked.

        This edits the served snapshot in place rather than forcing a
        whole rebuild: _build() walks 1,314 symbols and takes seconds,
        and doing that on a click is how the dashboard went stale on
        13 August. One panel, one lock, immediate.
        """
        try:
            panel = self._safe_watchlist()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[WATCHLIST] Could not refresh the panel ({exc}).")
            return False
        with self._lock:
            if isinstance(self._snapshot, dict):
                self._snapshot = dict(self._snapshot)
                self._snapshot["watchlist"] = panel
        return True

    # --------------------------------------------------

    def _build(self):
        # ==========================================================
        # ONE PASS OVER THE UNIVERSE, NOT SEVEN.  13 August 2026.
        # ==========================================================
        #
        #     "the full dashboard has data some of that were struck at
        #      last time i used & still its showing the same data"
        #
        # It was not the page. Measured on the live 12:40 session:
        #
        #     served_at   12:40:12 -> 12:40:31   moving
        #     updated_at  12:39:29 -> 12:39:29   FROZEN
        #
        # updated_at is stamped when THIS method returns, so the
        # snapshot was rebuilding roughly every two to three minutes
        # while main.py asked for one every second. The dashboard --
        # both screens -- was minutes behind a live market.
        #
        # The cause is in the log: [GL] appears ELEVEN times in two
        # seconds. _compute_gl_rows() walks all 1,314 symbols, and its
        # own docstring says it is deliberately uncached because "each
        # caller's own throttle already controls how often this runs".
        # That was true when it had TWO callers, both throttled. It now
        # has SEVEN, and five of them have no throttle at all -- the
        # shortlist, the movers, the extras.
        #
        # So the rows are computed ONCE per build and shared. Every
        # caller in one snapshot now sees the SAME rows, which is also
        # more honest than seven passes taken milliseconds apart
        # disagreeing about the same market.
        #
        # Cleared here, at the top, rather than expiring on a timer: a
        # build that takes twenty seconds must not recompute halfway
        # through, and the next build must never reuse this one.
        self._gl_rows_this_build = None

        # Snapshot every engine-owned mutable structure ONCE, up
        # front, before any of the _build_X methods below touch it.
        # engine.open_positions / closed_positions / entry_blocked
        # are mutated live by the feed thread (core/engine.py's
        # _enter()/_exit(), on every tick) while this refresh runs
        # on main.py's own loop -- a different thread. Iterating the
        # live dict/list directly from here can and did crash with
        # "RuntimeError: dictionary changed size during iteration"
        # (2026-07-23) the moment a position opened or closed mid-
        # refresh. dict(...)/list(...) copy the whole structure in a
        # single C-level pass that holds the GIL throughout, so the
        # copy itself can't be interrupted by the other thread --
        # the standard, safe way to read a structure another thread
        # is concurrently mutating without adding a lock to the
        # engine's own hot path (which must never slow down).
        open_positions = dict(self.engine.open_positions)
        closed_positions = list(self.engine.closed_positions)
        entry_blocked = {
            symbol: dict(directions)
            for symbol, directions in dict(self.engine.entry_blocked).items()
        }

        breadth = self._build_breadth()
        gainers_losers = self._build_gainers_losers()
        performance = self._build_performance(closed_positions)
        # Built once and passed to build_calls() rather than rebuilt
        # inside it -- the shortlist is the expensive thing on this
        # snapshot and it runs once a second.
        shortlist = self._build_shortlist()

        snapshot = {
            "ready": True,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            # None during the session; the close time once trading has
            # stopped. Carried through every later rebuild so a manual
            # "Refresh now" in review mode cannot clear the banner.
            "session_ended": self._session_ended,
            "capital": self._build_capital(open_positions),
            # ---- THE NUMBER ON THE SCREEN NEEDS A DATE. 18 Aug 2026 ----
            #
            #     "IT IS STILL SHOWING FUNDS OF LAST CONNECTION TIME
            #      AS 431116 RS"
            #
            # "capital" above is the BOOK's purse. This is what DHAN
            # says, and when it was last asked. They are different
            # questions and were being answered by one number, which
            # is how a constant from 9 August passed for a live
            # balance for nine days.
            "broker_funds": self._safe_broker_funds(),
            # WHY EACH RANKED PICK DID OR DID NOT ALERT. 19 Aug 2026.
            # The ranker's own refusals are a different list -- those
            # are stocks it never ranked. This is the gap between
            # "kept by the ranker" and "reached his phone", which was
            # invisible and is where the best pick of the day went.
            "routing": self._safe_routing(),
            "advances": breadth["advances"],
            "declines": breadth["declines"],
            "unchanged": breadth["unchanged"],
            "universe_size": breadth["universe_size"],
            "gainers_losers": gainers_losers,
            "shortlist": shortlist,
            # THE ANSWER. Everything else on this page is working out.
            # ---- WHY, NOT WHAT. 3 August 2026. ----
            #
            #   "any one can open telegram , x and see the news, orders,
            #    results but thats not our aim in building the bot"
            #
            # Right. Reprinting a headline is what a feed does. This is
            # the story turned into a list of stocks with a direction, a
            # mechanism, whether the two readers agree, and whether the
            # tape is confirming it -- none of which is on Telegram.
            "causes": self.build_causes(gainers_losers),
            "calls": self.build_calls(shortlist, gainers_losers,
                                      open_positions),
            # Top 50 each side WITH the shortlist's reasons joined on --
            # the panel that replaced both of the above on the LIVE tab.
            "movers": self.build_movers(),
            "breakouts": self._build_breakouts(),
            "actions": self._build_actions(),
            "announcements": self._build_announcements(),
            "news": self._build_news(),
            # ONE ROW PER STOCK, not one row per message. The panel
            # this replaces printed every RSS item and every Telegram
            # message as its own paragraph -- see core/news_table.py.
            "news_table": self._build_news_table(),
            "market_intelligence": self._build_market_intelligence(
                breadth, gainers_losers, performance
            ),
            "book_analytics": self._build_book_analytics(
                open_positions, closed_positions
            ),
            "open_positions": self._build_open_positions(open_positions),
            "closed_positions": self._build_closed_positions(closed_positions),
            "risk_filters": self._build_risk_filters(entry_blocked),
            "performance": performance,
            "system_health": self._build_system_health(breadth["universe_size"]),
            # 2026-07-24 -- EXIT ALL popup's "Stop New Entries + Exit
            # All" option. Surfaced so the dashboard can show a
            # persistent banner while automated entries are paused,
            # not just the fire-and-forget click itself -- see
            # trading/trade_controller.py's is_new_entries_paused().
            "entries_paused": self.engine.trade_controller.is_new_entries_paused(),
            # 2026-07-29 -- "everything that bot knows must shown in
            # dashboard". Each of these was already computed and had
            # no way to reach the screen.
            "alerts": self.build_alerts(),
            "signal_counts": self.build_signal_counts(),
            "premarket": self.build_premarket(),
            "preopen": self._preopen_cached(),
            "calendar": self.build_calendar(),
            "results_today": self.build_results_today(),
            "watchlist": self._safe_watchlist(),
            # ---- THE TELEGRAM TAB. 30 August 2026. ----
            #
            #     "show me in another tab named Telegram, under this
            #      tab create a data structure for all channels
            #      (currently -10 channels) & display"
            #
            # One row per channel: when it last posted, when the bot
            # read it, how late that was, and which loop it is on. He
            # has asked twice what the bot last heard and from where,
            # and both times it had to be dug out of SQLite by hand.
            "telegram_channels": self._safe_channel_report(),
            # ---- WHICH STOCKS WERE BLOCKED, AND WHY. 30 Aug 2026. ----
            #
            #     "why still today i cannot see which stocks were
            #      blocked & reason"          -- the operator
            #
            # Because the name was never written down. See
            # core/decision_log.py: `refusals` is (date, at, reason, n)
            # and carries no symbol, while core/select.py has had
            # {symbol: reason} in its hand the whole time.
            "refused_today": self._safe_refused_today(),
            # ---- HE ASKED WHERE THE MONEY WENT. 16 August 2026. ----
            #
            #     "5$ completed within 5 days"
            #
            # AiBudget.status()'s own docstring says "For the dashboard
            # and the startup banner" -- and the dashboard had never
            # once called it. Spend was measured, stored, capped, and
            # on no screen: the same fault as delivery %, the run-up
            # reading and the watchlist panel, except this one is his
            # money.
            # ---- THE FLOOR, PUBLISHED. 17 August 2026. ----
            #
            #     "why stocks with below 50 rs cmp is showing on
            #      dashboard? we are not trading them right?"
            #
            # He is right on both counts. config.MIN_TRADABLE_PRICE_RS
            # is an ENTRY rule -- core/engine.py checks it twice, at
            # the breakout gate and again in _enter(), and 1,075
            # refusals are recorded as "under the Rs 50 floor -- never
            # tradeable". It is not a display rule, and nothing in
            # dashboard/state.py or core/ranker.py mentions it.
            #
            # So the Live table drew them, because it merges the raw
            # gainers list -- built from PRICES, not from the
            # tradeable universe -- with the ranked rows.
            #
            # Published here rather than hardcoded in board.html: the
            # screen must not carry its own copy of a rule, which is
            # the sediment core/rules.py exists to prevent.
            "min_tradable_price": float(MIN_TRADABLE_PRICE_RS),
            "ai_spend": self._safe_ai_spend(),
            "opportunity_memory": self._safe_opportunity_memory(),
            "broker_sync": self.build_broker_sync(open_positions),
            # Is there a stop at the BROKER, or only in this process?
            # 2 August 2026. He must be able to see the answer without
            # reading a log line -- the whole point of this feature is
            # what happens when the process is gone, and "I thought it
            # was on" is the failure it would fail as.
            "broker_stop": self.build_broker_stop(open_positions),
            "orders": self.build_orders(open_positions),
            "book": self.build_book(open_positions),
            "telegram": self.build_telegram(),
            "news_impact": self.build_news_impact(),
            "morning_brief": self.build_morning_brief(),
            "corporate_actions": self.build_corporate_actions(),
            "journal": self.build_journal(),
            # ---- WHAT THE BOT KNOWS, AND WHETHER IT MAY USE IT ----
            #      12 August 2026.
            #
            #   "bot is getting results, news. but i'm not sure whether
            #    bot knows it. stores it and reuses when ever the same
            #    situation arises."
            #
            # Eleven stores, 200,000 rows, and no panel had ever said
            # whether any of it reaches a decision. See core/knowledge.py
            # -- it is a census, not a signal: it reads row counts and
            # the import graph and computes nothing.
            "knowledge": self.build_knowledge(),
            "fifty_two_week": self.build_52w(),
            # ---- THE WHOLE ENVIRONMENT, AND WHEN IT BREAKS ----
            #      3 August 2026.
            # core/awareness.py and core/shock.py were written, tested
            # and wired to nothing for an afternoon. An engine no
            # caller reaches is a file, not a feature.
            # Which stocks are in NIFTY 50 and F&O, so the LIVE tables
            # can be narrowed the same way the pre-open panel already
            # is. 4 August 2026 -- his request, and the membership was
            # already loaded for build_preopen.
            "ranked": self.build_ranked(gainers_losers, open_positions),
            # The 09:15-09:30 early-bird lane -- see build_early()'s
            # docstring. Read by main.py alongside "ranked" and fed into
            # the same auto_entry.take() call.
            "early": self.build_early(gainers_losers, open_positions),
            # ---- THE WATCHLIST BUILDS ITSELF NOW. 6 August 2026. ----
            #
            #     "it must check for the stocks & add them to watchlist
            #      not me manual adding ... excellent , Great grades
            #      first ; next row belongs to stocks which are having
            #      results during day & next stocks which are moving
            #      intraday"
            #
            # core/watchlist_builder.py produced the right three rows
            # for an hour while being reachable from nothing. An
            # engine no caller reaches is a file, not a feature -- the
            # comment three lines above says exactly that, and I did
            # it again anyway.
            "auto_watchlist": self.build_auto_watchlist(gainers_losers,
                                                        open_positions),
            "members": self.build_members(),
            "fno": self.build_fno(gainers_losers),
            "awareness": self.build_awareness(breadth, gainers_losers),
            "shock": self.build_shock(gainers_losers, open_positions),
            # THE SWITCH, read back from the engine itself -- never
            # from config. If the page says TRADING and the engine is
            # only alerting, the number on his screen is a lie about
            # his own money. 5 August 2026.
            "bot_trading": self._bot_trading(),
            # Whether this morning's inputs actually arrived. On the
            # screen so an empty watchlist is never mistaken for a
            # quiet market. See core/morning_ready.py.
            "morning_ready": self._morning_ready(),
            # ---- IT SAID PAPER ON A LIVE BOT. 5 August 2026. ----
            #
            #   "dashboard is still showing paper mode - random pnl,
            #    margins"
            #
            # The page reads s.mode and falls back to "PAPER" when it
            # is missing. This key was never set, so it printed PAPER
            # every second of every LIVE session -- the single most
            # dangerous label on the screen, defaulting to the
            # reassuring answer. Exactly what /api/mode's own docstring
            # warns against.
            "mode": self._trading_mode(),
            # ---- THE CHIPS, EVERYWHERE. 5 August 2026. ----
            #
            #   "I BROUGHT 9 FUCKING PRO CHANNELS THEY ARE NOT BEING
            #    USED PROPERLY . EVEN IF BOT USED , IT DOESN'T SHOW TO
            #    USER ON DASHBOARD."
            #
            # result_tag was computed for every stock and drawn for
            # about thirty -- only the rows the ranker named. SHILPAMED
            # read EXCELLENT and never appeared there, so the chip
            # showed him nothing on the best name of the day.
            #
            # One map, symbol -> tag, so the chip can be drawn beside a
            # symbol ANYWHERE it appears: gainers, losers, watchlist,
            # F&O, positions.
            "result_tags": self._result_tags_today(),
            "result_details": self.result_details(),
        }

        # ---- THE READING GOES ON EVERY ROW HE CAN SEE. 31 Aug ----
        #
        #     "Buying pressure / order flow / delta for all stocks on
        #      dashboard except 1/2 stocks"      -- the operator
        #
        # build_ranked() attaches flow, shape and trend to the rows
        # that CLEARED the gates -- three of them that afternoon. The
        # board draws the gainers and the refused rows too, so 146 of
        # 149 rows carried nothing and printed "not trading yet" over
        # stocks up eleven percent.
        #
        # Done here, after the payload is assembled, so it reaches
        # every list the board reads from and cannot drift out of step
        # with whichever of them the page happens to draw.
        ranked = snapshot.get("ranked") or {}
        self._widen_flow_to_the_board(
            ranked.get("rows"),
            (snapshot.get("gainers_losers") or {}).get("gainers"),
            ranked.get("refused_rows"))
        return snapshot

    def _result_tags_today(self):
        """{symbol: "EXCELLENT"|"GOOD"|"AVOID"} for everything that
        reported today. Cached per session -- the channels do not
        republish a result, and this runs on the refresh loop."""
        from datetime import timedelta
        today = datetime.now().strftime("%Y-%m-%d")
        cutoff = (datetime.now() - timedelta(hours=36)).isoformat()
        cached = getattr(self, "_tag_cache", None)
        if cached and cached.get("day") == today:
            return cached["tags"]
        tags, detail = {}, {}
        if self.telegram is not None:
            try:
                # symbols_in() PARSES TEXT -- it does not list symbols.
                # Checked against the real class rather than assumed
                # from the name. The store is the list.
                import sqlite3
                con = sqlite3.connect(self.telegram.db_path)
                named = {
                    part.strip().upper()
                    for (row,) in con.execute(
                        # 36 HOURS, NOT "TODAY". 6 August 2026 --
                        #   "now time 00:13 so no chips visible i guess"
                        # He was right. At 00:13 "today" has no messages
                        # at all, so every chip vanished at midnight and
                        # came back only when the channels woke up.
                        # Results published after yesterday's close are
                        # exactly what he trades on the next morning.
                        "select symbols from messages where at >= ? "
                        "and symbols is not null and symbols <> ''",
                        (cutoff,))
                    for part in str(row).split(",") if part.strip()}
                con.close()
                for symbol in named:
                    got = self._result_tag_for(symbol)
                    if got and got.get("tag"):
                        tags[symbol] = got["tag"]
                        # THE EVIDENCE, KEPT. A chip he cannot
                        # interrogate is a chip he has to take on
                        # trust, and he has been asked to do that
                        # once too often already.
                        detail[symbol] = {
                            "tag": got["tag"],
                            "score": got.get("score"),
                            "why": got.get("why") or [],
                            "against": got.get("against") or [],
                            "images": got.get("images"),
                            "channels": got.get("channels") or [],
                            "fields": got.get("fields") or {},
                        }

                # ---- WHERE THE MARGIN CAME FROM. 12 August 2026. ----
                #
                #     "i took trade after seeing excellent reuslts &
                #      it dragged me around 10K now"
                #
                # PANAMAPET printed PULSE EXCELLENT + CLEAN and closed
                # at a stop-out. GANDHAR had printed the same shape
                # twenty days earlier and SAVITA the same week -- three
                # names that buy base oil, one shut strait, one margin.
                # No single card can see that. This pass can, because
                # by now every name that reported has been read.
                #
                # It adds a CHIP and a NOTE. It does not touch the tag.
                # See result_tag.py and SHILPAMED, 5 August.
                from core import margin_driver, sector_map
                grid = []
                for sym, det in detail.items():
                    dp = margin_driver.margin_delta_pp(det.get("fields"))
                    if dp is None:
                        continue
                    grid.append({"symbol": sym, "delta_pp": dp,
                                 "sector": sector_map.sector_of(sym),
                                 "at": today})
                for sym, det in detail.items():
                    got = margin_driver.assess(
                        sym, det.get("fields"), peers=grid,
                        sector=sector_map.sector_of(sym))
                    det.pop("fields", None)
                    if not got:
                        continue
                    det["margin_driver"] = got
                    # The chips are drawn off `why`, so the line goes
                    # in there to be seen, and the evidence with it.
                    det["why"] = ([f'{got["chip"]}: {got["why"][0]}']
                                  + (det.get("why") or [])
                                  + [f"  {w}" for w in got["why"][1:]])
            except Exception:                              # noqa: BLE001
                tags, detail = {}, {}
        self._tag_cache = {"day": today, "tags": tags, "detail": detail}
        return tags

    def result_details(self):
        """{symbol: {tag, score, why[], against[], images, channels}}.

        Why the chip says what it says, in the words of the cards it
        was read from. Populated by the same pass that builds the
        chips, so it can never drift out of step with them.
        """
        self._result_tags_today()
        return (getattr(self, "_tag_cache", None) or {}).get("detail") or {}

    def _morning_ready(self):
        """Did this morning's inputs arrive? Never guessed."""
        try:
            from core import morning_ready
            return morning_ready.check()
        except Exception as exc:                           # noqa: BLE001
            return {"ready": None, "checks": [],
                    "why_not": [f"could not check ({exc})"]}

    def _trading_mode(self):
        """LIVE or PAPER, from config. Never guessed."""
        try:
            from config import TRADING_MODE
            return str(TRADING_MODE).upper()
        except Exception:                                  # noqa: BLE001
            return "UNKNOWN"

    def _bot_trading(self):
        """Is the bot actually placing orders right now?

            "control = bot trading on / off"
            "it must follow me . not i needs to go back on bot."

        Read live off engine.alert_only, so the button can never drift
        from what the engine is doing.
        """
        engine = getattr(self, "engine", None)
        if engine is None:
            return {"on": False, "known": False,
                    "note": "no engine -- nothing can trade"}
        alert_only = getattr(engine, "alert_only", None)
        if alert_only is None:
            return {"on": False, "known": False,
                    "note": "the engine did not say"}
        held = len(getattr(engine, "open_positions", {}) or {})
        return {
            "on": not alert_only,
            "known": True,
            "open_positions": held,
            "note": ("placing REAL orders" if not alert_only else
                     "watching only -- it alerts and records, "
                     "places nothing"),
            # Said out loud on the page, because it is the one thing
            # about this switch that will surprise him.
            "resets_on_restart": True,
        }

    # --------------------------------------------------

    def _build_breadth(self):
        """See module docstring's "SWITCHED 2026-07-24" section --
        prev-close based, not day-open. prev_close comes from
        engine.get_circuit_snapshot() (circuit_monitor's REST poll,
        already running for circuit-proximity checking and Top 50
        Gainers/Losers); last_price prefers market_data's own tick
        feed, falling back to the snapshot's LTP for a symbol that
        hasn't ticked yet this session.

        Throttled to MARKET_BREADTH_REFRESH_SECONDS (5s, 2026-07-24
        operator instruction) -- same cached-result-until-stale
        pattern as _build_stock_gainers_losers()/
        _build_sector_gainers_losers() below, previously unthrottled
        (rebuilt on every _build() call, i.e. every
        DASHBOARD_REFRESH_INTERVAL_SECONDS =1s). _build_sectors()
        (the green/red list) is derived from THIS method's per_symbol
        output on every _build() call regardless, so it inherits the
        same 5s effective cadence for free -- no separate throttle
        needed there.
        """
        now = time.monotonic()
        if self._breadth_cache is not None and \
                now - self._breadth_built_at < MARKET_BREADTH_REFRESH_SECONDS:
            return self._breadth_cache

        symbols = self.master_loader.all_symbols()
        snapshot = self.engine.get_circuit_snapshot()
        per_symbol = {}
        advances = declines = unchanged = 0

        for symbol in symbols:
            quote = snapshot.get(symbol)
            prev_close = quote.get("prev_close") if quote else None
            last_price = self.market_data.get_latest_price(symbol)
            if last_price is None and quote is not None:
                last_price = quote.get("last_price")

            if not prev_close or last_price is None:
                unchanged += 1
                per_symbol[symbol] = {
                    "change_pct": 0.0, "status": "unchanged", "last_price": last_price,
                }
                continue

            # ---- MEASURE THE TWO SOURCES. 10 August 2026. ----
            # This line is NSE's own definition and it is correct --
            # verified against the 07 Aug bhavcopy, 2,416 EQ symbols,
            # zero mismatches. What was never checked is whether the
            # prev_close feeding it, polled from REST, matches the one
            # arriving free on every tick. core/tick_ohlc.py records
            # any disagreement; nothing here changes behaviour.
            try:
                from core import tick_ohlc
                tick_ohlc.compare(symbol, quote)
            except Exception:                              # noqa: BLE001
                pass

            change_pct = (last_price - prev_close) / prev_close * 100

            # 2026-07-24 -- a split/bonus prev_close artifact (JLHL's
            # 2:10 split showed up as a fake ~-80% "decline"); the
            # exchange's own circuit band says this move is
            # impossible, so prev_close is untrustworthy for this
            # symbol today. Counted "unchanged", same bucket and same
            # "never guess" reasoning as missing prev_close above --
            # keeps the three published counts summing to the full
            # universe size, as specified, without misclassifying a
            # data artifact as a real advance or decline.
            if not _is_plausible_move(
                change_pct, prev_close,
                quote.get("upper_circuit_limit"), quote.get("lower_circuit_limit"),
            ):
                unchanged += 1
                per_symbol[symbol] = {
                    "change_pct": 0.0, "status": "unchanged", "last_price": last_price,
                }
                continue

            if last_price > prev_close:
                advances += 1
                status = "advance"
            elif last_price < prev_close:
                declines += 1
                status = "decline"
            else:
                unchanged += 1
                status = "unchanged"

            per_symbol[symbol] = {
                "change_pct": change_pct,
                "status": status,
                "last_price": last_price,
            }

        result = {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "universe_size": len(symbols),
            "per_symbol": per_symbol,
        }
        self._breadth_cache = result
        self._breadth_built_at = now
        return result

    def _build_sectors(self, per_symbol):
        """
        green/red only -- which sectors are net up/down today,
        purely derived from per_symbol (already built by
        _build_breadth()). SWITCHED 2026-07-24 along with breadth
        itself to PREV-CLOSE based (see module docstring's
        "SWITCHED 2026-07-24" section) -- no separate change here,
        this method just averages whatever per_symbol already
        computed. The former "heatmap" ranked list that used to live
        on this same return value is GONE as of 2026-07-23 evening
        -- superseded by _build_gainers_losers()'s sector_gainers/
        sector_losers (also prev-close based, ranked, styled like
        the stock Top 50 Gainers/Losers table -- see that method's
        own docstring). green/red now share the exact same
        reference point as sector_gainers/sector_losers -- only the
        ranked-list presentation moved to a different method, the
        underlying data is consistent across both.
        """
        sector_changes = {}
        for symbol, data in per_symbol.items():
            record = self.master_loader.get_by_symbol(symbol)
            if record is None:
                continue
            sector = record.get("SECTOR") or "UNKNOWN"
            sector_changes.setdefault(sector, []).append(data["change_pct"])

        green, red = [], []
        for sector, changes in sector_changes.items():
            avg = sum(changes) / len(changes) if changes else 0.0
            (green if avg >= 0 else red).append(sector)

        return {"green": sorted(green), "red": sorted(red)}

    def card_for(self, symbol):
        """Everything the bot holds about one stock. The operator's
        "recall the memory of any stock on demand"."""
        try:
            return self.stock_card.build(symbol)
        except Exception as exc:                           # noqa: BLE001
            return {"found": False, "symbol": symbol, "error": str(exc)}

    def build_alerts(self):
        """The plain-English notes the engine has raised today --
        positions the bot was not allowed to close, trailing-stop
        breaches it reported instead of acting on, and news that
        landed on something held.

        These existed from 29 July but reached the TERMINAL only.
        get_manual_alerts() had zero callers -- found in that evening's
        integration check.
        """
        try:
            rows = self.engine.get_manual_alerts() or []
        except Exception:                                  # noqa: BLE001
            return []

        # RANKED, not in arrival order -- 30 July 2026.
        #
        #     "Rank before considering. Bot will place those stocks in
        #      alert box. we agreed bot will not trade"
        #
        # The engine raises an alert the instant a signal fires, so the
        # list was in the order the tape happened to produce them. That
        # is the same first-come-first-served that filled the book with
        # THYROCARE at 0.03x volume while KSB was refused at 715x -- and
        # an alert box read top-down reproduces the bug by eye.
        #
        # The score comes from the shortlist, which has already weighed
        # the filing, the results grade, the volume, the pre-open
        # imbalance and the channel events. An alert for a stock the
        # shortlist never scored keeps its place by time, at the bottom,
        # rather than being dropped -- the bot saw something there.
        try:
            scores = {r.get("symbol"): r.get("score")
                      for r in (self._build_shortlist() or {}).get("rows", [])}
        except Exception:                                  # noqa: BLE001
            scores = {}
        if not scores:
            return rows

        def _symbol_of(row):
            if isinstance(row, dict):
                return (row.get("symbol")
                        or str(row.get("text") or "").split(" ")[1:2] or [None])[0] \
                    if not row.get("symbol") else row.get("symbol")
            return None

        ordered = []
        for index, row in enumerate(rows):
            symbol = _symbol_of(row)
            score = scores.get(symbol)
            if isinstance(row, dict):
                row = dict(row)
                row["score"] = score
            ordered.append((0 if score is None else 1,
                            score or 0.0, -index, row))
        # scored first, highest score first, newest first within a tie
        ordered.sort(key=lambda item: (-item[0], -item[1], -item[2]))
        return [item[3] for item in ordered]

    def build_signal_counts(self):
        """Taken vs refused so far today, straight off the journal
        buffer. Answers "is the bot seeing things and saying no" at a
        glance, instead of only after close."""
        try:
            journal = getattr(self.engine, "signal_journal", None)
            if journal is None:
                return None
            taken, refused = journal.counts()
            return {"taken": taken, "refused": refused}
        except Exception:                                  # noqa: BLE001
            return None

    def build_premarket(self):
        """The overnight world -- 18 numbers from core/premarket.py.
        Built 28 July, never shown."""
        try:
            return self.premarket.snapshot() if self.premarket else None
        except Exception:                                  # noqa: BLE001
            return None

    def build_news_impact(self):
        """Every story, and the stocks it touches.

            "every news will be connected to their respective stocks in
             memory brain and the same thing will be displayed upon
             demand"              -- operator, 30 July 2026

        Until ANTHROPIC_API_KEY is set the links carry direction
        UNKNOWN -- "these stocks share the subject", which is a
        different and weaker claim than "these stocks gain", and is
        labelled as such on screen.
        """
        try:
            if self.news_impact is None:
                return {"available": False, "rows": [],
                        "note": "impact memory not wired"}
            snapshot = self.news_impact.status()
            rows = self.news_impact.recent(limit=25, hours=36)
            # THE SECTOR IS THE MISSING LINK, added 30 July 2026.
            #
            #     "we want complete picture of news recvd = stock -
            #      sector linked = memory map"     -- operator
            #
            # The store knows story -> stock. The master file knows stock
            # -> sector. Neither knew the chain, so the panel could say
            # "this story touches TVSMOTOR" and never "the auto sector has
            # four stories on it this morning" -- which is the question
            # that decides whether a move is one company or a theme.
            #
            # Joined HERE rather than in core/news_impact.py on purpose:
            # that module must not grow a dependency on the master file
            # for a presentation concern.
            sector_of = {}
            if self.master_loader is not None:
                for row in rows:
                    for bucket in ("positive", "negative", "unknown"):
                        for hit in (row.get(bucket) or []):
                            symbol = hit.get("symbol")
                            if not symbol or symbol in sector_of:
                                continue
                            record = self.master_loader.get_by_symbol(symbol)
                            sector_of[symbol] = ((record or {}).get("SECTOR")
                                                 or "—")
                            hit["sector"] = sector_of[symbol]
                    # second pass so every hit carries it, cached or not
                    for bucket in ("positive", "negative", "unknown"):
                        for hit in (row.get(bucket) or []):
                            hit.setdefault("sector",
                                           sector_of.get(hit.get("symbol"), "—"))
            snapshot["rows"] = rows
            snapshot["available"] = True
            return snapshot
        except Exception as exc:                           # noqa: BLE001
            warn(f"[IMPACT] Panel build failed: {exc}")
            return {"available": False, "rows": [], "note": str(exc)}

    def build_telegram(self):
        """The four channels the operator watches on a second screen.

            "separate screens for NSE; Trading; Telegram for continous
             updates. Now we will replace everything by our Dashboard."

        Reading only. Nothing in this panel reaches core/engine.py --
        these are anonymous third-party channels, the bot cannot tell
        a paid promotion from a genuine call, and the standing rule is
        that an entry needs a real reason.
        """
        try:
            if self.telegram is None:
                return {"available": False, "connected": False, "rows": [],
                        "note": "not set up -- py tools/telegram_setup.py"}
            snap = self.telegram.snapshot()
            # IS IT STILL LISTENING? Added 30 July 2026. Until then the
            # feed was polled once at startup and never again, so the
            # panel showed 08:59's messages all day and looked exactly
            # like a panel that was up to date. A reading panel that has
            # silently stopped reading is worse than an empty one --
            # nothing on screen distinguished the two.
            try:
                snap["polling"] = bool(self.telegram.poller_alive())
            except Exception:                              # noqa: BLE001
                snap["polling"] = None
            return snap
        except Exception as exc:                           # noqa: BLE001
            warn(f"[TELEGRAM] Panel build failed: {exc}")
            return {"available": False, "connected": False, "rows": [],
                    "note": f"error: {exc}"}

    def build_52w(self):
        """How many of our stocks are at a 52-week high or low today.

        The reference layout asks for these two counts and nothing in the
        bot computed them -- while data/daily_candles.db holds 1.08m bars
        back to 2016 for 2,523 symbols. Derivable all along, never derived.

        WHY IT IS WORTH SEEING: breadth says how many rose today. This
        says how many are at a level they have not seen in a year, which
        is a different and slower fact. A market where 262 rose but only
        4 made new highs is not the same market as one where 84 did.

        Throttled hard -- one SQL pass over a year of bars is far too
        heavy for the dashboard's refresh loop, and this number changes
        slowly by construction.
        """
        # NEVER inside the refresh loop.
        #
        # The first version ran the year-long GROUP BY on every refresh
        # with only a per-instance cache, so each new DashboardState paid
        # for it again -- 1.08m rows scanned, and it hung the test suite.
        #
        # The band extremes are now read ONCE per process (module-level
        # cache) and only if a caller has actually asked for the panel.
        # A 52-week high does not change between two dashboard refreshes,
        # so there is nothing to gain from recomputing it and a whole
        # refresh loop to lose.
        import time
        now = time.time()
        cached = _52W_CACHE.get("bands")
        out = {"available": False, "highs": 0, "lows": 0, "note": ""}
        try:
            import os
            import sqlite3
            from datetime import date, timedelta
            path = os.path.join("data", "daily_candles.db")
            if not os.path.exists(path):
                out["note"] = "daily_candles.db not found"
                return out
            stale = cached is None or now - _52W_CACHE.get("at", 0) > 3600
            if stale and not _52W_CACHE.get("running"):
                # OFF THE CALLING THREAD. build_52w() runs inside
                # dashboard_state.refresh(), which main.py drives from its
                # MAIN LOOP -- the same loop that checks square-off time
                # and the feed watchdog. A 3.5s scan there is a 3.5s stall
                # in the bot's own heartbeat, and this project has already
                # been bitten once by blocking that path (the 09:15 tick
                # backlog that lost 646 symbols to staleness).
                #
                # So the first request starts a worker and returns
                # "computing"; the next refresh a few seconds later has it.
                # A 52-week high can wait ten seconds.
                _52W_CACHE["running"] = True

                def _scan():
                    try:
                        since = (date.today()
                                 - timedelta(days=365)).isoformat()
                        conn = sqlite3.connect(f"file:{path}?mode=ro",
                                               uri=True)
                        bands = {r[0]: (r[1], r[2]) for r in conn.execute(
                            "SELECT symbol, MAX(high), MIN(low) "
                            "FROM daily_bars WHERE date >= ? "
                            "GROUP BY symbol", (since,))}
                        conn.close()
                        _52W_CACHE["bands"] = bands
                        _52W_CACHE["at"] = time.time()
                    except Exception as exc:               # noqa: BLE001
                        diagnostic(f"[52W] scan failed: {exc}")
                    finally:
                        _52W_CACHE["running"] = False

                threading.Thread(target=_scan, name="52w-scan",
                                 daemon=True).start()
            if cached is None:
                out["note"] = "computing from a year of daily bars…"
                return out
            extremes = cached

            snapshot = self.engine.get_circuit_snapshot() or {}
            highs, lows, checked = [], [], 0
            for symbol, quote in snapshot.items():
                band = extremes.get(symbol)
                if not band or band[0] is None or band[1] is None:
                    continue
                last = quote.get("last_price") or quote.get("ltp")
                if not last:
                    continue
                checked += 1
                # At or through the band. Today's own bar is included in
                # the history only up to yesterday, so ">=" is right.
                if last >= band[0]:
                    highs.append(symbol)
                elif last <= band[1]:
                    lows.append(symbol)
            out = {"available": True, "highs": len(highs), "lows": len(lows),
                   "checked": checked,
                   "high_symbols": sorted(highs)[:25],
                   "low_symbols": sorted(lows)[:25],
                   "note": f"{checked} symbols with a year of history"}
        except Exception as exc:                           # noqa: BLE001
            out["note"] = f"error: {exc}"
        return out

    def build_knowledge(self):
        """The census of every store the bot keeps -- core/knowledge.py.

        Answers his question directly: for each thing the bot collects,
        does it reach a DECISION, only the SCREEN, or nowhere at all.

        Cheap enough to run every refresh (eleven `select count(*)`
        against local SQLite, all read-only) but cached for a minute
        anyway, because none of these numbers move faster than that and
        the refresh loop also drives the live price tables.

        Never raises. A census that could break the dashboard would be
        worse than no census.
        """
        import time
        now_s = time.time()
        cached = getattr(self, "_knowledge_cache", None)
        if cached and now_s - cached[0] < 60.0:
            return cached[1]
        try:
            from core import knowledge
            out = knowledge.census()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[KNOWLEDGE] Census failed: {exc}")
            out = {"available": False, "stores": [], "problems": [],
                   "empty": [], "stale": [], "counts": {},
                   "verdict": f"could not be read ({exc})"}
        self._knowledge_cache = (now_s, out)
        return out

    def build_journal(self):
        """Every signal today, taken AND refused, WITH THE REASON.

            "we will get mostly idea where we are doing wrong & what
             needs to be corrected"          -- operator, 30 July 2026

        Until now only counts() reached the screen, so "6 taken / 3
        refused" was visible and WHICH three, and why, was not. The
        reasons are the entire diagnostic.

        Measured on this session at 12:45 -- 609 signals, and the single
        biggest refusal reason by a wide margin:

            151  book full (10 positions)
             42  reports today, numbers not out yet
             28  against the tape (SHORT_ONLY) -- allowed anyway

        "book full" is not a judgement about the stock. It means ten other
        names broke out first, which is an accident of timing -- and
        core/engine.py's own comment calls it "THE most important row in
        the journal" for exactly that reason.
        """
        journal = getattr(self.engine, "signal_journal", None)
        if journal is None or not hasattr(journal, "today"):
            return {"available": False, "rows": [], "by_reason": [],
                    "note": "signal journal not wired"}
        try:
            rows = journal.today() or []
        except Exception as exc:                           # noqa: BLE001
            warn(f"[JOURNAL] Panel build failed: {exc}")
            return {"available": False, "rows": [], "by_reason": [],
                    "note": f"error: {exc}"}

        counts = {}
        slot_refused = 0
        for r in rows:
            if r.get("taken"):
                continue
            why = (r.get("refused_why") or "").strip()
            if not why:
                continue
            # Collapse the confirmation count so "book full (10) -- 0 of 3"
            # and "-- 1 of 3" group together. The cap is the reason; how
            # many confirmations were behind it is detail.
            key = why.split(" -- ")[0]
            counts[key] = counts.get(key, 0) + 1
            if key.startswith("book full"):
                slot_refused += 1
        by_reason = sorted(counts.items(), key=lambda kv: -kv[1])
        return {
            "available": True,
            "total": len(rows),
            "taken": sum(1 for r in rows if r.get("taken")),
            "by_reason": [{"why": k, "count": v} for k, v in by_reason],
            # The headline number for the first-come-first-served question.
            "slot_refused": slot_refused,
            "rows": [{"symbol": r.get("symbol"),
                      "direction": r.get("direction"),
                      "sector": r.get("sector"),
                      "first_seen": str(r.get("first_seen") or ""),
                      "break_price": r.get("break_price"),
                      "taken": bool(r.get("taken")),
                      "refused_why": r.get("refused_why"),
                      "open_at_signal": r.get("open_positions_at_signal"),
                      "volume_mult": r.get("volume_mult"),
                      "results_grade": r.get("results_grade"),
                      "confirmations": r.get("confirmations"),
                      "fired": r.get("fired_count")}
                     for r in rows[:120]],
        }

    def build_corporate_actions(self):
        """Dividends, splits, bonuses and demergers, with ex-dates.

        REAL corporate actions -- not to be confused with _build_actions()
        above, which is the manual click log. Two different things with
        confusingly similar names, and the v3 panel was reading the wrong
        one until 30 July 2026.

        Why the operator needs to see this: an ex-date inside a holding
        period is a VETO, and the bot applies it silently. On this
        session's own startup:

            [MEMORY] Price-distorting corporate actions in effect around
            today -- these will NOT be traded: INOXGREEN (DEMERGER)

        That is the bot refusing a stock for a good reason the screen
        never showed.
        """
        if self.stock_memory is None:
            return {"available": False, "rows": [], "counts": {},
                    "note": "stock memory not wired"}
        try:
            counts = self.stock_memory.event_counts() or {}
            blocked = sorted(self.stock_memory.price_distorting_symbols() or [])
            # ONE query, not 973.
            #
            # The first version of this looped over every master symbol
            # calling facts_for(symbol) -- 973 separate SQL round trips on
            # EVERY dashboard refresh, several times a minute. It hung the
            # test suite outright, and on the live dashboard it would have
            # made the refresh loop slower and slower as the universe grew,
            # for a panel that changes about twice a week.
            #
            # all_symbols_with_facts() already does exactly this in a
            # single windowed query and returns it grouped by symbol. It
            # existed before I wrote the loop.
            grouped = self.stock_memory.all_symbols_with_facts(
                window_days=21) or {}
            rows = []
            for symbol, facts in grouped.items():
                for fact in facts:
                    ex = fact.get("ex_date")
                    rows.append({"symbol": symbol,
                                 "action": fact.get("action_type"),
                                 "ex_date": (ex.isoformat()
                                             if hasattr(ex, "isoformat")
                                             else (str(ex) if ex else None)),
                                 "detail": fact.get("detail"),
                                 "source": fact.get("source")})
            rows.sort(key=lambda r: r.get("ex_date") or "")
            return {"available": True, "counts": counts,
                    "rows": rows[:40], "total": self.stock_memory.count(),
                    # The ones the bot will REFUSE today. This is the line
                    # that turns a silent veto into a visible one.
                    "not_traded": blocked}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[MEMORY] Corporate actions panel failed: {exc}")
            return {"available": False, "rows": [], "counts": {},
                    "note": f"error: {exc}"}

    def build_morning_brief(self):
        """The overnight brief -- opinion, clearly labelled as opinion.

        Fail-quiet like every other optional panel: no key, no client or
        a bad answer costs this panel and nothing else.
        """
        if self.morning_brief is None:
            return {"available": False,
                    "note": "morning brief not wired -- needs "
                            "ANTHROPIC_API_KEY and core/morning_brief.py"}
        try:
            return self.morning_brief.snapshot()
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "note": f"brief unavailable ({exc})"}

    def _build_institutional(self):
        """FII / DII, from whichever source actually has it.

        WAS A PLACEHOLDER SINCE IT WAS WRITTEN. The operator's first
        question of the session:

            "FII / DII set in config (EOD) ? these are still as a place
             holders . pls check with dhan if any of them we are recvng ??"

        Dhan does not publish it. NSE does, after the close. And the
        operator's own News Pulse channel reposts it within minutes --
        so the number was already on disk in telegram.db, rendered as a
        chat message and read as data by nobody.

        Order: the real fetcher, then the channels, then config. Each
        one says where it came from, because "FII +3,623cr" from NSE and
        the same figure quoted in a chat message are not equally
        authoritative and the screen should not pretend otherwise.
        """
        if self.market_flows is not None:
            snap = self.market_flows.snapshot()
            if snap.get("available"):
                snap.setdefault("source", "NSE")
                return snap
        try:
            from core.market_flows import from_telegram
            found = from_telegram(self.telegram)
        except Exception:                                  # noqa: BLE001
            found = None
        if found:
            # ---- SAY WHICH KIND OF SOURCE. 31 August 2026. ----
            #
            # Two channels carry this figure and they are not equally
            # reliable. News Pulse types it; Day Trader Telugu posts a
            # picture of it, which has to be OCR'd, and OCR has already
            # been caught inserting a digit -- one stored card reads
            # -50,359.8 where the image plainly shows -5,039.8.
            #
            # A figure read off a picture is still worth showing; it is
            # usually the first one to arrive. But the screen must not
            # present it as if someone had typed it.
            via = found.get("via")
            note = "quoted by a Telegram channel, not read from NSE directly"
            if via == "image":
                note = ("read off a picture posted by a Telegram channel. "
                        "Not typed, not from NSE -- treat as indicative "
                        "until a typed figure confirms it")
            elif found.get("disagrees_with_image"):
                note = (note + ". A picture on another channel gave a "
                        "different number; the typed one is shown")
            return {"available": True,
                    "fii_cr": found.get("fii_cr"),
                    "dii_cr": found.get("dii_cr"),
                    "as_of": found.get("as_of"),
                    "source": found.get("source"),
                    "via": via,
                    "note": note}
        return {"available": FII_NET_CR is not None or DII_NET_CR is not None,
                "fii_cr": FII_NET_CR, "dii_cr": DII_NET_CR,
                "source": "config",
                "note": "set by hand in config (EOD)"}

    def build_broker_sync(self, open_positions):
        """Does our book match Dhan's?

        Never raises and never corrects. A panel that quietly fixed a
        mismatch would hide the one thing worth knowing.
        """
        if self.broker_sync is None:
            return {"available": False, "in_sync": None,
                    "note": "sync not wired"}
        try:
            return self.broker_sync.check(open_positions)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SYNC] Panel build failed: {exc}")
            return {"available": False, "in_sync": None, "note": str(exc)}

    # Dhan is polled at most this often for the order book. Same
    # reasoning as BrokerSync: it is a REST call on the account the
    # orders go through, and being rate-limited mid-session is worse
    # than a five-second-old order list.
    ORDERS_MIN_SECONDS = 5

    def build_orders(self, open_positions=None):
        """Today's orders at the broker: filled, pending, rejected.

        ---- THE PANEL THAT WOULD HAVE SAVED HIM RS 11,000 ----

            "no NIFTY 50, BANKNIFTY, ORDERS TABLE = EXECUTED, PENDING,
             CANCELLED"
            "1st click no response & no way to check in dashboard, then
             i clicked the second one. now both orders gave me loss of
             huge amount"
                                        -- operator, 3 August 2026

        PENDING is the reason this exists. A filled order shows up as a
        position eventually; an order sitting unconfirmed at the
        exchange shows up NOWHERE, and that silence is what made him
        click BUY a second time on YASHO at 09:18.

        Grouped rather than listed flat, because the question he is
        actually asking is "is anything of mine still in flight?" --
        one number, at the top, answerable in a glance.

        Never raises. `available: False` means WE COULD NOT ASK, which
        must never be drawn the same way as "you have no orders".
        """
        import time

        executor = getattr(self.engine, "execution", None)
        executor = getattr(executor, "executor", executor)
        reader = getattr(executor, "orders", None)
        if reader is None:
            return {"available": False,
                    "note": "PAPER mode -- there is no broker order book."}

        now = time.monotonic()
        cached = getattr(self, "_orders_cache", None)
        if cached is not None and now - getattr(self, "_orders_at", 0.0) \
                < self.ORDERS_MIN_SECONDS:
            # The broker rows are cached; the HOLDING/CLOSED labels are
            # not. His book changes faster than this panel refetches,
            # and a row still showing HOLDING after he exited would be
            # a lie with money behind it.
            return self._label_orders(cached, open_positions)

        try:
            rows = reader()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[ORDERS] Could not read the order book: {exc}")
            return {"available": False, "note": f"could not ask Dhan: {exc}"}
        if rows is None:
            return {"available": False,
                    "note": "could not reach Dhan -- this is NOT 'no orders'"}

        # Dhan's own vocabulary, mapped onto the three words he asked
        # for. TRANSIT and PENDING both mean "at the exchange, not done"
        # -- the state that had nowhere to show.
        LIVE = ("PENDING", "TRANSIT", "PART_TRADED", "PARTIALLY_TRADED",
                "OPEN", "TRIGGER_PENDING", "MODIFIED", "VALIDATION_PENDING")
        DONE = ("TRADED", "EXECUTED", "COMPLETE", "FILLED")
        GONE = ("CANCELLED", "CANCELED", "REJECTED", "EXPIRED")

        pending, filled, cancelled = [], [], []
        for row in (rows if isinstance(rows, list) else []):
            status = str(row.get("orderStatus") or "").strip().upper()
            item = {
                "symbol": row.get("tradingSymbol") or row.get("symbol") or "",
                "side": str(row.get("transactionType") or "").upper(),
                "qty": row.get("quantity"),
                "filled_qty": row.get("filledQty") or row.get("filled_qty"),
                "price": row.get("averageTradedPrice") or row.get("price"),
                "product": row.get("productType") or "",
                "type": row.get("orderType") or "",
                "status": status,
                "order_id": row.get("orderId") or row.get("order_id") or "",
                "at": row.get("updateTime") or row.get("createTime") or "",
                "why": row.get("omsErrorDescription") or "",
            }
            if status in LIVE:
                pending.append(item)
            elif status in DONE:
                filled.append(item)
            elif status in GONE:
                cancelled.append(item)
            else:
                # An unknown status is treated as STILL IN FLIGHT. The
                # dangerous mistake is calling something finished when
                # it is not -- that is the mistake that cost him money.
                item["status"] = status or "UNKNOWN"
                pending.append(item)

        out = {
            "available": True,
            "pending": pending,
            "filled": filled,
            "cancelled": cancelled,
            "n_pending": len(pending),
            "n_filled": len(filled),
            "n_cancelled": len(cancelled),
        }
        self._orders_cache = out
        self._orders_at = now
        return self._label_orders(out, open_positions)

    # ---- FIVE STATES, EACH ONE A DIFFERENT COLOUR ----
    #      3 August 2026.
    #
    #   "TRADEBOOK IS NOT VISIBLE AS IT IS IN SMALL BOX . write some
    #    logic to color code them without moving the mouse to check
    #    everytime ... user must recognise that trade is executed or
    #    not. i gave an example thats it. u need to think & apply logic"
    #
    # His example -- green while open, normal once sold -- is the right
    # instinct, and the reason is worth naming: the order book alone
    # cannot answer the question he is actually asking. "TRADED" tells
    # him an order filled at 09:18. It does not tell him whether he is
    # still carrying it now, and that is the difference between history
    # and money at risk.
    #
    # So the state is the ORDER STATUS crossed with THE BOOK:
    #
    #   WAITING    at the exchange, unconfirmed. The YASHO state -- the
    #              silence that made him click BUY a second time.
    #   FAILED     rejected. The dangerous one: he thinks he is in and
    #              he is not, and nothing else on the screen says so.
    #   HOLDING    filled AND still in the book. Live money.
    #   CLOSED     filled, round trip done. History.
    #   CANCELLED  he pulled it.
    #
    # Sorted by what needs him, not by time: WAITING and FAILED first.
    # A rejected order four rows down is a rejected order he will not
    # see.
    ORDER_STATE_RANK = {"WAITING": 0, "FAILED": 1, "HOLDING": 2,
                        "CLOSED": 3, "CANCELLED": 4}

    def _label_orders(self, out, open_positions):
        if not out.get("available"):
            return out

        held = set()
        items = open_positions or {}
        names = items.keys() if hasattr(items, "keys") else [
            (row or {}).get("symbol") for row in items]
        for name in names:
            if name:
                held.add(str(name).strip().upper())

        rows = []
        for group, base in (("pending", "WAITING"),
                            ("filled", None),
                            ("cancelled", None)):
            for item in out.get(group) or []:
                row = dict(item)
                symbol = str(row.get("symbol") or "").strip().upper()
                if base:
                    row["state"] = base
                elif group == "cancelled":
                    row["state"] = ("FAILED"
                                    if row.get("status") == "REJECTED"
                                    else "CANCELLED")
                else:
                    row["state"] = "HOLDING" if symbol in held else "CLOSED"
                row["held"] = symbol in held
                rows.append(row)

        rows.sort(key=lambda r: (self.ORDER_STATE_RANK.get(r["state"], 9),
                                 str(r.get("at") or "")))
        out = dict(out)
        out["rows"] = rows
        out["counts"] = {name: sum(1 for r in rows if r["state"] == name)
                         for name in self.ORDER_STATE_RANK}
        # The one number he asked for at the top of this panel: is
        # anything of mine still in flight, or did anything fail?
        out["needs_eyes"] = out["counts"]["WAITING"] + out["counts"]["FAILED"]
        return out

    # How many calls the screen may show at once. Small on purpose --
    # a list he has to scroll is a list he has to search, and searching
    # is the work this is meant to remove.
    CALLS_MAX = 6

    def _build_sector_indices(self, snapshot):
        """Every sector index that is delivering, biggest mover first.

        `snapshot` is core/index_monitor.snapshot() -- {name: {...}} --
        where a sector arrives as "sector:Pharma". The prefix is how a
        sector is told from a headline index without a second lookup.

        Sorted by ABSOLUTE move. A sector down 3% is as much of an
        answer as one up 3%, and a signed sort would lead with the
        dullest name on a red day.

        A sector with no packet yet is left out rather than shown at
        0.00% -- a flat number is a claim, and "we have not heard from
        it" is not the same claim.
        """
        out = []
        for name, data in (snapshot or {}).items():
            if not str(name).startswith("sector:"):
                continue
            if not (data or {}).get("available"):
                continue
            pct = data.get("pct")
            if pct is None:
                continue
            out.append({"name": str(name).split(":", 1)[1],
                        "ltp": data.get("ltp"),
                        "pct": round(pct, 2)})
        out.sort(key=lambda r: -abs(r["pct"]))
        return out

    # How far back the cause-and-effect panel looks. A government
    # announcement at 09:28 is still the reason a stock is moving at
    # 14:00; one from yesterday is history.
    # One company's own earnings is not a cause -- News and Filed Today
    # already carry it, with a button. This panel is for a story that
    # reaches stocks nobody named. 3 August 2026.
    CAUSE_MIN_STOCKS = 2
    CAUSE_HOURS = 8
    CAUSE_MAX = 6

    def build_causes(self, gainers_losers):
        """What happened, which stocks it hits, and whether the tape agrees.

        ---- THE WHOLE PIPELINE, ASSEMBLED. 3 August 2026. ----

            "again why user need to bother on this? provide him the
             completed picture. our bot had complete pipe line from
             scratch to AI where the decision can be build along with
             direction . why can't we make trader life simpler by using
             advanced mechanism & sorting everything"

        Today the government suggested scrapping MDR on digital
        payments. Every part of this bot did its job:

            09:28  Day Trader Telugu posts it as an IMAGE
                   OCR reads it
                   the matcher finds PAYTM and MOBIKWIK by name
            09:28  core/news_impact.py REASONS outward and adds three
                   companies nobody named -- PINELABS, CCAVENUE,
                   FINOPB -- each with a mechanism:
                       "Zero MDR removes a key merchant transaction fee
                        revenue stream for Paytm's payments business"
            09:42  News Pulse finally carries the same story

        Fourteen minutes of edge, five stocks, written reasoning. He
        saw none of it, and learned about MDR from the news.

        AND THE TWO ENGINES DISAGREED
        -----------------------------
        core/news_impact.py said NEGATIVE for PAYTM: no MDR, no fee
        revenue. core/ai_news.py said POSITIVE at 0.75: lower friction,
        more volume. Both are defensible and they are opposite. The
        tape rallied, so the AI reader was right and the rule engine
        was wrong -- five times over.

        The first build of this panel printed that argument on his
        screen under the word CONTESTED and left him to settle it. That
        was the mistake. A split between the two readers means this bot
        does not have a direction, and a stock with no direction gets
        no row -- it is dropped here, in the background, before the
        payload is built. Averaging them would be worse still: a
        confident nothing.

        WHAT REACHES THE SCREEN
        -----------------------
        The story in plain words, the stock, the mechanism, BUY or
        SELL. The tape check, the confidence scores and the
        disagreement all still run -- they decide the ORDER and decide
        what is withheld -- but they are the bot's reasoning, not his
        reading. "volumes supports the data" is his rule; enforcing it
        is this function's job, not his.
        """
        if self.news_impact is None:
            return {"rows": [], "note": "news impact not wired"}
        try:
            stories = self.news_impact.recent(limit=40,
                                              hours=self.CAUSE_HOURS)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[CAUSE] Could not read the impact store: {exc}")
            return {"rows": [], "note": str(exc)}

        gl = gainers_losers or {}
        live = {}
        for side in ("gainers", "losers"):
            for row in gl.get(side) or []:
                live[row.get("symbol")] = row

        rows = []
        for story in stories:
            hits = (story.get("positive") or []) + (story.get("negative") or [])
            if not hits:
                continue

            stocks = []
            for hit in hits:
                symbol = hit.get("symbol")
                now = live.get(symbol) or {}
                said = str(hit.get("direction") or "").upper()

                # The other reader's verdict on the same symbol, from
                # the event store's ai_direction column.
                other = self._ai_direction(symbol)
                contested = bool(other and other != said)

                pct = now.get("change_pct")
                if pct is None:
                    agrees = None
                elif said == "POSITIVE":
                    agrees = pct > 0
                else:
                    agrees = pct < 0

                stocks.append({
                    "symbol": symbol,
                    "direction": said,
                    "confidence": hit.get("confidence"),
                    "why": hit.get("reason"),
                    "change_pct": pct,
                    "moving": now.get("moving"),
                    "recent_pct": now.get("recent_pct"),
                    # None means "no price yet", which is not the same
                    # as "the tape disagrees".
                    "tape_agrees": agrees,
                    "contested_by_ai": contested,
                    "ai_says": other if contested else None,
                })

            # ---- THE BOT DECIDES. HE DOES NOT ARBITRATE. ----
            #      3 August 2026.
            #
            #   "i do not want user to trouble with some highfive name
            #    ("tape agrees / disagrees", "contested") . why again &
            #    again repeated mistakes. do u really think the user can
            #    able to understand the words & act on it? even if he
            #    understand why bot needs to show ? let the background
            #    work as required but on dashboard end user will see the
            #    impacted direction of the impacted stock & JUST BUY /
            #    SELL"
            #
            # He is right. Today's MDR story is the proof: news_impact
            # said NEGATIVE on all five payment stocks, ai_news said
            # POSITIVE, and the tape rallied. Two readers, one wrong,
            # and my answer was to print the argument on his screen and
            # let him referee it while a position moved.
            #
            # A stock the readers split on is a stock this bot does not
            # have an answer for. It is REMOVED. Not greyed out, not
            # flagged, not annotated -- removed, because an action he
            # cannot take is noise, and today the action on offer would
            # have been a SHORT into a rally.
            #
            # The disagreement is still recorded (see the diagnostic
            # below) so core/outcomes.py can score which reader is right
            # over time. That is background work. It is not his problem.
            dropped = [s for s in stocks if s["contested_by_ai"]]
            for s in dropped:
                diagnostic(
                    f"[CAUSE] {s['symbol']} withheld: news_impact says "
                    f"{s['direction']}, the AI reader says {s['ai_says']}. "
                    f"No agreed direction, so no button.")
            stocks = [s for s in stocks if not s["contested_by_ai"]]
            if not stocks:
                continue

            # ---- A CAUSE HAS TO HAVE EFFECTS. 3 August 2026. ----
            #
            #   "WHY THINGS ARE MOVING ... showing like same the news i
            #    do not want this type at all. once you check u will
            #    get better clarity than i say. pls check"
            #
            # Checked, and he is right. Read out of the real
            # news_memory.db, eleven of the twelve stories here were a
            # single company's own earnings:
            #
            #   #BUTTERFLY  Earnings -> Press Release   1 stock
            #   #SAMHI      Earnings -> Press Release   1 stock
            #   #THOMASCOOK Earnings -> Press Release   1 stock
            #
            # That is not cause and effect. It is the News panel and the
            # Filed Today panel, printed a third time in a different
            # typeface -- and both of those already carry it with a
            # button.
            #
            # The twelfth was the whole point of this panel:
            #
            #   #INDUSTOWER  concall says telecom towers are shifting
            #                from lead-acid to lithium-ion
            #                -> INDUSTOWER, GRAVITA, POCL
            #
            # Two of those three are companies the message never names.
            # Nobody reading the filing would have found them, and no
            # feed prints them. THAT is what he built this bot for:
            #
            #   "without any thing stock doesn't move, that something is
            #    we need to find out"
            #
            # So one stock is not a cause -- it is news about a company,
            # and it has two homes already. Two or more is a chain.
            if len(stocks) < self.CAUSE_MIN_STOCKS:
                continue

            # Strongest conviction first, then whatever is moving.
            stocks.sort(key=lambda s: (-(s["confidence"] or 0),
                                       -abs(s.get("recent_pct") or 0)))
            confirmed = sum(1 for s in stocks if s["tape_agrees"] is True)
            # A routing note is not a headline. "Concall Recording ->
            # Concall Transcript" describes how the bot moved a file
            # between two of its own stages; the MECHANISM the readers
            # extracted is what actually happened, and it is already
            # sitting on the strongest stock.
            rows.append({
                "headline": _headline_for(story, stocks),
                "at": story.get("at") or story.get("seen_at"),
                "source": story.get("source"),
                "stocks": stocks,
                "n_stocks": len(stocks),
                "confirmed": confirmed,
                # Background bookkeeping. Nothing renders these -- they
                # exist so core/outcomes.py can grade the two readers
                # against what the stocks actually did.
                "withheld": [s["symbol"] for s in dropped],
                "contested": bool(dropped),
            })

        # A story the market is acting on outranks one it has ignored.
        rows.sort(key=lambda r: (-r["confirmed"], -r["n_stocks"]))
        return {"rows": rows[:self.CAUSE_MAX],
                "note": "" if rows else "no reasoned story in the last "
                                        f"{self.CAUSE_HOURS} hours"}

    # How often the REST fallback may ask. The tiles refresh every
    # second; Dhan's quote endpoint must not be asked every second.
    INDEX_REST_SECONDS = 30

    def indices(self):
        """Every index the bot prices, live tick FIRST, last close after.

        The tick feed is the truth once it is running. Before 09:15 it
        has never spoken, and a REST quote is the same number Dhan would
        have sent -- so the tiles show yesterday's close rather than
        "no feed" for the hour he is deciding in.

        Never raises. A failed quote leaves the monitor's answer alone.
        """
        live = {}
        if self.index_monitor is not None:
            try:
                live = self.index_monitor.snapshot() or {}
            except Exception:                              # noqa: BLE001
                live = {}

        missing = [name for name, row in live.items()
                   if not row.get("available")]
        if not missing or self._index_quote is None:
            return live

        now = time.time()
        if now - self._idx_rest_at >= self.INDEX_REST_SECONDS:
            self._idx_rest_at = now
            self._idx_rest = self._quote_indices() or self._idx_rest

        for name in missing:
            hit = (self._idx_rest or {}).get(name)
            if hit:
                merged = dict(live[name])
                merged.update(hit)
                # Said plainly so a close is never read as a live price.
                merged["from_rest"] = True
                live[name] = merged
        return live

    def _quote_indices(self):
        """{name: {ltp, prev_close, pct, available}} from Dhan's REST."""
        try:
            from config import INDEX_INSTRUMENTS
            ids = [int(i) for i in INDEX_INSTRUMENTS]
            raw = self._index_quote({"IDX_I": ids}) or {}
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[INDEX] REST quote failed: {exc}")
            return {}

        # ---- TWO "data" KEYS DEEP. 4 August 2026. ----
        #
        #   "why NIFTY & other shows no feed ? whats the issue."
        #
        # Because this read ONE level and Dhan nests TWO:
        #
        #     raw["data"]["data"][segment][security_id]
        #
        # tools/check_index_levels.py says so in a comment -- "Dhan's
        # HTTP wrapper nests the API body" -- and core/circuit_monitor.py
        # documents the same shape. Both were written before this and
        # both got it right.
        #
        # So the fallback returned {} on every call and the tiles kept
        # saying "no feed" all day. The tests passed because I wrote the
        # fixture in the shape I ASSUMED rather than copying it from the
        # tool that actually works -- which means the test only ever
        # confirmed my own misunderstanding.
        if str(raw.get("status", "")).lower() not in ("success", ""):
            diagnostic(f"[INDEX] Dhan refused the quote: {str(raw)[:160]}")
            return {}

        body = raw.get("data")
        if isinstance(body, dict) and isinstance(body.get("data"), dict):
            body = body["data"]                    # the real shape
        rows = {}
        for block in (body or {}).values() if isinstance(body, dict) else ():
            if isinstance(block, dict):
                rows.update(block)
        if not rows:
            diagnostic(f"[INDEX] No quotes in the reply: {str(raw)[:160]}")
            return {}

        out = {}
        for sec_id, quote in rows.items():
            name = INDEX_INSTRUMENTS.get(str(sec_id))
            if not name or not isinstance(quote, dict):
                continue
            last = quote.get("last_price") or quote.get("ltp")
            prev = quote.get("prev_close") or (quote.get("ohlc") or {}).get("close")
            try:
                last = float(last)
            except (TypeError, ValueError):
                continue
            try:
                prev = float(prev)
            except (TypeError, ValueError):
                prev = None
            pct = round((last - prev) / prev * 100, 2) if prev else None
            out[name] = {"ltp": last, "prev_close": prev, "pct": pct,
                         "available": True}
        return out

    # Ten a side, the same count he asked for in the pre-open panel.
    FNO_TOP = 10

    def build_fno(self, gainers_losers):
        """F&O stocks only: what is up, what is down, biggest first.

        ---- ONE CHIP, ONE VIEW. 4 August 2026. ----

            "keep that F&O tab inside the fixed box as chip if i click
             on that it shows me whats happening in those stocks which
             are gaining by how much % & which are falling ... make two
             tables with top 10 Gainers & losers of F&O"
            "do not mix up them."

        My first attempt put ALL / NIFTY 50 / F&O beside the side switch
        and used it to narrow every table on the LIVE tab. One button
        changed the whole screen, which is not what he asked for and is
        the opposite of a dashboard that eases the work.

        This is a panel of its own, fed by the same movers the LIVE
        tables use, filtered to the F&O list and cut to ten a side.
        Nothing else on the page changes when he opens it.
        """
        members = self.build_members().get("fno") or {}
        symbols = set(members.get("symbols") or [])
        if not symbols:
            return {"available": False,
                    "note": "F&O membership not loaded -- "
                            "py tools/index_members.py"}

        rows = []
        for side in ("gainers", "losers"):
            for row in (gainers_losers or {}).get(side) or []:
                symbol = str(row.get("symbol") or "").upper()
                if symbol in symbols and row.get("change_pct") is not None:
                    rows.append(row)

        rows.sort(key=lambda r: -(r.get("change_pct") or 0))
        up = [r for r in rows if (r.get("change_pct") or 0) > 0]
        down = [r for r in rows if (r.get("change_pct") or 0) < 0]

        def dress(items):
            out = []
            for row in items:
                out.append({
                    "symbol": row.get("symbol"),
                    "sector": row.get("sector"),
                    "ltp": row.get("ltp"),
                    "change_pct": row.get("change_pct"),
                    "recent_pct": row.get("recent_pct"),
                    "moving": row.get("moving"),
                    "coverage": _coverage(row.get("symbol")),
                })
            return out

        return {"available": True,
                "gainers": dress(up[:self.FNO_TOP]),
                # Biggest faller first, not smallest.
                "losers": dress(list(reversed(down))[:self.FNO_TOP]),
                "n_members": len(symbols),
                "n_moving": len(rows)}

    def build_auto_watchlist(self, gainers_losers, open_positions):
        """His three rows, built by the bot, on every refresh.

            "i need the bot to think like me. it must check for the
             stocks & add them to watchlist not me manual adding."

        Row 1  Excellent / Great results
        Row 2  Reporting today -- watch, never bought into
        Row 3  Rising now on real volume

        Long only. Below Rs 50 is dropped. Below his liquidity floor
        is dropped. Every exclusion is returned with its reason, so a
        stock that is NOT on the screen can still be accounted for.
        """
        try:
            from core.liquidity import adv
            from core.watchlist_builder import build as build_watchlist
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "note": str(exc)}

        movers = []
        for side in ("gainers", "losers"):
            movers.extend((gainers_losers or {}).get(side) or [])

        held = set()
        items = open_positions or {}
        names = items.keys() if hasattr(items, "keys") else [
            getattr(p, "symbol", None) for p in items]
        for name in names:
            if name:
                held.add(str(name).upper())

        try:
            blocked = set(self.master_loader.blocked_symbols() or {})
        except Exception:                                  # noqa: BLE001
            blocked = set()

        try:
            got = build_watchlist(
                movers=movers, adv_of=adv, blocked=blocked, held=held,
                price_of=lambda s: (self.market_data.get_latest_price(s)
                                    if self.market_data is not None
                                    else None))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[WATCHLIST] Could not build: {exc}")
            return {"available": False, "note": str(exc)}

        # ---- PREV CLOSE, OPEN, HIGH -- NOT JUST A PRICE. 7 Aug 2026. ----
        #
        #     "some stocks will open gapup but fadeout & thats cost my
        #      deepakntr without seeing those real values & bought
        #      will falling (rule book never catch falling knife)"
        #
        # The watchlist showed a symbol, an LTP and a grade. That
        # cannot tell him a stock gapped up and then faded -- which is
        # the exact moment he must not buy, and the exact way DEEPAKNTR
        # cost him. A price with no open and no previous close is not
        # information, it is a number.
        #
        # _compute_gl_rows() has carried open / high / low / prev_close
        # all along. The watchlist simply never read them.
        by_symbol = {}
        try:
            for row in (self._compute_gl_rows() or []):
                key = str(row.get("symbol") or "").upper()
                if key:
                    by_symbol[key] = row
        except Exception:                                  # noqa: BLE001
            by_symbol = {}

        rows = []
        for row in got.get("rows") or []:
            out = []
            for symbol in row.get("symbols") or []:
                detail = dict((got.get("of") or {}).get(symbol) or {})
                detail["symbol"] = symbol
                live = by_symbol.get(symbol) or {}
                for field in ("open", "high", "low", "prev_close",
                              "change_pct", "volume"):
                    detail[field] = live.get(field)
                try:
                    detail["ltp"] = (live.get("ltp")
                                     or (self.market_data.get_latest_price(symbol)
                                         if self.market_data is not None
                                         else None))
                except Exception:                          # noqa: BLE001
                    detail["ltp"] = live.get("ltp")
                # ---- HAS THE GAP ALREADY FADED? ----
                # Opened above yesterday's close, then sold off. Said
                # in one word so he never has to work it out from four
                # numbers while a price is moving.
                o, h, l = live.get("open"), live.get("high"), live.get("ltp")
                pc = live.get("prev_close")
                detail["faded"] = bool(
                    o and pc and h and l and o > pc and h > o
                    and (h - l) > 0.4 * (h - pc))
                out.append(detail)
            rows.append({"key": row.get("key"), "title": row.get("title"),
                         "rows": out, "count": len(out)})
        return {"available": True, "rows": rows,
                "dropped": len(got.get("dropped") or {})}

    def build_ranked(self, gainers_losers, open_positions):
        """The best stocks right now, ranked, with the reason.

        ---- PHASE 1. IT PICKS, IT RECORDS, IT TRADES NOTHING. ----
             4 August 2026.

            "phase-1 bot will trade (assumption) & record . after
             tomorrow market closing we will verify"
            "30K is not trading tomorrow"

        core/ranker.py replaces first-come-first-buy: instead of acting
        on whichever stock ticks into a setup first, the whole field is
        compared and the best is named. Nothing here places an order --
        core/engine.py is still the only thing that trades, and it has
        not been given this list.

        Every cycle is written to data/decisions.db with the price at
        the moment of the decision, so at the close the picks can be
        measured against what those stocks actually did. The weights in
        core/ranker.py are my judgement and have never been scored;
        this is how that stops being true.
        """
        try:
            from core.liquidity import adv
            from core.ranker import rank
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "note": str(exc)}

        # ---- THE LEADERBOARD IS NOT THE UNIVERSE. 29 Aug 2026 ----
        #
        #     "i do not want those top 50 gainers & losers which no one
        #      gonna use & burden the bot system"
        #                                    -- operator, 29 Aug 2026
        #
        # This seeded the candidate pool with 50 gainers AND 50 LOSERS.
        # config.ENABLE_SHORT_TRADES is False and always has been, so
        # every loser was walked through the gates only to be refused
        # for being a loser -- 2,045 SELL picks are on record that
        # could never have been taken.
        #
        # The gainers half is a leaderboard of moves ALREADY MADE, which
        # is why _widen_by_reason() below had to exist at all: to ADD
        # BACK the stock that filed results at 09:41 and sat 180th.
        # Seeding from the leaderboard and then repairing it is the
        # wrong way round, so the widener IS the seed now.
        #
        # _compute_gl_rows() already builds a row for every symbol --
        # the leaderboard was only ever a slice of it -- so this costs
        # nothing new and drops the half that cannot trade.
        #
        # gainers_losers still reaches rank() untouched: sector strength
        # and market breadth need every stock, candidate or not.
        # Narrowing what is TRADED must not narrow what is SEEN.
        movers = []

        # ---- THE RANKER COULD NOT SEE THE STOCK EARLY. ----
        #      4 August 2026.
        #
        #   "why bot or trader needs to wait till Circuit closing even
        #    after knowing the results are excellent & volumes started
        #    buying stock moving = bot / trader must buy these stocks
        #    right?"
        #
        # He is right, and the reason was structural, not a threshold.
        # movers came from the top 50 gainers and top 50 losers, and
        # nothing else. On a strong day the 50th gainer is already up
        # 5-6%. A stock that filed excellent results at 09:41 and is
        # up 2.5% on rising volume is somewhere around 180th -- so the
        # ranker never saw it AT ALL until it had already run.
        #
        # By the time it entered the top 50 it was near its circuit,
        # which is the one moment it must not be bought: no sellers,
        # and the printed percentage understates the move.
        #
        # So the pool is widened by REASON, not by rank. Any stock the
        # bot has a mechanism for today joins the candidates whatever
        # its position in the list. Every gate downstream still has to
        # be cleared -- this only gives the stock the chance to clear
        # them while there is still room to run.
        try:
            movers = self._widen_by_reason(movers)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[RANK] Could not build the pool: {exc}")
        # This is now the SEED, not a widening, so an empty result is
        # a different statement than it used to be: it means nothing
        # has a reason today, which is a legitimate and common answer
        # -- and it means NO TRADES. Said out loud once per session
        # rather than silently returning an empty board, because
        # "no news" and "the news lookup broke" look identical from
        # here and only one of them is fine.
        if not movers and not getattr(self, "_said_no_reasons", False):
            self._said_no_reasons = True
            diagnostic("[RANK] No stock has a published reason yet -- "
                       "nothing is a candidate. This is the rule, not "
                       "a fault: no event, no evaluation.")

        if not movers:
            return {"available": True, "rows": [], "note": "no prices yet"}

        held = set()
        items = open_positions or {}
        names = items.keys() if hasattr(items, "keys") else [
            (r or {}).get("symbol") for r in items]
        for name in names:
            if name:
                held.add(str(name).upper())

        blocked = []
        try:
            blocked = list(self.engine.results_gate.blocked_symbols())
        except Exception:                                  # noqa: BLE001
            blocked = []

        # ---- THE ROWS DID NOT CARRY A DAY HIGH. 4 August 2026. ----
        #
        # core/ranker.py's liveness() decides "is this move still on"
        # from how far the stock has given back from its extreme. I
        # wrote that reading row["day_high"] -- and no row anywhere in
        # this payload has ever had one. Two of its three legs would
        # have been permanently dark while the code read as finished.
        #
        # Third time: the index REST parser, the frozen candle store,
        # and now this. Writing the gate is not the work; checking the
        # data reaches it is.
        try:
            extremes = self.market_data.day_extremes()
        except Exception:                                  # noqa: BLE001
            extremes = {}
        # ---- HOW MUCH ROOM IS LEFT BEFORE THE CIRCUIT. ----
        #      4 August 2026.
        #
        # MOREPEN hit its upper circuit and there was no trade to be
        # had -- no sellers, and the printed percentage understates
        # the real move. The exchange publishes the band live and
        # circuit_monitor already polls it; nothing read it for this.
        #
        # Headroom is the difference between "room to run" and "too
        # late to chase", and it is the same number either way.
        try:
            bands = self.engine.get_circuit_snapshot() or {}
        except Exception:                                  # noqa: BLE001
            bands = {}

        if extremes or bands:
            enriched = []
            for row in movers:
                symbol = row.get("symbol")
                seen = extremes.get(symbol)
                band = bands.get(symbol) or {}
                if seen or band:
                    row = dict(row)
                if seen:
                    row["day_high"] = seen.get("high")
                    row["day_low"] = seen.get("low")
                ltp = row.get("ltp")
                upper = band.get("upper_circuit_limit")
                lower = band.get("lower_circuit_limit")
                if ltp and upper:
                    row["headroom_up_pct"] = round(
                        (float(upper) - float(ltp)) / float(ltp) * 100.0, 2)
                if ltp and lower:
                    row["headroom_down_pct"] = round(
                        (float(ltp) - float(lower)) / float(ltp) * 100.0, 2)
                enriched.append(row)
            movers = enriched

        # _mechanism_for() is handed a symbol and nothing else, and the
        # volume ratio lives on the mover row. Stashing it here is what
        # lets a surge count as a reason without that function having to
        # go and re-derive a number the caller is already holding.
        # ---- IT READ A KEY THAT IS NOT ON THE ROW. 1 Sept 2026. ----
        #
        #     "dycl starting 10:55 order flow confirmed surge in volume
        #      that usual . which exactly reason to trigger in buy"
        #
        # DYCL rose 11.8% on 1 September and was skipped as "no event".
        # The volume-surge rule added on 31 August was supposed to catch
        # exactly that -- and it never fired once, because this loop
        # looked for "volume_ratio" or "volume_x" and a mover row
        # carries neither. It carries `volume`, `ltp`, and a `vol_ratio`
        # that is None at this point in the build.
        #
        # So _volume_now was empty every cycle and the surge could never
        # be a reason. Measured after the fix, at 11:30 that morning:
        # GODREJAGRO 98.9x its own normal pace, DYCL and IZMO likewise
        # far above the 20x bar.
        #
        # The ratio is COMPUTED here, the same way core/ranker.py
        # computes it -- turnover so far against this stock's own normal
        # pace by this minute. Reading a pre-computed field was the
        # mistake: nothing computes it before this point.
        self._volume_now = {}
        _adv = {}
        try:
            import json as _json
            with open(os.path.join("data", "liquidity.json"),
                      encoding="utf-8") as _fh:
                _adv = (_json.load(_fh) or {}).get("adv_cr") or {}
        except Exception:                                  # noqa: BLE001
            _adv = {}
        _now = datetime.now().strftime("%H:%M")
        for row in movers or []:
            key = str(row.get("symbol") or "").upper()
            if not key:
                continue
            ratio = row.get("vol_ratio") or row.get("volume_ratio")                 or row.get("volume_x")
            if ratio is None:
                volume, price, adv = (row.get("volume"), row.get("ltp"),
                                      _adv.get(key))
                if volume and price and adv:
                    try:
                        traded_cr = float(volume) * float(price) / 1e7
                        from core.volume_pace import pace_ratio
                        ratio = pace_ratio(traded_cr, float(adv), key, _now)
                        if ratio is None:
                            ratio = traded_cr / float(adv)
                    except Exception:                      # noqa: BLE001
                        ratio = None
            if ratio:
                try:
                    self._volume_now[key] = float(ratio)
                except (TypeError, ValueError):
                    pass

        try:
            got = rank(movers,
                       gainers_losers=gainers_losers,
                       indices=self.indices(),
                       mechanism_of=self._mechanism_for,
                       adv_of=adv,
                       blocked=blocked,
                       held=held,
                       mtf_of=self._mtf_for,
                       # 5 August 2026. Nothing is named before the
                       # opening range closes, and a long below its own
                       # open is a falling stock whatever yesterday
                       # did. See core/ranker.py OPENING_RANGE_ENDS and the
                       # "below its own open" gate -- DEEPAKNTR and
                       # ICICIGI, the only two entries that day trading
                       # under their open, were also the only two he
                       # spotted himself.
                       now=datetime.now(),
                       open_of=self.market_data.get_day_open)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[RANK] Ranking failed: {exc}")
            return {"available": False, "note": str(exc)}

        # ---- HIS RULES DECIDE WHO SURVIVES. 8 August 2026. ----
        #
        #     "we will trade only on stocks which are having some story
        #      to tell us either results/news"
        #     "i asked you to create a bot"
        #
        # core/ranker.py scores the move and treats the reason as one
        # term among many, so it kept naming stocks whose only
        # qualification was drifting 3% on ordinary volume. His rule is
        # the other way round: a card is REQUIRED, and the move has to
        # still be going.
        #
        # This is a filter over the ranker's own output, not a
        # replacement for it -- every gate ranker.py applies still
        # applied first. It removes what his rules forbid.
        try:
            from core import select as _rules
            kept, dropped = [], {}
            for row in (got.get("rows") or []):
                symbol = row.get("symbol")
                # ---- FOUR KEY NAMES, AND EVERY TRADE. 11 Aug 2026. ----
                #
                #     "why dashboard is not showing the today top gained
                #      stocks ? fincables , lumaxtech & atleast 20 stocks
                #      were trading at high"
                #
                # This read row["day_open"]. core/ranker.py writes that
                # field as "open" (ranker.py:744, which itself accepts
                # BOTH names -- it had already been bitten). So day_open
                # was None on every row ever passed here, select.movement
                # returned {"ok": False, "why": "no price"}, and this
                # loop dropped ONE HUNDRED PERCENT of the ranker's output
                # every cycle of every session.
                #
                # That is why ranked.rows has been 0 all day, why
                # LUMAXTECH at +19% showed BLOCKED "no price" beside its
                # own printed price, and why the bot has never taken a
                # trade from this path.
                #
                # Both names accepted here, the same way the ranker
                # already does it. A field renamed in one module and read
                # by its old name in another is silent -- nothing throws,
                # the list simply comes back empty and looks like a quiet
                # market.
                verdict = _rules.movement({
                    "ltp": row.get("ltp"),
                    "day_open": row.get("day_open") or row.get("open"),
                    "day_high": row.get("day_high") or row.get("high"),
                    "day_low": row.get("day_low") or row.get("low"),
                    "volume_ratio": (row.get("volume_ratio")
                                     or row.get("volume_x") or 1.6),
                })
                # ---- THE TAPE IS ALSO A REASON. 8 August 2026. ----
                #
                #     "do u believe that stock moves in a random day
                #      with random buyers without happening anything
                #      under the closed doors?"          -- operator
                #
                # No. A stock doing several times its normal volume and
                # holding its highs IS information -- somebody knows
                # something that has not been published yet. The card
                # being absent from OUR store is not the same as
                # nothing having happened.
                #
                # core/ranker.py already had this, added at his own
                # instruction on 7 August: an unexplained mover on
                # 2.5x+ volume is kept and labelled "no published
                # reason yet" rather than discarded. The first version
                # of this filter made "no card" a hard refusal and
                # silently undid it.
                #
                # So: a card OR a genuinely unusual tape. What is
                # refused is a stock drifting on ordinary volume with
                # nothing behind it -- which is what the bot kept
                # buying.
                reason = (row.get("why") or "").strip()
                ratio = row.get("volume_ratio") or 0
                if not reason and ratio < _rules.UNEXPLAINED_VOLUME:
                    dropped[symbol] = (
                        f"drifting on {ratio:.1f}x volume with nothing "
                        f"behind it")
                    continue
                if not verdict.get("ok"):
                    dropped[symbol] = verdict.get("why") or "the move is over"
                    continue
                row["moving"] = verdict.get("why")
                kept.append(row)
            if dropped:
                got.setdefault("refusals", {}).update(dropped)
                when_it_changes(
                    "rules-dropped",
                    f"[RULES] {len(dropped)} pick(s) removed: a card "
                    f"is required and the move must still be going.")
            got["rows"] = kept
        except Exception as exc:                           # noqa: BLE001
            warn(f"[RULES] Could not apply the entry rules ({exc}). "
                 f"The ranker's own list stands.")

        # ---- WHERE HE GETS OUT, AND WHAT IT COSTS. 4 August 2026. ----
        #
        #   "MADE TO LOOSE SMALL INCASE OF LOSS & WIN BIG ON WINNING
        #    STOCKS. THATS THE CORE HEIRARCHY YOU MUST FOLLOW"
        #
        # The ranker named a stock and stopped talking. Sizing off a
        # fixed rupee value makes the loss whatever the chart happens
        # to give; sizing off the STOP makes every loss the same size,
        # which is the only version where "lose small" is a rule.
        try:
            from core.position_plan import plan as position_plan
            by_symbol = {r.get("symbol"): r for r in movers}
            for row in got.get("rows") or []:
                # ---- A FADING STOCK IS NOT A SETUP. 5 August 2026. ----
                #
                # liveness() had already labelled SFL and PNBHOUSING
                # "fading" -- and position_plan sized them anyway, on
                # the very same row, because it never asked. The bot
                # contradicted itself in one line of output and then
                # offered him a quantity and a stop for it.
                #
                # "exit once it gone ruthlessly" cannot coexist with
                # entering something already going.
                if row.get("state") == "fading":
                    row["plan"] = {"ok": False,
                                   "why": "fading -- the move has already "
                                          "stopped working"}
                    continue
                row["result_tag"] = self._result_tag_for(row.get("symbol"))
                # ---- HAD IT ALREADY BEEN BOUGHT? 8 August 2026. ----
                #
                #     "some stocks will move even though good grade. as
                #      we both know market rewards by anticipating
                #      future"                        -- operator
                #
                # The grade says the quarter was good. It cannot say
                # whether the stock spent the previous fortnight
                # climbing into it, which is the documented reason a
                # beat sells off: the news was consumed on the way up.
                #
                # REPORTS, NEVER VETOES. Five stocks in the SPENT
                # bucket is a hint, not evidence, and the standing rule
                # is that nothing becomes a rule until it is scored
                # against real outcomes.
                row["runup"] = self._runup_for(row.get("symbol"))
                # ---- WHAT KIND OF OPPORTUNITY IS THIS. 16 Aug 2026 ----
                #
                #     "bot itself act as an opportunity bot ... company
                #      news, government schemes, multi year order wins,
                #      acquisitions, FDA approvals ... 100's"
                #
                # core/opportunity.py names the family. It is attached
                # here, in the SHOWS layer, and NOWHERE on the entry
                # path -- tests/test_opportunity_brain.py fails the
                # build if it reaches the ranker, the engine or either
                # plan module.
                #
                # It is a LABEL FOR RECALL, not a reason. The type
                # comes from matching words, and core/ranker.py refuses
                # keyword reasons by name; core/rules.is_a_reason()
                # still governs whether anything may be traded.
                row["opportunity"] = self._opportunity_for(row)
                # ---- IS REAL MONEY STACKED BEHIND IT. 16 Aug 2026 ----
                #
                #     "Volume confirms it -- money changing hands above
                #      this stock's own normal for this time of day"
                #
                # total_buy_quantity / total_sell_quantity arrive on
                # EVERY Quote packet and were read by nothing until
                # today. core/tick_ohlc.py keeps them now; this puts
                # the reading where he can see it.
                #
                # RESTING ORDERS CAN BE PULLED. This is a snapshot of
                # what is standing in the book, not a record of what
                # traded, so it is shown and never gated on -- tests/
                # test_tick_pressure.py fails the build if it reaches
                # an entry.
                try:
                    from core import tick_ohlc as _tick
                    row["pressure"] = _tick.pressure(row.get("symbol"))
                except Exception:                          # noqa: BLE001
                    row["pressure"] = None
                # ---- WHO IS BUYING TO KEEP. 8 August 2026. ----
                #
                #     "by seeing them many FII/DII, retail Algos started
                #      to accumalte stocks"          -- operator
                #
                # Delivery percentage is the only published number that
                # separates stock being TAKEN from stock being passed
                # around intraday. ACCUMULATION -- a run of above-average
                # delivery in a tight range on falling volume -- is the
                # footprint that comes BEFORE the move, which is the one
                # thing nothing else on this screen can see.
                row["delivery"] = self._delivery_for(row.get("symbol"))
                # The 7-day structure, beside the delivery reading --
                # both answer "what has this stock been doing", which
                # neither the price nor the volume column can say.
                row["trend"] = self._trend_for(row.get("symbol"))
                # ---- VWAP, WHICH NOTHING EVER SET. 27 Aug 2026 ----
                # core/ranker.py's liveness() has read row["vwap"]
                # since it was written and no code anywhere wrote it,
                # so "is the average buyer under water" -- one of its
                # three signals -- has never once fired. Computed from
                # the same closed candles ATR already uses.
                row["vwap"] = self._vwap_for(row.get("symbol"))
                # ---- A RUN OF EVENTS, NOT JUST TODAY'S. 29 Aug ----
                # ATHERENERG had four events across two sessions --
                # Hero raising its stake twice -- and each was read
                # alone on the day it arrived. The stock ran +8.9%
                # from where the bot named it. The rows were all on
                # file; nothing asked "has this happened before".
                row["story"] = self._story_for(row.get("symbol"))
                # ---- WHAT ACTUALLY TRADED, NOT WHAT IS RESTING. ----
                #      30 August 2026.
                #
                #     "order flow reveals the pressure"
                #                            -- the operator
                #
                # row["pressure"] above is core/tick_ohlc.py: the
                # quantity STANDING in the book, which can be pulled.
                # This is core/order_flow.py: what was actually paid
                # for, buy against sell, classified off the real
                # 5-level depth. It has been recorded since 29 August
                # and reached no screen.
                # ---- IT ONLY REACHED THE CLEARED ROWS. 31 Aug ----
                #
                #     "Buying pressure / order flow / delta for all
                #      stocks on dashboard except 1/2 stocks"
                #                                 -- the operator
                #
                # This loop walks the rows that PASSED the gates -- 3
                # of them that afternoon. The board draws the gainers
                # and the refused rows as well, so 146 of 149 rows
                # carried no reading and printed "not trading yet"
                # over stocks that were up eleven percent.
                #
                # Widened below, in _widen_flow_to_the_board(), to
                # everything the board can draw. Not to everything:
                # 51 ms a symbol lands in ONE cycle of a one-second
                # refresh, so it is bounded by the mover threshold the
                # board itself filters on.
                row["flow"] = self._flow_for(row.get("symbol"))
                # And today's shape, beside the 7-day one. A stock can
                # be STRONG_UP on daily bars and sideways since 10:20.
                row["shape"] = self._shape_for(row.get("symbol"))
                # ---- HOW OLD THE REASON IS. 30 August 2026. ----
                #
                #     "yes needs better show-up"     -- the operator
                #
                # core/why_moving.py drops a reason the card says is a
                # day or more old, which is right: a four-day-old
                # order is not why a stock is moving this morning. It
                # dropped it SILENTLY, so the stock appeared with no
                # reason at all and looked identical to one nothing
                # had ever been published about.
                row["reason_age"] = self._reason_age_for(row.get("symbol"))
                source = by_symbol.get(row.get("symbol")) or {}
                mtf = self._mtf_for(row.get("symbol"), source) or {}
                row["plan"] = position_plan(
                    source.get("ltp"), row.get("action"),
                    day_low=source.get("day_low"),
                    day_high=source.get("day_high"),
                    margin_pct=mtf.get("margin_pct"),
                    # Without the symbol the plan cannot widen a stop
                    # that is too close and refuses instead -- which
                    # dropped the best two picks of 19 August.
                    symbol=row.get("symbol"))
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[RANK] Could not plan positions: {exc}")

        prices = {r.get("symbol"): r.get("ltp") for r in movers}
        try:
            if self._decisions is None:
                from core.decision_log import DecisionLog
                self._decisions = DecisionLog()
            self._decisions.record(got, prices=prices)
            # WHAT IT TURNED AWAY. Without this the scorecard is half
            # missing: "no reason found x41" either protected him or
            # blinded him, and only the count across several days can
            # say which. It is also the direct test of the ten-a-day
            # plan -- if the bot clears three setups on an average
            # session, ten positions means taking seven it refused.
            # ---- THE SYMBOLS WERE THROWN AWAY HERE. 31 August 2026. ----
            #
            #     "fix that refusals table so i can see why. i didn't
            #      understand why bot can't see the stocks"
            #
            # He asked why the bot took none of 31 August's twelve best
            # stocks -- DIFFNKG +18.3%, MANALIPETC +10.9%, PRUDENT
            # +10.7% and nine more. The answer was in the store and
            # unreadable: 20,962 refusal rows for the day, every one of
            # them anonymous, the largest being "no event -- not
            # evaluated" 99 stocks at a time.
            #
            # The ranker DOES keep the symbols. ranker.py line 696
            # writes refused_by_symbol[name] for every stock it skips
            # for want of a reason, and returns it. The dashboard reads
            # it to paint the Live tab. And this line, the only route
            # into the store, passed the anonymous census instead --
            # so "which stocks, and why" was computed every cycle,
            # displayed for as long as the page was open, and never
            # written down.
            #
            # record_refusals already understands both shapes: a count
            # goes to the census, a {symbol: reason} entry goes to the
            # census AND to refused_symbols. So both are handed over.
            refusals = dict(got.get("refusals") or {})
            refusals.update(got.get("refused_by_symbol") or {})
            self._decisions.record_refusals(refusals)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[RANK] Could not record: {exc}")

        # ==========================================================
        # WHY THE LIVE TAB WAS BLANK WHILE PRE WAS FULL. 11 Aug 2026.
        # ==========================================================
        #
        #     "dashboard is not showing live. its working till pre
        #      market & blank at live tab."
        #
        # PRE reads gainers_losers -- the raw tape, hundreds of rows.
        # LIVE read `rows`, which is what SURVIVES ten hard gates in
        # core/ranker.py plus the entry-rules pass above. On an
        # ordinary morning that is nought or one. So the centre of his
        # screen, the table he told me is the money table, sat empty
        # while the bot was working perfectly.
        #
        # The refusals were never lost -- they go to data/decisions.db
        # every cycle. They just never reached the screen, and:
        #
        #     "A refusal he cannot see is one he cannot argue with"
        #
        # is the rule this whole board was built on.
        #
        # WHY A SEPARATE KEY AND NOT JUST APPENDING TO `rows`
        # ---------------------------------------------------
        # main.py feeds `ranked.rows` STRAIGHT INTO auto_entry.take().
        # Appending refused stocks there would hand the entry path the
        # exact stocks the gates just turned away -- the bot would buy
        # what it had refused, and the screen would look right while it
        # happened. So refusals go in their own key, the board draws
        # both, and nothing that trades ever reads this one.
        try:
            shown = {r.get("symbol") for r in (got.get("rows") or [])}
            source = {r.get("symbol"): r for r in movers}

            # ---- ONLY REAL SYMBOLS. 11 August 2026, 12:58. ----
            # I built these rows from got["refusals"] having ASSUMED it
            # was {symbol: reason}. core/ranker.py has keyed it
            # {reason: count} since 4 August. So his board drew stocks
            # called "too thin to trade our size" and "not moving
            # enough", with the COUNT printed where the reason belongs.
            #
            # Two sources now, and both are checked against the movers
            # before a row is drawn:
            #   refused_by_symbol -- the ranker's gates, per stock
            #   refusals          -- the entry-rules pass ALSO writes
            #                        symbol-keyed entries into this same
            #                        dict, so it is a genuine mix
            # Anything whose key is not a stock we have a price for is
            # an aggregate, and aggregates do not get a row.
            candidates = {}
            for key, why in (got.get("refused_by_symbol") or {}).items():
                candidates[str(key).upper()] = why
            for key, why in (got.get("refusals") or {}).items():
                name = str(key).upper()
                # a count is not a reason; a reason is not a symbol
                if isinstance(why, (int, float)):
                    continue
                if name in source:
                    candidates[name] = why

            refused_rows = []
            for symbol, why in candidates.items():
                if not symbol or symbol in shown or symbol not in source:
                    continue
                raw = source.get(symbol) or {}
                refused_rows.append({
                    "symbol": symbol,
                    "ltp": raw.get("ltp"),
                    "open": raw.get("day_open") or raw.get("open"),
                    "high": raw.get("day_high"),
                    "low": raw.get("day_low"),
                    "prev_close": raw.get("prev_close"),
                    "volume": raw.get("volume"),
                    "change_pct": raw.get("change_pct"),
                    "sector": raw.get("sector"),
                    "grade": raw.get("grade"),
                    # ---- WHY IT IS MOVING, NOT JUST WHY IT WAS REFUSED ----
                    # 11 August. The first version of this row carried
                    # only `blocking`, so a BLOCKED line read "no volume
                    # behind it" and said nothing about the stock. He
                    # asked for "neat & clean explaination of why stock
                    # is moving, volume, & everyother details" -- and
                    # that has to hold for a refusal too, or he cannot
                    # judge whether the refusal was right.
                    #
                    # _widen_by_reason already hangs `why` and
                    # `volume_ratio` on the mover row. reasonOf() on the
                    # page reads mechanism / volume_x / headroom_pct.
                    "mechanism": raw.get("why") or raw.get("mechanism"),
                    "volume_x": raw.get("volume_ratio") or raw.get("volume_x"),
                    "headroom_pct": raw.get("pct_to_upper"),
                    "upper_circuit": raw.get("upper_circuit"),
                    "lower_circuit": raw.get("lower_circuit"),
                    "turnover_cr": raw.get("turnover_cr"),
                    # The board renders anything with `blocking` as
                    # BLOCKED and prints the first entry as the reason.
                    "blocking": [str(why)],
                    # Belt and braces: if this row ever did reach a
                    # trading path, this is the flag that says no.
                    "display_only": True,
                })
            got["refused_rows"] = refused_rows
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[RANK] Could not build the refused rows: {exc}")
            got["refused_rows"] = []

        # ---- NO ROW ON THIS SCREEN IS ANONYMOUS. 11 August 2026. ----
        #
        #     "all mixed ? why? not even one thing is as i wanted."
        #
        # At 12:03 KOLTEPATIL and AARTIPHARM were on his board showing
        # "--" for grade and "no reason recorded". Both were GRADED at
        # that exact minute -- the bot held 35 graded names. The grade
        # was never missing from the BOT, only from the rows that screen
        # happened to draw.
        #
        # Publishing the map fixes that at the source: whichever list a
        # row comes from, the board can chip it. A row the bot has an
        # opinion on must never reach him looking like one it does not.
        try:
            from core import watchlist_builder
            grades = {}
            grade_of = None
            gate = getattr(self, "results_gate", None) or getattr(
                getattr(self, "engine", None), "results_gate", None)
            if gate is not None:
                grade_of = getattr(gate, "_published_grade", None) or getattr(
                    gate, "grade_for", None)
            for symbol in (watchlist_builder.graded_symbols() or []):
                name = str(symbol).upper()
                grade = None
                if grade_of is not None:
                    try:
                        grade = grade_of(name)
                    except Exception:                          # noqa: BLE001
                        grade = None
                if grade:
                    grades[name] = str(grade).upper()
            got["graded"] = grades
        except Exception as exc:                               # noqa: BLE001
            diagnostic(f"[RANK] Could not publish the grade map: {exc}")
            got["graded"] = {}

        # ---- WHY IT IS MOVING, FOR EVERY MOVER. 11 August 2026. ----
        #
        #     "thats a simple dashboard with whats the top gaining
        #      stocks with their underlying reason which is even present
        #      within bot through the telegram pro channels"
        #
        # He is right that the bot already has it. _mechanism_for()
        # answers for any symbol and has done since 7 August. But it was
        # only ever CALLED on rows that reached core/ranker.py, so a
        # stock at the top of the day's gainers -- FINCABLES, SUNDRMFAST,
        # OIL at 15:10 -- drew as "no reason recorded" while the reason
        # sat one function call away.
        #
        # Published as a plain map for the same reason the grades are:
        # the screen should never have to survive the ranker to say what
        # the bot knows.
        try:
            reasons = {}
            for row in movers:
                name = str(row.get("symbol") or "").upper()
                if not name:
                    continue
                why = row.get("why") or row.get("mechanism")
                if not why:
                    try:
                        why = self._mechanism_for(name)
                    except Exception:                      # noqa: BLE001
                        why = None
                # ---- A DICT IS NOT A SENTENCE. 11 August 2026. ----
                # GODAVARIB drew on his board as
                #     News.{'text': 'GODAVARI BIOREFINERIES: CO. R...
                # because _mechanism_for can hand back the whole news
                # record, and str() on a dict is its repr. Same class of
                # fault as the watermark dict-reprs on 10 August: the
                # value was never wrong, only never unwrapped.
                if isinstance(why, dict):
                    why = (why.get("text") or why.get("headline")
                           or why.get("why") or why.get("title"))
                elif isinstance(why, (list, tuple)) and why:
                    first = why[0]
                    why = (first.get("text") if isinstance(first, dict)
                           else first)
                if why:
                    reasons[name] = str(why).strip()
            got["reasons"] = reasons
        except Exception as exc:                               # noqa: BLE001
            diagnostic(f"[RANK] Could not publish the reason map: {exc}")
            got["reasons"] = {}

        got["available"] = True
        return got

    def build_early(self, gainers_losers, open_positions):
        """The 09:15-09:30 lane: stocks graded EXCELLENT/GREAT/GOOD
        overnight, bought at the open before the day's tape widens the
        stop -- see core/auto_entry.py's early_rows().

        ---- THE LANE THAT WAS NEVER CALLED. 12 August 2026. ----

        early_rows() was written, documented (its own module docstring)
        and exercised through tools/replay_day.py across 7-11 August,
        and never once appeared in main.py's live loop -- the "built and
        left standing alone" pattern across core/ that the operator
        flagged in the audit that led to this fix. This is the join,
        matching the one build_ranked() already has for the standard
        ranked list (main.py feeds both `ranked.rows` and this method's
        `rows` into the same auto_entry.take() call).

        Same movers, same position_plan sizing as build_ranked() below
        -- a stock in this lane is priced and stopped by the identical
        logic, not a second, divergent implementation of the same idea.
        """
        try:
            from core import auto_entry
            from core.position_plan import plan as position_plan
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "note": str(exc)}

        movers = []
        for side in ("gainers", "losers"):
            movers.extend((gainers_losers or {}).get(side) or [])
        try:
            movers = self._widen_by_reason(movers)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[EARLY] Could not widen the pool: {exc}")

        if not movers:
            return {"available": True, "rows": []}

        def _plan_of(mover):
            try:
                mtf = self._mtf_for(mover.get("symbol"), mover) or {}
                return position_plan(
                    mover.get("ltp"), "BUY",
                    day_low=mover.get("day_low"),
                    day_high=mover.get("day_high"),
                    margin_pct=mtf.get("margin_pct"),
                    symbol=mover.get("symbol"))
            except Exception as exc:                       # noqa: BLE001
                diagnostic(f"[EARLY] Could not size "
                           f"{mover.get('symbol')}: {exc}")
                return {"ok": False, "why": f"sizing failed ({exc})"}

        try:
            rows = auto_entry.early_rows(movers, now=datetime.now(),
                                          plan_of=_plan_of,
                                          evidence_of=self._evidence_for)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[EARLY] early_rows failed: {exc}")
            return {"available": False, "note": str(exc)}

        return {"available": True, "rows": rows}

    def _story_for(self, symbol):
        """A RUN of events on this stock, or None. Never raises.

        One event is news. Several across days is a situation --
        somebody buying a company in instalments, an order book
        filling up -- and the tape has days to react, not minutes.
        Cached per symbol for the session; the store only gains rows.
        """
        if not symbol:
            return None
        cache = getattr(self, "_story_cache", None)
        if cache is None:
            cache = self._story_cache = {}
        if symbol in cache:
            return cache[symbol]
        got = None
        try:
            if getattr(self, "_events_store", None) is None:
                from core.stock_events import StockEvents
                self._events_store = StockEvents()
            got = self._events_store.running_story(symbol, days=7)
        except Exception:                                  # noqa: BLE001
            got = None      # a panel must not take the snapshot down
        # Bounded: a session touches ~1,300 symbols.
        if len(cache) > 2000:
            cache.clear()
        cache[symbol] = got
        return got

    def _vwap_for(self, symbol):
        """This session's VWAP for one symbol, or None. Never raises."""
        if not symbol:
            return None
        try:
            engine = getattr(self, "engine", None)
            candles = getattr(engine, "candle_engine", None) if engine else None
            if candles is None:
                return None
            return candles.vwap(symbol)
        except Exception:                                  # noqa: BLE001
            return None     # a panel must not take the snapshot down

    def _trend_for(self, symbol):
        """This stock's 7-day structure, or None.

            "as bot knows about stock trend, delivery % why can't it
             show in dashboard"          -- operator, 24 August 2026

        core/trend_structure.py has classified every stock as
        STRONG_UP / UPTREND / RANGE / DOWNTREND / STRONG_DOWN since it
        was written, and tools/trend_report.py printed it to a CSV that
        had to be run by hand. It reached no screen and no alert, so
        the bot knew the shape of every stock and he did not.

        Only the rows on the board are computed -- eight daily bars for
        twenty-odd symbols, not 1,290 -- and cached per DAY, because a
        daily-bar structure cannot change until tomorrow's close.
        """
        if not symbol:
            return None
        from datetime import date
        today = date.today().isoformat()
        cache = getattr(self, "_trend_cache", None)
        if cache is None or cache.get("day") != today:
            cache = {"day": today, "rows": {}}
            self._trend_cache = cache
        if symbol in cache["rows"]:
            return cache["rows"][symbol]

        result = None
        try:
            from core.trend_structure import analyse
            # DashboardState has NO daily_store attribute -- the first
            # draft of this used self.daily_store behind a getattr
            # guard, which would have made every trend silently None,
            # forever. Exactly the fault
            # tests/test_the_code_reads_keys_that_exist.py was written
            # to catch, written the same evening. core/daily_store.py
            # is opened directly, once, and held on the instance.
            # ONE store per PROCESS, not one per DashboardState.
            # core/daily_store.py is SQLAlchemy and pools connections,
            # so an instance-level store leaks a pool for every state
            # object built -- which in a full test run is a lot of open
            # handles on data/daily_candles.db, and three tests failed
            # only when the whole suite ran.
            store = _daily_store()
            bars = store.history(symbol, days=8) if store else None
            if bars:
                got = analyse(bars) or {}
                structure = got.get("structure")
                if structure and structure != "UNKNOWN":
                    result = {
                        "structure": structure,
                        "hh_streak": got.get("hh_streak"),
                        "broke": got.get("broke_structure"),
                    }
        except Exception:                                  # noqa: BLE001
            result = None       # a panel must never take the snapshot down
        cache["rows"][symbol] = result
        return result

    def _safe_refused_today(self):
        """Which stocks the gates turned away today, and why.

        Cached for a minute. The ranker refuses roughly 1,100 stocks a
        cycle and this screen is rebuilt once a second; the store only
        gains a row when a stock is refused for a NEW reason, so a
        fresher read than a minute buys nothing.

        Capped at 60 rows. The full list is every stock that did not
        move enough, which is most of the universe on most days and is
        not a thing anybody reads down.
        """
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        cache = getattr(self, "_refused_cache", None)
        if cache is not None and cache.get("minute") == stamp:
            return cache["rows"]
        rows = []
        try:
            log = getattr(self, "_decisions", None)
            if log is not None and hasattr(log, "refused_symbols"):
                rows = log.refused_symbols(limit=60) or []
        except Exception:                                  # noqa: BLE001
            rows = []
        self._refused_cache = {"minute": stamp, "rows": rows}
        return rows

    def _safe_channel_report(self):
        """One row per Telegram channel. Never raises, never blocks.

        Cached for a minute: the poller runs at 90 seconds, so a
        fresher reading than this cannot exist, and the dashboard
        cycle asks once a second.
        """
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        cache = getattr(self, "_tg_report_cache", None)
        if cache is not None and cache.get("minute") == stamp:
            return cache["rows"]
        rows = []
        try:
            feed = getattr(self, "telegram", None) or getattr(
                self, "telegram_feed", None)
            if feed is not None and hasattr(feed, "channel_report"):
                rows = feed.channel_report() or []
        except Exception:                                  # noqa: BLE001
            rows = []
        self._tg_report_cache = {"minute": stamp, "rows": rows}
        return rows

    def _reason_age_for(self, symbol):
        """"22 minutes ago" / "4 days old", or None.

        Reads the SAME cached reason the row already carries -- see
        _mechanism_for() and config.REASON_CACHE_SECONDS -- so this
        costs a dictionary lookup rather than a second pass over the
        event store.
        """
        if not symbol:
            return None
        try:
            got = self._mechanism_for(symbol)
            if isinstance(got, dict):
                from core.why_moving import age_text
                return age_text(got.get("at"))
        except Exception:                                  # noqa: BLE001
            return None
        return None

    # A row the board cannot draw does not need a flow reading. It
    # filters on this, so this is the honest bound.
    FLOW_ROWS_MIN_MOVE_PCT = 4.0
    FLOW_ROWS_MAX = 40

    def _widen_flow_to_the_board(self, *groups):
        """Attach flow, shape and trend to every row the board draws.

            "Buying pressure / order flow / delta for all stocks on
             dashboard except 1/2 stocks"        -- 31 August 2026

        build_ranked() enriches the rows that CLEARED the gates. The
        board draws the gainers and the refused rows too, so almost
        every row on his screen carried no reading and printed "not
        trading yet" over stocks that were up eleven percent.

        Bounded on purpose. One symbol costs about 51 ms of SQLite,
        and the whole cost lands in the first cycle of each minute
        because _flow_for caches per minute. Bounding it by the same
        mover threshold the board filters on keeps that spike near
        half a second instead of three.

        Never raises; a row without a reading is left exactly as it
        was.
        """
        seen = set()
        done = 0
        for rows in groups:
            for row in (rows or []):
                if done >= self.FLOW_ROWS_MAX:
                    return
                if not isinstance(row, dict):
                    continue
                symbol = row.get("symbol")
                if not symbol or symbol in seen:
                    continue
                if row.get("flow") is not None:
                    seen.add(symbol)
                    continue
                try:
                    move = abs(float(row.get("change_pct") or 0.0))
                except (TypeError, ValueError):
                    move = 0.0
                if move < self.FLOW_ROWS_MIN_MOVE_PCT:
                    continue
                seen.add(symbol)
                done += 1
                try:
                    row["flow"] = self._flow_for(symbol)
                    row["shape"] = self._shape_for(symbol)
                    if row.get("trend") is None:
                        row["trend"] = self._trend_for(symbol)
                except Exception:                          # noqa: BLE001
                    pass

    def _flow_for(self, symbol):
        """Who is winning this stock today, and whether that is
        measured or inferred. None until it has traded.

            {"delta": 482140.0, "buy":.., "sell":.., "share": 63.0,
             "book_pct": 96.0, "measured": True,
             "diverged": {...} or None}

        CACHED PER MINUTE. divergence() reads today's minutes off
        data/order_flow.db, and this is called for every board row on
        every dashboard cycle -- which is once a second. The store
        only changes when the recorder flushes (30s), so a per-minute
        cache cannot go stale in a way that matters and it takes ~20
        queries a second down to ~20 a minute.
        """
        if not symbol:
            return None
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        cache = getattr(self, "_flow_cache", None)
        if cache is None or cache.get("minute") != stamp:
            cache = {"minute": stamp, "rows": {}}
            self._flow_cache = cache
        if symbol in cache["rows"]:
            return cache["rows"][symbol]

        result = None
        try:
            from core import order_flow

            # ONE read of the day's minutes, shared by both answers.
            # divergence() would otherwise open the store a second
            # time for the same symbol in the same call -- 51 ms a
            # symbol measured, which is the whole cost of this panel.
            series = order_flow.session_series(symbol)
            live = order_flow.pressure(symbol)
            if live:
                buy = float(live.get("buy") or 0.0)
                sell = float(live.get("sell") or 0.0)
                traded = buy + sell
                ticks = int(live.get("ticks") or 0)
                book = int(live.get("book_ticks") or 0)
                book_pct = (book / ticks * 100.0) if ticks else 0.0
                try:
                    from config import FLOW_MIN_BOOK_PCT as _floor
                except Exception:                          # noqa: BLE001
                    _floor = 60.0
                result = {
                    "delta": live.get("delta"),
                    "buy": buy, "sell": sell,
                    # "63 shares in every 100 traded that way" -- the
                    # sentence on the card, so the number it needs is
                    # computed here rather than in JavaScript.
                    "share": round(buy / traded * 100.0, 1) if traded else None,
                    "book_pct": round(book_pct, 1),
                    "measured": book_pct >= _floor,
                    "ticks": ticks,
                    "diverged": order_flow.divergence(symbol, series=series),
                }
        except Exception:                                  # noqa: BLE001
            result = None       # a panel must never take the snapshot down
        cache["rows"][symbol] = result
        return result

    def _shape_for(self, symbol):
        """Today's shape -- "going up all session", "sideways since
        10:20" -- or None before about 10:00, which is the honest
        answer rather than "sideways".

        Cached per minute for the same reason as _flow_for: it reads
        the same minutes off the same store.
        """
        if not symbol:
            return None
        from datetime import datetime
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        cache = getattr(self, "_shape_cache", None)
        if cache is None or cache.get("minute") != stamp:
            cache = {"minute": stamp, "rows": {}}
            self._shape_cache = cache
        if symbol in cache["rows"]:
            return cache["rows"][symbol]
        result = None
        try:
            from core import intraday_shape
            result = intraday_shape.today(symbol)
        except Exception:                                  # noqa: BLE001
            result = None
        cache["rows"][symbol] = result
        return result

    def _delivery_for(self, symbol):
        """{"reading", "pct", "avg", "text"} or None.

        None means the delivery store has no run for this stock yet --
        it needs several sessions before the pattern means anything,
        and saying nothing is the honest answer until then.
        """
        if not symbol:
            return None
        try:
            from core import delivery
            got = delivery.reading(symbol)
        except Exception:                                  # noqa: BLE001
            return None
        if not got:
            return None
        return {"reading": got.get("reading"), "pct": got.get("pct"),
                "avg": got.get("avg"), "text": got.get("text")}

    def _runup_for(self, symbol):
        """How far the stock had already travelled INTO its result.

        {"pct", "reading", "text", "result_date"} or None. None means
        either no result inside the window or no price history -- both
        are "cannot say", and neither prints as a judgement.
        """
        if not symbol:
            return None
        try:
            from core import runup
            got = runup.reading(symbol)
        except Exception:                                  # noqa: BLE001
            return None
        if not got:
            return None
        return {"pct": got.get("pct"), "reading": got.get("reading"),
                "text": got.get("text"),
                "result_date": got.get("result_date")}

    def _result_tag_for(self, symbol):
        """EXCELLENT, GOOD, AVOID -- or None if it did not report today.

        ==========================================================
            "keep simple only excellent , good , avoid thats it"
            "pls make the background work i need to see the stock
             result only with tags/chips next to stock name"
                                    -- operator, 5 August 2026
        ==========================================================

        core/result_tag.py was written and validated on 5 August and
        then imported by NOTHING for a day. Nine PRO ratings collapse
        to one word here so nothing has to collapse on his screen.

        AVOID does not hide the stock. It labels it. A weak result on a
        name the tape is buying hard is still a trade -- at half size,
        a tighter stop, and out by the close -- and hiding it would be
        the bot overruling the market.
        """
        # THE RAW CHANNEL TEXT, not the trimmed headline. result_tag
        # reads what the channels actually write -- "Excellent Results",
        # "- Strong Beat", the coloured dot. stock_events keeps a
        # cleaned headline, and against that the tag fired on 2 of 7
        # names that had clearly reported. Against telegram.db it fires
        # on all of them.
        if self.telegram is None or not symbol:
            return None
        try:
            from datetime import timedelta

            from core import result_tag
            # 36 HOURS, not the calendar day. At 00:13 "today" is empty
            # and every chip vanished -- and a result published after
            # yesterday's close is exactly what he trades this morning.
            cutoff = (datetime.now() - timedelta(hours=36)).isoformat()
            messages = [
                (str(m.get("channel") or ""),
                 " ".join(str(m.get(k) or "") for k in ("text", "ocr_text")))
                for m in self.telegram.for_symbol(symbol, limit=40) or []
                if str(m.get("at") or "") >= cutoff
            ]
            if not messages:
                return None

            # ---- READ THE WHOLE CARD. 6 August 2026. ----
            #
            #     "i want bot to read all of them , understand and sort
            #      the answer for me to trade ... bot must check all the
            #      sources recevd & update the chip next to the
            #      respective stock"
            #
            # result_tag read four fields. Measured against the real
            # traffic of this day it took 68 fields out of 1,497,848
            # characters of OCR text, and handed back AVOID for 208 of
            # 241 stocks that reported -- a blanket refusal wearing the
            # costume of a judgement.
            #
            # core/result_read.py reads every field the channels print,
            # off every image, from every channel, across the whole arc
            # -- what was expected before the print, the print, and the
            # analysis after -- and returns the evidence with the chip
            # so the reason sits on the screen next to the answer.
            from core import result_read
            # ---- ONLY CARDS THAT ARE ABOUT THIS STOCK. 8 Aug 2026 ----
            #
            #     "0 knowlede is far better than half knowledge"
            #     "so pls do not miss or club one data to other stock"
            #
            # `messages` is every message TAGGED with this symbol, and
            # the tag means "mentions", not "is about". Measured on the
            # real store: SIEMENS's chip was built from 22 messages,
            # four of them about ENRIN, and it quoted TRENT's "22% YoY
            # net profit rise to Rs 518 Cr as soft like-for-like
            # fashion volume growth" inside an engineering company's
            # earnings verdict. It read AVOID at -1.2 off that.
            #
            # core/subject.py believes the card's own #hashtag, which
            # is what every Pulse channel puts on itself. With the gate
            # in place SIEMENS drops 22 -> 9 with zero ENRIN, GLAND
            # goes blank rather than reporting "Revenue +2008% YoY",
            # and TRENT -- which was clean enough to score either way
            # -- moves from WATCH to GOOD because the noise was
            # dragging it down.
            #
            # Some chips will now be blank. That is the trade he chose
            # when he saw what the alternative was producing.
            from core import subject
            messages = subject.only(symbol, messages)
            if not messages:
                return None
            fields = result_read.read(messages)
            verdict = result_read.score(fields)
            if verdict.get("chip") is None:
                # Nothing scoreable arrived. That is a question, not a
                # verdict, and it must not print as one.
                return None
            # THE READ FIELDS, CARRIED. core/margin_driver.py needs the
            # sales/op/opm grid to ask where the margin came from, and
            # it needs EVERY reporter's grid to ask whether the whole
            # sector printed the same thing. That second pass cannot
            # happen here -- it happens in _result_tags_today() once
            # all of today's names are read. 12 August 2026.
            return {"tag": verdict["chip"],
                    "score": verdict["score"],
                    "why": verdict["why"],
                    "against": verdict["against"],
                    "images": verdict["images"],
                    "channels": verdict["channels"],
                    "fields": fields,
                    "note": result_tag.note(fields)}
        except Exception:                                  # noqa: BLE001
            return None

    def _mechanism_for(self, symbol):
        """The written reason this stock is moving, or None.

        No mechanism, no candidate -- his rule since the first day:
        "without any thing stock doesn't move".

        ---- IT READ ONE STORE OUT OF TWO. 5 August 2026. ----

        This used to ask core/news_impact.py and nothing else, and
        returned whatever came back -- including "matched on: SHILPAMED",
        which is the keyword matcher naming itself. 41% of that store's
        reasons are that shape.

        Everything the PRO channels publish lives in the OTHER store,
        core/stock_events.py, and no part of the ranking path had ever
        opened it. SHILPAMED was graded GOOD by three channels at 13:51
        and was refused all day for having no reason.

        core/why_moving.py now asks both and returns the stronger
        answer, in the same shape the ranker already reads.
        """
        from core.why_moving import why

        # ---- IT RE-DERIVED THE SAME ANSWER EVERY SECOND. 29 Aug ----
        #
        # 15.1 ms a symbol, 105 symbols carrying news, once per cycle,
        # for a reason that has not changed since the news landed at
        # 09:41. That was 1,590 ms of a 1-second loop -- see
        # config.REASON_CACHE_SECONDS for the full measurement.
        #
        # Keyed by symbol AND day: a process that runs past midnight
        # must not serve yesterday's reason, and the entry gate reads
        # this to decide membership.
        #
        # This TTL is the bot's reaction time to fresh news, which is
        # the whole reason it is 30 seconds and not 5 minutes.
        name = str(symbol or "").upper()
        if not name:
            return None
        today = datetime.now().strftime("%Y-%m-%d")
        cache = getattr(self, "_reason_cache", None)
        if cache is None or getattr(self, "_reason_cache_day", None) != today:
            cache = self._reason_cache = {}
            self._reason_cache_day = today
        if REASON_CACHE_SECONDS:
            held = cache.get(name)
            if held is not None and time.monotonic() < held[0]:
                return held[1]

        events = []
        if self.stock_events is not None:
            try:
                events = self.stock_events.for_symbol(symbol, limit=20)
            except Exception:                              # noqa: BLE001
                events = []
        hits = []
        if self.news_impact is not None:
            try:
                hits = self.news_impact.for_symbol(symbol, limit=5)
            except Exception:                              # noqa: BLE001
                hits = []
        # TODAY only. Yesterday's result is not why it is moving now,
        # and a stale grade attached to a live move is the mis-match he
        # has warned about more than once.
        # `symbol` lets why() fall through to the pre-open gapper card
        # when neither store has a written sentence. That card names
        # the stock, grades yesterday's result and measures the gap --
        # it is a mechanism, and on 6 August it was the difference
        # between 0 candidates and a real list.
        # ---- AND THE THIRD STORE. 21 August 2026. ----
        #
        #     "the top gainers/ movers itself proves something is
        #      happening inside the stock right?"      -- operator
        #
        # It does, and the bot was holding the proof. Seven of the
        # 21 August gainers were refused "no event behind it" while
        # data/feeds.db held their NSE filings -- KRONOX's open offer,
        # NETWEB's Rs 1,200 crore QIP, RHETAN's solar project. This
        # function asked the PRO channels and the newswire and had
        # never once opened the filing store.
        #
        # Same fault as 5 August, one store further on.
        filing = None
        watcher = getattr(self, "announcement_watcher", None)
        if watcher is not None:
            try:
                filing = watcher.for_symbol(symbol)
            except Exception:                              # noqa: BLE001
                filing = None
        got = why(events=events, news_hits=hits, symbol=symbol,
                  filing=filing, on_date=today)

        # ---- AND THE VOLUME ITSELF. 31 August 2026. ----
        #
        #     "opportunity = news , govt order, volume surge, events"
        #
        # Volume surge was on his list and this function asked four
        # stores, none of them volume. On 31 August the bot took none
        # of the day's twelve best stocks -- it did not refuse them, it
        # never evaluated them. DIFFNKG went up 16.9% on 81x its normal
        # volume with no published sentence anywhere.
        #
        # LAST, deliberately. A real filing or a news item is a better
        # answer than "a lot of shares changed hands", so this only
        # speaks when the other four have nothing. When it does speak
        # it says the ratio, so the Live tab shows him the number the
        # decision was made on rather than the word "volume".
        if got is None and SURGE_IS_A_REASON:
            ratio = (getattr(self, "_volume_now", None) or {}).get(name)
            if ratio and ratio >= SURGE_REASON_MIN_RATIO:
                got = {"text": f"{ratio:.0f}x its normal volume -- "
                               f"something moved before the news did",
                       "weight": 0.5, "kind": "VOLUME_SURGE"}
        # None is cached too. "This stock has no reason" is an answer
        # that costs the same 15 ms to reach as any other, and it is
        # the answer for most of the list.
        #
        # ---- SPREAD THE EXPIRIES. ----
        # A flat TTL fills the whole cache on one cycle, so the whole
        # cache falls due on one cycle too: measured, that turned a
        # steady 1,590 ms into 0.3 ms for 29 cycles and 5,372 ms for
        # the thirtieth. The stall is worse than the average it fixes.
        #
        # So each symbol keeps its own lifetime between half the TTL
        # and all of it, fixed by its NAME rather than by chance --
        # the same stock gets the same offset on every restart, and
        # the re-derivations land a few per cycle instead of all at
        # once. Maximum staleness is still REASON_CACHE_SECONDS, which
        # is the number his 11:00-news rule cares about.
        # crc32, not sum-of-bytes and not hash(). Summing bytes puts
        # SYM0..SYM299 within 1.7 seconds of each other -- similar
        # names get similar sums, which is the stampede again wearing
        # a disguise. hash() is salted per process, so the same stock
        # would take a different slot on every restart and a timing
        # fault would only show up some mornings.
        lifetime = REASON_CACHE_SECONDS
        if lifetime:
            share = (zlib.crc32(name.encode("utf-8")) % 1000) / 1000.0
            lifetime = REASON_CACHE_SECONDS * (0.5 + share * 0.5)
        cache[name] = (time.monotonic() + lifetime, got)
        return got

    def _safe_opportunity_memory(self):
        """What each opportunity family has been WORTH, measured.

        ---- THE LEARNING HAD NO SCREEN. 16 August 2026. ----

            "i want you to develop a brain memory module in to bot with
             self evaluating & learning"

        core/opportunity.py does the evaluating. It ran only in Python,
        so the half he actually asked for -- what the memory has
        LEARNED -- was invisible. Fifth time in two days that something
        measured and stored reached no screen.

        CACHED FOR 30 MINUTES. evaluate() walks 13,996 events and every
        family's price history: 3.8 seconds measured. The board polls
        every 3, so calling it per snapshot would stall the screen --
        which is the fault that made the whole dashboard stale on 13
        August. The readings span 120 days; they do not move inside
        half an hour.

        (That last sentence is deliberately not worded with the word
        for a mean. tests/test_cause_and_effect.py slices this file
        from build_causes to _ai_direction and forbids that word in the
        span, to stop two disagreeing readers being blended into one
        number. It strips # comments but not docstrings, so this method
        landing inside the slice broke it -- the SEVENTH time a test
        here has matched prose. The rule it protects is right and has
        nothing to do with this panel, so the sentence moved rather
        than the test.)
        """
        import time

        now = time.time()
        held = getattr(self, "_opp_memory_cache", None)
        if held and now - held[0] < 1800:
            return held[1]
        try:
            from core import opportunity

            got = opportunity.evaluate()
            got["verdict"] = opportunity.verdict()
            got["computed_at"] = datetime.now().strftime("%H:%M")
        except Exception as exc:                           # noqa: BLE001
            warn(f"[OPPORTUNITY] Memory panel failed ({exc}). Everything "
                 f"else is unaffected.")
            got = {"available": False, "families": [], "note": str(exc)}
        self._opp_memory_cache = (now, got)
        return got

    def _safe_ai_spend(self):
        """This month's AI spend, per purpose. Never raises.

        Per PURPOSE, not just a total, because the total is what hid
        the problem: the ledger reported Rs 126 while three of five
        paid callers wrote no row at all. A breakdown makes a caller
        that stops reporting visible, where a single number does not.
        """
        try:
            import sqlite3
            from core.ai_budget import AiBudget

            meter = AiBudget()
            got = meter.status()
            got["by_purpose"] = []
            try:
                con = sqlite3.connect(f"file:{meter.db_path}?mode=ro",
                                      uri=True)
                got["by_purpose"] = [
                    {"purpose": p, "calls": c, "rs": round(r or 0.0, 2)}
                    for p, c, r in con.execute(
                        "SELECT purpose, COUNT(*), SUM(rs) FROM spend "
                        "WHERE month = ? GROUP BY purpose ORDER BY SUM(rs) "
                        "DESC", (got["month"],))]
                con.close()
            except Exception:                              # noqa: BLE001
                pass
            return got
        except Exception as exc:                           # noqa: BLE001
            warn(f"[AI SPEND] Panel failed ({exc}). Everything else is "
                 f"unaffected.")
            return {"available": False, "note": str(exc)}

    def _opportunity_for(self, row):
        """Which opportunity families this row's own reason text names.

        Fail-soft to None, like every sibling build_*: a panel may cost
        itself and may never cost the snapshot. core/watchlist.py took
        the whole refresh down on 4 August by raising here.

        None means "nothing recognised" AND "could not say" -- which is
        correct, because neither is a reason to trade and the caller
        must not be able to tell them apart and act on the difference.
        """
        try:
            from core import opportunity

            text = " ".join(str(row.get(k) or "") for k in
                            ("mechanism", "why", "reason", "headline"))
            if not text.strip():
                return None
            hits = opportunity.classify(text)
            if not hits:
                return None
            # Most specific first is not knowable here, so keep the
            # order the taxonomy declares and cap it -- three chips is
            # already more than a row can carry.
            return [{"key": h["key"], "label": h["label"],
                     "horizon": h["horizon"], "direction": h["direction"],
                     "matched": h["matched"]} for h in hits[:3]]
        except Exception:                                  # noqa: BLE001
            return None

    def build_members(self):
        """NIFTY 50 and F&O membership, for narrowing the LIVE tables.

        ---- 4 August 2026 ----

            "the most loavable product u build without my asking is F&O
             in pre-Market ... pls confirm that it will work in LIVE TAB
             too"

        The lists were already loaded -- build_preopen has used them for
        the pre-open group buttons since it was written. They simply
        never reached the LIVE tab, so the same question ("show me only
        F&O") was answerable at 09:05 and not at 09:20.

        An empty list means membership is UNKNOWN, and the panel must
        then offer no button rather than a filter that hides everything.
        """
        out = {}
        if self.index_members is None:
            return out
        for key, label in (("nifty50", "NIFTY 50"), ("fno", "F&O")):
            try:
                members = self.index_members.members(key) or []
            except Exception:                              # noqa: BLE001
                members = []
            if members:
                out[key] = {"label": label,
                            "symbols": sorted(str(s).upper() for s in members)}
        return out

    def _sector_rows(self, gainers_losers):
        # (see _Snapshot below -- a dict handed to something that expects
        #  a store)
        """The sector indices as rows, from the live feed."""
        rows = []
        idx = self.indices()
        for name, data in (idx or {}).items():
            if not str(name).startswith("sector:"):
                continue
            if data.get("pct") is None:
                continue
            rows.append({"name": str(name).split(":", 1)[1],
                         "pct": data["pct"]})
        return rows

    def build_awareness(self, breadth, gainers_losers):
        """Market Situational Awareness. Informs; never blocks.

            "Market Situational Awareness is the ability to understand
             the complete market environment before making any trading
             decision & during open position."
            "bot must inform the situation like a caution not block"

        Five legs, all of which the bot was already fetching and none
        of which reached a decision. See core/awareness.py -- the whole
        reason this exists is that market_trend, regime and
        overall_score were three labels on his screen driven by one
        number.
        """
        try:
            from core.awareness import assess
        except Exception as exc:                           # noqa: BLE001
            return {"available": False, "note": str(exc)}

        adv = (breadth or {}).get("advances") or 0
        dec = (breadth or {}).get("declines") or 0
        total = adv + dec
        pct = (adv / total * 100) if total else None

        try:
            reading = assess(
                premarket=self.premarket,
                indices=self.indices(),
                sector_rows=self._sector_rows(gainers_losers),
                # NOT self.market_flows. That is the NSE fetcher alone,
                # which has never returned a figure. _build_institutional
                # is the one that falls through to News Pulse, and it is
                # what the ribbon draws -- two sources for one number
                # would put "FII bought 277" on the line and "no flow
                # figure yet" in the panel beneath it, in the same
                # second. 3 August 2026.
                market_flows=_Snapshot(self._build_institutional()),
                breadth_pct=pct,
                events=self._recent_headlines(),
            )
        except Exception as exc:                           # noqa: BLE001
            warn(f"[AWARE] Reading failed: {exc}")
            return {"available": False, "note": str(exc)}
        reading["available"] = True
        return reading

    def _recent_headlines(self, hours=2, limit=25):
        """Market-wide headlines from the channels, newest first.

            "bot needed live news, events which will get sourced from
             our news channels - Day trader & News Pulse"

        News Pulse stays banned for STOCK TAGGING -- he ruled it
        unreliable there and NO_STOCK_TAGGING still enforces it. Nothing
        here is attached to a company, so it is safe and useful.
        """
        out = []
        try:
            rows = self.news_impact.recent(limit=limit, hours=hours) \
                if self.news_impact else []
        except Exception:                                  # noqa: BLE001
            rows = []
        for row in rows or []:
            out.append({"headline": row.get("headline"),
                        "source": row.get("source"),
                        "at": row.get("at")})
        return out

    def build_shock(self, gainers_losers, open_positions):
        """Something big just happened -- or nothing did.

            "if any major thing happened & how the bot knows? how it
             will alert the trader to look into the matter"

        Returns {} when the market is behaving. A screen that finds a
        crisis every day finds none on the day there is one.
        """
        try:
            from core.shock import assess
        except Exception as exc:                           # noqa: BLE001
            return {}

        movers = []
        for side in ("gainers", "losers"):
            for row in (gainers_losers or {}).get(side) or []:
                movers.append(row)

        nifty = {}
        if self.index_monitor:
            nifty = (self.indices() or {}).get("nifty") or {}

        # open_positions is a DICT keyed by symbol, not a list of rows.
        # I wrote the list version from memory and ten existing tests
        # caught it -- iterating a dict yields the keys, so every
        # position arrived here as a bare string. Both shapes are
        # accepted now because build_shock is also called directly from
        # tests. 3 August 2026.
        held = []
        items = (open_positions or {})
        pairs = items.items() if hasattr(items, "items") \
            else [((p or {}).get("symbol"), p) for p in items]
        for symbol, position in pairs:
            if not isinstance(position, dict):
                continue
            entry = position.get("entry_price")
            last = None
            try:
                last = self.market_data.get_latest_price(symbol)
            except Exception:                              # noqa: BLE001
                last = None
            pct = None
            if entry and last:
                pct = round((last - entry) / entry * 100, 2)
                if str(position.get("direction", "LONG")).upper() == "SHORT":
                    pct = -pct
            # ---- pnl WAS ALWAYS None. 24 August 2026. ----
            #
            # A stored position has entry_price, qty, initial_stop,
            # atr_stop, stop_mode -- and no "pnl" key, so this read
            # returned None every time and the shock banner showed his
            # open positions with a blank P&L during the one event
            # where it matters. `change_pct` on the line above already
            # had a fallback to the computed `pct`; this one did not.
            #
            # Found by tests/test_the_code_reads_keys_that_exist.py,
            # which was written after the same fault printed
            # "[CARRY] ... stop None" for three protected positions.
            qty = position.get("qty")
            pnl = position.get("pnl")
            if pnl is None and entry and last and qty:
                pnl = round((last - entry) * qty, 2)
                if str(position.get("direction", "LONG")).upper() == "SHORT":
                    pnl = -pnl
            held.append({"symbol": symbol,
                         "qty": qty,
                         "change_pct": position.get("change_pct", pct),
                         "pnl": pnl})

        try:
            return assess(headlines=self._recent_headlines(),
                          movers=movers,
                          index_pct=nifty.get("pct"),
                          positions=held) or {}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[SHOCK] Check failed: {exc}")
            return {}

    def _ai_direction(self, symbol):
        """What core/ai_news.py said about this stock most recently.

        Read-only and fail-quiet. Its purpose is to disagree out loud
        when it disagrees, not to override anything.
        """
        try:
            rows = self.stock_events.recent(hours=self.CAUSE_HOURS) \
                if self.stock_events else []
        except Exception:                                  # noqa: BLE001
            return None
        for row in rows:
            if row.get("symbol") == symbol and row.get("ai_direction"):
                return str(row["ai_direction"]).upper()
        return None

    def build_calls(self, shortlist, gainers_losers, open_positions):
        """The short list of things worth acting on. Nothing else.

        ---- WHAT THE WHOLE DASHBOARD IS FOR. 3 August 2026. ----

            "user(my) worry should be about taking trades which are
             sorted curated by bot. not by searching & calculating to
             trade. thats can be done by anywhere if dashboard is not
             efficient . today i almost lost my temper & loss moved to
             20K at one time. but as markets are good & recovered today
             which is not guaranteed on every day & i can't take trade
             on the clumsy dashboards"

        Every ingredient for this already existed and none of it was
        ever assembled into an answer. The shortlist scored stocks. The
        movement pass knew which were running. The chain knew BUY from
        AVOID. The gate knew what was blocked. He got all four as
        separate panels and had to do the join himself, by eye, while a
        position moved against him.

        This does the join.

        A stock earns a place only if ALL of these are true:

            it has a REASON        at least one chip -- a result, an
                                   order, a filing. "without any thing
                                   stock doesn't move, that something
                                   is we need to find out"
            it is MOVING NOW       the reason is being acted on by the
                                   market, in the last fifteen minutes
            the chain says GO      BUY or SHORT, never WAIT or AVOID
            it is TRADEABLE        not blocked, not already held

        Four filters, and the last two are the ones that make it short.
        Six rows maximum, because a list he has to scroll is a list he
        has to search.

        Empty is a legitimate answer and is said out loud. A screen
        that always finds six things to trade is a screen that will
        find six things on a day with nothing worth doing.
        """
        rows = (shortlist or {}).get("rows") or []
        if not rows:
            return {"rows": [], "note": "nothing scored yet"}

        gl = gainers_losers or {}
        moving = {}
        for side in ("gainers", "losers"):
            for row in gl.get(side) or []:
                if row.get("moving"):
                    moving[row.get("symbol")] = row

        held = set(open_positions or {})
        out = []
        for row in rows:
            symbol = row.get("symbol")
            if not symbol or symbol in held:
                continue
            state = str(row.get("chain_state") or "").upper()
            if state not in ("BUY", "SHORT"):
                continue
            if not (row.get("support") or 0):
                continue
            live = moving.get(symbol)
            if not live:
                continue
            if row.get("veto"):
                continue

            direction = "SHORT" if (live.get("recent_pct") or 0) < 0 else "BUY"
            out.append({
                "symbol": symbol,
                "action": direction,
                "ltp": row.get("ltp"),
                "change_pct": row.get("change_pct"),
                "recent_pct": live.get("recent_pct"),
                "sector": row.get("sector"),
                "grade": row.get("channel_grade"),
                "grade_from": row.get("channel_grade_from"),
                # The single strongest reason, already sorted by weight
                # in core/shortlist.py. He gets one line, not five
                # chips to weigh himself.
                "why": (row.get("why") or [None])[0],
                "why_all": row.get("why") or [],
                "support": row.get("support"),
                "against": row.get("against"),
                "score": row.get("score"),
                "news": (live.get("why_now") or {}).get("text"),
                # Has the bot ever seen this stock trade? YASHO had a
                # BUY button here on the first live day with zero price
                # history behind it. 3 August 2026.
                "coverage": _coverage(symbol),
            })
            if len(out) >= self.CALLS_MAX:
                break

        return {"rows": out,
                "note": "" if out else
                        "nothing meets the bar right now -- a reason, "
                        "movement behind it, and a clear call"}

    def build_book(self, open_positions):
        """EVERY position you hold, wherever the order came from.

        ---- ONE TABLE. 3 August 2026. ----

            "no . i said make all even . user can trade from any place-
             same rules applicable - ONLY MTF ORDERS, 1 LAKH MAX
             POSITION ... BUT DASHBOARD MUST SHOW ALL the positions
             irrespective of traded mechanism (dhan platforms /
             dashboard)"

        Until now there were two panels. POSITIONS held what the bot had
        opened; AT THE BROKER held everything else and shouted MISMATCH
        about it. On the first live day that split hid YASHO 24 and
        ABCAPITAL 1000 in plain sight -- both on the page, neither
        findable, because they were in the panel that looked like an
        error report.

        He trades from the Dhan app, the website, charts, a terminal and
        this dashboard. All five produce the same thing: a position.
        Where the click happened is not a property of the trade.

        So: DHAN IS THE LIST. One row per holding, same columns for all.
        The bot's own knowledge -- entry reason, stop level, how long it
        has been held -- is attached where it exists and blank where it
        does not, exactly like any other missing field.

        `bot_managed` is the one flag, and it is NOT a judgement about
        where he traded. It answers a single question: will anything
        happen to this position without him? The bot may only stop and
        exit what it opened, so for everything else the honest answer is
        no, and a man deciding whether to walk away from the screen
        needs that in one glance.
        """
        rows = []
        held = dict(open_positions or {})

        broker = None
        try:
            executor = getattr(self.engine, "execution", None)
            executor = getattr(executor, "executor", executor)
            reader = getattr(executor, "positions", None)
            broker = reader() if reader else None
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BOOK] Could not read positions from Dhan: {exc}")

        if broker is None:
            # PAPER, or the broker could not be reached. Show the bot's
            # own book and SAY which it is -- "we could not ask" must
            # never be drawn as "you hold nothing".
            for symbol, pos in held.items():
                rows.append(self._book_row(symbol, pos, None))
            return {"available": bool(held), "rows": rows,
                    "source": "bot only",
                    "note": "could not read Dhan -- showing the bot's own "
                            "book, which may be behind"}

        seen = set()
        # A broker reply is somebody else's data structure. Reading it
        # without checking the shape is what stopped main.py on the
        # morning of 4 August -- see LiveExecution.positions().
        if not isinstance(broker, list):
            warn(f"[BOOK] Dhan's positions came back as "
                 f"{type(broker).__name__}, not a list. Showing the bot's "
                 f"own book.")
            broker = []
        for entry in broker:
            if not isinstance(entry, dict):
                continue
            symbol = str(entry.get("tradingSymbol")
                         or entry.get("symbol") or "").upper()
            if not symbol:
                continue
            seen.add(symbol)
            rows.append(self._book_row(symbol, held.get(symbol), entry))

        # In the bot's book, gone from Dhan. Closed elsewhere -- still
        # shown, because a row that vanishes without explanation is how
        # he stops trusting the table.
        for symbol, pos in held.items():
            if symbol not in seen:
                row = self._book_row(symbol, pos, None)
                row["qty"] = 0
                row["stale"] = True
                rows.append(row)

        rows.sort(key=lambda r: (not r.get("bot_managed"), r.get("symbol")))
        return {"available": True, "rows": rows, "source": "dhan",
                "at": datetime.now().strftime("%H:%M:%S")}

    def _book_row(self, symbol, pos, broker_entry):
        """One holding, from both sides, with neither pretending."""
        row = {"symbol": symbol, "bot_managed": bool(pos), "stale": False}

        if broker_entry:
            row["qty"] = _num(broker_entry.get("netQty")
                              or broker_entry.get("quantity"))
            row["avg_price"] = _num(broker_entry.get("costPrice")
                                    or broker_entry.get("buyAvg"))
            row["product"] = broker_entry.get("productType") or ""
        elif pos:
            row["qty"] = pos.get("qty")
            row["avg_price"] = pos.get("entry_price")
            row["product"] = "MTF"

        # What the BOT knows, where it knows it. Absent is absent.
        if pos:
            row["entry_reason"] = pos.get("entry_reason")
            row["direction"] = pos.get("direction") or "LONG"
            row["stop"] = pos.get("initial_stop")
            row["entry_time"] = pos.get("entry_time")

        try:
            price = self.market_data.get_price(symbol) \
                if self.market_data else None
        except Exception:                                  # noqa: BLE001
            price = None
        row["cmp"] = price
        qty, avg = row.get("qty"), row.get("avg_price")
        if price and qty and avg:
            row["pnl"] = round((price - avg) * qty, 2)
            row["pnl_pct"] = round((price - avg) / avg * 100.0, 2)
        else:
            row["pnl"] = None
            row["pnl_pct"] = None

        # THE HOUSE RULES, APPLIED TO EVERY ROW EQUALLY.
        #
        #   "same rules applicable - ONLY MTF ORDERS, 1 LAKH MAX
        #    POSITION , WHAT EVER QTY BELOW THE 1 LAKH USER CHOICE. if
        #    the user wants he can place more qty order from dhan
        #    platforms thats his choice."
        #
        # So this MEASURES and never blocks. A position over the cap is
        # marked, not scolded -- he said outright that going bigger from
        # the Dhan app is his call to make.
        try:
            from config import MTF_MARGIN_PER_POSITION_RS as cap
        except Exception:                                  # noqa: BLE001
            cap = 100_000.0
        value = (price or avg or 0) * (qty or 0)
        row["value_rs"] = round(abs(value), 2) if value else None
        row["over_cap"] = bool(row["value_rs"] and row["value_rs"] > cap * 4)
        row["not_mtf"] = bool(row.get("product")
                              and str(row["product"]).upper() != "MTF")
        return row

    def build_broker_stop(self, open_positions):
        """Which open positions have a stop resting at Dhan.

            "we can do this at live market too? without stopping
             main.py?"                 -- operator, 2 August 2026

        `unprotected` is the number that matters and it is computed
        rather than assumed: a position this module has no resting
        order for is one that dies with the process. Never raises -- a
        panel must not be able to take the snapshot down.
        """
        stop = getattr(self.engine, "broker_stop", None)
        if stop is None:
            return {"available": False, "enabled": False,
                    "note": "broker stop not wired"}
        try:
            resting = stop.resting()
            held = list(open_positions or {})
            unprotected = [s for s in held if s not in resting]

            # ---- "NO STOP AT DHAN" IS PAPER'S DEFINITION. 24 Aug ----
            #
            #     "3 POSITIONS WITH NO STOP AT DHAN: JBMA, NCC, CDSL.
            #      why?"                -- operator, 24 August 2026
            #
            # Because the broker stop is DISABLED in PAPER, on purpose:
            # "BROKER_STOP_ENABLED is on but TRADING_MODE is PAPER".
            # Nothing rests at Dhan, so held-minus-resting is the whole
            # book, every cycle, in red.
            #
            # Those three were simulated fills carried from Friday.
            # They are not unprotected: their stops are live in this
            # process, which is exactly what the panel's OWN next
            # branch says -- "broker stop OFF, stops live in this
            # process only" -- and which it could never reach, because
            # the red branch fires first.
            #
            # This is the third place the same mistake was made: the
            # bot's simulated book compared against the real account.
            # core/broker_sync.py stopped DELETING paper positions on
            # 21 August and stopped WARNING about them on 24 August.
            # A missing resting order is a real alarm only when one was
            # supposed to be there.
            if not stop.enabled:
                unprotected = []
            return {
                "available": True,
                "enabled": bool(stop.enabled),
                "resting": len(resting),
                "open": len(held),
                "unprotected": unprotected,
                "levels": {s: v.get("trigger") for s, v in resting.items()},
                "note": ("" if stop.enabled else
                         "OFF -- every stop lives in this process only. "
                         "If it dies, nothing protects an open position."),
            }
        except Exception as exc:                           # noqa: BLE001
            warn(f"[BROKER_STOP] Panel build failed: {exc}")
            return {"available": False, "enabled": False, "note": str(exc)}

    def build_results_today(self):
        """Who reports today, and who reports in the next few days.

            "Results, Corporate actions of the day"
                                        -- operator, 30 July 2026

        The data has been in core/results_calendar.py all along, driving
        the shortlist's REPORTING TODAY chip. It was never a panel, so
        the plain question -- who reports today -- could only be answered
        by reading chips off a ranked list of something else.

        `today` is the set that matters before the open. `soon` is the
        next seven days, because a result two days out is a reason not to
        hold something overnight, and the operator carries positions now.
        """
        if self.results_calendar is None:
            return {"available": False,
                    "note": "results calendar not wired"}
        try:
            today = sorted(self.results_calendar.symbols_on())
        except Exception as exc:                           # noqa: BLE001
            warn(f"[RESULTS] Panel build failed: {exc}")
            return {"available": False, "note": str(exc)}

        soon = []
        try:
            for row in self.results_calendar.upcoming(days=7) or []:
                symbol = row.get("symbol") if isinstance(row, dict) else None
                when = row.get("results_date") if isinstance(row, dict) else None
                if not symbol or symbol in today:
                    continue
                soon.append({
                    "symbol": symbol,
                    # A date object is not JSON. One un-encodable value
                    # here is a 500 for the whole snapshot, not just this
                    # panel -- the same failure the stock card hit.
                    "on": when.isoformat() if hasattr(when, "isoformat")
                          else (str(when) if when else None),
                    "purpose": (row.get("purpose") or "")[:80],
                })
        except Exception as exc:                           # noqa: BLE001
            warn(f"[RESULTS] Upcoming failed: {exc}")

        # Held positions reporting today are the ones that can gap under
        # the operator overnight, so they are named separately rather
        # than left to be spotted in a list.
        held = []
        try:
            held = sorted(set(self.engine.open_positions) & set(today))
        except Exception:                                  # noqa: BLE001
            pass

        # ---- DURING OR AFTER THE CLOSE, 2 August 2026 ----
        #
        #   "what about watchlist = stocks reporting results during
        #    markets / after markets = todays + next day watchlist"
        #
        # The list above answers WHO reports today. It does not answer
        # WHEN in the day, and that is the only part that changes what
        # you do about it:
        #
        #   DURING   the move happens while you are watching
        #   AFTER    the market is shut when the numbers land, so it
        #            cannot be traded until the next open -- the
        #            early-bird window
        #
        # Merging the two, which is what this panel did, hides the
        # distinction entirely. core/reporting.py splits them, adds
        # tomorrow, and carries the BUY/WAIT/AVOID call for any name
        # the chain has already read.
        watch = None
        try:
            calls = {}
            try:
                for row in (self._build_shortlist() or {}).get("rows") or []:
                    if row.get("chain_state"):
                        calls[row["symbol"]] = row["chain_state"]
            except Exception:                              # noqa: BLE001
                pass
            # ---- THE TIER HE ASKED FOR, 2 August 2026 ----
            #
            #     "why divis, SHADOWFAX, AETHER, YASHO are not showing
            #      EXCEPTIONAL? in watchlist"
            #
            # Four EXCEPTIONAL names in the store, none of them on the
            # panel. Read straight from the SETUP events rather than
            # off the shortlist, because the shortlist is the top 50
            # movers and a stock reporting tomorrow has not moved yet.
            try:
                tiers = canslim_tiers()
            except Exception:                              # noqa: BLE001
                tiers = {}
            watch = reporting_watchlist(calls=calls, tiers=tiers)
            watch["counts"] = reporting_counts(watch)
            # ---- ONE CATALYST LIST, 2 August 2026 ----
            #
            #   "later this watchlist will carry the stocks which were
            #    sorted by news, orders, govt policy, fed, rbi, or any
            #    other things stocks/sector specifics like fda on
            #    pharmas ... commodities - gold, silver, aluminium on
            #    their related stocks, steel = related stocks"
            #
            # So the panel is fed a CATALYST list, not a results list.
            # Results is simply the only catalyst firing today. When a
            # theme is wired, core/watchlist.fan_out() adds its names
            # to this same list and nothing here changes.
            watch["rows"] = watchlist_build(results_view=watch,
                                            calls=calls)
            watch["by_catalyst"] = watchlist_counts(watch["rows"])
        except Exception as exc:                           # noqa: BLE001
            warn(f"[RESULTS] Watchlist failed: {exc}")

        return {"available": True, "today": today, "today_count": len(today),
                "soon": soon[:20], "held_reporting_today": held,
                "watchlist": watch}

    def build_calendar(self):
        """FOMC / RBI / CPI -- what is coming and whether it lands
        inside a session.

            "it doesn't know when FED meeting, RBI Meeting will
             happen"              -- operator, 29 July 2026

        Static dates, no network. Shown, never acted on: the operator
        settled that himself -- FOMC resolves at 23:30 IST while he is
        flat, so there is nothing to pause. RBI at ~10:00 IST is the
        one that lands with positions open, and what to do about that
        is his call, not a rule.
        """
        try:
            from core.econ_calendar import recent, upcoming
            out = upcoming()
            # WHAT ALREADY HAPPENED, added 30 July 2026. upcoming() only
            # looks forward, so last night's FOMC -- a date sitting in the
            # bot's own FOMC_2026 list -- was invisible on the morning it
            # mattered, and the panel showed the NEXT one 48 days out.
            #
            #     "last night FED meeting but today bot doesn't know
            #      anything about that & why markets are weakly opened"
            #
            # The event that explains a tape is always in the past by the
            # time you are trading it.
            out["recent"] = recent()
            return out
        except Exception as exc:                           # noqa: BLE001
            warn(f"[CALENDAR] Panel build failed: {exc}")
            return None

    def _preopen_cached(self):
        """The pre-open book, built ONCE per session.

        ---- 8.9 GB OF A FROZEN NUMBER. 29 August 2026 ----

            "i need the bot to be precise & earn not to collection
             agent"                        -- operator, 29 Aug 2026

        NSE collects orders 09:00-09:08 and matches them 09:08-09:12
        into one opening price per stock. After 09:12 the exchange
        publishes NOTHING more: the book is finished.

        build_preopen() was called on every snapshot cycle anyway.
        Measured on 29 August:

            snapshot payload   1,275,565 bytes
            preopen            1,065,470 bytes = 84% of it
            ~8,308 cycles a session -> 8.9 GB re-serialised

        At 14:30 the bot was still rebuilding this morning's opening
        auction, in full, every 2.6 seconds, for data that could not
        have changed since 09:12. That is not collecting -- it is
        re-packaging a finished thing, and it was 84% of every
        dashboard refresh.

        Rebuilt while the book is still forming (before 09:15), then
        frozen for the day. Keyed on the DATE so tomorrow builds its
        own, and a None result is never cached -- an empty answer at
        09:02 must not become the answer at 11:00.
        """
        from datetime import date, datetime
        today = date.today().isoformat()
        cache = getattr(self, "_preopen_cache", None)
        if cache and cache.get("day") == today and cache.get("book") is not None:
            return cache["book"]
        book = self.build_preopen()
        # Only freeze it once the book is closed and real.
        if book is not None and datetime.now().strftime("%H:%M") >= "09:15":
            self._preopen_cache = {"day": today, "book": book}
        return book

    def build_preopen(self):
        """NSE's 09:00-09:12 book -- where every stock opens, and the
        unmatched order imbalance behind it.

        Four groups, because that is the operator's actual routine:

            "i'll check these NIFTY50, ALL NIFTY, FNO STOCKS for top
             gainers/loosers both in pre-open markets sessions"

        A group whose membership we do not have is OMITTED, not shown
        unfiltered. The first version drew all four buttons and served
        the same list under each -- which would have been believed at
        09:05 tomorrow.
        """
        try:
            if self.preopen is None:
                return None
            mine = self.master_loader.all_symbols() \
                if self.master_loader else None
            snapshot = self.preopen.snapshot(symbols=mine)
            if not snapshot.get("available"):
                return snapshot

            # gaps() returns a third list now -- the rows NSE published
            # no pChange for, plus the exactly-flat ones. They carry a
            # real IEP and a real book and they must reach the panel:
            #
            #     "never throw away any symbol that gets in either
            #      direction"       -- operator, 1 August 2026
            groups = {"mine": {"label": f"My {len(mine or [])}",
                               "gap_up": snapshot.get("gap_up"),
                               "gap_down": snapshot.get("gap_down"),
                               "gap_unknown": snapshot.get("gap_unknown")}}
            # "All NSE" needs no membership list -- it is every symbol
            # NSE published a book for.
            up, down, unknown = self.preopen.gaps(symbols=None)
            groups["all"] = {"label": "All NSE", "gap_up": up,
                             "gap_down": down, "gap_unknown": unknown}

            if self.index_members is not None:
                for key, label in (("nifty50", "NIFTY 50"), ("fno", "F&O")):
                    members = self.index_members.members(key)
                    if not members:
                        continue          # unknown -> no button at all
                    up, down, unknown = self.preopen.gaps(symbols=members)
                    groups[key] = {"label": f"{label} ({len(members)})",
                                   "gap_up": up, "gap_down": down,
                                   "gap_unknown": unknown}

            snapshot["groups"] = groups
            snapshot["top"] = self._preopen_top(snapshot)
            return snapshot
        except Exception as exc:                           # noqa: BLE001
            warn(f"[PREOPEN] Panel build failed: {exc}")
            return None

    # How many rows per side. His answer when asked for a gap
    # threshold: "top 10 gainers /losers". A count, not a percentage --
    # a 1.5% cut is a different list every morning, and ten is ten.
    PREOPEN_TOP = 10

    def _preopen_top(self, snapshot):
        """The two lists he actually opens at 09:00.

        ---- TWO THOUSAND ROWS. 3 August 2026. ----

            "Pre-open is printing all universe stocks why? we want only
             the stocks with more gapups + Buyers waiting stocks ;
             gapdowns + sellers waiting in two tabs under Pre-market
             main tab"

        Measured on his real file: 1,684 gap-ups, 337 gap-downs and 203
        unknown -- 2,224 rows, and not even filtered to stocks he can
        trade. Nobody reads that at 09:00.

        THE DUAL PICTURE
        ----------------
            "two sub-tabs be strict - yes with gapup + sellers shows
             the dual picture"

        So the two tabs split by GAP DIRECTION only, and the order book
        is shown inside each rather than used to filter it. That is the
        more useful arrangement, and it was his idea: a stock gapping
        +4% with SELLERS queued is not a broken row, it is the fade --
        the gap is not going to hold. Dropping it, as I first proposed,
        would have thrown away the most interesting name on the screen.

        buy_qty and sell_qty come straight from NSE's 09:00-09:12
        auction. Nothing here is computed by the bot except the ratio.
        """
        def dress(rows, side):
            out = []
            for row in rows or []:
                buy = float(row.get("buy_qty") or 0)
                sell = float(row.get("sell_qty") or 0)
                if buy > sell and sell > 0:
                    who, times = "buyers", buy / sell
                elif sell > buy and buy > 0:
                    who, times = "sellers", sell / buy
                elif buy > 0 and not sell:
                    who, times = "buyers", None
                elif sell > 0 and not buy:
                    who, times = "sellers", None
                else:
                    who, times = None, None
                item = dict(row)
                item["waiting"] = who
                item["waiting_times"] = round(times, 1) if times else None
                # ---- AN UNTESTED SIGNAL. 3 August 2026. ----
                #
                #   "MUTHOOTFIN gapped -7.81% with 2.7x more buyers
                #    queued - fell like hell too"
                #
                # He watched it. I had one morning's file and no way to
                # check, because data/preopen.json is OVERWRITTEN every
                # day -- there is no archive, so this has never been
                # scored against a single outcome.
                #
                # The likely mechanism, and it argues against reading a
                # queue as support: NSE publishes total buy and sell
                # quantity across the WHOLE pre-open book, including
                # limit orders far from the indicative price. On a hard
                # gap down, bargain hunters stack bids well below --
                # they inflate buy_qty and never fill. "More buyers"
                # can therefore mean "a lot of lowball bids and nobody
                # willing to pay up", which is the opposite of support.
                #
                # So `agrees` stays as a RECORDED field for scoring and
                # is never drawn. The panel shows what NSE published --
                # 2.7x more buyers -- and stops there.
                item["agrees"] = (who == "buyers") if side == "up" \
                    else (who == "sellers")
                item["untested"] = True
                item["adv_cr"] = _adv(row.get("symbol"))
                out.append(item)
            # Biggest gap first. He asked for the top ten gainers and
            # losers, and the gap IS the ranking.
            out.sort(key=lambda r: -abs(r.get("gap_pct") or 0))
            return out[:self.PREOPEN_TOP]

        # ---- ALL FOUR GROUPS, NOT JUST 'MINE'. 4 August 2026. ----
        #
        #     "i'll check these NIFTY50, ALL NIFTY, FNO STOCKS for top
        #      gainers/loosers both in pre-open markets sessions"
        #
        # build_preopen has computed My / All NSE / NIFTY 50 / F&O since
        # it was written, and the panel has only ever drawn "mine". The
        # markup even has a <div id="poGroups"> for the buttons -- empty,
        # never written to, in every version of this file.
        groups = snapshot.get("groups") or {}
        tops = {}
        for key, group in groups.items():
            tops[key] = {
                "label": group.get("label") or key,
                "gap_up": dress(group.get("gap_up"), "up"),
                "gap_down": dress(group.get("gap_down"), "down"),
            }
        mine = groups.get("mine", {})
        return {"gap_up": dress(mine.get("gap_up"), "up"),
                "gap_down": dress(mine.get("gap_down"), "down"),
                "groups": tops,
                "n_seen": snapshot.get("shown", 0),
                "per_side": self.PREOPEN_TOP}

    def price_check_rows(self):
        """EVERY symbol the bot currently has a price for, unfiltered.

        Built 2026-07-29 for tools/nse_check.py, after the operator
        put data accuracy ahead of everything else:

            "NSE & BOT are not synchronised ... do not deviate from
             NSE"

        Deliberately NOT _compute_gl_rows(). That method drops rows on
        purpose -- implausible moves, circuit-locked names -- which is
        right for a ranked table and wrong here: a symbol being
        excluded from Top Gainers is itself something worth comparing
        against NSE. This returns the raw numbers with nothing removed
        and nothing ranked.

        Read-only. Touches no trading path.
        """
        snapshot = self.engine.get_circuit_snapshot()
        rows = []
        for symbol, quote in snapshot.items():
            live = self.market_data.get_latest_price(symbol)
            rest = quote.get("last_price")
            prev_close = quote.get("prev_close")
            last = live if live is not None else rest
            pct = None
            if last is not None and prev_close:
                pct = (last - prev_close) / prev_close * 100
            rows.append({
                "symbol": symbol,
                "last": last,
                # Both are reported separately on purpose: if the live
                # tick and the REST poll disagree, that is itself the
                # answer to "why doesn't this match NSE".
                "live_tick": live,
                "rest_quote": rest,
                "prev_close": prev_close,
                "change_pct": None if pct is None else round(pct, 2),
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "upper_circuit": quote.get("upper_circuit_limit"),
                "lower_circuit": quote.get("lower_circuit_limit"),
            })
        rows.sort(key=lambda r: r["symbol"])
        return {"rows": rows, "count": len(rows),
                "at": datetime.now().strftime("%H:%M:%S")}

    def _compute_gl_rows(self):
        """MEMOISED FOR ONE BUILD -- see _build()'s note. This walks
        1,314 symbols and had SEVEN callers, five unthrottled, so it
        ran eleven times in two seconds and the snapshot fell minutes
        behind a live market. The cache is cleared at the top of every
        _build(), so a build never reuses the previous one's rows.

        One per-symbol pass over engine.get_circuit_snapshot()
        (core/circuit_monitor.py's already-running REST poll, not a
        new data source), producing the raw rows BOTH the stock-level
        Top 50 Gainers/Losers table and the Sector Heatmap rank from.
        Split out 2026-07-24 (previously inlined directly in what's
        now _build_stock_gainers_losers()) so the two tables can each
        call this fresh on their OWN cadence -- see
        GAINERS_LOSERS_REFRESH_SECONDS (60s) vs
        SECTOR_GAINERS_LOSERS_REFRESH_SECONDS (5s) in config.py.
        Deliberately NOT cached here itself: each caller's own
        throttle (below) already controls how often this actually
        runs; a third cache layer here would just add complexity for
        no benefit, since neither caller runs more often than its own
        throttle allows anyway.
        """
        held = getattr(self, "_gl_rows_this_build", None)
        if held is not None:
            return held

        snapshot = self.engine.get_circuit_snapshot()

        # Instrumentation, 2026-07-28. Three panels went silent live --
        # Gainers/Losers, Sector Heatmap and Shortlist, the only three
        # that share this method -- while Breadth counted all 668. Rather
        # than guess a third time at WHICH exclusion is emptying it, count
        # them and say so once a minute.
        skipped = {"no_quote": 0, "no_prev_close": 0, "no_price": 0,
                   "implausible": 0, "circuit_locked": 0}

        rows = []
        for symbol, quote in snapshot.items():
            prev_close = quote.get("prev_close")
            # PREFER THE LIVE TICK, fall back to the REST snapshot --
            # exactly what _build_breadth() has always done.
            #
            # 2026-07-28, live: breadth counted all 668 symbols while
            # Top 50 Gainers/Losers, the Sector Heatmap and the Shortlist
            # were ALL empty at 09:16. Those three are the only consumers
            # of this method, and it read last_price from the REST
            # snapshot alone. Right after the open the snapshot has a
            # prev_close but not yet an LTP for most symbols, so every
            # row was skipped -- while the WebSocket had already been
            # ticking for a minute.
            last_price = self.market_data.get_latest_price(symbol)
            if last_price is None:
                last_price = quote.get("last_price")
            if not prev_close:
                skipped["no_prev_close"] += 1
                continue
            if last_price is None:
                skipped["no_price"] += 1
                continue

            change = last_price - prev_close
            change_pct = (change / prev_close) * 100

            # 2026-07-24 -- same split/bonus prev_close artifact
            # filter as _build_breadth() (JLHL's 2:10 split), applied
            # here too so the same fake move can't show up ranked in
            # Top Losers/Gainers either. Excluded outright (not just
            # zeroed like breadth does) -- there's no "unchanged"
            # bucket in a ranked table, an untrustworthy row simply
            # shouldn't compete for a rank at all.
            if not _is_plausible_move(
                change_pct, prev_close,
                quote.get("upper_circuit_limit"), quote.get("lower_circuit_limit"),
            ):
                skipped["implausible"] += 1
                continue

            # CEMPRO, locked at its 5% lower circuit -- zero real
            # order flow, excluded from the ranked table entirely
            # (still counts normally in breadth; being locked doesn't
            # change whether the move itself is real, only whether
            # it's currently tradeable, see _is_circuit_locked()'s
            # docstring).
            if _is_circuit_locked(
                last_price, quote.get("upper_circuit_limit"),
                quote.get("lower_circuit_limit"),
            ):
                skipped["circuit_locked"] += 1
                continue

            record = self.master_loader.get_by_symbol(symbol)
            sector = record.get("SECTOR") if record else None

            # ---- THE RANGE MUST CONTAIN THE PRICE. 13 Aug 2026. ----
            #
            #     "dashboard showing high & low of orb range right? &
            #      cmp is the live rate of stock"     -- operator
            #
            # They are the DAY's high and low, not the opening range --
            # and asking the question exposed that they disagreed with
            # the price beside them. Measured at 10:36 on 100 live rows:
            #
            #     CMP above the High   34
            #     CMP below the Low    29
            #     worst  SARDAEN  high 514.40  CMP 534.65  (3.94% out)
            #
            # Two sources, two update rates. `last_price` prefers the
            # LIVE TICK (see the note above); open/high/low come from
            # circuit_monitor's REST quote, which lags by a poll cycle.
            # So the row showed a stock trading 4% above its own day
            # high, on the screen used to decide entries.
            #
            # Not invented data: if it is trading at 534.65 then the
            # day's high IS at least 534.65. This widens the range to
            # the price already shown, never the other way round --
            # the REST value still wins whenever it is the extreme.
            day_high = quote.get("high")
            day_low = quote.get("low")
            if last_price:
                day_high = max(day_high or last_price, last_price)
                day_low = min(day_low or last_price, last_price)

            rows.append({
                "symbol": symbol,
                "sector": sector,
                "open": quote.get("open"),
                "high": day_high,
                "low": day_low,
                "prev_close": prev_close,
                "ltp": last_price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": quote.get("volume"),
                # UC / LC on the row the operator actually clicks BUY
                # from. circuit_monitor has polled these every few
                # seconds since 24 July and this builder threw them
                # away, so the one table used to enter a trade was the
                # one place the band was invisible:
                #
                #   "while clicking any buy we cannot see the stocks
                #    UC & LC"          -- operator, 30 July 2026
                #
                # SMLMAH was bought AT its upper circuit on 29 July.
                "upper_circuit": quote.get("upper_circuit_limit") or None,
                "lower_circuit": quote.get("lower_circuit_limit") or None,
                "pct_to_upper": (
                    round((quote["upper_circuit_limit"] - last_price)
                          / last_price * 100, 2)
                    if quote.get("upper_circuit_limit") and last_price else None),
                "pct_to_lower": (
                    round((last_price - quote["lower_circuit_limit"])
                          / last_price * 100, 2)
                    if quote.get("lower_circuit_limit") and last_price else None),
            })

        if not rows and snapshot:
            warn(f"[GL] {len(snapshot)} symbols in the snapshot but ZERO "
                 f"rows produced. Skipped: {skipped}")
        elif rows:
            diagnostic(f"[GL] {len(rows)} rows from {len(snapshot)} symbols. "
                       f"Skipped: {skipped}")

        # ==========================================================
        # THE CLOSE IS STILL DATA.  12 August 2026.
        # ==========================================================
        #
        #     "why dashboard is still showing empty ? it has todays
        #      complete data right? why it cant display them all stocks
        #      with their reasons"
        #
        # It did have it. Measured at 23:08 on a freshly restarted
        # main.py:
        #
        #     tick_count            0        market shut since 15:30
        #     feed_alive            False
        #     advances/declines     0 / 0    1,314 read as "unchanged"
        #     gainers / losers      0 / 0
        #
        # and at the same moment data/daily_candles.db held today's
        # close, prev_close and volume for every one of those symbols.
        # ARDEE +26.6%, SINGERIND +20.0%, TDPOWERSYS +16.0% -- a full
        # session, on disk, that no panel could see.
        #
        # This method reads circuit_monitor's REST quote poll, which
        # keeps answering after hours but stops carrying a usable last
        # price -- so every row failed the "no_price" test and the
        # board drew an empty table on top of a complete database.
        #
        # So when the live path yields nothing, fall back to the stored
        # session. Every row is stamped `at_close` and carries its
        # date, and build_stock_gainers_losers passes that through, so
        # the screen can say WHICH session it is showing. A close
        # presented as a live price would be far worse than an empty
        # table; a close LABELLED as a close is the answer to his
        # question.
        #
        # Never overrides live data -- `if rows` returns above.
        if not rows:
            rows = self._gl_rows_from_the_close()
        self._gl_rows_this_build = rows
        return rows

    def _gl_rows_from_the_close(self):
        """Today's session out of data/daily_candles.db, or [].

        Only reached when the live path produced nothing. Read-only,
        short timeout, and any failure returns [] -- an after-hours
        convenience must never be able to break the panel it is
        standing in for.
        """
        import os
        import sqlite3

        # ---- A TEST MUST NOT READ THE LIVE STORE. 12 Aug 2026. ----
        # This hardcoded data/daily_candles.db, so the first suite run
        # after it shipped had a unit test asserting an empty table get
        # 2,459 rows of the real session back. Tests that reach into
        # production data are how the YASHO liquidity assertion rotted
        # earlier the same day.
        #
        # Injectable, defaulting to the real store. Nothing in
        # production passes it; the tests do.
        path = getattr(self, "daily_candles_path", None) \
            or os.path.join("data", "daily_candles.db")
        if not os.path.exists(path):
            return []
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True,
                                   timeout=2.0)
        except Exception:                                  # noqa: BLE001
            return []
        try:
            latest = conn.execute(
                "select max(date) from daily_bars").fetchone()[0]
            if not latest:
                return []
            found = conn.execute(
                "select symbol, open, high, low, close, prev_close, volume "
                "from daily_bars where date = ? and prev_close > 0",
                (latest,)).fetchall()
        except Exception:                                  # noqa: BLE001
            return []
        finally:
            try:
                conn.close()
            except Exception:                              # noqa: BLE001
                pass

        # ---- THE SPLIT GUARD HAS TO BE A REAL ONE. ----
        #
        # First written as _is_plausible_move(change_pct, prev, None,
        # None). That function fails OPEN when circuit limits are
        # missing -- correctly, it is a fail-open helper -- and the
        # daily store carries no circuit bands, so the call was
        # decorative and a 2:10 split walked straight onto the board at
        # -80%. That is the JLHL failure this bot was built to stop,
        # arriving through a panel added to be helpful.
        #
        # core/stock_memory.py is the bot's own answer to "is this move
        # real or is the price scale different today", and it does not
        # need circuit limits to say so.
        distorted = set()
        try:
            from datetime import date as _date
            from core.stock_memory import default_memory
            on = _date.fromisoformat(str(latest))
            distorted = set(default_memory().price_distorting_symbols(on) or {})
            if distorted:
                diagnostic(f"[GL] {len(distorted)} symbol(s) excluded from "
                           f"the {latest} close -- corporate action makes "
                           f"the %-move meaningless.")
        except Exception:                                  # noqa: BLE001
            # No memory wired, or an unreadable store. The rows below
            # still carry their close honestly; this only costs the
            # split filter, and an empty table would cost more.
            distorted = set()

        rows = []
        for symbol, op, hi, lo, close, prev, vol in found:
            if not close or not prev:
                continue
            if symbol in distorted:
                continue
            change = close - prev
            change_pct = change / prev * 100.0
            record = self.master_loader.get_by_symbol(symbol) \
                if self.master_loader else None
            rows.append({
                "symbol": symbol,
                "sector": record.get("SECTOR") if record else None,
                "open": op, "high": hi, "low": lo,
                "prev_close": prev,
                "ltp": close,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": vol,
                "upper_circuit": None, "lower_circuit": None,
                "pct_to_upper": None, "pct_to_lower": None,
                # THE LABEL IS THE POINT. Without it this is a closing
                # price wearing a live one's clothes.
                "at_close": True,
                "as_of": str(latest),
            })
        if rows:
            when_it_changes(
                "gl-no-live-prices",
                f"[GL] No live prices -- showing the {latest} close "
                f"for {len(rows)} symbols, labelled at_close.")
        return rows

    def _build_stock_gainers_losers(self):
        """
        Top GAINERS_LOSERS_COUNT gainers and losers across the bot's
        own master universe, ranked by %-change vs each symbol's
        PREVIOUS DAY close -- see module docstring's "REPLACED
        2026-07-23 evening" section for why this table exists.
        Throttled to GAINERS_LOSERS_REFRESH_SECONDS (60s, 2026-07-24
        -- was 300s, then decoupled from the sector heatmap's own
        cadence, see config.py's comment): returns the cached result
        unless that much time has actually passed since the last
        rebuild, regardless of how often _build() itself runs
        (config.DASHBOARD_REFRESH_INTERVAL_SECONDS, much faster).
        time.monotonic() -- never wall clock -- same reasoning as
        every other cadence timer in this codebase (main.py's
        heartbeat/state-save loop): immune to a system clock
        adjustment.
        """
        now = time.monotonic()
        if self._gainers_losers_cache is not None and \
                now - self._gainers_losers_built_at < GAINERS_LOSERS_REFRESH_SECONDS:
            return self._gainers_losers_cache

        rows = self._compute_gl_rows()

        # dict(row) copies below are deliberate -- on a small universe
        # (fewer candidates than GAINERS_LOSERS_COUNT), the SAME
        # symbol can legitimately appear in both slices (e.g. only 3
        # symbols total, top-50 gainers/losers each just returns all
        # 3, reordered). Without copying, both tables would share the
        # same dict object per symbol, and stamping s_no for one
        # table would silently overwrite the other's.
        gainers = [dict(r) for r in
                   sorted(rows, key=lambda r: r["change_pct"], reverse=True)[:GAINERS_LOSERS_COUNT]]
        losers = [dict(r) for r in
                  sorted(rows, key=lambda r: r["change_pct"])[:GAINERS_LOSERS_COUNT]]
        for rank, row in enumerate(gainers, start=1):
            row["s_no"] = rank
        for rank, row in enumerate(losers, start=1):
            row["s_no"] = rank

        # Stamp movement BEFORE the two lists are cut from `rows`, so
        # both sides carry it and the history is sampled once.
        self._mark_movement(rows)
        gainers = [dict(r) for r in gainers]
        losers = [dict(r) for r in losers]
        by_symbol = {r.get("symbol"): r for r in rows}
        for side in (gainers, losers):
            for row in side:
                src = by_symbol.get(row.get("symbol")) or {}
                for key in ("recent_pct", "moving", "moving_dir", "why_now"):
                    if key in src:
                        row[key] = src[key]

        # Which session is on the screen. When the live path gave
        # nothing, _compute_gl_rows() falls back to the stored close and
        # stamps every row `at_close` -- see the note there. Lifted to
        # the top of the panel so the page can SAY so in one place
        # instead of every row having to be inspected. A closing price
        # shown without that label is a lie the operator would only
        # catch by noticing prices never move.
        at_close = bool(rows) and all(r.get("at_close") for r in rows)
        result = {
            "gainers": gainers,
            "losers": losers,
            "moving_now": sum(1 for r in rows if r.get("moving")),
            "reversals": self._find_reversals(rows),
            "built_at": datetime.now().strftime("%H:%M:%S"),
            "at_close": at_close,
            "as_of": (rows[0].get("as_of") if at_close and rows else None),
        }
        self._gainers_losers_cache = result
        self._gainers_losers_built_at = now
        return result

    # A stock has to have travelled this far from its extreme to count
    # as having TURNED. Below this it is noise on a quiet chart.
    REVERSAL_TRAVEL_PCT = 3.0
    # ...and it has to have been meaningfully extreme in the first
    # place. A stock that dipped 0.4% and recovered has not reversed
    # anything; it traded.
    REVERSAL_EXTREME_PCT = 3.0

    # How far back "moving NOW" looks. Short enough that a stock which
    # gapped at 09:15 and slept since is not still called a mover at
    # 14:00; long enough to survive one quiet minute.
    MOVING_WINDOW_SECONDS = 15 * 60
    # Below this the stock has not moved in that window -- it is
    # sitting on its number.
    MOVING_MIN_PCT = 0.4

    def _mark_movement(self, rows):
        """Say which of these is moving RIGHT NOW, and which is parked.

            "MOST top gainers were sitting at top and not moving in
             either direction & occupying most favored place on
             dashboard & making the next gainers invisible to user."
            "bot must find the moving stock in either direction with
             underlying news and update the table with same"
                                        -- operator, 3 August 2026

        He is describing the flaw in every gainers table ever built. It
        ranks by DISTANCE TRAVELLED SINCE YESTERDAY, so a stock that
        gapped 12% at 09:15 and has not ticked since outranks one
        moving 3% in the last ten minutes -- and takes the top of the
        screen, which is the space that decides what he looks at.

        Distance is history. What he can trade is what is moving.

        So every row carries, beside its day change:

            recent_pct   how far it has come in the last 15 minutes
            moving       True when that is worth noticing
            why_now      the freshest news on it, or None

        Ranking is left alone -- a table that re-sorts itself under a
        cursor is its own hazard, and he has had enough of those today.
        The MOVING flag is what the panel sorts and colours by, and a
        stalled leader can be collapsed rather than deleted.

        Fail-quiet: no history, no flag. Never raises.
        """
        import time

        now = time.time()
        history = getattr(self, "_move_history", None)
        if history is None:
            history = self._move_history = {}

        for row in rows or []:
            symbol = row.get("symbol")
            pct = row.get("change_pct")
            if not symbol or pct is None:
                continue
            trail = history.setdefault(symbol, [])
            trail.append((now, pct))
            # Keep a little more than the window so the oldest sample
            # inside it is a real one, not the only one.
            cutoff = now - (self.MOVING_WINDOW_SECONDS * 1.5)
            while trail and trail[0][0] < cutoff:
                trail.pop(0)

            window_start = now - self.MOVING_WINDOW_SECONDS
            older = [p for t, p in trail if t <= window_start]
            if not older:
                # Not enough history yet. Say so rather than calling it
                # stalled -- "we have not watched it long enough" and
                # "it is not moving" are different sentences.
                row["recent_pct"] = None
                row["moving"] = None
                continue
            moved = pct - older[-1]
            row["recent_pct"] = round(moved, 2)
            row["moving"] = abs(moved) >= self.MOVING_MIN_PCT
            row["moving_dir"] = "UP" if moved > 0 else (
                "DOWN" if moved < 0 else "FLAT")

            # ---- AND WHY ----
            # A mover with no reason beside it is the thing his whole
            # ideology is against: "without any thing stock doesn't
            # move, that something is we need to find out".
            if row["moving"]:
                row["why_now"] = self._why_moving(symbol)

        return rows

    def _why_moving(self, symbol):
        """The freshest thing said about this stock, or None.

        Cheap on purpose -- this runs for every flagged row on a
        one-second refresh. Reads what is already in memory and never
        goes near the network.
        """
        try:
            if self.news_watcher is not None:
                hit = self.news_watcher.for_symbol(symbol)
                if hit and hit.get("headline"):
                    return {"kind": hit.get("kind") or "NEWS",
                            "text": str(hit["headline"])[:120]}
        except Exception:                                  # noqa: BLE001
            pass
        try:
            if self.news_impact is not None:
                rows = self.news_impact.for_symbol(symbol, limit=1)
                if rows:
                    head = rows[0]
                    text = head.get("headline") or head.get("story") or ""
                    if text:
                        return {"kind": head.get("direction") or "IMPACT",
                                "text": str(text)[:120]}
        except Exception:                                  # noqa: BLE001
            pass
        return None

    def _find_reversals(self, rows):
        """Stocks that went hard one way and came back the other.

            "very rare events trigger stocks moving extreme negative to
             positive & viceversa . those stocks too follow the same
             rule."
                                        -- operator, 3 August 2026

        These are the rows a top-50 list cannot show. A stock down 6%
        at 10:00 and flat by 14:00 has done something violent, and it
        appears in NEITHER table: not a top gainer, not a top loser,
        just a middling number on a screen full of them.

        Measured from the day's own extreme, not from the open:

            turned UP    it traded down at least 3% below yesterday's
                         close, and has since climbed at least 3% off
                         that low
            turned DOWN  the mirror image

        Both thresholds matter. Travel alone catches a volatile stock
        that never went anywhere; extreme alone catches one that fell
        and stayed fallen. A reversal is BOTH -- it went, and it came
        back.

        `side` is where it is heading NOW, which is the side of the
        screen it belongs on. A stock that fell 6% and is climbing is a
        GAINER-side row even while its change_pct is still negative,
        because what it is doing is going up.
        """
        out = {"up": [], "down": []}
        for row in rows or []:
            prev = row.get("prev_close")
            low, high = row.get("low"), row.get("high")
            pct = row.get("change_pct")
            if not prev or pct is None:
                continue
            try:
                low_pct = (low - prev) / prev * 100.0 if low else None
                high_pct = (high - prev) / prev * 100.0 if high else None
            except (TypeError, ZeroDivisionError):
                continue

            if (low_pct is not None
                    and low_pct <= -self.REVERSAL_EXTREME_PCT
                    and (pct - low_pct) >= self.REVERSAL_TRAVEL_PCT):
                item = dict(row)
                item["turn"] = "UP"
                item["from_pct"] = round(low_pct, 2)
                item["travelled"] = round(pct - low_pct, 2)
                item["side"] = "gainers"
                out["up"].append(item)
                continue

            if (high_pct is not None
                    and high_pct >= self.REVERSAL_EXTREME_PCT
                    and (high_pct - pct) >= self.REVERSAL_TRAVEL_PCT):
                item = dict(row)
                item["turn"] = "DOWN"
                item["from_pct"] = round(high_pct, 2)
                item["travelled"] = round(high_pct - pct, 2)
                item["side"] = "losers"
                out["down"].append(item)

        # Biggest journey first -- the violence is the point.
        out["up"].sort(key=lambda r: -r["travelled"])
        out["down"].sort(key=lambda r: -r["travelled"])
        return out

    def _build_sector_gainers_losers(self):
        """
        sector_gainers/sector_losers -- "Sector Heatmap" in the UI
        (dashboard/static/index.html's own panel title), added
        2026-07-23 evening ("instead of deleting the sector heatmap,
        make it use like same top 50 gainers & losers... top gaining
        sectors / top loosing sectors"): each symbol's own row from
        _compute_gl_rows() is aggregated by SECTOR and averaged, same
        PREV-CLOSE basis. Sectors with fewer than
        SECTOR_GAINERS_LOSERS_MIN_SYMBOLS reporting symbols are
        dropped as too sparse to mean anything, same "too few is
        noise" reasoning used everywhere else in this codebase (e.g.
        the old INDUSTRY_HEATMAP_MIN_SYMBOLS this replaces,
        core/sector_monitor.py's SECTOR_PANIC_MIN_SYMBOLS). No S.No
        cap -- there are only ~29 sectors total, nowhere near
        GAINERS_LOSERS_COUNT, so every qualifying sector shows.

        Throttled to SECTOR_GAINERS_LOSERS_REFRESH_SECONDS (5s,
        2026-07-24) -- DECOUPLED from _build_stock_gainers_losers()'s
        own 60s cadence as of the same date (previously one shared
        cache/timer for both tables); each calls _compute_gl_rows()
        fresh on its own schedule now, so the two tables can (and by
        design now do) show data from two different underlying
        snapshots at any given moment.
        """
        now = time.monotonic()
        if self._sector_gainers_losers_cache is not None and \
                now - self._sector_gainers_losers_built_at < SECTOR_GAINERS_LOSERS_REFRESH_SECONDS:
            return self._sector_gainers_losers_cache

        rows = self._compute_gl_rows()

        sector_totals = {}
        for row in rows:
            # _text(), not `or ""`: a NaN sector is TRUTHY and used
            # to pass this guard, become a dict key, and crash the
            # whole snapshot 1,100 lines later. See _text().
            sector = _text(row.get("sector"))
            if not sector:
                continue
            total, count = sector_totals.get(sector, (0.0, 0))
            sector_totals[sector] = (total + row["change_pct"], count + 1)

        sector_rows = [
            {
                "sector": sector,
                "avg_change_pct": round(total / count, 2),
                "symbol_count": count,
            }
            for sector, (total, count) in sector_totals.items()
            if count >= SECTOR_GAINERS_LOSERS_MIN_SYMBOLS
        ]
        # Only the TOP N gaining + TOP N losing sectors (operator:
        # "we trade only momentum sectors of the day... show only top
        # 10 for both" -- config.SECTOR_HEATMAP_TOP_N). Listing all
        # ~29 sectors was noise and an unnecessary per-refresh burden.
        sector_gainers = [dict(r) for r in
                           sorted(sector_rows, key=lambda r: r["avg_change_pct"], reverse=True)
                           if r["avg_change_pct"] >= 0][:SECTOR_HEATMAP_TOP_N]
        sector_losers = [dict(r) for r in
                          sorted(sector_rows, key=lambda r: r["avg_change_pct"])
                          if r["avg_change_pct"] < 0][:SECTOR_HEATMAP_TOP_N]
        for rank, row in enumerate(sector_gainers, start=1):
            row["s_no"] = rank
        for rank, row in enumerate(sector_losers, start=1):
            row["s_no"] = rank

        result = {
            "sector_gainers": sector_gainers,
            "sector_losers": sector_losers,
            "built_at": datetime.now().strftime("%H:%M:%S"),
        }
        self._sector_gainers_losers_cache = result
        self._sector_gainers_losers_built_at = now
        return result

    def _build_gainers_losers(self):
        """
        Merges the two independently-throttled builds above into the
        ONE "gainers_losers" snapshot key the frontend already reads
        (dashboard/static/index.html's `gl.gainers`/`gl.losers`/
        `gl.sector_gainers`/`gl.sector_losers`) -- kept as a single
        combined key so the 2026-07-24 cadence split needed zero
        frontend changes beyond the new sector_built_at timestamp.
        `built_at` reflects the STOCK table specifically (the
        original field, still read by index.html's glUpdatedAt);
        `sector_built_at` is the new, separately-surfaced timestamp
        for the Sector Heatmap panel, since the two can now honestly
        be different ages.
        """
        stock = self._build_stock_gainers_losers()
        sector = self._build_sector_gainers_losers()
        return {
            "gainers": stock["gainers"],
            "losers": stock["losers"],
            # Which session these prices are from. See
            # _build_stock_gainers_losers().
            "at_close": stock.get("at_close", False),
            "as_of": stock.get("as_of"),
            # Built in _build_stock_gainers_losers() and passed through
            # here, because this is the dict the page actually reads.
            # Computing a thing and not wiring it to the screen is this
            # project's oldest and most expensive habit.
            "reversals": stock.get("reversals") or {"up": [], "down": []},
            "built_at": stock["built_at"],
            "sector_gainers": sector["sector_gainers"],
            "sector_losers": sector["sector_losers"],
            "sector_built_at": sector["built_at"],
        }

    def _build_actions(self):
        """The action log, SERVER-side (2026-07-28).

        It lived in the browser first, and a page refresh wiped it. The
        operator runs two or three screens, so a record only the
        clicking screen can see is not a record -- he could click on one
        monitor, watch another, and never learn the click died.

        Held on the TradeController so it survives a refresh, appears on
        every screen at once, and outlives a browser crash.
        """
        controller = getattr(self.engine, "trade_controller", None)
        if controller is None or not hasattr(controller, "actions"):
            return {"rows": [], "available": False}
        try:
            rows = controller.actions()
        except Exception:                                  # noqa: BLE001
            return {"rows": [], "available": False}
        return {
            "rows": rows,
            "failures": sum(1 for r in rows if not r.get("ok")),
            "available": True,
        }

    def _build_breakouts(self):
        """Fresh Breakouts panel (2026-07-28).

        Every structural signal the engine produced today, newest first,
        INCLUDING the ones it refused. On 2026-07-28 the engine fired
        breakouts on TVSMOTOR, NTPCGREEN, KTKBANK and dozens more, the
        SHORT_ONLY regime refused all of them silently, and no panel
        existed to show either fact. The operator watched TVS run with
        no idea his own bot had already spotted it.

        Fail-open: no feed wired (tests, dashboard_preview) returns an
        empty panel, never an error.
        """
        feed = getattr(self.engine, "breakout_feed", None)
        if feed is None:
            return {"rows": [], "count": 0, "available": False}
        try:
            rows = feed.snapshot(limit=BREAKOUT_PANEL_COUNT)
        except Exception:                                  # noqa: BLE001
            return {"rows": [], "count": 0, "available": False}
        return {
            "rows": rows,
            "count": len(rows),
            "active": sum(1 for r in rows if r.get("status") == "ACTIVE"),
            "available": True,
        }

    def _build_shortlist(self):
        """The reason-ranked shortlist. Throttled to its own cadence and
        wrapped so a failure here can never take the dashboard down --
        a screener going quiet must degrade to an empty panel, never to
        a dead page while the operator has money on the screen."""
        now = time.monotonic()
        if self._shortlist_cache is not None and \
                now - self._shortlist_built_at < SHORTLIST_REFRESH_SECONDS:
            return self._shortlist_cache
        try:
            result = self._shortlist.rank(
                self._compute_gl_rows(), top=SHORTLIST_COUNT)
        except Exception as e:
            warn(f"[SHORTLIST] Build failed, panel will show empty: {e}")
            result = {"rows": [], "thin": [], "scanned": 0,
                      "built_at": datetime.now().strftime("%H:%M:%S")}
        self._shortlist_cache = result
        self._shortlist_built_at = now
        return result

    def build_movers(self):
        """Top 50 gainers and top 50 losers, each carrying every reason
        the bot has for them.

            "Shortlist what moved, and why -- ranked from here we will do
             as per my order (top 50 stocks on each side) ... everything
             will be integrated into this one table neatly"
                                        -- operator, 30 July 2026

        Before this there were TWO panels showing overlapping truths: a
        25-row scored shortlist, and a 50-a-side gainers/losers table
        with no reasons on it at all. The same stock appeared in both,
        described differently, and neither was complete -- the shortlist
        dropped anything scoring under MIN_SCORE, so a stock up 14% with
        no filing behind it simply vanished from the reasoned view.

        This is a LEFT JOIN, and the direction matters: the 50 movers are
        the spine, and the shortlist's score, grade, veto and why-chips
        are attached where they exist. A mover with nothing behind it
        still appears, with an em dash, because "up 9% and we know
        nothing about why" is itself information -- and the operator's
        own rule for absent data is "if no data available simply --".

        The ORB attempt count rides along too: how many separate times
        the stock has tried its opening range today. Displayed, never
        scored -- see core/breakout_feed.attempt_for().
        """
        try:
            shortlist = self._build_shortlist() or {}
        except Exception as exc:                           # noqa: BLE001
            warn(f"[MOVERS] Shortlist unavailable: {exc}")
            shortlist = {}
        reasons = {r.get("symbol"): r for r in (shortlist.get("rows") or [])}

        try:
            rows = self._compute_gl_rows()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[MOVERS] Panel build failed: {exc}")
            return {"gainers": [], "losers": [], "scanned": 0,
                    "built_at": datetime.now().strftime("%H:%M:%S")}

        feed = getattr(self.engine, "breakout_feed", None)

        def attempts(symbol, direction):
            if feed is None:
                return None
            try:
                return feed.attempt_for(symbol, direction)
            except Exception:                              # noqa: BLE001
                return None

        def decorate(row, direction, rank):
            hit = reasons.get(row.get("symbol")) or {}
            out = dict(row)
            out["s_no"] = rank
            out["score"] = hit.get("score")
            out["why"] = hit.get("why") or []
            # 31 July 2026. APTUS showed "0 backing" beside a score of
            # 13 and three positive chips. The count was never copied
            # here, so the badge read 0 on every row in this table --
            # and a number that is always wrong is worse than no number,
            # because it teaches the operator to distrust the ones that
            # are right.
            out["support"] = hit.get("support")
            out["against"] = hit.get("against")
            # ---- THE SAME BUG, A SECOND TIME, 2 August 2026 ----
            #
            # The chain summary was built in core/shortlist.py, tested,
            # stored on the row -- and never appeared on screen. This
            # function copies fields ONE BY ONE, so a new key on the
            # shortlist row is invisible here until it is named.
            #
            # Exactly what happened to `support` on 31 July, four
            # comment-lines above. A hand-written copy list is a place
            # where new work goes to be silently dropped, and it has
            # now cost two features.
            out["chain"] = hit.get("chain")
            out["chain_state"] = hit.get("chain_state")
            out["chain_why"] = hit.get("chain_why")
            out["chain_rank"] = hit.get("chain_rank")
            out["chain_layers"] = hit.get("chain_layers")
            # ---- AND A THIRD TIME IF THIS IS FORGOTTEN ----
            # The chip beside the symbol is now the CHANNEL's verdict,
            # not our arithmetic. Both travel; only the first is drawn.
            # tests/test_trusted_chips.py reads shortlist.py for every
            # field the row emits and fails if this list misses one.
            out["channel_grade"] = hit.get("channel_grade")
            out["channel_grade_from"] = hit.get("channel_grade_from")
            out["grade"] = hit.get("grade")
            out["veto"] = hit.get("veto") or []
            out["vol_ratio"] = hit.get("vol_ratio")
            out["news"] = hit.get("news")
            out["financials"] = hit.get("financials")
            # LONG attempts for a gainer, SHORT for a loser -- asking the
            # feed about the wrong side would report a level the stock is
            # not actually testing.
            out["attempts"] = attempts(row.get("symbol"), direction)
            out["direction"] = direction
            return out

        top = sorted(rows, key=lambda r: r.get("change_pct") or 0, reverse=True)
        bottom = sorted(rows, key=lambda r: r.get("change_pct") or 0)
        gainers = [decorate(r, "LONG", i)
                   for i, r in enumerate(top[:GAINERS_LOSERS_COUNT], start=1)]
        losers = [decorate(r, "SHORT", i)
                  for i, r in enumerate(bottom[:GAINERS_LOSERS_COUNT], start=1)]

        return {
            "gainers": gainers,
            "losers": losers,
            "scanned": len(rows),
            "with_reasons": len(reasons),
            "thin": (shortlist.get("thin") or [])[:10],
            "built_at": shortlist.get("built_at")
                        or datetime.now().strftime("%H:%M:%S"),
        }

    def _build_announcements(self):
        """Today's filings as they land. No throttle -- the watcher keeps
        its own list in memory and this is a dict copy, so reading it on
        every refresh costs nothing and the panel stays current.

        `available: False` is deliberately different from an empty list.
        "Nothing filed yet" and "we cannot see the news" must never look
        the same to someone deciding whether to buy."""
        if self.announcement_watcher is None:
            return {"available": False, "rows": [], "count_today": 0,
                    "note": "watcher not running"}
        try:
            snap = self.announcement_watcher.snapshot(
                limit=ANNOUNCEMENT_PANEL_COUNT)
            snap["available"] = True
            return snap
        except Exception as e:
            warn(f"[NEWS] Panel build failed: {e}")
            return {"available": False, "rows": [], "count_today": 0,
                    "note": f"error: {e}"}

    def _build_news(self):
        """High-conviction news. Same shape as the announcements panel so
        the frontend treats them alike. `available: False` is deliberately
        different from an empty list -- "no big news today" and "the feed
        is down" must never look the same."""
        if self.news_watcher is None:
            return {"available": False, "rows": [], "count_today": 0,
                    "note": "news watcher not running"}
        try:
            return self.news_watcher.snapshot(limit=ANNOUNCEMENT_PANEL_COUNT)
        except Exception as e:
            warn(f"[NEWSFEED] Panel build failed: {e}")
            return {"available": False, "rows": [], "count_today": 0,
                    "note": f"error: {e}"}

    def _build_news_table(self):
        """The pre-market news panel, grouped by stock.

            "News collected - now it is a hell of mess with repeated
             items without clarity ... i need a clean table with
             Symbol  News (here details)  Time"
                                    -- operator, 1 August 2026

        Both sources feed one table. Failure of either is reported,
        never faked: an empty table and a dead feed must not look the
        same, which is the same rule _build_news() follows.
        """
        from core.news_table import build

        rss, telegram, notes = [], [], []
        if self.news_watcher is not None:
            try:
                snap = self.news_watcher.snapshot(limit=200)
                rss = snap.get("rows") or []
            except Exception as exc:                       # noqa: BLE001
                notes.append(f"news watcher: {exc}")
        else:
            notes.append("news watcher not running")

        if self.telegram is not None:
            try:
                telegram = self.telegram.recent(limit=300) or []
            except Exception as exc:                       # noqa: BLE001
                notes.append(f"telegram: {exc}")
        else:
            notes.append("telegram not set up")

        try:
            out = build(rss_rows=rss, telegram_rows=telegram)
        except Exception as exc:                           # noqa: BLE001
            warn(f"[NEWS TABLE] Panel build failed: {exc}")
            return {"available": False, "stocks": [], "market": [],
                    "note": f"error: {exc}"}

        out["available"] = bool(rss or telegram)
        out["note"] = "; ".join(notes)
        out["read"] = len(rss) + len(telegram)
        return out

    def _build_open_positions(self, open_positions):
        rows = []
        for symbol, position in open_positions.items():
            last_price = (
                self.market_data.get_latest_price(symbol)
                or position["entry_price"]
            )
            direction = position.get("direction", "LONG")
            pnl = _signed_pnl(direction, position["entry_price"], last_price, position["qty"])
            record = self.master_loader.get_by_symbol(symbol)
            initial_stop = position.get("initial_stop")
            fixed_target = position.get("fixed_target")

            # Three possible stop sources, mirroring core/engine.py's
            # own _check_trailing_stop() routing:
            #   - Old fixed-bracket trades (fixed_target set, only
            #     possible on a position restored from before the
            #     2026-07-24 ATR redesign) were never handed to
            #     trailing_stop.start() -- their stop IS initial_stop,
            #     unchanging by design.
            #   - ATR trailing (TOP_N_MOMENTUM_MODE, 2026-07-24
            #     onward) manages its own live stop directly on the
            #     position dict ("atr_stop"), never registered with
            #     the swing engine either.
            #   - Everything else (manual buy/short, non-momentum
            #     structural) reads the live ratcheted value from the
            #     swing-based trailing_stop engine, as before.
            if fixed_target is not None:
                stop_value = initial_stop
            elif position.get("stop_mode") == "ATR_TRAILING":
                stop_value = position.get("atr_stop")
            else:
                stop_value = self.engine.trailing_stop.get_stop(symbol)

            rows.append({
                "symbol": symbol,
                "direction": direction,
                "entry_time": _fmt_time(position.get("entry_time")),
                "entry_price": position["entry_price"],
                "sector": record.get("SECTOR") if record else None,
                "qty": position["qty"],
                "last_price": last_price,
                "pnl": round(pnl, 2),
                "stop": stop_value,
                "initial_stop": initial_stop,
                "fixed_target": fixed_target,
                "rr": _rr(direction, position["entry_price"], last_price, initial_stop),
                "entry_reason": position.get("entry_reason"),
                # The operator's own column names, 30 July. CMP and MTM
                # are what he says out loud; last_price and pnl are what
                # the old dashboard reads. Both are sent -- renaming
                # would silently blank index.html, and the page reading
                # a name the server never sends is exactly how the MTM
                # column came to be empty in the first place (v2 read
                # `live_pnl`, state sent `pnl`, and nothing errored).
                "cmp": last_price,
                "mtm": round(pnl, 2),
                "live_pnl": round(pnl, 2),
            })
            rows[-1].update(self._circuit_room(symbol, last_price))

        rows.sort(key=lambda r: r["entry_time"] or "")
        for index, row in enumerate(rows, start=1):
            row["s_no"] = index
        return rows

    def _circuit_room(self, symbol, last_price):
        """How much room a stock has left before it locks.

            "gap i observed is we dont know the UC & LC of any stock in
             dashboard at all"        -- operator, 29 July 2026

        He bought SMLMAH at its upper circuit and there was nowhere on
        screen showing he was at the band. circuit_monitor has polled
        these every three seconds all along.

        For a holding this is the number that matters most: a long
        sitting at the upper circuit cannot be sold into a bid that is
        not there. Reported as unknown, never as zero, when the bands
        have not been polled for that symbol yet.
        """
        out = {"upper_circuit": None, "lower_circuit": None,
               "pct_to_upper": None, "pct_to_lower": None, "at_circuit": None}
        try:
            quote = (self.engine.get_circuit_snapshot() or {}).get(symbol) or {}
        except Exception:                                  # noqa: BLE001
            return out
        upper = quote.get("upper_circuit_limit") or None
        lower = quote.get("lower_circuit_limit") or None
        out["upper_circuit"], out["lower_circuit"] = upper, lower
        if not last_price or last_price <= 0:
            return out
        if upper and upper > 0:
            out["pct_to_upper"] = round((upper - last_price) / last_price * 100, 2)
        if lower and lower > 0:
            out["pct_to_lower"] = round((last_price - lower) / last_price * 100, 2)
        for side, key in (("UPPER", "pct_to_upper"), ("LOWER", "pct_to_lower")):
            room = out[key]
            if room is not None and room <= CIRCUIT_PROXIMITY_PCT * 100:
                out["at_circuit"] = side
        return out

    def _widen_by_reason(self, movers):
        """Add every stock the bot has a REASON for today, whatever its
        rank in the gainers list.

        ==========================================================
            "why bot or trader needs to wait till Circuit closing
             even after knowing the results are excellent & volumes
             started buying stock moving"
                                -- operator, 4 August 2026
        ==========================================================

        The top 50 is a leaderboard of moves that have ALREADY
        happened. Results land at 09:41 and the stock is up 2.5% on
        rising volume -- 180th on the day, invisible, and by the time
        it reaches the leaderboard it is at its circuit with no sellers.

        This does not lower any bar. The stock still has to be moving,
        still has to beat its sector, still has to have volume, still
        has to be MTF-eligible. It just gets to be LOOKED AT while
        there is still room in the move.
        """
        seen = {str(r.get("symbol") or "").upper() for r in movers}
        named = []
        try:
            named = list(self._symbols_with_news_today())
        except Exception:                                  # noqa: BLE001
            return movers
        if not named:
            return movers

        wanted = {str(s).upper() for s in named} - seen
        if not wanted:
            return movers

        # Same rows the leaderboard is sliced from -- no new polling,
        # no second source that could disagree with the first.
        extra = [row for row in (self._compute_gl_rows() or [])
                 if str(row.get("symbol") or "").upper() in wanted]
        if extra:
            when_it_changes(
                "rank-added-by-reason",
                f"[RANK] {len(extra)} stock(s) added by reason "
                f"that the top-50 list would have hidden.")
        return list(movers) + [dict(r) for r in extra]

    def _symbols_with_news_today(self):
        """Every symbol something was filed or reported about today.

        ---- THE WATCHLIST WAS DRAWN AND READ BY NOTHING. 7 Aug 2026. ----

            "if bot doesn't know the best stocks then how it can trade?
             obivously it will go to next possible way"
                                            -- operator

        He is exactly right, and it is the same fault as core/ranker.py
        sitting unwired through 3,541 green tests. I built
        core/watchlist_builder.py, showed him the three rows working,
        put them on the screen -- and the ORDER PATH never read them.
        Verified before this fix:

            auto_watchlist referenced in main.py     0
            build_ranked mentions auto_watchlist     no
            auto_entry is fed from                   "ranked"

        So the ranker's pool was the top-50 gainers plus whatever
        announcements and news happened to name. A stock with an
        EXCELLENT result on the 09:08 gapper card had to fight its way
        into the top 50 before the bot would even look at it -- which
        is the "no use of such movement, it already ran" problem he
        raised on 4 August, in a different costume.

        The pool now also carries every symbol the watchlist found:
        the graded results, the ones reporting today, and the ones
        moving on real volume. Nothing here TAKES a trade -- every gate
        downstream still has to be cleared. It only gives those stocks
        the chance to be judged.
        """
        out = set()
        for holder in ("announcements", "news"):
            source = getattr(self.engine, holder, None)
            getter = getattr(source, "symbols_today", None)
            if getter:
                try:
                    out.update(getter() or [])
                except Exception:                          # noqa: BLE001
                    continue

        # The graded results and the day's real movers. Read from the
        # same builder the screen uses, so what he sees and what the
        # bot considers can never drift apart.
        try:
            from core import watchlist_builder
            cutoff_day = datetime.now().date().isoformat()
            out.update(watchlist_builder.graded_symbols() or {})
            out.update(watchlist_builder.reporting_on(cutoff_day) or {})
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[RANK] Could not widen by watchlist: {exc}")
        return out

    def _safe_watchlist(self):
        """The watchlist can cost itself. It cannot cost the session.

        4 August 2026: build_watchlist() raised AttributeError on a
        method I had invented, and it took the WHOLE snapshot with it
        -- dashboard_state.refresh() died, and main.py died with it on
        shutdown. Every other panel was fine.

        One panel must never be able to do that. Every sibling build_*
        already returns a dict on failure; this one went in without the
        same guard.
        """
        try:
            return self.build_watchlist()
        except Exception as exc:                           # noqa: BLE001
            warn(f"[WATCHLIST] Panel failed ({exc}). Everything else is "
                 f"unaffected.")
            return {"available": False, "during": [], "after": [],
                    "unknown": [], "mine": [], "note": str(exc)}

    def build_watchlist(self):
        """Results today, split by when -- plus whatever he added.

        ==========================================================
            "WATCHLIST = MAINTAIN ONLY STOCKS WHICH WILL GET RESULTS
             TODAY DURING LIVE MARKETS & GIVE ME OPTION TO ADD SOME
             STOCKS ... AFTER MARKET STOCK RESULTS + NEXT DAY DURING
             MARKET RESULTS STOCK ON NEXT DAY."
                                -- operator, 4 August 2026
        ==========================================================

        The old one put breakouts, news mentions, shortlist candidates
        and results in one list -- "bot clubbed all under same roof;
        why user needs to work hard". A list that has to be sorted
        before it can be read is not a watchlist.

        Three groups. Two of them manage themselves and one is his.
        Nothing about the results groups is persisted: they are
        recomputed from the calendar every session, so a stale name
        cannot survive into a day it does not belong to.
        """
        from core.watchlist_store import (AFTER, DURING, UNKNOWN,
                                          bucket_for)

        out = {"available": False, "during": [], "after": [],
               "unknown": [], "mine": []}

        if self._watchlist is None:
            try:
                from core.watchlist_store import WatchlistStore
                self._watchlist = WatchlistStore()
            except Exception as exc:                       # noqa: BLE001
                warn(f"[WATCHLIST] Store unavailable ({exc}).")
                return out

        prices = {}
        try:
            prices = self.market_data.latest_prices()
        except Exception:                                  # noqa: BLE001
            prices = {}

        def row(symbol, when="", why=""):
            record = self.master_loader.get_by_symbol(symbol) or {}
            # NaN, NOT None. An empty SECTOR cell in master_stocks.csv
            # comes back from pandas as float NaN, which is TRUTHY and
            # sails past every `or None` guard -- and one of them
            # refuses the WHOLE payload, not just this field. It 500'd
            # /api/snapshot mid-session on 5 August. The file's own
            # docstring warns about this trap and I walked into it.
            sector = record.get("SECTOR")
            if sector is None or sector != sector:          # NaN
                sector = None
            return {"symbol": symbol,
                    "when": when,
                    "why": why,
                    "sector": sector,
                    "ltp": prices.get(symbol),
                    "change_pct": self._change_pct_for(symbol)}

        # ---- THE RESULTS HALF ----
        today = datetime.now().strftime("%Y-%m-%d")
        # ---- Engine HAS NO results_calendar. 24 August 2026. ----
        #
        #     "its printing same thing multiple times"
        #                                    -- operator, 24 Aug 2026
        #
        # 487 identical AttributeErrors in the 37-minute pre-open of
        # 24 August, one per cycle. The attribute has never existed on
        # Engine, so the RESULTS HALF of this watchlist has never once
        # populated -- the message was filed as a diagnostic and read
        # as "no results today", which during results season it was
        # not. core/results_calendar.py owns the store; it is opened
        # here directly and cached, exactly as the other stores are.
        #
        # Reported once per process, not once per cycle: a condition
        # that cannot change between ticks does not need re-announcing
        # every 2.6 seconds.
        due = []
        try:
            if self._results_calendar is None:
                from core.results_calendar import ResultsCalendar
                self._results_calendar = ResultsCalendar()
            due = self._results_calendar.symbols_on(today) or []
        except Exception as exc:                           # noqa: BLE001
            if not self._results_calendar_warned:
                self._results_calendar_warned = True
                diagnostic(f"[WATCHLIST] No results calendar ({exc}). "
                           f"Said once; not repeated each cycle.")
            due = []

        for symbol in sorted({str(s).upper() for s in due}):
            timing = {}
            try:
                timing = calendar.typical_time(symbol) or {}
            except Exception:                              # noqa: BLE001
                timing = {}
            group = bucket_for(timing)
            when = timing.get("hhmm") or ""
            # SAY WHY THE TIME IS NOT TRUSTED. TITAN reports anywhere
            # across a 4.5-hour window; "17:07" alone would read as a
            # fact. The spread is the honest version.
            if group == UNKNOWN and when:
                when = f"~{when}?"
            why = self._reason_text(symbol) or "results due"
            out[{DURING: "during", AFTER: "after",
                 UNKNOWN: "unknown"}[group]].append(row(symbol, when, why))

        # ---- HIS HALF. Never touched by the above. ----
        for symbol in self._watchlist.symbols():
            note = self._watchlist.note_for(symbol)
            out["mine"].append(
                row(symbol, "",
                    note or self._reason_text(symbol) or "no news today"))

        out["available"] = True
        out["counts"] = {key: len(out[key])
                         for key in ("during", "after", "unknown", "mine")}
        return out

    def watchlist_store(self):
        """The store, built on first use. The server needs the same one
        the panel reads, or an add would not show until a restart."""
        if self._watchlist is None:
            from core.watchlist_store import WatchlistStore
            self._watchlist = WatchlistStore()
        return self._watchlist

    def _reason_text(self, symbol):
        """The written reason this stock is moving, in one line.

        ---- I INVENTED self._plain_headline(). 4 August 2026. ----
        It crashed main.py on shutdown:

            AttributeError: 'DashboardState' object has no attribute
            '_plain_headline'

        _plain_headline IS in this file -- as a module-level function
        taking TEXT. I called it as a method taking a SYMBOL. Wrong on
        both counts, and the fourth invented name in two days:
        known_symbols(), InstrumentMaster.rows(), release_all(), this.

        The real per-symbol reader is _mechanism_for(), which the
        ranker already uses. Wrapped here so the watchlist reads the
        SAME reason WHAT TO TRADE NOW does -- two panels disagreeing
        about why a stock is moving would be worse than either being
        silent.
        """
        try:
            mech = self._mechanism_for(symbol) or {}
        except Exception:                                  # noqa: BLE001
            return ""
        return str(mech.get("text") or "").strip()

    def _change_pct_for(self, symbol):
        """Today's move for a watchlist row, from the same gainers /
        losers rows the rest of the page reads. None when the stock has
        not been seen -- never zero, which would read as 'flat'."""
        try:
            rows = self._compute_gl_rows() or []
        except Exception:                                  # noqa: BLE001
            return None
        for row in rows:
            if str(row.get("symbol") or "").upper() == symbol:
                return row.get("change_pct")
        return None

    def _safe_routing(self):
        """What take() decided about each ranked pick. Never raises."""
        try:
            return list(getattr(self.engine, "routing_decisions", None)
                        or [])
        except Exception:                                  # noqa: BLE001
            return []

    def _safe_broker_funds(self):
        """What Dhan last said, and when. Never raises, never calls out.

        core/broker_funds.py does the asking -- on startup and on the
        heartbeat. This only reports the answer it already has, so
        building a snapshot can never block on the network.
        """
        try:
            from core import broker_funds
            return broker_funds.last_read()
        except Exception:                                  # noqa: BLE001
            return {"balance": None, "at": None, "source": None}

    def _evidence_for(self, symbol):
        """A one-line reason this stock has news behind it, or None.

        ---- THE 09:15 LANE ONLY OPENED FOR RESULTS. 18 Aug 2026. ----

            "by knowing the underlying news = buy right? if we wait
             for 09:30 to orb confirmation we may miss or never able
             to enter into trade after a long run up"

        core/engine.py._capture_reason() is the ONE place that knows
        what is behind a stock this morning -- the news feed, the
        announcements feed and the results grade. This hands that same
        answer to core/auto_entry.early_rows(), which until today
        could only see overnight results grades.

        Injected rather than imported so auto_entry keeps no engine
        reference, matching how mtf_of, plan_of and adv_of are already
        passed into that module.

        Never raises: an early lane that throws is an early lane that
        silently becomes the old one.
        """
        try:
            capture = getattr(self.engine, "_capture_reason", None)
            if capture is None:
                return None
            got = capture(symbol) or {}
        except Exception:                                  # noqa: BLE001
            return None
        if not got.get("had_reason"):
            return None
        return str(got.get("reason_summary") or "").strip() or None

    def _mtf_for(self, symbol, row=None):
        """Can he buy this ON MTF, and at what leverage?

        ==========================================================
            "only trade in best set of stocks in MTF"
                                -- operator, 4 August 2026
        ==========================================================

        core/mtf_margin.py has asked Dhan this question all along, for
        SIZING. The ranker never asked it at all, so it could put a
        stock in WHAT TO TRADE NOW that he could only buy with cash --
        and he would find out at the click.

        Returns None when the question cannot be asked (paper mode, no
        margin book, no security id). None means "not asked", and the
        ranker treats that as no objection. An unasked question read as
        a failed one would empty the table every time the broker is
        absent, which is the worse failure by far.
        """
        # engine.mtf_margin -- singular. I wrote "mtf_margins" first and
        # it would have returned None for every symbol, silently, so the
        # gate would have looked wired and checked nothing.
        book = getattr(self.engine, "mtf_margin", None)
        if book is None or not hasattr(book, "leverage_for"):
            return None
        record = self.master_loader.get_by_symbol(symbol) or {}
        security_id = record.get("SECURITY ID") or record.get("security_id")
        price = (row or {}).get("ltp")
        if not security_id or not price:
            return None
        try:
            return book.leverage_for(symbol, security_id, price)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[MTF] {symbol}: could not check eligibility ({exc}).")
            return None

    def _closed_from_dhan(self):
        """Dhan's own squared-off rows for the day.

        ==========================================================
            "post tab will be my closing positions . and pnl"
            "yes book needs to carry both right?"
                                    -- operator, 4 August 2026
        ==========================================================

        On 4 August he made about Rs 10,000 trading from the Dhan
        platform, the bot placed nothing, and the POST tab said "no
        closed trades today". It was reading the BOT's book on a day
        the bot did not trade.

        Same reader the open book already uses -- no extra REST call
        is made for this; positions() is one request that carries both
        the open rows and the CLOSED ones.

        Returns [] on any failure, never raises. A tab that cannot draw
        must not be able to stop the snapshot.
        """
        try:
            executor = getattr(self.engine, "execution", None)
            executor = getattr(executor, "executor", executor)
            reader = getattr(executor, "positions", None)
            broker = reader() if reader else None
        except Exception as exc:                           # noqa: BLE001
            warn(f"[POST] Could not read closed positions from Dhan: {exc}")
            return []
        if not isinstance(broker, list):
            return []
        return closed_book.from_dhan(broker)

    def _build_closed_positions(self, closed_positions):
        # BOTH BOOKS. The bot's own exits carry the reason it exited,
        # which Dhan cannot know; Dhan's rows carry the trades the bot
        # never saw, which is all of them on a day he trades by hand.
        # The mode decides whether a Dhan row for the same symbol is the
        # SAME trade or a DIFFERENT one. In paper the bot's orders never
        # reach Dhan, so it is always a different one -- his. Read at
        # call time, because he flips the switch mid-session.
        _mode = None
        try:
            _execution = getattr(self.engine, "execution", None)
            _mode = "LIVE" if getattr(_execution, "live", False) else "PAPER"
        except Exception:                                  # noqa: BLE001
            _mode = "PAPER"
        closed_positions = closed_book.merge(
            list(closed_positions or []), self._closed_from_dhan(),
            mode=_mode)
        rows = []
        for record in closed_positions:
            sector_record = self.master_loader.get_by_symbol(record["symbol"])
            direction = record.get("direction", "LONG")
            # A Dhan row can arrive with a price missing -- buyAvg is
            # 0.0 or absent on rows the broker has not finished pricing.
            # round_trip_charges() would multiply None and take the
            # whole snapshot down with it, so the trade is shown with
            # no charge estimate rather than not shown at all. Losing a
            # trade off his book is the worse failure.
            entry_price = record.get("entry_price")
            exit_price = record.get("exit_price")
            priced = (entry_price is not None and exit_price is not None
                      and record.get("qty"))
            pnl = record.get("pnl")
            if pnl is None and priced:
                pnl = _signed_pnl(direction, entry_price, exit_price,
                                  record["qty"])
            initial_stop = record.get("initial_stop")

            # nights_held decides intraday vs delivery/MTF costs
            # (2026-07-28). A same-session round trip pays neither
            # interest nor the higher delivery STT -- the operator's own
            # correction, and MTF interest genuinely starts at T+1.
            charges = round_trip_charges(
                entry_price, exit_price, record["qty"], direction,
                nights_held=nights_between(record.get("entry_time"),
                                           record.get("exit_time")),
            ) if priced else None
            rows.append({
                "symbol": record["symbol"],
                "direction": direction,
                # QTY. Every closed row was missing it -- not blank, not
                # zero: the key was never in the dict at all, so the
                # column had nothing to read and had been showing empty
                # since the day it was added. The operator reported it
                # twice ("blank QTY") and both times it was looked for
                # in the frontend, which was fine. It is used to compute
                # pnl and charges eight lines below, so the number was
                # right there the whole time.
                "qty": record.get("qty"),
                "entry_time": _fmt_time(record.get("entry_time")),
                "entry_price": entry_price,
                "sector": sector_record.get("SECTOR") if sector_record else None,
                "exit_price": exit_price,
                "exit_time": _fmt_time(record.get("exit_time")),
                "entry_reason": record.get("entry_reason"),
                "exit_reason": record.get("exit_reason"),
                "holding_seconds": record.get("holding_seconds"),
                "initial_stop": initial_stop,
                "fixed_target": record.get("fixed_target"),
                "rr": _rr(direction, entry_price, exit_price, initial_stop),
                "pnl": round(pnl, 2) if pnl is not None else None,
                # Transaction cost estimate + real net-of-cost P&L
                # (2026-07-24) -- see trading/charges.py. None on a
                # broker row we could not price -- shown as blank, never
                # as zero, because a zero charge is a claim.
                "charges": round(charges, 2) if charges is not None else None,
                "net_pnl": (round(pnl - charges, 2)
                            if (pnl is not None and charges is not None)
                            else None),
                # WHOSE TRADE WAS THIS. He asked the book to carry both.
                "origin": record.get("origin", "BOT"),
                "product": record.get("product"),
            })
            rows[-1].update(self._after_exit(record))
            # HOLDING (MINS) -- stored in seconds, read in minutes.
            held = record.get("holding_seconds")
            rows[-1]["holding_mins"] = (round(held / 60.0, 1)
                                        if held is not None else None)
            # CHANGE AFTER EXIT (Rs) -- what the move since the exit
            # would have been worth on the SAME quantity. The rupee
            # figure, not the percentage: 12.9% on PCBL means nothing
            # until it is Rs 11,000 on 259 shares.
            ltp = rows[-1].get("ltp")
            qty = record.get("qty")
            rows[-1]["change_after_exit_rs"] = (
                round(_signed_pnl(direction, exit_price, ltp, qty), 2)
                if (ltp and qty and exit_price is not None) else None)

        rows.sort(key=lambda r: r["exit_time"] or "", reverse=True)
        for index, row in enumerate(rows, start=1):
            row["s_no"] = index
        return rows

    def _after_exit(self, record):
        """Where the stock went after we sold it.

            "ltp is not place in closed positions so can't identify
             the move after exit in stocks - this requested by me as
             wanted but not done"      -- operator, 29 July 2026

        Asked for twice. On 29 July the bot trailed out of KAYNES at
        3,398 and it ran to 3,684.70 -- an 8.4% move the operator
        found on his broker screen, because nothing here showed it.

        Reported, never judged. There is no "should have held" flag
        and no missed-profit total: a number the bot could not have
        known at the time does not belong in a scorecard. It shows
        where the price went. What that means is the operator's call.
        """
        symbol = record["symbol"]
        exit_price = record.get("exit_price")
        direction = record.get("direction", "LONG")
        out = {"ltp": None, "since_exit_pct": None,
               "peak_since_exit": None, "peak_pct": None, "peak_at": None}
        if not exit_price:
            return out

        watch = None
        if hasattr(self.engine, "get_post_exit"):
            watch = self.engine.get_post_exit(symbol)

        last = self.market_data.get_latest_price(symbol)
        if last is None and watch:
            last = watch.get("last")
        if last is None:
            quote = (self.engine.get_circuit_snapshot() or {}).get(symbol)
            last = quote.get("last_price") if quote else None
        if last is None:
            return out

        out["ltp"] = last
        out["since_exit_pct"] = round((last - exit_price) / exit_price * 100, 2)

        # For a LONG the interesting extreme is the HIGH we missed; for
        # a SHORT it is the LOW. Reporting the high on a short would
        # read as "it went against you" when it did the opposite.
        if watch:
            extreme = watch.get("peak") if direction == "LONG" \
                else watch.get("trough")
            if extreme:
                out["peak_since_exit"] = extreme
                out["peak_pct"] = round(
                    (extreme - exit_price) / exit_price * 100, 2)
                peak_at = watch.get("peak_at")
                out["peak_at"] = _fmt_time(peak_at) if direction == "LONG" \
                    else None
        return out

    def _build_risk_filters(self, entry_blocked):
        """Surfaces exactly why a stock did or didn't trade today --
        panic-flagged sectors (core/sector_monitor.py), the
        news-contradiction / sector-panic block ledger
        (core/engine.py's entry_blocked), frozen-feed symbols
        (core/engine.py's get_frozen_symbols() -- see
        FROZEN_PRICE_STREAK_CANDLES's config.py docstring, added
        2026-07-23 after HFCL's feed froze for ~4 hours live), and
        circuit-proximity symbols (core/engine.py's
        get_circuit_flagged_symbols() -- see
        CIRCUIT_PROXIMITY_PCT's config.py docstring, the PROACTIVE
        follow-up added the same evening: close ahead of a circuit
        lock, not just detect it after the fact)."""
        blocked = []
        for symbol, directions in entry_blocked.items():
            for direction, reason in directions.items():
                blocked.append({
                    "symbol": symbol,
                    "direction": direction,
                    "reason": reason,
                })
        blocked.sort(key=lambda r: (r["symbol"], r["direction"]))

        # ---- 45 ROWS SAYING ONE THING, 2 August 2026 ----
        #
        # On the live panel this list ran to about forty-five rows,
        # every one of them reading
        #
        #     AADHARHFC   LONG   reports today, numbers not out yet
        #     AAVAS       LONG   reports today, numbers not out yet
        #     ...
        #
        # It occupied more of the page than gainers and losers put
        # together and carried one fact: results are due and the bot
        # will not act before they land. That is a COUNT, not a list.
        #
        # Grouped by reason, so the screen says "45 stocks: reports
        # today, numbers not out yet" and the names are one click
        # away. Nothing is dropped -- `blocked` is returned in full
        # beside it, because a stock the bot refused is exactly what
        # tools/refused_review.py exists to interrogate.
        by_reason = {}
        for row in blocked:
            key = str(row.get("reason") or "no reason recorded")
            by_reason.setdefault(key, []).append(row["symbol"])
        grouped = sorted(
            ({"reason": reason, "count": len(names),
              "symbols": sorted(set(names))}
             for reason, names in by_reason.items()),
            key=lambda r: -r["count"])

        panic_sectors = []
        if self.sector_monitor is not None:
            panic_sectors = sorted(self.sector_monitor.panicking_sectors())

        frozen_symbols = self.engine.get_frozen_symbols()
        circuit_flagged_symbols = self.engine.get_circuit_flagged_symbols()

        return {
            "panic_sectors": panic_sectors,
            # The full list stays. tools/refused_review.py and the
            # POST-MARKET tab both read it, and "which stocks did the
            # bot refuse today" is a question worth being able to ask.
            "blocked_symbols": blocked,
            # What the LIVE tab shows: one line per reason with a count.
            "blocked_by_reason": grouped,
            "blocked_count": len(blocked),
            "frozen_symbols": frozen_symbols,
            "circuit_flagged_symbols": circuit_flagged_symbols,
        }

    def _build_performance(self, closed_positions):
        """
        Real trade statistics from engine.closed_positions -- the
        in-session record of every CLOSED trade. Deliberately
        excludes open positions' unrealized P&L from max_drawdown:
        including it would make the number swing on every tick
        instead of only when a trade actually closes, which is
        what "drawdown" should mean for a stats panel, not a
        live mark-to-market figure (that's already on the Open
        Positions panel separately, per-position).
        """
        closed = closed_positions
        total = len(closed)
        if total == 0:
            return {
                "total_trades": 0, "wins": 0, "losses": 0, "flat": 0,
                "win_rate_pct": None, "profit_factor": None,
                "avg_win": None, "avg_loss": None, "expectancy_per_trade": None,
                "gross_profit": 0.0, "gross_loss": 0.0,
                "max_drawdown": 0.0, "net_pnl": 0.0,
                "total_charges": 0.0, "net_pnl_after_charges": 0.0,
            }

        wins = losses = flat = 0
        gross_profit = gross_loss = 0.0
        running = peak = max_dd = 0.0
        total_charges = 0.0

        for record in closed:
            direction = record.get("direction", "LONG")
            pnl = record.get("pnl")
            if pnl is None:
                pnl = _signed_pnl(
                    direction, record["entry_price"], record["exit_price"],
                    record["qty"],
                )

            total_charges += round_trip_charges(
                record["entry_price"], record["exit_price"], record["qty"], direction,
                nights_held=nights_between(record.get("entry_time"),
                                           record.get("exit_time")),
            )

            if pnl > 0:
                wins += 1
                gross_profit += pnl
            elif pnl < 0:
                losses += 1
                gross_loss += abs(pnl)
            else:
                flat += 1

            running += pnl
            if running > peak:
                peak = running
            drawdown = peak - running
            if drawdown > max_dd:
                max_dd = drawdown

        net_after_charges = running - total_charges
        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "flat": flat,
            "win_rate_pct": round(wins / total * 100, 1),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
            "avg_win": round(gross_profit / wins, 2) if wins > 0 else None,
            "avg_loss": round(gross_loss / losses, 2) if losses > 0 else None,
            # Expectancy = average NET-of-cost P&L per trade -- the
            # single number that says whether the edge is real
            # (2026-07-24, operator's win-rate-on-capital analysis).
            "expectancy_per_trade": round(net_after_charges / total, 2),
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "max_drawdown": round(max_dd, 2),
            "net_pnl": round(running, 2),                    # gross realized
            "total_charges": round(total_charges, 2),
            "net_pnl_after_charges": round(net_after_charges, 2),
        }

    def _build_market_intelligence(self, breadth, gainers_losers, performance):
        """
        2026-07-24 -- honest "Market Intelligence" panel from data the
        bot ACTUALLY has (breadth + sector aggregates + the day's
        realized P&L vs the guardrails). Index levels (Nifty/BankNifty/
        Midcap), India VIX, and FII/DII institutional flows are
        DELIBERATELY marked unavailable ("available": False) rather
        than faked -- they need a separate index/VIX feed subscription
        or an EOD institutional data source the bot doesn't have yet.
        """
        adv = breadth["advances"]
        dec = breadth["declines"]
        total = adv + dec
        breadth_pct = (adv / total * 100) if total else 50.0

        # Broad-market trend from breadth (whole traded universe) --
        # the honest stand-in for "Nifty trend" until a real index
        # feed is wired.
        if breadth_pct >= 60:
            market_trend, trend_cls = "Bullish", "bull"
        elif breadth_pct <= 40:
            market_trend, trend_cls = "Bearish", "bear"
        else:
            market_trend, trend_cls = "Neutral", "flat"

        # Trade-side bias (same >=60% rule the engine's regime gate
        # uses) -- what the bot itself is willing to trade right now.
        if breadth_pct <= 40:
            regime = "SHORT ONLY"
        elif breadth_pct >= 60:
            regime = "LONG ONLY"
        else:
            regime = "BOTH SIDES"

        # Banking trend proxy for BankNifty: the bank/financial
        # sector's own avg from the sector heatmap, if present.
        bank_trend = None
        for row in (gainers_losers.get("sector_gainers", []) +
                    gainers_losers.get("sector_losers", [])):
            name = _text(row.get("sector"))
            if "BANK" in name or "FINANC" in name:
                bank_trend = row["avg_change_pct"]
                break

        # Overall market score 0-100: breadth is the backbone.
        overall_score = round(breadth_pct)

        # Real index feed (Nifty/BankNifty/Midcap/VIX) if wired &
        # delivering -- else each stays unavailable ("needs feed").
        idx = self.indices()

        def _idx(name, note):
            d = idx.get(name)
            if d and d.get("available"):
                return {"available": True, "ltp": d["ltp"], "pct": d["pct"]}
            return {"available": False, "note": note}

        # BankNifty from the real index if we have it, else the sector-
        # average proxy computed above.
        banknifty = _idx("banknifty", "needs index feed")
        if not banknifty["available"] and bank_trend is not None:
            banknifty = {"available": True, "ltp": None, "pct": bank_trend, "proxy": True}

        return {
            "market_trend": market_trend,
            "market_trend_cls": trend_cls,
            "breadth_pct": round(breadth_pct, 1),
            "advances": adv,
            "declines": dec,
            "regime": regime,
            "bank_trend": bank_trend,
            "overall_score": overall_score,
            "realized_net_pnl": performance.get("net_pnl_after_charges", 0.0),
            "daily_goal_rs": DAILY_PROFIT_TARGET_RS,
            "daily_loss_rs": DAILY_MAX_LOSS_RS,
            # ---- WHICH SECTOR IS MOVING. 3 August 2026. ----
            #
            #   "4 th = SECTOR INDICES (sector based Indices as a
            #    dropdown option =this will be bird view from top
            #    section which index=sector is moving)"
            #
            # Every subscribed sector, biggest absolute move first, so
            # the tile can lead with the answer and keep the rest one
            # click away. Absolute, not signed: a sector down 3% is as
            # much of an answer as one up 3%, and on a red day the
            # signed sort would lead with the least interesting one.
            "sectors": self._build_sector_indices(idx),
            "nifty": _idx("nifty", "needs index feed"),
            "banknifty": banknifty,
            "midcap": _idx("midcap", "needs index feed"),
            "vix": _idx("vix", "needs India VIX feed"),
            # FII/DII, 2026-07-28. Was a config placeholder
            # (FII_NET_CR / DII_NET_CR) meant to be typed by hand and
            # never was, so the tile read "set in config" every session.
            # core/market_flows.py now fetches it from NSE. Always an
            # EOD figure -- NSE publishes after the close -- so it is
            # context, never a trigger, and carries its own date.
            "institutional": self._build_institutional(),
            # Configured indices that never delivered a tick, so a wrong
            # security id looks like a wrong id rather than a dead
            # market. config.INDEX_INSTRUMENTS said "VERIFY on the live
            # feed" in its own comment and nobody ever did.
            "index_missing": (self.index_monitor.missing()
                              if self.index_monitor is not None else []),
            # Configured ids that ARE delivering, but a level nowhere
            # near what that index really trades at -- i.e. the id points
            # at a different instrument. 2026-07-28: "nifty" showed
            # 7,330.5 and "banknifty" 3,038.
            "index_suspect": (self.index_monitor.suspect(INDEX_EXPECTED_RANGE)
                              if self.index_monitor is not None else []),
        }

    def _build_book_analytics(self, open_positions, closed_positions):
        """
        2026-07-24 -- replaces the redundant green/red "Sectors" panel
        (operator: it duplicated the Sector Heatmap). Shows what's
        UNIQUE to the operator's own book: open exposure by sector
        (concentration risk), today's net-of-cost P&L by sector (which
        sectors the strategy actually works in), and a long-vs-short
        scoreboard.
        """
        exposure = {}
        long_open = short_open = 0
        for symbol, pos in open_positions.items():
            rec = self.master_loader.get_by_symbol(symbol)
            sector = (rec.get("SECTOR") if rec else None) or "Unknown"
            direction = pos.get("direction", "LONG")
            e = exposure.setdefault(
                sector, {"sector": sector, "long": 0, "short": 0, "notional": 0.0}
            )
            e["notional"] += pos["entry_price"] * pos["qty"]
            if direction == "SHORT":
                e["short"] += 1
                short_open += 1
            else:
                e["long"] += 1
                long_open += 1
        exposure_rows = sorted(exposure.values(), key=lambda r: r["notional"], reverse=True)
        for r in exposure_rows:
            r["notional"] = round(r["notional"])

        sector_pnl = {}
        long_net = short_net = 0.0
        for rec in closed_positions:
            direction = rec.get("direction", "LONG")
            pnl = rec.get("pnl")
            if pnl is None:
                pnl = _signed_pnl(direction, rec["entry_price"], rec["exit_price"], rec["qty"])
            net = pnl - round_trip_charges(
                rec["entry_price"], rec["exit_price"], rec["qty"], direction,
                nights_held=nights_between(rec.get("entry_time"),
                                           rec.get("exit_time")),
            )
            srec = self.master_loader.get_by_symbol(rec["symbol"])
            sector = (srec.get("SECTOR") if srec else None) or "Unknown"
            sector_pnl[sector] = sector_pnl.get(sector, 0.0) + net
            if direction == "SHORT":
                short_net += net
            else:
                long_net += net
        sector_pnl_rows = sorted(
            [{"sector": s, "net_pnl": round(v)} for s, v in sector_pnl.items()],
            key=lambda r: r["net_pnl"], reverse=True,
        )

        return {
            "exposure": exposure_rows,
            "sector_pnl": sector_pnl_rows,
            "long_open": long_open,
            "short_open": short_open,
            "long_realized_net": round(long_net),
            "short_realized_net": round(short_net),
        }

    def _build_system_health(self, universe_size):
        """
        Real process/feed health, no fabricated numbers. CPU/RAM
        via psutil (optional dependency -- see requirements.txt;
        None, not a fake 0, if it's not installed). cpu_pct reads
        0.0 on this process's very first call (psutil needs a
        baseline) -- normal, not a bug, settles on subsequent
        refreshes. Tick count / staleness already tracked in
        core/market_data.py for the console heartbeat, reused here
        verbatim. feed_alive comes from main.py's get_feed_alive
        callable (the feed thread object itself lives in main.py's
        loop, not reachable from this read-only module otherwise);
        None if that wasn't wired in.
        """
        cpu_pct = ram_mb = None
        if psutil is not None:
            try:
                process = psutil.Process()
                cpu_pct = process.cpu_percent(interval=None)
                ram_mb = round(process.memory_info().rss / (1024 * 1024), 1)
            except Exception:
                pass

        feed_alive = self.get_feed_alive() if self.get_feed_alive is not None else None

        return {
            "cpu_pct": cpu_pct,
            "ram_mb": ram_mb,
            "tick_count": self.market_data.get_tick_count(),
            "stale_symbols_flagged": self.market_data.get_stale_warning_count(),
            "feed_alive": feed_alive,
            "universe_size": universe_size,
        }

    def _build_capital(self, open_positions):
        if self.portfolio is None:
            return None
        return self.portfolio.snapshot(
            open_positions, self.market_data.get_latest_price
        )
