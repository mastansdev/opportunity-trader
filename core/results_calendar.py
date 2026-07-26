"""
==========================================================
Results Calendar -- who reports, when, and (eventually) at what TIME
==========================================================

Operator, 2026-07-26:

    "it must know the result = which stock will release their quarterly
     result on which date & time (as of now time cannot predict but
     later from our own stored data, bot can predict the time too like
     earnings pulse)"

Exactly right, and the two halves are very different problems.

THE DATE is published. NSE announces board meetings in advance, with the
purpose ("Quarterly Results"). That replaces `config.EARNINGS_CALENDAR`,
which is a hand-typed dict that goes stale the moment nobody updates it.

THE TIME is not published anywhere. A company says it will report on the
28th; whether the numbers hit the wire at 11:40 or 16:20 is not
announced. But it IS observable after the fact, and companies are
creatures of habit -- a firm that has reported at ~16:00 for six
straight quarters will almost certainly do it again.

So: record the observed broadcast timestamp every quarter, and after a
few quarters the bot can say "TCS usually reports around 16:05 (6 of 7
past results between 15:40 and 16:30)". That is the earnings pulse, and
it is built out of our own accumulated data rather than bought.

WHY THE TIME MATTERS MORE THAN IT SOUNDS
Today the earnings gate is all-or-nothing: a reporting stock is refused
for the WHOLE session. But if the numbers land at 16:20, the entire
09:15-15:15 session was ordinary trading and we sat out for nothing.
Knowing the habitual time turns a blunt full-day block into "trade it
normally, stop 30 minutes before it usually reports".

That change is NOT made here. This module only supplies the data, with
enough history to justify the change later. Same discipline as
trend_structure and deal_flow: describe first, act on evidence.

FAIL-OPEN. An empty calendar means the bot knows of no results today,
which is precisely today's behaviour with the hardcoded dict.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import statistics
from datetime import date as _date
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Date, DateTime, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, func, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.logger import decision, warn

DEFAULT_DB = os.environ.get("RESULTS_CALENDAR_DB",
                            "sqlite:///data/results_calendar.db")

# Board-meeting purposes that mean "the numbers are coming".
_RESULT_MARKERS = ("result", "financial statement", "unaudited",
                   "audited financial")

# Operator, 2026-07-26: "the result part now this would be 4 times per
# year and around 4 months per year. so here too we need not check in
# after results sessions completed."
#
# Correct. Indian listed companies report quarterly, and the filings
# cluster hard into four windows. Q1 (Apr-Jun) lands in Jul-Aug, Q2 in
# Oct-Nov, Q3 in Jan-Feb, Q4 plus the annual audit in Apr-May. Outside
# those, board meetings about results are a trickle of stragglers.
#
# So the refresh runs DAILY in season and WEEKLY out of season. Not
# "never": a company can and does move its date, and a straggler filing
# still carries a broadcast timestamp worth having for the pulse.
RESULTS_SEASON_MONTHS = {1, 2, 4, 5, 7, 8, 10, 11}
OFF_SEASON_REFRESH_DAYS = 7


def in_results_season(day=None):
    day = _as_date(day) or datetime.now().date()
    return day.month in RESULTS_SEASON_MONTHS


def looks_like_results(purpose):
    text = str(purpose or "").lower()
    return any(marker in text for marker in _RESULT_MARKERS)


def _as_date(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d-%m-%Y", "%d %b %Y",
                "%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text[:len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    return None


def _as_datetime(value):
    """Broadcast timestamps -- the earnings-pulse raw material."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d-%m-%Y %H:%M:%S", "%d-%b-%Y %H:%M",
                "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


class ResultsCalendar:

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
        self.events = Table(
            "results_events", self.md,
            Column("id", Integer, primary_key=True, autoincrement=True),
            Column("symbol", String(64), nullable=False, index=True),
            Column("results_date", Date, nullable=False, index=True),
            Column("purpose", Text),
            Column("relating_to", String(64)),      # "Third Quarter" etc.
            # NULL until observed. This is the earnings pulse.
            Column("broadcast_at", DateTime),
            Column("source", String(16)),
            UniqueConstraint("symbol", "results_date", name="uq_result"),
        )
        self.meta = Table(
            "results_meta", self.md,
            Column("key", String(32), primary_key=True),
            Column("value", String(64)),
        )
        self.md.create_all(self.engine)

    # --------------------------------------------------
    # WRITE
    # --------------------------------------------------

    def remember(self, symbol, results_date, purpose="", relating_to="",
                 broadcast_at=None, source="NSE"):
        """
        Store or enrich one result event.

        An existing row is UPDATED only where the new data is better: a
        broadcast timestamp overwrites a NULL one (that is the whole
        point -- the date is known in advance, the time only afterwards),
        but a known timestamp is never blanked by a later row that
        lacks one.
        """
        symbol = str(symbol or "").strip().upper()
        results_date = _as_date(results_date)
        if not symbol or results_date is None:
            return False

        values = dict(symbol=symbol, results_date=results_date,
                      purpose=str(purpose or "")[:500],
                      relating_to=str(relating_to or "")[:64],
                      broadcast_at=_as_datetime(broadcast_at),
                      source=source)
        update = {k: v for k, v in values.items()
                  if k not in ("symbol", "results_date") and v}
        with self.engine.begin() as conn:
            stmt = sqlite_insert(self.events).values(values)
            stmt = (stmt.on_conflict_do_update(
                index_elements=["symbol", "results_date"], set_=update)
                if update else
                stmt.on_conflict_do_nothing(
                    index_elements=["symbol", "results_date"]))
            conn.execute(stmt)
        return True

    # --------------------------------------------------
    # READ -- what the engine asks
    # --------------------------------------------------

    def symbols_on(self, day=None):
        """Every symbol reporting on `day`. The direct replacement for
        config.EARNINGS_CALENDAR[date]."""
        day = _as_date(day) or datetime.now().date()
        with self.engine.begin() as conn:
            return {r[0] for r in conn.execute(
                select(self.events.c.symbol).where(
                    self.events.c.results_date == day))}

    def as_calendar_dict(self, frm=None, days=45):
        """
        {"YYYY-MM-DD": {SYMBOL, ...}} -- the exact shape
        config.EARNINGS_CALENDAR uses, so the engine's tick path keeps
        doing a plain dict lookup and never touches a database.
        """
        frm = _as_date(frm) or datetime.now().date()
        hi = frm + timedelta(days=days)
        out = {}
        with self.engine.begin() as conn:
            rows = conn.execute(select(
                self.events.c.results_date, self.events.c.symbol
            ).where((self.events.c.results_date >= frm)
                    & (self.events.c.results_date <= hi)))
            for day, symbol in rows:
                out.setdefault(_as_date(day).isoformat(), set()).add(symbol)
        return out

    def upcoming(self, days=14, frm=None):
        frm = _as_date(frm) or datetime.now().date()
        hi = frm + timedelta(days=days)
        with self.engine.begin() as conn:
            rows = conn.execute(select(self.events).where(
                (self.events.c.results_date >= frm)
                & (self.events.c.results_date <= hi)
            ).order_by(self.events.c.results_date, self.events.c.symbol))
            return [dict(r._mapping) for r in rows]

    def history_for(self, symbol):
        """Every result event we have for one symbol, oldest first."""
        with self.engine.begin() as conn:
            rows = conn.execute(select(self.events).where(
                self.events.c.symbol == str(symbol).strip().upper()
            ).order_by(self.events.c.results_date))
            return [dict(r._mapping) for r in rows]

    # --------------------------------------------------
    # EARNINGS PULSE -- learned from our own stored history
    # --------------------------------------------------

    def observed_times(self, symbol):
        """Past broadcast times for one symbol, as minutes past midnight."""
        out = []
        for row in self.history_for(symbol):
            at = row.get("broadcast_at")
            if isinstance(at, datetime):
                out.append(at.hour * 60 + at.minute)
        return out

    def typical_time(self, symbol, min_samples=2):
        """
        When this company usually reports.

        Returns dict(minutes, hhmm, samples, spread_minutes) or None when
        there is not enough history. MEDIAN, not mean -- one result that
        slipped to 22:00 should not drag the estimate.

        min_samples=2 is a floor, not a recommendation. Two quarters is
        the least that can show a habit at all; treat anything under
        four as a hint. spread_minutes is there so the caller can see
        how consistent the company actually is.
        """
        times = self.observed_times(symbol)
        if len(times) < max(1, min_samples):
            return None
        median = int(statistics.median(times))
        spread = max(times) - min(times)
        return dict(minutes=median,
                    hhmm=f"{median // 60:02d}:{median % 60:02d}",
                    samples=len(times), spread_minutes=spread)

    def pulse(self, symbol, min_samples=2):
        """One plain-English line, or None."""
        t = self.typical_time(symbol, min_samples=min_samples)
        if not t:
            n = len(self.observed_times(symbol))
            return (f"no timing history yet ({n} observed)" if n
                    else "no timing history yet")
        return (f"usually reports around {t['hhmm']} "
                f"({t['samples']} past results, spread "
                f"{t['spread_minutes']} min)")

    # --------------------------------------------------

    # --------------------------------------------------
    # Refresh cadence -- results are seasonal, not daily
    # --------------------------------------------------

    def last_refreshed(self):
        with self.engine.begin() as conn:
            row = conn.execute(select(self.meta.c.value).where(
                self.meta.c.key == "last_refresh")).first()
        return _as_date(row[0]) if row else None

    def mark_refreshed(self, day=None):
        day = _as_date(day) or datetime.now().date()
        with self.engine.begin() as conn:
            stmt = sqlite_insert(self.meta).values(
                key="last_refresh", value=day.isoformat())
            conn.execute(stmt.on_conflict_do_update(
                index_elements=["key"], set_=dict(value=day.isoformat())))

    def needs_refresh(self, day=None):
        """
        Daily in results season, weekly outside it. See
        RESULTS_SEASON_MONTHS for the reasoning.
        """
        day = _as_date(day) or datetime.now().date()
        last = self.last_refreshed()
        if last is None:
            return True
        if in_results_season(day):
            return last < day
        return (day - last).days >= OFF_SEASON_REFRESH_DAYS

    def stats(self):
        with self.engine.begin() as conn:
            total = conn.execute(
                select(func.count()).select_from(self.events)).scalar() or 0
            symbols = conn.execute(
                select(func.count(func.distinct(
                    self.events.c.symbol)))).scalar() or 0
            timed = conn.execute(
                select(func.count()).select_from(self.events).where(
                    self.events.c.broadcast_at.isnot(None))).scalar() or 0
        return dict(events=total, symbols=symbols, with_time=timed)


# ==================================================================
# Fetchers -- both fail open, both return a count
# ==================================================================

def fetch_board_meetings(calendar, days_ahead=45, known_symbols=None):
    """FORTHCOMING results dates, from NSE's board-meeting calendar."""
    try:
        from nse import NSE
        with NSE(download_folder="data") as n:
            rows = n.boardMeetings(
                index="equities",
                from_date=datetime.now() - timedelta(days=2),
                to_date=datetime.now() + timedelta(days=days_ahead)) or []
    except Exception as exc:
        warn(f"[RESULTS] Board meetings unavailable ({exc}).")
        return 0

    stored = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = str(row.get("bm_symbol") or row.get("symbol") or "").strip().upper()
        purpose = (row.get("bm_purpose") or row.get("purpose") or "")
        desc = (row.get("bm_desc") or row.get("attachmentText") or "")
        if not symbol or not looks_like_results(f"{purpose} {desc}"):
            continue
        if known_symbols and symbol not in known_symbols:
            continue
        day = _as_date(row.get("bm_date") or row.get("meetingdate")
                       or row.get("date"))
        if day is None:
            continue
        if calendar.remember(symbol, day, purpose=purpose or desc,
                             source="NSE_BM"):
            stored += 1
    return stored


def fetch_filed_results(calendar, days_back=400, known_symbols=None,
                        chunk_days=30, today=None):
    """
    PAST filings, which carry the broadcast timestamp -- the earnings
    pulse. `broadCastDate` looks like "01-Jul-2026 11:00:51", i.e. a real
    time of day, which is exactly what we need.

    FETCHED IN CHUNKS. A single 400-day request came back with just 90
    rows, all stragglers from defunct companies filing 2018-19 accounts
    (IL&FSTRANS, Videocon) -- the endpoint clearly caps or paginates a
    wide window. Month-sized slices get the real volume.

    Reaches back a year by default so a first run picks up four quarters
    at once instead of waiting a year to become useful.
    """
    today = _as_date(today) or datetime.now().date()
    stored = 0
    seen_rows = 0
    matched = 0
    no_date = 0
    sample_keys = []

    start = today - timedelta(days=days_back)
    while start < today:
        end = min(start + timedelta(days=chunk_days), today)
        try:
            from nse import NSE
            with NSE(download_folder="data") as n:
                rows = n.financial_results(
                    segment="equities", period="quarterly",
                    from_date=datetime.combine(start, datetime.min.time()),
                    to_date=datetime.combine(end, datetime.min.time())) or []
        except Exception as exc:
            warn(f"[RESULTS] Filings {start}..{end} unavailable ({exc}).")
            rows = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            seen_rows += 1
            if not sample_keys:
                sample_keys = sorted(row.keys())
            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if known_symbols and symbol not in known_symbols:
                continue
            matched += 1

            broadcast = _as_datetime(
                row.get("broadCastDate") or row.get("broadcastDate")
                or row.get("filingDate") or row.get("creationDate"))
            day = (broadcast.date() if broadcast
                   else _as_date(row.get("broadCastDate")
                                 or row.get("filingDate")))
            if day is None:
                no_date += 1
                continue
            if calendar.remember(symbol, day,
                                 purpose="Quarterly Results (filed)",
                                 relating_to=row.get("relatingTo") or "",
                                 broadcast_at=broadcast, source="NSE_FR"):
                stored += 1

        start = end

    # Explain a zero precisely, because the three causes need three
    # different fixes and all look identical from the outside.
    if seen_rows and not matched:
        warn(f"[RESULTS] NSE returned {seen_rows} filings but NONE were in "
             f"our universe -- they are stragglers from delisted names. "
             f"Not a parsing problem.")
    elif matched and not stored:
        warn(f"[RESULTS] {matched} filings matched our universe but none "
             f"could be dated ({no_date} unparseable). Field names have "
             f"probably changed. Keys seen: {sample_keys}")
    elif not seen_rows:
        warn("[RESULTS] NSE returned no filings at all for the window.")
    return stored


def refresh(calendar=None, known_symbols=None, days_ahead=45,
            days_back=400, force=False, today=None):
    """One full refresh. Never raises.

    Skipped entirely when nothing is due -- see needs_refresh(). Results
    are a four-times-a-year event; polling NSE every morning in, say,
    September buys nothing.
    """
    calendar = calendar or ResultsCalendar()
    today = _as_date(today) or datetime.now().date()

    if not force and not calendar.needs_refresh(today):
        stats = calendar.stats()
        decision(
            f"[RESULTS] Nothing due -- "
            + ("in season, already refreshed today. "
               if in_results_season(today)
               else f"off-season, next check in "
                    f"{OFF_SEASON_REFRESH_DAYS} days. ")
            + f"{stats['events']} events known, "
              f"{stats['with_time']} with a time."
        )
        return calendar

    # Count ROWS, before and after. remember() returns True for every
    # valid call including updates, so counting calls overstated the
    # result badly: the first live run reported "+639 scheduled" when it
    # had actually stored 296 rows -- NSE lists several board-meeting
    # entries per company and they collapse on UNIQUE(symbol, date).
    before = calendar.stats()
    fetch_board_meetings(calendar, days_ahead, known_symbols)
    mid = calendar.stats()
    fetch_filed_results(calendar, days_back, known_symbols)
    after = calendar.stats()

    decision(
        f"[RESULTS] {after['events']} result events for "
        f"{after['symbols']} symbols; {after['with_time']} carry an "
        f"observed broadcast time. (+{mid['events'] - before['events']} "
        f"new scheduled, +{after['events'] - mid['events']} new filed, "
        f"+{after['with_time'] - before['with_time']} new timings.)"
    )
    calendar.mark_refreshed(today)

    if after["with_time"] == 0:
        decision(
            "[RESULTS] No broadcast timings yet -- the earnings pulse "
            "cannot say anything until past filings carry timestamps. "
            "Run tools/inspect_results_feed.py to see what NSE is "
            "actually returning."
        )
    return calendar
