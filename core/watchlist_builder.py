"""
==========================================================
The watchlist builds itself, in the order he reads it
==========================================================

    "i need the bot to think like me. it must check for the stocks &
     add them to watchlist not me manual adding. why can't bot do
     that? it needs to maintain the watchlist with the stocks with
     excellent , Great grades first ; next row belongs to stocks which
     are having results during day & next stocks which are moving
     intraday . all stocks must be see & enter into trade. not random
     orb stocks like it did today."
                                -- operator, 6 August 2026

WHAT THIS IS
------------
Three rows, in his order, rebuilt on every refresh from sources the
bot already holds. He types nothing.

    ROW 1  GRADED        Excellent or Great result, published by the
                         PRO channels in the last 36 hours. These are
                         known-good results and they come FIRST
                         because the grade already did the work.

    ROW 2  REPORTING     Filing today, from the NSE results calendar.
                         Watch, do not buy -- the print is unknown and
                         he holds overnight on MTF.

    ROW 3  MOVING        Up on real volume right now, whether or not
                         anyone has explained it yet. MAZDOCK moved the
                         defence sector on 6 August with no channel
                         sentence the bot could read.

WHY THE ORDER IS THE POINT
--------------------------
On 6 August the bot filled eight positions off structural breakouts --
EXIDEIND, JAMNAAUTO, BASF, JKLAKSHMI, RHIM, BELRISE, VGUARD, GMDCLTD
-- none of which had a grade, a reason, or a place on any list he
would have written himself. It bought whatever crossed a line first.

A graded Excellent result is not the same kind of object as a stock
that happens to be up 2%, and putting them in one undifferentiated
pool is how the second one gets bought while the first is ignored. So
the rows are kept apart, and the row a stock sits in is recorded on
the row itself.

WHAT IT DOES NOT DO
-------------------
It does not rank within a row -- core/ranker.py does that, and it
scores on the tape. It does not size, stop, or order. It answers one
question: what should be on the screen, and in what order.

A symbol appears ONCE, in the highest row it qualifies for. A stock
with an Excellent result that is also moving is a GRADED stock; saying
so twice would double its apparent weight.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
from datetime import datetime, timedelta

GRADED = "GRADED"
REPORTING = "REPORTING"
MOVING = "MOVING"

ROW_TITLES = {
    GRADED: "Excellent / Great results",
    REPORTING: "Reporting today -- watch, do not buy into the print",
    MOVING: "Moving now on real volume",
}

# ==========================================================
# ROW 1 = EXCELLENT, GREAT, GOOD.  8 August 2026.
# ==========================================================
#
#     "the grades are indicators of the stocks quarterly performance .
#      stock movement will be rewarded on future parameters + past
#      results + announcements / acquisitions,
#      my idea of row-1 = >  @ results time = EXCELLENT, GREAT, GOOD &
#      we have other parameters too like volumes and all."
#
# GOOD was excluded because I read his original rule as a ranking and
# kept the top two. It was never a ranking. It is the list of grades
# that make a stock ELIGIBLE to be looked at, and the looking is done
# by everything else -- volume against its own normal, the move still
# extending, headroom to the circuit, supply events, the run-up before
# the print.
#
# The grade says how the quarter went. It does not say what the stock
# will do, and the measurement agreed: across 2,088 graded events
# EXCELLENT was the WORST next-day bucket.
#
# What it cost, once, that we can point at:
#
#     SHILPAMED   graded GOOD five times, 5 August
#                 kept out of Row 1, so unbuyable
#                 best trade of the 6 August replay, +Rs 2,972,
#                 a clean target hit
#
#     GESHIP      EXCELLENT, in Row 1, -Rs 1,475
#     STOVEKRAFT  GREAT,     in Row 1, -Rs 1,476
#
# The two grades that were admitted lost. The one that was filtered
# out won. Widening the gate does not make GOOD a buy signal -- it
# stops the bot refusing to LOOK at a stock whose quarter was fine.
TOP_GRADES = ("EXCELLENT", "GREAT", "GOOD")

# Row 3's bar. The SAME objects core/ranker.py uses -- imported, not
# copied, so the watchlist can never show a stock the ranker will then
# refuse for a bar the watchlist could have applied itself. It used to
# be a copy, and the copy said 1.5 while the ranker said 1.2.
from core.rules import (
    MIN_MOVE_FROM_PREV_CLOSE_PCT as MIN_MOVE_PCT,
    MIN_VOLUME_RATIO,
)

RESULTS_DB = "data/results_calendar.db"


def _upper(value):
    return str(value or "").strip().upper()


# ---------------------------------------------------------------
# ROW 1 -- graded results
# ---------------------------------------------------------------

# ---- ROW 1 GOING EMPTY MUST NOT BE SILENT. 8 August 2026. ----
#
# Three of the handlers below build Row 1 -- the graded results, the
# list his whole morning depends on. Each caught an exception and
# `pass`ed, so a broken gapper card, a broken poster reader or a
# broken recap grid produced an EMPTY Row 1 that looked exactly like
# a morning with no good results.
#
#     "an empty Row 1 is indistinguishable from a morning with no good
#      results, and he would have had no way to tell which"
#
# Once per source per session, then quiet.
_said = set()


def _broke(where, exc):
    if where not in _said:
        _said.add(where)
        try:
            from core.logger import warn
            warn(f"[ROW1] {where} raised and was swallowed: "
                 f"{type(exc).__name__}: {exc}. Row 1 is missing these "
                 f"grades until it is fixed.")
        except Exception:                                  # noqa: BLE001
            pass


def graded_symbols(hours=36, db_path="data/telegram.db", now=None):
    """{symbol: {"grade", "gap_pct", "source"}} for Excellent/Great.

    Two sources, both already parsed elsewhere:

      * the pre-open gapper card, which carries a Quality per symbol
        and the gap it opened with
      * every results poster in the window, read through the
        publisher's own taxonomy in core/pulse_ratings.py

    The gapper card wins where both speak, because it is the one that
    also tells us how the stock actually opened.
    """
    # ---- IT MUST BE ASKABLE ABOUT THE PAST. 8 August 2026. ----
    #
    #     "why no excellent stock were bought?"      -- operator
    #
    # This read datetime.now() and nothing else, so it could only ever
    # answer "what is graded RIGHT NOW". Asked on the 8th about a
    # stock graded on the 6th, it correctly said nothing -- and I read
    # that as "the watchlist is empty of his real stocks" and told him
    # so. The list was fine. The question could not be asked.
    #
    # Two things break without this. A replay of Tuesday silently uses
    # Friday's grades, which is looking at tomorrow's newspaper. And
    # any claim about what Row 1 held on a past morning is unfalsifiable.
    out, texts = {}, {}
    now = now or datetime.now()
    cutoff = (now - timedelta(hours=hours)).isoformat()
    # Nothing published AFTER the moment being asked about may count.
    ceiling = now.isoformat()

    try:
        from core import gappers
        for symbol, row in (gappers.cards_since(cutoff, db_path) or {}).items():
            if _upper(row.get("quality")) in TOP_GRADES:
                out[symbol] = {"grade": _upper(row.get("quality")),
                               "gap_pct": row.get("gap_pct"),
                               "source": "pre-open gapper card"}
    except Exception as exc:                               # noqa: BLE001
        _broke("pre-open gapper card", exc)

    try:
        from core import pulse_ratings
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "select symbols, ocr_text, text, coalesce(grade, '') "
            "from messages where at >= ? and at <= ? "
            "and symbols is not null and symbols <> ''",
            (cutoff, ceiling)).fetchall()
        con.close()
        # ---- THE GRADE THE COLLECTOR ALREADY READ. 8 August 2026. ----
        #
        #     "why pending not started?"
        #
        # This re-derived every grade from the card text and IGNORED
        # messages.grade, which the collector had already parsed and
        # stored. When the re-parse failed the stock simply vanished:
        #
        #   SHILPAMED  GOOD       stored 5 Aug, 4 separate messages
        #   ENRIN      EXCELLENT  stored 6 Aug, Earnings Pro
        #
        # Both were absent from Row 1 on every day they should have led
        # it, and SHILPAMED went on to be the best trade in the 6 August
        # replay. The evidence was in the store the whole time; the
        # reader threw it away and re-read the picture.
        #
        # The stored grade is used FIRST. read_ratings() still runs for
        # everything it does not cover -- verdict, consensus, the recap
        # grid -- so nothing is lost, only rescued.
        stored = {}
        for symbols, ocr, body, grade in rows:
            for part in str(symbols).split(","):
                symbol = _upper(part)
                if not symbol:
                    continue
                texts.setdefault(symbol, []).extend(
                    [t for t in (ocr, body) if t])
                mark = _upper(grade)
                if mark in TOP_GRADES:
                    stored.setdefault(symbol, mark)
        for symbol, mark in stored.items():
            if symbol not in out:
                out[symbol] = {"grade": mark, "gap_pct": None,
                               "source": "results poster"}
        for symbol, blocks in texts.items():
            if symbol in out:
                continue
            got = pulse_ratings.read_ratings(blocks)
            grade = got.get("pulse")
            # A Weak Pulse with a Beat verdict is NOT a top-row stock,
            # but nor is a Great Pulse with a Miss. Row 1 is for
            # results that are good on the publisher's own headline
            # grade and not contradicted by its verdict.
            if grade in TOP_GRADES and got.get("verdict") != "MISS":
                out[symbol] = {"grade": grade, "gap_pct": None,
                               "source": "results poster"}
    except Exception as exc:                               # noqa: BLE001
        _broke("results posters", exc)

    # ---- THE RECAP GRID FILLS WHAT THE CARDS MISSED. 7 Aug 2026. ----
    #
    #     "(SCI) not showed despite excellent"
    #
    # SCI has no individual poster -- its only mention is the evening
    # recap grid. core/gappers.parse_recap() reads that grid, anchored
    # on the symbols whose grade IS known from their own cards, and
    # refuses any line it cannot anchor unanimously.
    #
    # It runs LAST and never overwrites: a stock's own card always
    # beats a chip in a grid.
    try:
        from core import gappers, pulse_ratings
        con = sqlite3.connect(db_path)
        recap = con.execute(
            "select ocr_text from messages where at >= ? "
            "and ocr_text like '%EARNINGS PULSE RECAP%' "
            "order by at desc limit 1", (cutoff,)).fetchone()
        con.close()
        if recap and recap[0]:
            anchors = {}
            for symbol, blocks in (texts or {}).items():
                grade = pulse_ratings.read_ratings(blocks).get("pulse")
                if grade:
                    anchors[symbol] = grade
            for symbol, grade in (gappers.parse_recap(recap[0],
                                                      anchors) or {}).items():
                if symbol in out:
                    continue
                if grade in TOP_GRADES:
                    out[symbol] = {"grade": grade, "gap_pct": None,
                                   "source": "evening recap grid"}
    except Exception as exc:                               # noqa: BLE001
        _broke("evening recap grid", exc)
    return out


# ---------------------------------------------------------------
# ROW 2 -- reporting today
# ---------------------------------------------------------------
def reporting_on(day=None, db_path=RESULTS_DB):
    """{symbol: purpose} for everything filing on `day`.

    Straight off data/results_calendar.db, which the bot has been
    refreshing all along and never once read at decision time.
    """
    day = day or datetime.now().date().isoformat()
    try:
        con = sqlite3.connect(db_path)
        rows = con.execute(
            "select distinct symbol, purpose from results_events "
            "where results_date = ?", (day,)).fetchall()
        con.close()
    except Exception as exc:                               # noqa: BLE001
        _broke("results calendar (Row 2 is empty)", exc)
        return {}
    return {_upper(s): (p or "Financial Results") for s, p in rows if s}


# ---------------------------------------------------------------
# THE WATCHLIST
# ---------------------------------------------------------------
def build(movers=None, adv_of=None, min_liquidity_cr=8.0, blocked=None,
          held=None, day=None, hours=36, db_path="data/telegram.db",
          min_price=None, price_of=None):
    """Three rows, in his order, deduped, liquidity-filtered.

    `movers` is core/ranker.py's row shape -- {symbol, change_pct,
    volume_ratio or turnover_cr, ltp, ...}. Everything else is read
    from the stores.

    Returns {"rows": [{"key", "title", "symbols": [...]}],
             "of": {symbol: {...why it is here...}},
             "dropped": {symbol: reason}}
    """
    if min_price is None:
        try:
            from config import MIN_TRADABLE_PRICE_RS as min_price
        except Exception:                                  # noqa: BLE001
            min_price = 50.0
    blocked = {_upper(s) for s in (blocked or [])}
    held = {_upper(s) for s in (held or [])}
    seen, of, dropped = set(), {}, {}

    def priced(symbol, price):
        """His floor. "we/bot never trade in those stocks"."""
        if price is None or min_price <= 0:
            return True
        try:
            price = float(price)
        except (TypeError, ValueError):
            return True
        if price < min_price:
            dropped[symbol] = (f"Rs {price:,.2f} -- below your Rs "
                               f"{min_price:,.0f} floor")
            return False
        return True

    def liquid(symbol):
        if adv_of is None:
            return True
        try:
            adv = float(adv_of(symbol) or 0.0)
        except Exception as exc:                           # noqa: BLE001
            # Refusing is right -- an unknown liquidity is not a
            # tradeable one -- but say so, or a broken liquidity store
            # empties the whole watchlist in silence.
            _broke("liquidity lookup (stocks refused as illiquid)", exc)
            return False
        if adv < min_liquidity_cr:
            dropped[symbol] = (f"only Rs {adv:.0f} Cr a day -- too thin "
                               f"for your size")
            return False
        return True

    def admit(symbol, key, detail, price=None):
        symbol = _upper(symbol)
        # ONE ROW PER SYMBOL, the highest it earns. A graded stock that
        # is also moving is a GRADED stock; listing it twice would make
        # it look like two opportunities.
        if not symbol or symbol in seen or symbol in blocked:
            return False
        if symbol in held:
            dropped[symbol] = "already held"
            return False
        if price is None and price_of is not None:
            try:
                price = price_of(symbol)
            except Exception as exc:                       # noqa: BLE001
                _broke("price lookup", exc)
                price = None
        if not priced(symbol, price):
            return False
        if not liquid(symbol):
            return False
        seen.add(symbol)
        of[symbol] = dict(detail, row=key)
        return True

    rows = {GRADED: [], REPORTING: [], MOVING: []}

    # ---- ROW 1 ----
    for symbol, detail in sorted(
            (graded_symbols(hours, db_path) or {}).items(),
            key=lambda kv: (kv[1]["grade"] != "EXCELLENT",
                            -(kv[1].get("gap_pct") or 0))):
        if admit(symbol, GRADED, detail):
            rows[GRADED].append(symbol)

    # ---- ROW 2 ----
    for symbol, purpose in (reporting_on(day) or {}).items():
        # Deliberately admitted even though nothing will buy it: he
        # asked to SEE these, and a stock reporting today that he
        # cannot see is one he might buy by accident.
        if admit(symbol, REPORTING, {"purpose": purpose,
                                     "tradeable": False,
                                     "note": ("result is unknown -- watch "
                                              "it, do not buy into it")}):
            rows[REPORTING].append(symbol)

    # ---- ROW 3 ----
    for row in (movers or []):
        if not isinstance(row, dict):
            continue
        symbol = _upper(row.get("symbol"))
        try:
            move = float(row.get("change_pct") or 0.0)
        except (TypeError, ValueError):
            continue
        # ---- LONG ONLY. NOT A PREFERENCE, A PROHIBITION. ----
        #
        #     "shorting stocks is prohibited compleletly . u can safely
        #      avoid/replace them with long stocks opportunites. we
        #      trade only long positions if none . no trade thats it &
        #      simple."                     -- operator, 6 August 2026
        #
        # The first version put OMNI (-17.67%) and SFL (-9.96%) on his
        # screen. Neither can ever become a trade -- core/auto_entry.py
        # refuses anything that is not a long -- so they were pure
        # noise occupying rows a real opportunity could have used.
        #
        # A falling stock is dropped here, at the watchlist, so the
        # slot goes to the next stock that is actually RISING.
        if move < MIN_MOVE_PCT:
            if move <= -MIN_MOVE_PCT:
                dropped.setdefault(symbol, "falling -- we do not short")
            continue
        vratio = row.get("volume_ratio")
        try:
            vratio = float(vratio) if vratio is not None else None
        except (TypeError, ValueError):
            vratio = None
        if vratio is not None and vratio < MIN_VOLUME_RATIO:
            dropped.setdefault(symbol, "moving, but no volume behind it")
            continue
        if admit(symbol, MOVING, {"change_pct": move,
                                  "volume_ratio": vratio},
                 price=row.get("ltp") or row.get("price")):
            rows[MOVING].append(symbol)
    # Biggest riser first. No abs() -- there is nothing negative left
    # in this row to protect against.
    rows[MOVING].sort(key=lambda s: -(of[s].get("change_pct") or 0.0))

    return {
        "rows": [{"key": key, "title": ROW_TITLES[key],
                  "symbols": rows[key]}
                 for key in (GRADED, REPORTING, MOVING)],
        "of": of,
        "dropped": dropped,
    }
