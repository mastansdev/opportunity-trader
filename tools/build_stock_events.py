"""
==========================================================
Build the per-stock event memory
==========================================================
    py tools/build_stock_events.py           dry run
    py tools/build_stock_events.py --apply   write

    "we will use only useful news, images and store them in memory
     linked to respective stocks."       -- operator, 30 July 2026

Reads what the bot has already collected -- Telegram messages, their
image transcripts, and the news store -- and records the USEFUL ones as
typed events against the stocks they belong to.

Nothing is deleted. The raw messages stay exactly where they are; this
only writes a second, curated view. On 30 July alone the matching rules
changed three times and each change recovered links the previous rule
had missed by re-reading the raw store -- so the raw store is the thing
that must never be thrown away.

Safe to re-run: events are unique on (symbol, at, kind, headline), so a
second pass adds only what is genuinely new. That matters, because
re-running is how an improved matcher reaches yesterday's data.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.telegram_feed import TelegramFeed                # noqa: E402
from core.stock_events import (                            # noqa: E402
    StockEvents, classify, events_from_message, is_digest,
)

TELEGRAM_DB = ("data/telegram.db", "telegram.db")


def _find(paths):
    for path in paths:
        if os.path.exists(path):
            return path
    return None


def main(apply=False):
    path = _find(TELEGRAM_DB)
    if path is None:
        warn("No telegram.db found. Nothing to do.")
        return

    # RE-DERIVE the symbols; do not trust the stored column.
    #
    # The first run recorded a Crocs earnings line against MAHLIFE and
    # SWIGGY. Those links were in telegram.db's symbols column, written
    # months ago by a looser matcher, and tools/telegram_resymbol.py only
    # ever ADDS -- deliberately, so a rule change cannot delete a true
    # link. The curated view has no such obligation: it is rebuilt from
    # scratch every time, so it can and should apply today's rules.
    loader = MasterLoader()
    loader.load()
    matcher = TelegramFeed(client=None, master_loader=loader,
                           db_path=path, read_images=False)

    store = StockEvents()
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM messages ORDER BY at").fetchall()
    except sqlite3.Error as exc:
        warn(f"Could not read messages: {exc}")
        return

    kinds = Counter()
    skipped = Counter()
    planned = []

    for row in rows:
        typed = (row["text"] or "").strip()
        read = (row["ocr_text"] or "").strip() if "ocr_text" in row.keys() else ""
        body = (typed + "\n" + read).strip()

        # THE RULES LIVE IN ONE PLACE, 31 July 2026.
        #
        # Everything that used to be inlined here -- digest detection,
        # the three-company cut, classification, the beat summary, the
        # order-value restriction -- moved into
        # core/stock_events.events_from_message() so that the LIVE
        # session files events by exactly these rules and not by a
        # second copy of them that would drift.
        #
        # The counting below is only so this tool can still explain
        # itself. It re-derives what the shared function decided; it
        # does not decide anything of its own.
        events = events_from_message(
            matcher, text=row["text"], ocr_text=read, at=row["at"],
            channel=row["channel"], url=row["url"], grade=row["grade"])

        if not events:
            if not body:
                skipped["no text (image not read yet)"] += 1
            elif is_digest(body):
                skipped["digest (several stories in one message)"] += 1
            else:
                symbols = list(dict.fromkeys(
                    matcher.symbols_in(body) + matcher.names_in(body)))
                if len(symbols) >= 3:
                    skipped["several companies named (a list, not a story)"] += 1
                else:
                    kind, _ = classify(body, grade=row["grade"],
                                       has_symbol=bool(symbols))
                    kinds[kind] += 1
                    skipped[f"{kind.lower()} (kept in telegram.db, "
                            f"not an event)"] += 1
            continue

        kinds[events[0]["kind"]] += 1
        planned.extend(events)

    decision(f"[EVENTS] {len(rows)} messages read.")
    decision("")
    decision("  classified:")
    for kind, count in kinds.most_common():
        decision(f"    {kind:10} {count:5}")
    decision("")
    decision("  not recorded:")
    for why, count in skipped.most_common():
        decision(f"    {count:5}  {why}")

    stock = [p for p in planned if p["scope"] == "STOCK"]
    market = [p for p in planned if p["scope"] == "MARKET"]
    decision("")
    decision(f"  events against a stock : {len(stock)}")
    decision(f"  market context         : {len(market)}")

    decision("")
    decision("  a sample of what would be stored:")
    for item in stock[-12:]:
        bits = [item["kind"]]
        if item["grade"]:
            bits.append(f"grade={item['grade']}")
        if item["value_cr"]:
            bits.append(f"Rs {item['value_cr']:,.2f} cr")
        if item["counterparty"]:
            bits.append(f"from {item['counterparty']}")
        decision(f"    {item['symbol']:12} {' | '.join(bits)}")
        decision(f"      {item['headline'][:88]}")

    if not apply:
        decision("")
        decision("  DRY RUN -- nothing written. Re-run with --apply.")
        return

    written = 0
    for item in planned:
        if store.remember(**item):
            written += 1
    decision("")
    decision(f"  DONE. {written} new events stored "
             f"({len(planned) - written} were already there).")
    decision(f"  {store.status()}")


if __name__ == "__main__":
    main(apply="--apply" in sys.argv)
