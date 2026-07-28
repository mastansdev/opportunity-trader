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
import sqlite3
import statistics
import threading
from datetime import datetime, timedelta

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

MIN_MOVE_PCT = 2.0     # below this, nothing happened
MIN_SCORE = 2.0        # below this, not worth a line


# Reference data is the same for every builder on a given day, and
# loading it means reading a 151 MB daily store. Sharing it across
# instances is not a micro-optimisation: the dashboard's own tests
# construct 45 DashboardStates and went from instant to 22 seconds,
# which is 45 identical reads of the same file. In the live bot there is
# only one builder, so this changes nothing there -- but a suite nobody
# wants to run is a suite that stops being run.
_REFERENCE_LOCK = threading.Lock()
_REFERENCE_CACHE = {}          # (daily_db, results_db, memory_db, date) -> tuple


class ShortlistBuilder:
    """Reference data is loaded once per trading day and cached; ranking
    itself is pure arithmetic over rows the dashboard already computed.

    Every read is fail-OPEN. A missing database means the shortlist
    degrades to "ranked by movement", which is still better than what
    momentum_universe gave. It must never take the dashboard down.
    """

    def __init__(self, daily_db=DAILY_DB, results_db=RESULTS_DB,
                 memory_db=MEMORY_DB, announcement_watcher=None,
                 quarterly_results=None, news_watcher=None):
        self.daily_db = daily_db
        self.results_db = results_db
        self.memory_db = memory_db
        # core/announcement_watcher.py, wired 2026-07-27. The calendar
        # says a company reports TODAY; this says it filed 20 MINUTES
        # AGO. TMB's move began after 13:00 and 98% of its volume came
        # with it -- a calendar entry could never have told the operator
        # to look right then.
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
    NEWS_SCORE = {"DISASTER": -6.0, "REGULATORY": -5.0, "LEGAL": -4.0,
                  "ORDER_WIN": 5.0, "BROKER": 4.0, "DEAL": 4.0,
                  "GUIDANCE": 3.0, "FUND_RAISE": 1.0, "MANAGEMENT": -2.0}

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

            why = []
            score = abs(move) if abs(move) >= MIN_MOVE_PCT else 0.0
            if move >= MIN_MOVE_PCT:
                why.append(f"up {move:.1f}%")
            elif move <= -MIN_MOVE_PCT:
                why.append(f"DOWN {move:.1f}%")

            # --- reason: something was FILED today, and how long ago ---
            # Ranked above the calendar deliberately. "Reports today" is
            # a date; "filed 20 minutes ago" is the thing that is moving
            # the price while the operator is looking at the screen.
            news = self._news_for(symbol)
            if news:
                mins = news.get("minutes_ago")
                when = (f"{mins:.0f}m ago" if isinstance(mins, (int, float))
                        else (news.get("filed_at") or "today"))
                why.append(f"FILED {news['kind'].replace('_', ' ')} {when}")
                score += 6.0
                # Still fresh enough that the market is probably still
                # digesting it. Beyond an hour it is just "today's news".
                if isinstance(mins, (int, float)) and mins <= 30:
                    score += 2.0

            # --- reason: a high-conviction news event ---
            head = self._headline_for(symbol)
            if head:
                why.append(f"NEWS {head['kind'].replace('_', ' ')}: "
                           f"{head['headline'][:70]}")
                score += self.NEWS_SCORE.get(head["kind"], 0.0)

            # --- reason: were the numbers actually BETTER? ---
            # This is the one that separates KFINTECH from ACUTAAS. It
            # goes in whether or not the stock moved, because a STRONG
            # quarter on a flat day is exactly the "early" the operator
            # is looking for.
            fin = self._financials_for(symbol)
            grade = fin.get("grade") if fin else None
            if fin and grade:
                summary = fin.get("summary")
                why.append(f"{grade}" + (f": {summary}" if summary else ""))
                score += self.GRADE_SCORE.get(grade, 0.0)

            for days, _purpose in sorted(self._results.get(symbol, [])):
                if days == 0:
                    why.append("REPORTING TODAY")
                elif days < 0:
                    why.append(f"results out {abs(days)}d ago")
                else:
                    why.append(f"results due in {days}d")
                score += 4.0 if days <= 0 else 2.0

            for a, ex in acts:
                if a not in VETO_ACTIONS:
                    why.append(f"{a.lower()} ex-{ex}")
                    score += 1.0

            if ma50 and ltp:
                if ltp > ma50:
                    score += 1.0
                else:
                    why.append("below 50d avg")

            vratio = None
            if med_vol and r.get("volume"):
                vratio = r["volume"] / med_vol
                if vratio <= QUIET_MAX:
                    why.append(f"quiet {vratio:.1f}x -- may not be noticed yet")
                elif vratio >= LOUD_MIN:
                    why.append(f"CROWDED {vratio:.0f}x -- likely already priced")
                else:
                    why.append(f"vol {vratio:.1f}x")

            if score < MIN_SCORE:
                continue

            ranked.append({
                "symbol": symbol,
                "sector": r.get("sector"),
                "ltp": ltp,
                "change_pct": round(move, 2),
                "score": round(score, 1),
                "vol_ratio": round(vratio, 1) if vratio is not None else None,
                "veto": veto,
                "grade": grade,
                "news": head,
                "financials": ({"period": fin.get("period"),
                                "qoq": fin.get("qoq"),
                                "yoy": fin.get("yoy")} if fin else None),
                "why": why,
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
