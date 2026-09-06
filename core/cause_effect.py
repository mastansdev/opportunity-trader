"""What happened AFTER. The bot's memory of cause and effect.

==========================================================
    "what about welspun corp? rally after its order win.
     check our bots memory to recall the cause & effect
     after. this is the reason i asked you to build brain
     memory but still not done as i wanted"
                            -- the operator, 5 September 2026
==========================================================

THE GAP THIS FILLS. The bot holds 18,638 events and 200 trades and
NOTHING JOINS THEM. It can tell you an order was announced and it can
tell you a trade lost money, and it cannot tell you whether orders are
worth trading. It has facts and no memory.

WELSPUN CORP is the case. On 20 August the store recorded the largest
single order in the company's history, Rs 15,840 crore. The stock was
on the board 160 times the next day and was never bought. On 3, 4 and
5 September it was up 4.7 to 5.9% on four to six times its normal
volume and the refusal read:

    "up 4.7% and never in the pool: nothing published, volume 4.1"

Nothing published. The cause was two weeks old and the effect was
still running, and the bot could not connect the two because it has
never once looked back at what any cause produced.

---- THE CAUSE DOES NOT LAND WHERE IT IS FILED. 5 Sep 2026 ----

    "ultratech company announced its business expansion into wires &
     cables which lead the sector into sell off"      -- the operator

From this bot's own data:

    1 Sep   ULTRACEMCO commences commercial production of 11 lakh km
            of wires and cables

                     1 Sep    2 Sep
            POLYCAB   -5.8%    -1.0%
            KEI       -6.8%    -3.3%
            RRKABEL   -2.0%    -8.3%
            FINCABLES +0.1%    -4.6%
            HAVELLS   -1.7%    -2.4%
            ULTRACEMCO -0.4%   -0.1%   <- the company that announced it

The effect landed on five companies that were not named in the event.
The one that WAS named barely moved. An event store filed under
symbol can never see that, so this measures the SUBJECT and the
SECTOR separately and stores both.

WHAT IT IS NOT. It is not a prediction and it does not vote on a
trade. It is a record: this kind of cause, this many times, this is
what followed. Reading it is a separate decision that he has not yet
made, and nothing in the entry or exit path imports this module.

HOW IT MEASURES

    subject_1d   the named stock's close-to-close return the next
                 session after the event
    subject_3d   the same over three sessions
    peers_1d     the MEDIAN of its sector peers over one session --
                 the median, not the mean, because one peer having a
                 result of its own must not carry the reading

NEVER AVERAGED ACROSS CAUSES. Every event is one row. what_followed()
reports counts and medians of those rows and never blends two kinds
of cause into one number.

FAILS CLOSED. A stock with no prior close, an event with no date, a
sector with fewer than MIN_PEERS members -- all stored as None and
excluded from every reading. An unknown effect is not a zero effect.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime

from core.logger import diagnostic

DB_PATH = os.path.join("data", "cause_effect.db")
EVENTS_DB = os.path.join("data", "stock_events.db")
DAILY_DB = os.path.join("data", "daily_candles.db")

# A sector reading needs enough names to be a sector and not a stock.
MIN_PEERS = 3
# How many peers to measure. The whole sector is not needed and the
# tail of a large sector is illiquid names nothing trades.
MAX_PEERS = 12

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cause_effect (
    id          INTEGER PRIMARY KEY,
    date        TEXT NOT NULL,
    symbol      TEXT NOT NULL,
    kind        TEXT,
    grade       TEXT,
    value_cr    REAL,
    sector      TEXT,
    subject_1d  REAL,
    subject_3d  REAL,
    peers_1d    REAL,
    peers_3d    REAL,
    peer_count  INTEGER,
    -- ---- THE THREATENED, AS DISTINCT FROM THE PEERS. 5 Sep 2026 ----
    -- peers_*      companies in the FILER's own sector
    -- threat_*     companies whose CORE BUSINESS the event is about,
    --              whoever filed it. UltraTech is cement; the event
    --              was wires and cables; the threatened were KEI,
    --              POLYCAB and RRKABEL.
    threat_tag  TEXT,
    threat_1d   REAL,
    threat_3d   REAL,
    -- ---- THE IMPACT, NOT THE SCARE. 5 September 2026. ----
    --
    --     "which will eventually recover & stocks may rebound but the
    --      impact is the main thing we are capturing"
    --                                        -- the operator
    --
    -- One and three sessions cannot tell a permanent repricing from a
    -- two-day fright. A cement leader with that balance sheet entering
    -- wires does not hurt POLYCAB's earnings this quarter -- it
    -- changes what POLYCAB is worth. That shows up over weeks, and it
    -- is confirmed or refuted at the next results.
    threat_10d  REAL,
    threat_20d  REAL,
    subject_10d REAL,
    subject_20d REAL,
    -- ---- VOLUME IS THE MAGNITUDE. 5 September 2026. ----
    --
    --     "volume tells us the magnitue. the only thing markets can
    --      grab without ask is volume & order flow pressure on which
    --      side."                              -- the operator
    --
    -- Two order wins sit in this store looking identical:
    --
    --     WELCORP    21 Aug   Rs 15,840 cr   next day  +4.21%
    --     ANTELOPUS   1 Sep   onshore block  next day +20.00%
    --
    -- ANTELOPUS traded 12,446,135 shares that day against a normal of
    -- about 50,000 -- 262 TIMES. Welspun did not. The headlines cannot
    -- tell them apart and the volume can, so the volume is stored with
    -- the cause. It is measured against the stock's OWN prior median,
    -- never against another stock.
    vol_x       REAL,
    vol_x_next  REAL,
    threat_n    INTEGER,
    headline    TEXT,
    UNIQUE(date, symbol, kind, headline)
);
CREATE INDEX IF NOT EXISTS idx_ce_kind ON cause_effect(kind, grade);
CREATE INDEX IF NOT EXISTS idx_ce_symbol ON cause_effect(symbol, date);
"""


def _connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.executescript(_SCHEMA)
    return conn


def _sessions(daily_db=None):
    """Every trading date the daily store knows, in order.

    Forward returns are counted in SESSIONS, not days: an event on a
    Friday is measured against Monday. Counting calendar days would
    read a weekend as a flat market.
    """
    conn = sqlite3.connect("file:" + (daily_db or DAILY_DB) + "?mode=ro",
                           uri=True)
    try:
        return [r[0] for r in conn.execute(
            "SELECT DISTINCT date FROM daily_bars ORDER BY date")]
    finally:
        conn.close()


VOLUME_NORMAL_DAYS = 20      # what "normal" means for one stock


def _volumes(symbols, daily_db=None):
    """{symbol: [(date, volume), ...]} in date order."""
    if not symbols:
        return {}
    conn = sqlite3.connect("file:" + (daily_db or DAILY_DB) + "?mode=ro",
                           uri=True)
    out = {}
    try:
        marks = ",".join("?" * len(symbols))
        for sym, date, vol in conn.execute(
                f"SELECT symbol, date, volume FROM daily_bars "
                f"WHERE symbol IN ({marks}) AND volume IS NOT NULL "
                f"ORDER BY symbol, date", tuple(symbols)):
            out.setdefault(sym, []).append((date, float(vol)))
    finally:
        conn.close()
    return out


def _volume_multiple(series, on_date, ahead=0):
    """How many times its OWN normal this stock traded, or None.

    Normal is the MEDIAN of the prior VOLUME_NORMAL_DAYS sessions --
    the median, because one earlier event day in the window would
    raise a mean and hide the very spike being measured.
    """
    if not series:
        return None
    dates = [d for d, _v in series]
    try:
        i = dates.index(on_date)
    except ValueError:
        return None
    j = i + ahead
    if j >= len(series):
        return None
    prior = [v for _d, v in series[max(0, i - VOLUME_NORMAL_DAYS):i] if v > 0]
    if len(prior) < 5:
        return None
    normal = _median(prior)
    if not normal or normal <= 0:
        return None
    return series[j][1] / normal


def _closes(symbols, daily_db=None):
    """{symbol: {date: close}} for the symbols asked for."""
    if not symbols:
        return {}
    conn = sqlite3.connect("file:" + (daily_db or DAILY_DB) + "?mode=ro",
                           uri=True)
    out = {}
    try:
        marks = ",".join("?" * len(symbols))
        for sym, date, close in conn.execute(
                f"SELECT symbol, date, close FROM daily_bars "
                f"WHERE symbol IN ({marks}) AND close IS NOT NULL",
                tuple(symbols)):
            out.setdefault(sym, {})[date] = float(close)
    finally:
        conn.close()
    return out


def _forward(closes, sessions, on_date, ahead):
    """Close-to-close return over `ahead` SESSIONS, or None.

    None whenever it cannot be established -- the event date is not a
    session the store knows, the stock did not trade that day, or the
    day being measured to has not happened yet.
    """
    try:
        i = sessions.index(on_date)
    except ValueError:
        return None
    if i + ahead >= len(sessions):
        return None
    a, b = closes.get(on_date), closes.get(sessions[i + ahead])
    if not a or not b or a <= 0:
        return None
    return (b - a) / a * 100.0


def _median(values):
    got = sorted(v for v in values if v is not None)
    if not got:
        return None
    mid = len(got) // 2
    return got[mid] if len(got) % 2 else (got[mid - 1] + got[mid]) / 2.0


# ---- THE THREAT IS TO A CORE BUSINESS, NOT TO A TAG. ----
#                                     5 September 2026.
#
#     "sector map will never match this as we hard coded their sectors
#      which is 100% correct but in this case this sector leader is
#      expanding into new sector business"
#     "which is direct threat to their core business"
#                                            -- the operator
#
# He is right on both counts. ULTRACEMCO *is* cement -- the map is
# correct -- and the event was about wires and cables, a business it
# does not belong to. So the link cannot come from the filer's sector.
# It comes from the SUBJECT of the event, matched against what other
# companies do for a living.
#
# The master data already carries that vocabulary. like("cable")
# returns CABLES, ELECTRICAL CABLES, POWER CABLES; like("wire")
# returns WIRES. Nothing new is hardcoded here.
#
# NARROW TAGS ONLY. A tag with 687 members (MANUFACTURER) or 292
# (GOVERNMENT SPENDING) describes an attribute, not a business, and
# nothing threatens it. CABLES has six members and WIRES has three.
# The ceiling is what separates "this is what they do" from "this is
# something true about them".
SUBJECT_MAX_MEMBERS = 40
SUBJECT_MIN_MEMBERS = 3
# Columns that describe what a company DOES. OWNERSHIP, BUSINESS_TYPE
# and ECONOMIC_SENSITIVITY describe what it IS, and are not a business
# anyone can be threatened out of.
SUBJECT_COLUMNS = ("INDUSTRY", "THEMES", "KEYWORDS", "SECTOR")


def subjects_in(headline, tag_index=None):
    """Which businesses this event is ABOUT, whoever filed it.

    Returns [(tag, [members])] for the narrow tags whose words appear
    in the headline. Empty when the event names no business -- which
    is most events, and is a real answer.
    """
    text = " " + " ".join(str(headline or "").upper().split()) + " "
    if len(text) < 5:
        return []
    if tag_index is None:
        from core import sector_map
        tag_index = sector_map._tag_index()
    out, seen = [], set()
    for column, tags in (tag_index or {}).items():
        if column not in SUBJECT_COLUMNS:
            continue
        for tag, members in (tags or {}).items():
            name = str(tag or "").upper().strip()
            if len(name) < 4 or name in seen:
                continue
            if not (SUBJECT_MIN_MEMBERS <= len(members)
                    <= SUBJECT_MAX_MEMBERS):
                continue
            if (" " + name + " ") not in text:
                continue
            seen.add(name)
            out.append((name, sorted(members)))
    return out


def build(events_db=None, daily_db=None, db_path=None, since=None,
          sector_of=None, members_of=None, progress=None):
    """Measure what followed every event, and store it.

    The sector lookups are INJECTED so this can be tested without the
    master CSV, and so a broken sector map degrades to "no peer
    reading" rather than to no memory at all.

    Returns how many rows were written.
    """
    if sector_of is None or members_of is None:
        from core import sector_map
        sector_of = sector_of or sector_map.sector_of
        members_of = members_of or sector_map.members

    sessions = _sessions(daily_db)
    session_set = set(sessions)

    conn = sqlite3.connect("file:" + (events_db or EVENTS_DB) + "?mode=ro",
                           uri=True)
    try:
        sql = ("SELECT symbol, at, kind, grade, value_cr, headline "
               "FROM events WHERE symbol IS NOT NULL AND at IS NOT NULL")
        args = ()
        if since:
            sql += " AND at >= ?"
            args = (since,)
        events = conn.execute(sql + " ORDER BY at", args).fetchall()
    finally:
        conn.close()

    # One pass to learn which symbols are needed, so the daily store is
    # read once rather than once per event.
    try:
        from core import sector_map
        tag_index = sector_map._tag_index()
    except Exception:                                      # noqa: BLE001
        tag_index = {}

    wanted, rows = set(), []
    for sym, at, kind, grade, value_cr, headline in events:
        symbol = str(sym or "").upper()
        date = str(at or "")[:10]
        if not symbol or date not in session_set:
            continue
        try:
            sector = sector_of(symbol)
        except Exception:                                  # noqa: BLE001
            sector = None
        peers = []
        if sector:
            try:
                peers = [p for p in (members_of(sector, limit=MAX_PEERS) or [])
                         if p != symbol]
            except Exception:                              # noqa: BLE001
                peers = []
        # Who does this event THREATEN, whoever filed it. The named
        # company is excluded: UltraTech is not threatened by its own
        # announcement, which is exactly why it did not move.
        threat_tag, threatened = None, []
        for tag, members in subjects_in(headline, tag_index):
            hit = [m for m in members if m != symbol]
            if len(hit) >= SUBJECT_MIN_MEMBERS:
                threat_tag, threatened = tag, hit
                break
        wanted.add(symbol)
        wanted.update(peers)
        wanted.update(threatened)
        rows.append((date, symbol, kind, grade, value_cr, sector, peers,
                     threat_tag, threatened, headline))

    closes = _closes(sorted(wanted), daily_db)
    volumes = _volumes(sorted(wanted), daily_db)

    out = _connect(db_path)
    written = 0
    try:
        for (date, symbol, kind, grade, value_cr, sector, peers,
             threat_tag, threatened, headline) in rows:
            mine = closes.get(symbol) or {}
            s1 = _forward(mine, sessions, date, 1)
            s3 = _forward(mine, sessions, date, 3)
            p1 = p3 = None
            usable = [p for p in peers if closes.get(p)]
            if len(usable) >= MIN_PEERS:
                p1 = _median([_forward(closes[p], sessions, date, 1)
                              for p in usable])
                p3 = _median([_forward(closes[p], sessions, date, 3)
                              for p in usable])
            t1 = t3 = t10 = t20 = None
            hot = [t for t in threatened if closes.get(t)]
            if len(hot) >= SUBJECT_MIN_MEMBERS:
                t1, t3, t10, t20 = (
                    _median([_forward(closes[t], sessions, date, n)
                             for t in hot]) for n in (1, 3, 10, 20))
            vx = _volume_multiple(volumes.get(symbol), date, 0)
            vxn = _volume_multiple(volumes.get(symbol), date, 1)
            s10 = _forward(mine, sessions, date, 10)
            s20 = _forward(mine, sessions, date, 20)
            if s1 is None and p1 is None and t1 is None:
                continue                 # nothing measurable -- store nothing
            out.execute(
                "INSERT OR IGNORE INTO cause_effect "
                "(date, symbol, kind, grade, value_cr, sector, subject_1d, "
                " subject_3d, peers_1d, peers_3d, peer_count, threat_tag, "
                " threat_1d, threat_3d, threat_10d, threat_20d, "
                " subject_10d, subject_20d, vol_x, vol_x_next, threat_n, "
                " headline) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (date, symbol, kind, grade, value_cr, sector, s1, s3,
                 p1, p3, len(usable), threat_tag, t1, t3, t10, t20,
                 s10, s20, vx, vxn, len(hot), str(headline or "")[:300]))
            written += out.total_changes and 1 or 0
            if progress and written and written % 500 == 0:
                progress(written)
        out.commit()
        return out.execute("SELECT COUNT(*) FROM cause_effect").fetchone()[0]
    finally:
        out.close()


def what_followed(kind=None, grade=None, min_value_cr=None, db_path=None):
    """What has historically happened after this kind of cause.

        {"n": 41, "subject": {"up": 24, "down": 17, "median": 0.82},
         "peers":   {"up": 19, "down": 22, "median": -0.11}}

    None when there is nothing to say. A caller must treat that as
    UNKNOWN and never as "no effect" -- the same posture every gate in
    this bot takes.

    COUNTS AND MEDIANS, NEVER A MEAN. One event that moved 40% must
    not speak for forty that moved nothing.
    """
    conn = _connect(db_path)
    try:
        sql = ("SELECT subject_1d, peers_1d FROM cause_effect "
               "WHERE subject_1d IS NOT NULL")
        args = []
        if kind:
            sql += " AND kind = ?"
            args.append(kind)
        if grade:
            sql += " AND grade = ?"
            args.append(grade)
        if min_value_cr:
            sql += " AND value_cr >= ?"
            args.append(min_value_cr)
        rows = conn.execute(sql, tuple(args)).fetchall()
    finally:
        conn.close()
    if not rows:
        return None
    subject = [r[0] for r in rows if r[0] is not None]
    peers = [r[1] for r in rows if r[1] is not None]
    if not subject:
        return None
    return {
        "n": len(subject),
        "subject": {"up": sum(1 for v in subject if v > 0),
                    "down": sum(1 for v in subject if v <= 0),
                    "median": _median(subject)},
        "peers": ({"up": sum(1 for v in peers if v > 0),
                   "down": sum(1 for v in peers if v <= 0),
                   "median": _median(peers)} if peers else None),
    }


def recall(symbol, days=30, db_path=None):
    """What has been published about this stock lately, and what
    followed each time.

    THE WELSPUN QUESTION. The bot refused WELCORP for "nothing
    published" while a Rs 15,840 crore order sat in its own store two
    weeks old. This is how it can be asked instead: what do we know
    about this company, and what happened after we learned it.

    Newest first. Empty list when nothing is known -- which is a real
    answer and different from "nothing happened".
    """
    name = str(symbol or "").upper()
    if not name:
        return []
    conn = _connect(db_path)
    try:
        rows = conn.execute(
            "SELECT date, kind, grade, value_cr, subject_1d, subject_3d, "
            "peers_1d, headline FROM cause_effect WHERE symbol = ? "
            "ORDER BY date DESC LIMIT ?", (name, int(days))).fetchall()
    finally:
        conn.close()
    return [{"date": r[0], "kind": r[1], "grade": r[2], "value_cr": r[3],
             "subject_1d": r[4], "subject_3d": r[5], "peers_1d": r[6],
             "headline": r[7]} for r in rows]


# ==================================================================
# WHAT IS STILL STANDING.  5 September 2026.
# ==================================================================
#
#     "this is not measurement on intraday or long term move, this is
#      real company order & this 'Rs 15,840 crore order, fourteen
#      sessions ago' is worth tracking"        -- the operator
#
# WORTH TRACKING, not worth trading -- and the difference is the whole
# design of this function. Asked of the memory before building it:
#
#     what followed, by kind        n      median next session
#     ORDER                       454                   +0.01%
#     NEWS                      4,150                   -0.20%
#     RESULT                    2,092                   -0.81%
#
# The event alone is worth nothing. And the big-order band does not
# survive inspection: nine rows above Rs 10,000 cr, of which THREE are
# real orders -- the rest are an investor presentation classified as an
# order, an acquisition rumour, and Welspun's own filing landed on
# Landmark. Three is not a rule.
#
# Keeping such an order alive as a GATE was measured too: at Rs 10,000
# cr held ten sessions it admits 68 extra stock-days, 11 of which move
# more than 3%, median -0.02%. One to two candidates a day, mostly
# going nowhere, into a queue that already runs 84 to 400 deep against
# five seats. More candidates is not the constraint.
#
# So this changes nothing about what the bot may buy. STALE_REASON_
# HOURS stays at 24 and core/why_moving.py is untouched. This is a
# SENTENCE for the board, so that when WELCORP is up 4.7% he reads
# "Rs 15,840 cr order, 14 sessions ago" beside it and decides himself.
#
# THE CASE IT IS FOR. On 20 August the store recorded the largest order
# in Welspun's history. On 3, 4 and 5 September the stock was up 4.7 to
# 5.9% on four to six times normal volume and the board said:
#
#     "up 4.7% and never in the pool: nothing published, volume 4.1"
#
# The cause was a fortnight old and sitting in this bot's own store.
# Nothing was published TODAY, and that is a true sentence that reads
# as a false one.

# A real order, in rupees the company would call material. Not a
# measured threshold -- there is nothing to measure it against, see
# above -- but a floor low enough to catch what he would want to see
# and high enough that routine supply contracts do not fill the board.
STANDING_MIN_CR = 500.0

# Roughly a trading month. The Welspun order was 14 sessions old when
# he asked about it, so a window that could not hold 14 would answer
# the wrong question.
STANDING_DAYS = 30

# Only causes that COMMIT the company to something. A news headline
# ages; an order is still on the books.
STANDING_KINDS = ("ORDER",)

# ==================================================================
# WHEN A STANDING ORDER MAY COUNT AS A REASON.  5 September 2026.
# ==================================================================
#
#     "why WELCORP is showing Still refused? its a clear winner with
#      +3 % right"                              -- the operator
#
# He was right and my first measurement was wrong. I banded these
# orders by RUPEES, found nothing, and recommended display-only --
# after he had already said rupees is the wrong yardstick. Re-asked
# with HIS measure, every stock-day a standing order would have
# admitted, banded by the order's share of the company:
#
#   share of co.   stock-days   moved 3%+ with 2x volume   ran 3% from open
#   0-5%                  241                          7             7 of 7
#   5-10%                 123                          2             1 of 2
#   10-20%                 74                          3             3 of 3
#   20-100%               117                         15           15 of 15
#
# Nine DISTINCT days in the top band -- WELCORP four times, plus
# AFCONS, TEJASNET, RAILTEL and INOXWIND twice -- and every one
# reached +3% from the open. A day in that band is about four times
# more likely to qualify than one in the bottom band.
#
# WHAT THIS DOES AND DOES NOT DO. It lets a large order keep counting
# as a PUBLISHED REASON after the 24-hour staleness window, and
# nothing else. The stock still has to be up 3%, still has to carry
# the volume, still has to be alive, still has to win a seat. In his
# words: "here our rule saves us without taking all entries too."
#
# THE BAR IS THE SHARE, NOT THE RUPEES. Twenty percent of the company,
# because that is where the measurement separates -- and because a
# rupee bar would let L&T's Rs 15,000 cr order (3% of L&T) through
# while refusing RailTel's Rs 630 cr (27% of RailTel), which is the
# exact mistake this replaces.
#
# A stock whose size is not known gets NOTHING. There are 500 sizes on
# file for 1,976 symbols, and admitting the unmeasured ones on a rupee
# bar would reintroduce the fault by the back door.
STANDING_GATE_MIN_PCT = 20.0

# Two trading weeks. The Welspun order was ten sessions old when it
# was still running and fourteen when he asked about it.
STANDING_GATE_SESSIONS = 14


def standing_cause(symbol, on=None, events_db=None, min_cr=None,
                   days=None):
    """The biggest committed cause still standing for this stock.

    Returns {"value_cr", "sessions_ago", "date", "headline", "text"}
    or None. `text` is the sentence for the board, in his words:

        "Rs 15,840 cr order, 14 sessions ago"

    Reads the EVENT store, not cause_effect.db, so it is current
    without a rebuild. Never raises: a board that cannot draw because
    a memory lookup failed is worse than a board with no memory.
    """
    name = str(symbol or "").upper()
    if not name:
        return None
    floor = STANDING_MIN_CR if min_cr is None else float(min_cr)
    window = STANDING_DAYS if days is None else int(days)
    today = on or datetime.now().date()
    if isinstance(today, str):
        try:
            today = datetime.fromisoformat(today[:10]).date()
        except ValueError:
            today = datetime.now().date()
    try:
        # READ-ONLY, AND IT WAITS. The collector writes this store
        # from another process and the journal mode is `delete`, so a
        # reader BLOCKS during a write. The default timeout is 5 s and
        # a timeout here returns "no standing cause", which is a wrong
        # answer rather than a slow one. Same shape as _sessions() and
        # _closes() above.
        conn = sqlite3.connect("file:" + (events_db or EVENTS_DB)
                               + "?mode=ro", uri=True, timeout=30)
        rows = conn.execute(
            "SELECT date(at), value_cr, headline FROM events "
            "WHERE symbol = ? AND kind IN (%s) AND value_cr >= ? "
            "AND date(at) >= date(?, ?) AND date(at) <= date(?) "
            "ORDER BY value_cr DESC, date(at) ASC"
            % ",".join("?" * len(STANDING_KINDS)),
            (name,) + STANDING_KINDS
            + (floor, today.isoformat(), f"-{window} day",
               today.isoformat())).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MEMORY] standing_cause({name}) failed: {exc}")
        return None
    if not rows:
        return None

    # ---- THE HEADLINE MUST NAME THIS COMPANY. 5 September 2026. ----
    #
    # The first run of this put the same sentence on four stocks:
    #
    #     WELCORP     Rs 15,840 cr order, 9 sessions ago   correct
    #     WEALTH      Rs 15,840 cr order, 9 sessions ago
    #     NUVAMA      Rs 15,840 cr order, 9 sessions ago
    #     LANDMARK    Rs 15,840 cr order, 9 sessions ago
    #
    # LANDMARK's row is Welspun's own filing -- "Pursuant to Regulation
    # 30 of the SEBI (Listing Obligations..." -- a preamble that names
    # nobody, landed on a second company.
    #
    # This is a sentence he READS. A false one on his screen is worse
    # than no sentence at all, because he would act on it. So the same
    # rule the event path got today applies here: the story has to say
    # whose it is. The row is kept only if the headline carries the
    # symbol or the distinctive first word of the company's name --
    # "WELSPUN CORP: CO. SECURES LARGEST-EVER SINGLE ORDER" names
    # Welspun, and the SEBI preamble names nobody.
    # ---- AND IT IS RE-READ WITH TODAY'S RULES. 5 Sep 2026. ----
    #
    # The store holds rows filed by older code, and two of them would
    # have gone straight onto his screen as facts:
    #
    #   JNPR    Rs 26,231 cr order   -- an Investor Presentation, and
    #                                   26,231 is a MW capacity target
    #   NUVAMA  Rs 15,840 cr order   -- an acquisition approach, and
    #                                   the figure is not its own
    #
    # Today's classifier calls both NEWS with no amount, so the bug is
    # fixed at the source and only history is wrong. History is
    # exactly what a memory reads, though, so the row is re-read as it
    # is drawn: if the current rules would not call this an ORDER with
    # this amount, it is not shown. The store is left alone -- these
    # age out of the window on their own, and rewriting stored events
    # to make a display tidy is how a record stops being a record.
    picked = None
    for day, value, headline in rows:
        if not _headline_names(name, headline):
            continue
        if not _still_reads_as_an_order(headline, value):
            diagnostic(f"[MEMORY] {name}: a stored 'Rs {value:,.0f} cr "
                       f"order' does not read as one today -- not shown")
            continue
        picked = (day, value, headline)
        break
    if picked is None:
        return None
    day, value, headline = picked

    # SESSIONS, not days. "Fourteen sessions ago" is what he said and
    # what a trader counts; a fortnight of calendar days spans two
    # weekends and reads as older than it is.
    ago = _sessions_between(day, today)
    if ago is None:
        return None
    return _sentence(name, day, value, headline, ago)


def _sentence(symbol, day, value, headline, ago):
    """One standing cause, as something to read.

    ---- HOW BIG IT IS AGAINST THE COMPANY. 5 September 2026. ----

        "check the % of that order to their market cap. this reveal
         the significance of the order book. ex simple = 100 cr order
         for 200 MCAP & 10000 MCAP company 1st is 50% & the other is
         1%"                                      -- the operator

    He is right and the store proves it. Ranked by RUPEES the top of
    the list was JNPR's investor presentation, where the figure was a
    megawatt target. Ranked by SHARE OF THE COMPANY the two that
    actually ran come near the top, and RAILTEL's Rs 630 cr -- small
    in rupees, a quarter of the company -- stops being invisible.

    The share is added only when the size is known. It is FREE FLOAT,
    which is what NSE publishes in bulk and covers about 500 of the
    1,976 symbols on file, so it is labelled rather than implied. See
    core/market_cap.py.
    """
    value = float(value or 0.0)
    share = None
    try:
        from core import market_cap
        share = market_cap.share_of_company(symbol, value)
    except Exception:                                      # noqa: BLE001
        share = None
    text = (f"Rs {value:,.0f} cr order, "
            f"{ago} session{'s' if ago != 1 else ''} ago")
    if share is not None:
        # The share goes FIRST in the phrase, because it is the half
        # that tells him whether to care. An order larger than the
        # whole company is shown as it is -- that is the store saying
        # the row is wrong, and hiding it would hide the most useful
        # thing this measure does.
        text = (f"Rs {value:,.0f} cr order = {share:.0f}% of the "
                f"company, {ago} session{'s' if ago != 1 else ''} ago")
    return {
        "date": day,
        "value_cr": value,
        "sessions_ago": ago,
        "headline": headline,
        "pct_of_company": share,
        "cap_basis": "free float" if share is not None else None,
        "text": text,
    }


_NAME_NOISE = {"LIMITED", "LTD", "THE", "INDIA", "INDIAN", "CO",
               "COMPANY", "CORP", "CORPORATION", "AND", "OF", "PVT",
               "PRIVATE", "NEW", "GROUP"}


def _still_reads_as_an_order(headline, value_cr):
    """Would today's rules call this an order of this size?

    See the note at the call site. Fails OPEN -- a classifier that
    cannot be consulted must not silence a real cause.
    """
    try:
        from core.stock_events import amount_in_crore, classify
        kind, _scope = classify(str(headline or ""), has_symbol=True)
        if kind != "ORDER":
            return False
        amount = amount_in_crore(str(headline or ""))
    except Exception:                                      # noqa: BLE001
        return True
    if amount is None:
        # The headline states no figure of its own. Welspun's does not
        # -- it says "USD 1.8 BILLION" and the crore figure came from
        # the conversion -- so this cannot be a refusal on its own.
        return True
    # Within a rupee or two of what was stored. A different number
    # means the stored one came from somewhere else in the message.
    return abs(float(amount) - float(value_cr or 0)) <= max(
        1.0, float(value_cr or 0) * 0.02)


_MATCHER = None
_NAMES_CACHE = {}


def _matcher():
    """The same matcher the events path uses, built once.

    Deliberately not a private copy of the rules. Everything learned
    about naming a company today lives in that matcher -- the word
    tickers, the fund exclusion, the state names -- and a second
    implementation here would drift from it within the week.
    """
    global _MATCHER
    if _MATCHER is None:
        from core.master_loader import MasterLoader
        from core.telegram_feed import TelegramFeed
        # main.py has had a loaded MasterLoader since line 307. Loading
        # a SECOND one here cost 0.9 s and held the whole master list
        # in memory twice, for a list that is identical. warm() hands
        # the live one over before the open; this stays as the
        # fallback for tools and tests, which have no loader to give.
        loader = MasterLoader()
        loader.load()
        _MATCHER = TelegramFeed(master_loader=loader)
    return _MATCHER


def warm(master_loader=None):
    """Build the matcher and today's batch BEFORE the market opens.

    ---- 1.6 SECONDS, ONCE, IN THE WRONG PLACE. 6 Sep 2026. ----

        "i want 0 lag & 0 errors from monday"      -- the operator

    Measured in a fresh process: the first standing lookup costs
    1,642 ms and every one after it costs nothing. That first one
    would have landed inside _route_entries(), which runs every second
    from 09:15 -- so the one slow call was going to happen at the open,
    on the first stock with no fresh reason.

    Called from main.py at startup, where there is slack. Never
    raises: a memory that could not be warmed is a memory that warms
    itself on first use, which is what it did before this existed.
    """
    global _MATCHER
    try:
        if _MATCHER is None and master_loader is not None:
            from core.telegram_feed import TelegramFeed
            _MATCHER = TelegramFeed(master_loader=master_loader)
        held = _standing_batch(_day(None))
        return len(held)
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MEMORY] warm() failed ({exc}) -- the standing "
                   f"causes will be built on first use instead")
        return 0


def _headline_names(symbol, headline, matcher=None):
    """Does this headline actually name this company?

    ---- ASKED OF THE LIVE MATCHER. 5 September 2026. ----

    The first version looked for the ticker or a word of the company
    name in the text, and passed two rows it should have refused:

        LANDMARK  "we wish to inform the Exchange of a landmark..."
        WEALTH    "HSBC joins PEs in race for Nuvama Wealth"

    Both because the ticker IS an ordinary English word, which is the
    fault _WORD_TICKERS has existed for since 6 August -- and a second
    naming rule written here could not know that. So this asks the
    matcher instead, and inherits every guard it has.

    Old rows are why this is needed at all: the store still holds
    events filed before those guards, and a sentence he READS must be
    checked as it is drawn, not as it was stored.

    Fails OPEN: if the matcher cannot be built, an unchecked sentence
    is better than a lost one.
    """
    text = str(headline or "")
    if not text.strip():
        return False
    name = str(symbol or "").upper()

    # ---- IT ASKED THE SAME QUESTION EVERY CYCLE. 6 Sep 2026. ----
    #
    # Measured on the live path the morning after this shipped: 300
    # symbols through why() cost 23.5 ms each against 4.7 ms before,
    # and 93% of that time was seven stocks reaching this function.
    # One call is 86 ms, because names_in() compares the headline
    # against every company on the master list -- 553,913 string
    # comparisons for 300 symbols.
    #
    # The question is PURE. The same stored headline and the same
    # symbol give the same answer for as long as both exist, and the
    # rows being re-read are days old by definition. So it is asked
    # once and remembered, which changes no answer and removes the
    # cost from the second cycle onward.
    #
    # The matcher itself is NOT copied here -- see _matcher(). This
    # remembers what it said; it does not decide anything itself.
    key = (name, text)
    hit = _NAMES_CACHE.get(key)
    if hit is not None:
        return hit
    try:
        from core.stock_events import _for_matching
        m = matcher or _matcher()
        body = _for_matching(text)
        found = set(m.symbols_in(body)) | set(m.names_in(body))
    except Exception:                                      # noqa: BLE001
        return True                    # fails open, and is not cached
    got = name in found
    if len(_NAMES_CACHE) > 20000:      # a day of rows is a few hundred
        _NAMES_CACHE.clear()
    _NAMES_CACHE[key] = got
    return got


# How long the board's standing causes are held before being read
# again. A standing order is DAYS old by definition -- five minutes of
# staleness cannot change one -- and the events store is written by the
# collector, a different process, so nothing here misses its own write.
STANDING_CACHE_SECONDS = 300.0
# How long an EMPTY answer is held. See _standing_batch().
EMPTY_RETRY_SECONDS = 20.0
_STANDING_BATCH = {}
_REFRESHING = set()


def _day(on):
    """A date, whatever shape it arrived in.

    A datetime MUST become a date here. why() is called with one --
    core/why_moving.py has carried a note about that shape since
    August -- and datetime.isoformat() carries the time, so a datetime
    used as the cache key would miss on every single call and rebuild
    the board every second. That is the exact cost this cache exists
    to remove, arriving through the back door.
    """
    if on is None:
        return datetime.now().date()
    if isinstance(on, str):
        try:
            return datetime.fromisoformat(on[:10]).date()
        except ValueError:
            return datetime.now().date()
    if isinstance(on, datetime):       # datetime IS a date -- check first
        return on.date()
    return on


def _standing_batch(today):
    """Every standing cause on the board, in one pass, held briefly.

    ---- ONE QUERY A CYCLE, NOT ONE A STOCK. 6 September 2026. ----

    standing_causes() has carried this note since the day it was
    written -- "asking per symbol would be 1,800 queries a cycle" --
    and then the gate went in and started asking per symbol, on the
    path that runs every second. Measured before this: 23.5 ms a
    symbol through why(), against 4.7 ms before the gate existed.

    So the gate reads the same batch the board does. One code path,
    which is also why the two can no longer disagree.
    """
    key = today.isoformat()
    hit = _STANDING_BATCH.get(key)
    now = time.monotonic()
    if hit is not None and hit[0] > now:
        return hit[1]

    # ---- STALE BEATS SLOW, ON THIS PATH. 6 September 2026. ----
    #
    # Proved rather than assumed: with a writer holding the store, a
    # read WAITED 8.67 s and then returned the right answer. Correct,
    # and completely wrong for a loop that runs every second -- the
    # collector writes this file from another process all session and
    # the journal mode is `delete`, so any reader blocks during a
    # write.
    #
    # So an EXPIRED board is served as it is and rebuilt on a thread.
    # A standing cause is days old by definition; five minutes of
    # staleness cannot change one, and the entry loop never waits for
    # a disk at all. Only the very first build is synchronous, and
    # main.py does that before the feed connects -- see warm().
    if hit is not None:
        _refresh_soon(today, key)
        return hit[1]

    built = standing_causes(on=today)
    lifetime = STANDING_CACHE_SECONDS if built else EMPTY_RETRY_SECONDS
    _STANDING_BATCH.clear()            # yesterday's board is not today's
    _STANDING_BATCH[key] = (now + lifetime, built)
    return built


def _rebuild(today, key):
    """Read the board again and swap it in. Runs off the entry loop."""
    try:
        built = standing_causes(on=today)
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MEMORY] standing causes could not be re-read "
                   f"({exc}) -- keeping the board already held")
        built = {}
    now = time.monotonic()
    previous = _STANDING_BATCH.get(key)
    if not built and previous is not None and previous[1]:
        # The read failed, or the store was locked. standing_causes()
        # cannot tell us which. Keep the board we have and ask again
        # sooner rather than blanking every standing cause on it.
        _STANDING_BATCH[key] = (now + EMPTY_RETRY_SECONDS, previous[1])
    else:
        lifetime = STANDING_CACHE_SECONDS if built else EMPTY_RETRY_SECONDS
        _STANDING_BATCH[key] = (now + lifetime, built)
    _REFRESHING.discard(key)


def _refresh_soon(today, key):
    """One rebuild at a time, and never on the caller's thread."""
    if key in _REFRESHING:
        return
    _REFRESHING.add(key)
    try:
        thread = threading.Thread(target=_rebuild, args=(today, key),
                                  name="standing-causes", daemon=True)
        thread.start()
    except Exception as exc:                               # noqa: BLE001
        # A process that cannot start a thread still gets an answer:
        # the board already held, and another attempt next call.
        _REFRESHING.discard(key)
        diagnostic(f"[MEMORY] could not refresh the standing causes "
                   f"in the background ({exc})")


def standing_reason(symbol, on=None, events_db=None):
    """A standing order big enough to still be a REASON, or None.

    The one function in this module the trading path may call. See
    STANDING_GATE_MIN_PCT for the measurement behind the bar and for
    what this deliberately does not do.

    Returns the same shape core/ranker.py's mechanism_of() expects --
    {"text", "weight", "direction", "source"} -- so nothing downstream
    needs a new field.

    Never raises. A memory that cannot be read means no reason, which
    is exactly what the bot did before this existed.
    """
    try:
        if events_db is None:
            # The live path. One pass for the whole board, held for
            # STANDING_CACHE_SECONDS -- see _standing_batch().
            got = _standing_batch(_day(on)).get(str(symbol or "").upper())
        else:
            # An explicit store: a test, or a tool asking about a
            # specific file. Read it directly and cache nothing.
            got = standing_cause(symbol, on=on, events_db=events_db)
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MEMORY] standing_reason({symbol}) failed: {exc}")
        return None
    if not got:
        return None
    share = got.get("pct_of_company")
    if share is None or share < STANDING_GATE_MIN_PCT:
        return None
    # An "order" larger than the whole company is the store reporting a
    # bad row -- see the NUVAMA case in _sentence(). It must never open
    # a door.
    if share > 100.0:
        diagnostic(f"[MEMORY] {symbol}: a stored order reads as "
                   f"{share:.0f}% of the company -- not a reason")
        return None
    if got.get("sessions_ago", 0) > STANDING_GATE_SESSIONS:
        return None
    return {
        "text": got["text"],
        # Below a fresh, graded event on purpose. This is a cause that
        # is still standing, not news that broke this morning, and when
        # both exist the fresh one should rank first.
        "weight": 0.45,
        "direction": "POSITIVE",
        "at": got.get("date"),
        "source": "standing order",
        "pct_of_company": share,
        "sessions_ago": got.get("sessions_ago"),
    }


def standing_causes(on=None, events_db=None, min_cr=None, days=None):
    """{symbol: sentence} for every stock carrying a standing cause.

    One pass, because the board draws this beside any symbol it shows
    and asking per symbol would be 1,800 queries a cycle. Same rules as
    standing_cause() -- the headline must name the company and must
    still read as an order of that size today.
    """
    floor = STANDING_MIN_CR if min_cr is None else float(min_cr)
    window = STANDING_DAYS if days is None else int(days)
    today = on or datetime.now().date()
    if isinstance(today, str):
        try:
            today = datetime.fromisoformat(today[:10]).date()
        except ValueError:
            today = datetime.now().date()
    try:
        conn = sqlite3.connect("file:" + (events_db or EVENTS_DB)
                               + "?mode=ro", uri=True, timeout=30)
        rows = conn.execute(
            "SELECT symbol, date(at), value_cr, headline FROM events "
            "WHERE kind IN (%s) AND value_cr >= ? AND symbol IS NOT NULL "
            "AND symbol != '' AND date(at) >= date(?, ?) "
            "AND date(at) <= date(?) ORDER BY value_cr DESC, date(at) ASC"
            % ",".join("?" * len(STANDING_KINDS)),
            STANDING_KINDS + (floor, today.isoformat(),
                              f"-{window} day", today.isoformat())
        ).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[MEMORY] standing_causes failed: {exc}")
        return {}

    out = {}
    for symbol, day, value, headline in rows:
        name = str(symbol or "").upper()
        if not name or name in out:
            continue                       # biggest first, so keep it
        if not _headline_names(name, headline):
            continue
        if not _still_reads_as_an_order(headline, value):
            continue
        ago = _sessions_between(day, today)
        if ago is None:
            continue
        out[name] = _sentence(name, day, value, headline, ago)
    return out


_SESSION_CACHE = {}


def _sessions_cached(daily_db=None):
    """The session list, read once.

    ---- 4.7 SECONDS FOR 36 SENTENCES. 5 September 2026. ----

    standing_causes() called _sessions_between() per row and that read
    every distinct date out of daily_candles.db each time -- 36 full
    scans of a 218 MB store to answer "how many sessions ago". The
    board rebuilds on a one-second loop; five seconds inside it is not
    a slow feature, it is a broken one.

    The list only changes when a session ends, so it is cached under
    the store's own path. See core/board_rebuild -- the same lesson,
    twice.
    """
    key = daily_db or DAILY_DB
    if key not in _SESSION_CACHE:
        _SESSION_CACHE[key] = _sessions(daily_db)
    return _SESSION_CACHE[key]


def _sessions_between(day, today, daily_db=None):
    """Trading sessions from `day` to `today`, or None if unknown.

    Falls back to calendar days when the candle store cannot be read --
    an approximate age beats no sentence at all, and it is only ever
    displayed.
    """
    try:
        sessions = _sessions_cached(daily_db)
        after = [s for s in sessions
                 if day < s <= today.isoformat()]
        if after:
            return len(after)
    except Exception:                                      # noqa: BLE001
        pass
    try:
        when = datetime.fromisoformat(str(day)[:10]).date()
        return max(0, (today - when).days)
    except Exception:                                      # noqa: BLE001
        return None


def sector_shock(sector=None, since=None, limit=20, db_path=None):
    """Causes whose effect landed on the SECTOR, not the subject.

    ---- ULTRATECH, 1 September 2026. ----

    The announcement moved POLYCAB -5.8%, KEI -6.8%, RRKABEL -2.0% and
    left ULTRACEMCO at -0.4%. Filed under ULTRACEMCO, an event store
    can never surface that. This asks the question the other way
    round: which causes moved everyone EXCEPT the company named?

    Ordered by how much the peers moved relative to the subject.
    """
    conn = _connect(db_path)
    try:
        sql = ("SELECT date, symbol, kind, sector, subject_1d, peers_1d, "
               "peer_count, headline FROM cause_effect "
               "WHERE peers_1d IS NOT NULL AND subject_1d IS NOT NULL")
        args = []
        if sector:
            sql += " AND sector = ?"
            args.append(sector)
        if since:
            sql += " AND date >= ?"
            args.append(since)
        sql += (" ORDER BY ABS(peers_1d) - ABS(subject_1d) DESC LIMIT ?")
        args.append(int(limit))
        rows = conn.execute(sql, tuple(args)).fetchall()
    finally:
        conn.close()
    return [{"date": r[0], "symbol": r[1], "kind": r[2], "sector": r[3],
             "subject_1d": r[4], "peers_1d": r[5], "peer_count": r[6],
             "headline": r[7]} for r in rows]
