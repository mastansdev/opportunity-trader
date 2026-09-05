"""
==========================================================
Waiting forever for a picture
==========================================================

    "Telegram is having internal issues
     TimeoutError: Timeout while fetching data (caused by
     GetFileRequest)"
                                    -- operator, 1 August 2026

Telegram updated itself mid-run and its media servers stopped
answering. client.download_media() has no timeout: it drives the event
loop until the file arrives, and when the file never arrives the
catch-up sits on one image until somebody presses Ctrl+C.

    File "core/telegram_client.py", line 169, in fetch
        blob = client.download_media(message, file=bytes)
      ...
    KeyboardInterrupt

Three things were wrong and only one of them was Telegram's.

1. NO BOUND. The except-clause directly under that line could not
   help, because control never returned to it.

2. THE TEXT WAS LOST TOO. Every one of those messages had its text
   already in hand, and the text is most of the value -- a results
   card's grade, ticker and headline are all in the caption. Refusing
   to store any of it because a picture was slow is the wrong trade.

3. IT WOULD HAVE PAID THE COST FORTY TIMES. Forty pages, each
   stalling on the first image, is forty separate waits to learn the
   same fact about Telegram's mood.

So: a 25-second bound per image, and after three consecutive timeouts
on one channel the reader stops asking that channel for pictures and
carries on with text. Said once in the log, loudly, because a silent
degradation looks exactly like a quiet news day.

WHAT THIS IS NOT
----------------
It is not a retry, and it does not queue the missed images. Re-running
catch-up picks them up, and that is the operator's call to make, not a
background job's.

Author : H&M Opportunity Trader
==========================================================
"""

import asyncio

import pytest

from core.telegram_client import TelethonReader


class Loop:
    """Just enough of an asyncio loop for _photo_bytes to drive."""

    def __init__(self):
        self._loop = asyncio.new_event_loop()

    def is_running(self):
        return False

    def run_until_complete(self, coro):
        return self._loop.run_until_complete(coro)

    def close(self):
        self._loop.close()


class Client:
    """A Telethon client whose media server behaves as told."""

    def __init__(self, delay=0.0, blob=b"image-bytes"):
        self.delay = delay
        self.blob = blob
        self.calls = 0
        self.loop = Loop()

    def download_media(self, message, file=None):
        self.calls += 1

        async def fetch():
            await asyncio.sleep(self.delay)
            return self.blob

        return fetch()


@pytest.fixture
def reader():
    return TelethonReader(api_id="1", api_hash="x")


# ---------------------------------------------------------------
# 1. A HEALTHY DOWNLOAD IS UNCHANGED
# ---------------------------------------------------------------
def test_an_image_that_arrives_is_returned(reader):
    client = Client(delay=0.0)
    try:
        assert reader._photo_bytes(client, object(), 5.0) == b"image-bytes"
    finally:
        client.loop.close()


# ---------------------------------------------------------------
# 2. A STALLED ONE IS GIVEN UP ON
# ---------------------------------------------------------------
def test_a_stalled_download_raises_rather_than_hanging(reader):
    """THE REGRESSION THAT MATTERS. Unbounded, this test would never
    finish -- which is precisely what happened to the operator."""
    client = Client(delay=30.0)
    try:
        with pytest.raises((TimeoutError, asyncio.TimeoutError)):
            reader._photo_bytes(client, object(), 0.05)
    finally:
        client.loop.close()


def test_the_bound_is_measured_in_seconds_not_minutes():
    """25 seconds is already long for one picture during a session.
    A value in minutes would make the bound decorative."""
    assert 5.0 <= TelethonReader.PHOTO_TIMEOUT <= 60.0


def test_it_stops_asking_after_a_few_refusals():
    """Forty pages times one stall each is forty waits to learn the
    same thing about Telegram's mood."""
    assert 1 <= TelethonReader.PHOTO_GIVE_UP_AFTER <= 5


# ---------------------------------------------------------------
# 3. IT DEGRADES, IT DOES NOT REFUSE
# ---------------------------------------------------------------
def test_no_loop_falls_back_rather_than_refusing_to_read(reader):
    """The bound is an improvement, not a precondition. A Telethon
    build that exposes no loop must still read Telegram."""
    class NoLoop(Client):
        def __init__(self):
            super().__init__()
            self.loop = None

        def download_media(self, message, file=None):
            return b"image-bytes"

    assert reader._photo_bytes(NoLoop(), object(), 5.0) == b"image-bytes"


def test_the_timeout_is_configurable_per_reader():
    assert TelethonReader(api_id="1", api_hash="x",
                          photo_timeout=3).photo_timeout == 3.0
    assert TelethonReader(api_id="1", api_hash="x").photo_timeout == \
        TelethonReader.PHOTO_TIMEOUT


# ---------------------------------------------------------------
# 4. THE TEXT MUST SURVIVE THE PICTURE
# ---------------------------------------------------------------
def test_a_timeout_does_not_abandon_the_message_text():
    """A results card's grade, ticker and headline are all in the
    caption. Storing none of it because the image was slow throws
    away the part that was already in hand."""
    # ---- IT MOVED TO _shape(). 5 September 2026. ----
    # This read the body of fetch()'s loop. When Telegram was allowed
    # to PUSH posts as well as answer for them, the record-building was
    # lifted into _shape() so a pushed message and a fetched one build
    # the identical record. The counters moved onto the reader with it,
    # because "images are not being served right now" is true of the
    # connection and not of one call -- a pushed message hits the same
    # wall. The invariant this test protects is unchanged.
    src = open("core/telegram_client.py", encoding="utf-8").read()
    body = src[src.index("    def _shape(self, client, message, handle):"):]
    body = body[:body.index("\n    def ")] if "\n    def " in body else body
    assert "self._photo_bytes(" in body
    assert "self._photo_timeouts += 1" in body
    assert "self._photos_stalled = True" in body
    # No `continue` and no `raise` on the timeout path -- it has to
    # fall through to building the record.
    handler = body[body.index("except (TimeoutError"):]
    handler = handler[:handler.index("except Exception")]
    assert "continue" not in handler and "raise" not in handler
