"""
==========================================================
The filings NSE never told us about
==========================================================
    py tools/fetch_missing_filings.py            look, download nothing
    py tools/fetch_missing_filings.py --apply    fetch and read them

Downloads results PDFs using the links EARNINGS PULSE already gave us,
for companies core/announcement_watcher.py never saw.

WHY
---
31 July 2026. 32 companies reported. After the parser was fixed and
every stored PDF re-read, 18 were still being graded on an older
quarter. Split exactly in half:

     9   PDF on disk, still unreadable   (a parser problem)
     9   NO PDF EVER DOWNLOADED          (this)

For all nine of the second group, a filing link was sitting in
telegram.db. Eight of them pointed at BSE:

    ASHIKAG    bseindia.com/xml-data/corpfiling/AttachLive/...
    BEML       bseindia.com/...
    BLUEDART   bseindia.com/...
    SYRMA      bseindia.com/...

core/announcement_watcher.py polls NSE. A company that files to BSE --
or whose NSE announcement is not categorised as a result -- is never
queued, so no PDF is ever fetched and there is nothing for the parser
to fail at. The bot then grades that company's news against last
quarter's numbers, which is how APTUS showed "GOOD: PAT +10% QoQ" on
a day it fell 5.77%.

Earnings Pulse has been publishing those links all along and the bot
has been storing them, unread, in the filing_url column.

WHAT IT WILL NOT DO
-------------------
It downloads and parses. It never trades, and it never stores a figure
it could not read -- an unreadable filing is reported and skipped, so
the store keeps the older quarter and the dashboard keeps labelling it
with that quarter's name.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from datetime import datetime, timedelta

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.quarterly_results import QuarterlyResults        # noqa: E402
from core.results_ingest import ResultsIngestor, requests_downloader  # noqa: E402

TELEGRAM_DB = os.path.join("data", "telegram.db")


def _line():
    decision("-" * 70)


def links_from_telegram(days=4):
    """{SYMBOL: filing_url} for results posted in the last few days.

    One link per symbol -- the FIRST seen, because Earnings Pulse posts
    the outcome letter before any later corrigendum, and the outcome
    letter is the one with the table in it.
    """
    since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    try:
        conn = sqlite3.connect(TELEGRAM_DB)
        rows = conn.execute(
            "SELECT symbols, filing_url, at FROM messages "
            "WHERE filing_url IS NOT NULL AND filing_url != '' "
            "AND at >= ? ORDER BY at", (since,)).fetchall()
        conn.close()
    except sqlite3.Error as exc:
        warn(f"  Could not read {TELEGRAM_DB}: {exc}")
        return {}

    for symbols, url, _at in rows:
        # A message tagged with several companies cannot tell us whose
        # filing this is. One symbol, one link, or nothing.
        names = [s for s in (symbols or "").split(",") if s.strip()]
        if len(names) != 1:
            continue
        out.setdefault(names[0].strip().upper(), url)
    return out


def _newest_period(store, symbol):
    try:
        got = store.compare(symbol)
        return (got or {}).get("period")
    except Exception:                                      # noqa: BLE001
        return None


def main(apply=False, days=4):
    decision("=" * 70)
    decision("  MISSING FILINGS -- fetched from the links Telegram gave us")
    decision("=" * 70)

    links = links_from_telegram(days=days)
    if not links:
        warn("  No filing links in telegram.db for the last few days.")
        return

    store = QuarterlyResults()
    ingestor = ResultsIngestor(store, downloader=requests_downloader(),
                               keep_files=True)

    # Only what we are actually missing. Re-downloading a filing we
    # already read is a slow way to learn nothing, and these are other
    # people's servers.
    wanted = {}
    for symbol, url in links.items():
        if _newest_period(store, symbol) != "Jun-26":
            wanted[symbol] = url

    _line()
    decision(f"  links held for      : {len(links)} companies")
    decision(f"  already have Jun-26 : {len(links) - len(wanted)}")
    decision(f"  to fetch            : {len(wanted)}")
    _line()

    if not wanted:
        decision("  Nothing missing. Every company we hold a link for is "
                 "already on the current quarter.")
        return

    for symbol, url in sorted(wanted.items()):
        host = url.split("/")[2] if "//" in url else url[:30]
        decision(f"  {symbol:12} {host}")

    if not apply:
        _line()
        decision("  DRY RUN -- nothing was downloaded.")
        decision("  To fetch and read them:")
        decision("      py tools/fetch_missing_filings.py --apply")
        return

    _line()
    decision("  fetching...")
    decision("")
    read = failed = 0
    for symbol, url in sorted(wanted.items()):
        status = ingestor.ingest(symbol, url)
        if "quarters" in str(status):
            read += 1
        else:
            failed += 1
            warn(f"  {symbol:12} {status}")

    _line()
    decision(f"  read     : {read}")
    decision(f"  failed   : {failed}")
    decision("")
    decision("  NOTHING WAS TRADED. Filings were downloaded and read.")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
