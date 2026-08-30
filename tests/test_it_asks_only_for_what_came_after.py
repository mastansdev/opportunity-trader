"""The collector stopped asking for the posts it had already read.

    "the only issue i observed is bot looking back on already stored
     info & re processing them, thats the reason i asked to maintain
     the time stamps on all channels. incase daytrader posted img at
     30/08/2026 07:20:05 & bot read it then laptop off . next day
     laptop on & collector must check from that channel after
     30/08/2026 07:20:06 not before that time right as before data is
     already received . & same for every channel"
                                        -- operator, 30 August 2026

He is describing work that was really being done twice, and the
expensive half of it was invisible.

WHAT IT USED TO DO. poll() asked Telegram for the last N posts and
walked them. Inside that walk, core/telegram_client.py downloads the
PHOTO BYTES of every message it walks -- before anything has decided
whether the message is new. Only afterwards did _store()'s id floor
skip the ones already on file. So a restart on a channel that is 77%
pictures (Day Trader Telugu) paid for a page of image downloads in
order to store nothing at all. The morning of 30 August shows it:

    OrderBook Pulse   page 1   100 read   0 new

A hundred read, none kept.

WHAT IT DOES NOW. The newest id already held for THAT channel goes to
Telegram as `min_id`, which is a server-side filter: only posts above
it are sent. The already-read picture never arrives, so there is
nothing to download and nothing to skip.

WHY THE ID AND NOT THE CLOCK. They are the same boundary -- ids rise
with time within a channel -- but the id is exact. A timestamp has to
be compared across his machine's clock and Telegram's, and two posts
inside the same second cannot be ordered by it. His 07:20:05 picture
has an id, and "after that id" cannot be off by a second.

WHAT IS DELIBERATELY UNCHANGED. catch_up() still walks BACKWARDS past
the newest id, because the hole it exists to fill sits BELOW that id.
tests/test_telegram_catchup.py already fails hard if that is taken
away ("630 posts from the weekend were lost"). Being off overnight
leaves no hole -- it leaves a boundary -- so the two are not in
conflict, and the tests below hold both.
"""

import pytest

from core.telegram_feed import TelegramFeed


class Recorder:
    """A client that records what it was asked for and returns nothing."""

    def __init__(self):
        self.asked = []

    def fetch(self, handle, limit=30, before=None, since_id=None):
        self.asked.append({"handle": handle, "limit": limit,
                           "before": before, "since_id": since_id})
        return []


@pytest.fixture
def feed(tmp_path):
    got = TelegramFeed(db_path=str(tmp_path / "tg.db"))
    got.channels = [
        {"handle": "daytradertelugu", "name": "Day Trader Telugu"},
        {"handle": "orders_pulse", "name": "OrderBook Pulse"},
    ]
    got.client = Recorder()
    return got


def _remember(feed, channel, message_id, at):
    """Store one post the way a real pass would."""
    feed._store(channel, [{"id": message_id, "at": at,
                           "text": "already read"}])


# ------------------------------------------------------ the boundary itself

def test_a_channel_it_has_never_read_is_asked_for_everything(feed):
    """The first run must not be limited by a mark that does not exist.

    An empty store means None, not zero: `min_id=0` would be a filter
    that happens to pass everything today and is a landmine the day
    somebody makes it a default.
    """
    feed.poll()
    assert [a["since_id"] for a in feed.client.asked] == [None, None]


def test_it_resumes_after_the_post_it_already_read(feed):
    """His example, in the code's own terms."""
    channel = feed.channels[0]
    _remember(feed, channel, 4021, "2026-08-30T07:20:05")

    feed.poll()
    asked = {a["handle"]: a["since_id"] for a in feed.client.asked}
    assert asked["daytradertelugu"] == 4021, (
        "the 07:20:05 picture was read, stored, and then asked for again")


def test_every_channel_carries_its_own_mark(feed):
    """"& same for every channel." A shared boundary would either
    re-read the busy channel or skip the quiet one."""
    _remember(feed, feed.channels[0], 4021, "2026-08-30T07:20:05")
    _remember(feed, feed.channels[1], 90210, "2026-08-30T09:14:58")

    feed.poll()
    asked = {a["handle"]: a["since_id"] for a in feed.client.asked}
    assert asked["daytradertelugu"] == 4021
    assert asked["orders_pulse"] == 90210


def test_the_mark_moves_as_new_posts_arrive(feed):
    """A mark that never advanced would re-read the same page forever."""
    channel = feed.channels[0]
    _remember(feed, channel, 4021, "2026-08-30T07:20:05")
    feed.poll()
    _remember(feed, channel, 4022, "2026-08-30T07:21:40")
    feed.poll()

    marks = [a["since_id"] for a in feed.client.asked
             if a["handle"] == "daytradertelugu"]
    assert marks == [4021, 4022]


# --------------------------------------------- what reaches Telegram itself

def test_the_reader_turns_it_into_a_server_side_filter():
    """min_id is the whole point. If this became client-side filtering
    the photo downloads would come back and the fix would be a lie."""
    import inspect

    from core import telegram_client

    body = inspect.getsource(telegram_client.TelethonReader.fetch)
    assert 'kwargs["min_id"] = int(since_id)' in body, (
        "since_id no longer reaches Telegram as min_id -- the page "
        "would be downloaded and discarded again")


def test_the_web_fallback_is_not_handed_an_argument_it_cannot_take():
    """The public view serves whole pages. Forwarding since_id there
    would raise TypeError and lose the channel completely -- worse
    than reading a page twice."""
    import inspect

    from core import telegram_client

    body = inspect.getsource(telegram_client.FallbackReader.fetch)
    tail = body.split("self.secondary.fetch")[-1]
    assert "since_id" not in tail


def test_an_older_reader_without_the_argument_still_works(feed):
    """A stub or an older client must degrade to the previous
    behaviour, not take the channel down."""

    class Older:
        def __init__(self):
            self.calls = 0

        def fetch(self, handle, limit=30, before=None):
            self.calls += 1
            return []

    feed.client = Older()
    _remember(feed, feed.channels[0], 4021, "2026-08-30T07:20:05")
    assert feed.poll() == 0
    assert feed.client.calls == 2


# ------------------------------------------------ and the hole still fills

def test_catch_up_still_walks_below_the_newest_id(feed):
    """The one place the boundary must NOT apply.

    Hold 1000-1050 from before a stop and 1100-1150 from after it, and
    the newest id is 1150. A min_id of 1150 would make the 1051-1099
    hole permanently unreachable -- and filling that hole is the only
    reason catch_up() exists.
    """
    import inspect

    body = inspect.getsource(TelegramFeed.catch_up)
    assert "since_id" not in body, (
        "catch_up() must not be bounded by the newest id -- the hole "
        "it fills sits below it")


# ------------------------------------- the two this change broke on the way

def test_a_dead_channel_still_does_not_cost_the_others(feed):
    """The retry must be NESTED inside the outer guard.

    Written first as a sibling `except TypeError:` clause, which reads
    the same and is not: an error raised from inside an except handler
    is not caught by the following clause, so the first unreachable
    channel ended the whole pass. tests/test_telegram_feed.py caught it.
    """

    class OneIsDown:
        def __init__(self):
            self.reached = []

        def fetch(self, handle, limit=30, before=None):
            # no since_id -- so the retry path is the one under test
            self.reached.append(handle)
            if handle == "daytradertelugu":
                raise RuntimeError("channel unreachable")
            return []

    feed.client = OneIsDown()
    feed.poll()
    assert "orders_pulse" in feed.client.reached, (
        "the dead channel took the rest of the pass down with it")


def test_a_reader_without_the_argument_is_not_called_a_failed_api():
    """"Does not take that argument" is not "the API is down".

    Passing since_id unconditionally made an older primary raise
    TypeError, which the fallback read as failure and answered by
    dropping to the public web view -- and a PRIVATE channel has none.
    Those channels would have gone quietly empty on Monday with the
    log blaming Telegram.
    """
    from core.telegram_client import FallbackReader

    class Older:
        def __init__(self):
            self.calls = 0

        def fetch(self, channel, limit=30, before=None):
            self.calls += 1
            return [{"id": 7, "text": "from the API"}]

    class Web:
        def fetch(self, channel, limit=30, before=None):
            raise AssertionError("fell back to the web view")

    primary = Older()
    got = FallbackReader(primary=primary, secondary=Web()).fetch(
        "earnings_pulse", limit=30, since_id=4021)
    assert got == [{"id": 7, "text": "from the API"}]
    # One, not two: Python raises the TypeError when it BINDS the
    # arguments, before the body runs -- so the rejected attempt
    # never reached the counter. What matters is that the data
    # came from the API and the web view was never asked.
