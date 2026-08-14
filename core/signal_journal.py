"""
==========================================================
Every signal the bot saw -- including the ones it refused
==========================================================

    "real movers are ignored by bot. as first see = buy & 10 slots
     filled."                            -- operator, 29 July 2026

He was almost certainly right. It could not be checked, because the
evidence did not exist: core/breakout_feed.py holds every signal in
memory and the process exits at 15:30. Every breakout the bot saw and
refused was deleted daily, all six months.

So the most important entry question in the project --

    did the setups we REFUSED do better than the ones we TOOK?

-- has never had an answer, and could not get one.

WHAT THIS DOES
--------------
Writes one row per structural signal to data/signal_journal.db:

    when, symbol, direction, break price, the range it broke,
    whether it was TAKEN or REFUSED, and if refused, WHY.

One row per symbol+direction+day. A breakout that keeps re-firing on
every candle is one event, not forty -- the row is updated, and the
final outcome is what gets stored.

WHY A DATABASE AND NOT A LOG LINE
---------------------------------
Because it has to be joined against the price data afterwards. The
whole point is to ask "what did this stock do in the two hours after
we said no", and grep cannot answer that. tools/refused_review.py
does the join.

IT DECIDES NOTHING. Writing a row cannot block, allow, size or exit
anything. It is a notebook, and it fails silently by design -- a
journal that could break the tick loop would be worse than no journal.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import threading
from datetime import datetime

from core.logger import decision, diagnostic

DB_PATH = os.path.join("data", "signal_journal.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    trade_date   TEXT NOT NULL,
    symbol       TEXT NOT NULL,
    direction    TEXT NOT NULL,
    first_seen   TEXT,
    last_seen    TEXT,
    break_price  REAL,
    orb_high     REAL,
    orb_low      REAL,
    taken        INTEGER DEFAULT 0,
    refused_why  TEXT,
    fired_count  INTEGER DEFAULT 1,
    open_positions_at_signal INTEGER,
    -- The three confirmations the operator asked for, 29 July 2026:
    --   "1) Results (good) + 2) Volume + 3) News"
    -- Recorded on EVERY signal, gating on none of them except volume.
    -- Two data points cannot decide a rule; thirty can. In two weeks
    -- tools/refused_review.py answers whether news-backed breakouts
    -- actually outperform, and only then does anything become a gate.
    volume_mult   REAL,
    news_kind     TEXT,
    filing_kind   TEXT,
    results_grade TEXT,
    attempt       INTEGER,
    sector        TEXT,
    confirmations INTEGER,
    PRIMARY KEY (trade_date, symbol, direction)
);
"""


class SignalJournal:
    """One row per structural signal per day. Never raises."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._ready = False
        self._pending = {}

    # ------------------------------------------------------------

    def _connect(self):
        directory = os.path.dirname(self.db_path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=5)
        if not self._ready:
            conn.executescript(SCHEMA)
            conn.commit()
            self._ready = True
        return conn

    # ------------------------------------------------------------

    def record(self, symbol, direction, break_price=None, orb_high=None,
               orb_low=None, taken=False, refused_why=None,
               open_positions=None, when=None, volume_mult=None,
               news_kind=None, filing_kind=None, results_grade=None,
               attempt=None, sector=None):
        """Buffer one signal. Flushed by flush(), not written per tick.

        Buffered deliberately: this is called from the tick path, and
        a SQLite write per signal per candle would put disk I/O in
        front of price processing. The buffer is a plain dict keyed by
        symbol+direction, so a signal that re-fires all afternoon costs
        one dict update, not forty inserts.
        """
        try:
            when = when or datetime.now()
            date = when.strftime("%Y-%m-%d")
            key = (date, symbol, direction)
            with self._lock:
                row = self._pending.get(key)
                if row is None:
                    row = {
                        "trade_date": date,
                        "symbol": symbol,
                        "direction": direction,
                        "first_seen": when.strftime("%Y-%m-%d %H:%M:%S"),
                        "break_price": break_price,
                        "orb_high": orb_high,
                        "orb_low": orb_low,
                        "taken": 0,
                        "refused_why": None,
                        "fired_count": 0,
                        "open_positions_at_signal": open_positions,
                        "volume_mult": None, "news_kind": None,
                        "filing_kind": None, "results_grade": None,
                        "attempt": None, "sector": None,
                        "confirmations": 0,
                    }
                    self._pending[key] = row
                row["last_seen"] = when.strftime("%Y-%m-%d %H:%M:%S")
                row["fired_count"] += 1

                # Confirmations are filled in as they become known --
                # a later call carrying news must not blank the volume
                # reading an earlier one recorded.
                # NOT named `key` -- that is the buffer key three lines
                # above, and shadowing it here would be a live grenade
                # for whoever edits this next.
                for field, value in (("volume_mult", volume_mult),
                                     ("news_kind", news_kind),
                                     ("filing_kind", filing_kind),
                                     ("results_grade", results_grade),
                                     ("attempt", attempt),
                                     ("sector", sector)):
                    if value is not None:
                        row[field] = value
                row["confirmations"] = sum([
                    1 if (row["volume_mult"] or 0) >= 1.5 else 0,
                    1 if row["news_kind"] or row["filing_kind"] else 0,
                    1 if (row["results_grade"] or "") in ("STRONG", "GOOD") else 0,
                ])
                if taken:
                    # Taken wins permanently. A signal that fired,
                    # was refused, then fired again and got in, is a
                    # TAKEN signal -- otherwise a later refusal would
                    # overwrite the truth.
                    row["taken"] = 1
                    row["refused_why"] = None
                elif refused_why and not row["taken"]:
                    row["refused_why"] = refused_why
        except Exception:                                  # noqa: BLE001
            pass

    # ------------------------------------------------------------

    def flush(self):
        """Write the buffer. Safe to call as often as you like."""
        try:
            with self._lock:
                rows = list(self._pending.values())
            if not rows:
                return 0
            conn = self._connect()
            conn.executemany(
                "INSERT INTO signals (trade_date, symbol, direction, "
                "first_seen, last_seen, break_price, orb_high, orb_low, "
                "taken, refused_why, fired_count, open_positions_at_signal, "
                "volume_mult, news_kind, filing_kind, results_grade, "
                "attempt, sector, confirmations) "
                "VALUES (:trade_date, :symbol, :direction, :first_seen, "
                ":last_seen, :break_price, :orb_high, :orb_low, :taken, "
                ":refused_why, :fired_count, :open_positions_at_signal, "
                ":volume_mult, :news_kind, :filing_kind, :results_grade, "
                ":attempt, :sector, :confirmations) "
                "ON CONFLICT(trade_date, symbol, direction) DO UPDATE SET "
                "last_seen=excluded.last_seen, taken=excluded.taken, "
                "refused_why=excluded.refused_why, "
                "fired_count=excluded.fired_count, "
                "volume_mult=excluded.volume_mult, "
                "news_kind=excluded.news_kind, "
                "filing_kind=excluded.filing_kind, "
                "results_grade=excluded.results_grade, "
                "attempt=excluded.attempt, sector=excluded.sector, "
                "confirmations=excluded.confirmations",
                rows)
            conn.commit()
            conn.close()
            return len(rows)
        except Exception as exc:                           # noqa: BLE001
            diagnostic(f"[JOURNAL] Could not write ({exc}).")
            return 0

    # ------------------------------------------------------------

    def close(self):
        written = self.flush()
        if written:
            decision(f"[JOURNAL] {written} signal(s) recorded today -- "
                     f"taken and refused both. tools/refused_review.py "
                     f"reads them back against what the stocks did.")
        return written

    def counts(self):
        """(taken, refused) buffered so far -- for the dashboard."""
        with self._lock:
            rows = list(self._pending.values())
        taken = sum(1 for r in rows if r["taken"])
        return taken, len(rows) - taken

    def today(self):
        """Every signal recorded today, taken AND refused, newest first.

        WHY THIS EXISTS -- the dashboard only ever received counts(), so
        the operator could see "6 taken / 3 refused" and never learn WHICH
        three or WHY. The reasons are the whole point:

            "we will get mostly idea where we are doing wrong & what
             needs to be corrected"          -- operator, 30 July 2026

        `refused_why` answers it directly, and `open_positions_at_signal`
        is the evidence for the first-come-first-served question -- a
        breakout refused with 10 positions already open was refused by
        the clock, not by a judgement about the stock.

        Reads the buffer AND the table, because a signal recorded minutes
        ago may not have been flushed yet and "not flushed" must not look
        like "did not happen".
        """
        import datetime
        today = datetime.date.today().isoformat()
        with self._lock:
            rows = [dict(r) for r in self._pending.values()]
        seen = {(r.get("symbol"), r.get("direction")) for r in rows}
        try:
            conn = self._connect()
            conn.row_factory = sqlite3.Row
            for r in conn.execute(
                    "SELECT * FROM signals WHERE trade_date = ?", (today,)):
                row = dict(r)
                if (row.get("symbol"), row.get("direction")) not in seen:
                    rows.append(row)
        except sqlite3.Error as exc:
            diagnostic(f"[JOURNAL] today() read failed: {exc}")
        rows.sort(key=lambda r: str(r.get("first_seen") or ""), reverse=True)
        return rows
