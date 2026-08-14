"""
==========================================================
Re-read the filings we already have
==========================================================
    py tools/reingest_filings.py            look, change nothing
    py tools/reingest_filings.py --apply    read them and store

No network. No orders. It reads PDFs already on disk in data/filings
and writes quarters into data/quarterly_results.db.

WHY IT EXISTS
-------------
31 July 2026. APTUS reported, closed -5.77%, and the dashboard showed

    GOOD: PAT +10% QoQ

which was a grade of the MARCH quarter. Today's filing had downloaded
fine -- it was sitting in data/filings the whole time -- and the
parser could not read it, for two reasons since fixed:

  - the column header said 30.06.2026, and the date pattern demanded a
    three-letter month name
  - pdfplumber reports that filing's figures with stray spaces inside
    them ("2 6,095.49" is one number, not two)

Fixing the parser does not fix the STORE. Those PDFs were read once,
failed, and nothing goes back for them -- core/results_ingest.py runs
on a filing arriving, not on a parser improving. So the dashboard
would have kept grading August's news against March's numbers until
each company reported again.

This is the way a parser change reaches old data.

WHAT IT WILL NOT DO
-------------------
It never downloads and never trades. A PDF that still cannot be read
is reported and skipped -- half of them cannot, and saying so is the
point. Refusing loudly beats storing a guess: a wrong figure on a real
filing is the worst thing this program can produce.

Author : H&M Opportunity Trader
==========================================================
"""

import glob
import os
import sys
from collections import Counter

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.quarterly_results import QuarterlyResults        # noqa: E402
from core.results_pdf import parse_pdf                     # noqa: E402

FILING_DIR = os.path.join("data", "filings")


def _line():
    decision("-" * 70)


def symbol_of(path):
    """AAPTUS_20260731_..._sd.pdf -> APTUS. The ingester names files
    itself, so the symbol is always the first field."""
    return os.path.basename(path).split("_")[0].upper()


def main(apply=False, only=None, limit=None):
    decision("=" * 70)
    decision("  RE-INGEST -- read the filings already on disk")
    decision("=" * 70)

    files = sorted(glob.glob(os.path.join(FILING_DIR, "*.pdf")))
    if only:
        files = [f for f in files if symbol_of(f) == only.upper()]
    if limit:
        files = files[:limit]

    if not files:
        warn(f"  No PDFs in {FILING_DIR}. Nothing to do.")
        return

    store = QuarterlyResults()
    _line()
    decision(f"  filings on disk : {len(files)}")
    decision(f"  reading from    : {FILING_DIR}")
    if not apply:
        decision("  MODE            : DRY RUN, nothing will be stored")
    _line()

    counts = Counter()
    written = Counter()
    unreadable = []

    for path in files:
        symbol = symbol_of(path)
        try:
            rows = parse_pdf(path, symbol=symbol)
        except Exception as exc:                           # noqa: BLE001
            warn(f"  {symbol:14} raised: {str(exc)[:60]}")
            counts["raised"] += 1
            continue

        if not rows:
            counts["unreadable"] += 1
            unreadable.append(symbol)
            continue

        counts["readable"] += 1
        newest = rows[0]
        note = (f"{newest.get('period_label')}  "
                f"sales={newest.get('sales')}  pat={newest.get('pat')}")

        if not apply:
            decision(f"  {symbol:14} would store {len(rows)}q   {note}")
            continue

        for row in rows:
            outcome = store.remember(
                symbol=symbol, period_end=row["period_end"],
                period_label=row.get("period_label"), sales=row.get("sales"),
                pat=row.get("pat"), eps=row.get("eps"),
                other_income=row.get("other_income"),
                operating_profit=row.get("operating_profit"),
                opm_pct=row.get("opm_pct"), source="filing_pdf_reingest")
            written[outcome] += 1
        decision(f"  {symbol:14} stored {len(rows)}q   {note}")

    _line()
    decision(f"  readable   : {counts['readable']}")
    decision(f"  unreadable : {counts['unreadable']}")
    if counts["raised"]:
        decision(f"  raised     : {counts['raised']}")
    if unreadable:
        decision("")
        decision("  STILL UNREADABLE -- these keep whatever the store already")
        decision("  had, and their grades will stay labelled with the older")
        decision("  quarter on the dashboard:")
        for i in range(0, len(unreadable), 8):
            decision("    " + "  ".join(f"{s:<12}" for s in unreadable[i:i + 8]))

    if apply:
        _line()
        decision(f"  new rows     : {written.get('new', 0)}")
        decision(f"  updated rows : {written.get('updated', 0)}")
        decision(f"  unchanged    : {written.get('unchanged', 0)}")
        decision("")
        decision("  NOTHING WAS DOWNLOADED AND NOTHING WAS TRADED.")
    else:
        _line()
        decision("  DRY RUN. To store these:")
        decision("      py tools/reingest_filings.py --apply")


if __name__ == "__main__":
    args = sys.argv[1:]
    only = None
    if "--symbol" in args:
        only = args[args.index("--symbol") + 1]
    main(apply="--apply" in args, only=only)
