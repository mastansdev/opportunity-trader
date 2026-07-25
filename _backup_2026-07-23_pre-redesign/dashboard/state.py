"""
==========================================================
Dashboard State
==========================================================

Builds the single JSON-able snapshot the dashboard reads --
capital, advances/declines, sector colour, gainers/losers, open
and closed positions. Pure data assembly: engine, market_data,
master_loader, news_gate, portfolio are read-only inputs, this
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

A fixed Target is no longer universally "not applicable" --
TOP_N_MOMENTUM_MODE (config.py, 2026-07-24 experiment) gives
each fixed-bracket position a real fixed_target price
(core/engine.py's _fixed_bracket_prices()), surfaced per-
position in open/closed positions below. Positions opened
outside that mode still have no fixed target by design
(trailing-stop-only, see core/trailing_stop.py) -- the field is
simply None for those, never guessed. momentum_universe surfaces
today's locked top-25-gainers/top-25-losers shortlist
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
    TOP_N_MOMENTUM_MODE,
    GAINERS_LOSERS_REFRESH_SECONDS, GAINERS_LOSERS_COUNT,
    SECTOR_GAINERS_LOSERS_MIN_SYMBOLS,
)

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

    def __init__(self, engine, market_data, master_loader, news_gate=None,
                 portfolio=None, sector_monitor=None, get_feed_alive=None):
        self.engine = engine
        self.market_data = market_data
        self.master_loader = master_loader
        self.news_gate = news_gate
        self.portfolio = portfolio
        self.sector_monitor = sector_monitor
        # Optional zero-arg callable -> bool, wired from main.py
        # (feed_thread.is_alive() is a local loop variable there,
        # this is the one piece of system health this module can't
        # derive from its own read-only inputs). None if not wired
        # -- system health just omits the field rather than guess.
        self.get_feed_alive = get_feed_alive

        self._lock = threading.Lock()
        self._snapshot = {"ready": False}

        # Gainers/losers cache -- see _build_gainers_losers(). Kept
        # on the instance (not recomputed inside _build() every
        # refresh) specifically so it can be throttled to
        # GAINERS_LOSERS_REFRESH_SECONDS independent of this module's
        # own faster DASHBOARD_REFRESH_INTERVAL_SECONDS cycle.
        self._gainers_losers_cache = None
        self._gainers_losers_built_at = 0.0

    # --------------------------------------------------

    def refresh(self):
        """Rebuilds the snapshot, then swaps it in atomically --
        same pattern as NewsQueueReader.refresh()."""
        snapshot = self._build()
        with self._lock:
            self._snapshot = snapshot

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

        return {
            "ready": True,
            "updated_at": datetime.now().strftime("%H:%M:%S"),
            "capital": self._build_capital(open_positions),
            "advances": breadth["advances"],
            "declines": breadth["declines"],
            "unchanged": breadth["unchanged"],
            "universe_size": breadth["universe_size"],
            "sectors": self._build_sectors(breadth["per_symbol"]),
            "momentum_universe": self._build_momentum_universe(),
            "gainers_losers": self._build_gainers_losers(),
            "open_positions": self._build_open_positions(open_positions),
            "closed_positions": self._build_closed_positions(closed_positions),
            "risk_filters": self._build_risk_filters(entry_blocked),
            "performance": self._build_performance(closed_positions),
            "news_feed": self._build_news_feed(),
            "system_health": self._build_system_health(breadth["universe_size"]),
        }

    # --------------------------------------------------

    def _build_breadth(self):
        """See module docstring's "SWITCHED 2026-07-24" section --
        prev-close based, not day-open. prev_close comes from
        engine.get_circuit_snapshot() (circuit_monitor's REST poll,
        already running for circuit-proximity checking and Top 50
        Gainers/Losers); last_price prefers market_data's own tick
        feed, falling back to the snapshot's LTP for a symbol that
        hasn't ticked yet this session."""
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

        return {
            "advances": advances,
            "declines": declines,
            "unchanged": unchanged,
            "universe_size": len(symbols),
            "per_symbol": per_symbol,
        }

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

    def _build_momentum_universe(self):
        """
        TOP_N_MOMENTUM_MODE (config.py, 2026-07-24 experiment) --
        today's locked top-25-gainers (LONG-eligible) / top-25-
        losers (SHORT-eligible) shortlist, straight from
        core/momentum_universe.py's own export_state(). "enabled"
        reflects the config flag (so the dashboard can say "mode is
        off" distinctly from "mode is on but not locked yet");
        "locked" is False (with empty long/short lists) before
        ORB_WINDOW_END, exactly matching what the engine is actually
        gating entries on right now -- never a guessed or partial
        list.
        """
        if self.engine.momentum_universe is None:
            return {"enabled": False, "locked": False, "long": [], "short": []}

        state = self.engine.momentum_universe.export_state()
        return {
            "enabled": TOP_N_MOMENTUM_MODE,
            "locked": self.engine.momentum_universe.is_locked(),
            "long": state.get("long", []),
            "short": state.get("short", []),
        }

    def _build_gainers_losers(self):
        """
        Top GAINERS_LOSERS_COUNT gainers and losers across the bot's
        own master universe, ranked by %-change vs each symbol's
        PREVIOUS DAY close -- see module docstring's "REPLACED
        2026-07-23 evening" section for why this table exists and
        where its data comes from (engine.get_circuit_snapshot(),
        core/circuit_monitor.py's already-running REST poll, not a
        new data source).

        ALSO builds sector_gainers/sector_losers, added the same
        evening ("instead of deleting the sector heatmap, make it
        use like same top 50 gainers & losers... top gaining
        sectors / top loosing sectors"): each symbol's own row
        (already computed below for the stock-level table) is
        aggregated by SECTOR and averaged, same PREV-CLOSE basis --
        one pass over the snapshot feeds both tables, not two.
        Sectors with fewer than SECTOR_GAINERS_LOSERS_MIN_SYMBOLS
        reporting symbols are dropped as too sparse to mean
        anything, same "too few is noise" reasoning used everywhere
        else in this codebase (e.g. the old
        INDUSTRY_HEATMAP_MIN_SYMBOLS this replaces,
        core/sector_monitor.py's SECTOR_PANIC_MIN_SYMBOLS). No
        S.No cap on the sector lists -- there are only ~29 sectors
        total, nowhere near GAINERS_LOSERS_COUNT, so every
        qualifying sector shows.

        Both are throttled together to GAINERS_LOSERS_REFRESH_SECONDS:
        returns the cached result unless that much time has actually
        passed since the last rebuild, regardless of how often
        _build() itself runs (config.DASHBOARD_REFRESH_INTERVAL_SECONDS,
        much faster). time.monotonic() -- never wall clock -- same
        reasoning as every other cadence timer in this codebase
        (main.py's heartbeat/state-save loop): immune to a system
        clock adjustment.
        """
        now = time.monotonic()
        if self._gainers_losers_cache is not None and \
                now - self._gainers_losers_built_at < GAINERS_LOSERS_REFRESH_SECONDS:
            return self._gainers_losers_cache

        snapshot = self.engine.get_circuit_snapshot()

        rows = []
        for symbol, quote in snapshot.items():
            prev_close = quote.get("prev_close")
            last_price = quote.get("last_price")
            if not prev_close or last_price is None:
                continue

            record = self.master_loader.get_by_symbol(symbol)
            sector = record.get("SECTOR") if record else None
            change = last_price - prev_close
            change_pct = (change / prev_close) * 100

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
        sector_gainers = [dict(r) for r in
                           sorted(sector_rows, key=lambda r: r["avg_change_pct"], reverse=True)
                           if r["avg_change_pct"] >= 0]
        sector_losers = [dict(r) for r in
                          sorted(sector_rows, key=lambda r: r["avg_change_pct"])
                          if r["avg_change_pct"] < 0]
        for rank, row in enumerate(sector_gainers, start=1):
            row["s_no"] = rank
        for rank, row in enumerate(sector_losers, start=1):
            row["s_no"] = rank

        result = {
            "gainers": gainers,
            "losers": losers,
            "sector_gainers": sector_gainers,
            "sector_losers": sector_losers,
            "built_at": datetime.now().strftime("%H:%M:%S"),
        }
        self._gainers_losers_cache = result
        self._gainers_losers_built_at = now
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

            # Fixed-bracket trades (TOP_N_MOMENTUM_MODE) were never
            # handed to trailing_stop.start() -- their stop IS
            # initial_stop, unchanging by design. Everything else
            # reads the live ratcheted value as before.
            stop_value = initial_stop if fixed_target is not None \
                else self.engine.trailing_stop.get_stop(symbol)

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
                "avg_win": None, "avg_loss": None,
                "gross_profit": 0.0, "gross_loss": 0.0,
                "max_drawdown": 0.0, "net_pnl": 0.0,
            }

        wins = losses = flat = 0
        gross_profit = gross_loss = 0.0
        running = peak = max_dd = 0.0

        for record in closed:
            pnl = record.get("pnl")
            if pnl is None:
                direction = record.get("direction", "LONG")
                pnl = _signed_pnl(
                    direction, record["entry_price"], record["exit_price"],
                    record["qty"],
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

        return {
            "total_trades": total,
            "wins": wins,
            "losses": losses,
            "flat": flat,
            "win_rate_pct": round(wins / total * 100, 1),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else None,
            "avg_win": round(gross_profit / wins, 2) if wins > 0 else None,
            "avg_loss": round(gross_loss / losses, 2) if losses > 0 else None,
            "gross_profit": round(gross_profit, 2),
            "gross_loss": round(gross_loss, 2),
            "max_drawdown": round(max_dd, 2),
            "net_pnl": round(running, 2),
        }

    def _build_news_feed(self):
        """Today's HIGH-priority news items, newest first -- same
        advisory-only source core/engine.py's news-contradiction
        check reads (core/news_gate.py), just formatted as a real
        feed for the Alert Center panel."""
        if self.news_gate is None:
            return []

        items = []
        for symbol, item in self.news_gate.all_news_stocks().items():
            items.append({
                "symbol": symbol,
                "direction": item.get("direction"),
                "confidence": item.get("confidence"),
                "reason": item.get("reason"),
                "time": item.get("time"),
                "source": item.get("source"),
            })

        items.sort(key=lambda r: r.get("time") or "", reverse=True)
        return items

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
