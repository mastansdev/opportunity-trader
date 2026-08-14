"""
==========================================================
py tools/grade_audit.py  --  why did grade_edge see no grades?
==========================================================

grade_edge.py reported 0 graded stocks on eight of twelve recorded
sessions, including 5 and 6 August -- two days core/watchlist_builder.py
names in its own comments as having stored grades (SHILPAMED GOOD,
ENRIN EXCELLENT). Either those comments are wrong or the lookup is.

This answers that, and nothing else. It writes nothing and changes
nothing.

THREE PLACES IT CAN BREAK, checked in order
-------------------------------------------
  1. THE STORE.     data/telegram.db has no messages that far back,
                    or has them with an empty `grade` column.
  2. THE WINDOW.    graded_symbols(hours=36) looks back 36 hours from
                    the moment asked about. If `at` is stored in UTC
                    and the cutoff is built from a naive IST datetime,
                    the two are 5h30m apart and the window lands in
                    the wrong place.
  3. THE SYMBOLS.   The grades load fine but the symbol strings do not
                    match the ones in the candle store, so every
                    lookup misses and every stock falls into CONTROL.

Failure 3 is the dangerous one: it produces a clean-looking table
with a full control group and empty grade rows, which reads as
"the grade has no edge" when it means "the join failed".

    py tools/grade_audit.py

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, time as dtime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

TELEGRAM = os.path.join(ROOT, "data", "telegram.db")
CANDLES = os.path.join(ROOT, "data", "backtest_candles.db")

TOP_GRADES = ("EXCELLENT", "GREAT", "GOOD")


def rule(title):
    print()
    print("=" * 74)
    print(f"  {title}")
    print("=" * 74)


# ==========================================================
#  1. THE STORE
# ==========================================================

def audit_store():
    rule("1. WHAT IS ACTUALLY IN data/telegram.db")

    if not os.path.exists(TELEGRAM):
        print("  telegram.db does not exist. That is the whole answer.")
        return False

    con = sqlite3.connect(TELEGRAM)
    try:
        total = con.execute("select count(*) from messages").fetchone()[0]
    except sqlite3.Error as exc:
        print(f"  Cannot read messages: {exc}")
        con.close()
        return False

    lo, hi = con.execute(
        "select min(at), max(at) from messages").fetchone()
    print(f"  {total:,} message(s)")
    print(f"  earliest at : {lo}")
    print(f"  latest   at : {hi}")

    # Is `at` even the format the window comparison assumes? The query
    # in graded_symbols compares it as a STRING against an isoformat()
    # cutoff. If these disagree in shape, every comparison is nonsense.
    print()
    print("  A string window only works if every `at` is ISO. Shapes seen:")
    shapes = defaultdict(int)
    for (at,) in con.execute(
            "select at from messages where at is not null limit 5000"):
        text = str(at)
        shape = "".join("9" if ch.isdigit() else ch for ch in text)[:24]
        shapes[shape] += 1
    for shape, n in sorted(shapes.items(), key=lambda kv: -kv[1])[:6]:
        print(f"    {shape:<28} {n:>6}")

    print()
    print("  Messages carrying a stored grade, by day:")
    rows = con.execute(
        "select substr(at, 1, 10) as day, upper(coalesce(grade, '')), "
        "count(*) from messages "
        "where symbols is not null and symbols <> '' "
        "group by day, upper(coalesce(grade, '')) "
        "order by day").fetchall()
    con.close()

    by_day = defaultdict(lambda: defaultdict(int))
    for day, grade, n in rows:
        by_day[day][grade or "(none)"] += n

    if not by_day:
        print("    nothing with symbols attached at all")
        return False

    print(f"    {'day':<12} {'EXCELLENT':>10} {'GREAT':>7} {'GOOD':>6} "
          f"{'(none)':>8}")
    for day in sorted(by_day):
        counts = by_day[day]
        print(f"    {day:<12} {counts.get('EXCELLENT', 0):>10} "
              f"{counts.get('GREAT', 0):>7} {counts.get('GOOD', 0):>6} "
              f"{counts.get('(none)', 0):>8}")
    return True


# ==========================================================
#  2. THE WINDOW
# ==========================================================

def recorded_days():
    if not os.path.exists(CANDLES):
        return []
    con = sqlite3.connect(CANDLES)
    try:
        days = [r[0] for r in con.execute(
            "select distinct date from candles order by date")]
    except sqlite3.Error:
        days = []
    con.close()
    return days


def audit_window(days):
    rule("2. WHAT graded_symbols() RETURNS FOR EACH RECORDED DAY")

    try:
        from core import watchlist_builder
    except Exception as exc:                                   # noqa: BLE001
        print(f"  Cannot import core.watchlist_builder: {exc}")
        return {}

    print(f"  hours window = {watchlist_builder.graded_symbols.__defaults__}")
    print()
    found = {}
    for day in days:
        when = datetime.combine(datetime.fromisoformat(day).date(),
                                dtime(9, 15))
        try:
            got = watchlist_builder.graded_symbols(now=when) or {}
        except Exception as exc:                               # noqa: BLE001
            print(f"  {day}   RAISED: {exc}")
            continue
        found[day] = got
        sample = ", ".join(sorted(got)[:6])
        print(f"  {day}   {len(got):>4} graded   {sample}")

    # The same question asked WITHOUT a cutoff. If this returns plenty
    # while the dated calls return nothing, the bug is the window, not
    # the store.
    print()
    try:
        now_grades = watchlist_builder.graded_symbols() or {}
        print(f"  with no cutoff (i.e. right now): {len(now_grades)} graded")
    except Exception as exc:                                   # noqa: BLE001
        print(f"  with no cutoff: RAISED {exc}")

    # And with a much wider window, which separates "the messages are
    # older than 36 hours" from "the messages are not there".
    print()
    for hours in (36, 96, 24 * 30):
        try:
            wide = watchlist_builder.graded_symbols(
                hours=hours, now=datetime(2026, 8, 6, 9, 15)) or {}
            print(f"  6 Aug 09:15, {hours:>4}h window: {len(wide)} graded")
        except Exception as exc:                               # noqa: BLE001
            print(f"  6 Aug 09:15, {hours:>4}h window: RAISED {exc}")
    return found


# ==========================================================
#  3. THE SYMBOLS
# ==========================================================

def audit_symbols(found):
    rule("3. DO THE GRADED SYMBOLS MATCH THE CANDLE STORE?")

    if not os.path.exists(CANDLES):
        print("  no candle store")
        return

    con = sqlite3.connect(CANDLES)
    for day, grades in sorted(found.items()):
        if not grades:
            continue
        tape = {r[0] for r in con.execute(
            "select distinct symbol from candles where date=?", (day,))}
        hit = set(grades) & tape
        miss = set(grades) - tape
        print(f"  {day}   {len(hit):>3} of {len(grades):>3} graded symbols "
              f"have candles")
        if miss:
            print(f"      no candles for: {', '.join(sorted(miss)[:10])}")
    con.close()

    print()
    print("  A graded symbol with no candles is invisible to grade_edge.")
    print("  It is not counted as graded AND not counted as control --")
    print("  it simply vanishes, and the sample silently shrinks.")


def main():
    days = recorded_days()
    if not days:
        print("No recorded sessions in data/backtest_candles.db.")
        return 1
    audit_store()
    found = audit_window(days)
    audit_symbols(found)
    print()
    print("=" * 74)
    print("  Read section 1 first. If the grades are not in the store,")
    print("  sections 2 and 3 cannot tell you anything.")
    print("=" * 74)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
