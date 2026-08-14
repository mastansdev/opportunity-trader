"""
==========================================================
Market Data
==========================================================

Wraps the Dhan live feed. Two data-integrity rules are
enforced here, at the entry point, not downstream:

    1. A tick timestamped before MARKET_OPEN is dropped --
       logged loudly, never silently treated as live.
    2. A tick whose timestamp is older than wall clock by
       more than MAX_TICK_STALENESS_SECONDS is flagged --
       still processed (dropping every stale tick could
       stall the bot), but the staleness is never hidden.

Author : H&M Opportunity Trader
==========================================================
"""

import threading
from datetime import datetime, time as dtime

import time as _time

from config import (
    MARKET_OPEN, MAX_TICK_STALENESS_SECONDS, ORB_WINDOW_END,
    FEED_WARMUP_GRACE_SECONDS, FEED_SYSTEMIC_STALE_FRACTION,
    STALENESS_ADAPTIVE, STALENESS_MULTIPLE, STALENESS_MIN_SECONDS,
    STALENESS_WARMUP_TICKS, ORB_WINDOW_MAX_GAP_SECONDS,
)
from core.logger import decision, diagnostic, warn


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


MARKET_OPEN_T = _parse_hhmm(MARKET_OPEN)
ORB_WINDOW_END_T = _parse_hhmm(ORB_WINDOW_END)


class MarketData:
    """
    Thin, testable wrapper. The real Dhan MarketFeed
    connection is created in main.py and pushes ticks in
    here via on_tick() -- this class never talks to the
    network itself, so it can be unit tested with fake
    ticks.
    """

    def __init__(self):
        self._latest_price = {}
        self._day_open_price = {}
        # symbol -> {"high": x, "low": y}. Nothing else in the bot keeps
        # a running session extreme -- the candle store is trimmed, so a
        # high made at 09:16 is gone by noon, which is exactly the case
        # the ranker has to catch. See day_extremes().
        self._day_extremes = {}

        # The EXCHANGE's own opening price, when we have it. Preferred
        # over the first-tick guess above, which is ~2 seconds and a
        # rupee or two late. See set_official_day_open.
        self._official_day_open = {}
        self._lock = threading.Lock()
        self._callbacks = []
        self._tick_count = 0

        # Edge-triggered stale tracking: warn on console once when a
        # symbol GOES stale, not on every repeat -- at 750 symbols,
        # level-triggered logging here is exactly what floods a
        # terminal into uselessness. Repeats go to file only.
        self._stale_symbols = set()
        self._stale_warning_count = 0

        # #2, 2026-07-24 (evening) -- console-noise controls. Every
        # symbol we've ever accepted a tick for (the live universe, so
        # the systemic stale FRACTION has a denominator), the startup
        # instant (for the warm-up grace), and whether the systemic
        # "feed is lagging" alarm is currently raised (edge-triggered,
        # so it fires/clears once, not per tick).
        self._seen_symbols = set()
        self._started_at = _time.monotonic()
        self._systemic_stale_active = False

        # ORB-window staleness, 2026-07-24 -- operator's live report:
        # SONACOMS bought at 734.80 as a "breakout" above the bot's
        # saved ORB high (733.30), but Dhan's own ORB indicator
        # showed the true high at 737.10 -- 734.80 was still INSIDE
        # the real range. Traced to a ~30s stale-feed gap right at
        # 09:15:26-09:15:42 (see diagnostics.log), the single most
        # volatile stretch of the session -- whatever the real price
        # did during that gap was never delivered as individual
        # ticks, so orb_engine.update() never saw the true peak and
        # built a range 3.80 too narrow. A symbol that goes stale
        # WHILE its own ORB window [MARKET_OPEN, ORB_WINDOW_END) is
        # still open can't be trusted to have a complete range, full
        # stop -- flagged here, once, permanently for the session
        # (recovering from staleness doesn't un-happen the gap that
        # already occurred). core/engine.py's _try_structural_entry()
        # silently skips structural entries for any flagged symbol,
        # same pattern as the frozen-price/circuit-proximity checks.
        self._orb_window_stale_symbols = set()

        # PER-SYMBOL STALENESS, 2026-07-28. symbol -> [ewma_gap, count].
        # A plain list, not a dict, because this is touched on every one
        # of ~9,000 ticks a minute and two integer slots beat two hash
        # lookups. See config.py's STALENESS_ADAPTIVE block for why one
        # flat threshold could never work: it was set BELOW the feed's
        # own 4.63s average gap, so half the universe was permanently
        # "stale" and 607 symbols were locked out of trading.
        self._gap_stats = {}
        self._last_tick_time = {}

    # --------------------------------------------------

    def on_new_tick(self, callback):
        """Register something to run for every accepted tick."""
        self._callbacks.append(callback)

    # --------------------------------------------------

    def on_tick(self, symbol, price, tick_time, now=None, cum_volume=None):
        """
        Single entry point for every tick, real or
        simulated. Returns True if the tick was accepted,
        False if it was dropped as pre-market.

        cum_volume (2026-07-24 Change 2) is the feed's day-cumulative
        traded volume (Quote mode), or None in Ticker mode. It's
        forwarded to callbacks untouched -- market_data itself does
        nothing with it beyond passing it down to the candle engine.
        """
        now = now or datetime.now()

        if tick_time.time() < MARKET_OPEN_T:
            diagnostic(
                f"[MARKET_DATA] Dropped pre-market tick "
                f"{symbol} @ {tick_time} (before {MARKET_OPEN})"
            )
            return False

        self._seen_symbols.add(symbol)

        # #2, 2026-07-24 (evening): individual per-symbol stale events
        # NEVER hit the console any more -- they go to the file log
        # only. A single quiet mid-cap not trading for 5s is not
        # actionable, and 340 such lines at once (afternoon lull) or
        # 646 at once (open/restart connect burst) just drowned the
        # terminal. The console instead gets ONE systemic alarm when a
        # large share of the whole feed is stale together (see
        # _update_systemic_stale) -- the real "feed is lagging" signal.
        staleness = (now - tick_time).total_seconds()
        threshold = self._staleness_threshold(symbol, tick_time)
        if staleness > threshold:
            if symbol not in self._stale_symbols:
                self._stale_symbols.add(symbol)
                self._stale_warning_count += 1
            diagnostic(
                f"[MARKET_DATA] {symbol} stale: {staleness:.1f}s old "
                f"(tick_time={tick_time})."
            )

            # ORB-window integrity flag -- a genuine data-quality check
            # (the SONACOMS gap), kept ALWAYS-on and unchanged in
            # behaviour; just its log line moved to file-level so it
            # doesn't add to the console burst. The flag itself still
            # blocks structural entries for that symbol all session.
            # The ORB flag uses its OWN, much larger threshold. It
            # inherited the 5s general one and blacklisted 607 of 666
            # symbols on 2026-07-28 -- the bot took zero automated
            # entries all day. The incident it exists for (SONACOMS)
            # was a ~30 SECOND gap; below that is a quiet stock, not a
            # hole in the feed.
            if staleness >= ORB_WINDOW_MAX_GAP_SECONDS \
                    and MARKET_OPEN_T <= tick_time.time() < ORB_WINDOW_END_T \
                    and symbol not in self._orb_window_stale_symbols:
                self._orb_window_stale_symbols.add(symbol)
                diagnostic(
                    f"[MARKET_DATA] {symbol} went stale INSIDE its own "
                    f"ORB window (tick_time={tick_time}) -- range flagged "
                    f"unreliable; structural entries skipped for it today."
                )
        elif symbol in self._stale_symbols:
            self._stale_symbols.discard(symbol)
            diagnostic(f"[MARKET_DATA] {symbol} recovered from stale ticks.")

        self._update_systemic_stale()

        with self._lock:
            if symbol not in self._day_open_price:
                self._day_open_price[symbol] = price
            self._latest_price[symbol] = price
            # RUNNING SESSION HIGH AND LOW. See day_extremes(). Two
            # comparisons per tick, and without them core/ranker.py
            # cannot tell a stock making new highs from one that peaked
            # at 09:16 and has been sold ever since.
            seen = self._day_extremes.get(symbol)
            if seen is None:
                self._day_extremes[symbol] = {"high": price, "low": price}
            else:
                if price > seen["high"]:
                    seen["high"] = price
                if price < seen["low"]:
                    seen["low"] = price
            self._tick_count += 1

        for callback in self._callbacks:
            callback(symbol, price, tick_time, cum_volume)

        return True

    # --------------------------------------------------

    def get_tick_count(self):
        with self._lock:
            return self._tick_count

    def _staleness_threshold(self, symbol, tick_time):
        """How stale is too stale FOR THIS SYMBOL.

        Learns each symbol's own typical gap between trades and flags
        only a wide multiple of it. A stock that prints every 2 seconds
        is flagged at 8s; one that genuinely trades every 25 seconds is
        not flagged for being itself.

        Why this had to change: the old flat 5s was BELOW the feed's own
        4.63s average gap (measured live, 2026-07-28), so ~half the
        universe was permanently "stale". Dhan sends snapshots, not
        every trade, and tick_time is the last TRADE time -- so a quiet
        mid-cap looks identical to a broken feed.

        Falls back to the flat threshold until a symbol has enough
        history to have a normal.
        """
        if not STALENESS_ADAPTIVE:
            return MAX_TICK_STALENESS_SECONDS

        stats = self._gap_stats.get(symbol)
        previous = self._last_tick_time.get(symbol)
        self._last_tick_time[symbol] = tick_time

        if previous is not None:
            gap = (tick_time - previous).total_seconds()
            # Ignore non-positive gaps (same-second snapshots, or a
            # replay stepping backwards) -- they would drag the average
            # to zero and make everything look stale.
            if gap > 0:
                if stats is None:
                    stats = [gap, 1]
                    self._gap_stats[symbol] = stats
                else:
                    # EWMA, alpha 0.1 -- responds to a genuine change in
                    # a symbol's rhythm over ~20 ticks without letting
                    # one long lunchtime pause reset its normal.
                    stats[0] += 0.1 * (gap - stats[0])
                    stats[1] += 1

        if stats is None or stats[1] < STALENESS_WARMUP_TICKS:
            return MAX_TICK_STALENESS_SECONDS
        return max(STALENESS_MIN_SECONDS, STALENESS_MULTIPLE * stats[0])

    def typical_gap(self, symbol):
        """This symbol's learned normal, in seconds. None until warm."""
        stats = self._gap_stats.get(symbol)
        if stats is None or stats[1] < STALENESS_WARMUP_TICKS:
            return None
        return round(stats[0], 2)

    def get_stale_warning_count(self):
        return self._stale_warning_count

    def is_orb_window_unreliable(self, symbol):
        """True once this symbol has EVER gone stale while its own
        [MARKET_OPEN, ORB_WINDOW_END) window was still open, for the
        rest of the session -- see this class's own docstring/the
        SONACOMS 2026-07-24 incident for why. Never un-flags on
        recovery -- the gap already happened, so the range built
        around it can't retroactively become trustworthy again."""
        return symbol in self._orb_window_stale_symbols

    def clear_orb_window_unreliable(self, symbol):
        """The range has been rebuilt from the EXCHANGE's own high/low,
        so the feed gap no longer matters.

        The flag means one thing: "we may have missed the true high or
        low while building this range". core/engine.py's
        _reconcile_orb_from_exchange() replaces the range with the
        exchange's published values -- which is precisely the doubt this
        flag records. Leaving it set after that blocks a symbol whose
        range is now known-correct.

        On 2026-07-28 the flag was set on 607 of 666 symbols and the bot
        took ZERO automated entries. Many of those ranges had already
        been reconciled and were fine.

        Returns True if a flag was actually cleared, so the caller can
        say so once rather than every tick.
        """
        if symbol in self._orb_window_stale_symbols:
            self._orb_window_stale_symbols.discard(symbol)
            return True
        return False

    def get_orb_window_unreliable_count(self):
        return len(self._orb_window_stale_symbols)

    # --------------------------------------------------
    # Restart persistence (core/state_store.py)
    #
    # Added 2026-07-27, operator-found. This flag used to live only in
    # memory, so a restart forgot it. On 2026-07-27:
    #
    #   09:16  TBZ went stale INSIDE its own ORB window -- range
    #          flagged unreliable; structural entries skipped today.
    #   14:59  PAPER BUY TBZ (STRUCTURAL_LONG_BREAKOUT)
    #
    # Two restarts wiped the flag and the bot took the trade it had
    # already refused, on a range built around a hole in the feed. It
    # made money, which is the worst outcome -- a rule that quietly
    # stops applying looks fine until the day it doesn't.
    # --------------------------------------------------

    def export_orb_unreliable(self):
        """Plain sorted list, safe to json.dump directly."""
        return sorted(self._orb_window_stale_symbols)

    def load_orb_unreliable(self, symbols):
        """Restores from a snapshot produced by export_orb_unreliable().

        MERGES rather than overwrites -- unlike every other load_state()
        in this codebase, and deliberately so. This flag is one-way: a
        symbol that was unreliable at 09:16 is still unreliable at
        14:59, and anything flagged since the snapshot was written is
        equally real. Union is the only safe direction; dropping either
        set would re-open the hole this exists to close."""
        if not symbols:
            return
        self._orb_window_stale_symbols.update(symbols)

    def _in_warmup(self):
        return (_time.monotonic() - self._started_at) < FEED_WARMUP_GRACE_SECONDS

    def _update_systemic_stale(self):
        """#2, 2026-07-24 (evening): the ONE console signal about the
        feed. Edge-triggered -- fires once when the share of seen
        symbols that are stale AT ONCE crosses
        FEED_SYSTEMIC_STALE_FRACTION (a genuine feed lag, not a few
        quiet stocks), and clears once when it drops back. Silent
        during the warm-up grace, when a connect/open burst briefly
        makes almost everything 'stale' before self-clearing."""
        seen = len(self._seen_symbols)
        if seen == 0:
            return
        fraction = len(self._stale_symbols) / seen

        if self._in_warmup():
            # Keep the flag in sync silently, so we don't emit a stale
            # "recovered" line the moment the grace period ends.
            self._systemic_stale_active = fraction >= FEED_SYSTEMIC_STALE_FRACTION
            return

        if fraction >= FEED_SYSTEMIC_STALE_FRACTION and not self._systemic_stale_active:
            self._systemic_stale_active = True
            warn(
                f"[FEED] {len(self._stale_symbols)}/{seen} symbols "
                f"({fraction * 100:.0f}%) are stale AT ONCE -- the feed "
                f"appears to be lagging systemically, not just a few quiet "
                f"stocks. Watch for gaps in candles/entries."
            )
        elif fraction < FEED_SYSTEMIC_STALE_FRACTION and self._systemic_stale_active:
            self._systemic_stale_active = False
            decision(
                f"[FEED] Systemic staleness cleared -- back to "
                f"{fraction * 100:.0f}% stale."
            )

    # --------------------------------------------------

    def get_latest_price(self, symbol):
        with self._lock:
            return self._latest_price.get(symbol)

    def day_extremes(self, symbol=None):
        """The session's high and low per symbol, from the ticks.

        ==========================================================
            "some stocks will rally in opening 1/2 mins & sit in top
             gainers no use of such movement in stock for trader"
                                -- operator, 4 August 2026
        ==========================================================

        core/ranker.py's liveness() decides whether a move is still
        happening by asking how far the stock has given back from its
        extreme. I wrote that gate reading row["day_high"] -- and
        day_high does not exist anywhere in the payload. Two of the
        three legs would have been permanently dark while the code
        looked complete. That is the same mistake as the index parser
        and the frozen candle store, for the third time.

        Nothing else in the bot keeps a running session high. The
        candle store has per-minute highs but is trimmed, so a high
        made at 09:16 is gone by noon -- which is precisely the case
        this has to catch.

        So it is tracked here, where every tick already arrives, at the
        cost of two comparisons per tick.
        """
        with self._lock:
            if symbol is not None:
                return self._day_extremes.get(symbol)
            return {s: dict(v) for s, v in self._day_extremes.items()}

    def latest_prices(self):
        """EVERY live price at once, as a plain dict copy.

        ==========================================================
            "even today i got confused no of times & felt that lag
             on price observations"    -- operator, 4 August 2026
        ==========================================================

        The dashboard's price lag was never the feed. Ticks land here
        the moment Dhan sends them. The lag was everything after:
        main.py rebuilt the whole snapshot on a 1-second timer, and
        the page then polled that snapshot every 2 seconds -- so a
        number on his screen could be three seconds old while the Dhan
        app beside it was current. Correct, and stale, which is the
        worst combination because it looks right.

        A price channel needs none of that machinery. It needs this
        dict, copied under the same lock every other reader uses, so
        the server can push only what CHANGED, several times a second,
        without touching the snapshot builder at all.

        Returns a COPY on purpose. Handing out the live dict would let
        a caller iterate it while a tick thread writes -- and that is a
        RuntimeError mid-session, on the one path that must not break.
        """
        with self._lock:
            return dict(self._latest_price)

    def set_official_day_open(self, symbol, open_price):
        """Replace our first-tick guess with the EXCHANGE's real open.

        =====================================================
        2026-07-29 -- the bot never saw the opening print
        =====================================================
        Measured on INFY, 29 July:

            NSE pre-open equilibrium   1,147.00   (+3.74%)
            bot's first tick           1,145.00   (+3.55%)

        Rs 2 late. Dhan sends one snapshot per symbol roughly every
        4.6 seconds, so by the time the first packet arrives the
        opening print has already gone past. Nothing is wrong with the
        arithmetic -- it is correct arithmetic on a price that is two
        seconds old.

        That 0.19% is the whole of the "bot doesn't match NSE at 09:15"
        complaint the operator raised, and it is also why a restart
        used to corrupt the reference completely: get_day_open() then
        returned the first tick after the restart, which could be
        hours into the session.

        Dhan's REST quote carries the real open in the same response
        the circuit monitor already polls every 3 seconds. Set once per
        symbol per day; a later call cannot move it, because the open
        does not change.
        """
        try:
            open_price = float(open_price)
        except (TypeError, ValueError):
            return
        if open_price <= 0:
            return
        with self._lock:
            if self._official_day_open.get(symbol) == open_price:
                return
            self._official_day_open[symbol] = open_price

    def get_day_open(self, symbol):
        """
        This symbol's opening price today.

        Prefers the EXCHANGE's own open (set_official_day_open) and
        falls back to our first accepted tick, which is typically a
        rupee or two late -- see that method for the measurement.

        Used as the dashboard's advance/decline reference. The fallback
        also carries the old restart limitation: a mid-session restart
        resets it to the first tick received AFTER the restart. The
        official open does not suffer from that, which is a second
        reason to prefer it.
        """
        with self._lock:
            official = self._official_day_open.get(symbol)
            if official:
                return official
            return self._day_open_price.get(symbol)
