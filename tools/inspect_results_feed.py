"""
==========================================================
Inspect the results feed -- what is NSE actually sending?
==========================================================

    py tools/inspect_results_feed.py

Prints the RAW field names and a couple of raw rows from NSE's filed-
results endpoint, without interpreting anything.

Why this exists: on the first live run the results calendar stored 296
scheduled dates but ZERO broadcast timestamps, so the earnings pulse had
nothing to work with. That could mean one of two very different things:

  a) NSE genuinely returned no past filings, or
  b) it returned plenty, and our field names are wrong.

Those need opposite fixes, and "0 stored" looks identical either way.
This shows which it is in one command -- paste the output back and the
parser can be corrected in minutes rather than guessed at.

Author : H&M Opportunity Trader
==========================================================
"""

import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logger import decision, warn  # noqa: E402


def main():
    decision("=" * 62)
    decision("  RAW RESULTS FEED")
    decision("=" * 62)

    try:
        from nse import NSE
        with NSE(download_folder="data") as n:
            rows = n.financial_results(
                segment="equities", period="quarterly",
                from_date=datetime.now() - timedelta(days=400),
                to_date=datetime.now()) or []
    except Exception as exc:
        warn(f"  Fetch failed: {exc}")
        return 1

    decision(f"  Rows returned: {len(rows)}")
    if not rows:
        decision("  NSE returned nothing for the last 400 days. Either the "
                 "endpoint moved or it needs different parameters -- this "
                 "is NOT a parsing problem.")
        return 0

    first = rows[0] if isinstance(rows[0], dict) else {}
    decision(f"  Field names ({len(first)}):")
    for key in sorted(first):
        value = str(first[key])
        decision(f"      {key:<28} = {value[:56]}")

    decision("")
    decision("  Two more rows, raw:")
    for row in rows[1:3]:
        decision("      " + json.dumps(row, default=str)[:400])

    decision("")
    decision("  We are looking for: a SYMBOL field, and a field holding "
             "the broadcast/filing timestamp WITH a time of day (not just "
             "a date). If every date field is date-only, the earnings "
             "pulse cannot be built from this endpoint and we need "
             "another source.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
