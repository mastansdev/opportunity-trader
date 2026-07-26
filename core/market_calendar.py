"""
==========================================================
Market Calendar -- the bot knows when the market is shut
==========================================================

Operator, 2026-07-26: "i want to keep the bot in complete awareness of
trading holidays too. that's only 12-15 days in a whole year but worth
knowing the bot."

Right, and it is worth more than the count suggests. Without it:

  - the morning run downloads a bhavcopy that does not exist, warns,
    and trains you to ignore warnings (2026-06-26 did exactly this)
  - "yesterday's close" silently becomes three days old after a long
    weekend, so every gap and %-move is computed against the wrong bar
  - the bot starts, subscribes 545 symbols, and sits waiting for ticks
    that will never arrive
  - a backfill cannot tell a holiday from a failed download

Source: NSE's own holiday master (`nse.holidays`). Stored, so the answer
survives restarts and works offline.

TWO INDEPENDENT SOURCES, because this must not depend on a website
being up on the morning it matters:

  1. NSE's published list -- authoritative, fetched and stored.
  2. INFERRED from the daily-candle history: a weekday for which NSE
     never published a bhavcopy, with trading days either side of it,
     was a holiday. We already record those (DailyStore.no_data_dates),
     so the calendar can be rebuilt from data we hold locally even if
     the holiday API is unreachable forever.

FAIL-SAFE, NOT FAIL-OPEN. Note the difference from the rest of this
codebase. Elsewhere, missing data must never block trading. Here, an
empty calendar means "I only know about weekends" -- and is_trading_day()
returns True for any weekday it has no holiday record for. That is the
safe direction: the worst case is the bot starts on a holiday and sees
no ticks, which is harmless. The opposite default -- refusing to trade
on a day it wasn't sure about -- would cost real sessions.

Author : H&M Opportunity Trader
==========================================================
"""

import os
from datetime import date as _date
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, MetaData, String, Table, create_engine, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.logger import decision, diagnostic, warn

DEFAULT_DB = os.environ.get("MARKET_CALENDAR_DB",
                            "sqlite:///data/market_calendar.db")

WEEKEND = "weekend"


def _as_date(value):
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%Y", "%d-%m-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class MarketCalendar:

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
        self.holidays = Table(
            "market_holidays", self.md,
            Column("date", String(10), primary_key=True),   # YYYY-MM-DD
            Column("description", String(160)),
            Column("source", String(16)),                   # NSE / INFERRED
        )
        self.md.create_all(self.engine)
        self._cache = None

    # --------------------------------------------------
    # WRITE
    # --------------------------------------------------

    def add(self, day, description="", source="NSE"):
        """Record one holiday. Idempotent. An NSE-sourced record always
        wins over an inferred one -- the exchange's own list carries the
        real description, and we would rather show 'Independence Day'
        than 'inferred'."""
        day = _as_date(day)
        if day is None:
            return False
        key = day.isoformat()
        with self.engine.begin() as conn:
            stmt = sqlite_insert(self.holidays).values(
                date=key, description=description or "", source=source)
            if source == "NSE":
                stmt = stmt.on_conflict_do_update(
                    index_elements=["date"],
                    set_=dict(description=description or "", source=source))
            else:
                stmt = stmt.on_conflict_do_nothing(index_elements=["date"])
            conn.execute(stmt)
        self._cache = None
        return True

    def refresh_from_nse(self):
        """Pull NSE's holiday master. Returns how many were stored, or 0
        on any failure -- never raises."""
        try:
            from nse import NSE
            with NSE(download_folder="data") as n:
                payload = n.holidays(type="trading") or {}
        except Exception as exc:
            warn(f"[CALENDAR] NSE holiday list unavailable ({exc}). "
                 f"Falling back to what is already stored.")
            return 0

        rows = payload.get("CM") or []          # CM = capital markets
        stored = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            day = _as_date(row.get("tradingDate") or row.get("date"))
            if day is None:
                continue
            desc = str(row.get("description") or row.get("Description")
                       or "").strip()
            if self.add(day, desc, source="NSE"):
                stored += 1
        return stored

    def learn_from_missing_days(self, missing_dates):
        """
        Turn the daily store's "no bhavcopy on this weekday" records into
        holidays. This is what makes the calendar rebuildable from data
        we already hold, with no network at all.
        """
        stored = 0
        for day in missing_dates or ():
            d = _as_date(day)
            if d is None or d.weekday() >= 5:
                continue
            if self.add(d, "no bhavcopy published", source="INFERRED"):
                stored += 1
        return stored

    # --------------------------------------------------
    # READ
    # --------------------------------------------------

    def _load(self):
        if self._cache is None:
            with self.engine.begin() as conn:
                self._cache = {
                    r[0]: dict(description=r[1], source=r[2])
                    for r in conn.execute(select(
                        self.holidays.c.date, self.holidays.c.description,
                        self.holidays.c.source))
                }
        return self._cache

    def is_holiday(self, day=None):
        day = _as_date(day)
        return day is not None and day.isoformat() in self._load()

    def is_trading_day(self, day=None):
        """
        Weekends are never trading days. A weekday is a trading day
        unless we have a holiday record for it -- see the module
        docstring on why an unknown day defaults to TRUE.
        """
        day = _as_date(day)
        if day is None:
            return True
        if day.weekday() >= 5:
            return False
        return not self.is_holiday(day)

    def reason(self, day=None):
        """Why the market is shut, in words. None if it is open."""
        day = _as_date(day)
        if day is None:
            return None
        if day.weekday() >= 5:
            return "weekend"
        rec = self._load().get(day.isoformat())
        if not rec:
            return None
        return rec["description"] or "trading holiday"

    def next_trading_day(self, day=None, max_lookahead=14):
        day = _as_date(day)
        for _ in range(max_lookahead):
            day += timedelta(days=1)
            if self.is_trading_day(day):
                return day
        return None

    def previous_trading_day(self, day=None, max_lookback=14):
        """
        The session "yesterday's close" actually comes from. After a long
        weekend this is three days back, not one -- getting it wrong is
        how a gap gets measured against the wrong bar.
        """
        day = _as_date(day)
        for _ in range(max_lookback):
            day -= timedelta(days=1)
            if self.is_trading_day(day):
                return day
        return None

    def trading_days_between(self, start, end):
        start, end = _as_date(start), _as_date(end)
        out, day = [], start
        while day <= end:
            if self.is_trading_day(day):
                out.append(day)
            day += timedelta(days=1)
        return out

    def upcoming(self, days=90, frm=None):
        """[(date, description)] for holidays in the next `days` days."""
        frm = _as_date(frm)
        hi = frm + timedelta(days=days)
        out = []
        for key, rec in sorted(self._load().items()):
            d = _as_date(key)
            if d and frm <= d <= hi:
                out.append((d, rec["description"] or "trading holiday"))
        return out

    def count(self):
        return len(self._load())


_default = None


def default_calendar():
    global _default
    if _default is None:
        _default = MarketCalendar()
    return _default


def refresh(calendar=None, daily_store=None):
    """
    One full refresh: NSE's list, plus anything inferable from the daily
    candle history. Never raises.
    """
    calendar = calendar or default_calendar()
    n_nse = calendar.refresh_from_nse()

    n_inferred = 0
    try:
        if daily_store is None:
            from core.daily_store import DailyStore
            daily_store = DailyStore()
        n_inferred = calendar.learn_from_missing_days(
            daily_store.no_data_dates())
    except Exception as exc:
        diagnostic(f"[CALENDAR] Could not read inferred holidays: {exc}")

    decision(f"[CALENDAR] {calendar.count()} holidays known "
             f"({n_nse} from NSE, {n_inferred} inferred from missing "
             f"bhavcopies).")
    return calendar
