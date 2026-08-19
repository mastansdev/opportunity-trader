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


# ==========================================================
#  DAILY VOLATILITY -- THE STOP'S CORRECT UNIT
# ==========================================================
#
#     "do not fix the 2.5% for every stock. as u suggested
#      volatility-scaled stop may be best suited option"
#                                 -- operator, 18 August 2026
#
# WHY THIS EXISTS SEPARATELY FROM compute_atr() ABOVE
# ---------------------------------------------------
# The engine already computes ATR -- on its own ONE-MINUTE candles,
# because that is what core/candle_engine.py holds. Measured against
# data/history_candles.db on 31 July:
#
#     symbol       1-min ATR(14)      0.8x stop      daily ATR(14)
#     NAVINFLUOR      0.34%             0.27%           3.46%
#     POLYCAB         0.23%             0.18%           1.79%
#     ICIL            0.23%             0.19%           4.99%
#     NEOGEN          0.62%             0.50%           4.14%
#
# So switching on the existing ATR stop path would have produced
# stops of a fifth of a percent -- TEN TIMES TIGHTER than the flat
# 2.5% it was meant to improve on, stopped out by the spread. The
# machinery was right and the timeframe was wrong, and nothing in the
# code said which timeframe it assumed.
#
# A stop answers "has this idea failed", and an idea has not failed
# because the stock moved less than it moves on an ordinary day. That
# is a DAILY question, so it is measured on daily bars.
#
# NO NETWORK, NO LIVE DEPENDENCY. This reads the bhavcopy store the
# nightly chain already fills. If the store cannot answer, the caller
# is told None and falls back to the flat number -- an entry must
# never wait on a database.

import os
import sqlite3

DAILY_DB = os.path.join("data", "daily_candles.db")

#: Bars behind the reading. 14 sessions is three trading weeks -- long
#: enough to survive one quiet day, short enough to notice that a
#: stock has woken up.
DAILY_ATR_PERIOD = 14

#: Nothing may be read from fewer than this. A two-bar "ATR" on a
#: freshly listed stock is a number, not a measurement.
MIN_DAILY_BARS = 10

_CACHE = {}


def reset_daily_cache():
    """Drop the per-session cache. For tests and for a new day."""
    _CACHE.clear()


def daily_atr_pct(symbol, db_path=DAILY_DB, period=DAILY_ATR_PERIOD,
                  as_of=None):
    """This stock's ordinary daily range, as a % of its price.

    Returns None when it cannot be measured -- never a default, never
    a zero. A caller that gets None must fall back to a rule it can
    name, because a stop derived from a made-up volatility is worse
    than an honestly flat one.

    Cached per (symbol, as_of): the answer changes once a day, and the
    entry path may ask several times a minute.
    """
    key = (str(symbol or "").upper(), str(as_of or ""), period)
    if not key[0]:
        return None
    if key in _CACHE:
        return _CACHE[key]

    value = None
    conn = None
    try:
        if os.path.exists(db_path):
            conn = sqlite3.connect("file:" + db_path + "?mode=ro", uri=True)
            sql = ("SELECT high, low, close FROM daily_bars "
                   "WHERE symbol = ?")
            params = [key[0]]
            if as_of:
                # Bounded so a replay of a past morning cannot read a
                # volatility that had not happened yet.
                sql += " AND date <= ?"
                params.append(str(as_of))
            sql += " ORDER BY date DESC LIMIT ?"
            params.append(period + 1)
            rows = conn.execute(sql, params).fetchall()
            value = _atr_pct_from(rows)
    except Exception:                                       # noqa: BLE001
        value = None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:                               # noqa: BLE001
                pass

    _CACHE[key] = value
    return value


def _atr_pct_from(rows):
    """rows are NEWEST first, each (high, low, close)."""
    if not rows or len(rows) < MIN_DAILY_BARS:
        return None
    bars = list(rows)[::-1]                 # oldest first
    ranges = []
    for previous, current in zip(bars, bars[1:]):
        try:
            high, low = float(current[0]), float(current[1])
            prev_close = float(previous[2])
        except (TypeError, ValueError):
            continue
        if high <= 0 or low <= 0:
            continue
        ranges.append(max(high - low, abs(high - prev_close),
                          abs(low - prev_close)))
    if not ranges:
        return None
    try:
        last_close = float(bars[-1][2])
    except (TypeError, ValueError):
        return None
    if last_close <= 0:
        return None
    return (sum(ranges) / len(ranges)) / last_close * 100.0

def scaled_stop_pct(symbol, mult, floor_pct, ceiling_pct, fallback_pct,
                    as_of=None):
    """This stock's own daily range x `mult`, bounded, as a PERCENT.

    ---- ONE DEFINITION, THREE CALLERS. 19 August 2026. ----

    core/engine.py sized the entry stop from the daily range on
    18 August and core/trailing_stop.py followed on the 19th. A third
    site was missed: core/position_plan.py, which decides whether a
    ranked pick can be sized AT ALL -- and therefore whether it ever
    reaches his phone.

    That site had its own rule, and it did not widen a stop, it
    REFUSED the trade:

        RAILTEL     score 30.68   structural stop 0.10%   ATR 2.08%
        KIRLOSBROS  score 17.95   structural stop 0.14%   ATR 3.72%

    Both were the day's best setups. Both were dropped because a
    day-low-derived stop sat a tenth of a percent below the entry --
    which is not a stop, it is noise -- and the answer to a bad stop
    level is a better stop, not a discarded opportunity.

    Everything scaling a distance to a stock now comes through here,
    so the three cannot drift onto different ideas of how much a stock
    moves. `fallback_pct` is returned whenever the range cannot be
    measured: a distance derived from a volatility nobody measured is
    worse than an honestly flat one.
    """
    try:
        daily = daily_atr_pct(symbol, as_of=as_of)
    except Exception:                                       # noqa: BLE001
        daily = None
    if not daily or daily <= 0:
        return float(fallback_pct)
    wanted = float(mult) * float(daily)
    return max(float(floor_pct), min(float(ceiling_pct), wanted))
