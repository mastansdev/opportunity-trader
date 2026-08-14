"""
==========================================================
py tools/fix_security_ids.py -- correct the master from Dhan
==========================================================

    "pls make sure we will trade only NSE listed stocks"
    "there is no room for error at all"

WHY THIS EXISTS
---------------
tools/verify_master_database.py has been comparing data/master_stocks.csv
against Dhan's live scrip master and writing the differences to
data/scrip_verified.json. On the 7 August run it found three:

    TRIVENI      master 13084, Dhan 13081
    HMVL         master 19211, Dhan 19215
    SHALPAINTS   master 15342, Dhan 15346

And then nothing did anything with them. The file recorded the fault
and the fault stayed. TRIVENI has been subscribed on a wrong id and
silent on every recorded session since.

WHY A WRONG ID IS DANGEROUS, NOT MERELY USELESS
-----------------------------------------------
Checked before writing this, because the answer decides how urgent it
is: all three wrong ids belong to NOBODY in Dhan's master, so all three
are simply silent. Nothing is being recorded under the wrong name.

That was luck. An id that is wrong by four digits could as easily have
belonged to another live instrument, and the bot would have recorded
that stock's prices, ranked them, and traded them under this symbol --
the same class of fault as a chip built from another company's numbers,
except in the price series, where nothing downstream could detect it.

So this is applied, and re-verified, rather than left in a report.

WHAT IT DOES
------------
Reads the mismatches out of data/scrip_verified.json, rewrites those
rows of data/master_stocks.csv, and keeps a timestamped backup. It
changes nothing else -- one column, on the named rows only.

    py tools/fix_security_ids.py              show what it would do
    py tools/fix_security_ids.py --apply      write it

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import json
import os
import shutil
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROOF_PATH = os.path.join("data", "scrip_verified.json")
ID_COLUMN = "SECURITY ID"
SYMBOL_COLUMN = "SYMBOL"


def _corrections():
    """{symbol: dhan_id} from the last verification run."""
    try:
        with open(PROOF_PATH, encoding="utf-8") as handle:
            proof = json.load(handle) or {}
    except Exception as exc:                               # noqa: BLE001
        print(f"Cannot read {PROOF_PATH}: {exc}")
        return {}, None

    out = {}
    for line in proof.get("mismatches") or []:
        # "TRIVENI: master 13084, Dhan 13081"
        try:
            symbol, rest = str(line).split(":", 1)
            dhan = rest.split("Dhan", 1)[1].strip().strip(".,")
            if symbol.strip() and dhan.isdigit():
                out[symbol.strip().upper()] = dhan
        except (ValueError, IndexError):
            print(f"  could not parse: {line}")
    return out, proof.get("verified_at")


def main():
    apply = "--apply" in sys.argv
    from core.master_loader import MASTER_CSV_PATH

    fixes, verified_at = _corrections()
    print("=" * 68)
    print("  SECURITY ID CORRECTIONS FROM DHAN")
    print(f"  source: {PROOF_PATH}, verified {verified_at}")
    print("=" * 68)

    if not fixes:
        print("\n  Nothing to correct. The master agrees with Dhan.")
        print("=" * 68)
        return 0

    with open(MASTER_CSV_PATH, newline="", encoding="utf-8",
              errors="ignore") as handle:
        reader = csv.DictReader(handle)
        columns = reader.fieldnames
        rows = list(reader)

    if ID_COLUMN not in (columns or []):
        print(f"\n  {MASTER_CSV_PATH} has no '{ID_COLUMN}' column. "
              f"Refusing to guess.")
        return 1

    changed = []
    for row in rows:
        symbol = str(row.get(SYMBOL_COLUMN) or "").strip().upper()
        if symbol in fixes:
            was = str(row.get(ID_COLUMN) or "").strip()
            now = fixes[symbol]
            if was != now:
                changed.append((symbol, was, now))
                row[ID_COLUMN] = now

    print()
    for symbol, was, now in changed:
        print(f"  {symbol:<14} {was:>8}  ->  {now}")
    missing = sorted(set(fixes) - {c[0] for c in changed})
    for symbol in missing:
        print(f"  {symbol:<14} not present in the master -- skipped")

    if not apply:
        print(f"\n  {len(changed)} row(s) would change. Nothing written.")
        print("  Run again with --apply to write it.")
        print("=" * 68)
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = f"{MASTER_CSV_PATH}.{stamp}.bak"
    shutil.copy2(MASTER_CSV_PATH, backup)

    with open(MASTER_CSV_PATH, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n  {len(changed)} row(s) written.")
    print(f"  backup: {backup}")

    # ---- RE-READ IT. A write nobody verified is a write nobody trusts.
    from core.master_loader import MasterLoader
    check = MasterLoader()
    check.load()
    bad = [s for s, _was, now in changed
           if str(check.security_id(s)) != now]
    if bad:
        print(f"\n  VERIFY FAILED for {bad} -- restore {backup}")
        print("=" * 68)
        return 1
    print("  verified: the loader now returns Dhan's ids.")
    print("\n  Next: py tools/verify_master_database.py  (confirms "
          "against Dhan)")
    print("=" * 68)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
