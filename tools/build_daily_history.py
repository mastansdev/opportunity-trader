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


# A weekday with no bhavcopy is nearly always a trading holiday. But if
# it is within the last few days it might simply be that NSE has not
# published yet, so those stay retryable instead of being written off.
RETRY_WINDOW_DAYS = 4


def build(days=30, store=None, today=None):
    store = store or DailyStore()
    have = set(store.dates())
    known_empty = store.no_data_dates()
    decision(f"[DAILY] Already stored: {len(have)} day(s)."
             + (f" Known non-trading weekdays: {len(known_empty)}."
                if known_empty else ""))

    added_days = 0
    today = today or datetime.now()

    # ---- TODAY WAS NEVER FETCHED. 4 August 2026. ----
    #
    # This was `day = today`, and the loop's first act is to subtract a
    # day -- so the walk actually began at YESTERDAY and today's
    # bhavcopy was never once requested. Not on any run, ever.
    #
    # It hid because the tool's own summary is about the archive, and
    # the archive looked healthy: "2,464 days stored, 2016-08-23 ->
    # 2026-08-03" on the evening of the 4th. One day short, every day,
    # and the line that would have shown it is the one nobody reads.
    #
    # It surfaced as tools/verify_picks.py refusing to score the bot's
    # picks -- "No daily bars for 2026-08-04 yet -- run
    # build_daily_history.py first" -- after build_daily_history.py had
    # just been run. Which would have made Phase 1 unverifiable
    # tomorrow, and the day after, silently.
    #
    # Starting one day ahead means the first decrement lands on today.
    day = today + timedelta(days=1)
    checked = 0
    holidays = []
    # Walk back over calendar days, skipping weekends, until we've
    # collected `days` trading days. The 2x cushion covers holidays.
    #
    # Asking for today mid-session is safe: NSE has not published yet,
    # fetch_bhavcopy returns nothing, and the holiday check below only
    # fires after RETRY_WINDOW_DAYS -- so today can never be recorded
    # as a non-trading day and stop being retried.
    while added_days < days and checked < days * 2 + 20:
        day -= timedelta(days=1)
        checked += 1
        if day.weekday() >= 5:
            continue
        key = day.strftime("%Y-%m-%d")
        if key in have:
            added_days += 1
            continue
        if key in known_empty:
            # Already established there is no session for this date --
            # don't download it again, and don't warn about it again.
            continue

        rows = fetch_bhavcopy(date=day, folder="data", quiet=True)
        if not rows:
            # Old enough that NSE would certainly have published by now?
            # Then it was a holiday. Record it and stop asking.
            if (today - day).days > RETRY_WINDOW_DAYS:
                store.mark_no_data(key)
                holidays.append(key)
            continue
        bars = bars_from_bhavcopy(rows, key)
        written = store.upsert_many(bars)
        added_days += 1
        decision(f"[DAILY] {key}: {written} bars stored "
                 f"({len(bars)} EQ scrips in the file).")

    if holidays:
        decision(f"[DAILY] No session on {', '.join(holidays)} "
                 f"(trading holiday) -- recorded, won't be retried.")

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
