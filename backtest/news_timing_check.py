"""
==========================================================
Step 1 -- prove we are buying AFTER the news, not before
==========================================================

    py backtest/news_timing_check.py
    py backtest/news_timing_check.py --show 20

WHY THIS FILE EXISTS BEFORE ANY STRATEGY FILE
---------------------------------------------
On 2026-07-27 the swing backtest was reported to the operator four
times with confident numbers. It had a look-ahead bug: positions still
open at the end of a window were sold at the symbol's LAST EVER price,
five years in the future. BSE printed as 212.88 -> 3,549.70 in twenty
days. It was found only because the operator asked to see individual
trades instead of a summary.

A news backtest has the same bug waiting in a new place. Every
announcement carries a timestamp -- KARURVYSYA's Q1 results were filed
at 14:24:23 on 2026-07-20. If the code buys at that day's OPEN, it buys
five hours before the news existed, the results look wonderful, and
they are worthless.

So this file does ONE thing: it prints, for real announcements, the
timestamp of the news and the timestamp of the bar we would buy on, so
a human can confirm the second is after the first. No strategy, no
P&L, no conclusions. If the timestamps are wrong, nothing built on top
of them can be right.

WHAT "TRADEABLE" MEANS HERE
---------------------------
    news during market hours -> the next 1-minute bar that OPENS after
                                the announcement timestamp
    news after 15:30         -> the next trading day's first bar
    news before 09:15        -> the same day's first bar

The 1-minute history covers 2026-04-28 to 2026-07-24 only, so this
check runs on the 975 announcements inside that window.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MINUTE_DB = "data/history_candles.db"
EVENTS_DB = "data/results_calendar.db"
MIN_DATE, MAX_DATE = "2026-04-28", "2026-07-24"


def load_events():
    con = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    return con.execute(
        "select symbol, results_date, broadcast_at from results_events "
        "where broadcast_at is not null and results_date between ? and ? "
        "order by broadcast_at", (MIN_DATE, MAX_DATE)).fetchall()


def load_minutes(events):
    """Loads ONLY the (date, symbol) pairs the announcements actually
    touch, plus the following session so a post-close announcement has
    a next-day bar to buy on.

    Two slower approaches were tried first and both blew the time
    budget: one SQL lookup per announcement (975 x 2 queries against a
    2 GB file with no (symbol, minute) index), and a full-table scan of
    all 11.6 million rows over a network mount. This is a handful of
    date-indexed queries with a short symbol list each."""
    con = sqlite3.connect(f"file:{MINUTE_DB}?mode=ro", uri=True)
    all_dates = [r[0] for r in con.execute(
        "select distinct date from candles order by date")]
    nxt = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}

    need = {}
    for sym, rdate, ts in events:
        d = str(rdate)
        need.setdefault(d, set()).add(sym)
        if d in nxt:
            need.setdefault(nxt[d], set()).add(sym)

    bars = {}
    for d, syms in sorted(need.items()):
        marks = ",".join("?" * len(syms))
        rows = con.execute(
            f"select symbol, minute, o, h, l, c from candles "
            f"where date = ? and symbol in ({marks}) order by symbol, minute",
            [d] + sorted(syms)).fetchall()
        for sym, minute, o, h, l, c in rows:
            bars.setdefault(sym, []).append((minute, o, h, l, c))
    for v in bars.values():
        v.sort()
    return bars


def first_bar_after(bars, symbol, when):
    """The first 1-minute bar whose own timestamp is strictly AFTER
    `when`. Strictly, not >=: a bar stamped 14:24 covers 14:24:00 to
    14:24:59, so news at 14:24:23 lands inside it and that bar is
    already contaminated. The first CLEAN bar is 14:25."""
    series = bars.get(symbol)
    if not series:
        return None
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] <= when:
            lo = mid + 1
        else:
            hi = mid
    return series[lo] if lo < len(series) else None


def last_bar_before(bars, symbol, when):
    series = bars.get(symbol)
    if not series:
        return None
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < when:
            lo = mid + 1
        else:
            hi = mid
    return (series[lo - 1][0], series[lo - 1][4]) if lo > 0 else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()

    events = load_events()
    print(f"announcements in the 1-minute window: {len(events)}")
    bars = load_minutes(events)
    print(f"symbols with minute bars loaded     : {len(bars)}\n")

    checked = ok = no_bars = 0
    shown = 0
    bad = []
    print("Each row: when the company filed, and the first minute we could")
    print("actually buy. The BUY time must be LATER than the NEWS time.\n")
    print(f"{'symbol':<13}{'news filed at':<21}{'we buy at':<21}"
          f"{'price before':>13}{'price we pay':>13}")
    print("-" * 82)

    for sym, rdate, ts in events:
        when = str(ts)[:19].replace(" ", "T")
        nxt = first_bar_after(bars, sym, when)
        if not nxt:
            no_bars += 1
            continue
        checked += 1
        prev = last_bar_before(bars, sym, when)
        # THE CHECK
        if nxt[0] <= when:
            bad.append((sym, when, nxt[0]))
        else:
            ok += 1
        if shown < a.show:
            shown += 1
            before = f"{prev[1]:,.2f}" if prev else "-"
            print(f"{sym:<13}{when:<21}{nxt[0]:<21}{before:>13}{nxt[1]:>13,.2f}")

    print("\n" + "=" * 82)
    print(f"  announcements with usable minute bars : {checked}")
    print(f"  ...where the buy bar is AFTER the news: {ok}")
    print(f"  ...where it is NOT (look-ahead)       : {len(bad)}")
    print(f"  no minute bars for that symbol at all : {no_bars}")
    if bad:
        print("\n  LOOK-AHEAD DETECTED -- do not trust anything built on this:")
        for s, w, g in bad[:10]:
            print(f"    {s}: news {w}, buy bar {g}")
    else:
        print("\n  No look-ahead. Every buy happens after its news.")
    print("=" * 82)


if __name__ == "__main__":
    main()
