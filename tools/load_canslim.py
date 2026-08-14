"""
Load the CANSLIM watchlist export into the event store -- layer 06.

    py tools/load_canslim.py                 # dry run
    py tools/load_canslim.py --apply
    py tools/load_canslim.py --apply --file data/opportunities_watchlist.txt

WHERE THE FILE COMES FROM
-------------------------
earningspulse.ai/opportunities/earnings, the "TV Watchlist" download.
Save it to data/opportunities_watchlist.txt and run this.

It is the only source in the whole system with NO OCR in the path. The
tiers arrive as plain text, so a company can never be filed under the
wrong grade because a screenshot was blurry.

WHY IT IS WORTH THE NIGHTLY CLICK
---------------------------------
It is the sixth and last read in Earnings Pulse's own chain, and it is
the one that disagrees most with the others. On 1 August, twelve of
thirteen names had a different CANSLIM tier from their Pulse grade --
SHADOWFAX, AETHER and DIVISLAB were all EXCEPTIONAL on a GOOD quarter,
because CANSLIM adds the technical lens the Pulse grade does not have.

    "We don't tell you whether to buy, hold, or skip a name."
                                    -- their own page

Neither does this. It stores a tier.

Author : H&M Opportunity Trader
"""

import argparse
import os
import sys
from datetime import date, datetime

sys.path.insert(0, ".")

from core.canslim import (DEFAULT_PATH, counts, headline_for,  # noqa: E402
                          parse_watchlist, with_rarity)
from core.master_loader import MasterLoader                    # noqa: E402
from core.stock_events import StockEvents                      # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=DEFAULT_PATH)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--on", default=None,
                    help="the filing date the list describes, YYYY-MM-DD. "
                         "Defaults to the file's own modified date, because "
                         "the export does not carry one.")
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(f"No file at {args.file}.")
        print("Download 'TV Watchlist' from "
              "earningspulse.ai/opportunities/earnings and save it there.")
        return

    when = (date.fromisoformat(args.on) if args.on
            else datetime.fromtimestamp(os.path.getmtime(args.file)).date())

    loader = MasterLoader()
    loader.load()
    known = {str(s).upper() for s in loader.all_symbols(include_blocked=True)}

    text = open(args.file, encoding="utf-8").read()
    every = with_rarity(parse_watchlist(text))
    rows = [r for r in every if r["symbol"] in known]

    print(f"file      : {args.file}")
    print(f"describes : {when}")
    print(f"tiers     : {counts(every)}")
    print(f"names     : {len(every)} in the file, "
          f"{len(rows)} in your tradeable universe")
    print()
    for row in every:
        if row["tier"] == "EXCEPTIONAL":
            mark = "" if row["symbol"] in known else "   (not tradeable)"
            print(f"   {row['symbol']:12} {headline_for(row, on=when)}{mark}")
    print()

    if not args.apply:
        print("DRY RUN. Nothing written. Re-run with --apply.")
        return

    store = StockEvents("data/stock_events.db")
    at = f"{when.isoformat()}T23:00:00"
    written = 0
    for row in rows:
        head = headline_for(row, on=when)
        if not head:
            continue
        try:
            store.remember(symbol=row["symbol"], at=at, kind="SETUP",
                           scope="STOCK", headline=head, grade=None,
                           value_cr=None, counterparty=None,
                           source="CANSLIM", url=None, from_image=False)
            written += 1
        except Exception as exc:                           # noqa: BLE001
            print(f"   {row['symbol']}: {exc}")
    print(f"DONE. {written} SETUP events stored.")


if __name__ == "__main__":
    main()
