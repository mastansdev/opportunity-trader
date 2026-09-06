"""
==========================================================
Ctrl+C is answered in seconds, not at the end of a pass
==========================================================

    "py tools/collector.py is not closing in from 1st run. i tried to
     close ctrl+c .pls check"       -- operator, 3 August 2026

Nothing was hung. Nothing was listening either.

signal.signal() REPLACES the default handler, so Ctrl+C stopped raising
KeyboardInterrupt and only set a flag -- and the flag was read BETWEEN
passes. One pass is nine channels with OCR on every image. He pressed
Ctrl+C, the terminal did nothing visible for minutes, and there is no
way to tell a slow stop from a dead process.

Two fixes:

    * the flag is checked before every CHANNEL, not just between passes
    * a SECOND Ctrl+C leaves immediately, releasing the reader lock on
      the way out so the next run is not refused by a process that no
      longer exists

Author : H&M Opportunity Trader
==========================================================
"""

import os

import pytest

import tools.collector as collector
from core.runlock import LOCK_PATH, release_if_mine
from core.telegram_feed import TelegramFeed


class Client:
    """Counts how many channels were actually fetched."""

    def __init__(self):
        self.fetched = []

    def fetch(self, handle, limit=30):
        self.fetched.append(handle)
        return []


def feed_of(n=9):
    # ---- IT WAS WRITING INTO THE LIVE STORE. 6 September 2026. ----
    #
    # __new__ skips __init__, so this object never learned which file
    # to use -- and _note_attempt() falls back to the module default,
    # which is data/telegram.db, his real collected data. Every full
    # suite run bookmarked nine channels called c0..c8 in it, and his
    # dashboard listed them beside the ten real ones.
    #
    # Proved on 6 September: the store was cleaned, the suite was run,
    # and c0 through c8 were back before it finished.
    #
    # _store and _prune are stubbed below, so it was never the posts
    # that leaked -- only the bookmark row. One temp path closes it.
    import os
    import tempfile
    import threading

    feed = TelegramFeed.__new__(TelegramFeed)
    feed.db_path = os.path.join(tempfile.mkdtemp(), "tg.db")
    feed._lock = threading.Lock()
    feed.client = Client()
    feed.channels = [{"handle": "c%d" % i, "name": "c%d" % i}
                     for i in range(n)]
    feed._last_error = None
    feed._last_poll_at = None
    feed._store = lambda channel, messages: 0
    feed._prune = lambda: None
    return feed


# ---------------------------------------------------------------
# 1. A PASS CAN BE ABANDONED HALFWAY
# ---------------------------------------------------------------
def test_a_full_pass_walks_every_channel():
    feed = feed_of(9)
    feed.poll()
    assert len(feed.client.fetched) == 9


def test_it_stops_between_channels_when_asked():
    """One pass is nine channels with OCR. Checking the flag only
    between passes is what made Ctrl+C look ignored."""
    feed = feed_of(9)
    seen = {"n": 0}

    def stop():
        seen["n"] += 1
        return seen["n"] > 3          # let three channels through

    feed.poll(stop_check=stop)
    assert len(feed.client.fetched) == 3


def test_stopping_immediately_fetches_nothing():
    feed = feed_of(9)
    feed.poll(stop_check=lambda: True)
    assert feed.client.fetched == []


def test_no_stop_check_behaves_exactly_as_before():
    """The trading session's own feed passes nothing. It must not
    change."""
    feed = feed_of(4)
    assert feed.poll() == 0
    assert len(feed.client.fetched) == 4


def test_the_collector_passes_its_flag_in():
    src = open("tools/collector.py", encoding="utf-8").read()
    assert 'feed.poll(stop_check=lambda: _STOP["now"])' in src


# ---------------------------------------------------------------
# 2. THE SECOND CTRL+C LEAVES
# ---------------------------------------------------------------
def test_the_first_ctrl_c_asks_and_says_so(monkeypatch):
    monkeypatch.setattr(collector, "_STOP", {"now": False})
    said = []
    monkeypatch.setattr(collector, "decision", lambda msg="": said.append(msg))
    collector._stop_on_signal()
    assert collector._STOP["now"] is True
    assert any("again" in line for line in said), said


def test_the_second_ctrl_c_leaves_immediately(monkeypatch):
    """     "i tried to close ctrl+c"

    Waiting is a choice he should be able to withdraw."""
    monkeypatch.setattr(collector, "_STOP", {"now": True})
    monkeypatch.setattr(collector, "decision", lambda msg="": None)
    left = {}

    def fake_exit(code=130):
        left["code"] = code

    monkeypatch.setattr(collector, "_release_lock_and_exit", fake_exit)
    collector._stop_on_signal()
    assert left["code"] == 130


def test_it_uses_os_exit_not_sys_exit():
    """sys.exit raises inside the signal handler and unwinds back into
    the poll he is trying to escape from."""
    src = open("tools/collector.py", encoding="utf-8").read()
    block = src[src.index("def _release_lock_and_exit"):]
    block = block[:block.index("def build()")]
    # Code lines only. The comment above it explains WHY sys.exit is
    # wrong, and asserting on prose inside a docstring is a mistake this
    # project has made three times already.
    code = "\n".join(line for line in block.splitlines()
                     if not line.strip().startswith("#"))
    assert "os._exit(code)" in code
    assert "sys.exit" not in code


# ---------------------------------------------------------------
# 3. THE LOCK DOES NOT SURVIVE HIM
# ---------------------------------------------------------------
def test_a_forced_exit_releases_this_process_lock(tmp_path):
    """os._exit skips every `with` block, so the reader lock would
    outlive the process and the next run would be refused by a pid that
    is gone -- the same outage the self-detection bug caused, arriving
    by a different road."""
    path = str(tmp_path / "reader.lock")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("collector pid=%d (started 0 min ago)" % os.getpid())
    assert release_if_mine(path) is True
    assert not os.path.exists(path)


def test_it_never_removes_another_readers_lock(tmp_path):
    """A real second reader keeps its lock. Stealing it is how two
    readers end up sharing one Telethon session."""
    path = str(tmp_path / "reader.lock")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("collector pid=999999 (started 1 min ago)")
    assert release_if_mine(path) is False
    assert os.path.exists(path)


def test_a_missing_lock_is_not_an_error(tmp_path):
    assert release_if_mine(str(tmp_path / "nope.lock")) is False


def test_the_forced_exit_path_releases_before_leaving():
    src = open("tools/collector.py", encoding="utf-8").read()
    block = src[src.index("def _release_lock_and_exit"):]
    block = block[:block.index("def build()")]
    assert "release_if_mine()" in block
    assert block.index("release_if_mine()") < block.index("os._exit(code)")


# ---------------------------------------------------------------
# THE PRE-OPEN BOOK COLLECTS ITSELF
# ---------------------------------------------------------------
#     "IN MAIN.PY = ... PRE-OPEN SESSION UPDATE AT 09:10 AM EVERYDAY"
#                                     -- operator, 4 August 2026
#
# It was not happening. main.py builds PreOpen(fetcher=None) -- it only
# READS data/preopen.json -- and the only thing in this repo that ever
# wrote that file was tools/preopen_gaps.py, run by hand. So the PRE
# tab showed yesterday's auction, or nothing, on any morning it was
# forgotten. A stale pre-open looks exactly like a quiet one.
import tools.collector as collector


class _Clock:
    def __init__(self, *stamps):
        self._stamps = list(stamps)

    def now(self):
        return self._stamps.pop(0) if self._stamps else self._last

    @property
    def _last(self):
        return self._seen

    def __call__(self):
        return self.now()


def _run_watcher(monkeypatch, stamps, results):
    from datetime import datetime

    tried = []

    class Store:
        def refresh(self):
            tried.append(1)
            return results[len(tried) - 1] if len(tried) <= len(results) else 0

    monkeypatch.setattr("core.preopen.PreOpen", lambda **kw: Store())
    monkeypatch.setattr("core.nse_quotes.requests_fetcher", lambda: None)

    times = [datetime(*s) for s in stamps]

    class FakeDatetime:
        @staticmethod
        def now():
            return times.pop(0) if times else datetime(2026, 8, 5, 10, 0)

    monkeypatch.setattr(collector, "datetime", FakeDatetime)

    slices = []

    def fake_sleep(seconds):
        slices.append(seconds)
        return len(slices) >= len(stamps)

    monkeypatch.setattr(collector, "_sleep", fake_sleep)
    collector.preopen_watcher()
    return tried


def test_it_does_not_read_before_the_auction_has_matched(monkeypatch):
    """NSE's call auction runs 09:00-09:08 with matching to 09:12.
    Read earlier and the book is still forming."""
    tried = _run_watcher(monkeypatch,
                         [(2026, 8, 5, 9, 5), (2026, 8, 5, 9, 11)],
                         [342, 342])
    assert tried == []


def test_it_reads_once_the_auction_is_done(monkeypatch):
    tried = _run_watcher(monkeypatch, [(2026, 8, 5, 9, 12)], [342])
    assert len(tried) == 1


def test_it_does_not_read_again_after_the_open(monkeypatch):
    """Re-reading after 09:15 would overwrite the auction result with
    whatever the endpoint returns once regular trading has begun."""
    tried = _run_watcher(monkeypatch,
                         [(2026, 8, 5, 9, 16), (2026, 8, 5, 11, 0)],
                         [342, 342])
    assert tried == []


def test_an_empty_read_is_retried_not_written_off(monkeypatch):
    """The pre-open happens once a day. Losing it to one bad request
    would mean losing it for the session."""
    tried = _run_watcher(monkeypatch,
                         [(2026, 8, 5, 9, 12), (2026, 8, 5, 9, 13)],
                         [0, 342])
    assert len(tried) == 2


def test_a_good_read_is_not_repeated(monkeypatch):
    tried = _run_watcher(monkeypatch,
                         [(2026, 8, 5, 9, 12), (2026, 8, 5, 9, 13),
                          (2026, 8, 5, 9, 14)],
                         [342, 342, 342])
    assert len(tried) == 1


def test_it_runs_in_the_collector_never_in_main():
    """An HTTP call to NSE on a timer does not belong in the process
    that places orders."""
    assert "preopen_watcher" in open("tools/collector.py",
                                     encoding="utf-8").read()
    main_src = open("main.py", encoding="utf-8").read()
    assert "preopen_watcher" not in main_src
    assert "PreOpen(fetcher=None)" in main_src
