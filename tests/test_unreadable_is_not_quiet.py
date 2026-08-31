"""A channel that published nothing and one we could not reach.

    "if channel not posted then no error & if channel posted but bot
     struck at different time stamp then it must fetch after that time
     stamp data"                        -- operator, 31 August 2026

Those are different facts and the board showed them identically.

feed_watermark carries a column whose comment says exactly the right
thing -- "last_poll_ist: when we last LOOKED, even if empty" -- and
record() honours it: last_seen_ist is written only when something
arrived, last_poll_ist on every call.

But record() is called from _store(), and _store() only runs when
messages come back. So a look that found nothing and a look that
FAILED both left the column untouched. Read off the live store on
31 August, every single row:

    last_poll_ist == last_seen_ist

Earnings 360 read "quiet" while it had not been successfully read for
two days. It is a RESULTS channel: from 15 October it sits on the
90-second loop carrying the most time-critical thing the bot reads,
and it has no web fallback because it is private with no username. A
DNS blip in October would have shown as "quiet".
"""

import os
import tempfile

import pytest

from core import feed_clock


@pytest.fixture
def store(tmp_path):
    return str(tmp_path / "telegram.db")


def _row(store, channel):
    con = feed_clock._connect(store)
    try:
        con.row_factory = __import__("sqlite3").Row
        got = con.execute("select * from feed_watermark where channel = ?",
                          (channel,)).fetchone()
        return dict(got) if got else {}
    finally:
        con.close()


# ------------------------------------------------ the attempt is recorded

def test_a_read_that_worked_is_recorded(store):
    feed_clock.note_attempt("News Pulse", ok=True, db_path=store)
    got = _row(store, "News Pulse")
    assert got["last_try_ist"]
    assert got["last_error"] is None


def test_a_read_that_failed_keeps_the_reason(store):
    feed_clock.note_attempt("Earnings 360", ok=False,
                            error="the API failed (disconnected)",
                            db_path=store)
    got = _row(store, "Earnings 360")
    assert "disconnected" in got["last_error"]
    assert got["last_error_ist"]


def test_a_good_read_clears_the_error(store):
    feed_clock.note_attempt("Earnings 360", ok=False, error="boom",
                            db_path=store)
    feed_clock.note_attempt("Earnings 360", ok=True, db_path=store)
    assert _row(store, "Earnings 360")["last_error"] is None


def test_an_empty_read_does_not_claim_a_message_arrived(store):
    """The distinction the whole thing rests on: LOOKING is not
    RECEIVING. last_seen_ist must stay untouched."""
    feed_clock.note_attempt("News Pulse", ok=True, db_path=store)
    got = _row(store, "News Pulse")
    assert got["last_try_ist"] is not None
    assert got["last_seen_ist"] is None


def test_recording_an_arrival_still_works_beside_it(store):
    feed_clock.note_attempt("News Pulse", ok=True, db_path=store)
    feed_clock.record("News Pulse", at="2026-08-31T10:00:00+00:00",
                      message_id=42, db_path=store)
    got = _row(store, "News Pulse")
    assert got["last_seen_ist"] is not None
    assert got["last_msg_id"] == 42


def test_a_dict_is_refused_the_same_way_record_refuses_one(store):
    """10 August: the table grew rows keyed on "{'handle': ...". A
    bookmark that a caller's mistake can corrupt is not a bookmark."""
    feed_clock.note_attempt({"handle": "orders_pulse", "name": "OrderBook Pulse"},
                            ok=True, db_path=store)
    assert _row(store, "OrderBook Pulse")["last_try_ist"]
    assert _row(store, "{'handle'") == {}


def test_bookkeeping_never_raises(tmp_path):
    """A broken bookmark must not stop the collection it bookmarks."""
    assert feed_clock.note_attempt("X", ok=True,
                                   db_path=str(tmp_path / "no" / "x.db")) is False


# ------------------------------------------------------- what the board says

def _state(**over):
    from core.telegram_feed import TelegramFeed

    row = {"held": 10}
    row.update(over.pop("row", {}))
    return TelegramFeed._channel_state(
        over.pop("role", "daily"), over.pop("in_season", False), row,
        over.pop("late", 1), over.pop("last_post", None))


def test_a_failed_read_reads_unreadable():
    assert _state(row={"last_error": "the API failed"}) == "unreadable"


def test_it_outranks_off_season():
    """A results channel that cannot be read in October must not be
    excused as "off season" -- that is the month it matters."""
    assert _state(role="results", in_season=False,
                  row={"last_error": "boom"}) == "unreadable"


def test_a_channel_read_fine_with_nothing_new_is_not_an_error():
    """"if channel not posted then no error"."""
    from datetime import datetime, timedelta

    old = (datetime.now() - timedelta(hours=40)).isoformat()
    assert _state(row={"last_error": None}, last_post=old) == "quiet"


def test_the_report_carries_the_reason_to_the_screen():
    import inspect

    from core.telegram_feed import TelegramFeed

    src = inspect.getsource(TelegramFeed.channel_report)
    assert '"last_error"' in src and '"last_try"' in src


# --------------------------------- a private channel has no web page

def test_a_title_is_not_a_username():
    """folder_sources() takes a channel's USERNAME if it has one and
    falls back to its TITLE if it does not. Four of the ten came
    through as titles, which is how the bot learns they are private."""
    from core.telegram_client import _looks_like_a_username as ok

    for real in ("orders_pulse", "daytradertelugu", "WLPulseBot",
                 "news_pulse_ai", "@earnings_pulse"):
        assert ok(real) is True, real
    for title in ("Breakouts \U0001F1EE\U0001F1F3", "Business Pulse",
                  "Earnings 360", "Earnings Pro", "", None):
        assert ok(title) is False, title


def test_the_web_view_is_not_attempted_for_a_private_channel():
    """His terminal carried four of these every ninety seconds:

        [TELEGRAM] Breakouts: URL can't contain control characters.

    Roughly 160 warnings an hour over everything else."""
    from core.telegram_client import FallbackReader

    class DeadApi:
        def fetch(self, *a, **k):
            raise RuntimeError("Cannot send requests while disconnected")

    class Web:
        def fetch(self, *a, **k):
            raise AssertionError("the web view was attempted anyway")

    reader = FallbackReader(primary=DeadApi(), secondary=Web())
    assert reader.fetch("Earnings 360") == []


def test_it_is_said_once_not_every_pass():
    from core.telegram_client import FallbackReader

    class DeadApi:
        def fetch(self, *a, **k):
            raise RuntimeError("disconnected")

    class Web:
        def fetch(self, *a, **k):
            raise AssertionError("attempted")

    reader = FallbackReader(primary=DeadApi(), secondary=Web())
    for _ in range(5):
        reader.fetch("Earnings 360")
    assert reader._no_web_view == {"Earnings 360"}


def test_a_public_channel_still_falls_back():
    """The fallback exists for a reason and must keep working where a
    web page is actually possible."""
    from core.telegram_client import FallbackReader

    class DeadApi:
        def fetch(self, *a, **k):
            raise RuntimeError("disconnected")

    class Web:
        def fetch(self, *a, **k):
            return [{"id": 1, "text": "from the web view"}]

    reader = FallbackReader(primary=DeadApi(), secondary=Web())
    assert reader.fetch("orders_pulse")[0]["text"] == "from the web view"


# ------------------------------------------ a dropped connection revives

class _Client:
    """A telethon client that can be disconnected and reconnected."""

    def __init__(self, alive=True, revivable=True):
        self.alive = alive
        self.revivable = revivable
        self.connects = 0
        self.disconnects = 0

    def is_connected(self):
        return self.alive

    def connect(self):
        self.connects += 1
        if self.revivable:
            self.alive = True

    def disconnect(self):
        self.disconnects += 1
        self.alive = False


def _reader(client):
    from core.telegram_client import TelethonReader

    reader = TelethonReader.__new__(TelethonReader)
    reader._client = client
    reader.session = "x.session"
    # No credentials ON PURPOSE. When the cached client cannot be
    # revived, _connect() falls through to building a fresh one -- and
    # a real TelegramClient here would open a socket and leave asyncio
    # complaining on teardown. Missing credentials raise before that,
    # which is the branch these tests are about anyway.
    reader.api_id = None
    reader.api_hash = None
    return reader


def test_a_live_connection_is_reused():
    """Rebuilding a client on every call is what triggers Telegram's
    rate limits."""
    c = _Client(alive=True)
    assert _reader(c)._connect() is c
    assert c.connects == 0


def test_a_dropped_connection_is_revived_in_place():
    """10:47:04 -- the machine lost DNS, telethon dropped, and this
    returned the dead client on every call for five hours."""
    c = _Client(alive=False, revivable=True)
    assert _reader(c)._connect() is c
    assert c.connects == 1
    assert c.disconnects == 0, "a revivable client must not be thrown away"


def test_a_client_that_cannot_be_revived_is_discarded():
    c = _Client(alive=False, revivable=False)
    reader = _reader(c)
    with pytest.raises(Exception):
        reader._connect()          # falls through to building a new one
    assert c.disconnects == 1
    assert reader._client is None


def test_a_client_that_raises_on_check_is_discarded():
    class Broken(_Client):
        def is_connected(self):
            raise RuntimeError("socket gone")

    c = Broken(alive=False)
    reader = _reader(c)
    with pytest.raises(Exception):
        reader._connect()
    assert reader._client is None
