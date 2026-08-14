"""
==========================================================
py tools/grade_edge.py  --  when can this bot actually trade?
==========================================================

    "so pls do what will make the bot near to tradeable with the
     rules given & earn some money"
                                -- operator, 11 August 2026

WHAT THE FIRST TWO RUNS FOUND
-----------------------------
Run 1 invented its own stop and target and reported on a bot that does
not exist. Run 2 used core/position_plan.py -- the real stop, the real
Rs 1,500 size, the real 2R target -- and found the thing that actually
costs money:

    (ungraded)  refused 7,671 of 10,916   stop too close x7,221

SEVENTY PERCENT of every candidate refused, and not one of them for a
bad reason about the stock. At a 09:20 entry the day low is five
minutes old and sits right under the price, so entry - stop is smaller
than MIN_STOP_DISTANCE_PCT and position_plan refuses. Feeding it ATR
makes it worse, not better: stop_for() takes the TIGHTER of the two
levels, and a 5-candle ATR is tiny.

The bot is not picking badly. It is declining to bet, on seven of ten
opportunities, because there is not yet enough range to place a stop
behind.

    That is a CLOCK problem, not a selection problem.

SO THIS SWEEPS THE CLOCK
------------------------
Same measurement, at 09:20 / 09:30 / 09:45 / 10:00 / 10:30 / 11:00.
For each: how many trades the bot could take, how many it refused and
why, and what it made per trade -- graded against ungraded.

rules.py already says FIRST_NEW_ENTRY = 09:30. This is the evidence for
where that number belongs, measured instead of chosen.

WHAT IT IS NOT
--------------
No charges, no slippage, no MAX_OPEN_POSITIONS. The per-trade column is
the only one that means anything -- you can hold three positions, not
three thousand, so a total across 3,245 trades is arithmetic, not money.

    py tools/grade_edge.py
    py tools/grade_edge.py --at 09:45          one time, full detail
    py tools/grade_edge.py --at 09:45 --csv data/grade_edge.csv

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, time as dtime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

CANDLES = os.path.join(ROOT, "data", "backtest_candles.db")

SWEEP = ("09:20", "09:30", "09:45", "10:00", "10:30", "11:00")
GRADES = ("EXCELLENT", "GREAT", "GOOD")

# Below this, a bucket gets no percentages. tools/refused_review.py has
# carried the same guard since 29 July, when two data points produced a
# very confident wrong answer.
MIN_SAMPLE = 10


def recorded_days(con):
    return [r[0] for r in con.execute(
        "select distinct date from candles order by date")]


def graded_on(day):
    """The grades as they stood at 09:15 that morning -- never today's."""
    when = datetime.combine(datetime.fromisoformat(day).date(),
                            dtime(9, 15))
    from core import watchlist_builder
    return watchlist_builder.graded_symbols(now=when) or {}


def bars_of(con, day):
    """{symbol: [(minute, o, h, l, c, v), ...]} in time order."""
    out = defaultdict(list)
    for row in con.execute(
            "select symbol, minute, o, h, l, c, v from candles "
            "where date=? order by symbol, minute", (day,)):
        out[row[0]].append(row[1:])
    return out


def candidate(bars, entry_at):
    """Entry price and the day low behind it, at `entry_at`."""
    cutoff = None
    for i, (minute, o, h, l, c, v) in enumerate(bars):
        if minute[11:16] >= entry_at:
            cutoff = i
            break
    if cutoff is None or cutoff == 0:
        return None
    entry = bars[cutoff][4]
    lows = [b[3] for b in bars[:cutoff + 1] if b[3] is not None]
    if not entry or entry <= 0 or not lows:
        return None
    return {"entry": entry, "day_low": min(lows), "rest": bars[cutoff + 1:]}


def walk(entry, stop, target, qty, rest):
    """Which came first, the target or the stop. Never flatters itself:
    when both print inside one minute the LOSS is charged."""
    first = "flat"
    for minute, o, h, l, c, v in rest:
        if l is not None and l <= stop:
            first = "loss"
            break
        if h is not None and h >= target:
            first = "win"
            break

    if first == "win":
        exit_px = target
    elif first == "loss":
        exit_px = stop
    else:
        exit_px = rest[-1][4] if rest else entry

    high = max([b[2] for b in rest if b[2] is not None] or [entry])
    return {"first": first,
            "pnl_rs": round(qty * (exit_px - entry), 2),
            "high_pct": (high - entry) / entry * 100.0}


def measure(session, entry_at, plan):
    """One entry time, across every loaded session.

    `session` is [(day, grades, tape), ...] -- loaded once and reused
    for every time in the sweep, because reading twelve days of candles
    six times over is the difference between four seconds and a minute.
    """
    rows, refused = [], []
    for day, grades, tape in session:
        for symbol, bars in tape.items():
            got = candidate(bars, entry_at)
            if not got:
                continue
            grade = str((grades.get(symbol) or {}).get("grade") or "").upper()
            grade = grade if grade in GRADES else ""

            got_plan = plan(got["entry"], "BUY", day_low=got["day_low"])
            if not got_plan.get("ok"):
                refused.append({"date": day, "symbol": symbol, "grade": grade,
                                "why": got_plan.get("why", "?")})
                continue

            rows.append({"date": day, "symbol": symbol, "grade": grade,
                         "entry": got["entry"], "stop": got_plan["stop"],
                         "stop_pct": got_plan["stop_pct"],
                         "target": got_plan["target"],
                         "qty": got_plan["qty"],
                         **walk(got["entry"], got_plan["stop"],
                                got_plan["target"], got_plan["qty"],
                                got["rest"])})
    return rows, refused


def stats(group):
    n = len(group)
    if not n:
        return None
    wins = sum(1 for r in group if r["first"] == "win")
    losses = sum(1 for r in group if r["first"] == "loss")
    return {"n": n, "win": wins / n * 100.0, "loss": losses / n * 100.0,
            "flat": (n - wins - losses) / n * 100.0,
            "stop_pct": sum(r["stop_pct"] for r in group) / n,
            "net": sum(r["pnl_rs"] for r in group),
            "per": sum(r["pnl_rs"] for r in group) / n}


def detail(rows, refused, entry_at, limits):
    """The full table for ONE entry time."""
    lo, hi, mult, risk = limits
    print()
    print("=" * 78)
    print(f"  ENTRY {entry_at}   stop and size from core/position_plan.py")
    print(f"  win = reached +{mult}R before the stop, at Rs {risk:,.0f} risk")
    print("=" * 78)
    print("  " + "-" * 74)
    print(f"  {'':<14} {'n':>5}   {'WIN':>5}  {'LOSS':>5}  {'FLAT':>5}   "
          f"{'stop':>5}  {'net Rs':>11}  {'per tr':>9}")
    print("  " + "-" * 74)

    def line(name, group):
        got = stats(group)
        if not got:
            print(f"  {name:<14} {0:>5}   nothing tradable")
            return
        mark = " " if got["n"] >= MIN_SAMPLE else "?"
        print(f" {mark}{name:<14} {got['n']:>5}   {got['win']:>5.1f}%  "
              f"{got['loss']:>5.1f}%  {got['flat']:>5.1f}%   "
              f"{got['stop_pct']:>5.2f}%  {got['net']:>+11,.0f}  "
              f"{got['per']:>+9,.0f}")

    for grade in GRADES:
        line(grade, [r for r in rows if r["grade"] == grade])
    line("ALL GRADED", [r for r in rows if r["grade"]])
    print("  " + "-" * 74)
    line("CONTROL", [r for r in rows if not r["grade"]])
    print("  " + "-" * 74)

    print()
    print(f"  WHAT THE BOT REFUSED   (stop must be {lo}% to {hi}% away)")
    print("  " + "-" * 74)
    for label in list(GRADES) + ["(ungraded)"]:
        want = label if label in GRADES else ""
        mine = [r for r in refused if r["grade"] == want]
        took = len([r for r in rows if r["grade"] == want])
        total = len(mine) + took
        if not total:
            continue
        reasons = defaultdict(int)
        for r in mine:
            reasons[r["why"]] += 1
        top = sorted(reasons.items(), key=lambda kv: -kv[1])[:2]
        text = "; ".join(f"{why} x{n}" for why, n in top) or "none"
        print(f"  {label:<14} refused {len(mine):>5} of {total:>5}   {text}")
    print("  " + "-" * 74)


def main(argv):
    only_at = None
    if "--at" in argv:
        spot = argv.index("--at")
        if spot + 1 < len(argv):
            only_at = argv[spot + 1]

    csv_path = None
    if "--csv" in argv:
        spot = argv.index("--csv")
        csv_path = (argv[spot + 1]
                    if spot + 1 < len(argv) and not argv[spot + 1].startswith("-")
                    else "data/grade_edge.csv")

    if not os.path.exists(CANDLES):
        print(f"\n  No candle store at {CANDLES}. Nothing to measure.\n")
        return 1

    from core.position_plan import plan
    from core.rules import (MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT,
                            MIN_REWARD_MULTIPLE, RISK_PER_TRADE_RS)
    limits = (MIN_STOP_DISTANCE_PCT, MAX_STOP_DISTANCE_PCT,
              MIN_REWARD_MULTIPLE, RISK_PER_TRADE_RS)

    con = sqlite3.connect(CANDLES)
    days = recorded_days(con)
    if not days:
        print("\n  The candle store has no sessions in it.\n")
        con.close()
        return 1

    print()
    print(f"  Loading {len(days)} session(s): {days[0]} to {days[-1]} ...")
    session, with_grades = [], 0
    for day in days:
        try:
            grades = graded_on(day)
        except Exception as exc:                               # noqa: BLE001
            print(f"    {day}  COULD NOT READ THE GRADES: {exc}")
            grades = {}
        if grades:
            with_grades += 1
        session.append((day, grades, bars_of(con, day)))
    con.close()

    if with_grades < len(days):
        print()
        print("  " + "!" * 74)
        print(f"  {len(days) - with_grades} of {len(days)} sessions have NO "
              f"graded stocks. Every GRADED number")
        print(f"  below comes from {with_grades} session(s). The CONTROL "
              f"numbers use all {len(days)}.")
        print("  " + "!" * 74)

    times = [only_at] if only_at else list(SWEEP)

    # ---- THE SWEEP. ONE LINE PER ENTRY TIME. ----
    print()
    print("=" * 78)
    print("  WHEN CAN THIS BOT ACTUALLY TRADE?")
    print("=" * 78)
    print(f"  {'at':<7} {'tradable':>9} {'refused':>8} {'too close':>10}  |"
          f" {'GRADED n':>9} {'per tr':>8}  | {'CTRL n':>7} {'per tr':>8}")
    print("  " + "-" * 74)

    kept = {}
    for entry_at in times:
        rows, refused = measure(session, entry_at, plan)
        kept[entry_at] = (rows, refused)
        close = sum(1 for r in refused if "too close" in r["why"])
        graded = stats([r for r in rows if r["grade"]])
        control = stats([r for r in rows if not r["grade"]])
        g_n = graded["n"] if graded else 0
        g_per = f"{graded['per']:+,.0f}" if graded else "--"
        c_n = control["n"] if control else 0
        c_per = f"{control['per']:+,.0f}" if control else "--"
        star = "" if not graded or graded["n"] >= MIN_SAMPLE else " ?"
        print(f"  {entry_at:<7} {len(rows):>9,} {len(refused):>8,} "
              f"{close:>10,}  | {g_n:>9,}{star:<2} {g_per:>6}  | "
              f"{c_n:>7,} {c_per:>8}")

    print("  " + "-" * 74)
    print("  'too close' = the stop is nearer than "
          f"{MIN_STOP_DISTANCE_PCT}%, so there is not enough")
    print("  range yet to place one. That number falling as the clock")
    print("  moves is the whole point of this table.")
    print()
    print("  per tr is the ONLY money column worth reading. "
          f"MAX_OPEN_POSITIONS is 3,")
    print("  so a total across thousands of trades is arithmetic, not P&L.")
    print("  No charges, no slippage, no book limit.")
    print("=" * 78)

    # Full detail for a single requested time, or for the sweep's best.
    if only_at:
        rows, refused = kept[only_at]
        detail(rows, refused, only_at, limits)
    else:
        best = max(times, key=lambda t: len(kept[t][0]))
        detail(kept[best][0], kept[best][1], best, limits)
        print()
        print(f"  Detail above is {best} -- the time that let the bot place")
        print("  the most trades. Use --at HH:MM for any other.")

    if csv_path:
        pick = only_at or max(times, key=lambda t: len(kept[t][0]))
        rows = kept[pick][0]
        target = (csv_path if os.path.isabs(csv_path)
                  else os.path.join(ROOT, csv_path))
        parent = os.path.dirname(target)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=[
                "date", "symbol", "grade", "entry", "stop", "stop_pct",
                "target", "qty", "first", "pnl_rs", "high_pct"])
            writer.writeheader()
            writer.writerows(rows)
        print(f"\n  Written: {target}  ({len(rows)} row(s) at {pick})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
