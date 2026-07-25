"""
==========================================================
Sector Monitor
==========================================================

Detects when an entire SECTOR is falling together, not just one
stock -- the "Trump tariff on generic pharma" case the operator
raised: the tariffs weren't even immediate (2 years out) and only
applied to companies without US manufacturing, but pharma sold
off broadly anyway on the headline alone. That's the market
repricing on fear, not on any one company's fundamentals. Buying
a fresh bullish breakout inside a sector doing that is fighting
the market, not trading it.

Deliberately BREADTH-BASED, not news-matching-based: it reuses
the same day-open vs latest-price comparison the dashboard
already shows (core/market_data.py's get_day_open()), grouped by
sector (data/master_stocks.csv's SECTOR field, via
core/master_loader.py) -- completely independent of News Bot.
Conscious trade-off: correlating one macro headline to every
symbol it affects would need deeper changes to
news_bot/matching.py's current one-symbol-at-a-time model. It
isn't needed for the actual goal here -- don't buy long into a
sector the market itself is already broadly rejecting today,
regardless of exactly why.

Thresholds: config.SECTOR_PANIC_AVG_CHANGE_PCT,
SECTOR_PANIC_MIN_DECLINE_RATIO, SECTOR_PANIC_MIN_SYMBOLS.

Only ever affects new LONG entries (core/engine.py's
_try_structural_entry()) -- NEVER blocks a SHORT. A structural
breakdown inside a genuinely panicking sector is going WITH the
market, not against it, and stays fully available, same as any
other stock.

Refreshed on a timer (main.py, same cadence as the heartbeat) --
never recomputed on the hot tick path; is_panicking()/
is_symbol_in_panicking_sector() just read the last computed set
under a lock.

Not persisted across restart -- it's a live signal derived from
the same day-open baseline core/market_data.py already documents
as restart-reset (see get_day_open()'s own docstring). The
per-symbol entry BLOCK it triggers (core/engine.py's
entry_blocked) *is* persisted, so a block already placed
survives a restart even though this monitor's own live picture
starts fresh.

Author : H&M Opportunity Trader
==========================================================
"""

import threading

from config import (
    SECTOR_PANIC_AVG_CHANGE_PCT,
    SECTOR_PANIC_MIN_DECLINE_RATIO,
    SECTOR_PANIC_MIN_SYMBOLS,
)


class SectorMonitor:

    def __init__(self, market_data, master_loader):
        self.market_data = market_data
        self.master_loader = master_loader
        self._lock = threading.Lock()
        self._panic_sectors = set()

    # --------------------------------------------------

    def refresh(self):
        """Rebuilds the panic set, then swaps it in atomically --
        same pattern as NewsQueueReader.refresh() /
        DashboardState.refresh()."""
        panic = self._compute_panic_sectors()
        with self._lock:
            self._panic_sectors = panic

    def panicking_sectors(self):
        with self._lock:
            return set(self._panic_sectors)

    def is_panicking(self, sector):
        with self._lock:
            return sector in self._panic_sectors

    def sector_of(self, symbol):
        record = self.master_loader.get_by_symbol(symbol)
        return record.get("SECTOR") if record else None

    def is_symbol_in_panicking_sector(self, symbol):
        sector = self.sector_of(symbol)
        return sector is not None and self.is_panicking(sector)

    # --------------------------------------------------

    def _compute_panic_sectors(self):
        by_sector = {}  # sector -> [change_pct, ...]

        for symbol in self.master_loader.all_symbols():
            open_price = self.market_data.get_day_open(symbol)
            last_price = self.market_data.get_latest_price(symbol)
            if not open_price or last_price is None:
                continue

            record = self.master_loader.get_by_symbol(symbol)
            sector = record.get("SECTOR") if record else None
            if not sector:
                continue

            change_pct = (last_price - open_price) / open_price * 100
            by_sector.setdefault(sector, []).append(change_pct)

        panic = set()
        for sector, changes in by_sector.items():
            if len(changes) < SECTOR_PANIC_MIN_SYMBOLS:
                continue

            avg_change = sum(changes) / len(changes)
            decline_ratio = sum(1 for c in changes if c < 0) / len(changes)

            if (avg_change <= SECTOR_PANIC_AVG_CHANGE_PCT
                    and decline_ratio >= SECTOR_PANIC_MIN_DECLINE_RATIO):
                panic.add(sector)

        return panic
