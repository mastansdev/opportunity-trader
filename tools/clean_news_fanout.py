"""
==========================================================
Clean the news store -- remove fan-out and routine filings
==========================================================

    py tools/clean_news_fanout.py            # show what would go
    py tools/clean_news_fanout.py --apply    # actually delete

Operator, 2026-07-26, looking at the news dashboard: "not at all correct
build news". He was right. The store held:

    12,831 rows from 1,034 real headlines  =  12.4 copies of each
    93% BROAD tier

The worst single case: ONE Vedanta trading-window notice stored against
264 symbols -- ABB, AMBER, ASHOKLEY, BAJAJ-AUTO and every other name
whose SECTOR / THEMES / COMMODITY_EXPOSURE happens to mention steel. It
said nothing whatsoever about ABB.

Two separate faults, both now fixed in news_bot/matching.py:

  1. FAN-OUT. A headline that NAMES a company was still being matched
     against every other company's sector keywords. If a headline names
     someone, it is about them.

  2. ROUTINE FILINGS. "Trading Window", "Appointment of Mr X",
     "Disclosure under Regulation 30", "Schedule of analyst call" --
     41% of all headlines, none of which move a price.

This tool removes the rows those faults already created. It is
DELIBERATELY SURGICAL rather than a wipe:

  - a routine-filing headline goes entirely
  - a BROAD row goes ONLY if the same headline also produced a COMPANY
    row (that is the fan-out signature)
  - genuine sector news that names nobody -- "Steel prices surge on
    import duty" -- is KEPT, because that is what BROAD is for
  - every COMPANY row is kept

Dry run by default. Nothing is deleted without --apply.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import delete, func, select  # noqa: E402

from core.logger import decision, warn  # noqa: E402
from news_bot.matching import is_routine_filing  # noqa: E402
from news_bot.news_store import NewsStore  # noqa: E402


def plan(store):
    """Work out which row ids to delete, and why. Pure read."""
    table = store.news_items
    with store.engine.begin() as conn:
        rows = conn.execute(select(
            table.c.id, table.c.title, table.c.tier, table.c.symbol
        )).all()

    by_title = defaultdict(list)
    for row in rows:
        by_title[row.title].append(row)

    routine_ids, fanout_ids = [], []
    routine_titles, fanout_titles = set(), set()

    for title, group in by_title.items():
        if is_routine_filing(str(title or "")):
            routine_ids.extend(r.id for r in group)
            routine_titles.add(title)
            continue
        # Fan-out signature: this headline named a company AND was also
        # matched broadly. The broad half is the noise.
        has_company = any(r.tier == "COMPANY" for r in group)
        if has_company:
            broad = [r for r in group if r.tier == "BROAD"]
            if broad:
                fanout_ids.extend(r.id for r in broad)
                fanout_titles.add(title)

    return dict(
        total=len(rows),
        titles=len(by_title),
        routine_ids=routine_ids,
        fanout_ids=fanout_ids,
        routine_titles=sorted(routine_titles),
        fanout_titles=sorted(fanout_titles),
        by_title=by_title,
    )


def main():
    apply_it = "--apply" in sys.argv
    store = NewsStore()
    p = plan(store)

    decision("=" * 62)
    decision("  NEWS STORE CLEANUP" + ("" if apply_it else "   (DRY RUN)"))
    decision("=" * 62)
    decision(f"  Rows now            : {p['total']:,}")
    decision(f"  Distinct headlines  : {p['titles']:,}"
             f"   ({p['total'] / max(p['titles'], 1):.1f} rows each)")
    decision("-" * 62)
    decision(f"  Routine filings     : {len(p['routine_ids']):,} rows "
             f"from {len(p['routine_titles'])} headlines")
    decision(f"  Sector fan-out      : {len(p['fanout_ids']):,} rows "
             f"from {len(p['fanout_titles'])} headlines")

    remaining = p["total"] - len(p["routine_ids"]) - len(p["fanout_ids"])
    decision(f"  WOULD REMAIN        : {remaining:,} rows")

    # Show the worst offender, so the scale is concrete rather than
    # abstract.
    if p["fanout_titles"]:
        worst = max(p["fanout_titles"],
                    key=lambda t: len(p["by_title"][t]))
        decision("-" * 62)
        decision(f"  Worst fan-out ({len(p['by_title'][worst])} symbols):")
        decision(f"      {str(worst)[:70]}")
        decision("      " + ", ".join(
            r.symbol for r in p["by_title"][worst][:14]) + " ...")

    if not apply_it:
        decision("-" * 62)
        decision("  Dry run -- nothing deleted.")
        decision("  Re-run with --apply to delete.")
        return 0

    ids = p["routine_ids"] + p["fanout_ids"]
    if not ids:
        decision("  Nothing to delete.")
        return 0

    table = store.news_items
    deleted = 0
    with store.engine.begin() as conn:
        # Chunked -- SQLite caps bound parameters, and this list can run
        # to five figures.
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            deleted += conn.execute(
                delete(table).where(table.c.id.in_(chunk))).rowcount or 0
        left = conn.execute(select(func.count()).select_from(table)).scalar()

    decision("-" * 62)
    decision(f"  Deleted {deleted:,} rows. {left:,} remain.")
    decision("  The engine will not recreate them -- matching.py now "
             "drops both classes at the source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
