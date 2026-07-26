"""
==========================================================
Daily Store -- one candle per stock per day
==========================================================

The bot has always been blind to yesterday. Every session starts fresh
at 09:15, so a stock that has fallen 10% over two days looks identical
to one that has been grinding up for a week. That is how it came to buy
SRF long into a two-day collapse (2026-07-24) -- the breakout was real,
the context was not.

The fix costs nothing extra: NSE's daily bhavcopy, which the morning
run already downloads to decide SUBSCRIBE = YES/NO, carries OPEN, HIGH,
LOW, CLOSE and PREVIOUS CLOSE for every scrip. That IS a daily candle.
We were reading three columns and throwing the rest away.

So this store keeps them. One row per (date, symbol), filled by
backfilling a few weeks of bhavcopies once, then extended by one day
every morning. From that, core/trend_structure.py can answer the
question the operator posed:

    "some stocks make higher highs on day to day basis. once that
     formation stopped and forms higher low then lower low formation
     causes the reversal / range boundness in stocks."

Dedup is on (date, symbol) -- re-running the backfill over dates already
stored is a no-op, so the tool is safe to run repeatedly.

NOT ON THE TRADING PATH. Nothing here is consulted during a live tick.
It is read once, before the open, and cached.

Author : H&M Opportunity Trader
==========================================================
"""

import os

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, UniqueConstraint,
    create_engine, func, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

# Same override pattern as backtest/candle_store.py -- a sandbox whose
# mounted filesystem cannot do SQLite file-locking sets this.
DEFAULT_DB = os.environ.get("DAILY_CANDLE_DB", "sqlite:///data/daily_candles.db")


class DailyStore:

    def __init__(self, url=None):
        self.url = url or DEFAULT_DB
        if self.url.startswith("sqlite"):
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                directory = os.path.dirname(path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
        self.engine = create_engine(self.url, future=True)
        self.md = MetaData()
        self.bars = Table(
            "daily_bars", self.md,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("date", String(10), nullable=False, index=True),
            Column("symbol", String(64), nullable=False, index=True),
            Column("series", String(4)),
            Column("open", Float),
            Column("high", Float),
            Column("low", Float),
            Column("close", Float),
            Column("prev_close", Float),
            Column("volume", Float),
            Column("turnover", Float),
            UniqueConstraint("date", "symbol", name="uq_daily_date_symbol"),
        )
        self.md.create_all(self.engine)

    # --------------------------------------------------

    def upsert_many(self, rows):
        """
        Insert bars, ignoring any (date, symbol) already stored. Returns
        the number of rows actually written.

        ON CONFLICT DO NOTHING rather than "last write wins": a bhavcopy
        for a past date is immutable, so a second copy of the same day
        carries no new information, and silently overwriting would hide
        the fact that something re-downloaded a different file.
        """
        rows = [r for r in rows if r.get("symbol") and r.get("date")]
        if not rows:
            return 0
        written = 0
        with self.engine.begin() as conn:
            # Chunked -- SQLite has a hard limit on bound parameters and
            # a full bhavcopy is ~2,400 usable rows x 10 columns.
            for i in range(0, len(rows), 500):
                chunk = rows[i:i + 500]
                stmt = sqlite_insert(self.bars).values(chunk)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["date", "symbol"]
                )
                written += conn.execute(stmt).rowcount or 0
        return written

    # --------------------------------------------------

    def history(self, symbol, days=7, upto=None):
        """
        The last `days` bars for one symbol, OLDEST FIRST -- the order
        core/trend_structure.py expects. `upto` (YYYY-MM-DD) excludes
        anything after that date, which is what makes an honest
        backtest possible: replaying 2026-07-24 must not see 07-25.
        """
        q = select(self.bars).where(self.bars.c.symbol == symbol)
        if upto:
            q = q.where(self.bars.c.date <= upto)
        q = q.order_by(self.bars.c.date.desc()).limit(days)
        with self.engine.begin() as conn:
            rows = [dict(r._mapping) for r in conn.execute(q)]
        return list(reversed(rows))

    def history_many(self, symbols, days=7, upto=None):
        """{symbol: [bars]} -- one query per symbol, but the whole point
        is that this runs once before the open, not per tick."""
        return {s: self.history(s, days=days, upto=upto) for s in symbols}

    def dates(self):
        """Every trading date stored, ascending."""
        with self.engine.begin() as conn:
            return [r[0] for r in conn.execute(
                select(self.bars.c.date).distinct().order_by(self.bars.c.date)
            )]

    def stats(self):
        with self.engine.begin() as conn:
            total = conn.execute(
                select(func.count()).select_from(self.bars)
            ).scalar() or 0
            symbols = conn.execute(
                select(func.count(func.distinct(self.bars.c.symbol)))
            ).scalar() or 0
        dates = self.dates()
        return dict(
            bars=total, symbols=symbols, days=len(dates),
            first=dates[0] if dates else None,
            last=dates[-1] if dates else None,
        )


def bars_from_bhavcopy(rows, date, tradeable_only=True):
    """
    Turn raw bhavcopy rows into DailyStore rows. Pure function.

    tradeable_only keeps series EQ. A BE/T2T row is not a candle we ever
    want to compute a trend from -- we cannot trade it, and its prices
    move under different rules.
    """
    from core.universe_builder import _num, _pick

    out, seen = [], set()
    for row in rows:
        symbol = _pick(row, "symbol")
        if not symbol:
            continue
        symbol = str(symbol).strip().upper()
        series = str(_pick(row, "series") or "").strip().upper()
        if tradeable_only and series != "EQ":
            continue
        if symbol in seen:
            continue

        close = _num(_pick(row, "close"))
        if close is None or close <= 0:
            continue
        seen.add(symbol)

        volume = _num(_pick(row, "volume")) or 0.0
        turnover = _num(_pick(row, "turnover"))
        if turnover is None:
            turnover = close * volume

        out.append(dict(
            date=date, symbol=symbol, series=series,
            open=_num(row.get("OpnPric") or row.get("OPEN")),
            high=_num(row.get("HghPric") or row.get("HIGH")),
            low=_num(row.get("LwPric") or row.get("LOW")),
            close=close,
            prev_close=_num(row.get("PrvsClsgPric") or row.get("PREVCLOSE")),
            volume=volume, turnover=turnover,
        ))
    return out
