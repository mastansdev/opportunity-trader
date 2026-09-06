"""
==========================================================
Read NSE's own size list into the store
==========================================================

    py tools/refresh_company_size.py

Reads data/LIST_NSE.xlsx -- NSE's SEBI-LODR filing, his file, already
on disk -- and writes data/company_size.json: total market cap, NSE's
own rank, and the SEBI band that rank makes.

NO NETWORK. Nothing here touches NSE's website, so there is nothing to
throttle and nothing to be blocked by. Re-run it only when a newer
LIST_NSE.xlsx is dropped into data/ -- NSE publishes it twice a year.

This decides nothing. See core/company_size.py for why it exists and
why it is kept apart from the free-float store the order gate reads.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sys

# Run as `py tools/refresh_company_size.py` and Python puts tools/ on
# the path, not the project root -- so `from core import ...` fails
# with ModuleNotFoundError. Same fix, and the same shape, as
# tools/refresh_market_cap.py: anchored on THIS file rather than on
# the working directory, so it works from anywhere.
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from core import company_size                              # noqa: E402


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    source = argv[0] if argv else None

    before = company_size.status()
    written = company_size.refresh(source=source)
    if not written:
        print("Nothing written. The reason is printed above.")
        return 1

    after = company_size.status()
    print()
    print(f"  source        {after['source']}")
    print(f"  read at       {after['at']}")
    print(f"  companies     {after['symbols']:,}"
          + (f"  (was {before['symbols']:,})" if before["available"] else ""))
    print(f"  large cap     {after['large']:,}   rank 1-100")
    print(f"  mid cap       {after['mid']:,}   rank 101-250")
    print(f"  small cap     {after['small']:,}   rank 251 and on")
    print()

    # What it can actually say about HIS universe, which is the only
    # coverage number worth printing -- the list holds every listed
    # company, most of which he does not trade.
    try:
        import csv
        with open("data/master_stocks.csv", newline="",
                  encoding="utf-8", errors="ignore") as handle:
            universe = [str(row.get("SYMBOL") or "").strip().upper()
                        for row in csv.DictReader(handle)]
        universe = [s for s in universe if s]
        known = company_size.bands_for(universe)
        counts = {"LARGE": 0, "MID": 0, "SMALL": 0}
        for band in known.values():
            counts[band] = counts.get(band, 0) + 1
        print(f"  of the {len(universe):,} symbols the bot follows, "
              f"{len(known):,} have a size "
              f"({len(known) * 100 // max(1, len(universe))}%):")
        print(f"      large {counts['LARGE']:,}   "
              f"mid {counts['MID']:,}   small {counts['SMALL']:,}")
        print(f"      no size on file: {len(universe) - len(known):,} "
              f"-- mostly listed after the filing period")
    except Exception as exc:                               # noqa: BLE001
        print(f"  (could not read the universe file: {exc})")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
