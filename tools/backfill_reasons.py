"""
==========================================================
Backfill the reason columns onto trades already recorded
==========================================================

    py tools/backfill_reasons.py            # show what it WOULD write
    py tools/backfill_reasons.py --apply    # write it

WHY
---
trade_memory gained six reason columns on 2026-07-28. The 28 trades
already stored have NULL in all of them, which is honest but useless --
the reason study needs a starting sample, and 28 trades is a fifth of
what a first answer needs.

The reasons for those trades were not lost. They are in the log:

    [NEWS] CRAFTSMAN -- RESULTS filed 10:10:00 (1 min ago): ...
    [NEWS] LT -- GOVERNANCE filed 11:10:02 (2 min ago): Resignation
    [FILING] MOLDTKPAC: read 3 quarters -- STRONG: sales +26% QoQ ...

So this walks the diagnostics log, collects what was known about each
symbol on each day, and stamps it onto the matching trade.

WHAT THIS CANNOT DO, AND SAYS SO
--------------------------------
Only what was known BEFORE the entry counts. A results filing that
landed at 14:41 is not a reason for a trade opened at 09:45 -- stamping
it would be hindsight dressed as evidence, and would bias the very
study it is meant to feed. Anything filed after the entry time is
skipped, and the skip is reported.

Backfilled rows are marked reason_summary="[backfill] ..." so they can
be separated from live captures later. If the two disagree, the live
ones are the truth.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.trade_memory import TradeMemory                  # noqa: E402

LOG = os.path.join("logs", "diagnostics.log")

# [NEWS] SYMBOL -- KIND filed HH:MM:SS
NEWS_RE = re.compile(r"\[NEWS\] ([A-Z0-9&-]+) -- ([A-Z_]+) filed (\d\d:\d\d:\d\d)")
# [FILING] SYMBOL: read N quarters (...) -- GRADE: ...
FILING_RE = re.compile(r"\[FILING\] ([A-Z0-9&-]+): read .*? -- ([A-Z]+):")

FIXTURES = {"X", "AAA", "BBB", "WEAK", "STRONG", "HOLD", "TESTCO", "UP_CO",
            "DOWN_CO", "NEW", "OLD", "PENNY", "WAKEFIT"}


def harvest(path=LOG):
    """(date, symbol) -> list of (time, kind, grade). Time is when the
    event was SEEN, which is what decides whether a later entry could
    have known about it."""
    found = defaultdict(list)
    stamp = None
    if not os.path.exists(path):
        return found
    with open(path, encoding="utf-8", errors="ignore") as fh:
        for line in fh:
            if len(line) > 19 and line[:4] == "2026":
                stamp = line[:19]
            if stamp is None:
                continue
            day = stamp[:10]
            m = NEWS_RE.search(line)
            if m and m.group(1) not in FIXTURES:
                found[(day, m.group(1))].append(
                    (stamp[11:19], m.group(2), None))
                continue
            m = FILING_RE.search(line)
            if m and m.group(1) not in FIXTURES:
                found[(day, m.group(1))].append(
                    (stamp[11:19], "RESULTS", m.group(2)))
    return found


def reason_for(events, entry_time):
    """What was known BEFORE this entry. Returns (fields, skipped_count)."""
    out = {"news_kind": None, "filing_kind": None, "results_grade": None,
           "had_reason": 0, "reason_summary": None}
    if not events:
        return out, 0
    cutoff = entry_time.strftime("%H:%M:%S") if entry_time else "23:59:59"
    known = [e for e in events if e[0] <= cutoff]
    skipped = len(events) - len(known)
    parts = []
    for seen, kind, grade in known:
        if grade:
            out["results_grade"] = grade
            out["filing_kind"] = "RESULTS"
            parts.append(f"results:{grade}")
        elif kind in ("RESULTS", "PAYOUT", "GOVERNANCE", "APPROVAL"):
            out["filing_kind"] = kind
            parts.append(f"filed:{kind}")
        else:
            out["news_kind"] = kind
            parts.append(f"news:{kind}")
    if parts:
        out["had_reason"] = 1
        seen_unique = list(dict.fromkeys(parts))
        out["reason_summary"] = ("[backfill] " + ", ".join(seen_unique))[:160]
    return out, skipped


def main():
    apply = "--apply" in sys.argv
    events = harvest()
    print(f"log events harvested: {len(events)} symbol-days\n")

    memory = TradeMemory()
    with memory.engine.begin() as conn:
        rows = conn.execute(memory.trades.select()).mappings().all()
    if not rows:
        print("no trades recorded yet -- nothing to backfill.")
        return

    updates, with_reason, skipped_total = [], 0, 0
    print(f"{'symbol':12}{'date':12}{'entry':>9}  reason found before entry")
    print("-" * 78)
    for row in rows:
        key = (row["trade_date"], row["symbol"])
        fields, skipped = reason_for(events.get(key, []), row["entry_time"])
        skipped_total += skipped
        with_reason += fields["had_reason"]
        entry = row["entry_time"].strftime("%H:%M:%S") if row["entry_time"] else "-"
        print(f"{row['symbol']:12}{row['trade_date']:12}{entry:>9}  "
              f"{fields['reason_summary'] or '(none)'}"
              f"{'   [' + str(skipped) + ' after entry, ignored]' if skipped else ''}")
        updates.append((row["id"], fields))

    print("-" * 78)
    print(f"{len(rows)} trades   WITH a reason: {with_reason}   "
          f"WITHOUT: {len(rows) - with_reason}")
    if skipped_total:
        print(f"{skipped_total} events ignored -- they landed AFTER the entry. "
              f"Stamping them would be hindsight, not evidence.")

    if not apply:
        print("\nDRY RUN. Nothing written. Re-run with --apply to save.")
        return

    from sqlalchemy import update as sql_update
    written = 0
    with memory.engine.begin() as conn:
        for trade_id, fields in updates:
            conn.execute(sql_update(memory.trades)
                         .where(memory.trades.c.id == trade_id)
                         .values(**fields))
            written += 1
    print(f"\nwritten: {written} rows.")


if __name__ == "__main__":
    main()
