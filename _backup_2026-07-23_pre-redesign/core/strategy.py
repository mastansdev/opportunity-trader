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


class Strategy:

    def __init__(self, orb_engine):
        self.orb_engine = orb_engine

    # --------------------------------------------------

    def is_buy_signal(self, symbol, closed_candle, already_open):
        """
        closed_candle: dict from CandleEngine.update() /
        last_closed(), or None if no candle has closed yet.
        """
        orb_range = self._ready_range(symbol, closed_candle, already_open)
        if orb_range is None:
            return False

        return closed_candle["close"] > orb_range["high"]

    def is_short_signal(self, symbol, closed_candle, already_open):
        """Mirror of is_buy_signal -- CLOSE below the ORB low."""
        orb_range = self._ready_range(symbol, closed_candle, already_open)
        if orb_range is None:
            return False

        return closed_candle["close"] < orb_range["low"]

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
