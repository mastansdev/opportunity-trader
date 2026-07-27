"""
==========================================================
Step 2 -- let the MARKET tell us the result was good
==========================================================

    py backtest/news_reaction.py --show 15
    py backtest/news_reaction.py --threshold 1.0

THE PROBLEM THIS SOLVES
-----------------------
data/results_calendar.db records WHEN a company filed results. It does
not record WHAT the numbers were. There is no profit, no sales, no
growth figure anywhere in it. So a strategy built on it alone would buy
every filing -- the 45%-profit-jump and the 20%-profit-collapse
identically.

The operator does not read a balance sheet at 14:24 either. He watches
the stock move and reacts. That is the substitute available to us:
do not judge the result, judge the market's judgement of the result.

HOW IT WORKS, AND WHERE THE LOOK-AHEAD WOULD BE
-----------------------------------------------
    14:24:23   company files results
    14:25      first clean bar -- WATCH starts here, we hold nothing
    14:35      WATCH ends. reaction = move across those ten minutes
    14:36      IF the reaction was strong enough, we BUY here

The buy bar is strictly after the watch window. Nothing decides the
trade using a price at or after the entry. This is the same class of
mistake that made the swing backtest print BSE at 212.88 -> 3,549.70
on 2026-07-27, so it is asserted in code, not assumed.

ONLY IN-HOURS NEWS
------------------
2,505 of the announcements arrive after the close. There is nothing to
watch -- the market is shut and the whole reaction lands in the next
open (CEATLTD closed 3,516.70 and opened 3,810.00). Those are excluded
here. This file measures only news that arrives while the market is
open AND early enough to leave time to trade: 09:15 to 14:30.

WHAT IT REPORTS
---------------
Individual trades first, summary second. That order is deliberate.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import sqlite3
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

MINUTE_DB = "data/history_candles.db"
EVENTS_DB = "data/results_calendar.db"
MIN_DATE, MAX_DATE = "2026-04-28", "2026-07-24"
WATCH_MINUTES = 10
LAST_NEWS_TIME = "14:30:00"     # need room to watch AND to trade


def load_events():
    con = sqlite3.connect(f"file:{EVENTS_DB}?mode=ro", uri=True)
    rows = con.execute(
        "select symbol, results_date, broadcast_at from results_events "
        "where broadcast_at is not null and results_date between ? and ? "
        "order by broadcast_at", (MIN_DATE, MAX_DATE)).fetchall()
    out = []
    for sym, rdate, ts in rows:
        t = str(ts)[11:19]
        if "09:15:00" <= t <= LAST_NEWS_TIME:
            out.append((sym, str(rdate), str(ts)[:19].replace(" ", "T")))
    return out


def load_minutes(events):
    con = sqlite3.connect(f"file:{MINUTE_DB}?mode=ro", uri=True)
    all_dates = [r[0] for r in con.execute(
        "select distinct date from candles order by date")]
    nxt = {d: all_dates[i + 1] for i, d in enumerate(all_dates[:-1])}
    need = {}
    for sym, d, _ in events:
        need.setdefault(d, set()).add(sym)
        if d in nxt:
            need.setdefault(nxt[d], set()).add(sym)
    bars = {}
    for d, syms in sorted(need.items()):
        marks = ",".join("?" * len(syms))
        for sym, minute, o, h, l, c in con.execute(
                f"select symbol, minute, o, h, l, c from candles "
                f"where date = ? and symbol in ({marks})",
                [d] + sorted(syms)):
            bars.setdefault(sym, []).append((minute, o, h, l, c))
    for v in bars.values():
        v.sort()
    return bars, nxt


def bar_at_or_after(series, when):
    lo, hi = 0, len(series)
    while lo < hi:
        mid = (lo + hi) // 2
        if series[mid][0] < when:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(series) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=1.0,
                    help="%% move during the watch window to trigger a buy")
    ap.add_argument("--show", type=int, default=15)
    a = ap.parse_args()

    events = load_events()
    bars, nxt = load_minutes(events)
    print(f"in-hours announcements (09:15-{LAST_NEWS_TIME}): {len(events)}")
    print(f"watch window: {WATCH_MINUTES} minutes after the filing")
    print(f"buy if the stock moved more than +{a.threshold}% in that window\n")

    rows = []
    for sym, d, when in events:
        s = bars.get(sym)
        if not s:
            continue
        i = bar_at_or_after(s, when)          # bar containing the news
        if i is None:
            continue
        # first CLEAN bar is the one after the news bar
        w0 = i + 1
        w1 = w0 + WATCH_MINUTES
        e = w1 + 1                            # entry bar, strictly later
        if e >= len(s):
            continue
        if s[w0][0][:10] != d or s[e][0][:10] != d:
            continue                          # ran past the session
        assert s[e][0] > s[w1][0] > s[w0][0] > when, "look-ahead"
        react = (s[w1][4] - s[w0][1]) / s[w0][1] * 100.0
        entry = s[e][1]
        if entry <= 0:
            continue
        close = s[-1][4] if s[-1][0][:10] == d else None
        j15 = min(e + 15, len(s) - 1)
        j60 = min(e + 60, len(s) - 1)
        rows.append(dict(
            sym=sym, when=when, react=react, entry_at=s[e][0], entry=entry,
            m15=(s[j15][4] - entry) / entry * 100.0,
            m60=(s[j60][4] - entry) / entry * 100.0,
            eod=(close - entry) / entry * 100.0 if close else None))

    hits = [r for r in rows if r["react"] >= a.threshold]
    print(f"announcements measured : {len(rows)}")
    print(f"...that triggered a buy: {len(hits)}\n")

    print("TRADES -- check any of these on a chart before reading the summary")
    print(f"{'symbol':<12}{'news at':<20}{'move in 10min':>14}"
          f"{'buy at':<20}{'price':>9}{'+15min':>8}{'+60min':>8}{'close':>8}")
    print("-" * 100)
    for r in hits[:a.show]:
        eod = f"{r['eod']:+.2f}%" if r["eod"] is not None else "   -"
        print(f"{r['sym']:<12}{r['when']:<20}{r['react']:>13.2f}%"
              f"{r['entry_at']:<20}{r['entry']:>9,.2f}"
              f"{r['m15']:>7.2f}%{r['m60']:>7.2f}%{eod:>8}")

    def summary(name, group):
        if not group:
            return
        print(f"\n{name}  (n={len(group)})")
        for k, label in (("m15", "15 min after buying"),
                         ("m60", "60 min after buying"),
                         ("eod", "at the close")):
            v = [r[k] for r in group if r[k] is not None]
            if not v:
                continue
            up = 100.0 * sum(1 for x in v if x > 0) / len(v)
            print(f"   {label:<22}avg {statistics.mean(v):+.3f}%   "
                  f"median {sorted(v)[len(v)//2]:+.3f}%   up {up:.1f}%")

    summary("BOUGHT (stock was running)", hits)
    summary("ALL announcements (no filter)", rows)
    summary("SKIPPED (stock was not running)",
            [r for r in rows if r["react"] < a.threshold])


if __name__ == "__main__":
    main()
