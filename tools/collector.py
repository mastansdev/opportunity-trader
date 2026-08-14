"""
==========================================================
The Telegram collector -- its own process, its own terminal
==========================================================
    py tools/collector.py              collect, forever
    py tools/collector.py --once       one pass, then stop
    py tools/collector.py --catchup    fill the overnight gap first

    "TODAY WORK BELONGS TO TELEGRAM REPAIR & KEEPING MAIN.PY AS
     STANDALONE RUN + REMAINING RUN IN OTHER TERMINALS ......
     PLS DO NOT COMBINE MAIN.PY"
                                    -- operator, 3 August 2026

WHY THIS FILE EXISTS
--------------------
He asked for this before the first live session and I kept Telegram
inside main.py. Every failure of that morning came from that one
decision:

    08:19  nightly's telegram step reported "ok  0.0 min" and read
           nothing -- the lock had detected its own process
    08:51  main.py's 96-hour catch-up was on channel 2 of 9 at 3.5
           minutes a page, with the market opening at 09:15
    08:55  catch-up skipped; the first poll's AI grading then blocked
           startup for another twelve minutes
    09:03  the Telethon client, connected on the MAIN thread, was used
           by the POLLER thread and refused --

               "The asyncio event loop must not change after
                connection"

           All nine channels dead for the entire session.

Four failures, one cause. A chat reader was sharing a process, a
thread and a startup sequence with a trading engine.

WHAT THIS FIXES, STRUCTURALLY
-----------------------------
ONE PROCESS, ONE LOOP, ONE OWNER. The Telethon client is created and
used on this process's main thread and nowhere else, so the event-loop
error cannot happen. There is no second thread to disagree with.

NOTHING HERE CAN DELAY A TRADE. main.py no longer imports any of it.
If this process is slow, stuck, rate-limited or dead, the tick feed,
the ORB clock, the dashboard and every order path are untouched.

ONE WRITER. This is the only process that writes data/telegram.db.
main.py opens data/stock_events.db READ-ONLY in practice -- it calls
recent() and for_symbol() and never remember(). Two writers on a
Windows drive is what corrupted the store on 2 August.

RUN IT IN ITS OWN TERMINAL
--------------------------
    Terminal 1   py main.py                trading
    Terminal 2   py tools/collector.py     Telegram

Start order does not matter. Either can be restarted without the
other noticing.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import signal
import sys
import threading
import time
from datetime import datetime

sys.path.insert(0, ".")

from core.logger import decision, diagnostic, warn      # noqa: E402
from core.master_loader import MasterLoader             # noqa: E402
from core.runlock import TelegramReaderLock, held_by_another  # noqa: E402

POLL_SECONDS = 90

# How often the global picture is re-fetched during the session. Ten
# minutes is often enough that crude or the dollar moving is news while
# it still matters, and rare enough that eighteen throttled requests
# never stack up on each other.
WORLD_REFRESH_MINUTES = 10
# A failing poll must not become a hot loop against Telegram's servers.
BACKOFF_SECONDS = (5, 15, 60, 180)

_STOP = {"now": False}
# The feed threads this process owns, so Ctrl+C can stop them.
_FEEDS = []


def _line():
    decision("=" * 70)


def _stop_on_signal(*_args):
    """Ctrl+C is a decision, not a crash.

    Every message is committed as it is stored, so stopping costs
    nothing but the poll in flight.

    ---- IT LOOKED LIKE IT WAS IGNORING HIM. 3 August 2026. ----

        "py tools/collector.py is not closing in from 1st run. i tried
         to close ctrl+c"

    signal.signal() REPLACES the default handler, so Ctrl+C stopped
    raising KeyboardInterrupt and only set this flag -- and the flag
    was read between passes. One pass is nine channels with OCR on
    every image. He pressed Ctrl+C, the terminal did nothing visible
    for minutes, and there was no way to tell a slow stop from a hang.

    Two fixes. The flag is now checked between CHANNELS, not just
    between passes, and a SECOND Ctrl+C leaves immediately. Waiting is
    a choice he should be able to withdraw.
    """
    if _STOP["now"]:
        # He asked twice. Nothing here is mid-write -- every message is
        # committed as it is stored -- so leaving now costs the poll in
        # flight and nothing else.
        decision("")
        decision("  Second Ctrl+C -- leaving now.")
        _release_lock_and_exit()
    _STOP["now"] = True
    decision("")
    decision("  Stopping. Press Ctrl+C again to leave immediately.")


def _release_lock_and_exit(code=130):
    """Drop the reader lock before going, so the next run is not told
    it is already running by a process that no longer exists."""
    try:
        from core.runlock import release_if_mine
        release_if_mine()
    except Exception:                                      # noqa: BLE001
        pass
    sys.stdout.flush()
    # os._exit, not sys.exit: sys.exit raises inside the signal handler
    # and unwinds back into the poll he is trying to escape from.
    os._exit(code)


def build():
    """The feed, the event store and the grader. None are optional here.

    This is the whole job of this process, so unlike main.py -- where a
    missing grader must never stop a session -- a failure to build is
    worth saying loudly and exiting on.
    """
    from core.telegram_feed import TelegramFeed
    from core.telegram_client import build_reader
    from core.stock_events import StockEvents

    loader = MasterLoader()
    loader.load()

    events = None
    try:
        events = StockEvents()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Event store unavailable ({exc}). Messages will be "
             f"collected; events will not be filed.")

    # ==========================================================
    # THE MASTER SWITCH IS NOW HONOURED.  10 August 2026.
    # ==========================================================
    #
    #     "remove the bridge of API , now i'm ready to pay . until i
    #      see the results i'll not use API paid . we have the
    #      resources still bot doesn't know them."
    #
    # config.AI_ENABLED has been False since it was written -- "master
    # switch. Nothing calls out while False." It was not true. This
    # built the grader unconditionally, so on 10 August every call went
    # out and every one came back:
    #
    #     Your credit balance is too low to access the Anthropic API
    #
    # Twenty-five events waiting, none graded, all afternoon, as DEBUG
    # lines nobody would read.
    #
    # AND IT WAS NEVER NEEDED FOR THE GRADE. He said so on 8 August:
    # "bot is getting the sorted data & ready to use format. then why
    # still bot required any additional Haiku vision or ocr's". The
    # cards arrive with EXCELLENT / GREAT / GOOD already printed on
    # them; core/watchlist_builder.py reads that text directly. The AI
    # was a second opinion on a question already answered.
    grader = None
    try:
        from config import AI_ENABLED
    except Exception:                                      # noqa: BLE001
        AI_ENABLED = False
    if events is not None and AI_ENABLED:
        try:
            from core.ai_news import AiNewsGrader
            grader = AiNewsGrader(master_loader=loader)
        except Exception as exc:                           # noqa: BLE001
            warn(f"  AI grading off ({exc}). Events keep their kind and "
                 f"carry no direction.")
    elif events is not None:
        decision("  AI grading OFF (config.AI_ENABLED is False). No paid "
                 "call leaves this process. Grades come from the cards "
                 "themselves, which already carry them.")

    impact = None
    try:
        from core.news_impact import NewsImpact
        impact = NewsImpact(master_loader=loader)
    except Exception as exc:                               # noqa: BLE001
        diagnostic(f"  News impact off ({exc}).")

    # ---- THE CLIENT IS BUILT HERE, ON THIS THREAD, AND NOWHERE ELSE.
    #
    # This single line is the fix for 09:03. telethon.sync binds a
    # client to the event loop of the thread that connected it. In
    # main.py the connection happened on the main thread during startup
    # and the 90-second poller -- a different thread -- then tried to
    # use it. Here there is no other thread to hand it to.
    feed = TelegramFeed(client=build_reader(), master_loader=loader,
                        stock_events=events, ai_news=grader,
                        news_impact=impact)
    return feed, events


def main(once=False, catchup=False):
    signal.signal(signal.SIGINT, _stop_on_signal)

    _line()
    decision("  TELEGRAM COLLECTOR -- reads the channels, files events")
    decision(f"  pid {os.getpid()}.  main.py does not do any of this.")
    _line()

    busy, who = held_by_another()
    if busy:
        warn(f"  ALREADY RUNNING: {who}")
        warn("  Two readers share one Telethon session and one store, "
             "and both end up damaged. Nothing was read.")
        sys.exit(2)

    try:
        feed, events = build()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  Could not start: {exc}")
        sys.exit(1)

    decision(f"  WATCHING {len(feed.channels)} channel(s)")
    for entry in feed.channels:
        decision(f"    {entry.get('name') or entry.get('handle')}")
    if events is not None:
        decision(f"  {events.status().get('total', 0)} event(s) already on "
                 f"file.")
    _line()

    if not once:
        threading.Thread(target=world_watcher, name="world",
                         daemon=True).start()
        decision(f"  WORLD FEED every {WORLD_REFRESH_MINUTES} min "
                 f"(crude, gold, dollar, US yields, currencies)")
        # THE PRE-OPEN BOOK, 09:12, automatically. Until now the only
        # thing that ever wrote data/preopen.json was a tool run by
        # hand -- so the PRE tab showed yesterday's auction, silently,
        # on any morning it was forgotten.
        threading.Thread(target=preopen_watcher, name="preopen",
                         daemon=True).start()
        decision("  PRE-OPEN BOOK at 09:12 (NSE call auction)")
        for label in start_feeds():
            decision(f"  {label}")
        _line()

    with TelegramReaderLock("collector"):
        if catchup:
            decision("  Filling the gap since the last run "
                     "(--catchup). This walks back and is slow.")
            try:
                feed.catch_up()
            except Exception as exc:                       # noqa: BLE001
                warn(f"  Catch-up failed ({exc}). Live collection is "
                     f"unaffected.")

        failures = 0
        passes = 0
        while not _STOP["now"]:
            started = time.time()
            try:
                # Asked before every channel, so Ctrl+C is answered in
                # seconds instead of at the end of a nine-channel pass.
                feed.poll(stop_check=lambda: _STOP["now"])
                failures = 0
            except Exception as exc:                       # noqa: BLE001
                # A poll that throws must never end the process. These
                # channels are somebody else's servers and they will
                # rate-limit, time out and redesign without warning.
                failures += 1
                wait = BACKOFF_SECONDS[min(failures - 1,
                                           len(BACKOFF_SECONDS) - 1)]
                warn(f"  Poll failed ({exc}). Retrying in {wait}s "
                     f"(failure {failures}).")
                if _sleep(wait):
                    break
                continue

            passes += 1
            if passes == 1 or passes % 20 == 0:
                total = events.status().get("total", 0) if events else 0
                decision(f"  [{time.strftime('%H:%M:%S')}] pass {passes}, "
                         f"{total} event(s) on file.")

            if once:
                break
            spent = time.time() - started
            if _sleep(max(0.0, POLL_SECONDS - spent)):
                break

    for feed in _FEEDS:
        try:
            feed.stop()
        except Exception:                                  # noqa: BLE001
            pass

    _line()
    decision("  Collector stopped. Trading was never affected by this "
             "process, and is not affected by it stopping.")
    _line()


def start_feeds():
    """NSE filings and the RSS news, moved out of main.py.

    ---- THE SECOND TERMINAL, FINISHED. 3 August 2026. ----

        "why still NEWS is printing in main.py terminal ? ... in live
         markets only 2 terminals - main.py & news (news+rss++nse+bse+9
         pro channels)"

    Telegram moved days ago because it already had a database. These
    two had none -- AnnouncementWatcher kept its filings in a list and
    NewsWatcher kept its items in another -- so moving the polling
    would have taken the data with it, and results_gate reads those
    filings to decide whether 83 reporting stocks may be traded.

    core/feed_store.py gave them a shared home. This process writes it;
    main.py opens the same file and only reads.

    Returns a list of lines to print, so a feed that failed to start is
    visible here rather than discovered by an empty panel at 09:20.
    """
    lines = []
    try:
        from core.feed_store import FeedStore
        store = FeedStore()
    except Exception as exc:                               # noqa: BLE001
        warn(f"  FEED STORE unavailable ({exc}). Filings and news will "
             f"not be collected; Telegram is unaffected.")
        return lines

    try:
        from config import (ANNOUNCEMENT_LOOKBACK_HOURS,
                            ANNOUNCEMENT_POLL_SECONDS, NEWS_POLL_SECONDS)
        from core.announcement_watcher import AnnouncementWatcher
        watcher = AnnouncementWatcher(
            poll_seconds=ANNOUNCEMENT_POLL_SECONDS,
            lookback_hours=ANNOUNCEMENT_LOOKBACK_HOURS,
            store=store)
        watcher.start()
        _FEEDS.append(watcher)
        lines.append(f"NSE FILINGS every {ANNOUNCEMENT_POLL_SECONDS}s "
                     f"-> data/feeds.db")
    except Exception as exc:                               # noqa: BLE001
        warn(f"  FILINGS feed did not start ({exc}).")

    try:
        from config import NEWS_POLL_SECONDS
        from core.news_watcher import NewsWatcher
        news = NewsWatcher(poll_seconds=NEWS_POLL_SECONDS, store=store)
        news.start()
        _FEEDS.append(news)
        lines.append(f"RSS NEWS every {NEWS_POLL_SECONDS}s "
                     f"-> data/feeds.db")
    except Exception as exc:                               # noqa: BLE001
        warn(f"  NEWS feed did not start ({exc}).")

    return lines


def world_watcher(minutes=WORLD_REFRESH_MINUTES):
    """Keep the overnight numbers overnight numbers no longer.

    ---- 3 August 2026 ----

        "bot need to monitor continuously the news, events, global
         risks = bond yields, currency, commodities"
        "Market Situational Awareness is the ability to understand the
         complete market environment before making any trading decision
         & during open position"

    main.py builds PreMarket(fetcher=None) -- it reads what the 08:45
    job wrote and never fetches again. Crude, gold, the dollar and both
    US yields were therefore frozen from before the open, and the
    awareness tile was reporting a morning snapshot at 14:00 as though
    it were current. "During open position" was not covered at all.

    This belongs here and not in main.py. Refreshing means eighteen
    HTTP calls to a third party, and nothing that reaches over the
    internet on a timer goes anywhere near the process that places
    orders -- the same reason the channels moved out.

        "PLS DO NOT COMBINE MAIN.PY"

    Its own thread, because a refresh takes tens of seconds with the
    throttle spacing and must not hold up a Telegram poll. It writes
    the same data/premarket.json main.py already re-reads on change.
    """
    try:
        from core.premarket import PreMarket, requests_fetcher
    except Exception as exc:                                # noqa: BLE001
        warn(f"  World feed unavailable ({exc}). Overnight numbers will "
             f"stay as the morning job left them.")
        return

    store = PreMarket(fetcher=requests_fetcher())
    while not _STOP["now"]:
        try:
            fresh = store.refresh()
            if fresh:
                decision(f"  [WORLD] {fresh} global number(s) refreshed.")
            else:
                # Not fatal and not silent. core/awareness.py reads the
                # same failure and says "world data is not updating"
                # rather than reciting an older number as today's.
                warn("  [WORLD] Refresh collected nothing. Previous "
                     "figures kept and marked stale.")
        except Exception as exc:                            # noqa: BLE001
            warn(f"  [WORLD] Refresh failed ({exc}). Trading unaffected.")
        if _sleep(minutes * 60):
            break


def preopen_watcher():
    """Collect NSE's pre-open book once, at 09:12, every session.

    ==========================================================
        "IN MAIN.PY = ... PRE-OPEN SESSION UPDATE AT 09:10 AM
         EVERYDAY"                 -- operator, 4 August 2026
    ==========================================================

    It was not happening. main.py builds PreOpen(fetcher=None) -- it
    only READS data/preopen.json -- and the single thing in this repo
    that ever wrote that file was tools/preopen_gaps.py, a tool run by
    hand. So the PRE-MARKET tab showed yesterday's book, or nothing,
    on any morning he did not remember to run it.

    Nothing about it says so. A stale pre-open looks exactly like a
    quiet pre-open.

    IT LIVES HERE, NOT IN main.py. It is an HTTP call to NSE on a
    timer, and nothing that reaches over the internet on a timer goes
    near the process that places orders:

        "PLS DO NOT COMBINE MAIN.PY"

    09:12 because NSE's call auction runs 09:00-09:08 with order
    matching to 09:12; read before that and the book is still forming.
    One shot per day, then it stops -- re-reading after 09:15 would
    overwrite the auction result with whatever the endpoint returns
    once regular trading has begun.
    """
    try:
        from core.nse_quotes import requests_fetcher
        from core.preopen import PreOpen
    except Exception as exc:                                # noqa: BLE001
        warn(f"  Pre-open unavailable ({exc}). The PRE tab will show "
             f"whatever was last stored.")
        return

    store = PreOpen(fetcher=requests_fetcher())
    done_for = None
    while not _STOP["now"]:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")
        # Between 09:12 and 09:15, and not already collected today.
        ready = (now.hour == 9 and 12 <= now.minute < 15)
        if ready and done_for != today:
            try:
                count = store.refresh()
                if count:
                    done_for = today
                    decision(f"  [PREOPEN] {count} stocks collected from "
                             f"the call auction.")
                else:
                    # NOT marked done -- so it retries inside the window
                    # rather than losing the auction for the day on one
                    # bad request. The pre-open happens once.
                    warn("  [PREOPEN] Collected nothing. Will retry "
                         "until 09:15.")
            except Exception as exc:                        # noqa: BLE001
                warn(f"  [PREOPEN] Failed ({exc}). Trading unaffected.")
        if _sleep(30):
            break


def _sleep(seconds):
    """Sleep in short slices so Ctrl+C is answered immediately.

    Returns True if we were asked to stop while sleeping.
    """
    end = time.time() + seconds
    while time.time() < end:
        if _STOP["now"]:
            return True
        time.sleep(0.25)
    return _STOP["now"]


if __name__ == "__main__":
    main(once="--once" in sys.argv, catchup="--catchup" in sys.argv)
