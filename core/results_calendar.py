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
import re
import sqlite3
import statistics
from datetime import date as _date
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Date, DateTime, Integer, MetaData, String, Table, Text,
    UniqueConstraint, create_engine, func, select,
)
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.logger import decision, diagnostic, warn

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
# Some companies simply have no habit. Real data, 2026-07-26, all of
# them genuine "Outcome of Board Meeting" filings:
#
#     TCS       15:57 15:52 15:50 15:55 15:52   spread   7 min  <- habit
#     ASIANPAINT 14:11 15:05 13:58 14:06        spread  67 min  <- habit
#     COFORGE   21:54 16:10 23:35 16:58         spread 445 min  <- none
#
# A median of 17:06 for COFORGE is arithmetically true and completely
# useless. So typical_time() carries a `reliable` flag rather than
# leaving every caller to eyeball the spread and decide for itself.
#
# Two hours: wide enough to tolerate a board meeting running long,
# narrow enough that "stop trading 30 minutes before" would still be
# in the right part of the day.
RELIABLE_SPREAD_MINUTES = 120

# ---- THE SEASON ENDS ON A DAY, NOT AT A MONTH BOUNDARY ----
#      24 August 2026.
#
#     "i told u that about results right? before asking me why didn't
#      u checked online resources about indian markets & their working
#      methods , results - their periods"
#                                    -- operator, 24 August 2026
#
# He told me on 21 August that the season had ended and returns in the
# second week of October. I did not check, and built a month check
# that said 24 August WAS results season -- ten days after the Q1
# deadline had passed.
#
# SEBI (LODR) Regulation 33: quarterly results are due within 45 days
# of quarter end; the last quarter and the annual results within 60
# days of the financial year end. That fixes four hard deadlines, and
# reporting clusters in the weeks BEFORE each one:
#
#     Q1  Apr-Jun   due 14 August
#     Q2  Jul-Sep   due 14 November
#     Q3  Oct-Dec   due 14 February
#     Q4  + annual  due 30 May       (60 days, audited)
#
# So the Q2 season builds from mid-October to 14 November, which is
# exactly the "oct 2nd week" he named. Months cannot express this: by
# 24 August the filings are done, and by 30 May they are done too,
# while 1 May is the busiest part of the year.
#
# Windows open a month before each deadline -- companies file across
# the four weeks running up to it, not on the last day.
RESULTS_WINDOWS = (
    ((1, 15), (2, 14)),        # Q3 (Oct-Dec)
    ((4, 15), (5, 30)),        # Q4 and the audited annual
    ((7, 15), (8, 14)),        # Q1 (Apr-Jun)
    ((10, 15), (11, 14)),      # Q2 (Jul-Sep)
)

# Kept: callers and tests still read it, and it remains a true
# statement of WHICH MONTHS contain a season. It is no longer what
# in_results_season() decides on.
RESULTS_SEASON_MONTHS = {1, 2, 4, 5, 7, 8, 10, 11}
OFF_SEASON_REFRESH_DAYS = 7


def in_results_season(day=None):
    """Are companies filing results around now?

    Day-level, from the SEBI Regulation 33 deadlines above. 24 August
    is NOT results season; 14 August is.
    """
    day = _as_date(day) or datetime.now().date()
    for (m1, d1), (m2, d2) in RESULTS_WINDOWS:
        if (m1, d1) <= (day.month, day.day) <= (m2, d2):
            return True
    return False


# ...but the word "result" appears in the BODY of a great many
# announcements that are not the filing. NSE's `desc` field is the
# CATEGORY, and that is the reliable signal. Real data, 2026-07-26:
#
#   Outcome of Board Meeting   13:58  14:06  14:11  15:05   <- the numbers
#   Shareholders meeting       21:15  23:27  23:56  19:39   <- AGM minutes
#   Updates                    15:19  16:27  21:02          <- misc
#
# All three mention "results" somewhere in the text, so matching on the
# body swept in AGM proceedings filed near midnight -- which is how
# ASIANPAINT ended up with a 598-minute "habit" and INFY with fifteen
# results in a year.
#
# Strip to the board-meeting category and ASIANPAINT reads ~14:06 with a
# 67-minute spread; TCS reads 15:52 with a SEVEN-minute spread. That is
# what a real habit looks like.
_RESULT_CATEGORIES = ("outcome of board meeting", "financial result",
                      "financial statement")

# Categories that never carry the numbers, whatever their body says.
_EXCLUDED_CATEGORIES = ("shareholders meeting", "update", "analyst",
                        "investor", "press release", "newspaper",
                        "presentation", "transcript", "certificate",
                        "trading window", "disclosure under",
                        # Exchange queries and the company's replies.
                        # NESCO carried three, ACI two -- filed days
                        # after the numbers, at any hour.
                        "clarification", "reply to")

# Follow-up documents, checked against the whole text as a backstop.
_NOISE_MARKERS = (
    "newspaper", "publication", "published", "advertisement",
    "presentation", "transcript", "audio", "video", "recording",
    "conference call", "earnings call", "analyst", "investor meet",
    "schedule of", "press release", "corrigendum",
)


def looks_like_results(purpose):
    """
    True only for text that describes the filing of the numbers.

    Used for BOARD-MEETING purposes, where the purpose string is all we
    get ("To consider and approve the unaudited financial results").
    For announcements use is_results_announcement(), which can also see
    the category.
    """
    text = str(purpose or "").lower()
    if not any(marker in text for marker in _RESULT_MARKERS):
        return False
    return not any(noise in text for noise in _NOISE_MARKERS)


def is_results_announcement(desc, body=""):
    """
    True only for the announcement that CARRIES the numbers.

    `desc` is NSE's category. Judging on the body alone is what produced
    the 598-minute spreads -- see the note above.
    """
    category = str(desc or "").lower().strip()
    if any(bad in category for bad in _EXCLUDED_CATEGORIES):
        return False
    if not any(good in category for good in _RESULT_CATEGORIES):
        return False
    # A board meeting can be about fundraising or an appointment, so the
    # text still has to mention the numbers.
    text = f"{category} {str(body or '').lower()}"
    if not any(marker in text for marker in _RESULT_MARKERS):
        return False
    return not any(noise in text for noise in _NOISE_MARKERS)


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
                  if k not in ("symbol", "results_date", "broadcast_at")
                  and v}
        with self.engine.begin() as conn:
            stmt = sqlite_insert(self.events).values(values)
            if values["broadcast_at"] is not None:
                # Keep the EARLIEST broadcast of the day. Several
                # documents get filed on results day -- the numbers
                # first, then the presentation, the transcript, the
                # newspaper copy. The first one is when the market
                # learned; the rest are noise that would drag the
                # estimate later. COALESCE handles the NULL case: with
                # nothing stored yet, min(new, new) is just the new one.
                update["broadcast_at"] = func.min(
                    func.coalesce(self.events.c.broadcast_at,
                                  stmt.excluded.broadcast_at),
                    stmt.excluded.broadcast_at,
                )
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
        """
        Past broadcast times for one symbol, minutes past midnight, at
        most ONE PER CALENDAR QUARTER.

        A company reports four times a year. If the same quarter
        contributes several samples, they are follow-up filings that
        slipped through the subject filter -- and they would silently
        weight that quarter more heavily than the others. Earliest in
        each quarter wins, for the same reason as in remember().
        """
        by_quarter = {}
        for row in self.history_for(symbol):
            at = row.get("broadcast_at")
            if not isinstance(at, datetime):
                continue
            key = (at.year, (at.month - 1) // 3)
            if key not in by_quarter or at < by_quarter[key]:
                by_quarter[key] = at
        return [at.hour * 60 + at.minute
                for at in (by_quarter[k] for k in sorted(by_quarter))]

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
                    samples=len(times), spread_minutes=spread,
                    reliable=(spread <= RELIABLE_SPREAD_MINUTES
                              and len(times) >= 3))

    def pulse(self, symbol, min_samples=2):
        """One plain-English line, or None."""
        t = self.typical_time(symbol, min_samples=min_samples)
        if not t:
            n = len(self.observed_times(symbol))
            return (f"no timing history yet ({n} observed)" if n
                    else "no timing history yet")
        if not t["reliable"]:
            return (f"NO reliable pattern -- {t['samples']} past results "
                    f"spread over {t['spread_minutes']} min "
                    f"(median {t['hhmm']}, do not rely on it)")
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

        One override: if we hold NO broadcast timings at all, always
        refresh. Zero timings means the pulse has never once worked, so
        throttling is throttling a thing that has never succeeded --
        exactly what happened on 2026-07-26, when this gate skipped the
        run that carried the fix for it.
        """
        day = _as_date(day) or datetime.now().date()
        if self.stats()["with_time"] == 0:
            return True
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
    pulse.

    SOURCE: NSE's CORPORATE ANNOUNCEMENTS feed, not financial_results.

    financial_results looked like the obvious choice and was tried
    first. It returns almost nothing: 91 rows for a whole year even when
    walked in 30-day chunks, and every one of them a late filing of
    2018-19 accounts by a delisted name (IL&FSTRANS, Videocon). Not one
    was in our 750. Chunking did not help, so the endpoint is simply not
    a usable history of who reported when.

    corporate-announcements IS that history. Every results filing is
    broadcast there, tagged with `an_dt` -- a real timestamp like
    "25-Jun-2026 16:39:17" -- which is exactly the field the pulse needs.
    The trade-off is that it carries EVERY announcement, so we filter on
    the subject text (looks_like_results).
    """
    today = _as_date(today) or datetime.now().date()
    stored = 0
    seen = matched = no_date = not_results = 0
    sample_keys = []

    start = today - timedelta(days=days_back)
    while start < today:
        end = min(start + timedelta(days=chunk_days), today)
        try:
            from nse import NSE
            with NSE(download_folder="data") as n:
                rows = n.announcements(
                    index="equities",
                    from_date=datetime.combine(start, datetime.min.time()),
                    to_date=datetime.combine(end, datetime.min.time())) or []
        except Exception as exc:
            warn(f"[RESULTS] Announcements {start}..{end} unavailable "
                 f"({exc}).")
            rows = []

        for row in rows:
            if not isinstance(row, dict):
                continue
            seen += 1
            if not sample_keys:
                sample_keys = sorted(row.keys())

            symbol = str(row.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            if known_symbols and symbol not in known_symbols:
                continue

            desc = str(row.get("desc") or row.get("subject") or "")
            body = str(row.get("attchmntText") or "")
            if not is_results_announcement(desc, body):
                not_results += 1
                continue
            subject = f"{desc} {body}".strip()
            matched += 1

            broadcast = _as_datetime(
                row.get("an_dt") or row.get("sort_date")
                or row.get("exchdisstime"))
            day = broadcast.date() if broadcast else _as_date(
                row.get("an_dt") or row.get("sort_date"))
            if day is None:
                no_date += 1
                continue

            if calendar.remember(symbol, day,
                                 purpose=subject.strip()[:200] or
                                 "Financial Results (announced)",
                                 broadcast_at=broadcast, source="NSE_ANN"):
                stored += 1

        start = end

    # Explain a zero precisely -- the causes need different fixes and all
    # look identical from outside.
    if not seen:
        warn("[RESULTS] NSE returned no announcements at all for the "
             "window.")
    elif not matched:
        warn(f"[RESULTS] {seen} announcements seen, none were results "
             f"filings for our universe ({not_results} were other "
             f"subjects). Keys seen: {sample_keys}")
    elif not stored:
        warn(f"[RESULTS] {matched} results announcements matched but none "
             f"could be dated ({no_date} unparseable). Field names have "
             f"probably changed. Keys seen: {sample_keys}")
    return stored


# ==================================================================
# THE CHANNEL THAT ACTUALLY PUBLISHES THE CALENDAR.  5 Sep 2026.
# ==================================================================
#
#     "result gate = same as now , only block that stock/s on their
#      result day , to know which stock earnings pulse channel post
#      that image. this settles i think"        -- the operator
#
# The gate was already exactly what he describes. core/results_gate.py
# blocks a stock only on its own result day, only until the numbers
# land, and lets it through on GOOD or STRONG. Nothing about the RULE
# needed changing.
#
# What was broken is the LIST it reads. earnings_calendar is built in
# main.py from NSE board meetings plus a hand-typed dict, and on
# 5 September that store said:
#
#     last_refresh        2026-08-31
#     due from today on   0
#
# Zero. So the gate blocked nobody, and core/morning_ready.py -- which
# reads the same table -- reported "out of season, nothing due" on days
# when companies were reporting.
#
# Earnings Pulse publishes the list every day, and the CAPTION carries
# it in plain text, so this needs no picture-reading at all:
#
#     "Tomorrow's Calendar - 05 Sep, 2026
#      Key companies reporting results: #MOLBIO"
#
#     "THE WEEK AHEAD: Earnings Calendar
#      Key companies: #LALITHAA #SHIPROCKET #GAJA #BLEL"
#     picture: "MONDAY, SEPTEMBER 7 ... SHIPROCKET BLEL
#               THURSDAY, SEPTEMBER 10 ... GAJA
#               FRIDAY, SEPTEMBER 11 ... LALITHAA"
#
# BOTH shapes are read, because they fail differently. The daily one is
# exact but exists only if that post was collected; the weekly one is
# redundancy for the day it was missed. Measured on the store: 9 daily
# posts and 16 weekly ones with full day headers, covering 19-26 and
# 31 August and 2, 4, 5, 7, 10 and 11 September.
#
# WHERE THE SYMBOLS COME FROM: the caption hashtags, always. The
# picture is used ONLY to decide WHICH DAY each of those already-named
# companies belongs to. A company is never invented from a transcript
# -- an OCR slip that produced a symbol would put a stock on a results
# blackout it is not on, and this gate REFUSES entries.

_TG_DB = os.path.join("data", "telegram.db")

_TOMORROW = re.compile(
    r"tomorrow'?s calendar\s*[-\u2013]\s*(\d{1,2})\s+([A-Za-z]{3,9}),?\s*"
    r"(\d{4})", re.I)
_DAYHEAD = re.compile(
    r"\b(?:MON|TUE|WED|THU|FRI|SAT|SUN)[A-Z]*DAY,?\s+"
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})",
    re.I)
_TAG = re.compile(r"#([A-Z][A-Z0-9&\-]{1,})")

# ---- THE HEADER SAYS WHICH WEEK IT IS. 5 September 2026. ----
#
#     "ON TOP OF THE IMG = HEADER PART MENTIONS THE SAME DETAILS
#      WEEK AHEAD RESULTS."                     -- the operator
#
# He is right, and it is the only independent check available on a card
# whose grid the reader has scrambled:
#
#     EARNINGS PULSE: THE WEEK AHEAD  SEPTEMBER 7-11  Q1 FY27 EARNINGS
#     EARNINGS PULSE: THE WEEK AHEAD  AUGUST 25-31
#     EARNINGS PULSE: THE WEEK AHEAD  AUGUST 31-SEPTEMBER 2
#
# Two shapes -- "MONTH D-D" within one month, and "MONTH D-MONTH D"
# across two. A date read off the day headings that falls outside the
# week the card says it covers did not come from that card, and is
# dropped rather than stored.
_WEEK_RANGE = re.compile(
    r"WEEK\s+AHEAD\W{0,12}?"
    r"(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+(\d{1,2})"
    r"\s*[-\u2013]\s*"
    r"(?:(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s+)?"
    r"(\d{1,2})", re.I)
_MONTHS = {m: i + 1 for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"])}


def _month_number(word):
    return _MONTHS.get(str(word or "")[:3].upper())


def telegram_calendar_rows(db_path=None, since_days=30, now=None):
    """[(symbol_tag, date)] from the calendar posts on file.

    Pure reading -- no database is written and nothing is resolved to a
    master symbol here, so this can be tested and eyeballed on its own.
    The tags come back exactly as the publisher typed them.
    """
    db_path = db_path or _TG_DB
    now = now or datetime.now()
    # {tag: (rank, posted, date)} -- see the note at the bottom of this
    # function for what rank means and why it is needed.
    best = {}
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute(
            "SELECT at, text, ocr_text FROM messages "
            "WHERE text LIKE '%alendar%' OR ocr_text LIKE '%ALENDAR%' "
            "OR text LIKE '%eek Ahead%' OR ocr_text LIKE '%EEK AHEAD%'"
        ).fetchall()
        conn.close()
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[RESULTS] Could not read {db_path}: {exc}")
        return []

    for at, text, ocr in rows:
        caption = str(text or "")
        body = f"{caption}\n{ocr or ''}"
        tags = _TAG.findall(caption.upper())
        if not tags:
            continue
        # ---- THE STAMP CARRIES AN OFFSET. 5 September 2026. ----
        #
        # _as_date() returns None for "2026-08-25T02:30:19+00:00" --
        # the offset defeats it -- so every post was dated TODAY and
        # "the newest card wins" quietly became "whichever row sqlite
        # returned first wins". It happened to be right on the live
        # store and wrong the moment it was tested with two cards.
        #
        # Ordering is done on the RAW stamp: an ISO timestamp sorts
        # correctly as text, needs no parsing and cannot be off by a
        # timezone. The DATE is only wanted for the year, which the
        # first ten characters give exactly.
        posted = str(at or "")
        posted_day = _as_date(posted[:10]) or now.date()

        # ---- the daily post: one date, every tag on it ----
        m = _TOMORROW.search(body)
        if m:
            month = _month_number(m.group(2))
            if month:
                try:
                    when = _date(int(m.group(3)), month, int(m.group(1)))
                except ValueError:
                    when = None
                if when:
                    for tag in tags:
                        _keep(best, tag, 2, posted, when)
                    continue

        # ---- the weekly post: a date per day heading ----
        #
        # The heading carries no year, so it is taken from the post.
        # A December card naming JANUARY is next year -- the only place
        # the year can be wrong, and the one line that fixes it.
        heads = _DAYHEAD.findall(body)
        if not heads:
            continue

        # The week the card says it covers -- see _WEEK_RANGE. None
        # when the header did not read, and then nothing is bounded,
        # because refusing every card whose header was blurred would
        # cost far more than the one it protects against.
        span = None
        wm = _WEEK_RANGE.search(body.upper())
        if wm:
            m1 = _month_number(wm.group(1))
            m2 = _month_number(wm.group(3)) or m1
            if m1 and m2:
                y1 = posted_day.year
                if m1 < posted_day.month - 6:
                    y1 += 1
                y2 = y1 + (1 if m2 < m1 else 0)
                try:
                    span = (_date(y1, m1, int(wm.group(2))),
                            _date(y2, m2, int(wm.group(4))))
                except ValueError:
                    span = None
        sections = []
        upper = body.upper()
        marks = [(mm.start(), mm.group(1), mm.group(2))
                 for mm in _DAYHEAD.finditer(upper)]
        for i, (pos, mon, day_num) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(upper)
            month = _month_number(mon)
            if not month:
                continue
            year = posted_day.year
            if month < posted_day.month - 6:
                year += 1
            try:
                when = _date(year, month, int(day_num))
            except ValueError:
                continue
            if span and not (span[0] <= when <= span[1]):
                diagnostic(f"[RESULTS] a day heading read as {when} is "
                           f"outside the week this card states "
                           f"({span[0]} to {span[1]}) -- ignored")
                continue
            sections.append((when, upper[pos:end]))

        for when, chunk in sections:
            for tag in tags:
                # The tag has to APPEAR in that day's section. This is
                # the whole reason the picture is read at all: the
                # caption says who reports this week, the picture says
                # who reports on which day.
                if tag.upper() in chunk:
                    _keep(best, tag, 1, posted, when)

    return sorted((tag, when) for tag, (_r, _p, when) in best.items())


def _keep(best, tag, rank, posted, when):
    """Keep one date per company: the best-sourced, then the newest.

    ---- THE PICTURE IS READ COLUMN BY COLUMN. 5 Sep 2026. ----

    The week-ahead card is a GRID, and a flat transcript of a grid
    scrambles which company sits under which day. The 24 August card
    came out as

        ARDEE MVELECTRO AFTER CLOSE AFTER CLOSE
        WEDNESDAY, AUGUST 26  TUESDAY, AUGUST 25  MILKYMIST
        AFTER CLOSE  MONDAY, AUGUST 31

    -- so splitting on day headings put MILKYMIST on 25 August. The
    cards published on the 25th, 26th and 27th all place it under
    MONDAY, AUGUST 31, and they are right. This is the same fault that
    put nine companies in the wrong session on 2 August, and the word
    positions now stored beside each transcript are the eventual fix
    for it.

    Two rules until then, and both are about trusting the better
    source:

      RANK 2 -- "Tomorrow's Calendar" states ONE date for the whole
                post. There is no grid to scramble, so it always wins.
      RANK 1 -- the week-ahead grid, where the newest card wins,
                because the publisher has repeated the week every day
                and the last word is the one they stand on.
    """
    have = best.get(tag)
    if have is None or (rank, posted) > (have[0], have[1]):
        best[tag] = (rank, posted, when)


def fetch_from_telegram(calendar, known_symbols=None, db_path=None,
                        now=None):
    """Put the channel's calendar into the store. Returns rows written.

    Fails open like the other fetchers: a chat feed that cannot be read
    must never stop the NSE refresh that follows it.
    """
    try:
        rows = telegram_calendar_rows(db_path=db_path, now=now)
    except Exception as exc:                                # noqa: BLE001
        diagnostic(f"[RESULTS] Telegram calendar unreadable: {exc}")
        return 0
    if not rows:
        return 0

    known = {str(s).upper() for s in (known_symbols or ())}
    written = 0
    unknown = []
    for tag, when in rows:
        symbol = str(tag).upper()
        if known and symbol not in known:
            # NEVER GUESS. A tag the master does not carry is recorded
            # in the log and nowhere else -- inventing a symbol here
            # would blacklist a stock from trading on a day it does not
            # report, and this gate REFUSES entries.
            unknown.append(symbol)
            continue
        if calendar.remember(symbol=symbol, results_date=when,
                             purpose="Results (Earnings Pulse)",
                             source="telegram:Earnings Pulse"):
            written += 1
    if unknown:
        diagnostic(f"[RESULTS] {len(unknown)} calendar tag(s) are not in "
                   f"the master and were not stored: "
                   f"{', '.join(sorted(set(unknown))[:8])}")
    if written:
        decision(f"[RESULTS] {written} result date(s) taken from the "
                 f"Earnings Pulse calendar.")
    return written


def refresh(calendar=None, known_symbols=None, days_ahead=45,
            days_back=400, force=False, today=None):
    """One full refresh. Never raises.

    Skipped entirely when nothing is due -- see needs_refresh(). Results
    are a four-times-a-year event; polling NSE every morning in, say,
    September buys nothing.
    """
    calendar = calendar or ResultsCalendar()
    today = _as_date(today) or datetime.now().date()

    # ---- READ THE CHANNEL FIRST, ALWAYS. 5 September 2026. ----
    #
    # Before the needs_refresh() gate, deliberately. That gate exists to
    # stop polling NSE every morning for something that happens four
    # times a year, and it is right to. This costs one read of a local
    # sqlite file the collector has already filled, so there is nothing
    # to throttle -- and skipping it is exactly how the store came to
    # say "0 due from today" while Earnings Pulse was publishing a name
    # every afternoon.
    fetch_from_telegram(calendar, known_symbols=known_symbols)

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
