"""
==========================================================
py tools/verify_ids_offline.py -- every security id, no network
==========================================================

    "nothing is impossible when you're more interested in finding a
     way than finding excuses."
                                -- operator, 8 August 2026

He said that after I told him twice that MOTHERSON could not be
diagnosed because my environment has no route to Dhan. He was right.
The answer was already on disk.

THE KEY
-------
NSE's UDiFF bhavcopy carries a column called FinInstrmId. That is
NSE's own token number for the instrument -- and for the NSE_EQ
segment it is exactly what Dhan uses as SECURITY ID.

Proved on the 7 August file before this tool was written:

    HINDALCO    token 1363    master 1363    agree
    ANTELOPUS   token 13598   master 13598   agree
    ZEEMEDIA    token 14003   master 14003   agree
    AXISCADES   token 9436    master 9436    agree
    GALLANTT    token 13337   master 13337   agree

    MOTHERSON   token 4204    master 25510   WRONG
    CHOLAFIN    token 685     master 19257   WRONG
    ELECTCAST   token 928     master 18116   WRONG

Across the whole master: 1,498 agree, 3 wrong, 0 ambiguous. And those
three are precisely the three that Dhan's live quote API refused in
tools/probe_silent.py, run independently on his machine.

Two unrelated sources, the same three names. That is a fact, not a
theory.

WHY THIS REPLACES THE OLD CHECK
-------------------------------
tools/verify_master_database.py fetches Dhan's scrip master and
resolves through core/instrument_master.py -- the same function that
writes the master. It compared a wrong id against itself and reported
CORRECT every night while the operator held 2,000 MOTHERSON shares
with no price on his screen.

This one reads a DIFFERENT source (the exchange's own file), needs no
network, no token, and no static IP, and it cannot share a bug with
the code that produced the value it is checking.

    py tools/verify_ids_offline.py            report
    py tools/verify_ids_offline.py --apply    correct the master

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import glob
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BHAV_GLOB = os.path.join("data", "BhavCopy_NSE_CM_*.csv")
ID_COLUMN = "SECURITY ID"
SYMBOL_COLUMN = "SYMBOL"

# UDiFF column names. Checked against the real file, not remembered.
COL_SYMBOL = "TckrSymb"
COL_SERIES = "SctySrs"
COL_TOKEN = "FinInstrmId"

# Only the cash series. BE/BZ are restricted books and W1 is a
# warrant -- ELECTCAST carries both EQ and W1 on NSE, which is what
# made iloc[0] pick wrongly in core/instrument_master.py.
CASH_SERIES = "EQ"


def _tokens(path):
    """{symbol: token} from one bhavcopy, EQ series only."""
    out = {}
    dupes = set()
    with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
        for row in csv.DictReader(handle):
            if (row.get(COL_SERIES) or "").strip().upper() != CASH_SERIES:
                continue
            symbol = (row.get(COL_SYMBOL) or "").strip().upper()
            token = (row.get(COL_TOKEN) or "").strip()
            if not symbol or not token:
                continue
            if symbol in out and out[symbol] != token:
                dupes.add(symbol)
            out[symbol] = token
    for symbol in dupes:
        out.pop(symbol, None)
    return out, dupes


def main():
    apply = "--apply" in sys.argv

    files = sorted(glob.glob(BHAV_GLOB))
    if not files:
        print(f"No bhavcopy files matching {BHAV_GLOB}.")
        print("Run the nightly download first.")
        return 1
    newest = files[-1]

    tokens, dupes = _tokens(newest)
    if not tokens:
        print(f"{newest} carried no EQ rows -- is the format still UDiFF?")
        return 1

    from core.master_loader import MASTER_CSV_PATH, MasterLoader
    loader = MasterLoader()
    loader.load()

    agree, wrong, absent = 0, [], 0
    for symbol in loader.all_symbols(include_blocked=True):
        ours = str(loader.security_id(symbol) or "").strip()
        theirs = tokens.get(symbol)
        if theirs is None:
            absent += 1
            continue
        if ours == theirs:
            agree += 1
        else:
            wrong.append((symbol, ours, theirs))

    print("=" * 70)
    print("  SECURITY IDS vs NSE'S OWN TOKEN NUMBERS")
    print(f"  source: {os.path.basename(newest)}   (no network needed)")
    print("=" * 70)
    print(f"  agree             {agree}")
    print(f"  WRONG             {len(wrong)}")
    print(f"  not in this file  {absent}   (blocked, delisted, or not EQ)")
    if dupes:
        print(f"  ambiguous         {len(dupes)}   {sorted(dupes)[:6]}")

    if not wrong:
        print("\n  Every id the exchange knows about matches ours.")
        print("=" * 70)
        return 0

    print(f"\n  {'SYMBOL':<14}{'OURS':>10}{'NSE TOKEN':>12}   subscribed?")
    subscribed = set(loader.all_symbols())
    for symbol, ours, theirs in sorted(wrong):
        print(f"  {symbol:<14}{ours:>10}{theirs:>12}   "
              f"{'yes -- silently unpriced' if symbol in subscribed else 'no'}")

    if not apply:
        print(f"\n  Nothing written. Run again with --apply to correct "
              f"the master.")
        print("=" * 70)
        return 1

    # ---- APPLY ----
    with open(MASTER_CSV_PATH, newline="", encoding="utf-8",
              errors="ignore") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        rows = list(reader)
    if ID_COLUMN not in (columns or []):
        print(f"\n  {MASTER_CSV_PATH} has no '{ID_COLUMN}' column.")
        return 1

    fixes = {s: t for s, _o, t in wrong}
    changed = 0
    for row in rows:
        symbol = str(row.get(SYMBOL_COLUMN) or "").strip().upper()
        if symbol in fixes:
            row[ID_COLUMN] = fixes[symbol]
            changed += 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{MASTER_CSV_PATH}.{stamp}.bak"
    shutil.copy2(MASTER_CSV_PATH, backup)
    with open(MASTER_CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  {changed} row(s) written.  backup: {backup}")

    # Re-read from disk. A write nobody verified is a write nobody
    # trusts -- and this one decides which instrument gets traded.
    check = MasterLoader()
    check.load()
    bad = [s for s, t in fixes.items() if str(check.security_id(s)) != t]
    if bad:
        print(f"  VERIFY FAILED for {bad} -- restore {backup}")
        return 1
    print("  verified: the loader now returns the exchange's tokens.")
    print("\n  These stocks have never had a price. Their history starts")
    print("  from the next session -- nothing backfills it.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
