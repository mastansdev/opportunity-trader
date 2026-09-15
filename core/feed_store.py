"""
==========================================================
One store for the two feeds, so main.py can stop polling
==========================================================

    "why still NEWS is printing in main.py terminal ? ... in live
     markets only 2 terminals - main.py & news (news+rss++nse+bse+9 pro
     channels)"
    "PLS DO NOT COMBINE MAIN.PY"
                                    -- operator, 2-3 August 2026

THE BLOCKER, AND WHY IT TOOK THIS LONG
--------------------------------------
Telegram moved out of main.py days ago because it already had a
database: the collector writes data/stock_events.db, main.py reads it,
and neither knows about the other.

These two had no database at all. AnnouncementWatcher keeps `self._today`
in memory and NewsWatcher keeps `self._items`, so moving the polling out
of main.py would have taken the DATA out with it -- and both feed
`results_gate`, which decides whether 83 reporting stocks may be traded.
That is not a panel going blank; that is the trading loop losing an
input it gates on.

So the data needs a home first. This is that home.

WHO WRITES AND WHO READS
------------------------
    tools/collector.py   runs the watchers, writes here      (2nd terminal)
    main.py              reads here, polls nothing           (1st terminal)

Exactly the arrangement stock_events.db already has. If the collector
dies, these tables stop updating and the trading loop carries on with
the last thing it read -- which is the same failure mode as the chips,
and one the operator has already accepted.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
No scoring, no direction, no interpretation. Rows in, rows out. The
watchers still decide what a filing means; this only remembers it.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta

from core.logger import diagnostic, warn

DB_PATH = os.path.join("data", "feeds.db")

# Rows older than this are dropped on write. Both panels show "today",
# and a store that grows forever becomes the slow query that makes the
# dashboard feel broken.
KEEP_HOURS = 48


class FeedStore:
    """Announcements and news, on disk, shared between two processes."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ready = False
        self._local = threading.local()
        self._ensure()

    # ---- ONE READ CONNECTION PER THREAD. 15 September 2026. ----
    #
    # py-spy on the live bot, 10:00: the shortlist rebuild and the tick
    # worker were both sitting in _connect() -- a NEW sqlite connection
    # plus a PRAGMA journal_mode=WAL for every single for_symbol() call,
    # i.e. for every stock, every rebuild, every second. That is the
    # rebuild that took 40-125s and starved the price thread.
    #
    # Reads reuse one connection per thread (sqlite connections may not
    # cross threads). WAL is a property of the FILE, set once by the
    # writer in _ensure(); a reader does not need to ask again. Writes
    # still open and close their own, unchanged.
    def _reader(self):
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=10)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def _drop_reader(self):
        conn = getattr(self._local, "conn", None)
        self._local.conn = None
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    # ------------------------------------------------------------

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        # The Windows mount corrupted stock_events.db once under
        # concurrent writes. WAL is the documented answer and costs
        # nothing here.
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return conn

    def _ensure(self):
        try:
            directory = os.path.dirname(self.db_path)
            if directory:
                os.makedirs(directory, exist_ok=True)
            conn = self._connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS feed_rows (
                    kind     TEXT NOT NULL,      -- 'announcement' | 'news'
                    ident    TEXT NOT NULL,      -- de-dupe key
                    symbol   TEXT,
                    at       TEXT,               -- ISO, for ordering
                    seen_at  TEXT,
                    body     TEXT NOT NULL,      -- the row, as JSON
                    PRIMARY KEY (kind, ident)
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_feed_kind_at "
                         "ON feed_rows (kind, at DESC)")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_feed_symbol "
                         "ON feed_rows (kind, symbol)")
            conn.commit()
            conn.close()
            self._ready = True
        except (sqlite3.Error, OSError) as exc:
            # OSError as well as sqlite3.Error, and that is not
            # defensive padding: makedirs(exist_ok=True) still raises
            # FileExistsError when the path exists as a FILE, so a bad
            # db_path used to CRASH this constructor rather than
            # degrade -- and main.py builds one of these at startup.
            # 3 August 2026.
            warn(f"[FEEDS] Could not open {self.db_path}: {exc}. "
                 f"The panels will be empty; trading is unaffected.")
            self._ready = False

    # ---- write side: the collector only -------------------------

    def save(self, kind, rows, ident_of):
        """Store rows. Returns how many were new. Never raises."""
        if not self._ready or not rows:
            return 0
        now = datetime.now()
        payload = []
        for row in rows:
            try:
                raw = ident_of(row)
            except Exception:                              # noqa: BLE001
                continue
            # str(None) is "None" -- truthy, and it would have stored a
            # row with no identity under a key that every other
            # identity-less row also collides with. 3 August 2026.
            if raw is None:
                continue
            ident = str(raw).strip()
            if not ident:
                continue
            payload.append((
                kind, ident,
                str(row.get("symbol") or "").upper() or None,
                str(row.get("_at") or row.get("at") or row.get("filed_at")
                    or row.get("published") or now.isoformat()),
                now.isoformat(),
                json.dumps(row, default=str),
            ))
        if not payload:
            return 0
        try:
            with self._lock:
                conn = self._connect()
                before = conn.execute(
                    "SELECT COUNT(*) FROM feed_rows WHERE kind=?",
                    (kind,)).fetchone()[0]
                conn.executemany(
                    "INSERT OR REPLACE INTO feed_rows "
                    "(kind, ident, symbol, at, seen_at, body) "
                    "VALUES (?,?,?,?,?,?)", payload)
                cutoff = (now - timedelta(hours=KEEP_HOURS)).isoformat()
                conn.execute("DELETE FROM feed_rows WHERE seen_at < ?",
                             (cutoff,))
                conn.commit()
                after = conn.execute(
                    "SELECT COUNT(*) FROM feed_rows WHERE kind=?",
                    (kind,)).fetchone()[0]
                conn.close()
            return max(0, after - before)
        except sqlite3.Error as exc:
            warn(f"[FEEDS] Could not write {kind}: {exc}")
            return 0

    # ---- read side: main.py and the dashboard -------------------

    def rows(self, kind, limit=25):
        """Newest first. Always a list, even when the store is broken."""
        if not self._ready:
            return []
        try:
            conn = self._connect()
            found = conn.execute(
                "SELECT body FROM feed_rows WHERE kind=? "
                "ORDER BY at DESC, seen_at DESC LIMIT ?",
                (kind, limit)).fetchall()
            conn.close()
        except sqlite3.Error as exc:
            diagnostic(f"[FEEDS] Could not read {kind}: {exc}")
            return []
        out = []
        for record in found:
            try:
                out.append(json.loads(record["body"]))
            except (ValueError, TypeError):
                continue
        return out

    def count(self, kind):
        if not self._ready:
            return 0
        try:
            conn = self._connect()
            n = conn.execute("SELECT COUNT(*) FROM feed_rows WHERE kind=?",
                             (kind,)).fetchone()[0]
            conn.close()
            return n
        except sqlite3.Error:
            return 0

    def for_symbol(self, kind, symbol):
        """The newest row for one stock, or None.

        None means "nothing filed", which is what the caller has always
        been given and what results_gate reads.
        """
        if not self._ready or not symbol:
            return None
        try:
            # fetchall, not fetchone: a cursor left unfinished holds a
            # read transaction open on a reused connection, which would
            # pin an old snapshot and stop the WAL checkpointing.
            rows = self._reader().execute(
                "SELECT body FROM feed_rows WHERE kind=? AND symbol=? "
                "ORDER BY at DESC, seen_at DESC LIMIT 1",
                (kind, str(symbol).upper())).fetchall()
            found = rows[0] if rows else None
        except sqlite3.Error:
            self._drop_reader()
            return None
        if not found:
            return None
        try:
            return json.loads(found["body"])
        except (ValueError, TypeError):
            return None

    def symbols(self, kind):
        if not self._ready:
            return set()
        try:
            found = self._reader().execute(
                "SELECT DISTINCT symbol FROM feed_rows "
                "WHERE kind=? AND symbol IS NOT NULL", (kind,)).fetchall()
            return {r["symbol"] for r in found}
        except sqlite3.Error:
            self._drop_reader()
            return set()

    def last_write(self, kind):
        if not self._ready:
            return None
        try:
            conn = self._connect()
            found = conn.execute(
                "SELECT MAX(seen_at) AS t FROM feed_rows WHERE kind=?",
                (kind,)).fetchone()
            conn.close()
            return found["t"] if found else None
        except sqlite3.Error:
            return None


# ---------------------------------------------------------------
# Read-only stand-ins, shaped exactly like the live watchers
# ---------------------------------------------------------------
#
# main.py builds these instead of the real thing. Same three methods
# the rest of the code already calls -- for_symbol(), snapshot() and
# symbols_today() -- so nothing downstream changes and results_gate
# cannot tell the difference.

class StoredFeed:
    """Base: the read half of a watcher, backed by the store."""

    KIND = "news"
    LABEL = "feed"

    def __init__(self, store=None, db_path=DB_PATH):
        self.store = store or FeedStore(db_path)

    def for_symbol(self, symbol):
        return self.store.for_symbol(self.KIND, symbol)

    def symbols_today(self):
        return self.store.symbols(self.KIND)

    def snapshot(self, limit=25):
        rows = self.store.rows(self.KIND, limit=limit)
        last = self.store.last_write(self.KIND)
        return {
            "rows": rows,
            "count_today": self.store.count(self.KIND),
            "last_poll_at": (str(last)[11:19] if last else None),
            "poll_count": None,
            "error": None,
            # Said plainly, because "no rows" and "the collector is not
            # running" are different sentences and only one of them is
            # his problem to fix.
            "collected_by": "py tools/collector.py",
            "available": bool(rows) or last is not None,
        }

    # The live watchers own these; a reader must not pretend to.
    def start(self):
        raise NotImplementedError(
            f"{self.LABEL} is collected by py tools/collector.py, "
            f"not by this process.")

    def stop(self, timeout=3):
        return None


class StoredAnnouncements(StoredFeed):
    KIND = "announcement"
    LABEL = "Filings"


class StoredNews(StoredFeed):
    KIND = "news"
    LABEL = "News"
