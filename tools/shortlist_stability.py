"""
==========================================================
Does the shortlist hold its shape through the day?
==========================================================

Operator's question, 2026-07-27:

    "based on the movement does it move up & down or stay in same rank
     till day close?"

This is THE question for a screener that is supposed to help you enter
early. If a stock ranked 2nd at 09:30 is 40th by noon, an early list is
noise and you have to keep re-reading it all day. If it holds, the
09:30 list is actionable and the whole "enter early" idea works.

Method: rebuild the same ranking at several clock times using only the
data that existed AT that time (price up to that minute, nothing
later), then track where each name sat.

No look-ahead. The 10:00 ranking cannot see 10:01.

Usage:
    python -m tools.shortlist_stability --date 2026-07-27
==========================================================
"""

import argparse
import collections
import sqlite3
import statistics
from datetime import datetime, timedelta

from tools.shortlist import (DAILY_DB, INTRADAY_DB, MIN_TURNOVER,
                             normals, results_near, actions_near,
                             VETO_ACTIONS)

CHECKPOINTS = ["09:30", "10:00", "10:30", "11:00", "12:00",
               "13:00", "14:00", "15:00", "15:28"]


def prices_upto(date, hhmm):
    """{symbol: (day_open, price_at_hhmm)} using only bars at or before
    hhmm. This is what the bot could have known at that moment."""
    c = sqlite3.connect(f"file:{INTRADAY_DB}?mode=ro", uri=True)
    rows = c.execute(
        "select symbol, minute, o, c from candles "
        "where date=? and substr(minute,12,5)<=? order by symbol, minute",
        (date, hhmm)).fetchall()
    first, last = {}, {}
    for sym, minute, o, cl in rows:
        if sym not in first:
            first[sym] = o
        last[sym] = cl
    return {s: (first[s], last[s]) for s in first}


def rank_at(date, hhmm, norm, res, acts):
    """Same scoring as tools/shortlist.build, minus the volume note
    (which is not scored anyway). Returns {symbol: rank}."""
    px = prices_upto(date, hhmm)
    scored = []
    for sym, (o, cl) in px.items():
        if sym not in norm or not o:
            continue
        _, med_t, ma50 = norm[sym]
        if med_t < MIN_TURNOVER:
            continue
        if any(a in VETO_ACTIONS for a, _ in acts.get(sym, [])):
            continue
        move = (cl - o) / o * 100
        score = abs(move) if abs(move) >= 2.0 else 0.0
        for days, _ in res.get(sym, []):
            score += 4.0 if days <= 0 else 2.0
        for a, _ in acts.get(sym, []):
            if a not in VETO_ACTIONS:
                score += 1.0
        if cl > ma50:
            score += 1.0
        if score >= 2.0:
            scored.append((sym, score, move))
    scored.sort(key=lambda x: -x[1])
    return {s: i + 1 for i, (s, _, _) in enumerate(scored)}, len(scored)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"))
    a = p.parse_args()

    norm = normals(a.date)
    res = results_near(a.date)
    acts = actions_near(a.date)

    ranks = {}
    sizes = {}
    for t in CHECKPOINTS:
        ranks[t], sizes[t] = rank_at(a.date, t, norm, res, acts)

    final = ranks[CHECKPOINTS[-1]]
    close_top20 = [s for s, r in sorted(final.items(), key=lambda x: x[1])[:20]]

    print(f"\nRANK THROUGH THE DAY -- {a.date}")
    print("(where each of the day's final top 20 sat at each clock time)\n")
    hdr = f"{'symbol':<13}" + "".join(f"{t:>8}" for t in CHECKPOINTS)
    print(hdr)
    print("-" * len(hdr))
    for s in close_top20:
        line = f"{s:<13}"
        for t in CHECKPOINTS:
            r = ranks[t].get(s)
            line += f"{r if r else '-':>8}"
        print(line)

    print("\n\nHOW MUCH DOES THE TOP OF THE LIST CHURN?")
    print("(of the top 20 at each time, how many are STILL top 20 at close)\n")
    print(f"{'time':<10}{'names ranked':>14}{'of its top 20, still top 20 at close':>40}")
    print("-" * 64)
    for t in CHECKPOINTS:
        top20 = {s for s, r in ranks[t].items() if r <= 20}
        keep = len(top20 & set(close_top20))
        bar = "#" * keep
        print(f"{t:<10}{sizes[t]:>14}{keep:>10}/20  {bar}")

    print("\n\nHOW EARLY COULD YOU HAVE KNOWN?")
    print("(first checkpoint at which each final top-10 name was already "
          "in the top 10)\n")
    for s in close_top20[:10]:
        first = next((t for t in CHECKPOINTS if ranks[t].get(s, 999) <= 10), None)
        first20 = next((t for t in CHECKPOINTS if ranks[t].get(s, 999) <= 20), None)
        print(f"    {s:<13}top-10 from {first or 'never':<8}"
              f"top-20 from {first20 or 'never'}")


if __name__ == "__main__":
    main()
