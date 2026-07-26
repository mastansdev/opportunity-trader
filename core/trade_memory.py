"""
==========================================================
Trade Memory -- the learning loop (OBSERVATION ONLY)
==========================================================

From the operator's architecture deck (HM_ORB_AI_Final_Architecture):

    Position lifecycle:  ENTRY -> MONITOR -> NEWS -> RECALCULATE ->
                         TRAIL -> EXIT -> **LEARN -> MEMORY**

    Core ideology:  "Every completed trade becomes new memory,
                     improving future decisions."

Until now the bot forgot everything at 15:15. It could not tell you that
its breakouts in METALS had failed nine times this month, or that its
10:00 entries lose while its 11:00 entries win. Every session started
blind. This module is the missing half.

**IT DOES NOT VOTE.** Deliberate, operator-approved (2026-07-25):
observation first. It records what happened and reports what it sees;
nothing in the engine reads it to block or size a trade. The reason is
the same discipline that has caught three false conclusions already --
a handful of samples looks like a pattern long before it is one. Let it
learn in public for a few weeks; give it a vote only once its numbers
are backed by enough sessions to mean something.

What makes this useful is not the P&L (that's in trade_log.csv already)
but the CONTEXT captured at entry: the sector, the relative strength,
the hour, the market regime. Those are the conditions we can later ask
questions about.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, String, Table,
    UniqueConstraint, create_engine, func, insert, select,
)
from sqlalchemy.exc import IntegrityError

from core.db import resolve_database_url


def _utcnow():
    return datetime.now(timezone.utc)


class TradeMemory:

    def __init__(self, url=None):
        self.url = resolve_database_url(url, default="sqlite:///data/trade_memory.db")
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
        self.trades = Table(
            "trade_memory", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            Column("direction", String(8), nullable=False),
            Column("trade_date", String(10), nullable=False, index=True),
            Column("entry_time", DateTime),
            Column("exit_time", DateTime),
            Column("entry_price", Float),
            Column("exit_price", Float),
            Column("qty", Integer),
            Column("pnl", Float),
            Column("exit_reason", String(32), index=True),
            Column("entry_reason", String(48)),
            Column("holding_minutes", Float),
            # ---- CONTEXT AT ENTRY: the part worth learning from ----
            Column("sector", String(64), index=True),
            Column("entry_hour", String(5), index=True),      # "09:34" -> "09"
            Column("rel_strength", Float),                     # vs market
            Column("regime", String(12)),
            Column("recorded_at", DateTime(timezone=True), default=_utcnow),
            # One row per symbol per direction per day -- matches the
            # engine's own one-attempt-per-day rule, so a re-run or a
            # restart can't double-count a trade into the statistics.
            UniqueConstraint("symbol", "direction", "trade_date",
                             name="uq_trade_memory"),
        )
        self.metadata.create_all(self.engine)

    # ----------------------------------------------------------

    def record(self, closed_position):
        """Store one completed trade. Takes the engine's own
        closed_positions record (plus the entry-context fields the
        engine stamps onto it). Returns True if newly stored. Never
        raises -- a bookkeeping failure must not affect trading."""
        try:
            symbol = closed_position.get("symbol")
            direction = closed_position.get("direction")
            entry_time = closed_position.get("entry_time")
            if not symbol or not direction:
                return False
            trade_date = (entry_time.date().isoformat()
                          if isinstance(entry_time, datetime)
                          else datetime.now().date().isoformat())
            hour = (entry_time.strftime("%H")
                    if isinstance(entry_time, datetime) else None)
            holding = closed_position.get("holding_seconds")
            values = dict(
                symbol=symbol,
                direction=direction,
                trade_date=trade_date,
                entry_time=entry_time if isinstance(entry_time, datetime) else None,
                exit_time=closed_position.get("exit_time")
                if isinstance(closed_position.get("exit_time"), datetime) else None,
                entry_price=closed_position.get("entry_price"),
                exit_price=closed_position.get("exit_price"),
                qty=closed_position.get("qty"),
                pnl=closed_position.get("pnl"),
                exit_reason=closed_position.get("exit_reason"),
                entry_reason=closed_position.get("entry_reason"),
                holding_minutes=(holding / 60.0) if holding else None,
                sector=closed_position.get("sector"),
                entry_hour=hour,
                rel_strength=closed_position.get("rel_strength"),
                regime=closed_position.get("regime"),
                recorded_at=_utcnow(),
            )
            with self.engine.begin() as conn:
                existing = conn.execute(
                    select(self.trades.c.id).where(
                        (self.trades.c.symbol == symbol)
                        & (self.trades.c.direction == direction)
                        & (self.trades.c.trade_date == trade_date)
                    ).limit(1)
                ).first()
                if existing is not None:
                    return False
                try:
                    conn.execute(insert(self.trades).values(**values))
                except IntegrityError:
                    return False
            return True
        except Exception:
            return False

    # ----------------------------------------------------------
    # WHAT IT HAS LEARNED  (reporting only -- nothing reads this to
    # make a trading decision)
    # ----------------------------------------------------------

    def _bucket(self, column, min_trades=1):
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(
                    column,
                    func.count().label("n"),
                    func.sum(self.trades.c.pnl).label("total"),
                    func.avg(self.trades.c.pnl).label("avg"),
                ).group_by(column).order_by(func.count().desc())
            ).all()
        out = []
        for r in rows:
            key, n, total, avg = r[0], r[1], r[2] or 0.0, r[3] or 0.0
            if n < min_trades or key is None:
                continue
            wins = self._wins_for(column, key)
            out.append(dict(key=key, trades=n, wins=wins,
                            win_rate=100.0 * wins / n,
                            total_pnl=total, avg_pnl=avg))
        return out

    def _wins_for(self, column, key):
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.trades).where(
                    (column == key) & (self.trades.c.pnl > 0)
                )
            ).scalar_one()

    def by_sector(self, min_trades=1):
        return self._bucket(self.trades.c.sector, min_trades)

    def by_hour(self, min_trades=1):
        return sorted(self._bucket(self.trades.c.entry_hour, min_trades),
                      key=lambda d: d["key"])

    def by_direction(self, min_trades=1):
        return self._bucket(self.trades.c.direction, min_trades)

    def by_exit_reason(self, min_trades=1):
        return self._bucket(self.trades.c.exit_reason, min_trades)

    def by_symbol(self, min_trades=1):
        return self._bucket(self.trades.c.symbol, min_trades)

    def overall(self):
        with self.engine.begin() as conn:
            n = conn.execute(
                select(func.count()).select_from(self.trades)
            ).scalar_one()
            if not n:
                return dict(trades=0, sessions=0, wins=0, win_rate=0.0,
                            total_pnl=0.0, avg_win=0.0, avg_loss=0.0)
            total = conn.execute(
                select(func.sum(self.trades.c.pnl))
            ).scalar_one() or 0.0
            wins = conn.execute(
                select(func.count()).select_from(self.trades)
                .where(self.trades.c.pnl > 0)
            ).scalar_one()
            avg_win = conn.execute(
                select(func.avg(self.trades.c.pnl))
                .where(self.trades.c.pnl > 0)
            ).scalar_one() or 0.0
            avg_loss = conn.execute(
                select(func.avg(self.trades.c.pnl))
                .where(self.trades.c.pnl < 0)
            ).scalar_one() or 0.0
            sessions = conn.execute(
                select(func.count(func.distinct(self.trades.c.trade_date)))
            ).scalar_one()
        return dict(trades=n, sessions=sessions, wins=wins,
                    win_rate=100.0 * wins / n, total_pnl=total,
                    avg_win=avg_win, avg_loss=avg_loss)

    def count(self):
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.trades)
            ).scalar_one()


_default = None


def default_trade_memory():
    global _default
    if _default is None:
        _default = TradeMemory()
    return _default
