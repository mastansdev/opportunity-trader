"""
==========================================================
Backtest -- candle store (the replay corpus)
==========================================================

A SQLite store of 1-minute OHLCV candles, keyed by (date, symbol,
minute). This is the raw material the replay engine feeds through the
strategy. Two ways it gets filled:

  - import_from_log.py  -- bootstrap TODAY's candles out of the running
    bot's diagnostics.log (rough: no volume, restart-muddied), so we
    have something to replay immediately.

  - the forward recorder (wired into the live bot, separate task) --
    clean OHLCV with real market timestamps + volume, written each
    session. From there on, every real session accumulates a pristine
    recent-window corpus.

Dedup is on (date, symbol, minute) -- a restart re-logging the same bar
can't create a duplicate; last write wins.

Author : H&M Opportunity Trader
==========================================================
"""

import os

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, UniqueConstraint,
    create_engine, delete, insert, select, func,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

import os as _os

# Default lives in the project's data/ dir (your Windows bot writes it
# fine). Overridable via BACKTEST_CANDLE_DB -- used when running inside a
# sandbox whose mounted filesystem can't do SQLite file-locking.
DEFAULT_DB = _os.environ.get(
    "BACKTEST_CANDLE_DB", "sqlite:///data/backtest_candles.db"
)


class CandleStore:
    def __init__(self, url=None):
        self.url = url or DEFAULT_DB
        if self.url.startswith("sqlite"):
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)
        self.engine = create_engine(self.url, future=True)
        self.md = MetaData()
        self.candles = Table(
            "candles", self.md,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("date", String(10), nullable=False, index=True),   # YYYY-MM-DD
            Column("symbol", String(64), nullable=False, index=True),
            Column("minute", String(19), nullable=False),             # ISO close time to the minute
            Column("o", Float, nullable=False),
            Column("h", Float, nullable=False),
            Column("l", Float, nullable=False),
            Column("c", Float, nullable=False),
            Column("v", Float, nullable=True),                        # volume, may be None
            UniqueConstraint("date", "symbol", "minute", name="uq_candle"),
        )
        self.md.create_all(self.engine)

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------

    def add(self, date, symbol, minute, o, h, l, c, v=None):
        """Insert one candle, ignoring/replacing a duplicate (date,
        symbol, minute). Returns True if newly inserted."""
        stmt = sqlite_insert(self.candles).values(
            date=date, symbol=symbol, minute=minute, o=o, h=h, l=l, c=c, v=v
        ).on_conflict_do_update(
            index_elements=["date", "symbol", "minute"],
            set_={"o": o, "h": h, "l": l, "c": c, "v": v},
        )
        with self.engine.begin() as conn:
            conn.execute(stmt)
        return True

    def add_many(self, rows, chunk=5000):
        """
        Bulk upsert. `rows` = iterable of dicts with keys
        date,symbol,minute,o,h,l,c[,v].

        2026-07-26 REWRITTEN. The first version issued ONE conn.execute()
        per row inside the transaction. That was fine for the live
        recorder (a few hundred candles a minute) and completely
        unusable for the historical pull: 545 symbols x 375 minutes x
        62 sessions is ~12.7 MILLION rows, and at roughly 2-4k
        single-statement executes a second that is most of a day.

        Now one compiled statement per chunk via executemany. Same
        upsert semantics -- dedup on (date, symbol, minute), last write
        wins -- so a re-run of the fetcher still cannot duplicate a bar.

        Every row in a chunk must have the SAME keys, because a single
        compiled statement is reused across the batch. Rows are
        normalised to the full column set first (missing volume -> None),
        which also stops a partial dict silently NULLing a column that
        another row in the same batch did supply.
        """
        rows = list(rows)
        if not rows:
            return 0

        cols = ("date", "symbol", "minute", "o", "h", "l", "c", "v")
        normalised = [{c: r.get(c) for c in cols} for r in rows]

        stmt = sqlite_insert(self.candles)
        stmt = stmt.on_conflict_do_update(
            index_elements=["date", "symbol", "minute"],
            set_={c: stmt.excluded[c] for c in ("o", "h", "l", "c", "v")},
        )

        with self.engine.begin() as conn:
            for i in range(0, len(normalised), max(1, chunk)):
                conn.execute(stmt, normalised[i:i + max(1, chunk)])
        return len(normalised)

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------

    def dates(self):
        with self.engine.begin() as conn:
            return [r[0] for r in conn.execute(
                select(self.candles.c.date).distinct().order_by(self.candles.c.date)
            ).all()]

    def symbols_for(self, date):
        with self.engine.begin() as conn:
            return [r[0] for r in conn.execute(
                select(self.candles.c.symbol).distinct().where(
                    self.candles.c.date == date
                ).order_by(self.candles.c.symbol)
            ).all()]

    def candles_for(self, date, symbol=None):
        """All candles for a date (optionally one symbol), ordered by
        (minute, symbol) so a replay can walk them chronologically."""
        q = select(self.candles).where(self.candles.c.date == date)
        if symbol is not None:
            q = q.where(self.candles.c.symbol == symbol)
        q = q.order_by(self.candles.c.minute, self.candles.c.symbol)
        with self.engine.begin() as conn:
            return [dict(r._mapping) for r in conn.execute(q).all()]

    def count(self, date=None):
        q = select(func.count()).select_from(self.candles)
        if date is not None:
            q = q.where(self.candles.c.date == date)
        with self.engine.begin() as conn:
            return conn.execute(q).scalar_one()

    def clear_date(self, date):
        with self.engine.begin() as conn:
            conn.execute(delete(self.candles).where(self.candles.c.date == date))
