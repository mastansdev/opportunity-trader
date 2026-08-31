"""
==========================================================
Order Flow -- who was in a hurry, minute by minute
==========================================================

    "my point is not make universal timing . i'm saying you that by
     volume , order flow which carries the buyer & seller will give
     us info"                            -- operator, 29 August 2026

He is asking a question the bot cannot answer, and the reason it
cannot is that the answer arrives on every tick and is thrown away.

WHAT THE BOT ALREADY KNOWS, AND WHAT IT DOES NOT
------------------------------------------------
core/ranker.volume_ratio() measures HOW MUCH traded against this
stock's own normal for the time of day. That is a real reading and it
is already a hard gate.

It says nothing about WHO. A stock trading 5x its normal volume is
either being accumulated or distributed, and turnover reads the same
either way. His claim is that the buyer/seller split turns BEFORE the
price does -- and on 28 August PRECWIRE is exactly the shape of it:

    09:15 - 11:30    +1.5% to +2.4%     1.1x - 1.4x volume
    11:45            +3.0%              1.4x
    12:00            +5.6%              2.3x     <- it starts
    12:15            +8.2%              4.6x
    12:29           +16.4%             19.0x
    13:55            locked at the high
    close           +20.0%             upper circuit

The only stored reason arrived at 12:24 -- a Telegram card recycling
a preferential-issue filing published the previous evening, by which
time the stock was already +8%. Whatever was happening at 11:50 was
happening in the book, and nobody kept it.

WHY THIS IS A RECORDER AND NOT A SIGNAL
---------------------------------------
Because I measured his idea the cheap way first and it did not hold:
across 1,049 stock-days that crossed +3% on volume with no reason the
bot knew of, the result was -Rs 30,664, and splitting by the SIZE of
the surge showed no pattern (10-20x best, 20x+ negative -- noise).

But that measured turnover, not composition. It does not touch what
he actually said. His question is untested, and it is untestable
against anything stored today, which is the whole reason this file
exists. Nothing here reaches a decision. It writes.

The rule this bot keeps learning the hard way -- most recently this
morning, when a fade exit built on ranker.liveness() sounded right
and measured -Rs 24,000 against simply holding -- is that an idea
gets wired in AFTER it is measured, not before.

HOW THE SIDE IS DECIDED, AND HOW WRONG THAT CAN BE
--------------------------------------------------
Dhan's Quote packet carries LTQ (last traded quantity) but not an
aggressor flag: it does not say whether that trade lifted the offer
or hit the bid. So the side is inferred by the TICK RULE -- price up
from the previous print is a buy, down is a sell, unchanged inherits
the last direction. That is the Lee-Ready fallback every retail
platform uses, and it is right roughly 75-80% of the time. It
degrades in fast markets, which is precisely where this bot trades.

So the honest reading is recorded beside it rather than hidden:

    ltq_sum    the quantity this file actually saw and classified
    vol_delta  what the exchange's cumulative volume moved by

If ltq_sum is far below vol_delta the feed coalesced prints and the
delta is a SAMPLE, not the flow. Any measurement done on this data
later has to check that ratio first, or it will be measuring the
feed's throttling and calling it order flow.

True classification needs the best bid/ask beside each print, which
means Dhan's Full packet (5-level depth) instead of Quote. That is a
bigger change and it waits on whether this cheap version shows
anything at all.

RESTING BOOK IS NOT TRADED FLOW
-------------------------------
book_buy / book_sell are total_buy_quantity / total_sell_quantity --
the aggregate size RESTING on each side. Resting orders can be
pulled and often are. Kept because they are free and because the
comparison between what was resting and what actually traded is
itself a reading. They are a different thing from delta and must
never be added to it.
"""

from datetime import datetime
import os
import sqlite3
import threading

from core.logger import diagnostic, warn

DB_PATH = os.path.join("data", "order_flow.db")

# One row per symbol per minute. UNIQUE keeps a restart mid-session
# from doubling a minute it already wrote.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS flow_minutes (
    id         INTEGER PRIMARY KEY,
    date       TEXT NOT NULL,
    minute     TEXT NOT NULL,
    symbol     TEXT NOT NULL,
    ticks      INTEGER NOT NULL,
    book_ticks INTEGER,
    up_qty     REAL,
    down_qty   REAL,
    flat_qty   REAL,
    delta      REAL,
    ltq_sum    REAL,
    vol_delta  REAL,
    book_buy   REAL,
    book_sell  REAL,
    skew_pct   REAL,
    ltp        REAL,
    atp        REAL,
    UNIQUE(date, minute, symbol)
);
CREATE INDEX IF NOT EXISTS idx_flow_day_symbol
    ON flow_minutes(date, symbol);
"""

_lock = threading.Lock()
_open = {}        # symbol -> the minute being filled
_done = []        # completed minutes waiting to be written
_last_px = {}     # symbol -> last LTP seen, for the tick rule
_last_dir = {}    # symbol -> last non-flat direction, for unchanged prints
_stats = {"observed": 0, "written": 0, "dropped": 0}

# A minute that never closes is a minute that never gets written. If
# a stock stops ticking at 11:04 its 11:04 bucket sits open until the
# session ends, so flush() closes anything older than this.
STALE_MINUTES = 2


def _in_session(when):
    """Is this moment inside continuous trading?

    config.MARKET_OPEN / MARKET_CLOSE own the times so this cannot
    drift from the rest of the bot. Fails OPEN -- an unreadable clock
    must not silently stop the recorder for a whole session; a missing
    filter costs some pre-open rows, a broken one costs the day.
    """
    try:
        from config import MARKET_OPEN, MARKET_CLOSE
        hhmm = when.strftime("%H:%M")
        return str(MARKET_OPEN) <= hhmm <= str(MARKET_CLOSE)
    except Exception:                                      # noqa: BLE001
        return True


def _num(value):
    try:
        got = float(value)
    except (TypeError, ValueError):
        return None
    return None if got != got else got


_session = {}     # symbol -> the day's running totals, for pressure()


def _roll_into_session(held):
    """Fold a finished minute into the day's running total. Caller
    holds the lock."""
    day = _session.get(held["symbol"])
    if day is None or day["date"] != held["date"]:
        day = {"date": held["date"], "buy": 0.0, "sell": 0.0,
               "ticks": 0, "book_ticks": 0}
        _session[held["symbol"]] = day
    day["buy"] += held["up_qty"]
    day["sell"] += held["down_qty"]
    day["ticks"] += held["ticks"]
    day["book_ticks"] += held.get("book_ticks", 0)


def _blank(symbol, date, minute):
    return {"date": date, "minute": minute, "symbol": symbol, "ticks": 0,
            "book_ticks": 0,
            "up_qty": 0.0, "down_qty": 0.0, "flat_qty": 0.0, "ltq_sum": 0.0,
            "vol_first": None, "vol_last": None, "book_buy": None,
            "book_sell": None, "ltp": None, "atp": None}


def observe(symbol, message, now=None):
    """Fold one Quote packet into this symbol's current minute.

    O(1), no I/O, never raises. This runs on the websocket thread for
    every tick of every subscribed stock -- roughly 1,300 of them --
    so anything slow here is felt by the whole feed.

    Returns the bucket it closed, if this tick rolled the minute over.
    """
    if not symbol:
        return None
    try:
        symbol = str(symbol).upper()
        now = now or datetime.now()
        date = now.strftime("%Y-%m-%d")
        minute = now.strftime("%H:%M")

        # ==========================================================
        # THE SESSION, AND NOTHING OUTSIDE IT.  31 August 2026.
        # ==========================================================
        #
        #     "something is issue with time. today: going up since
        #      08:30 (still settling)"          -- the operator
        #
        # He caught it on the board: a shape reading anchored at 08:30,
        # forty-five minutes before the market opens.
        #
        # core/market_data.py drops pre-market ticks and says so in the
        # log. This recorder never did -- it rejected a zero price and
        # nothing else -- so it wrote a row for every quote that
        # arrived, whenever it arrived. Measured on 31 August, before
        # the fix:
        #
        #     07:58   1,288 symbols   1 tick each   delta 0
        #     08:30   1,288 symbols   1 tick each   delta 0
        #     09:00   1,288 symbols  54.7 each      delta +49,45,294
        #     09:15   1,288 symbols  50.0 each      delta  +7,32,969
        #
        # 12,829 rows before the open. The 07:58 and 08:30 rows are
        # startup snapshots -- one quote per symbol, delta zero,
        # harmless to the arithmetic but they become BLOCKS in
        # core/intraday_shape.py, which is what put "since 08:30" on
        # his screen.
        #
        # 09:00-09:14 is worse and invisible: that is the PRE-OPEN
        # AUCTION, not trading, and its delta was SEVEN TIMES the whole
        # of 09:15. Every cumulative-delta figure on the board carried
        # it, and the divergence read would have been computed off it.
        #
        # A tick outside the session is not a trade. It is not recorded.
        if not _in_session(now):
            return None

        ltp = _num(message.get("LTP"))
        ltq = _num(message.get("LTQ"))
        volume = _num(message.get("volume"))
        buy = _num(message.get("total_buy_quantity"))
        sell = _num(message.get("total_sell_quantity"))
        atp = _num(message.get("avg_price"))

        if ltp is None or ltp <= 0:
            return None                       # pre-open, nothing traded

        closed = None
        with _lock:
            held = _open.get(symbol)
            if held is not None and (held["minute"] != minute
                                     or held["date"] != date):
                _done.append(held)
                _roll_into_session(held)
                closed = held
                held = None
            if held is None:
                held = _blank(symbol, date, minute)
                _open[symbol] = held

            # ---- THE BOOK DECIDES, IF THE BOOK IS THERE ----
            #      29 August 2026.
            #
            #     "no thats not the way order flow is used"
            #     "it is used on same day"              -- operator
            #
            # He is right twice over. Delta is not "did the price tick
            # up" -- it is "did this trade LIFT THE OFFER or HIT THE
            # BID". That needs the best bid and ask beside the print,
            # which a Quote packet does not carry and a FULL packet
            # does: depth[0] is the top of book.
            #
            # Dhan's own order-flow terminal (DEXT T3) reads exactly
            # this, live, inside each candle -- buy vs sell volume,
            # delta, imbalance. Same day. Nothing about it is mined
            # from history.
            #
            # So when depth arrives the side is KNOWN, and the tick
            # rule below is only the fallback for a Quote packet. Which
            # of the two answered is counted, because a delta built
            # from inference and one built from the book are not the
            # same number and a later reader must be able to tell.
            side = None
            book = message.get("depth")
            if book:
                try:
                    top = book[0]
                    bid = _num(top.get("bid_price"))
                    ask = _num(top.get("ask_price"))
                    if ask and ltp >= ask:
                        side = 1          # lifted the offer
                    elif bid and ltp <= bid:
                        side = -1         # hit the bid
                    elif bid and ask:
                        side = 0          # inside the spread, unknowable
                    if side is not None:
                        held["book_ticks"] += 1
                except Exception:                          # noqa: BLE001
                    side = None

            # ---- THE TICK RULE ----
            # Up from the last print is a buy, down is a sell. A print
            # at the SAME price inherits the last direction rather than
            # being discarded -- an unchanged print at the offer is
            # still a buy, and dropping them would bias the delta
            # towards whichever side happened to move the price.
            previous = _last_px.get(symbol)
            size = ltq if (ltq is not None and ltq > 0) else 0.0
            if side is not None:
                # The book answered. No inference needed.
                bucket = ("up_qty" if side > 0
                          else "down_qty" if side < 0 else "flat_qty")
                if side:
                    _last_dir[symbol] = side
            elif previous is None or ltp == previous:
                direction = _last_dir.get(symbol, 0)
                bucket = ("up_qty" if direction > 0
                          else "down_qty" if direction < 0 else "flat_qty")
            elif ltp > previous:
                _last_dir[symbol] = 1
                bucket = "up_qty"
            else:
                _last_dir[symbol] = -1
                bucket = "down_qty"
            held[bucket] += size
            held["ltq_sum"] += size
            _last_px[symbol] = ltp

            held["ticks"] += 1
            held["ltp"] = ltp
            if atp is not None:
                held["atp"] = atp
            if buy is not None:
                held["book_buy"] = buy
            if sell is not None:
                held["book_sell"] = sell
            if volume is not None:
                if held["vol_first"] is None:
                    held["vol_first"] = volume
                held["vol_last"] = volume
            _stats["observed"] += 1
        return closed
    except Exception as exc:                              # noqa: BLE001
        # A recorder must never be able to break the feed it rides on.
        _stats["dropped"] += 1
        return None


def _row(held):
    up, down = held["up_qty"], held["down_qty"]
    book_buy, book_sell = held["book_buy"], held["book_sell"]
    skew = None
    if book_buy is not None and book_sell is not None \
            and (book_buy + book_sell) > 0:
        skew = round((book_buy - book_sell)
                     / (book_buy + book_sell) * 100.0, 2)
    vol_delta = None
    if held["vol_first"] is not None and held["vol_last"] is not None:
        vol_delta = held["vol_last"] - held["vol_first"]
    return (held["date"], held["minute"], held["symbol"], held["ticks"],
            held.get("book_ticks", 0),
            up, down, held["flat_qty"], up - down, held["ltq_sum"],
            vol_delta, book_buy, book_sell, skew, held["ltp"], held["atp"])


def flush(now=None, force=False):
    """Write completed minutes. Returns how many rows landed.

    Called off the tick path -- a SQLite write on the websocket thread
    is how a feed falls behind. `force` also closes every open bucket,
    which is what shutdown wants.
    """
    now = now or datetime.now()
    try:
        with _lock:
            if force:
                _done.extend(_open.values())
                _open.clear()
            else:
                # Close buckets nothing has ticked into for a while.
                cutoff = now.strftime("%H:%M")
                for symbol, held in list(_open.items()):
                    if held["minute"] == cutoff:
                        continue
                    gap = _minutes_between(held["minute"], cutoff)
                    if gap is None or gap >= STALE_MINUTES:
                        _done.append(held)
                        del _open[symbol]
            pending, _done[:] = list(_done), []
        if not pending:
            return 0
        rows = [_row(h) for h in pending]
        with sqlite3.connect(DB_PATH, timeout=30) as db:
            db.executescript(_SCHEMA)
            db.executemany(
                "INSERT OR IGNORE INTO flow_minutes "
                "(date, minute, symbol, ticks, book_ticks, up_qty, down_qty, "
                " flat_qty, delta, ltq_sum, vol_delta, book_buy, book_sell, "
                " skew_pct, ltp, atp) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        _stats["written"] += len(rows)
        return len(rows)
    except Exception as exc:                              # noqa: BLE001
        warn(f"[FLOW] Could not write order flow ({exc}). Nothing else "
             f"is affected -- this store feeds no decision.")
        return 0


def _minutes_between(older, newer):
    try:
        a = int(older[:2]) * 60 + int(older[3:5])
        b = int(newer[:2]) * 60 + int(newer[3:5])
        return b - a
    except (TypeError, ValueError, IndexError):
        return None


def pressure(symbol):
    """Who is winning this stock RIGHT NOW. None until it has traded.

    ---- SAME DAY, LIVE. 29 August 2026. ----

        "no thats not the way order flow is used"
        "it is used on same day"                  -- operator

    The store on disk is for checking this reading afterwards. THIS is
    the reading: a running total, this session, updated on every tick,
    answering "are buyers lifting offers or are sellers hitting bids".

    Nothing calls it yet, and that is deliberate -- the same rule the
    recorder shipped under. It is measured before it is traded on.

        delta       buy quantity minus sell quantity, since the open
        buy, sell   the two sides
        ticks       prints seen
        book_ticks  how many were classified against a REAL bid/ask
                    rather than inferred from the price change

    The last one is the honesty column. book_ticks near ticks means
    the delta is real. book_ticks near zero means the feed is in Quote
    mode and this is the tick rule -- roughly 75-80% right, and worst
    in exactly the fast markets it would be used in.
    """
    if not symbol:
        return None
    name = str(symbol).upper()
    with _lock:
        got = _session.get(name)
        held = _open.get(name)
        if not got and held is None:
            return None
        # TODAY only. A process that runs past midnight, or a session
        # replayed over two dates, must not add this morning's open
        # minute to yesterday's running total -- which is exactly what
        # the first version did.
        today = held["date"] if held is not None else got["date"]
        buy = sell = 0.0
        ticks = book = 0
        if got and got["date"] == today:
            buy, sell = got["buy"], got["sell"]
            ticks, book = got["ticks"], got["book_ticks"]
        if held is not None:
            buy += held["up_qty"]
            sell += held["down_qty"]
            ticks += held["ticks"]
            book += held.get("book_ticks", 0)
        if not ticks:
            return None
    return {"symbol": name, "delta": buy - sell, "buy": buy, "sell": sell,
            "ticks": ticks, "book_ticks": book,
            "from_the_book": bool(ticks) and book / ticks > 0.5}


def stats():
    """{"observed", "written", "dropped", "open", "pending"}."""
    with _lock:
        return dict(_stats, open=len(_open), pending=len(_done))


def reset():
    """Tests only."""
    with _lock:
        _open.clear()
        _done[:] = []
        _session.clear()
        _last_px.clear()
        _last_dir.clear()
        for key in _stats:
            _stats[key] = 0


class Recorder:
    """Owns the flush timer. Started from main.py, stopped at the bell."""

    def __init__(self, seconds=30):
        self.seconds = int(seconds)
        self._stop = threading.Event()
        self._thread = None

    def start(self):
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="order-flow")
        self._thread.start()
        diagnostic(f"[FLOW] Order flow recorder started "
                   f"(flush every {self.seconds}s -> {DB_PATH}).")
        return self

    def _loop(self):
        while not self._stop.is_set():
            self._stop.wait(self.seconds)
            if self._stop.is_set():
                break
            flush()

    def stop(self, timeout=5):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
            self._thread = None
        wrote = flush(force=True)
        got = stats()
        diagnostic(f"[FLOW] Recorder stopped. {got['written']} minutes "
                   f"written ({wrote} on the way out), "
                   f"{got['observed']} ticks seen, {got['dropped']} dropped.")


# ==========================================================
# READING IT BACK: WHEN DID THE BUYING STOP PAYING?
# ==========================================================
#
#     "nice points to build confidence in user for trading &
#      holding as long as data suggested"
#                                 -- operator, 30 August 2026
#
# Everything above RECORDS. This READS, for the screen only. It
# still votes on nothing.
#
# The store is the source, not a new in-memory series. flow_minutes
# already holds every minute and is indexed on (date, symbol);
# keeping a per-minute series for 1,300 subscribed symbols would
# have cost the live process roughly 60 MB to serve the twenty rows
# on the board.

def session_series(symbol, date=None, db_path=None):
    """Today's minutes for one stock, oldest first.

        [{"minute": "09:15", "delta": 4210.0, "cum": 4210.0,
          "ltp": 598.1, "ticks": 44, "book_ticks": 42}, ...]

    Empty list on any failure, and on a machine that has never
    recorded a session. The running total is built here rather than
    stored, so a gap in the middle cannot corrupt the earlier part.
    """
    name = str(symbol or "").upper()
    if not name:
        return []
    day = date or datetime.now().strftime("%Y-%m-%d")
    path = db_path or DB_PATH
    if not os.path.exists(path):
        return []
    try:
        conn = sqlite3.connect("file:" + path + "?mode=ro", uri=True)
        try:
            rows = conn.execute(
                "SELECT minute, delta, ltp, ticks, book_ticks "
                "FROM flow_minutes WHERE date = ? AND symbol = ? "
                "ORDER BY minute", (day, name)).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []

    out, running = [], 0.0
    for minute, delta, ltp, ticks, book_ticks in rows:
        running += float(delta or 0.0)
        out.append({"minute": minute, "delta": float(delta or 0.0),
                    "cum": running, "ltp": ltp,
                    "ticks": int(ticks or 0),
                    "book_ticks": int(book_ticks or 0)})
    return out


# How far back "still growing" looks. Not a new number: it is
# core/intraday_shape.BLOCK_MINUTES, the unit the shape reading
# already uses, so the two speak the same clock.
STILL_BUYING_LOOKBACK = 15


def still_buying(symbol, date=None, db_path=None, series=None,
                 lookback=STILL_BUYING_LOOKBACK):
    """Are buyers STILL winning this stock, or have they stopped?

    ---- PRECWIRE, 31 August 2026. ----

        "some stocks will rally sudden volume surges & later we/bot
         will know the reason ... volume can't hide"
                                            -- the operator

    The entry gate calls a stock "fading" on where its PRICE sits in
    the day's range. PRECWIRE sat at 0.22 of its range and was refused
    518 times, while buyers took 63% of every share traded and
    cumulative delta made new highs all session, measured at 100%
    against a real bid and ask. The price pulled back; the pressure
    never did.

    Two conditions, and deliberately no invented percentage:

        positive   cumulative delta above zero -- buyers ahead today
        growing    higher than it was `lookback` minutes ago

    Measured on the live session that afternoon:

        PRECWIRE     66,243  vs  65,930  ->  growing,  99% of peak
        ASHOKA      3,04,021 vs 3,28,122 ->  falling,  67% of peak
        ATHERENERG    34,988 vs   40,031 ->  falling,  83% of peak
        VIMTALABS    -33,897 vs  -14,861 ->  falling, negative

    An earlier draft asked how LONG ago the peak was. That is the
    wrong question: PRECWIRE's peak was 17 minutes old and it was
    sitting 1.1% below it. A stock can hold its high for an hour and
    it has not stopped buying.

    None means NO READING -- too little session, or the sides were
    inferred rather than read off a real book. A caller must treat
    that as "do not act", never as "no buying".
    """
    rows = series if series is not None else session_series(
        symbol, date=date, db_path=db_path)
    live = [r for r in rows if r.get("minute", "") >= "09:15"]
    if len(live) < lookback + 2:
        return None

    ticks = sum(r["ticks"] for r in live)
    book = sum(r["book_ticks"] for r in live)
    book_pct = (book / ticks * 100.0) if ticks else 0.0
    try:
        from config import FLOW_MIN_BOOK_PCT
    except Exception:                                      # noqa: BLE001
        FLOW_MIN_BOOK_PCT = 60.0
    if book_pct < FLOW_MIN_BOOK_PCT:
        return None                # a guess must not overrule a gate

    now, then = live[-1], live[-1 - lookback]
    peak = max(r["cum"] for r in live)
    return {
        "symbol": str(symbol or "").upper(),
        "delta": now["cum"],
        "was": then["cum"],
        "growing": now["cum"] > then["cum"],
        "positive": now["cum"] > 0,
        "still_buying": bool(now["cum"] > 0 and now["cum"] > then["cum"]),
        "of_peak": round(now["cum"] / peak * 100.0, 1) if peak > 0 else None,
        "book_pct": round(book_pct, 1),
        "minutes": lookback,
    }


def _minute_gap(older, newer):
    """Whole minutes between two "HH:MM" strings, or None."""
    try:
        a = datetime.strptime(older, "%H:%M")
        b = datetime.strptime(newer, "%H:%M")
    except (TypeError, ValueError):
        return None
    return int((b - a).total_seconds() // 60)


def divergence(symbol, date=None, db_path=None, series=None):
    """Has price kept making highs after the buying stopped?

    Returns None when there is nothing to say -- too little of the
    session, no new highs, or the sides were mostly INFERRED rather
    than read off a real bid and ask. Saying nothing is the honest
    answer; a guess here would tell him to sell a winner.

        {"diverged": True,
         "since": "14:05",          when the buying peaked
         "new_highs": 2,            price highs made after that
         "book_pct": 94.1,          how much of it was measured
         "why": "price made 2 new highs after 14:05 and buying did
                 not follow"}

    HOW IT DECIDES, in the order the questions are asked:

        1. at least FLOW_MIN_MINUTES of the session are recorded
        2. find the minute cumulative delta peaked
        3. count the minutes AFTER that where price set a new high
           for the day
        4. that must be at least FLOW_DIVERGENCE_HIGHS, and the last
           of them within FLOW_DIVERGENCE_RECENT_MINUTES -- a stock
           that diverged at 10:00 and has gone sideways since is not
           an exit at 15:00
        5. and FLOW_MIN_BOOK_PCT of prints must have been classified
           against a REAL bid and ask

    Step 5 is the one that matters. The tick rule is 75-80% right,
    and worst in exactly the fast markets this would be used in.
    """
    try:
        from config import (FLOW_DIVERGENCE_HIGHS,
                            FLOW_DIVERGENCE_RECENT_MINUTES,
                            FLOW_MIN_MINUTES, FLOW_MIN_BOOK_PCT)
    except Exception:                                      # noqa: BLE001
        FLOW_DIVERGENCE_HIGHS, FLOW_DIVERGENCE_RECENT_MINUTES = 2, 45
        FLOW_MIN_MINUTES, FLOW_MIN_BOOK_PCT = 20, 60.0

    rows = series if series is not None else session_series(
        symbol, date=date, db_path=db_path)
    priced = [r for r in rows if r.get("ltp")]
    if len(priced) < FLOW_MIN_MINUTES:
        return None

    ticks = sum(r["ticks"] for r in priced)
    book = sum(r["book_ticks"] for r in priced)
    book_pct = (book / ticks * 100.0) if ticks else 0.0

    peak_at, peak = None, None
    for row in priced:
        if peak is None or row["cum"] > peak:
            peak, peak_at = row["cum"], row["minute"]

    # New highs for the day, counted only AFTER the buying peaked.
    # The running max starts from the whole session so that a high
    # made in the morning is not counted again in the afternoon.
    high = None
    new_highs, last_high_at = 0, None
    for row in priced:
        price = row["ltp"]
        if high is None or price > high:
            high = price
            if peak_at is not None and row["minute"] > peak_at:
                new_highs += 1
                last_high_at = row["minute"]

    if new_highs < FLOW_DIVERGENCE_HIGHS or last_high_at is None:
        return None

    gap = _minute_gap(last_high_at, priced[-1]["minute"])
    if gap is not None and gap > FLOW_DIVERGENCE_RECENT_MINUTES:
        return None

    measured = book_pct >= FLOW_MIN_BOOK_PCT
    return {
        "diverged": True,
        "measured": measured,
        "since": peak_at,
        "new_highs": new_highs,
        "book_pct": round(book_pct, 1),
        "why": (f"price made {new_highs} new highs after {peak_at} "
                f"and buying did not follow"),
    }
