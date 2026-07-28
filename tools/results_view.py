"""
==========================================================
Who reports when, and what their last numbers were
==========================================================

    py tools/results_view.py                # -3 days to +5 days
    py tools/results_view.py --days 10      # further ahead
    py tools/results_view.py --back 7       # further back
    py tools/results_view.py --symbol TMB   # one company's whole history
    py tools/results_view.py --today        # just today, with grades

Operator, 2026-07-28: "how i can know which stocks are having their
results today, which posted last day, before that day, after tomorrow.
are we maintaining list of stocks with their result dates & results data
as i wanted them be stored in memory?"

Both stores existed and were populated -- 4,014 events across 922
symbols in data/results_calendar.db, and 1,347 real quarters across 677
symbols in data/quarterly_results.db. Neither had any way to LOOK at it.
A memory nobody can read is not a memory.

WHAT THE GRADE MEANS, AND WHAT IT DOES NOT
------------------------------------------
STRONG / GOOD / MIXED / WEAK is arithmetic on the LAST reported quarter
-- sales and PAT, QoQ and YoY. It says nothing about the quarter being
announced today.

And read it with care: almost every stored comparison is Mar-26 against
Dec-25, which is Q4 against Q3, and Q4 is India's seasonally strongest
quarter. 71% of companies "grew" on that basis. The WEAK names are the
informative ones -- shrinking in your best quarter is a real signal.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import collections
import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

RESULTS_DB = os.path.join("data", "results_calendar.db")
GRADE_ORDER = {"STRONG": 0, "GOOD": 1, "MIXED": 2, "WEAK": 3, None: 4}


def _ro(path):
    if not os.path.exists(path):
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def events_between(lo, hi):
    """{date -> [(symbol, purpose, broadcast_at)]}"""
    out = collections.defaultdict(list)
    conn = _ro(RESULTS_DB)
    if conn is None:
        print(f"  {RESULTS_DB} not found.")
        return out
    for sym, d, purpose, at in conn.execute(
            "select symbol, results_date, purpose, broadcast_at "
            "from results_events where results_date between ? and ? "
            "order by results_date, symbol", (lo.isoformat(), hi.isoformat())):
        out[d].append((sym, purpose or "", at or ""))
    return out


def grades_for(symbols):
    """{symbol: (grade, summary)} from the quarterly store."""
    try:
        from core.quarterly_results import QuarterlyResults
        store = QuarterlyResults()
    except Exception:                                      # noqa: BLE001
        return {}
    out = {}
    for s in symbols:
        try:
            c = store.compare(s)
        except Exception:                                  # noqa: BLE001
            continue
        if c and c.get("grade"):
            out[s] = (c["grade"], c.get("summary") or "", c.get("period"))
    return out


def show_range(back, ahead, with_grades=True):
    today = datetime.now().date()
    lo, hi = today - timedelta(days=back), today + timedelta(days=ahead)
    by_date = events_between(lo, hi)

    everyone = {s for rows in by_date.values() for s, _, _ in rows}
    grades = grades_for(everyone) if with_grades else {}

    print(f"\nRESULTS CALENDAR   today is {today}")
    print(f"{'':<12}{'':<10}last quarter on record")
    print("-" * 96)

    for offset in range(-back, ahead + 1):
        d = today + timedelta(days=offset)
        rows = by_date.get(d.isoformat(), [])
        if not rows and offset not in (0,):
            continue
        label = ("TODAY" if offset == 0 else
                 "yesterday" if offset == -1 else
                 "tomorrow" if offset == 1 else
                 f"{abs(offset)}d ago" if offset < 0 else f"in {offset}d")
        mark = "  <<<" if offset == 0 else ""
        print(f"\n{d}  {label:<10}{len(rows):>3} companies{mark}")
        if not rows:
            print("     (nothing scheduled)")
            continue
        # Graded names first -- they are the ones worth reading.
        rows = sorted(rows, key=lambda r: (GRADE_ORDER[grades.get(r[0], (None,))[0]],
                                           r[0]))
        for sym, purpose, at in rows:
            g = grades.get(sym)
            if g:
                grade, summary, period = g
                print(f"     {sym:<13}{grade:<8}{period:<8}{summary[:52]}")
            else:
                print(f"     {sym:<13}{'-':<8}{'':<8}{purpose[:52]}")


def show_symbol(symbol):
    symbol = symbol.upper()
    conn = _ro(RESULTS_DB)
    print(f"\n{symbol}")
    if conn is not None:
        rows = conn.execute(
            "select results_date, purpose, broadcast_at from results_events "
            "where symbol=? order by results_date", (symbol,)).fetchall()
        print(f"\n  {len(rows)} calendar event(s):")
        for d, purpose, at in rows[-12:]:
            print(f"     {d}   {(purpose or '')[:46]:<46}{at or ''}")
    try:
        from core.quarterly_results import QuarterlyResults
        store = QuarterlyResults()
        hist = store.history(symbol)
        print(f"\n  {len(hist)} quarter(s) of numbers:")
        for h in hist:
            print(f"     {h['period_label'] or h['period_end']:<9}"
                  f"sales {h['sales'] if h['sales'] is not None else '-':>10}  "
                  f"PAT {h['pat'] if h['pat'] is not None else '-':>9}  "
                  f"EPS {h['eps'] if h['eps'] is not None else '-':>7}  "
                  f"[{h['source']}]")
        c = store.compare(symbol)
        if c:
            print(f"\n  grade: {c['grade']}   {c['summary']}")
            if c.get("qoq"):
                print(f"     QoQ vs {c['qoq']['period']}: "
                      f"sales {c['qoq']['sales']}  PAT {c['qoq']['pat']}")
            if c.get("yoy"):
                print(f"     YoY vs {c['yoy']['period']}: "
                      f"sales {c['yoy']['sales']}  PAT {c['yoy']['pat']}")
        else:
            print("\n  not enough quarters stored to compare yet")
    except Exception as exc:                               # noqa: BLE001
        print(f"  quarterly store unavailable: {exc}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--back", type=int, default=3)
    ap.add_argument("--days", type=int, default=5)
    ap.add_argument("--symbol")
    ap.add_argument("--today", action="store_true")
    a = ap.parse_args()

    if a.symbol:
        show_symbol(a.symbol)
        return
    if a.today:
        show_range(0, 0)
        return
    show_range(a.back, a.days)
    print("\n  Grade is the LAST reported quarter, not the one being "
          "announced.\n  Most comparisons are Q4 vs Q3 and Q4 is India's "
          "strongest quarter,\n  so WEAK is the informative one.")


if __name__ == "__main__":
    main()
