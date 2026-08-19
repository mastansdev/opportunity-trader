"""
==========================================================
Every pick the bot would have made, written down
==========================================================

    "phase-1 bot will trade (assumption) & record . after tomorrow
     market closing we will verify & start the next phase-2"
    "30K is not trading tomorrow"
                                    -- operator, 4 August 2026

WHY THIS EXISTS BEFORE THE MONEY DOES
-------------------------------------
core/ranker.py now decides what the best stock of the day is. Its
weights -- W_EXCESS_SECTOR = 3.0 and the rest -- are my judgement and
nothing else. They have never been checked against an outcome, and
saying so is not modesty, it is the actual status.

So the bot spends a day picking with no money at stake, and every
decision is written here with the price at the moment it was made. At
the close, tools/verify_picks.py reads this back against what those
stocks actually did, and the answer is arithmetic rather than opinion.

Three things get recorded, and the third is the one that matters:

    THE PICK        symbol, direction, score, and the sentence
    THE PRICE       what it cost at the moment of the decision, so the
                    outcome can be measured rather than remembered
    THE REFUSALS    what was rejected and why

The refusals are the part a scorecard usually throws away. If the bot
refuses eleven stocks for "no reason found" and eight of them run 4%,
the mechanism gate is too strict and the number will say so. Without
this, the only thing measurable is what the bot chose, and a strategy
is also its declines.

NOTHING HERE TRADES, SIZES, OR DECIDES.
It is a notebook.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sqlite3
import threading
from datetime import datetime

DB_PATH = os.path.join("data", "decisions.db")


class DecisionLog:
    """Ranker output, per cycle, on disk."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ready = False
        self._last_key = None
        self._ensure()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.Error:
            pass
        return conn

    def _ensure(self):
        try:
            folder = os.path.dirname(self.db_path)
            if folder:
                os.makedirs(folder, exist_ok=True)
            conn = self._connect()
            conn.execute("""
                CREATE TABLE IF NOT EXISTS picks (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    date      TEXT NOT NULL,
                    at        TEXT NOT NULL,
                    rank      INTEGER NOT NULL,
                    symbol    TEXT NOT NULL,
                    action    TEXT NOT NULL,
                    score     REAL,
                    price     REAL,
                    change_pct   REAL,
                    excess_pct   REAL,
                    volume_x     REAL,
                    adv_cr       REAL,
                    sector       TEXT,
                    mechanism    TEXT,
                    why          TEXT,
                    market_pct   REAL,
                    detail       TEXT
                )""")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS refusals (
                    date TEXT NOT NULL, at TEXT NOT NULL,
                    reason TEXT NOT NULL, n INTEGER NOT NULL
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS ix_picks_date "
                         "ON picks (date, at)")
            conn.commit()
            conn.close()
            self._ready = True
        except (sqlite3.Error, OSError) as exc:
            # OSError as well: makedirs(exist_ok=True) still raises when
            # the path exists as a FILE, and this is built at startup.
            from core.logger import warn
            warn(f"[DECISIONS] Could not open {self.db_path}: {exc}. "
                 f"Picks will not be recorded; nothing else is affected.")
            self._ready = False

    def record(self, ranking, prices=None, when=None):
        """Store one cycle. Returns how many picks were written.

        Skips a cycle identical to the last one -- the ranker is asked
        on a clock, and writing the same five rows every thirty seconds
        would bury the moments something actually changed.
        """
        if not self._ready or not ranking:
            return 0
        rows = ranking.get("rows") or []
        if not rows:
            return 0

        now = when or datetime.now()
        key = "|".join(f"{r.get('symbol')}:{r.get('action')}" for r in rows)
        if key == self._last_key:
            return 0
        self._last_key = key

        prices = prices or {}
        stamp = now.strftime("%Y-%m-%d %H:%M:%S")
        day = now.strftime("%Y-%m-%d")
        payload = []
        for i, row in enumerate(rows, start=1):
            symbol = row.get("symbol")
            payload.append((
                day, stamp, i, symbol, row.get("action"),
                row.get("score"),
                prices.get(symbol) if prices.get(symbol) is not None
                else row.get("ltp"),
                row.get("change_pct"), row.get("excess_pct"),
                row.get("volume_x"), row.get("adv_cr"), row.get("sector"),
                (row.get("mechanism") or "")[:300], row.get("why"),
                ranking.get("market_pct"),
                json.dumps({k: v for k, v in row.items()
                            if k not in ("why", "mechanism")}, default=str),
            ))
        try:
            with self._lock:
                conn = self._connect()
                conn.executemany(
                    "INSERT INTO picks (date, at, rank, symbol, action, "
                    "score, price, change_pct, excess_pct, volume_x, "
                    "adv_cr, sector, mechanism, why, market_pct, detail) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", payload)
                conn.commit()
                conn.close()
        except sqlite3.Error as exc:
            from core.logger import diagnostic
            diagnostic(f"[DECISIONS] Could not write: {exc}")
            return 0
        return len(payload)

    def record_refusals(self, counts, when=None):
        """Why candidates were turned away, and how many of each.

        A strategy is also its declines. If "no reason found" rejects
        eleven names and eight of them run, the mechanism gate is wrong
        and only this table can say so.

        ---- TWO PRODUCERS, TWO SHAPES. 19 August 2026. ----

        Found in his live log, once, and silently:

            [RANK] Could not record: invalid literal for int() with
                   base 10: 'up only -13.1% -- not moving'

        Two modules publish a key called "refusals" and they do not
        agree on what it holds:

            core/ranker.py:930   {reason: count}    -- a census
            core/select.py:339   {symbol: reason}   -- a per-stock log

        This method expected the first and int()'d the value. Handed
        the second it raised -- and the int() sat OUTSIDE the try, so
        ONE unreadable entry threw away the WHOLE cycle's census,
        including every well-formed count beside it.

        The refusal table is how he finds out whether "no reason
        found x22" protected him or blinded him. Losing a cycle of it
        to a shape mismatch is exactly the kind of quiet gap this
        project keeps finding.

        Both shapes are meaningful and both are now recorded: values
        that are numbers are counts, values that are sentences are
        tallied by how often each sentence appears. Anything else is
        skipped and SAID, rather than taking the batch down with it.
        """
        if not self._ready or not counts:
            return 0
        now = when or datetime.now()

        tally = {}
        skipped = 0
        for key, value in counts.items():
            if isinstance(value, bool):
                skipped += 1
                continue
            if isinstance(value, (int, float)):
                tally[str(key)] = tally.get(str(key), 0) + int(value)
            elif isinstance(value, str) and value.strip():
                # {symbol: reason} -- the reason is what is counted,
                # because "how often was this refusal used" is the
                # question the table answers.
                tally[value.strip()] = tally.get(value.strip(), 0) + 1
            else:
                skipped += 1
        if skipped:
            from core.logger import diagnostic
            diagnostic(f"[DECISIONS] {skipped} refusal entr(ies) in an "
                       f"unreadable shape were skipped; the rest were "
                       f"recorded.")
        if not tally:
            return 0
        rows = [(now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d %H:%M:%S"),
                 reason, count) for reason, count in tally.items()]
        try:
            with self._lock:
                conn = self._connect()
                conn.executemany("INSERT INTO refusals (date, at, reason, n) "
                                 "VALUES (?,?,?,?)", rows)
                conn.commit()
                conn.close()
        except sqlite3.Error:
            return 0
        return len(rows)

    # ---- read side, for tools/verify_picks.py -------------------

    def days(self):
        if not self._ready:
            return []
        try:
            conn = self._connect()
            out = [r["date"] for r in conn.execute(
                "SELECT DISTINCT date FROM picks ORDER BY date")]
            conn.close()
            return out
        except sqlite3.Error:
            return []

    def picks(self, date=None, best_only=False):
        if not self._ready:
            return []
        sql = "SELECT * FROM picks"
        args = []
        where = []
        if date:
            where.append("date = ?")
            args.append(date)
        if best_only:
            where.append("rank = 1")
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY at, rank"
        try:
            conn = self._connect()
            out = [dict(r) for r in conn.execute(sql, args)]
            conn.close()
            return out
        except sqlite3.Error:
            return []

    def first_pick_per_symbol(self, date):
        """The earliest moment each name was picked, and at what price.

        That is the honest entry: the bot cannot claim the best fill of
        the day for a stock it named at 09:40 and again at 14:10.
        """
        seen = {}
        for row in self.picks(date):
            if row["symbol"] not in seen:
                seen[row["symbol"]] = row
        return seen

    def refusals(self, date=None):
        if not self._ready:
            return {}
        try:
            conn = self._connect()
            sql = ("SELECT reason, SUM(n) AS n FROM refusals "
                   + ("WHERE date = ? " if date else "")
                   + "GROUP BY reason ORDER BY n DESC")
            rows = conn.execute(sql, ([date] if date else [])).fetchall()
            conn.close()
            return {r["reason"]: r["n"] for r in rows}
        except sqlite3.Error:
            return {}

    def status(self):
        return {"available": self._ready, "path": self.db_path,
                "days": len(self.days())}
