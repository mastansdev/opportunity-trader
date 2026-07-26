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


def _show(title, rows, want):
    decision("")
    decision("-" * 62)
    decision(f"  {title}: {len(rows)} rows")
    decision("-" * 62)
    if not rows:
        decision("  (nothing returned)")
        return
    first = rows[0] if isinstance(rows[0], dict) else {}
    for key in sorted(first):
        decision(f"      {key:<24} = {str(first[key])[:52]}")
    decision(f"  Looking for: {want}")


def main():
    decision("=" * 62)
    decision("  RAW RESULTS FEEDS")
    decision("=" * 62)

    frm = datetime.now() - timedelta(days=30)
    to = datetime.now()

    try:
        from nse import NSE
    except Exception as exc:
        warn(f"  nse library unavailable: {exc}")
        return 1

    # 1. corporate announcements -- the feed we actually use
    try:
        with NSE(download_folder="data") as n:
            announcements = n.announcements(
                index="equities", from_date=frm, to_date=to) or []
    except Exception as exc:
        warn(f"  announcements fetch failed: {exc}")
        announcements = []
    _show("corporate-announcements (last 30 days)", announcements,
          "a SYMBOL, a subject mentioning 'results', and an_dt with a "
          "time of day")

    if announcements:
        results_rows = [
            r for r in announcements if isinstance(r, dict)
            and any(m in " ".join(str(r.get(k) or "") for k in
                                  ("desc", "attchmntText", "subject")).lower()
                    for m in ("result", "financial statement"))
        ]
        decision(f"  Of those, {len(results_rows)} look like results "
                 f"filings.")
        for row in results_rows[:5]:
            decision(f"      {str(row.get('symbol')):<14} "
                     f"{str(row.get('an_dt')):<22} "
                     f"{str(row.get('desc'))[:40]}")

    # 2. financial_results -- kept only to show WHY it is not used
    try:
        with NSE(download_folder="data") as n:
            filings = n.financial_results(
                segment="equities", period="quarterly",
                from_date=frm, to_date=to) or []
    except Exception as exc:
        warn(f"  financial_results fetch failed: {exc}")
        filings = []
    _show("financial_results (last 30 days) -- NOT used", filings,
          "reference only: this endpoint returns ~91 rows a YEAR, all "
          "late filings by delisted names")

    decision("")
    decision("  Paste this back if the pulse is still empty after a "
             "refresh.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
