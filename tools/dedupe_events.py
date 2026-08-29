"""
==========================================================
Collapse repeated news in data/stock_events.db
==========================================================
    py tools/dedupe_events.py            what WOULD go, nothing removed
    py tools/dedupe_events.py --apply    remove them (backs up first)

    "pls check incase of duplicate info being taken as multiple times
     as different channels are being sourced"
    "chip should show stories not repeats. & complete the clean up of
     events till date"                   -- operator, 29 August 2026

WHAT A DUPLICATE IS HERE
------------------------
The same announcement reaching us twice, because one channel reposts
another's card. ATHERENERG, 28 August:

    08:15  "To buy additional stake in Ather Energy for 1,758 cr
            ... phe 4 y NOW IN|"                    (OCR'd, noisy)
    09:01  "HERO MOTOCORP: CO TO ACQUIRE ADDITIONAL STAKE IN ATHER
            ENERGY FOR UP TO 1,758 CRORE"

Four shared words out of eight -- no text threshold calls those the
same, and a person reads them as one instantly. The RUPEE FIGURE is
what identifies the story, and it is also what keeps the 26 August
event (Rs 960cr) apart from this one. See StockEvents._same_story().

WHAT IS KEPT
------------
The EARLIEST of each group, per stock per day. Earliest is also the
fastest source, which is the one worth measuring lag against.

Never across days: two identical-looking headlines on different
sessions may be a story that genuinely recurred, and merging them
would hide exactly the multi-day run this work exists to surface.
"""

import argparse
import os
import shutil
import sqlite3
import sys
import time
from collections import defaultdict

sys.path.insert(0, ".")

from core.logger import decision, warn          # noqa: E402
from core.stock_events import StockEvents       # noqa: E402

DB = os.path.join("data", "stock_events.db")
KINDS = ("NEWS", "ORDER", "RESULT", "CONCALL")


def find(db_path=DB):
    """Groups of rows that are the same story. Returns [(keep, [drop])]."""
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT id, symbol, at, kind, headline, source, value_cr, "
        "url, grade, ai_reason FROM events "
        "WHERE symbol IS NOT NULL AND symbol <> '' "
        f"AND kind IN ({','.join('?' * len(KINDS))}) "
        "ORDER BY at", KINDS).fetchall()
    con.close()

    by_day = defaultdict(list)
    for row in rows:
        by_day[(row["symbol"], str(row["at"])[:10])].append(row)

    groups = []
    for _, items in sorted(by_day.items()):
        kept = []
        drops = defaultdict(list)
        for row in items:
            match = next(
                (k for k in kept
                 if StockEvents._same_story(row["headline"], k["headline"])),
                None)
            # ---- A REPEAT THAT ADDS A NUMBER IS NOT A REPEAT ----
            #      29 August 2026.
            #
            # Keeping the EARLIEST loses the richer telling. Of 1,093
            # rows the first pass would have removed, 54 were like
            # these:
            #
            #   KEEP  "ADVAIT ENERGY e Revives turnkey contract for..."
            #   DROP  "ADVAIT ENERGY TRANSITIONS: CO SECURES 2134.62
            #          CRORE TURNKEY ORDER"
            #
            #   KEEP  "Apollo Micro Systems secures INR 2133.91M..."
            #   DROP  "APOLLO MICRO SYSTEMS: CO WINS ORDER WORTH
            #          RUPEES 213 CR FROM DRDO"
            #
            # Same announcement, but the row being deleted is the one
            # carrying the figure -- and the figure is what
            # core/why_moving.py weighs and what tells a Rs 51cr order
            # from a Rs 2,134cr one. Deleting it to save a row is a bad
            # trade.
            #
            # So a duplicate is only dropped when it names NO amount
            # the keeper is missing. Anything that adds a number stays.
            if match is not None:
                new_money = (StockEvents._amounts(row["headline"])
                             - StockEvents._amounts(match["headline"]))
                # ---- value_cr IS PARSED, NOT READ OFF THE TEXT ----
                #      29 August 2026.
                #
                # The first --apply removed 8 rows whose value_cr no
                # survivor had. "NBCC secures USD 75M Seychelles
                # housing project" names no rupee figure at all, yet
                # carried value_cr=660.0 from the parser -- so the
                # headline test could not see what was being lost.
                # They were restored from the backup and the rule
                # widened. A field that took work to extract is not
                # recoverable by re-reading the sentence.
                keeps_value = (row["value_cr"] is not None
                               and match["value_cr"] is None)
                if new_money or keeps_value:
                    match = None        # it adds something -- keep it
            if match is None:
                kept.append(row)
            else:
                drops[match["id"]].append(row)
        for keeper in kept:
            if drops.get(keeper["id"]):
                groups.append((keeper, drops[keeper["id"]]))
    return groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true",
                        help="actually remove them (a backup is written first)")
    parser.add_argument("--show", type=int, default=8,
                        help="how many groups to print")
    args = parser.parse_args()

    groups = find()
    total = sum(len(d) for _, d in groups)
    con = sqlite3.connect(DB)
    before = con.execute("SELECT count(*) FROM events").fetchone()[0]
    con.close()

    decision("=" * 62)
    decision("  REPEATED NEWS IN data/stock_events.db")
    decision("=" * 62)
    decision(f"  events on file      : {before:,}")
    decision(f"  groups with repeats : {len(groups):,}")
    decision(f"  rows that would go  : {total:,}")
    decision("-" * 62)

    for keeper, drops in groups[:args.show]:
        decision(f"  {keeper['symbol']}  {str(keeper['at'])[:16]}")
        decision(f"    KEEP  [{str(keeper['source'])[:16]:<16}] "
                 f"{str(keeper['headline'])[:56]}")
        for row in drops:
            decision(f"    drop  [{str(row['source'])[:16]:<16}] "
                     f"{str(row['headline'])[:56]}")

    if not args.apply:
        decision("-" * 62)
        decision("  Nothing removed. Re-run with --apply to remove them.")
        return 0

    if not total:
        decision("  Nothing to remove.")
        return 0

    backup = f"{DB}.{time.strftime('%Y%m%d-%H%M%S')}.bak"
    shutil.copy2(DB, backup)
    decision(f"  backup written      : {backup}")

    ids = [row["id"] for _, drops in groups for row in drops]
    con = sqlite3.connect(DB)
    con.executemany("DELETE FROM events WHERE id = ?",
                    [(i,) for i in ids])
    con.commit()
    after = con.execute("SELECT count(*) FROM events").fetchone()[0]
    con.close()
    decision(f"  removed             : {before - after:,}")
    decision(f"  events now          : {after:,}")
    if before - after != total:
        warn(f"  expected to remove {total}, removed {before - after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
