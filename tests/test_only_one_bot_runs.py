"""
==========================================================
Two bots on one Dhan account
==========================================================

    "i'm having 2 terminals only  1 - main.py & 2- py tools/collector.py"
                                -- operator, 13 August 2026

He had two terminals and THREE processes. A main.py started at 07:30
had outlived the window it was launched from and was still running an
hour later -- heartbeat, circuit monitor over 1,314 symbols, ranker
every few seconds. A second complete bot on his Dhan account, with no
window and no way to notice it. Closing a terminal on Windows does not
stop the process inside it.

main.py's own comment says why that is serious:

    both are wired to Dhan, so a manual BUY on the wrong tab is a
    second real order
    whichever exits LAST silently overwrites the other's book

WHY THE OLD GUARD MISSED IT
---------------------------
It asked "is anything listening on port 8000?". On Windows a second
socket can bind OVER a listening one -- the bind succeeds, the newer
process takes the port, and the probe that ran a moment earlier saw
nothing. The second bot then owned the dashboard he was watching while
the first traded invisibly.

A port also answers the wrong question. The dashboard can be down while
the engine runs, which is exactly the state the 07:30 process was in.

WHY NOT core/runlock.py
-----------------------
Its staleness rule is AGE -- two hours. Correct for a Telegram catch-up
that runs for minutes; wrong for a session that runs 09:15 to 15:30 and
holds the dashboard open afterwards. Age would call a healthy bot stale
mid-morning and wave a second one through.

Author : H&M Opportunity Trader
==========================================================
"""

import os
import pathlib

import pytest

from core import single_instance as si

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def lock(tmp_path):
    return str(tmp_path / "main_bot.lock")


def _write(path, text):
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


# ---------------------------------------------------------------
# THE DECISIVE QUESTION: is that pid alive, and is it this bot
# ---------------------------------------------------------------

def test_no_lock_means_free(lock):
    assert si.held_by_another(lock) == (False, "")


def test_a_live_bot_is_detected(lock, monkeypatch):
    """THE REGRESSION. The 07:30 process was alive and invisible."""
    monkeypatch.setattr(si, "_alive", lambda pid: True)
    monkeypatch.setattr(si, "_is_this_bot", lambda pid: True)
    _write(lock, "pid=12376 since=2026-08-13T07:30:05")
    busy, who = si.held_by_another(lock)
    assert busy is True
    assert "12376" in who


def test_a_dead_pid_does_not_block(lock, monkeypatch):
    """A crash leaves a lock behind. The next start must not be stuck
    behind a process that no longer exists -- this is the whole reason
    it checks liveness rather than age."""
    monkeypatch.setattr(si, "_alive", lambda pid: False)
    _write(lock, "pid=999999 since=2026-08-12T09:00:00")
    assert si.held_by_another(lock) == (False, "")


def test_a_recycled_pid_does_not_block(lock, monkeypatch):
    """Pids are reused. A stale lock naming 12376 must not stop a
    session because an unrelated program now holds that number."""
    monkeypatch.setattr(si, "_alive", lambda pid: True)
    monkeypatch.setattr(si, "_is_this_bot", lambda pid: False)
    _write(lock, "pid=12376 since=2026-08-13T07:30:05")
    assert si.held_by_another(lock) == (False, "")


def test_our_own_lock_never_blocks_us(lock):
    si.claim(lock)
    assert si.held_by_another(lock) == (False, "")


def test_an_unreadable_lock_does_not_stop_a_session(lock):
    _write(lock, "this is not a lock")
    assert si.held_by_another(lock) == (False, "")


# ---------------------------------------------------------------
# CLAIM AND RELEASE
# ---------------------------------------------------------------

def test_claim_records_this_process(lock):
    assert si.claim(lock) is True
    held = si.read(lock)
    assert held["pid"] == os.getpid()
    assert held["since"]


def test_release_only_removes_our_own(lock):
    _write(lock, "pid=12376 since=2026-08-13T07:30:05")
    assert si.release(lock) is False, (
        "released a lock belonging to another process -- that hands out "
        "permission this process does not have")
    assert os.path.exists(lock)

    si.claim(lock)
    assert si.release(lock) is True
    assert not os.path.exists(lock)


def test_a_lock_that_cannot_be_written_does_not_stop_the_session(tmp_path):
    """Best effort. The cost is that the NEXT start cannot see this
    one -- the behaviour before this module existed, never a refusal
    to start."""
    assert si.claim(str(tmp_path / "no" / "such" / "dir" / "x.lock")) in (
        True, False)


# ---------------------------------------------------------------
# UNKNOWN MUST REFUSE, NOT ALLOW
# ---------------------------------------------------------------

def test_an_unanswerable_liveness_check_reads_as_alive(monkeypatch):
    """Refusing costs one restart. Allowing costs a duplicated order on
    a real account."""
    import builtins

    real_import = builtins.__import__

    def _no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("no psutil")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", _no_psutil)
    monkeypatch.setattr(si.os, "kill",
                        lambda *a: (_ for _ in ()).throw(OSError("weird")))
    assert si._alive(4242) is True


# ---------------------------------------------------------------
# main.py must actually use it
# ---------------------------------------------------------------

def test_main_uses_the_pid_guard_not_the_port_probe():
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "single_instance.held_by_another()" in code, (
        "main.py no longer checks for a second bot by pid")
    assert "single_instance.claim()" in code, (
        "main.py does not record itself, so the NEXT start cannot see it")
    assert "if _another_bot_is_already_running():" not in code, (
        "the port probe is back on the startup path -- on Windows a "
        "second socket binds over a listening one and it sees nothing")


def test_main_releases_the_lock_on_a_clean_shutdown():
    src = (ROOT / "main.py").read_text(encoding="utf-8", errors="replace")
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    assert "single_instance.release()" in code


def test_the_lock_is_not_committed():
    import subprocess
    done = subprocess.run(["git", "check-ignore", "data/main_bot.lock"],
                          cwd=str(ROOT), capture_output=True, text=True)
    assert done.returncode == 0, (
        "data/main_bot.lock is not gitignored -- a machine-local pid "
        "would be committed and would then be wrong on every other "
        "machine")


# ---------------------------------------------------------------
# THE SUITE MUST NOT BE ABLE TO LOCK HIM OUT
# ---------------------------------------------------------------
#
# 14 August 2026. A test booted a real bot (see tests/
# test_single_instance.py) and claim() stamped pytest's own pid into
# data/main_bot.lock:
#
#     pid=7436 since=2026-08-14T07:39:03 argv=__main__.py
#
# For as long as that run lived, `py main.py` in his other terminal
# would have refused to start and told him another bot was already
# running. tests/conftest.py now redirects the lock into tmp_path for
# every test in the directory.

def test_the_suite_cannot_write_the_real_lock(tmp_path):
    """The redirect has to BITE, not just be present.

    core/single_instance.py takes path=None and resolves LOCK_PATH per
    call for exactly this reason -- with path=LOCK_PATH as a default
    argument the value is bound at import, monkeypatching the module
    attribute changes nothing, and this test would pass while claim()
    went on writing data/main_bot.lock.
    """
    assert si.LOCK_PATH != os.path.join("data", "main_bot.lock"), (
        "conftest is not redirecting the lock for this test")

    real = ROOT / "data" / "main_bot.lock"
    before = real.read_bytes() if real.exists() else None

    assert si.claim() is True
    assert pathlib.Path(si.LOCK_PATH).exists(), (
        "claim() reported success but wrote nothing where it was sent")

    after = real.read_bytes() if real.exists() else None
    assert before == after, (
        "claim() wrote the REAL data/main_bot.lock during a test run. "
        "While the suite runs, his own main.py would refuse to start.")


def test_read_and_release_follow_the_redirect_too(tmp_path):
    """claim() is not the only one. A release() that resolved the real
    path could delete a running bot's lock and wave a second one in."""
    real = ROOT / "data" / "main_bot.lock"
    before = real.read_bytes() if real.exists() else None

    si.claim()
    held = si.read()
    assert held is not None and held["pid"] == os.getpid()
    assert si.release() is True
    assert not pathlib.Path(si.LOCK_PATH).exists()

    after = real.read_bytes() if real.exists() else None
    assert before == after, "release() reached the real lock file"
