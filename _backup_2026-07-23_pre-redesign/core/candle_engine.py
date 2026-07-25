"""
==========================================================
Candle Engine
==========================================================

Builds 1-minute candles per symbol from raw ticks. Exists
for exactly one reason: the strategy needs to know when a
candle CLOSES, not just the running price, so a breakout
can be confirmed rather than triggered on a fake wick.

Author : H&M Opportunity Trader
==========================================================
"""

from config import CANDLE_INTERVAL_SECONDS


def _bucket(tick_time):
    epoch = tick_time.timestamp()
    return int(epoch // CANDLE_INTERVAL_SECONDS)


class CandleEngine:

    def __init__(self):
        # symbol -> current open candle dict
        self._open_candle = {}
        # symbol -> list of closed candles (dicts)
        self._closed_candles = {}

    # --------------------------------------------------

    def update(self, symbol, price, tick_time):
        """
        Feed one tick. Returns the just-closed candle dict
        if this tick closed a candle, else None.
        """
        bucket = _bucket(tick_time)
        current = self._open_candle.get(symbol)

        if current is None:
            self._open_candle[symbol] = {
                "bucket": bucket,
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "time": tick_time,
            }
            return None

        if bucket == current["bucket"]:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["time"] = tick_time
            return None

        # New bucket -> previous candle just closed.
        closed = current
        self._closed_candles.setdefault(symbol, []).append(closed)

        self._open_candle[symbol] = {
            "bucket": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "time": tick_time,
        }

        return closed

    # --------------------------------------------------

    def last_closed(self, symbol):
        candles = self._closed_candles.get(symbol)
        if not candles:
            return None
        return candles[-1]
