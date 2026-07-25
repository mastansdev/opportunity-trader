"""
==========================================================
Momentum Universe
==========================================================

The narrowed, ranked universe for TOP_N_MOMENTUM_MODE (config.py,
built 2026-07-23 evening for the 2026-07-24 (Friday) session --
see config.py's own docstring for the full "why", and
core/engine.py's _check_fixed_bracket() for the fixed-SL/target
side of this experiment).

Operator's own words: "enter into only stocks where the alpha
matter lies intraday -- if we keep concentration on whole 750
stocks = bot will be loaded & human cannot do at all... best in my
terms top trending stocks in both cases = top 25 gainers & top 25
losers."

Ranks every symbol by %-change vs its own day open (identical
comparison to core/sector_monitor.py's and dashboard/state.py's
breadth calc -- deliberately reused, not reinvented) and LOCKS the
top N gainers as the only LONG-eligible symbols, and the bottom N
(top N losers) as the only SHORT-eligible symbols, for the REST OF
THE DAY. This is a one-shot lock() at ORB_WINDOW_END (main.py),
not a periodic refresh like SectorMonitor -- the operator's design
is a stable daily shortlist, not a constantly-reshuffling one (see
config.py's TOP_N_MOMENTUM_LIST_SIZE docstring for why: an open
trade shouldn't lose its own eligibility mid-trade just because
some other symbol overtook it in the rankings ten minutes later).

Persisted across restart (core/state_store.py) -- once locked, an
intraday restart must restore the EXACT same 50 symbols, not
recompute a possibly-different list from whatever prices happen to
be current at restart time.

Author : H&M Opportunity Trader
==========================================================
"""

from core.logger import decision
from core.trailing_stop import LONG, SHORT

from config import TOP_N_MOMENTUM_LIST_SIZE


class MomentumUniverse:

    def __init__(self, market_data, master_loader):
        self.market_data = market_data
        self.master_loader = master_loader
        self._long_universe = None   # None = not locked yet today
        self._short_universe = None

    # --------------------------------------------------

    def is_locked(self):
        return self._long_universe is not None

    def lock(self):
        """
        Ranks every symbol by %-change vs day open, locks the top
        TOP_N_MOMENTUM_LIST_SIZE gainers as LONG-eligible and the
        bottom TOP_N_MOMENTUM_LIST_SIZE (i.e. the biggest losers)
        as SHORT-eligible. Call exactly ONCE, right at
        ORB_WINDOW_END (main.py enforces the "once" part via its
        own momentum_locked guard, same pattern as squared_off for
        SQUARE_OFF_T) -- calling this twice would silently replace
        the day's shortlist partway through, which defeats the
        entire point of a stable daily list.

        Symbols with no day-open or no live price yet (illiquid /
        untraded so far) are simply excluded from the ranking, same
        as every other breadth calc in this codebase -- never
        guessed at.
        """
        changes = []
        for symbol in self.master_loader.all_symbols():
            open_price = self.market_data.get_day_open(symbol)
            last_price = self.market_data.get_latest_price(symbol)
            if not open_price or last_price is None:
                continue
            change_pct = (last_price - open_price) / open_price * 100
            changes.append((symbol, change_pct))

        changes.sort(key=lambda pair: pair[1], reverse=True)

        gainers = changes[:TOP_N_MOMENTUM_LIST_SIZE]
        losers = changes[-TOP_N_MOMENTUM_LIST_SIZE:] if changes else []
        losers = list(reversed(losers))  # biggest loser first, cosmetic only

        self._long_universe = {symbol for symbol, _ in gainers}
        self._short_universe = {symbol for symbol, _ in losers}

        decision(
            f"[MOMENTUM] Universe locked for today -- "
            f"LONG-eligible ({len(self._long_universe)}): "
            f"{', '.join(sorted(self._long_universe))}\n"
            f"SHORT-eligible ({len(self._short_universe)}): "
            f"{', '.join(sorted(self._short_universe))}"
        )

        return {
            "long": sorted(self._long_universe),
            "short": sorted(self._short_universe),
        }

    def is_eligible(self, symbol, direction):
        """
        False before lock() has ever run -- structurally this
        never matters in practice (no structural signal can fire
        before ORB_WINDOW_END anyway, see core/orb_engine.py), but
        fail-CLOSED here is the correct default: "not yet in
        today's shortlist" should mean "not eligible", not "let it
        through because we haven't decided yet".
        """
        if self._long_universe is None:
            return False
        universe = self._long_universe if direction == LONG else self._short_universe
        return symbol in universe

    # --------------------------------------------------

    def export_state(self):
        """Plain-dict snapshot, safe to json.dump directly. None
        (not locked yet) exports as empty lists -- load_state()
        treats an empty pair as "not locked", not "locked with
        zero eligible symbols"."""
        return {
            "long": sorted(self._long_universe) if self._long_universe else [],
            "short": sorted(self._short_universe) if self._short_universe else [],
        }

    def load_state(self, state):
        """Restores a lock from a snapshot produced by
        export_state() -- e.g. after an intraday restart past
        ORB_WINDOW_END. An empty/missing state leaves this
        unlocked, exactly like a fresh instance; main.py's own
        momentum_locked guard is what then decides whether to call
        lock() fresh."""
        if not state:
            return
        long_list = state.get("long") or []
        short_list = state.get("short") or []
        if not long_list and not short_list:
            return
        self._long_universe = set(long_list)
        self._short_universe = set(short_list)
