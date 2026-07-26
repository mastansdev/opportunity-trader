"""
==========================================================
Calendar Report -- holidays, results, and what memory holds
==========================================================

    py tools/calendar_report.py              # everything
    py tools/calendar_report.py TCS INFY     # one or more symbols

Three questions, answered from stored data:

  1. When is the market shut?
  2. Who reports results, and when -- and at what TIME do they
     habitually report? (the earnings pulse)
  3. How much corporate activity does memory actually hold --
     results, dividends, splits, bonuses, buybacks, per symbol
     and across the universe?

Read-only. Refresh the underlying data with `py tools/refresh_calendars.py`
(the morning tool refreshes it too).

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn  # noqa: E402
from core.market_calendar import MarketCalendar  # noqa: E402
from core.results_calendar import ResultsCalendar  # noqa: E402
from core.stock_memory import StockMemory  # noqa: E402


def per_symbol(symbols):
    results = ResultsCalendar()
    memory = StockMemory()

    for symbol in symbols:
        decision("")
        decision(f"  {symbol}")
        decision("  " + "-" * 46)

        pulse = results.pulse(symbol)
        decision(f"    Earnings pulse : {pulse}")

        history = results.history_for(symbol)
        if history:
            decision(f"    Result events  : {len(history)}")
            for row in history[-6:]:
                at = row.get("broadcast_at")
                when = at.strftime("%H:%M") if at else "time unknown"
                decision(f"        {row['results_date']}  {when:<13}"
                         f"{(row.get('relating_to') or '')[:24]}")
        else:
            decision("    Result events  : none stored")

        counts = memory.counts_for(symbol)
        if counts:
            decision("    Corporate acts : "
                     + ", ".join(f"{k} x{v}" for k, v in
                                 sorted(counts.items())))
            for row in memory.history_for(symbol)[-6:]:
                decision(f"        {row['ex_date']}  {row['action_type']:<14}"
                         f"{(row.get('detail') or '')[:40]}")
        else:
            decision("    Corporate acts : none stored")
    return 0


def main():
    if len(sys.argv) > 1:
        return per_symbol([s.upper() for s in sys.argv[1:]])

    today = datetime.now().date()

    # ---- 1. Holidays --------------------------------------------
    calendar = MarketCalendar()
    decision("=" * 62)
    decision("  MARKET CALENDAR")
    decision("=" * 62)
    decision(f"  Holidays known   : {calendar.count()}")
    decision(f"  Today ({today})  : "
             + ("TRADING DAY" if calendar.is_trading_day(today)
                else f"CLOSED -- {calendar.reason(today)}"))
    decision(f"  Previous session : {calendar.previous_trading_day(today)}")
    decision(f"  Next session     : {calendar.next_trading_day(today)}")

    upcoming = calendar.upcoming(days=120)
    if upcoming:
        decision("  Next 120 days:")
        for day, desc in upcoming:
            gap = (day - today).days
            decision(f"      {day}  ({gap:>3}d)  {desc}")
    elif calendar.count() == 0:
        warn("  No holiday data. Run: py tools/refresh_calendars.py")

    # ---- 2. Results ---------------------------------------------
    results = ResultsCalendar()
    stats = results.stats()
    decision("")
    decision("=" * 62)
    decision("  RESULTS CALENDAR")
    decision("=" * 62)
    decision(f"  Events stored    : {stats['events']} "
             f"across {stats['symbols']} symbols")
    decision(f"  With a known TIME: {stats['with_time']} "
             f"(the earnings-pulse corpus)")

    soon = results.upcoming(days=14)
    if soon:
        decision(f"  Reporting in the next 14 days ({len(soon)}):")
        by_day = {}
        for row in soon:
            by_day.setdefault(row["results_date"], []).append(row["symbol"])
        for day in sorted(by_day):
            names = sorted(by_day[day])
            decision(f"      {day}  ({len(names):>3})  "
                     + ", ".join(names[:10])
                     + ("..." if len(names) > 10 else ""))
    else:
        warn("  No forthcoming results stored. Run: "
             "py tools/refresh_calendars.py")

    # Who do we actually know the timing of?
    timed = [(s, results.typical_time(s))
             for s in {r["symbol"] for r in results.upcoming(days=14)}]
    timed = [(s, t) for s, t in timed if t]
    if timed:
        reliable = [(s, t) for s, t in timed if t["reliable"]]
        vague = [(s, t) for s, t in timed if not t["reliable"]]

        decision(f"  RELIABLE reporting times ({len(reliable)} of "
                 f"{len(timed)} with history):")
        for symbol, t in sorted(reliable,
                                key=lambda kv: kv[1]["spread_minutes"])[:15]:
            decision(f"      {symbol:<14} ~{t['hhmm']}  "
                     f"({t['samples']} past, spread {t['spread_minutes']}min)")
        if not reliable:
            decision("      (none yet -- needs 3+ results within a "
                     "2-hour spread)")
        if vague:
            decision(f"  No usable pattern ({len(vague)}): "
                     + ", ".join(s for s, _ in sorted(
                         vague, key=lambda kv: -kv[1]["spread_minutes"])[:12]))
            decision("  (these file at genuinely inconsistent hours -- "
                     "the median is arithmetically true and useless)")
    elif stats["with_time"] == 0:
        decision("  No timing history yet -- it accumulates one quarter at "
                 "a time. Nothing to do but keep running the morning tool.")

    # ---- 3. Memory ----------------------------------------------
    memory = StockMemory()
    counts = memory.event_counts()
    first, last = memory.date_range()
    decision("")
    decision("=" * 62)
    decision("  STOCK MEMORY  (corporate actions)")
    decision("=" * 62)
    decision(f"  Facts stored     : {memory.count()}"
             + (f"   ({first} -> {last})" if first else ""))
    if counts:
        for action, n in counts.items():
            decision(f"      {action:<16} {n:>5}")
    else:
        warn("  Memory is empty. Run: py tools/refresh_calendars.py")

    busiest = memory.busiest_symbols(limit=10)
    if busiest:
        decision("  Most corporate activity on record: "
                 + ", ".join(f"{s}({n})" for s, n in busiest))
        decision("  (a name far above its peers usually means a duplicate "
                 "feed, not a busy company -- worth a look)")

    decision("")
    decision("  Per-symbol detail:  py tools/calendar_report.py TCS INFY")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
