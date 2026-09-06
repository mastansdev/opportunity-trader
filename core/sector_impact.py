"""
==========================================================
Who else does this land on
==========================================================

    "recent ultratech announced its wire & cables capex. then bot
     needs to check ultratech business (positive to neutral or non
     event too until the real business lands) + wires & cables business
     companies (for this sector its negative update) ... it will be
     recorded in memory that this day this sector is impacted by that
     company & impacted stocks performance on event day"
                                -- the operator, 6 September 2026

THE EVENT HE NAMED, AND WHAT IT DID. 1 September 2026, "ULTRATECH
CEMENT: CO. COMMENCES COMMERCIAL PRODUCTION OF 11 LAKH KM WIRES &
CABLES PLANT":

    ULTRACEMCO   -0.44%   the announcer -- a non-event, as he said
    KEI          -6.83%   high -2.30%, never green all day
    POLYCAB      -5.82%   high -2.50%, never green all day
    RRKABEL      -2.00%   and -8.34% the next day
    APARINDS     -1.71%   and -3.37% the next day

The bot watched all of that and learned nothing, because nothing
wrote down that a sector had been hit.

THE RULE IS ONE SENTENCE. A business named in the headline that the
announcer is NOT already in, is a business it is entering. Measured on
his example:

    tags in the headline    CABLES, CEMENT, WIRES
    CABLES    6 incumbents, ULTRACEMCO not one    -> entering
    WIRES     3 incumbents, ULTRACEMCO not one    -> entering
    CEMENT   50 incumbents, ULTRACEMCO IS one     -> its own trade

CEMENT falling out on its own is the point. No list of "expansion
words", no guess about intent -- if the company is already in that
business, the headline is about its own operations.

IT TRADES NOTHING. Long only, MTF, no shorting, so the side this
usually identifies cannot be acted on at all. It is a MEMORY: after a
dozen of these the bot can answer from its own book how far incumbents
fall when a large company walks into their market, and for how long.
The mirror case -- an event that is GOOD for a sector -- is the one
that becomes tradeable, and today the bot cannot see either.

NOTHING IN THE TRADING PATH IMPORTS THIS, and a test enforces that.
It is built from the stored events after the fact, never on the tick
path -- same shape as core/cause_effect.build().

A NOTE ON WHAT WAS NOT BUILT. The same day, the bot was shown to file
a competitor's expansion as a plain NEWS reason ON THE INCUMBENT --
why(symbol="KEI") returns UltraTech's launch with direction UNKNOWN
and weight 0.6. I claimed that could reach a buy and could not show
it: the 3% and volume gates refused KEI on all three days, and two
attempts to measure the frequency produced numbers that were my own
detectors misfiring. So no gate was added. See
[[verify-the-value-the-live-path-reads]] -- a mechanism is not a
measurement.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sqlite3
from datetime import datetime

from core.logger import decision, diagnostic

DB_PATH = os.path.join("data", "sector_impact.db")
EVENTS_DB = os.path.join("data", "stock_events.db")
DAILY_DB = os.path.join("data", "daily_candles.db")

# Which master columns describe what a company DOES. SECTOR is left
# out deliberately: it is far too broad -- "Capital Goods" holds 137
# companies and tells you nothing about who competes with whom.
BUSINESS_COLUMNS = ("THEMES", "KEYWORDS", "INDUSTRY")

# A tag naming one company is not a sector, and a tag naming eighty is
# the whole market. Both extremes teach nothing, so both are skipped.
MIN_INCUMBENTS = 2
MAX_INCUMBENTS = 30

# Short tags match inside ordinary words. Four characters is the
# shortest that has survived reading the list.
MIN_TAG_LENGTH = 4

# Beyond this, a one-day "move" is a split or a bonus with an
# unadjusted previous close, not a price. See _day_move().
CORPORATE_ACTION_PCT = 35.0

# ---- A MENTION IS NOT AN ENTRY. 6 September 2026. ----
#
# The first cut asked only "is a business named here that this company
# is not already in". Run over three weeks of real events it produced:
#
#     TCS        entered METRO      a word in a headline
#     PURVA      entered MUMBAI     a place, not a business
#     SPECTRUM   entered RURAL
#     DIACABS    entered POWER      it IS a power cable company, just
#                                   not tagged as one in the master
#
# I had said no list of expansion words was needed and that was wrong.
# His own example carries one -- "COMMENCES COMMERCIAL PRODUCTION OF
# 11 LAKH KM WIRES & CABLES PLANT". The announcement has to SAY the
# company is moving in; a business merely named is a mention.
#
# Deliberately narrow. A missed entry costs a row in a memory. A false
# one teaches the bot something that never happened.
ENTRY_SIGNALS = re.compile(
    r"enters?\s+(?:the\s+)?[a-z\s&]{0,20}"
    r"(?:market|business|segment|space|sector)"
    r"|entered\s+(?:the\s+)?[a-z\s&]{0,20}(?:market|business|segment)"
    r"|foray(?:s|ed|ing)?\b"
    r"|diversif(?:y|ies|ied|ication)"
    r"|(?:commence|begin)(?:s|d|ning)?\s+(?:commercial\s+)?production"
    r"|launch(?:es|ed|ing)?\s+(?:its\s+)?(?:new\s+)?[a-z&\s']{0,26}"
    r"(?:brand|business|vertical|range|plant)"
    r"|sets?\s+up\s+(?:a\s+)?(?:new\s+)?(?:plant|facility|unit)"
    r"|greenfield"
    r"|new\s+(?:manufacturing\s+)?(?:plant|facility)"
    r"|expand(?:s|ed|ing)?\s+into"
    r"|to\s+manufacture",
    re.IGNORECASE)


def announces_an_entry(headline):
    """Does this headline SAY the company is moving into a business?"""
    return bool(ENTRY_SIGNALS.search(str(headline or "")))


_TAGS = None


def reset():
    """Forget the tag index. Tests, and a rebuilt master file."""
    global _TAGS
    _TAGS = None


def business_tags():
    """{tag: frozenset(symbols)} -- every business the master names.

    Built from core/sector_map.py, never from a private copy. If the
    master gains a tag tomorrow this sees it.
    """
    global _TAGS
    if _TAGS is not None:
        return _TAGS
    out = {}
    try:
        from core import sector_map
        counts = sector_map.tag_counts() or {}
        wanted = set()
        for column in BUSINESS_COLUMNS:
            for tag, _n in counts.get(column, ()) or ():
                name = str(tag or "").strip().upper()
                if len(name) >= MIN_TAG_LENGTH:
                    wanted.add(name)
        for name in wanted:
            symbols = set()
            for group in sector_map.carrying(name) or ():
                if str(group.get("column") or "").upper() in BUSINESS_COLUMNS:
                    symbols.update(group.get("symbols") or ())
            if MIN_INCUMBENTS <= len(symbols) <= MAX_INCUMBENTS:
                out[name] = frozenset(symbols)
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[SECTOR] could not read the business tags ({exc})")
        return {}
    _TAGS = out
    return out


def businesses_in(headline):
    """Every known business this headline names, longest first.

    Whole words only. "WIRES" must not match inside another word, and
    a longer tag is reported before the shorter one it contains so
    "AUTO COMPONENTS" wins over "AUTO".
    """
    text = str(headline or "").upper()
    if not text.strip():
        return []
    found = []
    for tag in business_tags():
        if re.search(r"(?<![A-Z0-9])" + re.escape(tag) + r"(?![A-Z0-9])",
                     text):
            found.append(tag)
    found.sort(key=len, reverse=True)
    return found


#: Two business tags this close together in the text are one market.
#: "WIRES & CABLES" is a single phrase; "CABLES ... SUPPORTING
#: INFRASTRUCTURE" is a business and then some context.
ADJACENT_CHARS = 6


def _spans(headline, tags):
    """Where each tag sits in the text: {tag: (start, end)}."""
    text = str(headline or "").upper()
    out = {}
    for tag in tags:
        m = re.search(r"(?<![A-Z0-9])" + re.escape(tag) + r"(?![A-Z0-9])",
                      text)
        if m:
            out[tag] = m.span()
    return out


def _one_market(headline, tags):
    """The tags that form ONE market with the tightest of them.

    ---- 23 INFRASTRUCTURE BUILDERS. 6 September 2026. ----

    Taking the union of every business named pulled his own example
    from 7 companies to 30, because the headline ends "...WIRES &
    CABLES PLANT AT BHARUCH SUPPORTING INFRASTRUCTURE" and nothing
    said INFRASTRUCTURE was a different subject. Taking only the
    tightest tag went the other way and dropped the CABLES-only names.

    The text already says which is which: "WIRES & CABLES" is one
    phrase, INFRASTRUCTURE is twenty characters further on. So tags
    are joined only while they are touching.
    """
    spans = _spans(headline, tags)
    if not spans:
        return []
    ordered = sorted(spans.items(), key=lambda kv: kv[1][0])
    clusters, current = [], [ordered[0]]
    for tag, span in ordered[1:]:
        if span[0] - current[-1][1][1] <= ADJACENT_CHARS:
            current.append((tag, span))
        else:
            clusters.append(current)
            current = [(tag, span)]
    clusters.append(current)

    index = business_tags()
    tightest = min(spans, key=lambda t: len(index.get(t) or ()))
    for cluster in clusters:
        names = [t for t, _s in cluster]
        if tightest in names:
            return names
    return [tightest]


def entering(symbol, headline):
    """The businesses this company is walking INTO, or [].

    A business it is already in is its own operations, not an entry --
    that is what drops CEMENT out of UltraTech's wires-and-cables
    announcement without needing to know what "commences commercial
    production" means.
    """
    name = str(symbol or "").strip().upper()
    if not name:
        return []
    tags = business_tags()
    out = []
    for tag in businesses_in(headline):
        holders = tags.get(tag) or frozenset()
        if name not in holders:
            out.append(tag)
    return out


def impact_of(symbol, headline):
    """{"entrant", "business", "incumbents", "also_named"} or None.

    Every company in any business it is entering, each appearing once.
    `business` is the tightest tag matched -- the most specific true
    name for the row -- and `also_named` keeps the rest, so the reason
    the list is as wide as it is can always be read back.
    """
    name = str(symbol or "").strip().upper()
    if not announces_an_entry(headline):
        return None                    # a mention is not an entry
    entered = entering(name, headline)
    if not entered:
        return None
    tags = business_tags()
    # ---- THE UNION, NOT THE TIGHTEST. 6 September 2026. ----
    #
    # The first version kept only the smallest tag, so his own example
    # recorded WIRES (KEI, POLYCAB, RRKABEL) and quietly dropped the
    # CABLES-only names -- APARINDS, UNIVCABLES, DYCL, KEC. "Wires and
    # cables" is ONE market and he named it as one.
    #
    # A set union, so a company in both tags still gets exactly one
    # row. The tightest tag names the row because it is the most
    # specific true description; the rest are kept in also_named so
    # the reason for the wider list is never lost.
    entered = _one_market(headline, entered)
    holders = set()
    for tag in entered:
        holders |= set(tags.get(tag) or ())
    holders = sorted(holders)
    if len(holders) < MIN_INCUMBENTS or len(holders) > MAX_INCUMBENTS:
        return None
    best = min(entered, key=lambda t: len(tags.get(t) or ()))
    return {"entrant": name, "business": best, "incumbents": holders,
            "also_named": [t for t in entered if t != best]}


# ------------------------------------------------------------------
# what each of them did
# ------------------------------------------------------------------

def _day_move(symbol, day, daily_db=None):
    """{"move_pct", "high_pct", "low_pct"} for one stock on one day."""
    try:
        conn = sqlite3.connect("file:" + (daily_db or DAILY_DB) + "?mode=ro",
                               uri=True, timeout=30)
        row = conn.execute(
            "SELECT close, high, low, prev_close FROM daily_bars "
            "WHERE date = date(?) AND symbol = ?", (day, symbol)).fetchone()
        conn.close()
    except Exception:                                      # noqa: BLE001
        return None
    if not row or not row[3]:
        return None
    close, high, low, prev = row
    move = (close - prev) / prev * 100.0

    # ---- A SPLIT IS NOT A FALL. 6 September 2026. ----
    #
    # The first scan reported "VOLTAS entered COMPRESSORS, worst
    # incumbent -50.45%". That incumbent was KIRLPNU, which went
    # 1,534.30 to 760.20 on 18 August -- a 1:2 split with prev_close
    # never adjusted, not a company losing half its value.
    #
    # This is a memory the bot will reason from later. A wrong number
    # in it is worse than a missing one, so the row is dropped and
    # said out loud rather than stored as a fact.
    if abs(move) > CORPORATE_ACTION_PCT:
        diagnostic(f"[SECTOR] {symbol} on {day} reads {move:+.1f}% -- "
                   f"that is a corporate action, not a move. Not recorded.")
        return None

    return {"move_pct": round(move, 2),
            "high_pct": round((high - prev) / prev * 100.0, 2),
            "low_pct": round((low - prev) / prev * 100.0, 2)}


def _connect(path=None):
    conn = sqlite3.connect(path or DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sector_impact (
            id INTEGER PRIMARY KEY,
            day TEXT, business TEXT, entrant TEXT,
            symbol TEXT, role TEXT,
            move_pct REAL, high_pct REAL, low_pct REAL,
            headline TEXT, source TEXT, recorded_at TEXT)""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_impact "
                 "ON sector_impact (day, business, entrant, symbol)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_impact_business "
                 "ON sector_impact (business, day)")
    conn.commit()
    return conn


def record(symbol, headline, day, source=None, db_path=None, daily_db=None):
    """Write down who was hit, and what each of them did that day.

    Returns how many rows were written. Never raises: a memory that
    cannot be written must not stop whatever was writing it.
    """
    got = impact_of(symbol, headline)
    if not got:
        return 0
    day = str(day)[:10]
    rows = [(got["entrant"], "ENTRANT")]
    rows += [(s, "INCUMBENT") for s in got["incumbents"]]
    written = 0
    try:
        conn = _connect(db_path)
        for name, role in rows:
            moved = _day_move(name, day, daily_db)
            if moved is None:
                continue
            conn.execute(
                "INSERT OR REPLACE INTO sector_impact (day, business, "
                "entrant, symbol, role, move_pct, high_pct, low_pct, "
                "headline, source, recorded_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (day, got["business"], got["entrant"], name, role,
                 moved["move_pct"], moved["high_pct"], moved["low_pct"],
                 str(headline or "")[:300], source,
                 datetime.now().isoformat(timespec="seconds")))
            written += 1
        conn.commit()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[SECTOR] could not record {symbol}/{day}: {exc}")
        return 0
    return written


def scan(since=None, events_db=None, db_path=None, daily_db=None,
         limit=None):
    """Walk the stored events and record every sector impact found.

    Run after the close, or from a tool. Reads the event store; never
    called from the trading path.
    """
    since = str(since or "2026-08-01")[:10]
    try:
        conn = sqlite3.connect("file:" + (events_db or EVENTS_DB)
                               + "?mode=ro", uri=True, timeout=30)
        rows = conn.execute(
            "SELECT date(at), symbol, headline, source FROM events "
            "WHERE symbol IS NOT NULL AND symbol != '' "
            "AND date(at) >= date(?) ORDER BY at", (since,)).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[SECTOR] could not read the events ({exc})")
        return {"events": 0, "impacts": 0, "rows": 0}

    seen, impacts, written = 0, 0, 0
    for day, symbol, headline, source in rows:
        seen += 1
        n = record(symbol, headline, day, source=source,
                   db_path=db_path, daily_db=daily_db)
        if n:
            impacts += 1
            written += n
        if limit and impacts >= limit:
            break
    decision(f"[SECTOR] {seen} events read, {impacts} of them landed on "
             f"another sector, {written} company-days recorded.")
    return {"events": seen, "impacts": impacts, "rows": written}


# ------------------------------------------------------------------
# reading it back
# ------------------------------------------------------------------

def recall(business=None, entrant=None, days=180, db_path=None):
    """Every recorded impact, newest first. One row per company-day."""
    where, params = [], []
    if business:
        where.append("business = ?")
        params.append(str(business).upper())
    if entrant:
        where.append("entrant = ?")
        params.append(str(entrant).upper())
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        conn = _connect(db_path)
        rows = conn.execute(
            "SELECT day, business, entrant, symbol, role, move_pct, "
            "high_pct, low_pct, headline FROM sector_impact" + clause +
            " ORDER BY day DESC, role DESC, symbol", params).fetchall()
        conn.close()
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"[SECTOR] could not read the memory ({exc})")
        return []
    keys = ("day", "business", "entrant", "symbol", "role", "move_pct",
            "high_pct", "low_pct", "headline")
    return [dict(zip(keys, r)) for r in rows][:2000] if days else []


def what_happened(business=None, db_path=None):
    """One line per event: who walked in, and what the incumbents did.

    Grouped by EVENT, never pooled across events -- each entry into a
    market is its own story, and averaging them is the thing he has
    said not to do.
    """
    rows = recall(business=business, db_path=db_path)
    by_event = {}
    for row in rows:
        key = (row["day"], row["business"], row["entrant"])
        by_event.setdefault(key, {"entrant": None, "incumbents": []})
        if row["role"] == "ENTRANT":
            by_event[key]["entrant"] = row
        else:
            by_event[key]["incumbents"].append(row)
    out = []
    for (day, business, entrant), got in sorted(by_event.items(),
                                                reverse=True):
        hit = got["incumbents"]
        fell = [r for r in hit if (r.get("move_pct") or 0) < 0]
        out.append({
            "day": day, "business": business, "entrant": entrant,
            "entrant_move": (got["entrant"] or {}).get("move_pct"),
            "incumbents": len(hit),
            "fell": len(fell),
            "worst": min((r.get("move_pct") for r in hit
                          if r.get("move_pct") is not None), default=None),
            "names": [r["symbol"] for r in hit],
        })
    return out
