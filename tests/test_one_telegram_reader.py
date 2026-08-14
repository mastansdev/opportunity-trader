"""
==========================================================
Two readers, one session, both damaged
==========================================================

    "shall i run this py tools/nightly.py now? in one terminal
     py tools/telegram_catchup.py --apply is running right now"
                                    -- operator, 2 August 2026

He asked before doing it, so nothing broke. tools/nightly.py opens
with the same telegram_catchup he already had running.

WHY IT MATTERS
--------------
Telethon keeps its session in a SQLite file and so does the message
store. Two processes writing both gives "database is locked" -- not
reliably and not immediately, so the failure shows up as a half-read
backlog and a session file that has to be regenerated, discovered at
08:45 on a trading morning.

WHAT THE GUARD DOES, AND DOES NOT DO
------------------------------------
It guards ONE thing: the Telegram reader. The other five nightly steps
overlap a catch-up perfectly safely, so nightly.py refuses at the TOP
and prints the --only line for those five rather than making him wait
for all of it.

A stale lock -- laptop closed mid-run, process killed -- is ignored by
age. A lock that outlives its process must never be able to stop work
happening; that turns a convenience into an outage.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import time

import pytest

from core.runlock import (LOCK_PATH, STALE_AFTER_SECONDS,
                          TelegramReaderLock, held_by_another)


@pytest.fixture
def lock_path(tmp_path):
    return str(tmp_path / "telegram_reader.lock")


# ---------------------------------------------------------------
# 1. THE LOCK ITSELF
# ---------------------------------------------------------------
def test_no_lock_means_free(lock_path):
    busy, _ = held_by_another(lock_path)
    assert busy is False


def test_a_live_lock_is_seen(lock_path):
    """---- THIS TEST ASSERTED THE BUG. 3 August 2026. ----

    It used to hold the lock in THIS process and assert busy is True:

        with TelegramReaderLock("telegram_catchup", path=lock_path):
            busy, who = held_by_another(lock_path)
            assert busy is True          # <- the self-block, pinned

    That is not "a live lock is seen", it is "a process refuses
    itself" -- and it is exactly what tools/telegram_catchup.py does,
    because the lock wraps the whole run and main() checks inside it.
    So the tool took the lock, found it, warned ALREADY RUNNING and
    exited; nightly logged "ok telegram 0.0 min"; and Monday opened
    with nothing read since Sunday 21:16.

    A green test made it invisible. The lock is meant to stop a SECOND
    reader, so the test has to involve a second one.
    """
    import os
    import time
    with open(lock_path, "w", encoding="utf-8") as handle:
        handle.write(f"telegram_catchup pid={os.getpid() + 9999} "
                     f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    busy, who = held_by_another(lock_path)
    assert busy is True
    assert "telegram_catchup" in who


def test_and_my_own_lock_is_not_a_second_reader(lock_path):
    """The other half, which was never asserted at all."""
    with TelegramReaderLock("telegram_catchup", path=lock_path):
        busy, who = held_by_another(lock_path)
    assert busy is False, f"blocked by its own lock: {who}"


def test_the_lock_is_released_on_a_clean_finish(lock_path):
    with TelegramReaderLock("x", path=lock_path):
        pass
    assert held_by_another(lock_path)[0] is False


def test_the_lock_is_released_when_the_run_crashes(lock_path):
    """A crash mid-catchup must not lock him out of tonight's run."""
    with pytest.raises(RuntimeError):
        with TelegramReaderLock("x", path=lock_path):
            raise RuntimeError("boom")
    assert held_by_another(lock_path)[0] is False


def test_a_stale_lock_is_ignored_rather_than_blocking(lock_path):
    """Laptop closed mid-run. A lock that outlives its process must
    never be able to stop work happening -- that turns a convenience
    into an outage."""
    with open(lock_path, "w") as handle:
        handle.write("telegram_catchup pid=999")
    old = time.time() - (STALE_AFTER_SECONDS + 60)
    os.utime(lock_path, (old, old))
    assert held_by_another(lock_path)[0] is False


def test_the_stale_window_is_longer_than_an_honest_run():
    """A weekend backlog is 40-60 minutes of real work. Anything
    shorter would call a running catch-up stale and let a second one
    start."""
    assert STALE_AFTER_SECONDS >= 90 * 60


def test_an_unreadable_lock_fails_open(tmp_path):
    """A filesystem oddity must not stop the night's work."""
    assert held_by_another(str(tmp_path / "nope" / "deep" / "x.lock"))[0] \
        is False


def test_a_failed_write_does_not_stop_the_reader(tmp_path):
    """The lock exists to stop a SECOND reader, not to become a third
    way the first one can fail.

    A missing parent directory is NOT the failure case -- it is created
    -- so this points the lock at a path that is already a directory,
    which no amount of makedirs can turn into a file."""
    bad = tmp_path / "iam_a_directory.lock"
    bad.mkdir()
    with TelegramReaderLock("x", path=str(bad)) as held:
        assert held.taken is False        # could not write, carried on
    assert bad.is_dir(), "and it did not delete anything on the way out"


# ---------------------------------------------------------------
# 2. BOTH TOOLS USE IT
# ---------------------------------------------------------------
def test_catchup_takes_the_lock_around_the_whole_run():
    """Taken at the entry point, so it is released on a clean finish,
    on Ctrl+C and on a crash alike."""
    src = open("tools/telegram_catchup.py", encoding="utf-8").read()
    assert 'with TelegramReaderLock("telegram_catchup"):' in src
    tail = src[src.find("if __name__"):]
    assert "TelegramReaderLock" in tail


def test_catchup_refuses_when_another_reader_is_running():
    src = open("tools/telegram_catchup.py", encoding="utf-8").read()
    block = src[src.find("def main(apply=False"):]
    block = block[:block.find("events = None")]
    assert "held_by_another()" in block
    assert "ALREADY RUNNING" in block
    assert "return" in block, "it must refuse, not carry on"


def test_nightly_checks_before_it_starts_anything():
    """Told at the top rather than discovered twenty seconds into the
    telegram step -- the answer changes what he does."""
    src = open("tools/nightly.py", encoding="utf-8").read()
    block = src[src.find("def main(argv)"):]
    block = block[:block.find("results = [run(step)")]
    assert "held_by_another()" in block
    assert block.find("held_by_another()") < block.find("return 2")


def test_nightly_offers_the_five_steps_that_are_safe_anyway():
    """There is no reason to make him wait for all of it -- history,
    discover, classify, verify and universe overlap a catch-up
    perfectly safely."""
    src = open("tools/nightly.py", encoding="utf-8").read()
    block = src[src.find("A Telegram reader is ALREADY RUNNING"):]
    block = block[:block.find("return 2")]
    assert '--only' in block
    assert 's[0] != "telegram"' in block


def test_only_the_telegram_step_is_gated():
    """--only history,universe must run even while a catch-up is
    going, because those two do not touch the Telegram session."""
    src = open("tools/nightly.py", encoding="utf-8").read()
    assert 'any(s[0] == "telegram" for s in steps)' in src
