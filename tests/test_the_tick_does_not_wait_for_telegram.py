"""The 1-second trading loop waited up to 70 seconds for a phone.

    "the alerts i'm getting in telegram? if yes no need delete them if
     they are causing lag"
    "yes, alerts off the trading thread first."
                                   -- the operator, 4 September 2026

The path, traced through the live code:

    Engine.process_tick()            the 1-second loop
      -> _try_structural_entry()                     engine.py:1037
        -> _manual_alert()                           engine.py:4031
          -> _push_alert()
            -> TelegramDesk.push()
              -> send() -> _call() -> urlopen(timeout=POLL_SECONDS+10)

POLL_SECONDS is 25, so the timeout is 35 seconds -- and send() tries
TWICE, because Telegram rejects a whole message with 400 when it
cannot parse the Markdown and the plain-text retry is what actually
gets the alert through. Seventy seconds, on the thread that decides
entries and runs the stops.

Engine._push_alert()'s own comment reads "A Telegram timeout must
never delay a tick". It wraps the call in try/except, which catches
ERRORS and does nothing whatever about SLOWNESS: a timeout is not an
error until the waiting is already over. The third comment found today
describing a protection that was intended and never built.

The alert now goes on a bounded queue and a daemon thread does the
waiting. The message still goes. The tick does not wait for it.
"""

import threading
import time

import pytest

import core.telegram_desk as td
from core.telegram_desk import TelegramDesk


@pytest.fixture
def desk():
    return TelegramDesk()


def test_without_a_worker_it_sends_inline_exactly_as_before(monkeypatch, desk):
    """Every test and tool that never starts a worker keeps the old
    shape -- nothing has to learn a new one to be tested."""
    sent = []
    monkeypatch.setattr(td, "send", lambda text, chat_id=None: sent.append(text))
    desk._deliver("hello")
    assert sent == ["hello"]


def test_with_a_worker_the_caller_does_not_wait(monkeypatch, desk):
    """THE fix. A send that takes two seconds must not cost the caller
    two seconds."""
    started = threading.Event()

    def _slow(text, chat_id=None):
        started.set()
        time.sleep(2.0)
        return True

    monkeypatch.setattr(td, "send", _slow)
    desk.start_sender()
    try:
        began = time.monotonic()
        desk._deliver("a slow one")
        took = time.monotonic() - began
        assert took < 0.5, (
            f"the caller waited {took:.2f}s for Telegram -- on the real "
            f"path that is Engine.process_tick()")
        assert started.wait(timeout=3.0), "the message never left at all"
    finally:
        desk._stop.set()


def test_the_message_actually_gets_sent(monkeypatch, desk):
    """Off-thread must not mean dropped on the floor."""
    got = []
    done = threading.Event()

    def _capture(text, chat_id=None):
        got.append(text)
        done.set()
        return True

    monkeypatch.setattr(td, "send", _capture)
    desk.start_sender()
    try:
        desk._deliver("it must arrive")
        assert done.wait(timeout=3.0)
        assert got == ["it must arrive"]
    finally:
        desk._stop.set()


def test_the_queue_is_bounded_so_a_dead_phone_cannot_grow_memory(desk):
    """An alert nobody could send an hour ago is not worth sending now
    -- it is already on the board and in the log."""
    desk.start_sender(depth=3)
    try:
        assert desk._outbox.maxsize == 3
    finally:
        desk._stop.set()


def test_starting_twice_does_not_make_two_threads(desk):
    desk.start_sender()
    try:
        first = desk._sender
        assert desk.start_sender() is first
    finally:
        desk._stop.set()


def test_an_empty_message_is_not_queued(desk):
    desk.start_sender()
    try:
        assert desk._deliver("") is False
        assert desk._outbox.empty()
    finally:
        desk._stop.set()


def test_main_starts_the_sender():
    """The audit's lesson, applied immediately: machinery nobody calls
    looks exactly like machinery that works."""
    import io
    body = io.open("main.py", encoding="utf-8").read()
    assert "telegram_desk.start_sender()" in body, (
        "main.py never starts the sender -- alerts would still be sent "
        "on the trading thread, and this fix would be decoration")
