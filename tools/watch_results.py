"""
==========================================================
Watch for results filings, live, as they land
==========================================================

    py tools/watch_results.py                 # poll every 3 minutes
    py tools/watch_results.py --every 60      # every 60 seconds
    py tools/watch_results.py --once          # one look and exit

WHY THIS IS A SEPARATE SCRIPT AND NOT A CHANGE TO main.py
----------------------------------------------------------
Found 2026-07-27: main.py refreshes the results calendar exactly ONCE,
at startup (line 258), and never again. There is no timer. So on a day
when 68 companies report, the bot learns about a 12:12 filing the
following morning.

Canara Bank filed around noon. At 13:50 the bot still had no idea.

The fix belongs in main.py's loop eventually. But main.py is running a
live session right now, and restarting it to add a poller would end the
session's recording -- the exact "untested change on top of untested
change" that this project has been bitten by before. So this runs
alongside, reads the same NSE feed with the same call, touches nothing
the live bot owns, and can be Ctrl+C'd at any moment.

WHAT IT ANSWERS
---------------
1. HOW FAST does the exchange publish a filing, and how fast could a bot
   know? (prints the gap between the filing timestamp and our seeing it)

2. DO THE NUMBERS TRAVEL WITH IT? NSE's announcement row carries
   `attchmntText`. core/results_calendar.py reads it only to decide "is
   this a results filing, yes or no", then throws it away. If it also
   carries revenue and profit, the bot has a same-minute financial feed
   and does not need BSE for the trigger at all -- BSE's own
   resultsSnapshot was still showing Mar-26 for CANBK 98 minutes after
   the numbers were public.

WHAT IT DOES NOT DO
-------------------
No trading. No writes to any database the bot uses. No parsing rules
committed to yet -- it PRINTS what arrived so a human can judge whether
the text is usable before anyone writes a parser against it.

Author : H&M Opportunity Trader
==========================================================
"""

import argparse
import os
import re
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.results_calendar import is_results_announcement  # noqa: E402

# Numbers we would want out of a filing, and the words that tend to
# introduce them in Indian results text. Nothing is parsed on these yet
# -- they only decide whether a line is worth SHOWING.
MONEY_WORDS = (
    "total income", "revenue from operations", "net profit", "profit for",
    "profit after tax", "earnings per share", "eps", "total revenue",
    "profit before tax", "operating profit",
)


def looks_numeric(text):
    """Does this line carry an actual figure, not just a word?"""
    return bool(re.search(r"\d[\d,]*\.?\d*", text or ""))


def fetch(since_hours):
    from nse import NSE
    now = datetime.now()
    with NSE(download_folder="data") as n:
        return n.announcements(
            index="equities",
            from_date=now - timedelta(hours=since_hours),
            to_date=now) or []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=int, default=180,
                    help="seconds between polls (default 180)")
    ap.add_argument("--hours", type=int, default=8,
                    help="how far back to look on each poll")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--show-text", type=int, default=600,
                    help="characters of attachment text to print")
    a = ap.parse_args()

    print("=" * 78)
    print("  WATCHING FOR RESULTS FILINGS")
    print(f"  polling NSE every {a.every}s, looking back {a.hours}h")
    print("  Ctrl+C to stop. Touches nothing the live bot owns.")
    print("=" * 78)

    seen = set()
    first_pass = True

    while True:
        try:
            rows = fetch(a.hours)
        except Exception as exc:                        # noqa: BLE001
            print(f"{datetime.now():%H:%M:%S}  fetch failed: {exc}")
            if a.once:
                return
            time.sleep(a.every)
            continue

        fresh = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            sym = str(row.get("symbol") or "").strip().upper()
            desc = str(row.get("desc") or row.get("subject") or "")
            body = str(row.get("attchmntText") or "")
            if not sym or not is_results_announcement(desc, body):
                continue

            stamp = str(row.get("an_dt") or row.get("sort_date")
                        or row.get("exchdisstime") or "")
            key = (sym, stamp)
            if key in seen:
                continue
            seen.add(key)
            fresh += 1

            # On the first pass everything looks "new" -- it is just
            # history. Only announce arrivals AFTER we started watching.
            if first_pass:
                continue

            now = datetime.now()
            print("\n" + "-" * 78)
            print(f"  {sym}   filed {stamp}   seen by us {now:%H:%M:%S}")
            try:
                filed = datetime.strptime(str(stamp)[:19],
                                          "%d-%b-%Y %H:%M:%S")
                print(f"  DELAY: {(now - filed).total_seconds()/60:.1f} minutes"
                      f" between the exchange publishing and us seeing it")
            except Exception:                           # noqa: BLE001
                pass
            print(f"  desc: {desc[:120]}")

            if not body.strip():
                print("  attachment text: EMPTY -- no numbers travel with "
                      "this announcement")
            else:
                print(f"  attachment text: {len(body)} chars")
                hits = [ln.strip() for ln in re.split(r"[\n\r]+", body)
                        if any(w in ln.lower() for w in MONEY_WORDS)
                        and looks_numeric(ln)]
                if hits:
                    print("  LINES THAT LOOK LIKE FIGURES:")
                    for h in hits[:8]:
                        print(f"     {h[:110]}")
                else:
                    print("  no figure-like lines found. Raw start:")
                    print(f"     {body[:a.show_text]}")

        if first_pass:
            print(f"{datetime.now():%H:%M:%S}  baseline: {fresh} results "
                  f"filings already in the last {a.hours}h. Watching for new "
                  f"ones from now.")
            first_pass = False
        else:
            print(f"{datetime.now():%H:%M:%S}  checked, "
                  f"{'nothing new' if not fresh else f'{fresh} NEW'}")

        if a.once:
            return
        time.sleep(a.every)


if __name__ == "__main__":
    main()
