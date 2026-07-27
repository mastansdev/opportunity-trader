"""
==========================================================
Event study -- does the move come the NEXT day?
==========================================================

    py backtest/event_study.py
    py backtest/event_study.py --symbol KARURVYSYA

THE OPERATOR'S CLAIM, 2026-07-27
--------------------------------
"ex karurvysya - result day no movement; next day almost upper circuit"

and, on why intraday could never work for this:

"after 09:30 itself all top trading stocks gone and simply moving in a
range... so MTF will help in this case by holding and next day gap will
be rided"

That is a specific, falsifiable claim about WHERE the return lives:
NOT in the results-day session, but in the gap between that close and
the next open. If true it has three consequences:

  1. An intraday bot structurally CANNOT capture it. It is flat at
     15:15, and the move happens while it is flat.
  2. The position has to be held overnight -- which needs MTF, exactly
     as the operator says.
  3. The trigger is an EVENT, not a price pattern. Every backtest run
     on 2026-07-27 before this one tested price patterns with no event
     input at all, which is why they measured nothing.

WHAT THIS MEASURES
------------------
For every results event with matching price history:

    d0      the results session itself
    gap     next open  vs d0 close      <- the operator's claim
    d1      next close vs d0 close
    d2..d10 further drift

then buckets by what d0 itself did, to answer the sharp version of the
claim: does a stock that did NOTHING on results day move the next day?

WHAT IT DOES NOT DO
-------------------
No costs, no sizing, no strategy. This is measurement only -- is the
effect there at all. If it is not, no rule set built on it can work and
we stop. If it is, THEN it gets a strategy, a random control, and a
cost model, in that order.

The events span 2025-07 -> 2026-07: four earnings seasons. That is
thin, and one good season could carry the whole result. Any effect
found here is a candidate, not a finding.
==========================================================
"""

import argparse
import os
import sqlite3
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

EXCLUDE = {
    "ZFCVINDIA", "PATANJALI", "HEXT", "PICCADIL", "MWL", "MIDQ50ADD",
    "SHRIPISTON", "HEALTHADD", "PSUBANK", "JLHL", "MBAPL", "KRISHANA",
    "POCL", "BRIGADE",
}


def load_prices():
    con = sqlite3.connect("file:data/daily_candles.db?mode=ro", uri=True)
    rows = con.execute(
        "select symbol, date, open, high, low, close from daily_bars "
        "where close > 0 order by symbol, date").fetchall()
    bars = defaultdict(list)
    for sym, d, o, h, l, c in rows:
        if sym not in EXCLUDE:
            bars[sym].append((d, o, h, l, c))
    idx = {s: {r[0]: i for i, r in enumerate(v)} for s, v in bars.items()}
    return bars, idx


def load_events():
    con = sqlite3.connect("file:data/results_calendar.db?mode=ro", uri=True)
    return con.execute(
        "select symbol, results_date from results_events "
        "order by results_date").fetchall()


def measure(bars, idx, sym, date):
    """Returns the move on the results day, the overnight gap, and the
    drift after it -- or None if the history isn't there."""
    series = bars.get(sym)
    if not series:
        return None
    i = idx[sym].get(str(date))
    if i is None:
        # results date wasn't a trading day -- use the next session
        later = [j for d, j in idx[sym].items() if d > str(date)]
        if not later:
            return None
        i = min(later)
    if i < 1 or i + 10 >= len(series):
        return None
    prev_c = series[i - 1][4]
    d0_c = series[i][4]
    d1_o = series[i + 1][1]
    d1_c = series[i + 1][4]
    if not prev_c or not d0_c:
        return None
    pct = lambda a, b: (a - b) / b * 100.0
    return dict(
        sym=sym, date=series[i][0],
        d0=pct(d0_c, prev_c),
        gap=pct(d1_o, d0_c),
        d1=pct(d1_c, d0_c),
        d3=pct(series[i + 3][4], d0_c),
        d5=pct(series[i + 5][4], d0_c),
        d10=pct(series[i + 10][4], d0_c),
    )


def stats(rows, key):
    v = sorted(r[key] for r in rows)
    if not v:
        return None
    return dict(n=len(v), mean=statistics.mean(v),
                med=v[len(v) // 2],
                up=100.0 * sum(1 for x in v if x > 0) / len(v))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=None)
    a = ap.parse_args()

    bars, idx = load_prices()
    events = load_events()
    rows = [m for s, d in events if (m := measure(bars, idx, s, d))]
    print(f"events measured: {len(rows):,} "
          f"across {len({r['sym'] for r in rows})} symbols\n")

    if a.symbol:
        mine = [r for r in rows if r["sym"] == a.symbol]
        print(f"--- {a.symbol} ---")
        print(f"{'results day':<13}{'d0':>8}{'gap':>8}{'d1':>8}"
              f"{'d3':>8}{'d5':>8}{'d10':>8}")
        for r in mine:
            print(f"{r['date']:<13}{r['d0']:>7.1f}%{r['gap']:>7.1f}%"
                  f"{r['d1']:>7.1f}%{r['d3']:>7.1f}%{r['d5']:>7.1f}%"
                  f"{r['d10']:>7.1f}%")
        return

    print("ALL EVENTS -- where does the move actually happen?")
    print(f"{'window':<10}{'n':>7}{'mean':>9}{'median':>9}{'% up':>8}")
    for k, label in (("d0", "results day"), ("gap", "overnight gap"),
                     ("d1", "next day"), ("d3", "3 days"),
                     ("d5", "5 days"), ("d10", "10 days")):
        s = stats(rows, k)
        print(f"{label:<10}{s['n']:>7,}{s['mean']:>8.2f}%"
              f"{s['med']:>8.2f}%{s['up']:>7.1f}%")

    print("\n\nTHE OPERATOR'S CLAIM: split by what the RESULTS DAY did.")
    print("If 'quiet on results day, moves next day' is real, the QUIET")
    print("bucket should show a large gap and next-day move.\n")
    buckets = [(-999, -3, "d0 fell over 3%"), (-3, -1, "d0 fell 1-3%"),
               (-1, 1, "d0 QUIET (-1% to +1%)"), (1, 3, "d0 rose 1-3%"),
               (3, 999, "d0 rose over 3%")]
    print(f"{'results-day move':<26}{'n':>6}{'gap':>9}{'next day':>10}"
          f"{'5 days':>9}{'10 days':>9}")
    for lo, hi, label in buckets:
        b = [r for r in rows if lo <= r["d0"] < hi]
        if not b:
            continue
        g, d1 = stats(b, "gap"), stats(b, "d1")
        d5, d10 = stats(b, "d5"), stats(b, "d10")
        print(f"{label:<26}{len(b):>6}{g['mean']:>8.2f}%{d1['mean']:>9.2f}%"
              f"{d5['mean']:>8.2f}%{d10['mean']:>8.2f}%")


if __name__ == "__main__":
    main()
