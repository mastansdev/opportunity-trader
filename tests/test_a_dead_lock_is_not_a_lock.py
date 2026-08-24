"""A lock names a pid. Ask whether that pid is running.

Staleness was decided by FILE AGE alone -- two hours -- so a collector
killed at 15:34 locked the next one out until 17:31 with:

    ALREADY RUNNING: collector pid=18540 (started 4 min ago)

18540 had been dead for thirty seconds.
"""

import os

from core.runlock import _pid_alive


def test_a_dead_pid_does_not_hold_a_lock():
    # 1 is init on unix and never a python collector on Windows; use a
    # pid that certainly does not exist instead.
    dead = 999_999
    import psutil
    while psutil.pid_exists(dead):
        dead -= 1
    assert _pid_alive(f"collector pid={dead} 2026-08-24 15:31:08") is False


def test_a_live_pid_does_hold_it():
    assert _pid_alive(f"collector pid={os.getpid()} now") is True


def test_a_line_with_no_pid_is_assumed_held():
    # Fails CLOSED here on purpose: an unreadable owner must not be
    # taken as permission to start a second reader.
    assert _pid_alive("collector started") is True
    assert _pid_alive("") is True
    assert _pid_alive(None) is True


def test_the_age_rule_still_applies_when_psutil_is_gone(monkeypatch):
    # If the check cannot run, behaviour must be exactly what it was.
    import builtins
    real = builtins.__import__

    def no_psutil(name, *a, **k):
        if name == "psutil":
            raise ImportError("gone")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_psutil)
    assert _pid_alive("collector pid=999999 now") is True
