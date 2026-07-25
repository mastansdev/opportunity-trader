"""
==========================================================
News Bot -- persistent per-stock store (SQLite / Postgres)
==========================================================

The single filing cabinet the 24/7 news engine writes to and the
brain bot + dashboard read from. Replaces the old flat .jsonl
files (data/news_audit_log.jsonl, data/news_high_priority.jsonl),
which could not do three things a 24/7, cloud-hosted engine needs:

  1. DEDUP ACROSS POLL CYCLES. RSS keeps showing the same headline
     for hours, so the old file re-recorded every story on every
     45s poll (proven live: TCS/INFY/SBIN written twice, 53s
     apart, 2026-07-24). Here every row carries the news `guid`
     and there is a UNIQUE(guid, symbol) constraint -- the same
     story for the same stock can physically only be stored once,
     ever. Re-inserts are silently ignored.

  2. PER-STOCK "BRAIN" (Bloomberg-terminal style). Every item is
     keyed by symbol and indexed, so "what does RELIANCE know?"
     is one indexed lookup (for_symbol()), and the full history
     per stock accumulates instead of being thrown away nightly.

  3. SHARED ACROSS PROCESSES / MACHINES. The engine can run 24/7
     on Railway (cloud) while the brain bot runs on the PC, both
     pointing at the same database. Local dev uses a SQLite file;
     Railway sets DATABASE_URL to its Postgres and the SAME code
     runs unchanged.

Storage vs. action are deliberately separate:
  - The store keeps EVERYTHING it's given (MID + HIGH), forever,
    per stock -- that's the brain.
  - The brain bot only ACTS on HIGH items, and only ones inside a
    freshness window (config.NEWS_ACTIONABLE_WINDOW_HOURS) so a
    three-day-old headline can't veto today's trade. DUMMY / vague
    / low-priority news never reaches this module at all -- Stage
    2 (matching) and the priority tiering drop it upstream.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    Column, DateTime, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, insert, select,
)
from sqlalchemy.exc import IntegrityError

from news_bot.config import (
    NEWS_DB_URL_DEFAULT, NEWS_ACTIONABLE_WINDOW_HOURS, NEWS_RECENT_FEED_LIMIT,
)


def resolve_database_url(explicit=None):
    """
    Pick the database URL. Priority: explicit arg (tests) >
    DATABASE_URL env (Railway/Postgres) > local SQLite default.

    Railway/Heroku hand out URLs starting 'postgres://', but
    SQLAlchemy 2.x wants 'postgresql://' -- normalize it so the
    exact URL Railway injects works with zero editing.
    """
    url = (explicit or os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        url = NEWS_DB_URL_DEFAULT
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _utcnow():
    # Store everything in UTC -- the engine may run in a different
    # timezone (a cloud box) from the brain bot, so a single,
    # unambiguous clock is the only safe choice for windowing.
    return datetime.now(timezone.utc)


class NewsStore:
    """SQLAlchemy-Core store. One instance owns one engine/connection
    pool; construct once and share (see default_store())."""

    def __init__(self, url=None):
        self.url = resolve_database_url(url)

        connect_args = {}
        if self.url.startswith("sqlite"):
            # A SQLite file may be opened by the writer (news engine)
            # and reader (brain bot / dashboard) threads at once.
            connect_args["check_same_thread"] = False
            # Make sure the parent dir exists for a file: URL.
            path = self.url.replace("sqlite:///", "", 1)
            if path and path != ":memory:":
                directory = os.path.dirname(path)
                if directory:
                    os.makedirs(directory, exist_ok=True)

        self.engine = create_engine(
            self.url, future=True, pool_pre_ping=True, connect_args=connect_args
        )

        self.metadata = MetaData()
        self.news_items = Table(
            "news_items", self.metadata,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("guid", String(512), nullable=False, index=True),
            Column("symbol", String(64), nullable=False, index=True),
            Column("priority", String(8), nullable=False),      # HIGH / MID
            Column("direction", String(16)),                    # bullish/bearish/neutral
            Column("confidence", Integer),
            Column("materiality", String(16)),
            Column("reason", Text),
            Column("matched_field", String(64)),
            Column("tier", String(16)),                         # COMPANY / BROAD
            Column("classifier", String(16)),                   # haiku / keyword
            Column("source", String(64)),
            Column("title", Text),
            Column("link", Text),
            # created_at = when WE recorded it (server clock, UTC).
            # This is what all freshness windows are measured against
            # -- honest about ingestion time, never a feed-supplied
            # timestamp we can't trust.
            Column("created_at", DateTime(timezone=True), nullable=False,
                   index=True, default=_utcnow),
            # Same story can legitimately match many stocks (a sector
            # headline). Dedup is per (story, stock), not per story.
            UniqueConstraint("guid", "symbol", name="uq_news_guid_symbol"),
        )
        self.metadata.create_all(self.engine)

    # ----------------------------------------------------------
    # WRITE
    # ----------------------------------------------------------

    def record(self, priority_result, item):
        """
        Store one (news item, matched stock) row. Returns True if a
        NEW row was written, False if it was a duplicate we ignored.
        Dedup is enforced two ways -- a pre-check (cheap, the common
        case on a busy feed) AND the UNIQUE constraint as the real
        backstop against a race. DUMMY items never reach here.
        """
        guid = item.guid or item.link
        symbol = priority_result.symbol

        with self.engine.begin() as conn:
            existing = conn.execute(
                select(self.news_items.c.id).where(
                    (self.news_items.c.guid == guid)
                    & (self.news_items.c.symbol == symbol)
                ).limit(1)
            ).first()
            if existing is not None:
                return False

            try:
                conn.execute(insert(self.news_items).values(
                    guid=guid,
                    symbol=symbol,
                    priority=priority_result.priority,
                    direction=priority_result.direction,
                    confidence=priority_result.confidence,
                    materiality=priority_result.materiality,
                    reason=priority_result.reason,
                    matched_field=priority_result.matched_field,
                    tier=priority_result.tier,
                    classifier=getattr(priority_result, "classifier", "haiku"),
                    source=item.source,
                    title=item.title,
                    link=item.link,
                    created_at=_utcnow(),
                ))
            except IntegrityError:
                # Lost a race with another insert of the same
                # (guid, symbol) -- that's fine, the row exists now.
                return False
        return True

    def exists(self, guid, symbol):
        """True if this (story, stock) pair was already CLASSIFIED and
        recorded -- the budget-critical dedup check the pipeline runs
        BEFORE doing any work. If it's here, we've already classified
        it once (and, if it went to the paid AI, already paid for it),
        so it must never be classified or billed again. See pipeline.py."""
        with self.engine.begin() as conn:
            row = conn.execute(
                select(self.news_items.c.id).where(
                    (self.news_items.c.guid == guid)
                    & (self.news_items.c.symbol == symbol)
                ).limit(1)
            ).first()
        return row is not None

    # ----------------------------------------------------------
    # READ
    # ----------------------------------------------------------

    def _row_dict(self, row):
        d = dict(row._mapping)
        created = d.get("created_at")
        # Expose an ISO 'time' string for backward compatibility with
        # everything that read the old file records' "time" field.
        if isinstance(created, datetime):
            d["time"] = created.isoformat()
        else:
            d["time"] = str(created) if created is not None else ""
        return d

    def _since_cutoff(self, hours):
        return _utcnow() - timedelta(hours=hours)

    def high_priority_for(self, symbol, window_hours=None):
        """Today-and-still-actionable HIGH items for `symbol`, oldest
        first. 'Actionable' = created within the freshness window
        (default config.NEWS_ACTIONABLE_WINDOW_HOURS) so overnight and
        weekend news carries into the next session but a stale headline
        eventually stops vetoing trades."""
        if window_hours is None:
            window_hours = NEWS_ACTIONABLE_WINDOW_HOURS
        cutoff = self._since_cutoff(window_hours)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.news_items).where(
                    (self.news_items.c.symbol == symbol)
                    & (self.news_items.c.priority == "HIGH")
                    & (self.news_items.c.created_at >= cutoff)
                ).order_by(self.news_items.c.created_at.asc())
            ).all()
        return [self._row_dict(r) for r in rows]

    def all_high_symbols(self, window_hours=None):
        """symbol -> latest actionable HIGH item, for every symbol
        with at least one inside the window."""
        if window_hours is None:
            window_hours = NEWS_ACTIONABLE_WINDOW_HOURS
        cutoff = self._since_cutoff(window_hours)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.news_items).where(
                    (self.news_items.c.priority == "HIGH")
                    & (self.news_items.c.created_at >= cutoff)
                ).order_by(self.news_items.c.created_at.asc())
            ).all()
        latest = {}
        for r in rows:
            d = self._row_dict(r)
            latest[d["symbol"]] = d      # asc order -> last write wins
        return latest

    def recent(self, limit=None, window_hours=None):
        """Most-recent MID+HIGH items, newest first -- the dashboard's
        display feed. Windowed the same way so the panel shows the
        current session's news, not the entire history."""
        if limit is None:
            limit = NEWS_RECENT_FEED_LIMIT
        if window_hours is None:
            window_hours = NEWS_ACTIONABLE_WINDOW_HOURS
        cutoff = self._since_cutoff(window_hours)
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.news_items).where(
                    (self.news_items.c.created_at >= cutoff)
                    & (self.news_items.c.direction != "neutral")
                ).order_by(self.news_items.c.created_at.desc()).limit(limit)
            ).all()
        return [self._row_dict(r) for r in rows]

    def for_symbol(self, symbol, limit=200):
        """The Bloomberg-style per-stock brain: this symbol's stored
        SIGNAL history, newest first (no freshness window). Neutral /
        no-signal rows are excluded -- a stock's brain is its real
        news, not 'please refer attachment' filler. This is the whole
        point of keeping the data: ask a stock what's happened to it."""
        with self.engine.begin() as conn:
            rows = conn.execute(
                select(self.news_items).where(
                    (self.news_items.c.symbol == symbol)
                    & (self.news_items.c.direction != "neutral")
                ).order_by(self.news_items.c.created_at.desc()).limit(limit)
            ).all()
        return [self._row_dict(r) for r in rows]

    def count(self):
        """Total rows -- for health/heartbeat logging."""
        from sqlalchemy import func
        with self.engine.begin() as conn:
            return conn.execute(
                select(func.count()).select_from(self.news_items)
            ).scalar_one()

    def stats(self, window_hours=None):
        """Header numbers for the news dashboard, computed in the DB
        (never pulls all rows). Returns all-time total plus, WITHIN
        the freshness window: HIGH count, MID count, and how many
        distinct stocks have news."""
        from sqlalchemy import func
        if window_hours is None:
            window_hours = NEWS_ACTIONABLE_WINDOW_HOURS
        cutoff = self._since_cutoff(window_hours)
        t = self.news_items
        with self.engine.begin() as conn:
            total_all_time = conn.execute(
                select(func.count()).select_from(t)
            ).scalar_one()
            high = conn.execute(
                select(func.count()).select_from(t).where(
                    (t.c.priority == "HIGH") & (t.c.created_at >= cutoff)
                )
            ).scalar_one()
            mid = conn.execute(
                select(func.count()).select_from(t).where(
                    (t.c.priority == "MID") & (t.c.created_at >= cutoff)
                    & (t.c.direction != "neutral")
                )
            ).scalar_one()
            distinct_symbols = conn.execute(
                select(func.count(func.distinct(t.c.symbol))).where(
                    (t.c.created_at >= cutoff) & (t.c.direction != "neutral")
                )
            ).scalar_one()
        return {
            "total_all_time": int(total_all_time),
            "window_hours": window_hours,
            "high": int(high),
            "mid": int(mid),
            "distinct_symbols": int(distinct_symbols),
        }

    def delete_neutral(self):
        """One-time cleanup: remove NEUTRAL / no-signal rows already
        stored before the neutral-drop rule was added (2026-07-24).
        The going-forward gate is in pipeline.py; this just clears the
        backlog. Returns how many rows were deleted."""
        from sqlalchemy import delete
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(self.news_items).where(
                    self.news_items.c.direction == "neutral"
                )
            )
        return result.rowcount

    def prune_older_than(self, days):
        """Optional housekeeping: delete rows older than `days`. The
        per-stock brain is meant to accumulate, so this is NOT called
        automatically -- it exists for when a store needs trimming
        (e.g. a free-tier DB nearing its size cap)."""
        from sqlalchemy import delete
        cutoff = self._since_cutoff(days * 24)
        with self.engine.begin() as conn:
            result = conn.execute(
                delete(self.news_items).where(
                    self.news_items.c.created_at < cutoff
                )
            )
        return result.rowcount


# --------------------------------------------------------------
# Module-level default store (the real one), lazily built so importing
# this module never touches a database or the network. Tests construct
# their own NewsStore(url=...) against a temp DB and never touch this.
# --------------------------------------------------------------

_default_store = None


def default_store():
    global _default_store
    if _default_store is None:
        _default_store = NewsStore()
    return _default_store
