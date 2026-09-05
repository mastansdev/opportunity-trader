"""
==========================================================
The posts that were published while the laptop was off
==========================================================

    "for me all info must be tagged properly & never mis ,
     duplicate , thats it"
                                -- the operator, 5 September 2026

Counted on data/telegram.db that morning: 183 posts published to his
channels and never collected. They were not scattered noise. Every long
run of them was a weekend:

    RedboxGlobal India   76 missing   29 Aug 11:04 -> 31 Aug 18:07
    Earnings 360         10 missing   26 Aug 07:56 -> 27 Aug 07:10
    Earnings Pro          9 missing   26 Aug 07:35 -> 27 Aug 07:10
    Earnings Pulse        7 missing   26 Aug 03:38 -> 27 Aug 10:08

catch_up() had run on every one of those days and reported itself
finished. It walks BACKWARDS a page at a time and stops after two pages
that add nothing new -- which closes a gap at the EDGE of what is held,
and cannot close one in the MIDDLE, because the pages either side of a
weekend hole are ground already held. Four weeks of a walk declaring
success with 183 posts still missing.

A page walk is the wrong question. The store can answer the right one
exactly: it holds 3711 and 3788 and nothing between, so it asks for
3712..3787 BY NAME. Telegram answers up to a hundred ids in one request
and walks past nothing.

WHAT THIS FILE PINS DOWN

  1. a hole in the middle of a range is found, not just one at the end
  2. a post already on file is never asked for
  3. holes older than the retention window are left alone -- fetching a
     post that the same run's _prune() deletes is work done to throw away
  4. an id that never arrives is asked for three times and then dropped,
     because Telegram numbers SERVICE posts in the same sequence and
     asking for them for ever is the traffic pattern that gets a reader
     rate-limited
  5. a hole this channel could not have published is not a hole -- see
     the WLPulseBot case below
  6. the reader refuses to approximate: the public web view serves pages
     and cannot answer "give me post 3741", so it returns nothing rather
     than a page nobody asked for

THE WLPulseBot CASE, which is (5)

    RedboxGlobal India   76 ids over 55 hours   346 posts on file
    WLPulseBot           57 ids over 33 hours     3 posts on file

The first is a weekend on a channel that publishes ~43 posts a day. The
second is a BOT, whose ids belong to a shared conversation that has
nothing to do with this feed -- it has published three things in three
days. Each channel is therefore measured against ITSELF, never against
the others: Day Trader Telugu posts ninety a day and Earnings Pulse
three, and one number for both would be wrong for both.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import sqlite3
import tempfile
from datetime import datetime, timedelta, timezone

import pytest

from core.telegram_feed import TelegramFeed


def _iso(hours_ago):
    return (datetime.now(timezone.utc)
            - timedelta(hours=hours_ago)).isoformat()


class FakeReader:
    """Answers by id, and remembers what it was asked."""

    def __init__(self, published=None, missing=()):
        # {id: text} for posts that still exist on the channel
        self.published = published or {}
        self.missing = set(missing)
        self.asked = []

    def fetch(self, channel, limit=30, before=None, since_id=None, ids=None):
        if ids is None:
            return []
        self.asked.append(list(ids))
        out = []
        for mid in ids:
            if mid in self.missing or mid not in self.published:
                continue
            out.append({
                "id": mid,
                "at": datetime.now(timezone.utc),
                "text": self.published[mid],
                "photos": [],
                "photo_data": [],
                "links": [],
                "hashtags": [],
                "url": f"https://t.me/x/{mid}",
            })
        return out


@pytest.fixture()
def feed():
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path, channels=[{"name": "Chan",
                                              "handle": "chan"}])
    yield f


def _seed(feed, rows):
    """rows = [(message_id, hours_ago)]"""
    conn = sqlite3.connect(feed.db_path)
    for mid, hours in rows:
        conn.execute(
            "INSERT OR REPLACE INTO messages "
            "(channel, message_id, at, text, seen_at) VALUES (?,?,?,?,?)",
            ("Chan", str(mid), _iso(hours), f"post {mid}",
             datetime.now().isoformat()))
    conn.commit()
    conn.close()


# ------------------------------------------------------------------
# 1. the hole in the middle
# ------------------------------------------------------------------

def test_a_hole_in_the_middle_of_the_range_is_found():
    """The shape catch_up() cannot close: held on both sides."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path, channels=[{"name": "Chan",
                                              "handle": "chan"}])
    # A weekend: posted steadily, then a hole, then steadily again.
    _seed(f, [(100, 40), (101, 39), (102, 38), (103, 37), (104, 36),
              # 105..112 never collected -- the laptop was off
              (113, 20), (114, 19), (115, 18), (116, 17), (117, 16)])
    missing = f.missing_ids("Chan")
    assert missing == [105, 106, 107, 108, 109, 110, 111, 112], missing


def test_a_post_already_on_file_is_never_asked_for():
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path, channels=[{"name": "Chan",
                                              "handle": "chan"}])
    _seed(f, [(100, 40), (101, 39), (102, 38), (103, 37), (104, 36),
              (113, 20), (114, 19), (115, 18)])
    held = {100, 101, 102, 103, 104, 113, 114, 115}
    assert not (set(f.missing_ids("Chan")) & held)


# ------------------------------------------------------------------
# 3. the retention edge
# ------------------------------------------------------------------

def test_a_hole_older_than_the_window_is_left_alone():
    """_prune() keeps keep_hours. Fetching a post the same run deletes
    is work done to throw away."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path, keep_hours=96,
                     channels=[{"name": "Chan", "handle": "chan"}])
    # The hole's older edge is 200 hours back -- past the window.
    _seed(f, [(100, 210), (101, 205), (102, 200),
              # 103..108 missing, but too old to matter
              (109, 190), (110, 185),
              # and a recent stretch with a hole of its own
              (200, 10), (201, 9), (202, 8),
              # 203 missing, inside the window
              (204, 6), (205, 5)])
    missing = f.missing_ids("Chan")
    assert 203 in missing
    assert not [m for m in missing if 103 <= m <= 108], missing


# ------------------------------------------------------------------
# 4. three tries and then quiet
# ------------------------------------------------------------------

def test_an_id_that_never_arrives_is_dropped_after_three_tries():
    """Telegram numbers service posts -- joins, pins, a changed channel
    photo -- in the same sequence, and the reader skips anything with no
    text and no picture. Those ids can never be stored. Asking for them
    on every run for ever is the traffic pattern that gets a reader
    rate-limited."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path,
                     channels=[{"name": "Chan", "handle": "chan"}])
    _seed(f, [(100, 40), (101, 39), (102, 38), (103, 37), (104, 36),
              (108, 20), (109, 19), (110, 18)])
    # 105, 106, 107 are service messages: they will never come back.
    reader = FakeReader(published={}, missing={105, 106, 107})
    f.client = reader

    for _ in range(3):
        f.fill_gaps()
    assert reader.asked, "it never asked at all"
    asked_first = reader.asked[0]
    assert set(asked_first) == {105, 106, 107}

    before = len(reader.asked)
    f.fill_gaps()
    assert len(reader.asked) == before, \
        "asked a fourth time -- it must go quiet after three"


def test_a_post_that_does_arrive_is_stored():
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path,
                     channels=[{"name": "Chan", "handle": "chan"}])
    _seed(f, [(100, 40), (101, 39), (102, 38), (103, 37), (104, 36),
              (108, 20), (109, 19), (110, 18)])
    f.client = FakeReader(published={105: "ACME wins Rs 900 crore order",
                                     106: "second one", 107: "third"})
    assert f.fill_gaps() == 3
    assert f.missing_ids("Chan") == []


# ------------------------------------------------------------------
# 5. a hole this channel could not have published
# ------------------------------------------------------------------

def test_a_bots_id_space_is_not_a_gap_in_this_channel():
    """@WLPulseBot: three posts in three days, and 57 ids 'missing' in
    thirty-three hours. Those numbers were never this channel's."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path,
                     channels=[{"name": "Chan", "handle": "chan"}])
    _seed(f, [(17263, 80), (17321, 47), (17379, 14)])
    assert f.missing_ids("Chan") == []


def test_a_busy_channels_weekend_is_still_a_gap():
    """The same guard must NOT refuse the real case. RedboxGlobal India
    publishes ~43 posts a day; 76 missing over a weekend fits."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path, keep_hours=24 * 14,
                     channels=[{"name": "Chan", "handle": "chan"}])
    rows = []
    mid = 3000
    # Eight days of steady posting, about two an hour, ending 116 hours
    # ago -- Saturday lunchtime.
    for hour in range(300, 115, -1):
        for _ in range(2):
            rows.append((mid, hour))
            mid += 1
    # Then the laptop is off. 76 posts published into the silence, and
    # the channel is heard from again 55 hours later, Monday evening.
    hole_from = mid
    mid += 76
    for hour in range(61, 5, -1):
        rows.append((mid, hour))
        mid += 1
    _seed(f, rows)
    missing = f.missing_ids("Chan", cap=500)
    assert len(missing) == 76, len(missing)
    assert missing[0] == hole_from


# ------------------------------------------------------------------
# 6. the reader refuses to approximate
# ------------------------------------------------------------------

def test_the_web_view_returns_nothing_rather_than_a_page():
    """t.me/s/<channel> serves pages. There is no way to ask it for post
    3741 and nothing else, so it must not answer with a page -- that is
    the opposite of asking for exactly what is missing."""
    from core.telegram_web import TelegramWebReader
    assert TelegramWebReader().fetch("anything", ids=[1, 2, 3]) == []


def test_a_reader_without_the_argument_leaves_the_hole_open():
    """A stub or an older reader. Losing the fill is fine; guessing at
    it with a page is not."""
    path = os.path.join(tempfile.mkdtemp(), "telegram.db")
    f = TelegramFeed(db_path=path,
                     channels=[{"name": "Chan", "handle": "chan"}])
    _seed(f, [(100, 40), (101, 39), (102, 38), (103, 37), (104, 36),
              (108, 20), (109, 19), (110, 18)])

    class OldReader:
        def __init__(self):
            self.pages = 0

        def fetch(self, channel, limit=30, before=None, since_id=None):
            self.pages += 1
            return [{"id": 999, "at": datetime.now(timezone.utc),
                     "text": "a page nobody asked for", "photos": [],
                     "photo_data": [], "links": [], "hashtags": [],
                     "url": "x"}]

    old = OldReader()
    f.client = old
    assert f.fill_gaps() == 0
    conn = sqlite3.connect(f.db_path)
    got = conn.execute("SELECT COUNT(*) FROM messages "
                       "WHERE message_id = '999'").fetchone()[0]
    conn.close()
    assert got == 0, "stored a page it never asked for"


# ------------------------------------------------------------------
# and the wiring
# ------------------------------------------------------------------

def test_the_collector_actually_calls_it():
    """The recurring fault in this codebase is machinery that exists and
    is never called -- trading_gate, surge(), MOVE_DIED, refused_symbols.
    This one is called."""
    import io
    src = io.open("tools/collector.py", encoding="utf-8").read()
    assert "feed.fill_gaps()" in src
    assert src.index("feed.catch_up()") < src.index("feed.fill_gaps()"), \
        "the walk brings in what is new; this is only for what it stepped over"


def test_named_posts_never_travel_with_a_page_request():
    """`ids` and `limit`/`offset_id`/`min_id` are different questions.
    Mixing them silently returns something other than what was asked."""
    import io
    src = io.open("core/telegram_client.py", encoding="utf-8").read()
    assert 'if ids:\n            kwargs = {"ids":' in src
    assert "if before and not ids:" in src
    assert "if since_id and not ids:" in src
