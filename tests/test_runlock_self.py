"""
==========================================================
A process is not another process
==========================================================

    "but just now i opened laptop & started runs. only 1 terminal
     using, why it gets locked?"
                                    -- operator, 3 August 2026, 06:31

He was right, and the lock had been eating every Telegram read since
it shipped the previous evening.

tools/telegram_catchup.py takes the lock in __main__ and then calls
main(), and main() asks held_by_another() -- which found the lock the
same process had written one line earlier:

    with TelegramReaderLock("telegram_catchup"):   # writes the lock
        main(apply=...)                            # reads it back

    WARNING:  ALREADY RUNNING: telegram_catchup pid=30928
              2026-08-03 06:33:43 (started 0 min ago)

Same pid. Same second. Every single run.

WHAT IT COST
------------
tools/nightly.py runs that tool as step one and reports the exit code.
The tool exited 0, so the night logged:

    ok  telegram  0.0 min

and moved on to five more steps that all worked. Monday morning opened
with telegram.db exactly as it had been at 21:16 on Sunday -- no
overnight concall briefs, no Monday cards -- and the summary said the
step was fine.

    "A lock that outlives its process must never be able to stop work
     happening; that turns a convenience into an outage."
                            -- core/runlock.py, its own docstring

It was not a stale lock that did it. It was a live one, owned by the
process it blocked, and the docstring's rule applies just the same.

WHY THE PID AND NOT SOMETHING CLEVERER
--------------------------------------
The lock already writes "who pid=NNNN timestamp". Checking whether that
pid is os.getpid() costs one regex and cannot be wrong: a process
always knows its own id. Anything unparseable is treated as SOMEBODY
ELSE'S -- two readers corrupt a Telethon session, and one false minute
of waiting costs nothing.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import time

import pytest

from core.runlock import (STALE_AFTER_SECONDS, TelegramReaderLock,
                          held_by_another)


@pytest.fixture
def lock_path(tmp_path):
    return str(tmp_path / "telegram_reader.lock")


def _write(path, text, age_seconds=0):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    if age_seconds:
        old = time.time() - age_seconds
        os.utime(path, (old, old))


# ---------------------------------------------------------------
# 1. THE BUG
# ---------------------------------------------------------------
def test_a_process_does_not_block_itself(lock_path):
    """The exact shape of the failure: take the lock, then ask."""
    with TelegramReaderLock("telegram_catchup", path=lock_path):
        busy, who = held_by_another(lock_path)
    assert busy is False, f"blocked by its own lock: {who}"


def test_the_real_tool_order_is_take_then_check(lock_path):
    """tools/telegram_catchup.py does exactly this, and it must work --
    the lock has to wrap the whole run so it is released on Ctrl+C and
    on a crash alike, which means it is taken BEFORE main() runs."""
    seen = {}

    def main_body():
        seen["busy"], seen["who"] = held_by_another(lock_path)

    with TelegramReaderLock("telegram_catchup", path=lock_path):
        main_body()
    assert seen["busy"] is False, seen["who"]


# ---------------------------------------------------------------
# 2. WHAT MUST STILL BE REFUSED
# ---------------------------------------------------------------
def test_a_genuinely_different_process_is_still_refused(lock_path):
    """The reason the lock exists. Two readers share one Telethon
    session and one store, and both end up damaged."""
    # A LIVE other process. core/runlock.py now checks whether the pid
    # in the lock is still running, so `os.getpid() + 9999` -- a pid
    # that never existed -- is no longer a second reader. It became a
    # real one rather than the check being weakened: the two-hour
    # age-only rule locked a restarted collector out for two hours.
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, "-c",
                              "import time; time.sleep(60)"])
    try:
        _write(lock_path, f"telegram_catchup pid={child.pid} "
                          f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
        busy, who = held_by_another(lock_path)
    finally:
        child.kill()
        child.wait(timeout=10)
    assert busy is True
    assert "pid=" in who


def test_a_lock_whose_owner_has_died_is_released(lock_path):
    """The other half of the same rule, 24 August 2026.

    "ALREADY RUNNING: collector pid=18540 (started 4 min ago)" was
    printed thirty seconds after 18540 was killed.
    """
    import subprocess
    import sys
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    child.wait(timeout=10)
    _write(lock_path, f"collector pid={child.pid} "
                      f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
    busy, _ = held_by_another(lock_path)
    assert busy is False


def test_a_lock_with_no_pid_is_somebody_elses(lock_path):
    """Unattributable means refuse. Two readers corrupt a session; one
    false minute of waiting costs nothing."""
    _write(lock_path, "telegram_catchup 2026-08-03 06:33:43")
    busy, _who = held_by_another(lock_path)
    assert busy is True


def test_a_pid_that_is_not_a_number_is_somebody_elses(lock_path):
    _write(lock_path, "telegram_catchup pid=notanumber")
    busy, _who = held_by_another(lock_path)
    assert busy is True


# ---------------------------------------------------------------
# 3. WHAT MUST NOT CHANGE
# ---------------------------------------------------------------
def test_no_lock_means_free(lock_path):
    busy, who = held_by_another(lock_path)
    assert busy is False and who == ""


def test_a_stale_lock_never_blocks_the_night(lock_path):
    """Even one carrying a DIFFERENT pid. A killed process must not be
    able to stop tomorrow's run."""
    _write(lock_path, f"telegram_catchup pid={os.getpid() + 9999}",
           age_seconds=STALE_AFTER_SECONDS + 60)
    busy, _who = held_by_another(lock_path)
    assert busy is False


def test_the_lock_is_removed_on_a_clean_exit(lock_path):
    with TelegramReaderLock("telegram_catchup", path=lock_path):
        assert os.path.exists(lock_path)
    assert not os.path.exists(lock_path)


def test_the_lock_is_removed_when_the_run_raises(lock_path):
    """It wraps the whole run precisely so Ctrl+C and a crash release
    it. If they did not, the next run would wait two hours."""
    with pytest.raises(KeyboardInterrupt):
        with TelegramReaderLock("telegram_catchup", path=lock_path):
            raise KeyboardInterrupt
    assert not os.path.exists(lock_path)


def test_the_lock_records_its_own_pid(lock_path):
    """Everything above depends on the owner being written down."""
    with TelegramReaderLock("telegram_catchup", path=lock_path):
        text = open(lock_path, encoding="utf-8").read()
    assert f"pid={os.getpid()}" in text
    assert "telegram_catchup" in text


# ---------------------------------------------------------------
# 4. THE SILENT SUCCESS THAT HID IT
# ---------------------------------------------------------------
def test_a_refusal_to_read_is_not_a_successful_step():
    """     "ok  telegram  0.0 min"

    nightly.py read the exit code and called it fine. The tool returns
    after warning, so the night reported success for a step that read
    nothing -- and the Monday it exists to prepare opened blind.

    The lock refusal must not leave through the same door as a good
    run.
    """
    src = open("tools/telegram_catchup.py", encoding="utf-8").read()
    block = src[src.find("busy, who = held_by_another()"):]
    block = block[:block.find("events = None")]
    assert "ALREADY RUNNING" in block
    assert "sys.exit(" in block, (
        "a refusal must exit non-zero, or tools/nightly.py records it "
        "as 'ok telegram 0.0 min' and moves on -- which is exactly how "
        "this went unnoticed for a whole night")
