"""
One-time reconciliation: compare data/master_stocks.csv
against Dhan's LIVE scrip master. Run this locally
(needs real network -- this will not work from a
restricted sandbox) before trusting the file for a live
session, and again periodically -- symbols get delisted,
security IDs occasionally change.

Usage: python tools/verify_master_database.py
"""

import os
import sys
from datetime import datetime

sys.path.insert(0, ".")

from core.master_loader import MasterLoader
from core.instrument_master import InstrumentMaster, COMPACT_CSV_URL

# Read every morning by tools/preflight.py.
PROOF_PATH = os.path.join("data", "scrip_verified.json")


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

    # WRITE THE PROOF. Until 2026-07-29 this script only printed its
    # findings, so nothing downstream could tell whether it had ever
    # been run. tools/preflight.py now reads this file every morning
    # and FAILS in LIVE mode if it is missing, stale, or records a
    # mismatch -- because "someone could run the check by hand" is not
    # a control when the consequence is buying the wrong company with
    # real money.
    import json
    proof = {
        "verified_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "checked": count,
        "source": COMPACT_CSV_URL,
        "mismatches": [f"{s}: master {e}, Dhan {l}"
                       for s, e, l in mismatches],
        "not_found": list(not_found),
        "clean": not mismatches,
    }
    try:
        os.makedirs("data", exist_ok=True)
        with open(PROOF_PATH, "w", encoding="utf-8") as fh:
            json.dump(proof, fh, indent=1)
        print(f"\nProof written to {PROOF_PATH} -- preflight reads this.")
    except OSError as exc:
        print(f"\nCould not write {PROOF_PATH}: {exc}")

    if not not_found and not mismatches:
        print(f"All {count} symbols verified clean against live Dhan data.")
    else:
        print(
            "\nFix the rows above in master_database.xlsx / "
            "data/master_stocks.csv before trusting this file live."
        )
        if mismatches:
            print("A MISMATCH MEANS THE BOT WOULD BUY A DIFFERENT COMPANY "
                  "THAN THE ONE IT CHOSE. Preflight will now refuse to pass "
                  "in LIVE mode until this is clean.")
            sys.exit(1)


if __name__ == "__main__":
    main()
