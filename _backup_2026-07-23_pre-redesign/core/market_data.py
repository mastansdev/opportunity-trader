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

from config import MARKET_OPEN, MAX_TICK_STALENESS_SECONDS
from core.logger import diagnostic, warn


def _parse_hhmm(value):
    hour, minute = value.split(":")
    return dtime(int(hour), int(minute))


MARKET_OPEN_T = _parse_hhmm(MARKET_OPEN)


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

    # --------------------------------------------------

    def on_new_tick(self, callback):
        """Register something to run for every accepted tick."""
        self._callbacks.append(callback)

    # --------------------------------------------------

    def on_tick(self, symbol, price, tick_time, now=None):
        """
        Single entry point for every tick, real or
        simulated. Returns True if the tick was accepted,
        False if it was dropped as pre-market.
        """
        now = now or datetime.now()

        if tick_time.time() < MARKET_OPEN_T:
            diagnostic(
                f"[MARKET_DATA] Dropped pre-market tick "
                f"{symbol} @ {tick_time} (before {MARKET_OPEN})"
            )
            return False

        staleness = (now - tick_time).total_seconds()
        if staleness > MAX_TICK_STALENESS_SECONDS:
            if symbol not in self._stale_symbols:
                self._stale_symbols.add(symbol)
                self._stale_warning_count += 1
                warn(
                    f"Stale tick for {symbol}: {staleness:.1f}s old "
                    f"(tick_time={tick_time}, now={now}). Further "
                    f"staleness for {symbol} goes to the file log only "
                    f"until it recovers."
                )
            else:
                diagnostic(
                    f"[MARKET_DATA] {symbol} still stale: "
                    f"{staleness:.1f}s old."
                )
        elif symbol in self._stale_symbols:
            self._stale_symbols.discard(symbol)
            diagnostic(f"[MARKET_DATA] {symbol} recovered from stale ticks.")

        with self._lock:
            if symbol not in self._day_open_price:
                self._day_open_price[symbol] = price
            self._latest_price[symbol] = price
            self._tick_count += 1

        for callback in self._callbacks:
            callback(symbol, price, tick_time)

        return True

    # --------------------------------------------------

    def get_tick_count(self):
        with self._lock:
            return self._tick_count

    def get_stale_warning_count(self):
        return self._stale_warning_count

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
