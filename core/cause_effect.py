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
from datetime import datetime

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
