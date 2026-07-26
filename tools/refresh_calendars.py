"""
==========================================================
Refresh calendars -- holidays, results, corporate actions
==========================================================

    py tools/refresh_calendars.py

Fetches and stores the three "what does the bot KNOW" datasets:

  1. NSE trading holidays          -> data/market_calendar.db
  2. Results dates + past filing
     timestamps (earnings pulse)   -> data/results_calendar.db
  3. Corporate actions
     (dividend/split/bonus/...)    -> the stock memory

This is a SEPARATE command from `morning_universe.py` on purpose. That
one rewrites data/master_stocks.csv, and you should not have to touch
the tradeable universe just to load a holiday list. The morning tool
calls the same refreshers, so running it also keeps these current --
this is simply the narrow version, safe to run at any time.

Nothing here is on the trading path and every fetch fails open: an
unreachable NSE means the bot learns nothing new, not that anything
breaks.

Read the result with:  py tools/calendar_report.py

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn  # noqa: E402


def main():
    decision("=" * 62)
    decision("  REFRESH CALENDARS")
    decision("=" * 62)

    # Which symbols we care about -- used to discard the ~1,700 NSE
    # names that are not in our universe, so the stores stay relevant.
    known = None
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        known = set(loader.all_symbols(include_blocked=True))
        decision(f"  Universe: {len(known)} symbols")
    except Exception as exc:
        warn(f"  Could not load the master list ({exc}) -- storing "
             f"everything NSE returns instead of just our universe.")

    # Count what is actually STORED, before and after. "It didn't throw"
    # is not the same as "it worked" -- every fetch in here fails open,
    # so a run with no network completes happily having learned nothing.
    # Reporting that as success would be a lie, and this is exactly the
    # kind of quiet lie that costs a trading morning.
    holidays = results = facts = 0

    # ---- 1. Trading holidays ------------------------------------
    try:
        from core.market_calendar import refresh as refresh_calendar
        cal = refresh_calendar()
        holidays = cal.count()
        today = datetime.now().date()
        decision(f"  Today {today}: "
                 + ("trading day" if cal.is_trading_day(today)
                    else f"CLOSED ({cal.reason(today)})"))
        decision(f"  Previous session {cal.previous_trading_day(today)}, "
                 f"next {cal.next_trading_day(today)}")
    except Exception as exc:
        warn(f"  Holiday calendar failed: {exc}")

    # ---- 2. Results + earnings pulse ----------------------------
    try:
        from core.results_calendar import refresh as refresh_results
        results = refresh_results(known_symbols=known).stats()["events"]
    except Exception as exc:
        warn(f"  Results calendar failed: {exc}")

    # ---- 3. Corporate actions -----------------------------------
    try:
        from core.corporate_actions import refresh as refresh_actions
        refresh_actions(known_symbols=known)
        from core.stock_memory import default_memory
        facts = default_memory().count()
    except Exception as exc:
        warn(f"  Corporate actions failed: {exc}")

    decision("-" * 62)
    decision(f"  Holidays known    : {holidays}")
    decision(f"  Result events     : {results}")
    decision(f"  Corporate actions : {facts}")

    if not (results or facts):
        warn("  NOTHING was fetched from NSE/BSE. The stores are empty or "
             "unchanged -- this run learned nothing. Check the network: "
             "NSE blocks some connections (VPNs, proxies, data-centre "
             "IPs) outright. Nothing is broken; the bot simply has no "
             "results or corporate-action data to work with.")
        return 1

    decision("  Now run: py tools/calendar_report.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
