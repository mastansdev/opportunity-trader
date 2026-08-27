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

    def close_open_candles(self):
        """Finalise every still-open candle and return them.

        =====================================================
        2026-07-29 -- the last minutes of every day were lost
        =====================================================
        A candle closes only when a tick from the NEXT minute arrives.
        At the end of the session there is no next tick, so whatever
        was open simply vanished. The operator's own check found it:
        across all 666 symbols the last recorded candle on 29 July was
        15:27, though the market trades to 15:30.

        Consequence: the bot's "last price" was the 15:27 close, not
        the real one. Checked against Dhan's close on six names the gap
        ran from Rs 0.25 to Rs 21.60 -- small, but it is the number the
        day's P&L and tomorrow's reference are read from.

        Called once at shutdown. Returns [(symbol, candle), ...] so the
        caller can record them; the engine's own closed-candle history
        is updated either way.
        """
        finalised = []
        for symbol, candle in list(self._open_candle.items()):
            if candle is None:
                continue
            if candle["_cum_open"] is not None \
                    and candle["_cum_last"] is not None:
                volume = candle["_cum_last"] - candle["_cum_open"]
                candle["volume"] = volume if volume >= 0 else None
            self._closed_candles.setdefault(symbol, []).append(candle)
            finalised.append((symbol, candle))
            self._open_candle[symbol] = None
        return finalised

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

    def vwap(self, symbol):
        """Volume-weighted average price for this session, or None.

        ---- IT WAS READ AND NEVER WRITTEN. 27 August 2026 ----

        core/ranker.py's liveness() has asked for row["vwap"] since it
        was written -- "below VWAP on a long means the average buyer
        today is under water, that is not a stock to be joining" --
        and NOTHING anywhere set that key. It appears zero times in
        the live snapshot. The guard reads `if vwap and ltp:` so it
        degraded quietly rather than raising, and one of the three
        signals deciding alive-vs-fading has never fired.

        Same class as position.get("stop") printing None for three
        protected positions: a field read from a shape that does not
        carry it.

            VWAP = sum(typical price x volume) / sum(volume)
            typical price = (high + low + close) / 3

        Computed over THIS SESSION'S closed candles, which is the
        definition -- VWAP resets each day. Candle volume is already
        the per-minute delta (see update()), not a cumulative figure,
        so these sum correctly.

        None when nothing has volume yet: a session with no volume has
        no volume-weighted price, and returning the plain average
        would be inventing one.
        """
        candles = self._closed_candles.get(symbol)
        if not candles:
            return None
        weighted = 0.0
        total = 0.0
        for candle in candles:
            volume = candle.get("volume")
            if not volume or volume <= 0:
                continue
            high = candle.get("high")
            low = candle.get("low")
            close = candle.get("close")
            if high is None or low is None or close is None:
                continue
            typical = (float(high) + float(low) + float(close)) / 3.0
            weighted += typical * float(volume)
            total += float(volume)
        if total <= 0:
            return None
        return weighted / total

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
