"""
==========================================================
py tools/apply_classifications.py  --  open the gate, safely
==========================================================

    "what? pls complete the master data its the key . without key where
     to land?"
                                -- operator, 8 August 2026

WHAT WAS ACTUALLY WRONG, 11 AUGUST
----------------------------------
193 stocks that trade every single day sat at SUBSCRIBE = NO with the
reason "new listing -- awaiting sector classification". They are not
new listings. ALLCARGO, BAJAJHIND, HMVL, ANDHRAPAP, UFO -- decades
old. They were locked out because one column was empty.

On the morning of 11 August that hid four graded gappers from the
board, including SPECIALITY, which the card graded EXCELLENT and which
gapped +5.9%. The bot could not see it at any price.

WHY THIS IS A SEPARATE FILE AND NOT A ONE-LINER
-----------------------------------------------
On 8 August I flipped 91 stocks to SUBSCRIBE = YES while their SECTOR
was still blank. core/master_loader.py refuses to load when a TRADEABLE
row has no sector -- correctly, because core/news_impact.py fans a
sector event out to every stock in that sector. The bot would not
start. I reverted it within minutes, but it should never have reached
him.

So this tool will not flip a single row until it has checked:

    1. the SECTOR is non-blank
    2. the SECTOR is one the master ALREADY uses -- no new vocabulary
       arrives by accident, because a sector of one is a fan-out of one
    3. the symbol really is in the master
    4. master_loader can still load the file afterwards

If any check fails the file is not written at all. A backup is taken
first regardless.

    py tools/apply_classifications.py            -- dry run, shows all
    py tools/apply_classifications.py --write    -- writes

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

MASTER = os.path.join("data", "master_stocks.csv")
FILLED = os.path.join("data", "_classified.csv")

# A sector that appears in the master exactly once is not a sector, it
# is a typo with a stock attached. New values must be deliberate.
ALLOW_NEW_SECTORS = False

# Every column core/master_loader.py demands on a TRADEABLE row. Two of
# nine is as unloadable as none of nine -- see the note in main().
FILL_COLUMNS = ["SECTOR", "INDUSTRY", "CORE BUSINESS", "BUSINESS_TYPE",
                "OWNERSHIP", "COMMODITY_EXPOSURE", "ECONOMIC_SENSITIVITY",
                "KEYWORDS", "THEMES"]


def _read_master():
    with open(MASTER, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader), reader.fieldnames


def _known_sectors(rows):
    return {(r.get("SECTOR") or "").strip().upper()
            for r in rows if (r.get("SECTOR") or "").strip()}


def main(write=False):
    rows, columns = _read_master()
    known = _known_sectors(rows)
    by_symbol = {r["SYMBOL"].strip().upper(): r for r in rows}

    if not os.path.exists(FILLED):
        print(f"\n  {FILLED} does not exist. Nothing to apply.\n")
        return 1

    with open(FILLED, encoding="utf-8-sig") as handle:
        filled = list(csv.DictReader(handle))

    ok, refused = [], []
    for row in filled:
        symbol = (row.get("SYMBOL") or "").strip().upper()
        sector = (row.get("SECTOR") or "").strip().upper()

        if symbol not in by_symbol:
            refused.append((symbol, "not in the master")); continue

        # ---- ALL NINE, OR NONE. 11 August. ----
        # My first attempt filled SECTOR and INDUSTRY only. master_loader
        # refused the file and this tool rolled it back -- correctly.
        # It checks every column in REQUIRED_COLUMNS that is not
        # identity, and a row that satisfies two of nine is exactly as
        # unloadable as a row that satisfies none.
        blank = [c for c in FILL_COLUMNS if not (row.get(c) or "").strip()]
        if blank:
            refused.append((symbol, f"blank: {', '.join(blank)}"))
            continue

        if sector not in known and not ALLOW_NEW_SECTORS:
            refused.append((symbol, f"'{sector}' is a sector the master has "
                                    f"never used -- check it is not a typo"))
            continue
        ok.append((symbol, sector, (row.get("INDUSTRY") or "").strip().upper(),
                   row))

    print()
    print(f"  {len(filled)} researched, {len(ok)} ready to apply, "
          f"{len(refused)} refused")
    print("  " + "=" * 70)
    for symbol, sector, industry, _row in ok:
        print(f"  {symbol:<13}{sector:<30}{industry[:26]}")
    if refused:
        print()
        print("  REFUSED -- these stay SUBSCRIBE = NO:")
        for symbol, why in refused:
            print(f"      {symbol:<13}{why}")

    if not write:
        print()
        print("  Dry run. Nothing written. Add --write to apply.")
        print()
        return 0

    if not ok:
        print("\n  Nothing passed the checks. Master untouched.\n")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{MASTER}.{stamp}.bak"
    shutil.copy2(MASTER, backup)

    for symbol, _sector, _industry, source in ok:
        row = by_symbol[symbol]
        for column in FILL_COLUMNS:
            row[column] = (source.get(column) or "").strip().upper()
        row["SUBSCRIBE"] = "YES"
        row["SUBSCRIBE_REASON"] = ""

    # PLAIN utf-8, NOT utf-8-sig. Writing the BOM back renamed the first
    # column to "﻿SECURITY ID" for every reader that opens the file
    # as plain utf-8 -- which tests/test_master_is_complete.py does, and
    # which failed within a minute of the first write. Read forgiving,
    # write exactly what was there.
    with open(MASTER, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    # ---- THE CHECK THAT MATTERS. 8 August: the bot would not start. ----
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        count = len(loader.all_symbols())
    except Exception as problem:                               # noqa: BLE001
        shutil.copy2(backup, MASTER)
        print()
        print(f"  master_loader REFUSED the new file: {problem}")
        print(f"  Rolled back from {backup}. The bot will start as before.")
        print()
        return 1

    print()
    print(f"  Written. Backup at {os.path.basename(backup)}")
    print(f"  master_loader loads. Tradeable universe is now {count}.")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--write" in sys.argv))
