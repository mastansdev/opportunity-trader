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

import threading
import time
from datetime import datetime

from config import (
    GAINERS_LOSERS_REFRESH_SECONDS, GAINERS_LOSERS_COUNT,
    SECTOR_GAINERS_LOSERS_MIN_SYMBOLS, SECTOR_GAINERS_LOSERS_REFRESH_SECONDS,
    SECTOR_HEATMAP_TOP_N, DAILY_PROFIT_TARGET_RS, DAILY_MAX_LOSS_RS,
    FII_NET_CR, DII_NET_CR,
    SANITY_BAND_MULTIPLE, CIRCUIT_LOCK_TOLERANCE_PCT,
    MARKET_BREADTH_REFRESH_SECONDS,
    SHORTLIST_REFRESH_SECONDS, SHORTLIST_COUNT,
)

from core.logger import warn
from core.shortlist import ShortlistBuilder
from trading.charges import round_trip_charges

try:
    import psutil
except ImportError:  # pragma: no cover -- optional, system health degrades gracefully
    psutil = None


def _fmt_time(value):
    if value is None:
        return None
    return value.strftime("%H:%M:%S")


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


class DashboardState:

    def __init__(self, engine, market_data, master_loader,
                 portfolio=None, sector_monitor=None, get_feed_alive=None,
                 index_monitor=None):
        self.engine = engine
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

        self._lock = threading.Lock()
        self._snapshot = {"ready": False}

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
        self._shortlist = ShortlistBuilder()
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

    def get_snapshot(self):
        with self._lock:
            return self._snapshot

    # --------------------------------------------------

    def _build(self):
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

        return {
            "ready": True,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "capital": self._build_capital(open_positions),
            "advances": breadth["advances"],
            "declines": breadth["declines"],
            "unchanged": breadth["unchanged"],
            "universe_size": breadth["universe_size"],
            "gainers_losers": gainers_losers,
            "shortlist": self._build_shortlist(),
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

    def _compute_gl_rows(self):
        """
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
        snapshot = self.engine.get_circuit_snapshot()

        rows = []
        for symbol, quote in snapshot.items():
            prev_close = quote.get("prev_close")
            last_price = quote.get("last_price")
            if not prev_close or last_price is None:
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
                continue

            # CEMPRO, locked at its 5% lower circuit -- zero real
            # order flow, excluded from the ranked table entirely
            # (still counts normally in breadth; being locked doesn't
            # change whether the move itself is real, only whether
            # it's currently tradeable, see _is_circuit_locked()'s
            # docstring).
            if _is_circuit_locked(
                last_price, quote.get("upper_circuit_limit"), quote.get("lower_circuit_limit"),
            ):
                continue

            record = self.master_loader.get_by_symbol(symbol)
            sector = record.get("SECTOR") if record else None

            rows.append({
                "symbol": symbol,
                "sector": sector,
                "open": quote.get("open"),
                "high": quote.get("high"),
                "low": quote.get("low"),
                "prev_close": prev_close,
                "ltp": last_price,
                "change": round(change, 2),
                "change_pct": round(change_pct, 2),
                "volume": quote.get("volume"),
            })
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

        result = {
            "gainers": gainers,
            "losers": losers,
            "built_at": datetime.now().strftime("%H:%M:%S"),
        }
        self._gainers_losers_cache = result
        self._gainers_losers_built_at = now
        return result

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
            sector = row["sector"]
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
            "built_at": stock["built_at"],
            "sector_gainers": sector["sector_gainers"],
            "sector_losers": sector["sector_losers"],
            "sector_built_at": sector["built_at"],
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
            })

        return sorted(rows, key=lambda r: r["entry_time"] or "")

    def _build_closed_positions(self, closed_positions):
        rows = []
        for record in closed_positions:
            sector_record = self.master_loader.get_by_symbol(record["symbol"])
            direction = record.get("direction", "LONG")
            pnl = record.get("pnl")
            if pnl is None:
                pnl = _signed_pnl(direction, record["entry_price"], record["exit_price"], record["qty"])
            initial_stop = record.get("initial_stop")

            charges = round_trip_charges(
                record["entry_price"], record["exit_price"], record["qty"], direction,
            )
            rows.append({
                "symbol": record["symbol"],
                "direction": direction,
                "entry_time": _fmt_time(record.get("entry_time")),
                "entry_price": record["entry_price"],
                "sector": sector_record.get("SECTOR") if sector_record else None,
                "exit_price": record["exit_price"],
                "exit_time": _fmt_time(record.get("exit_time")),
                "entry_reason": record.get("entry_reason"),
                "exit_reason": record.get("exit_reason"),
                "holding_seconds": record.get("holding_seconds"),
                "initial_stop": initial_stop,
                "fixed_target": record.get("fixed_target"),
                "rr": _rr(direction, record["entry_price"], record["exit_price"], initial_stop),
                "pnl": round(pnl, 2),
                # Transaction cost estimate + real net-of-cost P&L
                # (2026-07-24) -- see trading/charges.py.
                "charges": round(charges, 2),
                "net_pnl": round(pnl - charges, 2),
            })

        rows.sort(key=lambda r: r["exit_time"] or "", reverse=True)
        return rows

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

        panic_sectors = []
        if self.sector_monitor is not None:
            panic_sectors = sorted(self.sector_monitor.panicking_sectors())

        frozen_symbols = self.engine.get_frozen_symbols()
        circuit_flagged_symbols = self.engine.get_circuit_flagged_symbols()

        return {
            "panic_sectors": panic_sectors,
            "blocked_symbols": blocked,
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
            name = (row.get("sector") or "").upper()
            if "BANK" in name or "FINANC" in name:
                bank_trend = row["avg_change_pct"]
                break

        # Overall market score 0-100: breadth is the backbone.
        overall_score = round(breadth_pct)

        # Real index feed (Nifty/BankNifty/Midcap/VIX) if wired &
        # delivering -- else each stays unavailable ("needs feed").
        idx = self.index_monitor.snapshot() if self.index_monitor is not None else {}

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
            "nifty": _idx("nifty", "needs index feed"),
            "banknifty": banknifty,
            "midcap": _idx("midcap", "needs index feed"),
            "vix": _idx("vix", "needs India VIX feed"),
            # FII/DII: operator-set (EOD only, config.FII_NET_CR /
            # DII_NET_CR) -- honest manual value, never a fake intraday
            # scrape.
            "institutional": {
                "available": FII_NET_CR is not None or DII_NET_CR is not None,
                "fii_cr": FII_NET_CR,
                "dii_cr": DII_NET_CR,
                "note": "set FII_NET_CR / DII_NET_CR in config",
            },
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
