"""
==========================================================
Take the advertisements back out of the store
==========================================================

    py tools/clean_the_junk.py            # show what would go
    py tools/clean_the_junk.py --do-it    # back up, then remove

    "next clean junk no matter time of arrivals, remove 13 junk
     channel rows"              -- the operator, 6 September 2026

core/telegram_feed.py now refuses these at the door, so nothing new
arrives. This is for what got in before that rule existed.

TWO KINDS OF JUNK

  ADVERTISEMENTS -- 26 of 1,610 messages. YouTube shorts about gold
  lockers and buying cars, Instagram launch posts, an affiliate
  insurance link, "add our channels as a folder" invites. Four of them
  were filed against ACC, the cement company, because a short titled
  "Gold in Bank Locker? Not Safe?" matched it.

  GHOST CHANNELS -- 13 rows in feed_watermark that have never
  delivered a single message: A, B, c0 through c8, MoneyPurse, and
  EARNINGS PULSE in capitals (the real "Earnings Pulse" has 104
  messages and is untouched). The c0-c8 names come from
  tests/test_collector_stops.py, which builds a feed with
  TelegramFeed.__new__() -- skipping __init__, so the instance has no
  db_path and falls back to the live store. The test suite has been
  writing into his production data.

IT BACKS UP FIRST, ALWAYS. His rule: "i do not want to miss / loose
any info even by mistake". The copy is data/telegram.db.pre-clean-
<stamp> and nothing is deleted until it exists.

NOTHING HERE TOUCHES TRADING. data/telegram.db is read by the
collector and the event builder; core/rules.py, core/ranker.py,
core/auto_entry.py, core/engine.py, core/why_moving.py and
core/results_gate.py do not open it. Removing a row cannot change a
gate, a stop or a size.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import shutil
import sqlite3
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from core.telegram_feed import is_just_a_link                # noqa: E402

STORE = os.path.join("data", "telegram.db")


def look(store=STORE):
    """What is junk, without touching anything."""
    conn = sqlite3.connect(f"file:{store}?mode=ro", uri=True, timeout=10)
    messages = conn.execute(
        "SELECT channel, message_id, at, text, symbols FROM messages"
    ).fetchall()
    ads = [r for r in messages if is_just_a_link(r[3])]

    delivered = {r[0] for r in conn.execute(
        "SELECT DISTINCT channel FROM messages")}
    marks = conn.execute(
        "SELECT channel, messages FROM feed_watermark").fetchall()
    conn.close()
    # A ghost has never delivered AND carries no message count. Both
    # conditions, so a channel that has simply gone quiet is kept.
    ghosts = [r[0] for r in marks
              if r[0] not in delivered and not (r[1] or 0)]
    return {"messages": len(messages), "ads": ads, "ghosts": sorted(ghosts)}


def clean(store=STORE):
    """Back up, then remove. Returns what went."""
    found = look(store)
    if not found["ads"] and not found["ghosts"]:
        return dict(found, backup=None, removed_messages=0,
                    removed_channels=0)

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = f"{store}.pre-clean-{stamp}"
    shutil.copy2(store, backup)
    if not os.path.exists(backup):
        raise RuntimeError("the backup was not written -- nothing removed")

    conn = sqlite3.connect(store, timeout=30)
    gone_m = 0
    for channel, message_id, _at, _text, _symbols in found["ads"]:
        conn.execute("DELETE FROM messages WHERE channel = ? "
                     "AND message_id = ?", (channel, message_id))
        gone_m += 1
    gone_c = 0
    for channel in found["ghosts"]:
        conn.execute("DELETE FROM feed_watermark WHERE channel = ?",
                     (channel,))
        gone_c += 1
    conn.commit()
    conn.close()
    return dict(found, backup=backup, removed_messages=gone_m,
                removed_channels=gone_c)


def main(argv=None):
    argv = list(argv if argv is not None else sys.argv[1:])
    doing = "--do-it" in argv

    found = look()
    print()
    print(f"  messages held        {found['messages']:,}")
    print(f"  advertisements       {len(found['ads'])}")
    print(f"  channels that have never delivered   "
          f"{len(found['ghosts'])}")
    print()
    for channel, _mid, at, text, symbols in found["ads"][:40]:
        line = str(text or "")[:56].replace("\n", " ")
        print(f"     {str(channel)[:18]:<20}{str(at)[:10]}  {line}"
              + (f"   [filed against {symbols}]" if symbols else ""))
    print()
    if found["ghosts"]:
        print("     " + ", ".join(found["ghosts"]))
    print()

    if not doing:
        print("  Nothing removed. Run again with --do-it to remove them.")
        print("  A backup is written before anything is deleted.")
        return 0

    got = clean()
    print(f"  backed up to         {got['backup']}")
    print(f"  messages removed     {got['removed_messages']}")
    print(f"  channel rows removed {got['removed_channels']}")
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
