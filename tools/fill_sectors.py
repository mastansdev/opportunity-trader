"""
==========================================================
py tools/fill_sectors.py  --  sector and industry, from NSE
==========================================================

    "pls complete the master data its the key . without key where to
     land?"
                                -- operator, 8 August 2026

WHY THIS EXISTS
---------------
336 rows of data/master_stocks.csv have no SECTOR and no INDUSTRY, and
91 of those are stocks that pass his own rules and receive graded
result cards. core/master_loader.py refuses to load if any TRADEABLE
row has a blank sector -- correctly, because core/news_impact.py fans a
sector event out to every stock in that sector, so a blank or a wrong
label is a silent, expensive mistake.

So those 91 sit at SUBSCRIBE = NO until this fills them.

WHY NOT GUESS
-------------
    "0 knowlede is far better than half knowledge"

A sector derived from a company name puts "Pharmaceuticals" next to a
company that makes valves, and nothing downstream ever questions it.
Only NSE's own classification is used here.

WHERE THE FILES COME FROM
-------------------------
    "out of bot scope = dhan tokens, nse related things i'll do
     manually"

NSE blocks automated downloads, so he fetches them the same way he
fetched LIST_NSE.xlsx. Save any of these into data/ :

    https://nsearchives.nseindia.com/content/indices/
        ind_niftytotalmarket_list.csv      (750 names)
        ind_niftymicrocap250_list.csv      (250)
        ind_niftysmallcap250_list.csv      (250)
        ind_niftymidcap150_list.csv        (150)
        ind_nifty500list.csv               (500)

Every one of them carries the same four columns:

    Company Name, Industry, Symbol, Series, ISIN Code

This reads every ind_*_list.csv it finds, so more files simply means
better coverage. Overlaps are fine -- first file wins and the rest
agree.

WHAT IT WRITES
--------------
SECTOR and INDUSTRY, both from NSE's Industry column. NSE publishes one
level of classification, not two, and inventing a finer INDUSTRY from
it would be the guessing this file exists to avoid.

Rows it cannot match are LEFT BLANK and listed by name at the end, so
the gap stays visible instead of becoming a plausible wrong answer.

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

MASTER = os.path.join("data", "master_stocks.csv")
INDEX_GLOB = os.path.join("data", "ind_*_list.csv")
STAMP = "8 Aug 2026"


def _nse_sectors():
    """{symbol: (industry, source file)} from every NSE index list."""
    out = {}
    files = sorted(glob.glob(INDEX_GLOB))
    for path in files:
        try:
            with open(path, newline="", encoding="utf-8",
                      errors="ignore") as handle:
                rows = list(csv.DictReader(handle))
        except Exception as exc:                               # noqa: BLE001
            print(f"  ! {os.path.basename(path)} unreadable ({exc})")
            continue
        added = 0
        for row in rows:
            symbol = str(row.get("Symbol") or "").strip().upper()
            industry = str(row.get("Industry") or "").strip()
            if not symbol or not industry or symbol in out:
                continue
            out[symbol] = (industry, os.path.basename(path))
            added += 1
        print(f"  {os.path.basename(path):<40}{len(rows):>5} rows, "
              f"{added:>4} new")
    if not files:
        print(f"  ! no ind_*_list.csv in data/ -- see this file's header "
              f"for the five URLs")
    return out


def run(switch_on=True):
    rows = list(csv.DictReader(open(MASTER, encoding="utf-8", errors="ignore")))
    if not rows:
        print("  ! master_stocks.csv is empty")
        return 1
    columns = list(rows[0].keys())

    print("READING NSE'S OWN CLASSIFICATION\n")
    sectors = _nse_sectors()
    if not sectors:
        return 1
    print(f"\n  {len(sectors)} symbols classified by NSE\n")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    shutil.copy(MASTER, f"{MASTER}.{stamp}.bak")

    filled, switched, still_blank = 0, 0, []
    for row in rows:
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        blank = not str(row.get("SECTOR") or "").strip()
        got = sectors.get(symbol)
        if blank and got:
            industry, source = got
            row["SECTOR"] = industry
            row["INDUSTRY"] = industry
            filled += 1
            # ---- ONLY THEN MAY IT BE WATCHED ----
            # These were switched on this morning and switched straight
            # back off, because master_loader refuses a tradeable row
            # with no sector -- and it was right to. Now it has one.
            if switch_on and STAMP in str(row.get("SUBSCRIBE_REASON") or ""):
                row["SUBSCRIBE"] = "YES"
                row["SUBSCRIBE_REASON"] = (
                    row["SUBSCRIBE_REASON"].split(" -- HELD OFF")[0]
                    + f". sector '{industry}' from NSE {source}. {STAMP}")
                switched += 1
        elif blank:
            still_blank.append(symbol)

    with open(MASTER, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    total = len(rows)
    known = sum(1 for r in rows if str(r.get("SECTOR") or "").strip())
    watched = sum(1 for r in rows
                  if str(r.get("SUBSCRIBE") or "").strip().upper() == "YES")
    print(f"  backed up      master_stocks.csv.{stamp}.bak")
    print(f"  sectors filled {filled}")
    print(f"  switched ON    {switched}")
    print(f"  SECTOR known   {known} of {total}  ({known / total * 100:.1f}%)")
    print(f"  watch list     {watched}")

    if still_blank:
        print(f"\n  {len(still_blank)} still have no sector -- NSE does not "
              f"classify them in the files present:")
        for chunk in range(0, min(len(still_blank), 40), 8):
            print("    " + ", ".join(sorted(still_blank)[chunk:chunk + 8]))
        print("  These stay SUBSCRIBE = NO. A blank is a question the bot "
              "knows it cannot answer.")

    # ---- THE LOADER IS THE REAL TEST ----
    try:
        from core.master_loader import MasterLoader
        loader = MasterLoader()
        loader.load()
        print(f"\n  master_loader: OK, {len(loader.all_symbols())} subscribed")
    except Exception as exc:                                   # noqa: BLE001
        print(f"\n  ! master_loader STILL REFUSES: {str(exc)[:200]}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(run(switch_on="--no-switch" not in sys.argv))
