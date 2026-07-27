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
        if staleness > MAX_TICK_STALENESS_SECONDS:
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
            if MARKET_OPEN_T <= tick_time.time() < ORB_WINDOW_END_T \
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
            self._tick_count += 1

        for callback in self._callbacks:
            callback(symbol, price, tick_time, cum_volume)

        return True

    # --------------------------------------------------

    def get_tick_count(self):
        with self._lock:
            return self._tick_count

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

    def get_day_open(self, symbol):
        """
        The first accepted tick price for this symbol today --
        used as the dashboard's advance/decline reference (NOT
        previous day's close; that would need either a feed-mode
        change or a separate REST lookup this build didn't take
        on -- see dashboard/state.py's own docstring).

        KNOWN LIMITATION, not persisted across a restart: a
        restart mid-session resets this to the first tick
        received AFTER the restart, not the true day's open.
        Only affects the advance/decline/sector-colour display,
        never trading logic.
        """
        with self._lock:
            return self._day_open_price.get(symbol)
