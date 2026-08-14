"""
==========================================================
Fetch the channel history, any day, without starting the bot
==========================================================
    py tools/telegram_catchup.py            look, fetch nothing
    py tools/telegram_catchup.py --apply    walk back and store

Reads only. Places no orders, touches no positions.

WHY THIS IS SEPARATE FROM main.py
---------------------------------
1 August 2026, a Saturday. The operator restarted the bot to test the
catch-up fix and got:

    [CALENDAR] 2026-08-01 is not a trading day (weekend).
    Next session: 2026-08-03. Nothing to do -- exiting.

Correct behaviour for a trading bot, and exactly backwards for
COLLECTION. The weekend is when the gap forms: 34% of what these
channels publish arrives outside market hours, and Friday close to
Monday open is 65 hours of it. Being unable to collect on the one day
the hole is opening is the wrong shape.

So collection is available on its own, any day, without the engine,
the feed, the broker or the dashboard.

WHAT IT DOES
------------
Walks t.me/s/<channel> backwards a page at a time -- the same
mechanism a browser uses when you scroll up -- and stores anything it
does not already have. It stops when a page adds NOTHING NEW twice in
a row, which is the only signal that means "we already hold this
ground". Measured 1 August: Telegram serves pages from three months
back without complaint, so depth is not the constraint.

It also files the recovered messages as events and, if the key is
present, gives the ungraded ones a direction -- so a Saturday run
leaves Monday morning with the weekend already read.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3
import sys

sys.path.insert(0, ".")

from core.logger import decision, warn                     # noqa: E402
from core.runlock import TelegramReaderLock, held_by_another  # noqa: E402
from core.master_loader import MasterLoader                # noqa: E402
from core.stock_events import StockEvents                  # noqa: E402
from core.telegram_feed import TelegramFeed, CATCH_UP_PAGES  # noqa: E402
from core.telegram_client import build_reader              # noqa: E402


def _line():
    decision("-" * 70)


def _counts(db_path):
    """Messages held per channel, and the id range -- the gap is the
    difference between the span and the count."""
    out = {}
    try:
        conn = sqlite3.connect(db_path)
        for name, lo, hi, n in conn.execute(
                "SELECT channel, MIN(CAST(message_id AS INTEGER)), "
                "MAX(CAST(message_id AS INTEGER)), COUNT(*) "
                "FROM messages GROUP BY channel"):
            out[name] = (lo, hi, n)
        conn.close()
    except sqlite3.Error as exc:
        warn(f"  Could not read telegram.db: {exc}")
    return out


def _report(title, counts):
    decision(f"  {title}")
    for name, (lo, hi, n) in sorted(counts.items()):
        span = (hi - lo + 1) if lo is not None and hi is not None else 0
        gap = span - n
        decision(f"    {name:22} hold {n:4}  of {span:4} published  "
                 f"missing {gap}")


def main(apply=False, pages=CATCH_UP_PAGES):
    decision("=" * 70)
    decision("  TELEGRAM CATCH-UP -- read the history, no trading")
    decision("=" * 70)

    # ---- ONE READER AT A TIME. 2 August 2026. ----
    #
    #     "shall i run this py tools/nightly.py now? in one terminal
    #      py tools/telegram_catchup.py --apply is running right now"
    #
    # He asked, so nothing broke. Telethon keeps its session in SQLite
    # and so does the message store; two processes writing both gives
    # "database is locked" -- unreliably, and usually discovered at
    # 08:45 with a session file that has to be regenerated.
    #
    # Refuses rather than corrupts. See core/runlock.py: a lock older
    # than any honest run is ignored, so a killed process can never
    # block tomorrow night.
    busy, who = held_by_another()
    if busy:
        warn(f"  ALREADY RUNNING: {who}")
        warn("  Two readers share one Telegram session and one store, "
             "and both end up damaged. Nothing was read.")
        warn("  Wait for that one to finish, then run this again.")
        # ---- NON-ZERO, 3 August 2026. ----
        #
        # This was a bare `return`, so the process exited 0 and
        # tools/nightly.py recorded its first step as:
        #
        #     ok  telegram  0.0 min
        #
        # A refusal to read is not a successful read. The night went on
        # to five more steps, all of which worked, and printed a summary
        # saying everything was fine while telegram.db still held
        # Sunday's last message.
        sys.exit(2)

    events = None
    grader = None
    loader = MasterLoader()
    loader.load()
    try:
        events = StockEvents()
        from core.ai_news import AiNewsGrader
        grader = AiNewsGrader(master_loader=loader)
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Event filing unavailable ({exc}). Messages will still "
             f"be collected.")

    feed = TelegramFeed(client=build_reader(), master_loader=loader,
                        stock_events=events, ai_news=grader)

    _line()
    # Which channels this run will actually read. If the PRO folder was
    # picked up they appear here; if it was not, the list is the four
    # public ones and the warning above says why.
    decision(f"  WATCHING {len(feed.channels)} channel(s)")
    for entry in feed.channels:
        decision(f"    {entry.get('name') or entry.get('handle')}")
    _line()
    before = _counts(feed.db_path)
    _report("BEFORE", before)
    _line()

    if not apply:
        decision("  DRY RUN -- nothing was fetched.")
        decision("  To walk the history back and store what is missing:")
        decision("      py tools/telegram_catchup.py --apply")
        return

    # WHAT THIS RUN COSTS, MEASURED, NOT PROMISED.
    #
    #     "in 2 runs same output it printed & AI will use 2 times which
    #      will cost us"          -- operator, 1 August 2026
    #
    # It does not -- a message already held is not re-stored, grading
    # only runs when something new WAS stored, and the query that picks
    # work asks for ai_direction IS NULL, so a graded event can never
    # be selected twice. But none of that was visible from the output,
    # and "trust me, it is fine" is not an answer about money.
    #
    # So the ledger is read before and after, and the difference is
    # printed. A second run in a row now says Rs 0.00 out loud.
    spent_before = None
    try:
        from core.ai_budget import AiBudget
        meter = AiBudget()
        spent_before = meter.spent_this_month()
    except Exception:                                      # noqa: BLE001
        meter = None

    decision(f"  walking back up to {pages} pages per channel, stopping at")
    decision(f"  anything older than {feed.keep_hours}h.")
    decision("")
    decision("  THIS IS SLOW ON THE IMAGE CHANNELS. Day Trader Telugu is")
    decision("  three-quarters pictures, and every new one is downloaded and")
    decision("  read by OCR -- a few seconds each. A page of 100 can take")
    decision("  minutes. Each page prints twice: once when it is asked for,")
    decision("  once when it has been stored.")
    decision("")
    feed.poll()
    recovered = feed.catch_up(max_pages=pages)

    _line()
    after = _counts(feed.db_path)
    _report("AFTER", after)
    _line()
    decision(f"  messages recovered : {recovered}")

    if meter is not None and spent_before is not None:
        spent_after = meter.spent_this_month()
        if spent_after is not None:
            cost = spent_after - spent_before
            if cost <= 0:
                decision("  AI cost this run   : Rs 0.00 -- nothing new "
                         "needed a verdict")
            else:
                decision(f"  AI cost this run   : Rs {cost:.2f}")
            decision(f"  {meter.report()}")

    decision("")
    decision("  Nothing was traded. Run this after the close, or on a")
    decision("  weekend, and Monday opens with the gap already read.")
    decision("  Safe to run twice -- the second run costs nothing.")


if __name__ == "__main__":
    # ---- Ctrl+C IS A DECISION, NOT A CRASH. 1 August 2026. ----
    #
    # Telegram stopped serving images mid-run and the operator had no
    # way to stop the tool except Ctrl+C, which answered with forty
    # lines of asyncio traceback ending in GetQueuedCompletionStatus.
    # Nothing was lost -- every page is committed as it is stored --
    # but there was no way to tell that from the screen.
    try:
        # The lock is taken HERE, around the whole run, so it is
        # released on a clean finish, on Ctrl+C, and on a crash alike.
        with TelegramReaderLock("telegram_catchup"):
            main(apply="--apply" in sys.argv)
    except KeyboardInterrupt:
        decision("")
        decision("  Stopped. Every page read so far is already saved --")
        decision("  the store is committed page by page, not at the end.")
        decision("  Run the same command again to carry on from here.")
        sys.exit(0)
