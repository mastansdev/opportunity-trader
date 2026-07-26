"""
==========================================================
Build daily history -- run ONCE, then the morning tool keeps it current
==========================================================

    py tools/build_daily_history.py            # last 30 trading days
    py tools/build_daily_history.py 60         # last 60

Downloads that many past bhavcopies and stores the daily OPEN / HIGH /
LOW / CLOSE / PREV CLOSE / VOLUME / TURNOVER for every EQ scrip. Slow the
first time (one HTTP download per trading day), instant afterwards --
already-stored dates are skipped, so re-running costs nothing.

After this, `py tools/morning_universe.py` appends one day per run and
the history stays current on its own.

Why bother: seven daily bars is enough to see whether a stock has been
stepping UP day after day, has stopped, or has broken down -- the
structure the operator described with PARAS / KALYANKJIL / DATAPATTERNS.
See core/trend_structure.py.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.daily_store import DailyStore, bars_from_bhavcopy  # noqa: E402
from core.logger import decision, warn  # noqa: E402
from core.universe_builder import fetch_bhavcopy  # noqa: E402


def build(days=30, store=None):
    store = store or DailyStore()
    have = set(store.dates())
    decision(f"[DAILY] Already stored: {len(have)} day(s).")

    added_days = 0
    day = datetime.now()
    checked = 0
    # Walk back over calendar days, skipping weekends, until we've
    # collected `days` trading days. The 2x cushion covers holidays.
    while added_days < days and checked < days * 2 + 20:
        day -= timedelta(days=1)
        checked += 1
        if day.weekday() >= 5:
            continue
        key = day.strftime("%Y-%m-%d")
        if key in have:
            added_days += 1
            continue

        rows = fetch_bhavcopy(date=day, folder="data")
        if not rows:
            continue                       # holiday, or a failed download
        bars = bars_from_bhavcopy(rows, key)
        written = store.upsert_many(bars)
        added_days += 1
        decision(f"[DAILY] {key}: {written} bars stored "
                 f"({len(bars)} EQ scrips in the file).")

    return store.stats()


def main():
    days = 30
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            warn(f"Ignoring '{sys.argv[1]}' -- expected a number of days.")

    decision("=" * 58)
    decision(f"  BUILD DAILY HISTORY  ({days} trading days)")
    decision("=" * 58)

    stats = build(days=days)

    decision("-" * 58)
    decision(f"  Days stored  : {stats['days']}  "
             f"({stats['first']} -> {stats['last']})")
    decision(f"  Symbols      : {stats['symbols']}")
    decision(f"  Total bars   : {stats['bars']:,}")
    if stats["days"] < 8:
        warn("  Fewer than 8 days stored -- a 7-day structure read needs "
             "8 bars to make 7 comparisons. Re-run when more history is "
             "available.")
    decision("=" * 58)
    decision("  Now run:  py tools/trend_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
