"""
One-time reconciliation: compare data/master_stocks.csv
against Dhan's LIVE scrip master. Run this locally
(needs real network -- this will not work from a
restricted sandbox) before trusting the file for a live
session, and again periodically -- symbols get delisted,
security IDs occasionally change.

Usage: python tools/verify_master_database.py
"""

import sys

sys.path.insert(0, ".")

from core.master_loader import MasterLoader
from core.instrument_master import InstrumentMaster, COMPACT_CSV_URL


def main():
    loader = MasterLoader()
    count = loader.load()
    print(f"Master database: {count} rows loaded and structurally valid.")

    print(f"Fetching live Dhan scrip master from {COMPACT_CSV_URL} ...")
    im = InstrumentMaster()
    im.load()

    mismatches = []
    not_found = []

    for symbol in loader.all_symbols(include_blocked=True):
        expected_id = str(loader.security_id(symbol))
        live_id = im.resolve(symbol)

        if live_id is None:
            not_found.append(symbol)
        elif str(live_id) != expected_id:
            mismatches.append((symbol, expected_id, live_id))

    print()
    print(f"Checked {count} symbols against the live Dhan scrip master.")
    print(f"Not found on NSE (possibly delisted/renamed): {len(not_found)}")
    for symbol in not_found:
        print(f"  - {symbol}")

    print(f"Security ID mismatches: {len(mismatches)}")
    for symbol, expected, live in mismatches:
        print(f"  - {symbol}: master has {expected}, Dhan has {live}")

    if not not_found and not mismatches:
        print("\nAll 750 symbols verified clean against live Dhan data.")
    else:
        print(
            "\nFix the rows above in master_database.xlsx / "
            "data/master_stocks.csv before trusting this file live."
        )


if __name__ == "__main__":
    main()
