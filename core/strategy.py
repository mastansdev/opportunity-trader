"""
==========================================================
Strategy -- Layer 1
==========================================================

TWO mirrored triggers, both pure price action, nothing else:
  - LONG  : a 1-minute candle CLOSES above the ORB high.
  - SHORT : a 1-minute candle CLOSES below the ORB low.
Not a touch, not a wick -- a close, either direction.

If the ORB range isn't complete yet, there is no signal.
If a symbol already has an open position, there is no
signal (no pyramiding in Layer 1).

Author : H&M Opportunity Trader
==========================================================
"""


from config import BREAKOUT_MIN_MARGIN_PCT


class Strategy:

    def __init__(self, orb_engine):
        self.orb_engine = orb_engine
        # Per-symbol memory of whether the PRIOR closed candle was
        # already beyond the range. 2026-07-24 (evening) #0b fix: the
        # breakout must fire ONCE, on the fresh CROSS (inside -> out),
        # not on every candle a stock spends sitting beyond its range.
        # Without this, a stock that broke out at 11am is a standing
        # signal all afternoon, so the 10-slot cap instantly refills
        # the moment any position closes (operator report). These are
        # updated EVERY closed candle via note_candle_close() -- even
        # while a position is open -- so a stopout that leaves price
        # still beyond the range can't immediately re-fire.
        self._was_above = {}
        self._was_below = {}

        # 2026-07-24 (evening) Change 1 -- restart-seeding. A symbol
        # is "primed" only AFTER we've observed at least one closed
        # candle for it (post ORB-completion) this run. Until then, a
        # signal can't fire -- the FIRST candle we see only RECORDS
        # the beyond-range state, it never triggers an entry. This is
        # the fix for the stale-restart entry (KPITTECH, 2026-07-24):
        # if the bot restarts at 2pm and KPITTECH is already at 583,
        # far above its 556.70 ORB high, a fresh-started Strategy has
        # no memory that the cross happened at 12:02 -- so without
        # priming it would read "583 > 556.70" as a brand-new breakout
        # and buy the top. Priming makes the first post-restart candle
        # merely record "already above", so only a GENUINE later cross
        # (price drops back inside, then breaks out again) can fire.
        # On a fresh 09:15 start this costs nothing: the first candle
        # after the range completes is almost always still inside the
        # range, so it just primes, and the real breakout later fires
        # normally.
        self._primed = set()

    # --------------------------------------------------

    def is_buy_signal(self, symbol, closed_candle, already_open):
        """
        closed_candle: dict from CandleEngine.update() /
        last_closed(), or None if no candle has closed yet.

        Fires only on a FRESH cross above the ORB high -- this candle
        closes above it AND the prior closed candle did not -- and
        only once the symbol has been PRIMED (at least one prior
        closed candle observed this run, see the __init__ docstring's
        restart-seeding note).
        """
        orb_range = self._ready_range(symbol, closed_candle, already_open)
        if orb_range is None:
            return False

        if symbol not in self._primed:
            return False

        now_above = closed_candle["close"] > self._long_threshold(orb_range)
        return now_above and not self._was_above.get(symbol, False)

    def is_short_signal(self, symbol, closed_candle, already_open):
        """Mirror of is_buy_signal -- a FRESH cross below the ORB low."""
        orb_range = self._ready_range(symbol, closed_candle, already_open)
        if orb_range is None:
            return False

        if symbol not in self._primed:
            return False

        now_below = closed_candle["close"] < self._short_threshold(orb_range)
        return now_below and not self._was_below.get(symbol, False)

    # The breakout must clear the ORB boundary by a real margin
    # (config.BREAKOUT_MIN_MARGIN_PCT) to count -- a close that just
    # grazes the line is range noise (see the engine's own margin
    # gate). 2026-07-24 (evening): folded INTO the strategy so the
    # fresh-cross memory (#0b) tracks the SAME margin-adjusted line
    # the signal uses -- otherwise a sub-margin dip below the low
    # would arm _was_below and swallow the real breakdown that
    # follows.
    def _long_threshold(self, orb_range):
        return orb_range["high"] * (1 + BREAKOUT_MIN_MARGIN_PCT)

    def _short_threshold(self, orb_range):
        return orb_range["low"] * (1 - BREAKOUT_MIN_MARGIN_PCT)

    def note_candle_close(self, symbol, closed_candle):
        """
        Update the per-symbol beyond-range memory. MUST be called
        once per closed candle for EVERY symbol -- including while a
        position is open, when no entry can fire -- so a fresh cross
        can be distinguished from a stock that's simply been sitting
        beyond its range. Called by core/engine.py's process_tick()
        after the signal branch. A no-op until the ORB range is
        complete (nothing to be "beyond" yet).
        """
        if closed_candle is None or not self.orb_engine.is_complete(symbol):
            return
        orb_range = self.orb_engine.get_range(symbol)
        if orb_range is None:
            return
        close = closed_candle["close"]
        self._was_above[symbol] = close > self._long_threshold(orb_range)
        self._was_below[symbol] = close < self._short_threshold(orb_range)
        # Priming happens here, AFTER the first state is recorded, so
        # the first observed candle can never itself have fired a
        # signal (is_buy/is_short return False until primed). See the
        # __init__ restart-seeding note.
        self._primed.add(symbol)

    # --------------------------------------------------

    def _ready_range(self, symbol, closed_candle, already_open):
        """Shared guards for both signals -- returns the ORB range
        if a signal is even possible, else None."""
        if already_open:
            return None

        if closed_candle is None:
            return None

        if not self.orb_engine.is_complete(symbol):
            return None

        return self.orb_engine.get_range(symbol)
