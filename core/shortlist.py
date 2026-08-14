"""
==========================================================
Shortlist -- the names worth the operator's attention, live
==========================================================

Operator, 2026-07-27:

    "as a human i cannot read all 750/960/1500 stocks daily, i created
     bot to trade beside me not replacing me"

    "yes on dashboard its worth to take action instantly"

WHAT THIS REPLACES
------------------
core/momentum_universe.py ranks every symbol by ONE number -- % change
against its own day open -- and LOCKS the top 25 at 09:30. Price, and
nothing else, decided once.

On 2026-07-27 that surfaced SWIGGY and AWFIS, neither with any event
behind it, and never showed the operator:

    TMB        +12.1%   Q1 update, total advances +27% YoY
    CARTRADE   +10.8%   UBS initiated Buy, target Rs 4,000
    KFINTECH    +9.2%   Q1 results, revenue +30% YoY, profit beat
    SENCO       +7.4%   Q1 update, revenue +60% YoY

Every one was public before 09:15. The bot was not short of data; it
only ever looked at price.

WHY IT IS NOT A ONE-SHOT LOCK
-----------------------------
Measured on 2026-07-27 by rebuilding this ranking at nine clock times
using only the bars available at each (tools/shortlist_stability.py):

    of the closing top 20, how many were already top 20 at...
        09:30   12/20        13:00   13/20        15:00   17/20

Some names never move -- KFINTECH sat 8,7,7,10,5,4,3,2,3 all day and
could have been acted on in the first fifteen minutes. TMB did the
opposite: rank 16, then 95 at noon, then 2 at the close, with 98% of
its 7.17m shares traded after 13:00 and its busiest minute at 15:17.

A list frozen at 09:30 cannot contain TMB. So this one is rebuilt on
every dashboard refresh. In fairness the effect is smaller than TMB
alone suggests -- 19 of 22 gainers had made most of their move by
13:00 -- so continuous ranking buys three or four names a day. Today
one of them was the best stock on the board.

RANKED ON MOVEMENT, EXPLAINED BY REASON
---------------------------------------
The first version of this scored "quiet volume" as a positive and
buried TMB at rank 45 for trading 39x normal volume on the day it
reported. That was a category error. The quiet-volume finding (7.5
years, 631,736 stock-days) answers "will this keep running for 20
days?" -- a HOLDING question. This file answers "does this deserve
thirty seconds of attention?" and a 12% move on results day is the most
important thing on the board whatever the volume did.

So size of move ranks. Volume character is printed as a note the
operator weighs, never as a score.

WHAT IT DELIBERATELY DOES NOT DO
--------------------------------
It does not buy. It does not filter hard. A screener working beside a
human must MISS NOTHING -- eight names when three are worth it costs
thirty seconds; missing TMB costs the trade.

THE KNOWN HOLE
--------------
The calendar knows WHO reported, not whether the numbers were GOOD. On
2026-07-27 both groups had results events: KFINTECH reported and rose
9.2%, ACUTAAS reported the same week and fell. Until per-quarter QoQ
figures are stored, "results out" means "worth a look", nothing more.
Do not read the score as a recommendation.

Author : H&M Opportunity Trader
==========================================================
"""

import collections
import os
import re
import sqlite3
import statistics
import threading
from datetime import datetime, timedelta

from core.chain import call as chain_call
from core.chain import rank as chain_rank
from core.chain import read as chain_read
from core.chain import reason as chain_reason
from core.chain import summary as chain_summary
from core.logger import diagnostic, warn

DAILY_DB = os.path.join("data", "daily_candles.db")
RESULTS_DB = os.path.join("data", "results_calendar.db")
MEMORY_DB = os.path.join("data", "stock_memory.db")

# Below this a Rs 6 lakh position cannot be filled without moving the
# price. Such names are not dropped silently -- they go to a separate
# "moved but too thin" list, because DPABHUSHAN rose 6.7% on 2026-07-27
# and vanished from the first version of this without a word.
MIN_TURNOVER = 5e7

QUIET_MAX = 1.5        # volume at or under this x its own normal
LOUD_MIN = 6.0         # at or over this = the crowd is already here
THIN_ALERT_PCT = 4.0   # a thin stock moving this much is still news

RESULTS_BACK_DAYS = 5  # a result 3 days old still moves a stock
RESULTS_FWD_DAYS = 3   # one due in 2 days already does

# Price SCALE changed -- a % move against an unadjusted close is a lie.
# The JLHL 2:10 case, read by this bot as -80%.
VETO_ACTIONS = {"SPLIT", "BONUS", "RIGHTS", "DEMERGER"}

# A DISPLAY bar, not an entry bar. Owned by core/rules.py so it has
# one home -- value unchanged, nothing on the screen moves.
from core.rules import SHORTLIST_MIN_MOVE_PCT as MIN_MOVE_PCT
MIN_SCORE = 2.0        # below this, not worth a line

# ---------------------------------------------------------------
# READING ORDER for chips that score nothing
# ---------------------------------------------------------------
# Only three chips in a 50-row table can be read at a glance, so what
# occupies those three matters. Scoring reasons sort by their own
# points. These do not score at all and still have to be placed:
#
#   CAUTION_HIGH  "CROWDED 30x -- likely already priced". Worth as much
#                 as a mid-weight reason. It is the one thing on the row
#                 that argues against acting, and burying it under three
#                 positives is how a screener flatters itself.
#   ECHO          a second source saying the same thing as the first.
#                 Not counted twice in the score, genuinely useful to
#                 see -- two independent sources agreeing is the
#                 strongest statement this panel can make.
#   CAUTION       "quiet 1.2x" -- context, not a warning.
#   CAUTION_LOW   volume ratios and the 50-day line. Background.
#   LAST          the price move itself. It is WHAT is being explained,
#                 and it is already printed in its own column two cells
#                 to the left.
# Above every scoring chip. When the filed numbers and the channel
# disagree about the same quarter, that disagreement outranks either
# verdict -- see the APTUS note in rank(). It is a LOOK, not a signal,
# so it scores nothing and is never collapsed behind a "+N".
# Just under CONFLICT. A grade the market has already contradicted is
# the second most useful thing that can be said about a row, and it
# says something no other chip does: that the news is out and the
# price has answered it.
# Read straight after the result itself. "Expected BEARISH" beside a
# weak quarter is the difference between a warning and a non-event.
EXPECTATION = 4.5
MARKET_ANSWER = 8.0
CONFLICT = 9.0
CAUTION_HIGH = 3.5
ECHO = 2.6
CAUTION = 1.4
CAUTION_LOW = 0.5
LAST = -99.0

# ---------------------------------------------------------------
# HOW FAR BACK THE EVENT MEMORY IS READ
# ---------------------------------------------------------------
# Was 36 hours, which quietly meant THE WEEKEND DID NOT EXIST.
#
#     "real gap as far i concerned about after my terminal(laptop)
#      close to next opening. & weekends data?"
#
# Friday's close to Monday's open is 65.5 hours. An excellent result
# posted on Friday afternoon was still in the events database on
# Monday morning -- events are never pruned -- but 65 hours is outside
# a 36-hour window, so nothing read it. The stock would open Monday
# near the top of the gainers with no reason chip beside it, which is
# the precise failure he has been describing all evening.
#
# 96 hours clears a normal weekend with room for a Friday-night
# posting. It does NOT clear a long weekend with a Monday holiday --
# that needs the session calendar rather than a fixed number, and is
# worth doing properly rather than by adding hours until it stops
# hurting.
#
# Anything not from today is labelled with its age on the chip. A
# reason from Friday is still a reason; it is not the same as one from
# eleven minutes ago, and the operator has to be able to tell.
EVENT_WINDOW_HOURS = 96

# A safety valve, NOT a filter -- EVENT_WINDOW_HOURS is what selects
# the window. Measured 1 August 2026: 2,058 rows inside 96 hours, and
# the old value of 2,000 was already dropping 58 of them, silently and
# always the oldest.
#
# Set at more than TEN TIMES the observed volume on purpose. A cap
# placed just above today's number is a cap that bites again in a
# fortnight, and the failure is invisible when it does -- a stock whose
# evidence fell off the end simply has no chips, which looks exactly
# like a stock nothing has happened to. About seven weeks of headroom
# at the observed rate, and a few thousand rows cost milliseconds.
EVENT_ROW_CAP = 25000


# Reference data is the same for every builder on a given day, and
# loading it means reading a 151 MB daily store. Sharing it across
# instances is not a micro-optimisation: the dashboard's own tests
# construct 45 DashboardStates and went from instant to 22 seconds,
# which is 45 identical reads of the same file. In the live bot there is
# only one builder, so this changes nothing there -- but a suite nobody
# wants to run is a suite that stops being run.
_REFERENCE_LOCK = threading.Lock()
_REFERENCE_CACHE = {}          # (daily_db, results_db, memory_db, date) -> tuple


# What the parsers put in FRONT of a headline, separated by " -- ".
# Only these are shown as a chip in their own right: everything else
# before the separator is raw OCR, and raw OCR in a chip is how a
# panel becomes unreadable.
# "CLEAN |" sits in its own alternative rather than in the \b list,
# for two reasons. A word boundary cannot follow the pipe, so it never
# matched there at all; and CLEAN is a real NSE ticker (Clean Science),
# so a bare CLEAN would turn that company's every headline into a chip
# of raw OCR. The pipe is what makes it OUR label rather than a name.
_LEAD_FACT = re.compile(
    r"^\s*((?:ONE-?OFF|NOT\s+CLEAN|WATCH|MISS|BEAT|MET|STRONG\s+BEAT|"
    r"IN[\s-]?LINE)\b.*?|CLEAN\s*\|.*?|.*?\bvs\s+est\b.*?)\s+--\s", re.I)


def _lead_fact(headline):
    """The fact a parser found, or None.

    "ONE-OFF: Dividend income from subsidiary: Rs 39.5 Cr -- Earnings
    Pulse EARNINGS BRIEF CDSL Q1 FY27 GREAT Strong standalone..."
                              ^ this half, and not the rest of it

    Written 1 August 2026, because the panel was throwing this away.
    The chip said "PULSE: Weak results" while the headline underneath
    it carried the 39.5 Cr that explained the whole quarter:

        "as a human we cannot grasp all image data & trade decision
         right? bot will fill that gap by giving me correct info
         rather than pasting simple chips at why"
    """
    found = _LEAD_FACT.match(" ".join(str(headline or "").split()))
    if not found:
        return None
    fact = found.group(1).strip(" .;-")
    return fact[:88] if len(fact) >= 6 else None


def _source_name(source):
    """A channel name short enough to fit two of them in one chip.

    "Earnings Pulse says Great, Earnings Pulse FinAI says Weak" does
    not fit in the 80 characters the panel shows; "Brief says Great,
    FinAI says Weak" does, and is the same sentence.
    """
    name = " ".join(str(source or "").split())
    if not name:
        return "one card"
    short = {"earnings pulse": "Pulse", "earnings pro": "Pro",
             "earnings 360": "360", "orderbook pulse": "Orderbook",
             "business pulse": "Business", "day trader telugu": "DayTrader"}
    return short.get(name.lower(), name[:14])


def _age_suffix(at, today=None):
    """" (Fri)" or " (2d ago)" for anything not from today, else "".

    Reading the event window back to 96 hours means a chip on Monday
    morning can be describing something that happened on Friday. That
    is worth showing -- an excellent quarter does not expire over a
    weekend -- but it is NOT the same as a result eleven minutes old,
    and a panel that presents them identically is lying by omission.

    Fails silent and returns "" on anything it cannot parse. An
    unreadable timestamp must not cost the chip.
    """
    if not at:
        return ""
    try:
        stamp = str(at)[:10]
        when = datetime.strptime(stamp, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return ""
    try:
        now = (datetime.strptime(today, "%Y-%m-%d").date() if today
               else datetime.now().date())
    except (TypeError, ValueError):
        now = datetime.now().date()
    days = (now - when).days
    if days <= 0:
        return ""
    if days == 1:
        return " (yesterday)"
    if days <= 6:
        return f" ({when.strftime('%a')})"
    return f" ({days}d ago)"


def _newest_per_fact(rows):
    """The same fact once, newest first. DISPLAY ONLY -- nothing is
    deleted and the store is not touched.

    ---- 2 August 2026, from his screenshot ----
    The panel showed NH three times and CONCORDBIO three times, the
    same sentence each. Counted across the store:

        80   CANSLIM rows differing only by the date in brackets
       145   REPORTED rows re-filed by a later recap
        13   exact duplicates

    Most of it is mine, from today: load_canslim ran on the 1st and
    again on the 2nd, and the recap parser re-files a company the
    forward card already named.

    WHY THIS IS NOT THE DEDUPLICATION THAT KEEPS FAILING.
    _events_for()'s own comment says the store is deliberately NOT
    deduplicated -- "every attempt to collapse them safely has failed:
    see StockEvents.remember() ... losing an event costs a trade." That
    is about DELETING rows, and it is right.

    This deletes nothing. Every row stays in stock_events.db, every
    tool still reads all of them, and outcome tracking still measures
    each one. The panel simply stops printing the same sentence three
    times. Reversible by removing one call.
    """
    seen, out = set(), []
    for row in sorted(rows or [],
                      key=lambda r: str(r.get("at") or ""), reverse=True):
        key = ShortlistBuilder._same_fact(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


class ShortlistBuilder:
    """Reference data is loaded once per trading day and cached; ranking
    itself is pure arithmetic over rows the dashboard already computed.

    Every read is fail-OPEN. A missing database means the shortlist
    degrades to "ranked by movement", which is still better than what
    momentum_universe gave. It must never take the dashboard down.
    """

    def __init__(self, daily_db=DAILY_DB, results_db=RESULTS_DB,
                 memory_db=MEMORY_DB, announcement_watcher=None,
                 quarterly_results=None, news_watcher=None,
                 stock_events=None, preopen=None):
        self.daily_db = daily_db
        self.results_db = results_db
        self.memory_db = memory_db
        # ---- ONE PER BUILDER, LIVING ACROSS REFRESHES ----
        #
        #   "in dashboard chips are changing constantly - on Yasho some
        #    times AVOID, BUY, WAIT, EXCELLENT"
        #
        # rank() runs once a second. This is the only thing here that
        # remembers the previous run, and it exists so the word on his
        # screen holds still long enough to be read and acted on. See
        # core/chain.SteadyCall.
        from core.chain import SteadyCall
        self._steady_call = SteadyCall()
        # core/announcement_watcher.py, wired 2026-07-27. The calendar
        # says a company reports TODAY; this says it filed 20 MINUTES
        # AGO. TMB's move began after 13:00 and 98% of its volume came
        # with it -- a calendar entry could never have told the operator
        # to look right then.
        # core/stock_events.py, wired 30 July 2026. THE SPEED GAP.
        #
        #     "we have telegram channel called earnings pulse which will
        #      post almost instant result & we are not utilising that at
        #      all"
        #
        # quarterly_results below knows a result AFTER the filing is
        # parsed. Earnings Pulse posts a graded verdict within seconds of
        # the company filing, and OrderBook Pulse posts an order win with
        # its value. Both were collected all day and read by nothing.
        #
        # Scored LOWER than the filed numbers on purpose: a channel's
        # one-word verdict is a good early signal, not an audited fact.
        self.stock_events = stock_events
        self._events_cache = None
        # core/reaction.py -- what the market did with a graded result.
        # None = not built yet, False = unavailable. Built on first use
        # so a builder that never reaches an event never opens the
        # daily-bar store.
        self._reaction = None
        # core/preopen.py, wired 30 July 2026. WHO IS STILL WAITING.
        #
        #     "in today premarket run . NSE , we get info like buyers are
        #      waiting here ; Sellers are waiting here ... Redington it
        #      showed Buyers are waiting"
        #
        # NSE's 09:00-09:12 auction leaves orders UNMATCHED, and that
        # residue says whether a gap has demand behind it. REDINGTON on
        # 30 July: 640,418 buys still waiting against 146,196 sells. The
        # collector has stored it since it was written; the score never
        # saw it.
        #
        # Only counts BEFORE the opening range is set. After 09:30 the
        # tape has spoken and an auction imbalance is history.
        self.preopen = preopen
        self._imbalance = None
        self.announcement_watcher = announcement_watcher
        # core/quarterly_results.py, wired 2026-07-27. The calendar and
        # the watcher both say a company REPORTED. This says whether the
        # numbers were better than last quarter -- the only thing that
        # separated KFINTECH (+9.2%) from ACUTAAS (-Rs 1,593) that day,
        # since both filed in the same week.
        self.quarterly_results = quarterly_results
        # core/news_watcher.py. Filings are not the whole story: on
        # 2026-07-27 the day's biggest mover either way -- GANDHAR
        # -11.6% on a plant flood, CARTRADE +10.8% on a UBS initiation
        # -- were both invisible to a filings-only feed.
        self.news_watcher = news_watcher
        self._qoq_cache = {}
        self._lock = threading.Lock()
        self._loaded_for = None      # date string the cache belongs to
        self._normals = {}           # symbol -> (median_vol, median_turnover, ma50)
        self._results = {}           # symbol -> [(days_away, purpose)]
        self._actions = {}           # symbol -> [(action_type, ex_date)]

    # ------------------------------------------------------------
    # REFERENCE DATA -- slow, loaded once a day
    # ------------------------------------------------------------

    def ensure_loaded(self, today=None):
        today = today or datetime.now().date().isoformat()
        with self._lock:
            if self._loaded_for == today:
                return
        key = (self.daily_db, self.results_db, self.memory_db, today)
        with _REFERENCE_LOCK:
            cached = _REFERENCE_CACHE.get(key)
            if cached is None:
                cached = (self._load_normals(today),
                          self._load_results(today),
                          self._load_actions(today))
                # Only today's entry is worth keeping; anything else is
                # a finished day or a test fixture.
                _REFERENCE_CACHE.clear()
                _REFERENCE_CACHE[key] = cached
                fresh = True
            else:
                fresh = False
        with self._lock:
            self._normals, self._results, self._actions = cached
            self._loaded_for = today
        if not fresh:
            return
        diagnostic(
            f"[SHORTLIST] Reference loaded for {today}: "
            f"{len(self._normals)} symbols with 50-day normals, "
            f"{len(self._results)} with results near, "
            f"{len(self._actions)} with corporate actions."
        )

    def _ro(self, path):
        if not os.path.exists(path):
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True)

    def _load_normals(self, today, lookback=50):
        """(median daily volume, median daily turnover, 50-day average
        close) per symbol, from bars STRICTLY BEFORE today. Using today's
        own bar to judge whether today is unusual would be circular."""
        out = {}
        conn = self._ro(self.daily_db)
        if conn is None:
            warn(f"[SHORTLIST] {self.daily_db} missing -- no volume/trend "
                 f"context; ranking on movement alone.")
            return out
        try:
            # Only the recent window: reading all 1.08m rows takes many
            # seconds and this runs inside the dashboard's own loop.
            since = (datetime.strptime(today, "%Y-%m-%d").date()
                     - timedelta(days=160)).isoformat()
            rows = conn.execute(
                "select symbol,close,volume from daily_bars "
                "where date>=? and date<? order by symbol,date",
                (since, today)).fetchall()
            by = collections.defaultdict(list)
            for s, cl, v in rows:
                by[s].append((cl or 0, v or 0))
            for s, ser in by.items():
                w = ser[-lookback:]
                if len(w) < 20:
                    continue
                out[s] = (
                    statistics.median([v for _, v in w]) or 1,
                    statistics.median([cl * v for cl, v in w]) or 0.0,
                    sum(cl for cl, _ in w) / len(w),
                )
        except sqlite3.Error as e:
            warn(f"[SHORTLIST] Could not read daily bars: {e}")
        finally:
            conn.close()
        return out

    def _load_results(self, today):
        out = collections.defaultdict(list)
        conn = self._ro(self.results_db)
        if conn is None:
            return dict(out)
        try:
            d0 = datetime.strptime(today, "%Y-%m-%d").date()
            lo = (d0 - timedelta(days=RESULTS_BACK_DAYS)).isoformat()
            hi = (d0 + timedelta(days=RESULTS_FWD_DAYS)).isoformat()
            for sym, rd, purpose in conn.execute(
                    "select symbol,results_date,purpose from results_events "
                    "where results_date between ? and ?", (lo, hi)):
                try:
                    days = (datetime.strptime(rd, "%Y-%m-%d").date() - d0).days
                except (TypeError, ValueError):
                    continue
                out[sym].append((days, purpose or ""))
        except sqlite3.Error as e:
            warn(f"[SHORTLIST] Could not read results calendar: {e}")
        finally:
            conn.close()
        return dict(out)

    def _load_actions(self, today):
        out = collections.defaultdict(list)
        conn = self._ro(self.memory_db)
        if conn is None:
            return dict(out)
        try:
            d0 = datetime.strptime(today, "%Y-%m-%d").date()
            lo = (d0 - timedelta(days=3)).isoformat()
            hi = (d0 + timedelta(days=30)).isoformat()
            for sym, at, ex in conn.execute(
                    "select symbol,action_type,ex_date from stock_actions "
                    "where ex_date between ? and ?", (lo, hi)):
                out[sym].append((str(at).upper(), str(ex)))
        except sqlite3.Error as e:
            warn(f"[SHORTLIST] Could not read stock memory: {e}")
        finally:
            conn.close()
        return dict(out)

    # Grade -> score. STRONG and GOOD lift a name; WEAK pushes it down,
    # because a longs-only book wants to know a stock reported BADLY just
    # as much as it wants to know it reported well.
    #
    # These weights are NOT validated against price outcomes -- nothing
    # has measured whether STRONG quarters outperform, because that needs
    # years of stored results matched to daily bars and the store starts
    # empty. They are deliberately smaller than the movement score so
    # they re-order names rather than invent a ranking of their own.
    GRADE_SCORE = {"STRONG": 5.0, "GOOD": 3.0, "MIXED": 0.0, "WEAK": -3.0}

    # An instant verdict from Earnings Pulse. Deliberately BELOW
    # GRADE_SCORE: the filed numbers are arithmetic, this is somebody
    # else's one-word summary of them. It arrives hours earlier, which is
    # the entire reason to use it, and it is not worth as much.
    PULSE_SCORE = {"EXCELLENT": 4.0, "GREAT": 4.0, "GOOD": 2.5,
                   "OK": 0.0, "WEAK": -2.5, "POOR": -3.5}

    # An order win. Size matters, so it is banded rather than flat -- a
    # Rs 2 crore contract and a Rs 2,205 crore contract are not the same
    # news, and treating them alike is how a screener starts lying.
    ORDER_SCORE_BANDS = ((1000.0, 5.0), (250.0, 4.0), (50.0, 3.0),
                         (0.0, 2.0))
    # An order with no figure at all still counts -- "wins optical fibre
    # export order" is real -- but at the bottom band.
    ORDER_SCORE_UNKNOWN = 2.0

    # A book that is 52/48 is balanced, and calling that "buyers waiting"
    # would make the signal noise. Same threshold the panel uses.
    IMBALANCE_MIN = 0.2
    IMBALANCE_SCORE = 2.0

    def _imbalance_for(self, symbol):
        """+1 all unmatched orders are buys, -1 all sells, None unknown."""
        if self.preopen is None:
            return None
        if self._imbalance is None:
            self._imbalance = {}
            try:
                book = self.preopen.snapshot() or {}
                groups = book.get("groups") or {}
                for group in groups.values():
                    if not isinstance(group, dict):
                        continue
                    for rows in group.values():
                        for row in (rows or []):
                            key = str(row.get("symbol") or "").upper()
                            if key and row.get("imbalance") is not None:
                                self._imbalance[key] = row["imbalance"]
            except Exception as exc:                       # noqa: BLE001
                warn(f"[SHORTLIST] Pre-open book unavailable: {exc}")
                self._imbalance = {}
        return self._imbalance.get((symbol or "").upper())

    @staticmethod
    def _same_fact(row):
        """The identity of a fact, ignoring which card delivered it.

        Two rows are the same fact when the kind and the wording match
        once the trailing date stamp is removed:

            CANSLIM MIXED -- 41 of 90 today (01 Aug)
            CANSLIM MIXED -- 41 of 90 today (02 Aug)

        Same tier, same company, two rows, because the loader ran on
        two days. Likewise REPORTED, which a later recap re-files.
        """
        head = str(row.get("headline") or "")
        head = re.sub(r"\s*\(\d{1,2}\s+[A-Za-z]{3}\)\s*$", "", head).strip()
        return (str(row.get("kind") or "").upper(), head)

    def _events_for(self, symbol):
        """Today's recorded events for one stock, read once per rebuild.

        One query for the whole universe rather than 973 -- the same
        lesson as build_corporate_actions(), which was doing a query per
        symbol on every refresh.
        """
        if self.stock_events is None:
            return []
        if self._events_cache is None:
            self._events_cache = {}
            try:
                # ---- THE LIMIT WAS ALREADY BITING. 1 August 2026. ----
                #
                # 2,058 STOCK-scope rows sat inside the 96-hour window
                # against a limit of 2,000, so 58 events were being
                # dropped before the panel ever saw them -- silently,
                # and always the OLDEST, because the query sorts
                # newest first.
                #
                # The `hours` filter is what selects the window. This
                # number is only a safety valve against a runaway
                # store, so it belongs far above the real volume
                # rather than just above it. At the measured rate --
                # roughly 2,000 rows per four days -- EVENT_ROW_CAP is
                # about three weeks of headroom.
                #
                # Raised rather than deduplicated on purpose. 400 of
                # those rows are older versions of the same event,
                # and every attempt to collapse them safely has failed:
                # see StockEvents.remember(). Reading them costs
                # milliseconds; losing an event costs a trade.
                for row in self.stock_events.recent(
                        limit=EVENT_ROW_CAP, hours=EVENT_WINDOW_HOURS,
                        scope="STOCK") or []:
                    key = (row.get("symbol") or "").upper()
                    if key:
                        self._events_cache.setdefault(key, []).append(row)
            except Exception as exc:                       # noqa: BLE001
                warn(f"[SHORTLIST] Event memory unavailable: {exc}")
                self._events_cache = {}
        return _newest_per_fact(
            self._events_cache.get((symbol or "").upper(), []))

    # STAIRCASE STEP 2, and not one step further.
    #
    # config.py lays out four steps from "the model reads news" to "the
    # model chooses which breakout to take". This is step two: its view
    # is VISIBLE and worth EXACTLY ZERO to the score.
    #
    # The zero is the whole point and it is not timidity. On 30 July the
    # bot's own arithmetic reported +Rs 9,498 on a day it really lost
    # Rs 11,239. An unchecked model stacked on an unchecked scorer is
    # two things nobody can audit, and there is no honest way to skip
    # the measurement -- every verdict is stored with the event so
    # tools/refused_review.py can ask, in a fortnight, "when it said
    # POSITIVE, what did the stock actually do?"
    #
    # Turning this into a score is a config change and a conversation,
    # not a code change. AI_MAY_AFFECT_SCORE is the switch.
    AI_CHIP_ORDER = 2.2       # read below the hard evidence, above noise
    AI_MIN_CONFIDENCE = 0.55  # below this it is a shrug, not a view

    @staticmethod
    def _is_stale(fin, event_at):
        """Do our filed numbers pre-date the result this event is about?

        The store keeps a period_end date; the event carries the moment
        the channel posted. If the quarter we hold ENDED before the
        event was posted, we are describing an older result and must
        not claim to have counted this one.

        Fails to "stale" when either date is unreadable. Getting this
        wrong in the safe direction means the channel's verdict scores
        as well -- which is one extra signal. Getting it wrong the
        other way silences a fresh warning, which is what happened to
        APTUS.
        """
        if not fin or not event_at:
            return True
        row = fin.get("latest") or {}
        ends = row.get("period_end")
        try:
            if hasattr(ends, "isoformat"):
                ends = ends.isoformat()
            ends = str(ends)[:10]
            posted = str(event_at)[:10]
            if not ends or not posted:
                return True
            return ends < posted
        except Exception:                                  # noqa: BLE001
            return True

    def _market_answer(self, symbol, at, grade):
        """"LESS BAD THAN FEARED" / "ALREADY PRICED", or None.

        Only the DISAGREEMENTS are shown. "Market agrees" is the
        expected case and putting it on 57 of 151 rows would bury the
        32 that matter -- the whole reason this exists is that a grade
        alone is right about direction fewer than four times in ten.

        Built lazily and wrapped: it opens the daily-bar store, which
        must never be able to take the panel down.
        """
        if self._reaction is None:
            try:
                from core.reaction import Reaction
                self._reaction = Reaction()
            except Exception:                              # noqa: BLE001
                self._reaction = False
        if not self._reaction:
            return None
        try:
            answer = self._reaction.verdict(symbol, at, grade)
        except Exception:                                  # noqa: BLE001
            return None
        if not answer or answer["state"] not in ("LESS BAD", "PRICED IN"):
            return None
        return answer["note"]

    def _ai_chip(self, event):
        """(text, 0.0 points, reading order) for a model verdict, or None.

        NEUTRAL is deliberately not shown. "affects this company but not
        clearly either way" is true of most news and would put a chip on
        every row, which is how a panel stops being read at all.
        """
        direction = str(event.get("ai_direction") or "").upper()
        if direction not in ("POSITIVE", "NEGATIVE"):
            return None
        confidence = event.get("ai_confidence")
        if confidence is not None and confidence < self.AI_MIN_CONFIDENCE:
            return None
        reason = (event.get("ai_reason") or "").strip()
        if not reason:
            return None
        mark = "+" if direction == "POSITIVE" else "-"
        return (f"AI {mark}: {reason[:80]}", 0.0, self.AI_CHIP_ORDER)

    def _order_score(self, value_cr):
        if value_cr is None:
            return self.ORDER_SCORE_UNKNOWN
        for floor, points in self.ORDER_SCORE_BANDS:
            if value_cr >= floor:
                return points
        return self.ORDER_SCORE_UNKNOWN

    def _financials_for(self, symbol):
        """Latest QoQ/YoY comparison for one symbol, cached for the day.
        Wrapped -- the store is optional and must never break the panel."""
        if self.quarterly_results is None:
            return None
        if symbol in self._qoq_cache:
            return self._qoq_cache[symbol]
        try:
            out = self.quarterly_results.compare(symbol)
        except Exception:                                  # noqa: BLE001
            out = None
        self._qoq_cache[symbol] = out
        return out

    # A concrete event outranks a price move, because the price move is
    # usually the CONSEQUENCE. Negative categories score too -- for a
    # longs-only book, knowing a plant is on fire matters as much as
    # knowing an order was won.
    #
    # These five have a FIXED sign. A fire is never good news; an order
    # win is never bad. The category alone settles the direction.
    NEWS_SCORE = {"DISASTER": -6.0, "REGULATORY": -5.0,
                  "ORDER_WIN": 5.0, "DEAL": 4.0, "FUND_RAISE": 1.0}

    # These four DO NOT. Until 31 July 2026 they were in the table above
    # with one flat number each, which meant:
    #
    #     "UBS issues 'sell' tag on Bajaj Finance"   scored +4.0
    #     "Tata Power cuts FY27 guidance"            scored +3.0
    #     "Company wins arbitration award"           scored -4.0
    #
    # The first is the one that was live on the operator's screen. A
    # sell rating was being rewarded exactly as much as an upgrade.
    #
    # NEUTRAL is small but not always zero. "Jefferies maintains Hold"
    # is a non-event. "NCLT hearing scheduled" is faintly bad even
    # without a verdict, which is why LEGAL/NEUTRAL is negative.
    NEWS_STANCE_SCORE = {
        "BROKER":     {"POSITIVE": 4.0, "NEGATIVE": -4.0, "NEUTRAL": 0.5},
        "GUIDANCE":   {"POSITIVE": 3.0, "NEGATIVE": -3.5, "NEUTRAL": 0.0},
        "LEGAL":      {"POSITIVE": 3.0, "NEGATIVE": -4.0, "NEUTRAL": -1.0},
        "MANAGEMENT": {"POSITIVE": 0.5, "NEGATIVE": -2.0, "NEUTRAL": -0.5},
    }

    def _news_points(self, head):
        """Score one news item, sign included.

        The stance is normally already on the item -- news_watcher sets
        it at collection. It is recomputed here when absent so that
        items reaching the score from anywhere else (Telegram, a
        replayed session, a test) are not silently scored as neutral.
        """
        kind = str(head.get("kind") or "")
        if kind not in self.NEWS_STANCE_SCORE:
            return self.NEWS_SCORE.get(kind, 0.0), None
        stance = head.get("stance")
        if not stance:
            try:
                from core.news_watcher import classify_stance
                stance = classify_stance(kind, head.get("headline"))
            except Exception:                              # noqa: BLE001
                stance = None
        stance = stance or "NEUTRAL"
        return self.NEWS_STANCE_SCORE[kind].get(stance, 0.0), stance

    def _headline_for(self, symbol):
        if self.news_watcher is None:
            return None
        try:
            return self.news_watcher.for_symbol(symbol)
        except Exception:                                  # noqa: BLE001
            return None

    def _news_for(self, symbol):
        """Today's newest announcement for one symbol, or None. Wrapped
        because the watcher is optional and must never be able to break
        the panel."""
        if self.announcement_watcher is None:
            return None
        try:
            return self.announcement_watcher.for_symbol(symbol)
        except Exception:                                  # noqa: BLE001
            return None

    # ------------------------------------------------------------
    # RANKING -- fast, every refresh
    # ------------------------------------------------------------

    def rank(self, rows, top=25, today=None):
        """`rows` are dashboard/state.py's _compute_gl_rows() output --
        already filtered for implausible moves and circuit locks.

        Returns {"rows": [...], "thin": [...], "scanned": n}.
        """
        self._imbalance = None
        # Cleared every rebuild. Cached for the DURATION of one ranking
        # pass so the 973-symbol loop below does one query instead of
        # 973 -- the same mistake build_corporate_actions() made, found
        # when a refresh started taking seconds.
        self._events_cache = None

        try:
            self.ensure_loaded(today)
        except Exception as e:                 # never break the dashboard
            warn(f"[SHORTLIST] Reference load failed, ranking on movement "
                 f"only: {e}")

        ranked, thin = [], []
        for r in rows:
            symbol = r.get("symbol")
            move = r.get("change_pct")
            if symbol is None or move is None:
                continue

            norm = self._normals.get(symbol)
            med_vol, med_turnover, ma50 = norm if norm else (None, None, None)
            ltp = r.get("ltp")

            acts = self._actions.get(symbol, [])
            veto = sorted({a for a, _ in acts if a in VETO_ACTIONS})

            if med_turnover is not None and med_turnover < MIN_TURNOVER:
                if abs(move) >= THIN_ALERT_PCT:
                    thin.append({"symbol": symbol, "change_pct": round(move, 2),
                                 "turnover_cr": round(med_turnover / 1e7, 2)})
                continue

            # EVERY REASON CARRIES ITS OWN WEIGHT, 31 July 2026.
            #
            #     "how many why's support the stock rally > if more
            #      supports ; more supports = more chips = clumsy in
            #      table ,. to resolve this u find a solution"
            #
            # The chips used to be a plain list in the order the code
            # happened to build them, so "vol 1.2x" could sit above
            # "ORDER WIN Rs 2,205cr" and the first thing the eye met on
            # a 50-row table was the least important thing known.
            #
            # Pairing each chip with the points it actually contributed
            # answers both halves at once: the list can be sorted
            # strongest-first, and the number of reasons that PUSHED THE
            # SCORE UP is countable rather than guessed from the text.
            # No string matching -- the weight is the same number that
            # moved the score.
            # Each entry is (text, points, reading_order).
            #
            # POINTS is what this reason added to the score, and it is
            # what the backing count is made of. READING_ORDER is how
            # much it is worth SEEING, which is usually the same number
            # but not always:
            #
            #   "up 9.1%"        scores nothing and is already printed
            #                    in the Change% column -- last.
            #   "CROWDED 30x"    scores nothing and is a warning the
            #                    operator must not miss -- high.
            #   "PULSE: Excellent" when the filed numbers already
            #                    scored the same quarter: no points, so
            #                    it is not double counted, but a second
            #                    independent source agreeing is one of
            #                    the more useful things on the row.
            #
            # Keeping them as one number is what buried the Pulse chip
            # behind the price move on the first attempt.
            why = []                       # [(text, points, order)]
            score = abs(move) if abs(move) >= MIN_MOVE_PCT else 0.0
            if move >= MIN_MOVE_PCT:
                why.append((f"up {move:.1f}%", 0.0, LAST))
            elif move <= -MIN_MOVE_PCT:
                why.append((f"DOWN {move:.1f}%", 0.0, LAST))

            # --- reason: something was FILED today, and how long ago ---
            # Ranked above the calendar deliberately. "Reports today" is
            # a date; "filed 20 minutes ago" is the thing that is moving
            # the price while the operator is looking at the screen.
            news = self._news_for(symbol)
            if news:
                mins = news.get("minutes_ago")
                when = (f"{mins:.0f}m ago" if isinstance(mins, (int, float))
                        else (news.get("filed_at") or "today"))
                filed_points = 6.0
                # Still fresh enough that the market is probably still
                # digesting it. Beyond an hour it is just "today's news".
                if isinstance(mins, (int, float)) and mins <= 30:
                    filed_points += 2.0
                why.append((f"FILED {news['kind'].replace('_', ' ')} {when}",
                            filed_points, filed_points))
                score += filed_points

            # --- reason: a high-conviction news event ---
            head = self._headline_for(symbol)
            if head:
                points, stance = self._news_points(head)
                # The stance goes in the badge the operator reads. He saw
                # "NEWS BROKER:" beside a sell rating and had to read the
                # headline to find out it was bad news. Now the label
                # says so.
                label = head["kind"].replace("_", " ")
                if stance and stance != "NEUTRAL":
                    label += f" {'+' if stance == 'POSITIVE' else '-'}"
                elif stance:
                    label += " ="
                # A negative news item is sorted by how LOUD it is,
                # not how good. A downgrade must not fall to the bottom
                # of the list because its points are negative.
                why.append((f"NEWS {label}: {head['headline'][:70]}",
                            points, abs(points)))
                score += points

            # --- reason: were the numbers actually BETTER? ---
            # This is the one that separates KFINTECH from ACUTAAS. It
            # goes in whether or not the stock moved, because a STRONG
            # quarter on a flat day is exactly the "early" the operator
            # is looking for.
            fin = self._financials_for(symbol)
            grade = fin.get("grade") if fin else None
            if fin and grade:
                summary = fin.get("summary")
                grade_points = self.GRADE_SCORE.get(grade, 0.0)
                # NAME THE QUARTER. 31 July 2026, and this one nearly
                # cost a trade:
                #
                #   APTUS  [GOOD]  GOOD: PAT +10% QoQ
                #                  FILED RESULTS 591m ago
                #                  REPORTING TODAY
                #                  PULSE: Weak results
                #   ... and the stock closed -5.77%.
                #
                #     "to be frank i could have bought this by seeing
                #      Good & AI - 18% yoy. but weak results from PULSE"
                #
                # The GOOD was real arithmetic -- on the MARCH quarter,
                # comparing Mar-26 against Dec-25, read on 27 July.
                # Today's Jun-26 filing (PAT 261 vs 261, flat, with
                # provisions up 103% YoY) had not been ingested. A
                # three-month-old grade sat beside "REPORTING TODAY"
                # with nothing on it to say which quarter it described.
                #
                # The period was in the data the whole time. It is now
                # on the chip, always -- not only when stale, because a
                # label that appears only when something is wrong is a
                # label nobody learns to read.
                period = str(fin.get("period") or "").strip()
                # ---- SAY WHOSE WORD IT IS. 2 August 2026. ----
                #
                #     "then how bot dashboard shows me? and what are
                #      those chips of STRONG, MIXED, WEAK next to
                #      symbol?"
                #
                # He assumed a channel had said it. Nobody had. This
                # grade is core/quarterly_results.grade() reading filed
                # sales and PAT -- our own arithmetic, in a vocabulary
                # that OVERLAPS the channels' (GOOD and WEAK appear in
                # both) while meaning something different.
                #
                #     "we cannot deviate from NSE & PRO CHANNELS"
                #
                # So it is prefixed, always. Every word on the screen
                # now names its source: OUR NUMBERS, or PULSE, or the
                # publisher by name. The chip beside the symbol is the
                # channel's; this one lives in the collapsed list where
                # it can be read with its label attached.
                label = f"OUR NUMBERS: {grade}"
                label += f" ({period})" if period else ""
                why.append((label + (f" -- {summary}" if summary else ""),
                            grade_points, abs(grade_points) or 3.0))
                score += grade_points

            # --- reason: who was still trying to get in at the open ---
            # Direction-aware on purpose. Buyers left unmatched support a
            # riser and CONTRADICT a faller: a stock down 5% with a queue
            # of unfilled buy orders behind it is a different animal from
            # one falling with sellers still queued.
            imbalance = self._imbalance_for(symbol)
            if imbalance is not None and abs(imbalance) >= self.IMBALANCE_MIN:
                buyers = imbalance > 0
                agrees = (buyers and move > 0) or (not buyers and move < 0)
                side = "BUYERS" if buyers else "SELLERS"
                imb_points = (self.IMBALANCE_SCORE if agrees
                              else -self.IMBALANCE_SCORE)
                why.append((f"pre-open {side} still waiting"
                            + ("" if agrees else " -- against the move"),
                            imb_points, abs(imb_points)))
                score += imb_points

            # --- reason: what the channels reported, typed ---
            # RESULT here is Earnings Pulse's instant verdict; ORDER is a
            # contract win with its value. Both land hours before the
            # filed numbers that GRADE_SCORE above works from.
            seen_kinds = set()
            # The first channel verdict of the day, kept so a SECOND
            # one can be compared against it. See the CDSL note below.
            first_pulse = None
            # ---- CAPTURED SEPARATELY FROM first_pulse, ON PURPOSE ----
            #
            # 2 August 2026, caught by measuring before shipping. The
            # obvious way to write this was `first_pulse[0]`, and it
            # would have blanked the chip on 69 real cards.
            #
            # first_pulse is only set when PULSE_SCORE knows the word.
            # Counted on the 755 RESULT events in the live window:
            #
            #     GOOD 289   WEAK 197   OK 123   MIXED 69
            #     EXCELLENT 63   GREAT 14
            #
            # MIXED is a genuine publisher word -- Earnings 360's
            # "WATCH: growth Falling" and Earnings Pro's "BEAT Revenue
            # | MISS PAT" both land on it -- and it is deliberately
            # absent from PULSE_SCORE because it scores nothing.
            # Scoring nothing is not the same as saying nothing.
            channel_grade = None
            channel_from = None
            # Held so core/chain.py can read the same events the chips
            # were built from -- one pass, one truth. Fetching them a
            # second time would let the summary and the chips disagree
            # about the same stock, which is the one thing a summary
            # must never do.
            events_for_symbol = list(self._events_for(symbol))
            for event in events_for_symbol:
                kind = event.get("kind")

                # ---- THE MODEL SAID THIS IS NOT ABOUT THIS COMPANY --
                #
                # 31 July 2026. The keyword matcher produced these, and
                # they were printed on screen as REASONS:
                #
                #   URBANCO     "Afcons secures Rs 900 crore..."
                #   POWERGRID   "Vikran wins a subcontract FROM PowerGrid"
                #   SBC         "Texmaco Rail wins an order"
                #   NMDC   x3   "GMDC reports Q1 results"
                #
                # 22 of 142 events were wrong pairings. POWERGRID is
                # the CUSTOMER -- the panel was crediting the buyer
                # with winning its own order.
                #
                # This is the first thing the model does that the
                # cheap filters could not, and note the DIRECTION of
                # it: it REMOVES a wrong chip rather than adding a new
                # one. Dropped before anything else looks at the
                # event, so it cannot score, cannot be counted as
                # support, and cannot be read.
                if str(event.get("ai_direction") or "").upper() == "UNRELATED":
                    continue

                verdict = self._ai_chip(event)
                if verdict:
                    why.append(verdict)
                # ---- A PARSED FACT MUST NOT NEED THE AI TO BE SEEN ----
                # 1 August 2026. Measured on the store: 808 news events
                # carry a symbol, 715 reach the panel through an AI
                # verdict -- and 15 carry a fact one of OUR OWN parsers
                # found and reach nothing at all:
                #
                #     DIVISLAB    CLEAN | Rising, Expanding, Healthy
                #     SEJALLTD    WATCH: margins Compressing
                #     LGBBROSLTD  CLEAN | Rising, Expanding, Healthy
                #
                # Those are earnings briefs with no grade pill, so they
                # stay kind=NEWS, and the RESULT branch below never sees
                # them. The AI is the only route a NEWS event has to the
                # panel, and it is not the only thing that read the card.
                #
                # Scored ZERO. It is the card describing itself, not a
                # second source agreeing -- the same rule the fact chip
                # on a RESULT follows.
                # CONCALL excluded with the others: its headline is
                # already the parsed reading ("CONCALL POSITIVE/
                # CONFIDENT: growth rising, margins expanding"), so
                # running _lead_fact over it would print half of it
                # twice on the same row.
                if kind not in ("RESULT", "ORDER", "EXPECTATION",
                                "CONCALL", "MARKET_ANSWER", "REPORTED",
                                "SETUP", "AI_VERDICT"):
                    fact = _lead_fact(event.get("headline"))
                    if fact:
                        why.append((fact, 0.0, CAUTION_HIGH))
                if kind == "RESULT" and "RESULT" not in seen_kinds:
                    pulse = (event.get("grade") or "").upper()
                    # The chip beside the symbol. Taken here, ABOVE the
                    # PULSE_SCORE lookup, so an unscored-but-real word
                    # still reaches the panel. Events arrive newest
                    # first, so the first one wins.
                    if pulse and channel_grade is None:
                        channel_grade = pulse
                        channel_from = _source_name(event.get("source"))
                    points = self.PULSE_SCORE.get(pulse)
                    if points is not None:
                        # SHOW BOTH, SCORE ONCE -- 31 July 2026.
                        #
                        #     "for some stocks chip is showing these &
                        #      for some PULSE: Excellent results ;
                        #      instead keep both chips"
                        #
                        # The chip used to be hidden whenever the filed
                        # numbers had already graded the stock, so the
                        # panel silently showed one of two different
                        # things depending on which source had arrived
                        # -- and the operator could not tell whether the
                        # other one was absent or merely suppressed.
                        #
                        # They are different evidence and BOTH are worth
                        # seeing: the channel's instant verdict and our
                        # own arithmetic off the filing. Two independent
                        # sources agreeing is the strongest thing this
                        # panel can say.
                        #
                        # The DOUBLE COUNT is what had to be prevented,
                        # and that is about the SCORE, not the chip. So
                        # the chip is always added; the points are added
                        # only when the arithmetic has not already
                        # scored the same quarter. A zero-weight chip
                        # still shows -- it just does not count twice
                        # toward the support tally either.
                        # ---- ONLY A GRADE OF THE *SAME* RESULT COUNTS
                        #      AS ALREADY SCORED. 31 July 2026. ----
                        #
                        # This used to be `bool(fin and grade)` -- "we
                        # have our own grade, so do not count the
                        # channel's too". Sound, and wrong whenever the
                        # two are about DIFFERENT QUARTERS.
                        #
                        # APTUS: our store held Mar-26 (read 27 July).
                        # Earnings Pulse posted WEAK on the Jun-26
                        # filing at 07:52 today. The stale GOOD scored
                        # +3.0 AND silenced the fresh WEAK's -2.5 -- a
                        # 5.5 point swing the wrong way on a stock that
                        # closed down 5.77%.
                        #
                        # A verdict on today's result cannot be
                        # "already counted" by arithmetic that has
                        # never seen today's result.
                        already = bool(fin and grade) and not self._is_stale(
                            fin, event.get("at"))
                        pulse_points = 0.0 if already else points

                        # ---- WHEN THE TWO SOURCES POINT OPPOSITE WAYS
                        #
                        # APTUS, 31 July 2026, after the filing was
                        # finally read correctly:
                        #
                        #   ours   STRONG: sales +15% YoY, PAT +19% YoY
                        #   pulse  Weak results
                        #   market -5.77%
                        #
                        # Both were honest. Ours grades sales and PAT.
                        # The market cared about provisions +103% YoY
                        # and GNPA 1.42% against 1.29% -- asset quality,
                        # which for a lender IS the result and which
                        # core/quarterly_results.py cannot see at all.
                        #
                        # Two sources disagreeing is not noise to be
                        # averaged. It is the single most informative
                        # thing on the row, and shown as two calm chips
                        # it reads as one mild positive and one mild
                        # negative. It has to be louder than either.
                        #
                        # Scored at zero deliberately: the disagreement
                        # says LOOK, not BUY or SELL. Which of the two
                        # is right is exactly what nobody has measured
                        # yet -- that is what outcome tracking is for.
                        # ---- WHAT THE MARKET DID WITH IT ----
                        #
                        #     "some stocks earnings with lower business
                        #      or negative reading also considered as
                        #      positive & stock moves as results were
                        #      not as bad as expected... market prices
                        #      the future right"
                        #
                        # Measured on the 151 graded results held on 1
                        # August 2026:
                        #
                        #     CONFIRMS      57   38%
                        #     NO REACTION   62   41%
                        #     LESS BAD      16   11%
                        #     PRICED IN     16   11%
                        #
                        # One in five times the grade pointed the WRONG
                        # WAY -- UEL weak and +7.3%, DHANBANK great and
                        # -6.3%. A grade on its own is right about
                        # direction less than four times in ten.
                        #
                        # Scored at ZERO, like the other disagreements.
                        # Which side is right is what outcome tracking
                        # will measure; asserting it now would be
                        # inventing an answer.
                        answer = self._market_answer(symbol,
                                                     event.get("at"), pulse)
                        if answer:
                            why.append((answer, 0.0, MARKET_ANSWER))

                        if grade and pulse:
                            ours = self.GRADE_SCORE.get(grade, 0.0)
                            theirs = self.PULSE_SCORE.get(pulse, 0.0)
                            if ours * theirs < 0:
                                why.append((
                                    f"CONFLICT: our numbers say "
                                    f"{grade.title()}, the channel says "
                                    f"{pulse.title()}", 0.0, CONFLICT))
                        why.append((f"PULSE: {pulse.title()} results"
                                    + _age_suffix(event.get("at"), today),
                                    pulse_points,
                                    abs(points) or ECHO))
                        # THE FACT, NOT ONLY THE LABEL. "PULSE: Weak
                        # results" is a verdict the operator cannot
                        # check. "ONE-OFF: Dividend income from
                        # subsidiary: Rs 39.5 Cr" is a number he can
                        # subtract from the printed profit himself.
                        # Scored at zero -- the grade above already
                        # carries the weight, and this is the same
                        # card explaining itself, not a second source.
                        fact = _lead_fact(event.get("headline"))
                        if fact:
                            why.append((fact, 0.0, CAUTION_HIGH))
                        score += pulse_points
                        seen_kinds.add("RESULT")
                        first_pulse = (pulse, event.get("source") or "",
                                       str(event.get("at") or "")[:10])
                elif (kind == "RESULT" and first_pulse
                      and "RESULT_CONFLICT" not in seen_kinds):
                    # ONCE, NOT PER ROW. 1 August 2026: GILLETTE showed
                    #
                    #   CONFLICT: Pro says Good, Pulse says Weak
                    #   CONFLICT: Pro says Good, Pulse says Weak
                    #
                    # because the store holds more than one RESULT row
                    # per source, and this branch fired for each of
                    # them. The marker below was being SET and never
                    # read. Saying it twice does not make it truer; it
                    # takes a line the operator has to read at 09:10.
                    # ---- TWO CARDS, SAME COMPANY, OPPOSITE VERDICTS ----
                    #
                    #     "as a human we cannot grasp all image data &
                    #      trade decision right?"
                    #                   -- operator, 1 August 2026
                    #
                    # CDSL Q1 FY27, 1 August 2026, 12:44. Two cards from
                    # the same publisher, minutes apart:
                    #
                    #     EARNINGS BRIEF   GREAT
                    #     FinAI grid       Pulse Rating: Weak
                    #
                    # The panel showed "PULSE: Weak results" and nothing
                    # else. The second card was stored, counted in the
                    # support tally, and never shown -- so the row read
                    # as a settled negative when the publisher itself
                    # had not settled it.
                    #
                    # The CONFLICT chip above only compares OUR
                    # arithmetic against a channel. It had no way to
                    # see two channels contradicting each other.
                    #
                    # BOUNDED TO THE SAME CALENDAR DAY, deliberately. A
                    # Weak card on Mar-26 and a Great card on Jun-26
                    # three days apart are not a disagreement -- they
                    # are two quarters, and calling that a conflict
                    # would put the chip on half the panel.
                    #
                    # Scored at zero, like every other disagreement.
                    # Which card is right is what outcome tracking will
                    # measure; asserting it now would be inventing an
                    # answer.
                    pulse = (event.get("grade") or "").upper()
                    theirs = self.PULSE_SCORE.get(pulse)
                    ours = self.PULSE_SCORE.get(first_pulse[0])
                    same_day = str(event.get("at") or "")[:10] == first_pulse[2]
                    if (theirs is not None and ours is not None
                            and ours * theirs < 0 and same_day):
                        here = _source_name(event.get("source"))
                        there = _source_name(first_pulse[1])
                        label = (f"{there} says {first_pulse[0].title()}, "
                                 f"{here} says {pulse.title()}"
                                 if here != there else
                                 f"same source graded this "
                                 f"{first_pulse[0].title()} AND "
                                 f"{pulse.title()}")
                        why.append((f"CONFLICT: {label}", 0.0, CONFLICT))
                        seen_kinds.add("RESULT_CONFLICT")
                        # A conflict tells the operator to look. This
                        # tells him what to look AT -- and on CDSL it
                        # is the whole explanation of why one card
                        # said Great and the other said Weak.
                        fact = _lead_fact(event.get("headline"))
                        if fact:
                            why.append((fact, 0.0, CAUTION_HIGH))
                elif kind == "EXPECTATION" and "EXPECTATION" not in seen_kinds:
                    # ---- THE HURDLE, BEFORE THE RESULT ----
                    #
                    #     "None of it knows what the market already
                    #      expected? we have covered by one of our pro
                    #      channel right? every thing in one page"
                    #
                    # Earnings Pro publishes a stance per stock before
                    # the numbers land -- BULLISH, NEUTRAL or BEARISH,
                    # with the reasoning and often the consensus
                    # figure. It is the bar the quarter has to clear,
                    # and without it a weak result and a weak result
                    # everybody already feared look identical.
                    #
                    # Shown, not scored. An expectation is context for
                    # reading the result, not evidence about the
                    # stock -- and a BULLISH expectation that then
                    # MISSES is a sell, so scoring it positive would
                    # have the sign backwards half the time.
                    why.append((event.get("headline") or "", 0.0,
                                EXPECTATION))
                    seen_kinds.add("EXPECTATION")
                elif (kind == "AI_VERDICT"
                      and "AI_VERDICT" not in seen_kinds):
                    # Layer 04. The audit that read the filing, the
                    # presentation and the concall, and said whether
                    # the algorithm's grade was right. It disagrees one
                    # time in four -- see core/ai_verdict.py.
                    #
                    # Placed at MARKET_ANSWER's weight and scored ZERO,
                    # like every other read in the chain. It is a
                    # verdict on a GRADE, not evidence about a price.
                    why.append((event.get("headline") or "", 0.0,
                                MARKET_ANSWER))
                    seen_kinds.add("AI_VERDICT")
                elif kind == "SETUP" and "SETUP" not in seen_kinds:
                    # ---- LAYER 06, 2 August 2026 ----
                    #
                    #   "Have you forgot SEBI mandates about no stock
                    #    buy / sell recommendations? no one gives that
                    #    signals. these channels provide data with
                    #    vedict."
                    #
                    # CANSLIM (TechnoFunda) is the last of the six
                    # reads in Earnings Pulse's own chain, and the only
                    # one that carries the CHART. It disagreed with the
                    # Pulse grade on twelve of thirteen names the day
                    # it arrived -- SHADOWFAX, AETHER and DIVISLAB all
                    # EXCEPTIONAL on a quarter graded GOOD.
                    #
                    # Placed at MARKET_ANSWER's weight: a tier that
                    # contradicts the grade is worth as much as a tape
                    # that contradicts it, and for the same reason.
                    #
                    # SCORED ZERO. It is a tier, not an instruction --
                    # their own page says "we don't tell you whether to
                    # buy, hold, or skip a name", and neither does this
                    # panel. Nobody has measured whether EXCEPTIONAL
                    # outperforms either; core/outcomes.py can answer
                    # that once a month of tiers is stored.
                    why.append((event.get("headline") or "", 0.0,
                                MARKET_ANSWER))
                    seen_kinds.add("SETUP")
                elif kind == "REPORTED" and "REPORTED" not in seen_kinds:
                    # ---- NOT YET PRICED, 1 August 2026 ----
                    #
                    #   "sorted list of results which will get impacted
                    #    on monday market"
                    #
                    # A result released after 15:30 has not been
                    # answered by the tape -- the market was shut. It
                    # is the only chip on the row that describes
                    # something that has NOT happened yet, which is
                    # exactly the position he asked to be in:
                    #
                    #   "before the movement i need to trust as early
                    #    bird not in a over crowded place after rally
                    #    done"
                    #
                    # Scored ZERO all the same. "Reported after the
                    # close" says the market has not judged it -- not
                    # that the numbers were good. The grade is a
                    # different chip and it is already on the row.
                    why.append((event.get("headline") or "", 0.0,
                                MARKET_ANSWER))
                    seen_kinds.add("REPORTED")
                elif (kind == "MARKET_ANSWER"
                      and "MARKET_ANSWER" not in seen_kinds):
                    # ---- WHAT THE TAPE SAID BACK, 1 August 2026 ----
                    #
                    # 52 pages, 258 stock rows, 3 events. Every row
                    # carried the publisher's grade, the sentiment and
                    # a sentence with the actual price move, and the
                    # three-company rule was eating the lot.
                    #
                    # Scored ZERO, and this one is not caution -- it is
                    # arithmetic. The move is YESTERDAY's, already in
                    # the price. Scoring it would reward a stock for
                    # having moved, which is the "bought near the upper
                    # circuit" mistake the operator named himself.
                    #
                    # It earns MARKET_ANSWER's weight in the reading
                    # order because a grade the tape contradicted is
                    # the second most useful line on a row -- the same
                    # place ALREADY PRICED sits, for the same reason.
                    why.append((event.get("headline") or "", 0.0,
                                MARKET_ANSWER))
                    seen_kinds.add("MARKET_ANSWER")
                elif kind == "CONCALL" and "CONCALL" not in seen_kinds:
                    # ---- WHAT MANAGEMENT SAID, 1 August 2026 ----
                    #
                    #   "conviction on business + confidence on
                    #    management"
                    #
                    # Earnings 360 publishes a concall card carrying
                    # the tone management struck, the direction they
                    # guided on growth and margins, and the things
                    # their LANGUAGE gave away -- "hedged FY28 capex on
                    # Solapur success". 79 arrived and every one was
                    # filed as plain news with the card cut off
                    # mid-word.
                    #
                    # SHOWN, NOT SCORED, and for a harder reason than
                    # the expectation above. A result is arithmetic. A
                    # concall is a person choosing words, and nothing
                    # here has ever measured whether a confident tone
                    # is worth paying for. core/outcomes.py will answer
                    # it once there are samples; scoring it now would
                    # be inventing an edge, which is the thing this
                    # project keeps catching itself doing.
                    why.append((event.get("headline") or "", 0.0,
                                EXPECTATION))
                    seen_kinds.add("CONCALL")
                elif kind == "ORDER" and "ORDER" not in seen_kinds:
                    value = event.get("value_cr")
                    who = event.get("counterparty")
                    label = "ORDER WIN"
                    if value:
                        label += f" Rs {value:,.0f}cr"
                    if who:
                        label += f" from {who}"
                    order_points = self._order_score(value)
                    label += _age_suffix(event.get("at"), today)
                    why.append((label, order_points, order_points))
                    score += order_points
                    seen_kinds.add("ORDER")

            for days, _purpose in sorted(self._results.get(symbol, [])):
                cal_points = 4.0 if days <= 0 else 2.0
                if days == 0:
                    why.append(("REPORTING TODAY", cal_points, cal_points))
                elif days < 0:
                    why.append((f"results out {abs(days)}d ago",
                                cal_points, cal_points))
                else:
                    why.append((f"results due in {days}d",
                                cal_points, cal_points))
                score += cal_points

            for a, ex in acts:
                if a not in VETO_ACTIONS:
                    why.append((f"{a.lower()} ex-{ex}", 1.0, 1.0))
                    score += 1.0

            if ma50 and ltp:
                if ltp > ma50:
                    score += 1.0
                else:
                    # A caution, not a reason. Zero weight so it never
                    # counts as something SUPPORTING the move.
                    why.append(("below 50d avg", 0.0, CAUTION_LOW))

            vratio = None
            if med_vol and r.get("volume"):
                vratio = r["volume"] / med_vol
                if vratio <= QUIET_MAX:
                    why.append((f"quiet {vratio:.1f}x -- may not be noticed "
                                f"yet", 0.0, CAUTION))
                elif vratio >= LOUD_MIN:
                    # A warning scores nothing and must still be seen.
                    why.append((f"CROWDED {vratio:.0f}x -- likely already "
                                f"priced", 0.0, CAUTION_HIGH))
                else:
                    why.append((f"vol {vratio:.1f}x", 0.0, CAUTION_LOW))

            if score < MIN_SCORE:
                continue

            # STRONGEST FIRST, and count what actually supports the move.
            #
            # A stable sort, so two chips of equal weight keep the order
            # the code built them in -- otherwise the panel would
            # reshuffle between refreshes for no visible reason, which on
            # a table the operator is clicking BUY in is its own hazard.
            why.sort(key=lambda row: -row[2])
            support = sum(1 for _, points, _o in why if points > 0)
            against = sum(1 for _, points, _o in why if points < 0)
            why = [text for text, _p, _o in why]

            # ---- THE SIX LAYERS, AS ONE LINE, 2 August 2026 ----
            #
            #   "in live markets i cannot see +10/+8 chips right?
            #    thats your work to make sure the code does the
            #    backgorund & show the final output to end user with
            #    clear case"
            #
            # He is right, and it is the argument against everything
            # built this weekend if it goes unanswered. Ten chips on a
            # fifty-row table at 09:15 is a screen nobody reads.
            #
            # So the chain is assembled here and handed to the panel as
            # ONE bright line. The chips are untouched -- they collapse
            # behind it. Nothing is thrown away, which is the standing
            # rule; it is just no longer all shouting at once.
            #
            # Reports STATE, never an instruction. See core/chain.py.
            chain_facts = chain_read(events_for_symbol,
                                     vol_ratio=vratio, change_pct=move)
            chain_line = chain_summary(events_for_symbol)

            # ---- THE CHIP BESIDE THE SYMBOL IS THEIRS, NOT OURS ----
            #
            # 2 August 2026. The panel printed STRONG / GOOD / MIXED /
            # WEAK next to the symbol and the operator read it as a
            # channel verdict. It was not. It was GRADE_SCORE's own
            # arithmetic off the filing, in four words, two of which
            # collide with the channels' six:
            #
            #     Earnings Pulse   EXCELLENT GREAT GOOD OK WEAK POOR
            #     ours             STRONG    GOOD  MIXED   WEAK
            #
            # On CONCORDBIO the channel said GOOD and our chip said
            # MIXED, side by side, with nothing to say which was whose.
            # core/quarterly_results.grade()'s own docstring reads "NOT
            # VALIDATED AGAINST PRICE".
            #
            #     "pls make sure to follow the pro channel way in
            #      building our own chips. we cannot deviate from NSE
            #      & PRO CHANNELS"
            #
            # So the chip is now the PUBLISHER'S word, taken from the
            # newest RESULT event -- the same verdict the PULSE chip
            # carries, raised to where the eye lands first. Our own
            # grade is not promoted to a substitute when the channel is
            # silent: an empty cell says "no channel has graded this",
            # which is a fact, and filling it with our arithmetic under
            # their name is the mismatch he told us never to make.
            #
            # channel_grade is taken from the FIRST RESULT event seen,
            # and _events_for() sorts newest first, so it is the latest
            # verdict and it is inside the 96-hour window by
            # construction -- unlike `grade`, which sat three months
            # stale on APTUS beside the words "REPORTING TODAY".
            #
            # MEASURED BEFORE SHIPPING, on the live store: of the 218
            # symbols a channel had graded in the window, 182 also had
            # our own grade, and the two words DIFFERED on 144 of them
            # -- APLAPOLLO ours STRONG / theirs WEAK, AJANTPHARM ours
            # GOOD / theirs EXCELLENT. Four rows in five were showing
            # him a word no channel had said.

            ranked.append({
                "symbol": symbol,
                "sector": r.get("sector"),
                "ltp": ltp,
                "change_pct": round(move, 2),
                "score": round(score, 1),
                # The one line, its state for the colour, and a sort
                # key that orders equals without inventing points.
                "chain": chain_line,
                # STEADY, not instantaneous. See core/chain.SteadyCall:
                # this was recomputed on every one-second refresh and
                # flickered BUY / AVOID / WAIT while he was deciding
                # whether to hold YASHO. The raw call is still what
                # decides; it just has to mean it for twenty seconds
                # before it rewrites what is on his screen.
                "chain_state": self._steady_call(symbol, chain_facts),
                "chain_why": chain_reason(chain_facts),
                "chain_rank": chain_rank(chain_facts),
                "chain_layers": chain_facts.get("layers", 0),
                "vol_ratio": round(vratio, 1) if vratio is not None else None,
                "veto": veto,
                # The publisher's verdict -- what the panel draws.
                "channel_grade": channel_grade,
                "channel_grade_from": channel_from,
                # Ours. Kept on the row because tools/outcome_report.py
                # and the drill-down card both read it, and because
                # comparing the two is the point of storing both. It is
                # no longer drawn beside the symbol.
                "grade": grade,
                "news": head,
                "financials": ({"period": fin.get("period"),
                                "qoq": fin.get("qoq"),
                                "yoy": fin.get("yoy")} if fin else None),
                "why": why,
                # How many independent things pushed this up, and how
                # many pushed back. The table shows the count and the
                # strongest few; the rest are one click away.
                "support": support,
                "against": against,
            })

        ranked.sort(key=lambda x: -x["score"])
        ranked = ranked[:top]
        for rank, row in enumerate(ranked, start=1):
            row["s_no"] = rank
        thin.sort(key=lambda x: -abs(x["change_pct"]))

        return {
            "rows": ranked,
            "thin": thin[:10],
            "scanned": len(rows),
            "built_at": datetime.now().strftime("%H:%M:%S"),
        }
