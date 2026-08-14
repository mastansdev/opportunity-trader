"""
==========================================================
Read the numbers the channel already sent
==========================================================
    py tools/load_pulse_grids.py            look, write nothing
    py tools/load_pulse_grids.py --apply    load them

    "all pro folder channels give us complete data in realtime, which
     our own bot is unable to get in real time"
                                    -- operator, 1 August 2026

He said it at eight in the morning and it took until evening to act on
it.

WHAT WAS BEING DONE INSTEAD
---------------------------
core/results_pdf.py downloads a company's filing and hunts for the
results table inside it. That day, 200 filings were fetched:

    92   parsed
    108  failed -- 57% of them had no results table in the PDF at all

and 21 of the 1,699 stored rows held figures that could not be that
company. RAYMOND at 1.36 crore of quarterly sales. WESTLIFE at 1.00.

WHAT WAS ALREADY IN HAND
------------------------
Earnings Pulse publishes a FinAI grid with every result and the bot
has been storing it, reading only the Pulse Rating off the top:

    Metric      QoQ    YoY    Jun'26  Mar'26  Jun'25
    Sales        1%    11%       783     792     707
    OP         -18%     8%       228     277     210
    PAT         17%     9%       159     192     146

206 such cards were in telegram.db. 192 parse cleanly, and each one
carries THREE quarters -- including the year-ago quarter, which a
single filing does not even contain.

WESTLIFE's card says 736. The store said 1.00.

WHY THESE ROWS OVERWRITE THE PDF'S
----------------------------------
Written with trusted=True, which skips the store's own sanity check.
That check compares a new figure against the company's own median, and
WESTLIFE's median is the corrupt 1.00 -- so the CORRECT figure reads as
a 736x outlier and gets refused. Corrupt data defending itself.

It is not a weaker check. It is a better source: the channel prints
what the company reported, minutes after it reports.

WHAT IT WILL NOT DO
-------------------
It never trades. It refuses a card it cannot read cleanly rather than
guessing -- 14 of the 206 -- and it does not delete the filing rows: a
second independent reading of a quarter is what the CONFLICT chip is
made of.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, ".")

from core.logger import decision, warn                    # noqa: E402
from core.pulse_grid import GRID_HEADER, parse_grid       # noqa: E402
from core.quarterly_results import QuarterlyResults       # noqa: E402

TELEGRAM_DB = os.path.join("data", "telegram.db")


def cards(db_path=TELEGRAM_DB):
    """Every stored message carrying a FinAI grid, newest first."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT at, channel, symbols, text, ocr_text FROM messages "
        "ORDER BY at DESC").fetchall()
    conn.close()
    out = []
    for row in rows:
        body = (row["ocr_text"] or "") or (row["text"] or "")
        if body and GRID_HEADER.search(body):
            out.append((row, body))
    return out


def main(apply=False):
    if not os.path.exists(TELEGRAM_DB):
        warn(f"No {TELEGRAM_DB}. Nothing to do.")
        return 1

    store = QuarterlyResults()
    found = cards()
    tally = Counter()
    plan, seen = [], set()

    for row, body in found:
        symbols = [s for s in (row["symbols"] or "").split(",") if s]
        if not symbols:
            tally["no symbol on the card"] += 1
            continue
        # ONE company per card. A grid names one company; if the symbol
        # column holds more, we cannot tell which the figures belong to
        # and guessing is how a quarter lands on the wrong stock.
        if len(set(symbols)) > 1:
            tally["more than one symbol -- refused"] += 1
            continue
        symbol = symbols[0].strip().upper()
        quarters = parse_grid(body)
        if not quarters:
            tally["grid would not parse"] += 1
            continue
        for q in quarters:
            key = (symbol, q["period_end"])
            if key in seen:            # an older card for the same quarter
                continue
            seen.add(key)
            plan.append((symbol, q))
        tally["read"] += 1

    decision("=" * 78)
    decision("  THE FIGURES THE CHANNEL ALREADY SENT")
    decision("=" * 78)
    decision("")
    decision(f"  cards holding a grid : {len(found)}")
    for reason, n in tally.most_common():
        decision(f"    {reason:34s} {n}")
    decision(f"  quarters to write    : {len(plan)}")
    decision("")

    for symbol, q in plan[:12]:
        decision(f"  {symbol:12s} {q['period_label']:8s} "
                 f"sales={q.get('sales')}  OP={q.get('operating_profit')}  "
                 f"PAT={q.get('pat')}  EPS={q.get('eps')}")
    if len(plan) > 12:
        decision(f"  ... and {len(plan) - 12} more")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing written. Re-run with --apply.")
        return 0

    counts = Counter()
    for symbol, q in plan:
        counts[store.remember(
            symbol, q["period_end"],
            sales=q.get("sales"), other_income=q.get("other_income"),
            operating_profit=q.get("operating_profit"),
            opm_pct=q.get("opm_pct"), pat=q.get("pat"), eps=q.get("eps"),
            period_label=q["period_label"], source="pulse_grid",
            trusted=True)] += 1

    decision("")
    decision(f"  DONE. new={counts['new']}  updated={counts['updated']}  "
             f"unchanged={counts['unchanged']}")
    decision("  Nothing was traded. The filing rows were left alone -- two")
    decision("  independent readings of a quarter is what the CONFLICT")
    decision("  chip is made of.")
    return 0


if __name__ == "__main__":
    sys.exit(main(apply="--apply" in sys.argv))
