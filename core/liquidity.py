"""
==========================================================
Which names are actually tradeable
==========================================================

    "what you want ? = One weakness I'll repeat rather than bury: ??"
                                    -- operator, 3 August 2026

Nothing, as it turns out. I said the fan-out's fallback ordering was
alphabetical because the master carries no size or liquidity column,
and that fixing it "needs another input". That was wrong, and it was
wrong in the way I have been wrong before: I described a gap without
first checking what was already on disk.

data/history_candles.db holds 19,120,781 minute candles across 788
symbols with a volume column on every row. Average daily traded value
is close x volume, summed. Five sessions of it:

    INFY        2,581 Cr/day        TCS         1,361 Cr/day
    HDFCBANK    2,118 Cr/day        M&M         1,251 Cr/day
    KALYANKJIL  1,876 Cr/day        COFORGE     1,223 Cr/day

Those are the names that should lead a sector list. Without this the
first seconds of a shock showed 63MOONS and AFFLE for IT, because
nothing was moving yet and the fallback sorted by alphabet.

WHY IT IS CACHED
----------------
The aggregate takes about six seconds over nineteen million rows. That
is fine once a night and impossible on a one-second dashboard refresh,
so it is computed after the close and read from a small JSON file.

A missing or stale file is not an error. spread() falls back to the
old alphabetical order, which is what it did before this existed.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import statistics
import sqlite3
import threading
import time

from core.logger import decision, diagnostic, warn

CANDLES_DB = os.path.join("data", "history_candles.db")
STORE_PATH = os.path.join("data", "liquidity.json")

# Five sessions. Enough that one frantic day in a small name does not
# promote it above a genuine large cap, short enough to notice a stock
# that has actually started trading.
# ---- FIVE SESSIONS IS NOT ENOUGH FOR A MEDIAN. 27 Aug 2026 ----
#
# A median only finds "normal" if normal is the majority of the
# window. QUADFUTURE ran for THREE days -- 21 Aug Rs 289cr, 24 Aug
# Rs 1,058cr, 25 Aug Rs 211cr -- against a real normal near Rs 10cr.
# Over five sessions the median of that is Rs 211cr: three-fifths of
# the window is the spike itself.
#
#     stock          5d      10d      20d      30d
#     QUADFUTURE  211.2     10.3     10.2     10.0
#     RATNAMANI    45.4      9.5      9.5      7.4
#     BALUFORGE   166.5    191.9     50.0     36.8
#     TVSSCS       24.4      6.6      5.9      4.7
#
# At 20 a run would need ELEVEN elevated days to move the median, and
# eleven days is not a spike -- it is a re-rating, which SHOULD move
# the number. The daily store holds 2,480 sessions, so depth costs
# nothing.
SESSIONS = 20

# How often the file is checked for changes. It is written once a
# night; adv() is called thousands of times inside a single sort.
STAT_EVERY_SECONDS = 5.0

_LOCK = threading.Lock()
_CACHE = None
_MTIME = None
_CHECKED = 0.0


def refresh(db_path=None, store_path=STORE_PATH, sessions=SESSIONS):
    """Compute average daily traded value and write it to disk.

    ---- IT WAS MEASURING A DEAD STORE. 4 August 2026. ----

    This read data/history_candles.db, whose ONLY writer is
    tools/fetch_history.py -- not the live session, not the nightly.
    So it ended on 31 July and stayed there. The operator ran
    measure_liquidity twice on 4 August and INFY came back at the
    identical 2,580.92 both times, because the underlying data had not
    moved in a week.

    That number is not decoration. It is the YASHO gate in
    core/ranker.py (MIN_LIQUIDITY_CR), the fallback ordering in the
    shock fan-out, and the watchlist tiebreak. A week-old measurement
    was quietly deciding what the bot is allowed to trade.

    DailyStore is the right source and was there all along:
      * tools/build_daily_history.py refreshes it every night from
        NSE's bhavcopy, so it is current to yesterday
      * it carries TURNOVER -- the exchange's own rupee value -- rather
        than close x volume summed over minute bars, which is an
        estimate at best and double-counts if the feed ever reports
        cumulative volume

    Returns how many symbols were measured. Never raises.
    """
    started = time.time()
    try:
        from sqlalchemy import select

        from core.daily_store import DailyStore

        store = DailyStore()
        days = sorted(store.dates())[-sessions:]
        if not days:
            warn("[LIQUIDITY] No sessions in the daily store. "
                 "Run py tools/build_daily_history.py first.")
            return 0

        bars = store.bars
        per_day = {}
        with store.engine.connect() as conn:
            for row in conn.execute(
                    select(bars.c.symbol, bars.c.date, bars.c.turnover,
                           bars.c.close, bars.c.volume)
                    .where(bars.c.date.in_(days))):
                symbol = (row.symbol or "").strip().upper()
                if not symbol:
                    continue
                value = row.turnover
                if value is None and row.close and row.volume:
                    value = float(row.close) * float(row.volume)
                if not value:
                    continue
                per_day.setdefault(symbol, []).append(
                    (str(row.date), float(value)))

        # ---- TODAY WAS INSIDE ITS OWN DENOMINATOR. 25 Aug 2026 ----
        #
        #     "whats this denominator error ?"      -- operator
        #
        # This was the MEAN of the last five sessions INCLUDING the one
        # being measured, so a stock that exploded today had its own
        # explosion averaged into what counts as normal:
        #
        #     LTFOODS   18-21 Aug  Rs 21cr a day
        #               24 Aug     Rs 1,968cr        <- in its own mean
        #               "normal"   Rs 410cr
        #               reads      4.8x     truth: 116x
        #
        # Every big mover on 24 August compressed to roughly the same
        # number -- LTFOODS 4.8x, QUADFUTURE 3.8x, TVSSCS 4.9x,
        # RATNAMANI 4.4x, VMM 4.0x -- because the spike dominates the
        # five-day mean it is then divided by. Which is why comparing
        # winners against losers found NO separation in volume_x
        # (2.83 vs 2.78): the instrument could not tell them apart.
        #
        # And it persisted. With 24 August in the window, LTFOODS reads
        # Rs 410cr as "normal" for five more sessions, so it cannot
        # look busy again all week however hard it trades.
        #
        # TWO CHANGES:
        #   MEDIAN, not mean -- one session cannot dominate.
        #   EXCLUDE THE LATEST DAY -- a stock is measured against the
        #   days BEFORE it, never against itself.
        #
        # Still divided by the sessions THIS stock actually traded, not
        # by the window: a name listed three days ago is not a
        # low-volume name.
        # Exclude the latest session ONLY when it is TODAY. The point
        # is that a stock must not be measured against its own spike
        # while that spike is happening. If the daily store is a day
        # or two behind -- on 27 August its newest was the 25th -- then
        # the 25th is ordinary history and dropping it would throw away
        # a real session for no reason.
        today = time.strftime("%Y-%m-%d")
        latest = max(days)
        drop = latest if latest == today else None
        rows = []
        for symbol, entries in per_day.items():
            values = [v for day, v in entries if day != drop]
            if not values:
                # Only today on file -- a new listing. Use what there
                # is rather than dropping it; UNMEASURED would hide it.
                values = [v for _, v in entries]
            if not values:
                continue
            rows.append((symbol, statistics.median(values) / 1e7))
    except Exception as exc:                                # noqa: BLE001
        warn(f"[LIQUIDITY] Could not measure ({exc}). The fan-out will "
             f"fall back to alphabetical order.")
        return 0

    data = {"sessions": days,
            "at": time.strftime("%Y-%m-%d %H:%M:%S"),
            # Crore per day. Rounded -- this decides an ORDER, and
            # storing fourteen decimal places of a five-day average
            # would imply a precision it does not have.
            "adv_cr": {symbol: round(value or 0.0, 2)
                       for symbol, value in rows if symbol}}
    try:
        os.makedirs(os.path.dirname(store_path) or ".", exist_ok=True)
        with open(store_path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
    except OSError as exc:
        warn(f"[LIQUIDITY] Could not write {store_path}: {exc}")
        return 0

    decision(f"[LIQUIDITY] {len(data['adv_cr'])} symbols measured over "
             f"{len(days)} session(s) in {time.time() - started:.1f}s.")
    return len(data["adv_cr"])


def _load(store_path=STORE_PATH):
    """Re-read only when the file has actually changed.

    ---- A STAT CALL PER LOOKUP IS NOT FREE. 3 August 2026. ----
    adv() is called from inside two SORT keys -- the watchlist and the
    sector fan-out. A sort over a few hundred rows asks thousands of
    times, and checking the file's mtime on every one of those turned a
    twenty-second test chunk into a timeout. The file is written once a
    night; asking the filesystem more than once every few seconds is
    pure waste.
    """
    global _CACHE, _MTIME, _CHECKED
    now = time.time()
    if _CACHE is not None and (now - _CHECKED) < STAT_EVERY_SECONDS:
        return _CACHE
    _CHECKED = now
    try:
        stamp = os.path.getmtime(store_path)
    except OSError:
        return {}
    with _LOCK:
        if _CACHE is None or stamp != _MTIME:
            try:
                with open(store_path, encoding="utf-8") as handle:
                    _CACHE = json.load(handle) or {}
                _MTIME = stamp
                diagnostic(f"[LIQUIDITY] Loaded "
                           f"{len(_CACHE.get('adv_cr') or {})} symbols.")
            except (OSError, ValueError) as exc:
                warn(f"[LIQUIDITY] {store_path} unreadable ({exc}).")
                _CACHE = {}
        return _CACHE


def reset():
    global _CACHE, _MTIME, _CHECKED
    with _LOCK:
        _CACHE, _MTIME, _CHECKED = None, None, 0.0


def adv(symbol, store_path=STORE_PATH):
    """Average daily traded value in crore, or 0.0 when unknown.

    Zero rather than None so it can be sorted on directly. An unmeasured
    stock sinks to the bottom of a fallback list, which is the right
    place for a name the bot has never seen trade.
    """
    table = (_load(store_path) or {}).get("adv_cr") or {}
    try:
        return float(table.get(str(symbol or "").strip().upper(), 0.0))
    except (TypeError, ValueError):
        return 0.0


def available(store_path=STORE_PATH):
    return bool((_load(store_path) or {}).get("adv_cr"))


def measured_at(store_path=STORE_PATH):
    return (_load(store_path) or {}).get("at")


def known(symbol, store_path=STORE_PATH):
    """Has the bot ever seen this stock trade?

    ---- THE YASHO QUESTION. 3 August 2026. ----

        "yasho - dual entries made loss"
        "yasho alone caused - 11.3K loss"

    Measured after the fact: YASHO has ZERO minute candles in
    data/history_candles.db and no traded value at all. The bot scored
    it, ranked it and put a BUY button on it while knowing nothing
    about how it trades.

    191 of the 946 tradeable names in the master are in that state.

    This is deliberately NOT a risk score or a size rule. At his Rs 1
    lakh cap even the thinnest MEASURED stock is 0.22% of a day's
    turnover, so size is not the problem and inventing a limit would be
    solving a fear rather than a fact. The problem is simpler and
    worth saying out loud: on those 191 names every number the bot
    shows him is an extrapolation from nothing.

        "never assume-give clarity on every item residing in bot"
    """
    return adv(symbol, store_path) > 0


def unknown_count(symbols, store_path=STORE_PATH):
    """How many of these the bot has never seen trade."""
    return sum(1 for s in (symbols or []) if not known(s, store_path))


def share_of_day(rupees, symbol, store_path=STORE_PATH):
    """A position as a percentage of one day's trading, or None.

    None means "we cannot say", which must never be drawn as "fine".
    """
    value = adv(symbol, store_path)
    if not value or not rupees:
        return None
    # Four decimals, not two. At Rs 1 lakh against INFY's 2,581 Cr a
    # day the honest answer is 0.0004% -- rounding that to 0.00 would
    # print a zero and read as "no data".
    return round(float(rupees) / (value * 1e7) * 100, 4)


def by_size(symbols, store_path=STORE_PATH):
    """Biggest first, then alphabetical so the order is stable.

    The table is read ONCE and the sort keys are built from it, rather
    than calling adv() inside the comparison -- see _load() for why
    that mattered.
    """
    table = (_load(store_path) or {}).get("adv_cr") or {}

    def size_of(symbol):
        try:
            return float(table.get(str(symbol or "").strip().upper(), 0.0))
        except (TypeError, ValueError):
            return 0.0

    return sorted(symbols, key=lambda s: (-size_of(s), s))
