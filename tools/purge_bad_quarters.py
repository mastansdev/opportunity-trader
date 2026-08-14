"""
==========================================================
A wrong number is worse than a missing one
==========================================================
    py tools/purge_bad_quarters.py            look, delete nothing
    py tools/purge_bad_quarters.py --apply    remove them

WHAT WAS FOUND
--------------
1 August 2026. After 200 results PDFs were fetched and parsed, an audit
of the whole store turned up 21 rows in 1,685 where the stored sales
figure disagrees with the company's OWN history by twenty times or
more:

    BAJFINANCE  Jun-26  sales     12.00   own median   8,308.97
    REDINGTON   Jun-26  sales     19.59   own median   6,400.64
    TORNTPHARM  Mar-26  sales      1.00   own median   2,599.00
    VEDL        Jun-25  sales     24.61   own median  15,754.00
    AMBUJACEM   Jun-25  sales      6.15   own median   6,116.49

Bajaj Finance did not do twelve crore of sales. Nineteen of the
twenty-one came from the PDF parser reading the wrong column of a
results table; two came from BSE's own snapshot.

WHY IT MATTERS MORE THAN A FAILED PARSE
---------------------------------------
The same run failed to read 108 filings, and that is the SAFE outcome:
a missing quarter leaves the panel labelled with the older quarter's
name, which the operator can see. A wrong one produces a confident
grade -- "STRONG: sales +12,000% QoQ" -- off arithmetic that is
nonsense, and nothing on screen says so.

Two of the twenty-one are Jun-26. Those are live.

WHAT THIS DELETES, AND WHAT IT WILL NOT
---------------------------------------
Only rows where the company has at least three other quarters to be
compared against, and where this one is 20x or more away from their
median. Twenty is deliberately loose: a genuine doubling, a merger,
a fourfold jump on a new plant all survive. The real cases were 327x
to 2,599x.

It never edits a figure. It removes the row, so the store falls back
to the previous quarter -- which is the state the bot handles
correctly and labels honestly.

core/quarterly_results.remember() now refuses these at the door, so
this is a one-off clean-up of what landed before that guard existed.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import statistics
import sys
from collections import defaultdict

sys.path.insert(0, ".")

from core.logger import decision, warn                    # noqa: E402
from core.quarterly_results import QuarterlyResults       # noqa: E402

DB = os.path.join("data", "quarterly_results.db")


def suspects(db_path=DB,
             ratio=QuarterlyResults.SALES_SANITY_RATIO,
             min_history=QuarterlyResults.SALES_SANITY_MIN_HISTORY):
    """Every row whose sales cannot be reconciled with its own company."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, symbol, period_end, period_label, sales, pat, source "
        "FROM quarterly_results WHERE sales IS NOT NULL "
        "ORDER BY symbol, period_end").fetchall()
    conn.close()

    by_symbol = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)

    out = []
    for symbol, group in by_symbol.items():
        values = [float(r["sales"]) for r in group
                  if r["sales"] and float(r["sales"]) > 0]
        if len(values) < min_history:
            continue
        median = statistics.median(values)
        if median <= 0:
            continue
        for row in group:
            sales = float(row["sales"] or 0)
            if sales <= 0:
                continue
            off = max(sales / median, median / sales)
            if off >= ratio:
                out.append((off, dict(row), median))
    out.sort(reverse=True, key=lambda x: x[0])
    return out


def main(apply=False):
    if not os.path.exists(DB):
        warn(f"No {DB}. Nothing to do.")
        return 1
    found = suspects()
    total = sqlite3.connect(DB).execute(
        "SELECT COUNT(*) FROM quarterly_results").fetchone()[0]

    decision("=" * 78)
    decision("  QUARTERS THAT DISAGREE WITH THEIR OWN COMPANY")
    decision("=" * 78)
    decision("")
    decision(f"  {len(found)} rows of {total}")
    decision("")
    if not found:
        decision("  Nothing to remove.")
        return 0

    decision(f"  {'SYMBOL':12s} {'QUARTER':9s} {'STORED':>12s} "
             f"{'OWN MEDIAN':>13s} {'OFF BY':>8s}  source")
    decision("  " + "-" * 74)
    live = 0
    for off, row, median in found:
        if str(row["period_end"]) >= "2026-06-01":
            live += 1
        decision(f"  {row['symbol']:12s} {str(row['period_label'] or ''):9s} "
                 f"{float(row['sales']):12,.2f} {median:13,.2f} "
                 f"{off:7,.0f}x  {row['source']}")
    decision("")
    if live:
        decision(f"  {live} of these are the CURRENT quarter. Those are live "
                 f"on the panel now.")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing removed. Re-run with --apply.")
        decision("  The row is deleted, never edited: the store then falls")
        decision("  back to the previous quarter, which the panel labels")
        decision("  honestly with that quarter's name.")
        return 0

    conn = sqlite3.connect(DB)
    for _off, row, _median in found:
        conn.execute("DELETE FROM quarterly_results WHERE id = ?",
                     (row["id"],))
    conn.commit()
    left = conn.execute("SELECT COUNT(*) FROM quarterly_results").fetchone()[0]
    conn.close()
    decision("")
    decision(f"  DONE. {total} -> {left} rows.")
    decision("  remember() now refuses these at the door, so this should")
    decision("  find nothing on a second run.")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
