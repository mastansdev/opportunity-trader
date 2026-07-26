"""
==========================================================
History Fetch -- years of real market, from Dhan
==========================================================

WHY THIS EXISTS
---------------
As of 2026-07-26 the replay bench (backtest/monday_replay.py) runs the
bot's REAL rules -- top-20 movers, top-8 sectors, RS band, staged seats,
rotation, ATR stops, charges -- over exactly ONE recorded session, and
that one was restart-muddied. Every open question in POST_MONDAY_TODO
(does riding strength work or fading it; is the RS band right; do the
staged seats ever bind; is +0.17R real) is unanswerable for one reason:
not enough market.

Dhan already serves the missing data, and we already hold the
credentials:

    POST /v2/charts/intraday    1/5/15/25/60-min candles, LAST 5 YEARS,
                                all active instruments.
                                *** max 90 days per request ***
    POST /v2/charts/historical  daily candles, back to INCEPTION.
                                no window limit.

Data-API rate limit is 5 requests/second and 100,000/day, so the whole
subscribed universe is minutes of wall clock, not hours:

    62 trading days x 545 symbols  =    545 requests  (~2 min)
     1 year         x 545 symbols  =  2,725 requests  (~10 min)
     5 years        x 545 symbols  = 13,600 requests  (~45 min)

The API is not the bottleneck. Disk is: 545 symbols x 375 minutes x 62
sessions is ~12.7 million 1-minute bars.

WHAT THIS MODULE IS AND IS NOT
------------------------------
It is a PURE-ish fetcher: given a caller-supplied `post` function it
turns Dhan's columnar response into the row shape our stores already
use. All the parsing, chunking, epoch->IST conversion and validation is
testable with no network and no credentials -- which matters, because
the last four times we wrote a parser against a feed we had not actually
looked at, it took four attempts (see CALENDAR_AND_RESULTS.md).

It does NOT decide anything, does NOT touch the live trading path, and
is never imported by main.py or core/engine.py.

TWO THINGS TO VERIFY BEFORE TRUSTING THE OUTPUT
-----------------------------------------------
1. SPLIT ADJUSTMENT. It is not documented whether Dhan's historical
   candles are adjusted for splits/bonuses. If they are NOT, a 1:10
   split mid-history reads as a -90% bar and poisons every ORB range
   and ATR around it. `suspect_price_jumps()` below flags the candidates
   so they can be checked against core/stock_memory.py's 141 recorded
   corporate actions BEFORE any backtest is believed.

2. SURVIVORSHIP. master_stocks.csv is TODAY'S universe. Pulling two
   years of it silently excludes everything delisted in between and
   includes names that only became liquid recently. That biases results
   upward. Real, modest for intraday ORB, and worth stating in any
   result that comes out of this data.

Author : H&M Opportunity Trader
==========================================================
"""

import time
from datetime import datetime, timedelta, timezone

from core.logger import warn

# Dhan v2 data endpoints.
INTRADAY_URL = "https://api.dhan.co/v2/charts/intraday"
DAILY_URL = "https://api.dhan.co/v2/charts/historical"

# Documented ceiling: "only 90 days of data can be polled at once".
MAX_INTRADAY_WINDOW_DAYS = 90

# Documented Data-API limit is 5/sec. We ask for 4 to leave headroom for
# the live bot if this is ever run while something else is polling.
REQUESTS_PER_SECOND = 4.0

# NSE equities trade 09:15-15:30 IST. Anything outside that in a
# response is either a pre-open print or junk, and must not become a
# candle -- an 09:07 bar would corrupt the 09:15-09:30 opening range,
# which is the one thing the entire strategy is built on.
SESSION_START = (9, 15)
SESSION_END = (15, 30)

IST = timezone(timedelta(hours=5, minutes=30))


# ----------------------------------------------------------
# Response parsing -- the part that must be right
# ----------------------------------------------------------

def _columns(payload):
    """
    Dhan returns COLUMNAR arrays, not a list of candles:

        {"open": [...], "high": [...], "low": [...], "close": [...],
         "volume": [...], "timestamp": [...]}

    Returns the six arrays, or None if the payload is not that shape.
    Any length mismatch is fatal-for-this-symbol rather than silently
    zipped short: mismatched arrays mean we are reading the wrong thing,
    and quietly truncating would hide it.
    """
    if not isinstance(payload, dict):
        return None
    required = ("open", "high", "low", "close", "timestamp")
    if any(not isinstance(payload.get(k), list) for k in required):
        return None
    # The price arrays and the timestamps must agree in length. If they
    # don't we are reading the wrong thing, and zipping to the shortest
    # would silently mis-date every candle after the mismatch.
    if len({len(payload[k]) for k in required}) != 1:
        return None
    # Volume is the one column allowed to be short or absent -- some
    # segments don't report it, and a missing volume costs us the
    # volume-surge filter, not the candle.
    volume = payload.get("volume")
    if not isinstance(volume, list):
        volume = []
    return [payload["open"], payload["high"], payload["low"],
            payload["close"], volume, payload["timestamp"]]


def _ist(epoch):
    """Epoch seconds -> IST datetime. Dhan stamps candles in epoch."""
    return datetime.fromtimestamp(int(epoch), tz=IST)


def in_session(dt):
    """True if this IST timestamp is inside NSE equity trading hours."""
    hm = (dt.hour, dt.minute)
    return SESSION_START <= hm <= SESSION_END


def parse_intraday(payload, symbol, session_only=True):
    """
    Dhan intraday response -> rows for backtest/candle_store.py:

        {date, symbol, minute, o, h, l, c, v}

    `minute` is the ISO timestamp to the minute, matching what the live
    recorder writes, so historical and recorded bars land in the same
    table and dedup against each other correctly.

    Returns [] on any malformed payload -- never raises. A bad symbol
    must cost that symbol, not the whole 545-symbol run.
    """
    cols = _columns(payload)
    if cols is None:
        return []
    o, h, l, c, v, ts = cols

    rows = []
    for i, stamp in enumerate(ts):
        try:
            dt = _ist(stamp)
        except (TypeError, ValueError, OSError):
            continue
        if session_only and not in_session(dt):
            continue
        try:
            row = dict(
                date=dt.strftime("%Y-%m-%d"),
                symbol=symbol,
                minute=dt.strftime("%Y-%m-%dT%H:%M:00"),
                o=float(o[i]), h=float(h[i]),
                l=float(l[i]), c=float(c[i]),
                v=float(v[i]) if i < len(v) and v[i] is not None else None,
            )
        except (TypeError, ValueError, IndexError):
            continue
        # A candle whose high is below its low, or whose open sits
        # outside [low, high], is broken data, not a quiet market.
        if row["h"] < row["l"]:
            continue
        if not (row["l"] <= row["o"] <= row["h"]):
            continue
        if not (row["l"] <= row["c"] <= row["h"]):
            continue
        rows.append(row)
    return rows


def parse_daily(payload, symbol):
    """
    Dhan daily response -> rows for core/daily_store.py:

        {date, symbol, series, open, high, low, close, volume}

    `series` is set to "EQ" because that is what we asked for and what
    DailyStore's bhavcopy path stores; prev_close and turnover are left
    None (Dhan does not return them, and nothing reads them for trend
    structure).
    """
    cols = _columns(payload)
    if cols is None:
        return []
    o, h, l, c, v, ts = cols

    rows = []
    for i, stamp in enumerate(ts):
        try:
            dt = _ist(stamp)
            rows.append(dict(
                date=dt.strftime("%Y-%m-%d"),
                symbol=symbol,
                series="EQ",
                open=float(o[i]), high=float(h[i]),
                low=float(l[i]), close=float(c[i]),
                prev_close=None,
                volume=float(v[i]) if i < len(v) and v[i] is not None else None,
                turnover=None,
            ))
        except (TypeError, ValueError, IndexError, OSError):
            continue
    return [r for r in rows if r["high"] >= r["low"]]


# ----------------------------------------------------------
# Request planning
# ----------------------------------------------------------

def window_chunks(from_date, to_date, max_days=MAX_INTRADAY_WINDOW_DAYS):
    """
    Split a date range into <= max_days slices, because the intraday
    endpoint refuses anything wider.

    Both bounds are `date` objects; returns [(from, to), ...] oldest
    first, contiguous and non-overlapping.
    """
    if to_date < from_date:
        return []
    out = []
    start = from_date
    step = timedelta(days=max(1, max_days) - 1)
    while start <= to_date:
        end = min(start + step, to_date)
        out.append((start, end))
        start = end + timedelta(days=1)
    return out


def intraday_body(security_id, from_dt, to_dt, interval="1"):
    """The request JSON. Kept separate so a test can assert its shape
    without a network call."""
    return {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "interval": str(interval),
        "oi": False,
        "fromDate": from_dt.strftime("%Y-%m-%d %H:%M:%S"),
        "toDate": to_dt.strftime("%Y-%m-%d %H:%M:%S"),
    }


def daily_body(security_id, from_date, to_date):
    return {
        "securityId": str(security_id),
        "exchangeSegment": "NSE_EQ",
        "instrument": "EQUITY",
        "expiryCode": 0,
        "oi": False,
        "fromDate": from_date.strftime("%Y-%m-%d"),
        "toDate": to_date.strftime("%Y-%m-%d"),
    }


class RateLimiter:
    """Dead simple: never issue more than `per_second` requests a second.

    Dhan's Data-API limit is 5/sec; being throttled mid-run would leave
    a half-populated database that looks complete, which is worse than
    being slow.
    """

    def __init__(self, per_second=REQUESTS_PER_SECOND, sleep=time.sleep,
                 clock=time.monotonic):
        self.min_gap = 1.0 / max(0.01, per_second)
        self._sleep = sleep
        self._clock = clock
        self._last = None

    def wait(self):
        now = self._clock()
        if self._last is not None:
            gap = now - self._last
            if gap < self.min_gap:
                self._sleep(self.min_gap - gap)
        self._last = self._clock()


# ----------------------------------------------------------
# The fetcher
# ----------------------------------------------------------

class HistoryFetcher:
    """
    `post` is injected: post(url, json_body) -> parsed dict. Real callers
    pass a requests-backed function; tests pass a fake. That is the whole
    reason this class exists rather than a script -- so the parsing can
    be proven without credentials.
    """

    def __init__(self, post, limiter=None, retries=2, sleep=time.sleep):
        self.post = post
        self.limiter = limiter or RateLimiter()
        self.retries = retries
        self._sleep = sleep
        self.requests_made = 0
        self.failures = []

    def _call(self, url, body, label):
        for attempt in range(self.retries + 1):
            self.limiter.wait()
            try:
                self.requests_made += 1
                return self.post(url, body)
            except Exception as exc:            # noqa: BLE001 -- fail open
                if attempt >= self.retries:
                    warn(f"[HISTORY] {label} failed after "
                         f"{self.retries + 1} tries: {exc}")
                    self.failures.append((label, str(exc)))
                    return None
                self._sleep(1.0 + attempt)
        return None

    def intraday(self, security_id, symbol, from_date, to_date,
                 interval="1"):
        """Every 1-minute bar for one symbol across a date range,
        automatically split into <=90-day requests."""
        rows = []
        for start, end in window_chunks(from_date, to_date):
            body = intraday_body(
                security_id,
                datetime.combine(start, datetime.min.time()).replace(
                    hour=SESSION_START[0], minute=SESSION_START[1]),
                datetime.combine(end, datetime.min.time()).replace(
                    hour=SESSION_END[0], minute=SESSION_END[1]),
                interval=interval,
            )
            payload = self._call(INTRADAY_URL, body,
                                 f"{symbol} {start}..{end}")
            if payload:
                rows.extend(parse_intraday(payload, symbol))
        return rows

    def daily(self, security_id, symbol, from_date, to_date):
        """Daily bars -- one request, no window limit."""
        payload = self._call(DAILY_URL,
                             daily_body(security_id, from_date, to_date),
                             f"{symbol} daily")
        return parse_daily(payload, symbol) if payload else []


# ----------------------------------------------------------
# The split check -- read the docstring at the top of this file
# ----------------------------------------------------------

def suspect_price_jumps(daily_rows, threshold_pct=25.0):
    """
    Day-on-day close moves larger than `threshold_pct`, which on NSE
    equities almost always means an unadjusted corporate action rather
    than a real move (the widest normal band is 20%, and a stock at its
    circuit simply stops trading).

    Returns [{symbol, date, prev_close, close, pct}] so the caller can
    cross-check against core/stock_memory.py before believing anything
    the backtest says. JLHL's 2:10 split read as -80% in the bhavcopy;
    the same thing here would silently invent an ORB gap of a lifetime.
    """
    out = []
    by_symbol = {}
    for r in daily_rows:
        by_symbol.setdefault(r["symbol"], []).append(r)
    for symbol, rows in by_symbol.items():
        rows = sorted((r for r in rows if r.get("close")),
                      key=lambda r: r["date"])
        for prev, cur in zip(rows, rows[1:]):
            if not prev["close"]:
                continue
            pct = (cur["close"] - prev["close"]) / prev["close"] * 100.0
            if abs(pct) >= threshold_pct:
                out.append(dict(symbol=symbol, date=cur["date"],
                                prev_close=prev["close"],
                                close=cur["close"], pct=pct))
    return sorted(out, key=lambda r: -abs(r["pct"]))
