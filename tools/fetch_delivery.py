"""
==========================================================
py tools/fetch_delivery.py -- pull NSE's delivery figures
==========================================================

    "DELIVER % - YES"
                                -- operator, 8 August 2026

The bot already downloads NSE's UDiFF bhavcopy every night. Checked
column by column on the real file: it carries OHLC, volume, turnover
and trade count, and NO delivery figures. The Rsvd1-4 columns are
empty.

Delivery lives in a separate published file, sec_bhavdata_full, on the
same archive host the bot already reaches for index constituents.

    py tools/fetch_delivery.py               yesterday and today
    py tools/fetch_delivery.py --days 30     backfill a month
    py tools/fetch_delivery.py --status      what is already stored

WHY BACKFILL MATTERS MORE HERE THAN ELSEWHERE
---------------------------------------------
The signal is not a number, it is a RUN: three to five sessions of
above-average delivery in a tight price range on falling volume. With
one day stored, core/delivery.py can say nothing at all and correctly
returns None. It needs about ten sessions before the first reading
appears, so the first thing to do is fetch the last month.

Weekends and holidays simply have no file. That is not an error and
this does not treat it as one.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from core import delivery

    if "--status" in sys.argv:
        got = delivery.coverage()
        print("=" * 62)
        print("  DELIVERY STORE")
        print("=" * 62)
        print(f"  rows     {got['rows']:,}")
        print(f"  symbols  {got['symbols']:,}")
        print(f"  from     {got['from']}")
        print(f"  to       {got['to']}")
        if got["rows"]:
            for symbol in ("HINDALCO", "RELIANCE", "MOTHERSON"):
                reading = delivery.reading(symbol)
                print(f"\n  {symbol}: "
                      f"{reading['text'] if reading else 'not enough history'}")
        print("=" * 62)
        return 0

    days = 2
    if "--days" in sys.argv:
        try:
            days = int(sys.argv[sys.argv.index("--days") + 1])
        except (IndexError, ValueError):
            print("--days needs a number")
            return 1

    print("=" * 62)
    print(f"  FETCHING DELIVERY DATA -- last {days} calendar day(s)")
    print("=" * 62)

    ok = skipped = 0
    today = date.today()
    for back in range(days):
        when = today - timedelta(days=back)
        if when.weekday() >= 5:            # Sat / Sun -- no session
            continue
        got = delivery.ingest(when)
        if got.get("ok"):
            ok += 1
            print(f"  [ OK ] {got['date']}  {got['rows']:,} stocks")
        else:
            skipped += 1
            print(f"  [ -- ] {got['date']}  {got['why']}")

    print("-" * 62)
    print(f"  {ok} session(s) stored, {skipped} unavailable")
    coverage = delivery.coverage()
    print(f"  store now: {coverage['rows']:,} rows, "
          f"{coverage['symbols']:,} symbols, "
          f"{coverage['from']} to {coverage['to']}")
    if ok and coverage["rows"] < 5000:
        print("\n  Thin. The pattern needs a RUN of sessions -- "
              "try --days 30.")
    print("=" * 62)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
