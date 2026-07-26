"""
==========================================================
Deals Report -- bulk / block deals and short selling
==========================================================

    py tools/deals_report.py              # last 5 days, all three reports
    py tools/deals_report.py 15           # last 15 days

Writes data/deals.csv and prints the biggest net buyers and sellers.

WHAT EACH ONE IS
  BULK    one client trading >0.5% of a company's listed shares in a day
  BLOCK   a negotiated trade >= Rs 10cr, crossed in the 08:45-09:00
          window BEFORE the market opens
  SHORT   NSE's daily securities-wise short-selling report

READ IT WITH CARE. It is context, not a signal, and it does not gate any
trade:
  - it lands AFTER the close, so it is always at least a day stale
  - a block deal has a buyer AND a seller, so "net" is only really
    meaningful for bulk deals on the normal market
  - plenty of large deals are promoter exits or pledge unwinds, which
    mean the opposite of conviction

The one immediately practical use is the LIVE block window: a large
block crossed at a discount at 08:50 very often precedes a gap, and we
can see it before 09:15.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.deal_flow import (  # noqa: E402
    BLOCK, BULK, SHORT, fetch, fetch_todays_blocks, summarise_by_symbol,
)
from core.logger import decision, warn  # noqa: E402

OUT_CSV = os.path.join("data", "deals.csv")


def main():
    days = 5
    if len(sys.argv) > 1:
        try:
            days = int(sys.argv[1])
        except ValueError:
            warn(f"Ignoring '{sys.argv[1]}' -- expected a number of days.")

    decision("=" * 62)
    decision(f"  DEAL FLOW  (last {days} days)")
    decision("=" * 62)

    everything = []
    for kind in (BULK, BLOCK, SHORT):
        deals = fetch(kind, days_back=days)
        decision(f"  {kind:<14} {len(deals):>5} rows")
        everything.extend(deals)

    live_blocks = fetch_todays_blocks()
    if live_blocks:
        warn(f"  TODAY's block window ({len(live_blocks)}) -- these often "
             f"gap at the open:")
        for d in live_blocks[:10]:
            value = f"Rs {d['value']/1e7:.1f}cr" if d["value"] else "?"
            warn(f"      {d['symbol']:<14} {d['side']:<4} {value:>10}  "
                 f"{d['client'][:34]}")
        everything.extend(live_blocks)

    if not everything:
        warn("  Nothing returned. NSE may be unreachable, or there were "
             "genuinely no deals. Nothing depends on this.")
        return 0

    os.makedirs(os.path.dirname(OUT_CSV) or ".", exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(everything[0].keys()))
        w.writeheader()
        w.writerows(everything)

    summary = summarise_by_symbol([d for d in everything if d["kind"] == BULK])
    ranked = sorted(summary.items(), key=lambda kv: -(kv[1]["net_value"] or 0))

    if ranked:
        decision("-" * 62)
        decision("  Biggest NET BUYING (bulk deals only):")
        for symbol, rec in ranked[:10]:
            if rec["net_value"] <= 0:
                break
            decision(f"      {symbol:<14} +Rs {rec['net_value']/1e7:>7.1f}cr  "
                     f"{rec['deals']}d  {', '.join(rec['clients'][:2])[:40]}")
        decision("  Biggest NET SELLING:")
        for symbol, rec in list(reversed(ranked))[:10]:
            if rec["net_value"] >= 0:
                break
            decision(f"      {symbol:<14} -Rs {abs(rec['net_value'])/1e7:>7.1f}cr  "
                     f"{rec['deals']}d  {', '.join(rec['clients'][:2])[:40]}")

    decision("-" * 62)
    decision(f"  Written: {OUT_CSV}")
    decision("  Context only -- this does not gate any trade.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
