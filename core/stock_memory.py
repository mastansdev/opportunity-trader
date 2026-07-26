"""
==========================================================
Stock Memory -- what the bot KNOWS about each of the 750
==========================================================

Operator's own proposal, 2026-07-25:

    "I proposed a memory bot for every 750 stocks... so that Brain Bot,
     before selecting any trade, will understand the stock situation and
     use the opportunity. ex - JLHL: stock split, but bot sees it as 80%
     down from last closed price. If memory bot is there and sends
     signals to Brain Bot for every special case -- stock split,
     dividend, and anything else which will affect the stock price --
     it will be seen BEFORE opening the trade itself."

That is exactly the missing layer. Everything else in this bot reasons
about PRICE. Nothing reasoned about WHY a price is what it is.

The concrete failure this fixes:

    JLHL, 2026-07-24: a 2:10 stock split. The exchange halved the
    reference price; our prev_close was the UNADJUSTED one. The bot
    therefore read a routine corporate action as an **-80% crash** --
    ranked it the day's biggest loser, and in the replay "shorted" it.
    Nothing was wrong with the market. The bot simply did not know.

    Same class: a stock going ex-dividend opens lower by the dividend
    amount. That is not weakness, and shorting it is a mistake.

So this module stores FACTS about a symbol -- corporate actions with
their effective dates -- and answers one question the engine asks before
every entry: **"is anything special going on with this stock today?"**

Design, deliberately mirroring news_bot/news_store.py (same reasoning:
survives restarts, shared across processes, dedupes on its own key):
  - SQLite locally, Postgres on Railway (DATABASE_URL), same code.
  - UNIQUE(symbol, action_type, ex_date) so re-polling can't duplicate.
  - Read path is cached in memory by the caller; the tick path never
    touches the database.
  - Fail-OPEN everywhere. An empty memory must never block trading --
    it just means the bot knows nothing special, which is today's
    behaviour anyway.

Sources: NSE (`nse.actions`) and BSE (`bse.actions`) forthcoming
corporate actions, both already installed for the news engine. Manual
entries are supported too, for anything the feeds miss.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, Date, DateTime, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, insert, select,
)
from sqlalchemy.exc import IntegrityError

from news_bot.news_store import resolve_database_url

# Action types that MOVE THE PRICE MECHANICALLY -- the reference price
# changes, so a % move computed against yesterday's close is a lie.
# These are the ones that must block or adjust, not merely inform.
PRICE_ADJUSTING = {"SPLIT", "BONUS", "RIGHTS", "DEMERGER", "DIVIDEND"}

# Everything else is context: it may explain volatility, but the price
# scale is unchanged.
INFORMATIONAL = {"EARNINGS", "BOARD_MEETING", "AGM", "BUYBACK", "OTHER"}


def _utcnow():
    return datetime.now(timezone.utc)


class StockMemory:
    """Per-symbol facts. Construct once and share."""

    def __init__(self, url=None):
        self.url = resolve_database_url(url)
        connect_args = {}
        if self.url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                d = os.path.dirname(path)
                if d:
                    os.makedirs(d, exist_ok=True)

        self.engine = create_engine(
            self.url, future=True, pool_pre_ping=True, connect_args=connect_args
        )
        self.metadata = MetaData()
        self.actions = Table(
            "stock_actions", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            # SPLIT / BONUS / DIVIDEND / RIGHTS / DEMERGER / EARNINGS / ...
            Column("action_type", String(32), nullable=False),
            # The date the price actually changes (ex-date). This is the
            # one that matters -- NOT the announcement date.
            Column("ex_date", Date, nullable=False, index=True),
            # Free text as the exchange gave it ("Rs 4 per share",
            # "2:10", "1:1"). Parsing every format is a losing game; the
            # bot only needs to KNOW, and a human can read the detail.
            Column("detail", Text),
            Column("source", String(32)),
            Column("created_at", DateTime(timezone=True), default=_utcnow),
            UniqueConstraint("symbol", "action_type", "ex_date",
                             name="uq_stock_action"),
        )
        self.metadata.create_all(self.engine)

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------

    def remember(self, symbol, action_type, ex_date, detail="", source="manual"):
        """Store one fact. Returns True if newly stored, False if the
        bot already knew. Never raises on a duplicate."""
        if not symbol or not action_type or ex_date is None:
            return False
        action_type = action_type.strip().upper()
        symbol = symbol.strip().upper()
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.actions.c.id).where(
                    (self.actions.c.symbol == symbol)
                    & (self.actions.c.action_type == action_type)
                    & (self.actions.c.ex_date == ex_date)
                ).limit(1)
            ).first()
            if existing is not None:
                return False
            try:
                conn.execute(insert(self.actions).values(
                    symbol=symbol, action_type=action_type, ex_date=ex_date,
                    detail=(detail or "")[:500], source=source,
                    created_at=_utcnow(),
                ))
            except IntegrityError:
                return False
        return True

    # ----------------------------------------------------------
    # READ -- what the engine asks
    # ----------------------------------------------------------

    def facts_for(self, symbol, on_date=None, window_days=1):
        """Every known action for `symbol` whose ex-date falls within
        +/- window_days of `on_date` (default today). The window exists
        because the price distortion straddles the ex-date: the day
        before is when the old close becomes stale."""
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.symbol == symbol.strip().upper())
                    & (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                ).order_by(self.actions.c.ex_date)
            ).all()
        return [dict(r._mapping) for r in rows]

    def price_distorting_symbols(self, on_date=None, window_days=1):
        """
        The set the engine actually needs: every symbol whose PRICE SCALE
        is being changed around `on_date`. A %-move computed for one of
        these against an unadjusted previous close is meaningless -- this
        is the JLHL case, and the direct answer to "know before trading".

        Returned as {symbol: [reasons]} so the log can say WHY.
        """
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                    & (self.actions.c.action_type.in_(tuple(PRICE_ADJUSTING)))
                )
            ).all()
        out = {}
        for r in rows:
            d = dict(r._mapping)
            out.setdefault(d["symbol"], []).append(
                f"{d['action_type']}"
                + (f" ({d['detail']})" if d.get("detail") else "")
            )
        return out

    def all_symbols_with_facts(self, on_date=None, window_days=1):
        on_date = on_date or datetime.now().date()
        lo = on_date - timedelta(days=window_days)
        hi = on_date + timedelta(days=window_days)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    (self.actions.c.ex_date >= lo)
                    & (self.actions.c.ex_date <= hi)
                ).order_by(self.actions.c.symbol)
            ).all()
        out = {}
        for r in rows:
            d = dict(r._mapping)
            out.setdefault(d["symbol"], []).append(d)
        return out

    def count(self):
        from sqlalchemy import func
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.actions)
            ).scalar_one()

    # ----------------------------------------------------------
    # HISTORY -- "how many times has this stock done X?"
    # ----------------------------------------------------------
    # Operator, 2026-07-26: "how many times stocks are releasing their
    # results & dividend/buyback/splits announcing, or any other
    # announcements in memory". The memory was only ever queried for
    # TODAY; everything it had already stored about the past was
    # invisible. These are read-only views over the same table -- no new
    # data, no new fetching, just the ability to look backwards.

    def history_for(self, symbol):
        """Every fact ever stored for one symbol, oldest ex-date first."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions).where(
                    self.actions.c.symbol == str(symbol).strip().upper()
                ).order_by(self.actions.c.ex_date)
            ).all()
        return [dict(r._mapping) for r in rows]

    def counts_for(self, symbol):
        """{action_type: n} for one symbol."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.action_type, func.count())
                .where(self.actions.c.symbol == str(symbol).strip().upper())
                .group_by(self.actions.c.action_type)
            ).all()
        return {r[0]: r[1] for r in rows}

    def event_counts(self):
        """{action_type: n} across the whole universe."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.action_type, func.count())
                .group_by(self.actions.c.action_type)
                .order_by(func.count().desc())
            ).all()
        return {r[0]: r[1] for r in rows}

    def busiest_symbols(self, limit=20):
        """[(symbol, n)] -- who has the most corporate activity on
        record. Useful mostly as a data-quality check: a name with far
        more entries than its peers usually means a duplicate feed, not
        an unusually busy company."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.actions.c.symbol, func.count())
                .group_by(self.actions.c.symbol)
                .order_by(func.count().desc())
                .limit(limit)
            ).all()
        return [(r[0], r[1]) for r in rows]

    def date_range(self):
        """(earliest ex-date, latest ex-date) or (None, None)."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            row = conn.execute(select(
                func.min(self.actions.c.ex_date),
                func.max(self.actions.c.ex_date))).first()
        return (row[0], row[1]) if row else (None, None)


_default = None


def default_memory():
    global _default
    if _default is None:
        _default = StockMemory()
    return _default
