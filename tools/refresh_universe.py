"""
Pre-market universe review — proposes additions and removals.

Downloads NSE's daily bhavcopy and compares it against
data/master_stocks.csv, then writes data/universe_review.csv with:

    ADD     — qualifies but we don't have it (new listings)
    REMOVE  — we have it but it no longer qualifies (T2T, illiquid,
              too cheap, too expensive)
    CHECK   — in our list but absent from the bhavcopy entirely
              (delisted / suspended / renamed)

**It never edits master_stocks.csv.** You review the proposal and apply
what you agree with.

Run:  py tools/refresh_universe.py            (yesterday's bhavcopy)
      py tools/refresh_universe.py 2026-07-24 (a specific trading day)
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn
from core.master_loader import MasterLoader
from core.universe_builder import (
    MAX_PRICE, MIN_PRICE, MIN_TURNOVER_RS,
    classify, fetch_bhavcopy, summarise, write_review,
)


def main(date=None):
    loader = MasterLoader()
    loader.load()
    current = set(loader.all_symbols())
    decision(f"[UNIVERSE] Current universe: {len(current)} symbols.")
    decision(f"[UNIVERSE] Rules: series EQ only, "
             f"Rs {MIN_PRICE:.0f}-{MAX_PRICE:,.0f}, "
             f"turnover >= Rs {MIN_TURNOVER_RS/1e7:.0f}cr/day.")

    # Bhavcopy is published after the close, so default to the previous
    # day; walk back over weekends/holidays.
    when = date or (datetime.now() - timedelta(days=1))
    rows = []
    for back in range(0, 6):
        attempt = when - timedelta(days=back)
        rows = fetch_bhavcopy(attempt)
        if rows:
            decision(f"[UNIVERSE] Using bhavcopy for {attempt:%Y-%m-%d} "
                     f"({len(rows)} rows).")
            break

    if not rows:
        warn("[UNIVERSE] No bhavcopy could be fetched. NSE may be blocking "
             "this machine, or these were all non-trading days. Nothing "
             "was changed.")
        return 1

    result = classify(rows, current)
    summarise(result)
    path = write_review(result)
    decision(f"\n  Proposal written to: {path}")
    decision("  Review it, then edit data/master_stocks.csv yourself.")
    decision("  NOTHING has been changed automatically.")
    return 0


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    d = datetime.strptime(arg, "%Y-%m-%d") if arg else None
    sys.exit(main(d))
