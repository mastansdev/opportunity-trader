"""
==========================================================
Telegram tells the bot, instead of the bot asking
==========================================================

    "right now the bot is asking telegram channels for new post or
     reverse ? if telegram tells bot to check then it will be easy to
     bot i think. this will solves the issue of reading all empty to
     only channels posting information"
                                -- the operator, 5 September 2026

It was asking. POLL_SECONDS is 90 and every channel was asked on every
pass whether or not anything had been published -- about 400 requests
an hour, most of them answering "nothing".

He is right that Telegram will tell us instead. NewMessage rides on the
connection that is already open and already authorised, and a post
arrives the moment it is published rather than up to 90 seconds later.
For the three channels where "delay in getting their data into bot will
cost us money", that is the whole of the lag: measured 18-29 August,
Day Trader Telugu's median from posted to stored was 5.5 minutes and
its p90 24.9.

WHY THE POLLING STAYS. Telegram pushes to a client that is CONNECTED
and queues nothing for one that is not. A dropped socket, a closed lid,
a DNS blink -- everything published in the gap is simply never sent. So
push replaces the ASKING and never the CATCHING UP. poll(), catch_up()
and fill_gaps() are untouched: push is the fast path, the poll is the
floor.

WHY ONE THREAD NOW. start() ran two: the fast loop for the daily three,
the slow loop for the rest, both calling poll() on the same telethon
client. That works for ask-and-answer calls -- the sync wrapper
serialises them onto its own event loop, and no error about it has ever
been recorded on any channel. It stops working the moment anything
HOLDS that loop, which is exactly what listening does. Two owners and a
held loop is "this event loop is already running", on the path that
feeds the ranker.

So the two loops became one, and the wait between polls became a wait
that LISTENS. The thread was going to sleep for 90 seconds anyway; now
Telegram delivers during those 90 seconds and the client is free again
when they are up. Same cadence, same safety net, nothing new blocked.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timezone

import pytest

from core.telegram_feed import TelegramFeed


class PushReader:
    """A reader that can be told to deliver a post."""

    def __init__(self, can_push=True):
        self.can_push = can_push
        self.handler = None
        self.watched = None
        self.pumped = 0
        self.fetches = 0

    def watch(self, handles, on_message):
        if not self.can_push:
            return 0
        self.watched = list(handles)
        self.handler = on_message
        return len(self.watched)

    def pump(self, seconds):
        self.pumped += 1
        return bool(self.can_push)

    def fetch(self, channel, limit=30, before=None, since_id=None,
              ids=None):
        self.fetches += 1
        return []

    def deliver(self, handle, text, mid=1):
        self.handler(handle, {
            "id": mid, "at": datetime.now(timezone.utc), "text": text,
            "photos": [], "photo_data": [], "links": [], "hashtags": [],
            "url": f"https://t.me/{handle}/{mid}"})


@pytest.fixture()
def feed():
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    return TelegramFeed(db_path=path,
                        channels=[{"name": "Day Trader Telugu",
                                   "handle": "daytradertelugu"}])


# ------------------------------------------------------------------
# the push itself
# ------------------------------------------------------------------

def test_a_pushed_post_is_stored(feed):
    reader = PushReader()
    feed.client = reader
    assert feed.listen() == 1
    reader.deliver("daytradertelugu",
                   "HAL wins order worth 2,205 crore from MoD", mid=42)
    conn = sqlite3.connect(feed.db_path)
    rows = conn.execute("SELECT message_id, text FROM messages").fetchall()
    conn.close()
    assert rows and rows[0][0] == "42"
    assert "2,205" in rows[0][1]


def test_the_channel_is_matched_by_handle_or_by_title(feed):
    """Private channels have no @handle and are known by their title.
    A pushed post from one must land in the same row a polled one does."""
    reader = PushReader()
    feed.client = reader
    feed.listen()
    reader.deliver("Day Trader Telugu", "by title", mid=7)
    conn = sqlite3.connect(feed.db_path)
    n = conn.execute("SELECT COUNT(*) FROM messages "
                     "WHERE channel='Day Trader Telugu'").fetchone()[0]
    conn.close()
    assert n == 1


def test_a_post_from_an_unwatched_channel_is_ignored(feed):
    """Storing it under a name nothing else uses makes a row no panel
    and no matcher will ever read."""
    reader = PushReader()
    feed.client = reader
    feed.listen()
    reader.deliver("somebody_else", "not ours", mid=5)
    conn = sqlite3.connect(feed.db_path)
    n = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    conn.close()
    assert n == 0


def test_a_handler_that_throws_cannot_take_the_loop_down(feed):
    """This runs inside telethon's event loop. An exception escaping it
    would stop the loop and with it the polling that is the safety
    net."""
    reader = PushReader()
    feed.client = reader
    feed.listen()
    feed.db_path = "Z:/nowhere/that/exists/telegram.db"
    reader.deliver("daytradertelugu", "a post nobody can store", mid=9)


# ------------------------------------------------------------------
# and what must not break
# ------------------------------------------------------------------

def test_a_reader_that_cannot_push_is_a_normal_answer(feed):
    """The public web view serves pages and cannot push. Zero is not a
    failure -- everything still works, more slowly."""
    feed.client = PushReader(can_push=False)
    assert feed.listen() == 0


def test_a_reader_with_no_watch_at_all_is_fine(feed):
    class OldReader:
        def fetch(self, channel, limit=30, before=None, since_id=None):
            return []

    feed.client = OldReader()
    assert feed.listen() == 0


def test_the_polling_is_still_there():
    """Telegram queues nothing for a laptop that is off. Push replaces
    the asking, never the catching up."""
    import io
    src = io.open("core/telegram_feed.py", encoding="utf-8").read()
    loop = src[src.index("        def _loop():"):]
    loop = loop[:loop.index("self._thread = threading.Thread")]
    assert "self.poll(" in loop, \
        "push is the fast path; the poll is the floor"
    assert "self._stop.wait(every_seconds)" in loop, \
        "a reader that cannot push must not spin"


def test_the_pushed_count_is_readable(feed):
    """Zero an hour into the session means the listener is not
    delivering and the polling is carrying the whole feed. That works,
    and is slower, and must not be discovered by accident."""
    reader = PushReader()
    feed.client = reader
    feed.listen()
    assert feed.pushed_count() == 0
    reader.deliver("daytradertelugu", "HAL wins 2,205 crore order", mid=3)
    assert feed.pushed_count() == 1


def test_the_collector_listens_too():
    """Listening was wired into TelegramFeed.start(), which spawns a
    thread and is what main.py uses. tools/collector.py never calls
    start() -- it drives poll() from its own loop -- so the listener
    would have sat unregistered in the one process he runs by hand every
    morning. Machinery built and never called, again."""
    import io as _io
    src = _io.open("tools/collector.py", encoding="utf-8").read()
    assert "feed.listen()" in src, "the collector never starts listening"
    assert "feed.client.pump(" in src, "the wait between passes must listen"
    assert "_sleep(wait_for)" in src, \
        "a reader that cannot push must not spin"


def test_only_one_thread_owns_the_connection():
    """Two owners and a held event loop is 'this event loop is already
    running', on the path that feeds the ranker."""
    import io
    src = io.open("core/telegram_feed.py", encoding="utf-8").read()
    block = src[src.index("    def start(self, every_seconds=POLL_SECONDS):"):]
    block = block[:block.index("    def stop(self):")]
    assert block.count("threading.Thread(") == 1, \
        "the listener and the poller must share one thread"
