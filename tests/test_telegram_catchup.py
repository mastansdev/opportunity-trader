"""
==========================================================
The weekend must not be a hole
==========================================================

    "real gap as far i concerned about after my terminal(laptop) close
     to next opening. & weekends data?"
    "we cannot loose some important in weekends"

THE SIZE OF THE HOLE, measured on the real channels
---------------------------------------------------
    one page of t.me/s/            ~20 posts
    News Pulse                     ~10.5 posts/hour
    Day Trader Telugu              ~7.1
    Earnings Pulse                 ~6.1
    posted OUTSIDE market hours    34% of everything

Friday 15:30 to Monday 09:00 is 65.5 hours -- 400 to 700 posts per
channel. Monday's first poll recovered twenty of them and said
nothing about the rest.

HOW IT IS CLOSED
----------------
Telegram paginates these pages itself and publishes the mechanism in
the HTML it serves:

    canonical: /s/earnings_pulse?before=10095
    <a href="https://t.me/s/earnings_pulse?before=10075">

Post ids are sequential integers, so ?before=<id> is the "load older"
link a browser follows when you scroll up.

THE STOP CONDITION IS THE WHOLE DESIGN, AND THE FIRST ONE WAS WRONG
-------------------------------------------------------------------
It first stopped "as soon as a page contains an id we ALREADY HOLD".
That reasoning assumed the gap sits at one END of what we have.

Measured on 1 August 2026, it does not:

    31 July, Earnings Pulse published ids 12587..12702
      116 posts
       81 held
       35 missing, SCATTERED THROUGH THE RANGE

We held the newest and the oldest of that range, so the overlap rule
stopped on page one and declared itself finished with 35 posts still
missing -- among them graded results for companies the bot then went
on to score from three-month-old numbers.

The laptop is off overnight and the page carries twenty at a time, so
holes in the middle are the NORMAL case.

The rule now is: stop when a page stores NOTHING NEW, twice in a row.
That is the only signal that actually means "we already have this
ground", and one barren page alone can happen on a quiet stretch.

Author : H&M Opportunity Trader
==========================================================
"""

import sqlite3

import pytest

from core.telegram_feed import TelegramFeed


def _recent(seed=0):
    """A timestamp inside the retention window, whenever this runs."""
    from datetime import datetime, timedelta
    return (datetime.now()
            - timedelta(minutes=seed % 60)).strftime("%Y-%m-%dT%H:%M:%S")


class Channel:
    """A fake channel with a known history, served a page at a time.

    Ids descend exactly as Telegram's do, and `before` is honoured, so
    the walk under test is the walk that would happen live.
    """

    PAGE = 20

    def __init__(self, newest=1000, total=200):
        self.ids = list(range(newest - total + 1, newest + 1))
        self.requests = []

    def fetch(self, handle, limit=None, before=None):
        self.requests.append(before)
        older = [i for i in self.ids if before is None or i < before]
        page = sorted(older)[-self.PAGE:]
        # ---- THE FIXTURE MUST NOT AGE. 5 August 2026. ----
        #
        # This was hard-dated "2026-08-01T10:...". catch_up() stops at
        # the retention edge (_all_older_than), so the moment the
        # calendar moved past KEEP_HOURS every one of these tests began
        # failing on page one -- five red tests describing a bug that
        # did not exist, while the production walk was correct.
        #
        # A test fixture dated in absolute time is a bomb with a fuse
        # as long as the retention window. Dated relative to now, it
        # tests the walk instead of the date.
        return [{"id": str(i), "at": _recent(i),
                 "text": f"#GAIL - Good Results (post {i})",
                 "photos": [], "hashtags": ["GAIL"]}
                for i in page]


@pytest.fixture
def feed(tmp_path, monkeypatch):
    f = TelegramFeed(
        client=None, master_loader=None,
        db_path=str(tmp_path / "telegram.db"), read_images=False,
        channels=[{"handle": "earnings_pulse", "name": "Earnings Pulse",
                   "kind": "text", "trust_hashtags": True}])
    f.symbols_in = lambda text: ["GAIL"] if "GAIL" in (text or "") else []
    f.names_in = lambda text: []
    # ---- REAL AMBIENT STATE WAS LEAKING IN. 12 August 2026. ----
    #
    # catch_up()'s "pages sized to the gap" feature (10 August) calls
    # core.feed_clock.gaps() with no db_path override, so it always read
    # the REAL data/telegram.db on whatever machine ran the suite --
    # never this fixture's isolated tmp_path one. It went unnoticed
    # because the call sat behind a crash (self._log did not exist,
    # AttributeError, silently swallowed by catch_up()'s own bare
    # except), which happened to fall back to the correct max_pages
    # every time. Fixing that crash (core/telegram_feed.py) exposed
    # this: on a machine where the real channel genuinely was only
    # ~2h behind, these tests' own simulated 65-hour-weekend and
    # empty-database scenarios got capped to 2-3 pages instead of the
    # walk they were built to test, and silently lost hundreds of
    # "recovered" messages. A test must not be able to pass or fail
    # depending on what the real bot last did on this PC.
    monkeypatch.setattr("core.feed_clock.gaps", lambda *a, **k: [])
    return f


def _stored(feed):
    conn = sqlite3.connect(feed.db_path)
    ids = sorted(int(r[0]) for r in
                 conn.execute("select message_id from messages"))
    conn.close()
    return ids


# ---------------------------------------------------------------
# 1. IT WALKS BACK, AND IT STOPS ON OVERLAP
# ---------------------------------------------------------------
def test_a_hole_in_the_middle_is_filled(feed):
    """THE SHAPE THE REAL GAPS HAVE, 1 August 2026.

        31 July, Earnings Pulse published ids 12587..12702
          116 posts
           81 held
           35 missing, scattered through the range

    We held the NEWEST and the OLDEST of that range with 35 gone from
    between them. The first version of catch_up() stopped "as soon as
    a page contains an id we already have", so it stopped on page one
    and reported itself finished with 35 posts still missing.

    The laptop is off overnight and the page carries twenty at a time,
    so holes in the middle are the normal case, not the exception.
    """
    channel = Channel(newest=1000, total=300)
    feed.client = channel
    # We hold the newest and the oldest of the range, nothing between.
    for kept in (1000, 951):
        feed._store(feed.channels[0],
                    [{"id": str(kept), "at": "2026-07-31T15:29:00",
                      "text": "#GAIL - Good Results", "photos": [],
                      "hashtags": ["GAIL"]}])

    feed.catch_up()

    ids = set(_stored(feed))
    missing = set(range(951, 1001)) - ids
    assert not missing, (
        f"{len(missing)} posts inside the range were never recovered -- "
        f"a stop-on-first-overlap rule cannot fill a hole")


def test_it_stops_once_a_page_adds_nothing_new(feed):
    """The replacement rule. A page that stores nothing is the honest
    signal that we are into ground we already hold -- and it takes two
    such pages in a row, because one can happen on a quiet stretch."""
    channel = Channel(newest=1000, total=300)
    feed.client = channel
    # A solid block already held: 900 through 1000, no gaps.
    feed._store(feed.channels[0],
                [{"id": str(i), "at": "2026-07-31T15:00:00",
                  "text": "#GAIL - Good Results", "photos": [],
                  "hashtags": ["GAIL"]} for i in range(900, 1001)])
    before = len(channel.requests)
    feed.catch_up()
    walked = len(channel.requests) - before
    assert walked <= 8, (
        f"it walked {walked} pages over ground it already held")


def test_a_full_weekend_is_recovered(feed):
    """65 hours at 10 posts an hour is ~650. Twenty of those used to
    be all that arrived."""
    channel = Channel(newest=5000, total=1200)
    feed.client = channel
    feed._store(feed.channels[0],
                [{"id": "4350", "at": "2026-07-31T15:29:00",
                  "text": "#GAIL - Good Results", "photos": [],
                  "hashtags": ["GAIL"]}])

    feed.catch_up()

    ids = set(_stored(feed))
    missing = set(range(4351, 5001)) - ids
    assert not missing, f"{len(missing)} posts from the weekend were lost"


def test_the_walk_stops_at_the_retention_edge(feed):
    """A BREAKOUT FROM JUNE IS NOT A SIGNAL.

        "from now we need to capture as they are contemporary things.
         not a memory one. a fresh breakout is not valid after 1 week
         so do not get these old items into bot"

    And the code was worse than that: _prune() deletes anything older
    than keep_hours, so the walk was fetching months of history in
    order to store messages the same run then threw away.
    """
    from datetime import datetime, timedelta
    old = (datetime.now() - timedelta(days=30)).isoformat()
    new = datetime.now().isoformat()
    pages = [
        [{"id": str(i), "at": new, "text": "#GAIL - Good Results",
          "photos": [], "hashtags": ["GAIL"]} for i in (300, 299)],
        [{"id": str(i), "at": old, "text": "#GAIL - Good Results",
          "photos": [], "hashtags": ["GAIL"]} for i in (200, 199)],
        [{"id": str(i), "at": old, "text": "#GAIL - Good Results",
          "photos": [], "hashtags": ["GAIL"]} for i in (100, 99)],
    ]
    calls = {"n": 0}

    class Paged:
        def fetch(self, channel, limit=30, before=None):
            i = calls["n"]
            calls["n"] += 1
            return pages[i] if i < len(pages) else []

    feed.client = Paged()
    feed.catch_up()
    ids = set(_stored(feed))
    assert {300, 299} <= ids, "recent messages must be stored"
    assert not ({200, 199, 100, 99} & ids), (
        "messages past the retention window must not be fetched into "
        "the bot -- prune would delete them on the same run")


def test_an_undated_page_does_not_end_the_walk(feed):
    """Failing towards "keep walking" is right: an unreadable
    timestamp must not stop the walk early and leave a real gap."""
    from core.telegram_feed import _all_older_than
    assert _all_older_than([{"id": "1"}], 96) is False
    assert _all_older_than([], 96) is False


def test_it_asks_for_a_bounded_page_never_the_whole_history(feed):
    """ONE ARGUMENT, TWO READERS, TWO MEANINGS.

    This asked for limit=None, which the public web reader takes as
    "everything on this page" -- about twenty. The Telegram API reader
    takes it as "the entire channel history" and iterates without a
    limit.

    Measured 1 August 2026: Breakouts, Earnings 360 and Earnings Pro
    all stopped at exactly 30 messages -- the first poll's worth --
    because the walk that should have followed asked for ten thousand
    at once and never came back.
    """
    seen = []

    class Recorder:
        def fetch(self, channel, limit=30, before=None):
            seen.append(limit)
            return []

    feed.client = Recorder()
    feed.catch_up()
    assert seen, "it must ask for at least one page"
    assert all(isinstance(n, int) and 0 < n <= 500 for n in seen), (
        f"every page must be bounded, got {seen[:4]}")


def test_it_asks_for_older_pages_by_id(feed):
    channel = Channel(newest=1000, total=300)
    feed.client = channel
    feed._store(feed.channels[0],
                [{"id": "900", "at": "2026-07-31T15:29:00",
                  "text": "#GAIL - Good Results", "photos": [],
                  "hashtags": ["GAIL"]}])
    feed.catch_up()
    assert channel.requests[0] is None, "the first page is the newest"
    assert all(isinstance(b, int) for b in channel.requests[1:]), (
        "every later page must be requested with ?before=<id>")
    assert channel.requests[1:] == sorted(channel.requests[1:],
                                          reverse=True), (
        "it must walk strictly backwards")


# ---------------------------------------------------------------
# 2. IT IS BOUNDED
# ---------------------------------------------------------------
def test_an_empty_database_does_not_walk_the_whole_channel(feed):
    """First ever run. There is nothing to overlap with, so only the
    page cap stops it. A channel with 9,000 posts must not become
    9,000 posts of history and 450 requests at a stranger's server."""
    channel = Channel(newest=9000, total=9000)
    feed.client = channel
    feed.catch_up(max_pages=5)
    assert len(channel.requests) == 5
    assert len(_stored(feed)) == 100


def test_a_network_failure_keeps_what_was_already_read(feed):
    """Partial history is worth having. Losing the pages that DID
    arrive because a later one failed would be gratuitous."""
    channel = Channel(newest=1000, total=300)

    calls = {"n": 0}

    def flaky(handle, limit=None, before=None):
        calls["n"] += 1
        if calls["n"] > 2:
            raise RuntimeError("connection reset")
        return channel.fetch(handle, limit, before)

    feed.client = type("C", (), {"fetch": staticmethod(flaky)})()
    feed.catch_up()
    assert len(_stored(feed)) >= 20, (
        "the pages that arrived before the failure must be kept")


def test_catch_up_never_raises(feed):
    """It runs at startup. It must not be able to stop the bot."""
    class Broken:
        def fetch(self, *a, **k):
            raise RuntimeError("telegram is down")

    feed.client = Broken()
    assert feed.catch_up() == 0


# ---------------------------------------------------------------
# 3. RECOVERED MESSAGES ARE REAL MESSAGES
# ---------------------------------------------------------------
def test_recovered_messages_become_scored_events(tmp_path, feed):
    """The point of recovering them. A weekend result must arrive with
    its grade attached, not as raw text nobody reads."""
    from core.stock_events import StockEvents
    store = StockEvents(db_path=str(tmp_path / "events.db"))
    feed.stock_events = store
    feed.client = Channel(newest=1000, total=60)
    feed.catch_up(max_pages=2)

    conn = sqlite3.connect(store.db_path)
    graded = conn.execute(
        "select count(*) from events where kind='RESULT' "
        "and grade='GOOD'").fetchone()[0]
    conn.close()
    assert graded > 0, (
        "messages recovered from the gap must go through the same "
        "classifier as live ones")
