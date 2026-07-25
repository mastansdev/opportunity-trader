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

    def update(self, symbol, price, tick_time, cum_volume=None):
        """
        Feed one tick. Returns the just-closed candle dict
        if this tick closed a candle, else None.

        cum_volume (2026-07-24 Change 2) is the DAY-CUMULATIVE traded
        volume reported by the feed's Quote mode (day total so far),
        or None in Ticker mode / when unavailable. A candle's own
        "volume" is derived as the delta between its first and last
        cumulative reading. It stays None whenever any part of that
        can't be computed -- the volume filter treats None as
        "unknown" and fails open, never blocking a trade.
        """
        bucket = _bucket(tick_time)
        current = self._open_candle.get(symbol)

        if current is None:
            self._open_candle[symbol] = self._new_candle(bucket, price, tick_time, cum_volume)
            return None

        if bucket == current["bucket"]:
            current["high"] = max(current["high"], price)
            current["low"] = min(current["low"], price)
            current["close"] = price
            current["time"] = tick_time
            if cum_volume is not None:
                if current["_cum_open"] is None:
                    current["_cum_open"] = cum_volume
                current["_cum_last"] = cum_volume
            return None

        # New bucket -> previous candle just closed. Finalise its own
        # volume from the cumulative readings seen inside it.
        closed = current
        if closed["_cum_open"] is not None and closed["_cum_last"] is not None:
            vol = closed["_cum_last"] - closed["_cum_open"]
            closed["volume"] = vol if vol >= 0 else None
        self._closed_candles.setdefault(symbol, []).append(closed)

        self._open_candle[symbol] = self._new_candle(bucket, price, tick_time, cum_volume)

        return closed

    @staticmethod
    def _new_candle(bucket, price, tick_time, cum_volume):
        return {
            "bucket": bucket,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "time": tick_time,
            "volume": None,          # finalised on close (see update())
            "_cum_open": cum_volume,  # cumulative at first tick, internal
            "_cum_last": cum_volume,  # cumulative at last tick, internal
        }

    # --------------------------------------------------

    def last_closed(self, symbol):
        candles = self._closed_candles.get(symbol)
        if not candles:
            return None
        return candles[-1]

    def last_n_closed(self, symbol, n):
        """
        Up to the last `n` closed candles for symbol, OLDEST FIRST
        (core/atr.py's compute_atr() expects this order to chain
        prev_close correctly). Returns fewer than n if fewer exist
        yet -- never pads with fake candles -- and [] if none exist
        at all. Added 2026-07-24 for ATR sizing (item 3 of the
        redesign): by the earliest a structural signal can fire
        (right after ORB_WINDOW_END), a normally-ticking symbol
        already has ~15 one-minute candles, comfortably enough for a
        14-period ATR; thin/illiquid symbols with fewer real candles
        get whatever's here, and the caller (core/engine.py) decides
        whether that's enough via config.MIN_ATR_CANDLES.
        """
        candles = self._closed_candles.get(symbol)
        if not candles:
            return []
        return candles[-n:]
