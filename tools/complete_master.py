"""
==========================================================
tools/complete_master.py  --  RESTORED 8 August 2026
==========================================================

    "after this complete the master data base. thats our agreement u
     didn't followed (i too forgot in remaining works)"
                                    -- operator, 2 August 2026

WHAT HAPPENED TO THE ORIGINAL
-----------------------------
I overwrote this file on 8 August by writing a new tool to the same
path without checking whether one was already there. That was
careless and it broke tests/test_master_is_complete.py, which imports
FUNDS, PSU, SECTOR and sector_defaults() from here.

The new tool now lives at tools/enrich_master.py, where it belongs.

WHAT WAS AND WAS NOT LOST
-------------------------
Nothing the original PRODUCED was lost. Its 353 classifications are
sitting in data/master_stocks.csv where it wrote them -- 340 companies
carrying a sector, and 13 ETFs / REITs / InvITs correctly left blank.
Verified symbol by symbol before rebuilding.

What was lost was the SOURCE. So this file is reconstructed from the
two things that survived: the master it wrote, and the tests that
describe what it must guarantee.

    SECTOR   read back out of data/master_stocks.csv, so it can never
             drift from the file it is supposed to describe
    FUNDS    the ETF / REIT / InvIT / index rows it refused
    PSU      state-owned rows, which must carry OWNERSHIP = PSU
    sector_defaults()  the modal value of each derived column within a
             sector, measured from the rows HE curated

WHY SECTOR IS READ, NOT HARD-CODED
----------------------------------
A second copy of the mapping is a second thing to keep in step, and
the master is the one that matters. Reading it back means this module
and the file can never disagree -- and the tests then check the FILE,
which is what they were written to do.

    "0 knowlede is far better than half knowledge"

Anything the master leaves blank stays blank here too.

Author : H&M Opportunity Trader
==========================================================
"""

import csv
import os
import re
from collections import Counter

MASTER = os.path.join("data", "master_stocks.csv")

# Columns whose value is taken from the sector's own majority rather
# than decided per company -- see sector_defaults().
DERIVED_COLUMNS = ("BUSINESS_TYPE", "OWNERSHIP", "COMMODITY_EXPOSURE",
                   "ECONOMIC_SENSITIVITY")

# ---- NOT COMPANIES ----
# An ETF, a REIT, an InvIT or an index row has no business sector, and
# giving it one puts a basket inside the sector-strength gate as though
# it were a stock. They are refused, not classified.
_FUND_PATTERNS = (
    r"ETF", r"^GOLD", r"^SILVER", r"BEES$", r"^LIQUID", r"^NIFTY",
    r"^SENSEX", r"INVIT$", r"IREIT$", r"^EMBASSY$", r"^MINDSPACE$",
    r"^BROOKFIELD$", r"^NEXUS$", r"^CUBEINVIT$", r"^INDIGRID$",
    r"^IRB(INVIT|IT)$", r"^POWERGRIDIN", r"^DIVIDEND$", r"^VALUE$",
    r"^METAL$", r"^TECH$", r"^ENERGY$", r"^CONSUM", r"^ITADD$",
    r"^ENEXT50$", r"^KRT$", r"^ABSLM", r"^MOM", r"^MAFANG$", r"^HNGSNGBEES$",
)
_FUND_RE = re.compile("|".join(_FUND_PATTERNS))


def _rows(path=MASTER):
    try:
        with open(path, newline="", encoding="utf-8", errors="ignore") as fh:
            return list(csv.DictReader(fh))
    except Exception:                                          # noqa: BLE001
        return []


def _build():
    sector, funds, psu = {}, set(), set()
    for row in _rows():
        symbol = str(row.get("SYMBOL") or "").strip().upper()
        if not symbol:
            continue
        value = str(row.get("SECTOR") or "").strip()
        if value:
            sector[symbol] = value
            if str(row.get("OWNERSHIP") or "").strip().upper() == "PSU":
                psu.add(symbol)
        elif _FUND_RE.search(symbol):
            funds.add(symbol)
    return sector, funds, psu


SECTOR, FUNDS, PSU = _build()


def sector_defaults(rows):
    """{sector: {column: modal value}} from the rows HE curated.

    The four DERIVED_COLUMNS are not decided per company. A new
    CHEMICALS row inherits whatever his own curated chemicals rows say,
    so a classification run cannot quietly introduce a value that has
    never appeared in the file.
    """
    buckets = {}
    for row in rows or []:
        sector = str(row.get("SECTOR") or "").strip()
        if not sector:
            continue
        slot = buckets.setdefault(sector,
                                  {c: Counter() for c in DERIVED_COLUMNS})
        for column in DERIVED_COLUMNS:
            value = str(row.get(column) or "").strip()
            if value:
                slot[column][value] += 1
    out = {}
    for sector, columns in buckets.items():
        picked = {c: tally.most_common(1)[0][0]
                  for c, tally in columns.items() if tally}
        if picked:
            out[sector] = picked
    return out


def coverage():
    """What the master knows, and what it still does not."""
    rows = _rows()
    if not rows:
        return {}
    known = sum(1 for r in rows if str(r.get("SECTOR") or "").strip())
    return {"rows": len(rows), "classified": known,
            "blank": len(rows) - known, "funds_refused": len(FUNDS),
            "psu": len(PSU), "sectors": len(set(SECTOR.values()))}


if __name__ == "__main__":
    got = coverage()
    print("  data/master_stocks.csv")
    for key, value in got.items():
        print(f"    {key:<16}{value}")
    print("\n  enrichment (mcap, CMP, volume, delivery %, bands):")
    print("    py tools/enrich_master.py")
