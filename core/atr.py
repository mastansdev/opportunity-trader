"""
==========================================================
ATR -- Average True Range (pure logic, no I/O)
==========================================================

Item 3 of the 2026-07-23 post-market redesign, operator's own
real-trading insight: "we do not treat all stocks same, the
movement of the stock under 200 rs is very different to above
2000 rs... we need more info about the price movement itself."
ATR is that "more info" -- a stock's own typical candle-to-candle
range, in rupees, not a percentage and not a guess.

True Range (TR) for one candle is the largest of:
    high - low
    abs(high - prev_close)
    abs(low - prev_close)
(the second and third cases catch gaps -- a candle that opens
sharply away from the previous close moved further than its own
high-low would suggest.) The first candle in any series has no
prev_close, so TR is just high - low for it.

ATR is the simple average of TR over the last `period` candles.
Deliberately a plain average, not Wilder's smoothing -- this bot
computes ATR fresh from THIS SESSION's own 1-minute candles
(core/candle_engine.py), not a long historical daily series, so
there's no multi-day smoothing state to carry forward anyway; a
plain rolling average over whatever's in the window is simpler
and just as valid for a short intraday window.

Author : H&M Opportunity Trader
==========================================================
"""


def true_range(candle, prev_close=None):
    """
    candle : dict with "high" and "low" keys (any of this
             codebase's candle dicts qualify).
    prev_close : the PREVIOUS closed candle's "close", or None
             for the very first candle in a series.

    Returns the true range for this one candle, in rupees.
    """
    high = candle["high"]
    low = candle["low"]

    if prev_close is None:
        return high - low

    return max(
        high - low,
        abs(high - prev_close),
        abs(low - prev_close),
    )


def compute_atr(candles, period):
    """
    candles : list of closed candle dicts, OLDEST FIRST (the same
              order core/candle_engine.py's last_n_closed() returns
              them in). Callers should pass period + 1 candles when
              available -- the extra, oldest one is used ONLY to
              give the first counted candle a real prev_close (so
              gap moves into the window are caught too), it never
              contributes its own TR to the average. Pass fewer and
              whatever's there is used (caller decides whether
              that's enough via MIN_ATR_CANDLES, this function never
              refuses to compute on a short list); pass more and the
              extras beyond period+1 are ignored.

    Returns the average true range over the window, or None if
    `candles` is empty -- never a fake/default number silently
    stood in for a real reading.
    """
    if not candles:
        return None

    window = candles[-(period + 1):]

    if len(window) == 1:
        # No prior candle at all -- nothing to compare against for
        # a gap, TR degrades to this one candle's own high - low.
        return true_range(window[0])

    true_ranges = [
        true_range(window[i], prev_close=window[i - 1]["close"])
        for i in range(1, len(window))
    ]
    return sum(true_ranges) / len(true_ranges)
